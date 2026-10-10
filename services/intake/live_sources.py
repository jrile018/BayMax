"""Bounded, provider-specific official hazard candidates. No shared-state writes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import math
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPHandler, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError


class SourceError(ValueError):
    """Source bytes or provider fields failed a bounded structural gate."""


@dataclass(frozen=True)
class SourcePolicy:
    source_id: str
    allowed_urls: tuple[str, ...]
    max_bytes: int = 1_000_000
    max_records: int = 200
    timeout_s: float = 5.0
    max_redirects: int = 2
    min_interval_s: int = 60

    def __post_init__(self):
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise SourceError("source_id required")
        if not isinstance(self.allowed_urls, tuple) or not self.allowed_urls:
            raise SourceError("exact URL allowlist required")
        if self.source_id not in ("nws", "usgs"):
            raise SourceError("unregistered official provider")
        for url in self.allowed_urls:
            _https_url(url)
            parts = urlsplit(url)
            if self.source_id == "nws":
                active_area = (parts.path == "/alerts/active"
                               and re.fullmatch(r"area=[A-Z]{2}", parts.query) is not None)
                filtered_alerts = (parts.path == "/alerts"
                                   and re.fullmatch(r"active=true&area=[A-Z]{2}", parts.query) is not None)
                if parts.netloc != "api.weather.gov" or not (active_area or filtered_alerts):
                    raise SourceError("NWS URL outside registered active-alert area shape")
            elif (parts.netloc != "earthquake.usgs.gov"
                  or parts.path != "/earthquakes/feed/v1.0/summary/all_hour.geojson"
                  or parts.query):
                raise SourceError("USGS URL outside registered hourly GeoJSON feed")
        if len(set(self.allowed_urls)) != len(self.allowed_urls):
            raise SourceError("duplicate allowed URL")
        if type(self.max_bytes) is not int or not 1 <= self.max_bytes <= 5_000_000:
            raise SourceError("invalid byte cap")
        if type(self.max_records) is not int or not 1 <= self.max_records <= 1000:
            raise SourceError("invalid record cap")
        if type(self.max_redirects) is not int or not 0 <= self.max_redirects <= 3:
            raise SourceError("invalid redirect cap")
        if type(self.min_interval_s) is not int or not 0 <= self.min_interval_s <= 3600:
            raise SourceError("invalid poll interval")
        if isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float)) or not 0 < self.timeout_s <= 30 or not math.isfinite(self.timeout_s):
            raise SourceError("invalid timeout")


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str


@dataclass(frozen=True)
class RawDocument:
    source_id: str
    request_url: str
    final_url: str
    status: int
    headers: tuple[tuple[str, str], ...]
    fetched_at: str
    raw: bytes
    sha256: str


@dataclass(frozen=True)
class Refresh:
    state: str
    last_good: RawDocument | None
    error: str | None


def _https_url(url):
    if not isinstance(url, str):
        raise SourceError("URL must be text")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127
           for char in url):
        raise SourceError("source URL contains whitespace or control characters")
    try:
        p = urlsplit(url)
        forbidden = p.username or p.password or p.fragment or p.port
    except ValueError as exc:
        raise SourceError("malformed source URL") from exc
    if p.scheme != "https" or not p.hostname or forbidden:
        raise SourceError("source URL must be canonical HTTPS with no credentials, port or fragment")
    if p.hostname != p.hostname.lower() or not p.path.startswith("/"):
        raise SourceError("noncanonical source URL")
    return url


def _header(headers, name):
    return next((v for k, v in headers.items() if k.casefold() == name.casefold()), None)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def urllib_transport(url, headers, timeout_s, max_bytes):
    """One HTTP exchange only; caller validates every redirect target."""
    opener = build_opener(HTTPHandler(), HTTPSHandler(), _NoRedirect())
    request = Request(url, headers=headers, method="GET")
    try:
        response = opener.open(request, timeout=timeout_s)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read(max_bytes + 1)
        return TransportResponse(response.status, dict(response.headers.items()), body, response.geturl())


class BoundedSourceClient:
    def __init__(self, policy, transport, clock):
        if not isinstance(policy, SourcePolicy) or not callable(transport) or not callable(clock):
            raise SourceError("policy, transport and clock required")
        self.policy, self.transport, self.clock = policy, transport, clock
        self._last_good = None
        self._last_attempt = None
        self._retry_until = None

    def refresh(self, url):
        try:
            if url not in self.policy.allowed_urls:
                raise SourceError("URL outside exact allowlist")
            now = datetime.fromisoformat(_utc(self.clock()).replace("Z", "+00:00"))
            if ((self._last_attempt is not None
                 and now < self._last_attempt + timedelta(seconds=self.policy.min_interval_s))
                    or (self._retry_until is not None and now < self._retry_until)):
                return Refresh("throttled", self._last_good, "provider poll interval or Retry-After")
            self._last_attempt = now
            headers = {"Accept": "application/geo+json, application/json",
                       "User-Agent": "Knight26-live-source/0.1 (+https://github.com/jrile018/knight26)"}
            if self._last_good and self._last_good.request_url == url:
                previous = dict(self._last_good.headers)
                etag = _header(previous, "ETag")
                modified = _header(previous, "Last-Modified")
                if etag:
                    headers["If-None-Match"] = etag
                if modified:
                    headers["If-Modified-Since"] = modified
            target = url
            for redirect_count in range(self.policy.max_redirects + 1):
                response = self.transport(target, headers, self.policy.timeout_s, self.policy.max_bytes)
                if not isinstance(response, TransportResponse) or type(response.status) is not int or not isinstance(response.headers, dict) or not isinstance(response.body, bytes):
                    raise SourceError("invalid transport response")
                if response.url != target:
                    raise SourceError("transport followed an unchecked redirect")
                if len(response.body) > self.policy.max_bytes:
                    raise SourceError("response byte cap exceeded")
                if response.status in (301, 302, 303, 307, 308):
                    location = _header(response.headers, "Location")
                    if location not in self.policy.allowed_urls or redirect_count == self.policy.max_redirects:
                        raise SourceError("redirect target or count rejected")
                    target = location
                    continue
                if response.status == 304:
                    if self._last_good is None or self._last_good.request_url != url:
                        raise SourceError("304 without matching last-good bytes")
                    return Refresh("not_modified", self._last_good, None)
                if response.status != 200:
                    if response.status in (429, 503):
                        retry = _header(response.headers, "Retry-After")
                        if isinstance(retry, str):
                            if retry.isdecimal():
                                if len(retry) > 12:
                                    self._retry_until = datetime.max.replace(tzinfo=timezone.utc)
                                else:
                                    try:
                                        self._retry_until = now + timedelta(seconds=int(retry))
                                    except OverflowError:
                                        self._retry_until = datetime.max.replace(tzinfo=timezone.utc)
                            else:
                                try:
                                    parsed_retry = parsedate_to_datetime(retry)
                                    if parsed_retry.tzinfo is not None:
                                        self._retry_until = parsed_retry.astimezone(timezone.utc)
                                except (TypeError, ValueError, IndexError, OverflowError):
                                    pass
                    raise SourceError(f"HTTP {response.status}")
                fetched_at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
                doc = RawDocument(self.policy.source_id, url, target, 200,
                                  tuple(sorted(response.headers.items())), fetched_at,
                                  response.body, sha256(response.body).hexdigest())
                if self.policy.source_id == "nws":
                    parse_nws_alerts(doc, max_records=self.policy.max_records)
                elif self.policy.source_id == "usgs":
                    parse_usgs_earthquakes(doc, max_records=self.policy.max_records)
                else:
                    raise SourceError("unregistered official provider")
                self._last_good = doc
                return Refresh("fresh", doc, None)
            raise SourceError("redirect count exceeded")
        except (SourceError, TimeoutError, OSError) as exc:
            return Refresh("stale" if self._last_good is not None else "failed",
                           self._last_good, str(exc))


def _utc(value):
    if not isinstance(value, str):
        raise SourceError("timestamp must be ISO8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceError("invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise SourceError("timestamp requires offset")
    try:
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (OverflowError, ValueError) as exc:
        raise SourceError("timestamp out of range") from exc


def _optional_utc(value):
    return None if value is None else _utc(value)


def _ms_utc(value):
    if type(value) is not int or not 1_000_000_000_000 <= value <= 9_999_999_999_999:
        raise SourceError("provider time must be epoch milliseconds")
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError) as exc:
        raise SourceError("provider millisecond time out of range") from exc


def _finite_float(value):
    try:
        parsed = float(value)
    except (OverflowError, ValueError) as exc:
        raise SourceError("invalid JSON number") from exc
    if not math.isfinite(parsed):
        raise SourceError("nonfinite JSON number")
    return parsed


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SourceError("invalid provider number")
    try:
        if not math.isfinite(value):
            raise SourceError("nonfinite provider number")
    except OverflowError as exc:
        raise SourceError("provider number out of range") from exc
    return value


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("duplicate decoded JSON key")
        result[key] = value
    return result


def _features(document, max_records):
    raw = document.raw if isinstance(document, RawDocument) else document.body if isinstance(document, TransportResponse) else None
    if not isinstance(raw, bytes) or len(raw) > 5_000_000:
        raise SourceError("invalid or oversized source bytes")
    if isinstance(document, RawDocument) and sha256(raw).hexdigest() != document.sha256:
        raise SourceError("raw source hash mismatch")
    try:
        top = json.loads(raw, object_pairs_hook=_object_pairs, parse_float=_finite_float,
                         parse_constant=lambda _: (_ for _ in ()).throw(SourceError("nonfinite JSON")))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise SourceError("invalid provider JSON") from exc
    if not isinstance(top, dict) or top.get("type") != "FeatureCollection" or not isinstance(top.get("features"), list):
        raise SourceError("expected GeoJSON FeatureCollection")
    if type(max_records) is not int or not 1 <= max_records <= 1000 or len(top["features"]) > max_records:
        raise SourceError("provider record cap exceeded")
    return top["features"]


def _provider_document(document, provider):
    if not isinstance(document, (RawDocument, TransportResponse)):
        raise SourceError("official source document required")
    url = document.final_url if isinstance(document, RawDocument) else document.url
    SourcePolicy(provider, (url,))
    if isinstance(document, RawDocument):
        SourcePolicy(provider, (document.request_url,))
        if document.source_id != provider or document.status != 200:
            raise SourceError("source identity or status mismatch")
        _utc(document.fetched_at)
    elif document.status != 200:
        raise SourceError("only successful provider bytes can be parsed")


def _metadata(document, provider):
    if isinstance(document, RawDocument):
        return {"source_id": provider, "request_url": document.request_url,
                "final_url": document.final_url, "source_url": document.final_url,
                "raw_sha256": document.sha256, "fetched_at": document.fetched_at}
    return {"source_id": provider, "request_url": document.url,
            "final_url": document.url, "source_url": document.url,
            "raw_sha256": sha256(document.body).hexdigest(), "fetched_at": None}


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise SourceError(f"{name} must be bounded nonempty text")
    return value


def _coord(point):
    if not isinstance(point, list) or len(point) < 2 or len(point) > 3:
        raise SourceError("invalid GeoJSON coordinate")
    lon, lat = point[:2]
    for value in point:
        _finite_number(value)
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise SourceError("GeoJSON longitude/latitude out of range")


def _nws_geometry(geometry):
    if geometry is None:
        return None
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise SourceError("NWS geometry must be area polygon or null")
    polygons = [geometry.get("coordinates")] if geometry["type"] == "Polygon" else geometry.get("coordinates")
    if not isinstance(polygons, list) or not polygons or len(polygons) > 100:
        raise SourceError("NWS polygon cap")
    vertices = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise SourceError("invalid NWS polygon")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise SourceError("invalid NWS ring")
            for point in ring:
                _coord(point)
                vertices += 1
                if vertices > 5000:
                    raise SourceError("NWS vertex cap")
            if ring[0] != ring[-1]:
                raise SourceError("NWS ring must close")
    return geometry


def parse_nws_alerts(document, *, max_records=200):
    _provider_document(document, "nws")
    features = _features(document, max_records)
    meta = _metadata(document, "nws")
    output = []
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
            raise SourceError("invalid NWS feature")
        props = feature["properties"]
        item_id = _text(props.get("id"), "NWS id")
        feature_url = _https_url(feature.get("id"))
        if urlsplit(feature_url).hostname != "api.weather.gov":
            raise SourceError("NWS feature origin mismatch")
        status = _text(props.get("status"), "NWS status")
        if status not in ("Actual", "Exercise", "System", "Test", "Draft"):
            raise SourceError("unknown NWS status")
        message = _text(props.get("messageType"), "NWS messageType")
        if message not in ("Alert", "Update", "Cancel", "Ack", "Error"):
            raise SourceError("unknown NWS messageType")
        references = props.get("references")
        if not isinstance(references, list) or len(references) > 100:
            raise SourceError("invalid NWS references")
        if message in ("Update", "Cancel") and not references:
            raise SourceError("NWS update/cancel lacks prior message references")
        checked_refs = []
        for ref in references:
            if not isinstance(ref, dict):
                raise SourceError("invalid NWS reference")
            ref_url = _https_url(ref.get("@id"))
            if urlsplit(ref_url).hostname != "api.weather.gov":
                raise SourceError("NWS reference origin mismatch")
            checked_refs.append({"identifier": _text(ref.get("identifier"), "NWS reference ID"),
                                 "sender": _text(ref.get("sender"), "NWS reference sender"),
                                 "sent": _utc(ref.get("sent")), "url": ref_url})
        geometry = _nws_geometry(feature.get("geometry"))
        area = props.get("areaDesc")
        if area is not None:
            _text(area, "NWS areaDesc")
        geocode = props.get("geocode")
        raw_ugc = geocode.get("UGC", []) if isinstance(geocode, dict) else []
        if not isinstance(raw_ugc, list) or len(raw_ugc) > 100:
            raise SourceError("invalid NWS UGC list")
        ugc = tuple(_text(x, "NWS UGC") for x in raw_ugc)
        zones = props.get("affectedZones", [])
        if not isinstance(zones, list) or len(zones) > 100:
            raise SourceError("invalid NWS affected zones")
        affected_zones = []
        for zone in zones:
            _https_url(zone)
            if urlsplit(zone).hostname != "api.weather.gov" or not urlsplit(zone).path.startswith("/zones/"):
                raise SourceError("NWS affected zone origin/path mismatch")
            affected_zones.append(zone)
        if geometry is None and not area and ugc:
            area = ", ".join(ugc)
            _text(area, "NWS UGC area label")
        output.append({
            **meta, "id": item_id, "feature_url": feature_url, "status": status,
            "message_type": message, "references": tuple(checked_refs),
            "sent": _utc(props.get("sent")), "effective": _utc(props.get("effective")),
            "onset": _optional_utc(props.get("onset")), "expires": _utc(props.get("expires")),
            "ends": _optional_utc(props.get("ends")),
            "event": _text(props.get("event"), "NWS event"),
            "geometry": geometry, "precision": "area" if geometry is not None else "area_label",
            "area_label": area, "ugc": ugc, "affected_zones": tuple(affected_zones),
            "acceptance": "candidate_hazard" if status == "Actual" and message in ("Alert", "Update")
                          else "provider_cancel" if status == "Actual" and message == "Cancel"
                          else "not_actual",
        })
    return tuple(output)


def parse_usgs_earthquakes(document, *, max_records=200):
    _provider_document(document, "usgs")
    features = _features(document, max_records)
    meta = _metadata(document, "usgs")
    output = []
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
            raise SourceError("invalid USGS feature")
        props = feature["properties"]
        item_id = _text(feature.get("id"), "USGS preferred id")
        if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", item_id) is None:
            raise SourceError("invalid USGS preferred id")
        ids = props.get("ids")
        if not isinstance(ids, str) or len(ids) > 4096:
            raise SourceError("invalid USGS associated ids")
        associated = tuple(x for x in ids.split(",") if x)
        if (not associated or len(associated) > 100 or len(set(associated)) != len(associated)
                or any(re.fullmatch(r"[A-Za-z0-9._-]{1,100}", x) is None for x in associated)):
            raise SourceError("invalid USGS associated ids")
        if item_id not in associated:
            associated = (item_id,) + associated
        place = props.get("place")
        if place is not None:
            _text(place, "USGS place")
        status = _text(props.get("status"), "USGS status")
        if status not in ("automatic", "reviewed", "deleted"):
            raise SourceError("unknown USGS status")
        event_type = _text(props.get("type"), "USGS type")
        mag = props.get("mag")
        if mag is not None:
            _finite_number(mag)
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            raise SourceError("USGS geometry must be point")
        coordinates = geometry.get("coordinates")
        _coord(coordinates)
        if len(coordinates) != 3:
            raise SourceError("USGS point needs depth")
        output.append({
            **meta, "id": item_id, "associated_ids": associated,
            "time": _ms_utc(props.get("time")), "updated": _ms_utc(props.get("updated")),
            "status": status, "event_type": event_type, "magnitude": mag,
            "geometry": geometry, "precision": "point", "place": place,
            "acceptance": "candidate_hazard" if event_type == "earthquake" and status != "deleted"
                          else "provider_deleted" if status == "deleted" else "not_earthquake",
        })
    return tuple(output)
