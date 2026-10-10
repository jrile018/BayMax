"""Deterministic official hazard records for the frozen incident-v1 contract.

Only trusted application code supplies IngestionContext and the frozen contract
module. Provider bytes supply event facts; they never supply acceptance context.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import math
import re

from services.intake.live_sources import (
    RawDocument, SourceError, parse_nws_alerts, parse_usgs_earthquakes,
)

NWS_FIELDS = (
    "id", "properties.id", "properties.status", "properties.messageType",
    "properties.sent", "properties.effective", "properties.onset",
    "properties.ends", "properties.expires", "properties.event",
    "properties.areaDesc", "properties.geocode.UGC",
    "properties.affectedZones", "properties.references", "geometry",
)
USGS_FIELDS = (
    "id", "properties.ids", "properties.status", "properties.type",
    "properties.time", "properties.updated", "properties.mag",
    "properties.place", "geometry.coordinates",
)
NWS_PAYLOAD = ("event", "status", "message_type", "provider_item_id",
               "feature_url", "effective_at", "area_desc", "ugc",
               "affected_zones", "references")
USGS_PAYLOAD = ("event_type", "status", "magnitude", "depth_km",
                "place", "provider_item_id", "associated_ids")
PROVIDERS = {"nws": "National Weather Service", "usgs": "US Geological Survey"}
HOSTS = {"nws": "api.weather.gov", "usgs": "earthquake.usgs.gov"}
LICENSES = {
    "nws": "NWS API open data: https://www.weather.gov/documentation/services-web-api",
    "usgs": "USGS data policy: https://www.usgs.gov/data-management/data-licensing",
}


@dataclass(frozen=True)
class IngestionContext:
    """Trusted app metadata; never deserialize this from provider JSON."""
    accepted_at: str
    first_seen_at: str
    bbox_lonlat: tuple[float, float, float, float]
    transport_verified: bool
    canonical_item_id: str | None = None
    previous_revision: int | None = None
    previous_provider_item_id: str | None = None


def official_policies(contract):
    _contract(contract)
    return (
        contract.OfficialPolicy("nws", PROVIDERS["nws"], HOSTS["nws"],
                                NWS_FIELDS, NWS_PAYLOAD, "nws-active-alert-v1"),
        contract.OfficialPolicy("usgs", PROVIDERS["usgs"], HOSTS["usgs"],
                                USGS_FIELDS, USGS_PAYLOAD, "usgs-hourly-earthquake-v1"),
    )


def _contract(contract):
    if getattr(contract, "VERSION", None) != "knight26-incident-v1":
        raise SourceError("frozen incident-v1 contract required")
    for name in ("OfficialPolicy", "VerifiedSource", "record_fingerprint"):
        if not hasattr(contract, name):
            raise SourceError("incident contract interface missing")


def _trusted_time(value, name):
    # Controller receipts use seven fractional digits (100 ns). The incident
    # contract stores microseconds; truncate only that final sub-microsecond.
    if not isinstance(value, str) or re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,7})?Z", value) is None:
        raise SourceError(f"{name} requires canonical UTC")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        precision = "microseconds" if parsed.microsecond else "seconds"
        return parsed, parsed.isoformat(timespec=precision).replace("+00:00", "Z")
    except (ValueError, OverflowError) as exc:
        raise SourceError(f"invalid {name}") from exc


def _bbox(value):
    if not isinstance(value, tuple) or len(value) != 4:
        raise SourceError("trusted bbox must be four coordinates")
    for coordinate in value:
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise SourceError("invalid bbox coordinate")
        try:
            if not math.isfinite(coordinate):
                raise SourceError("nonfinite bbox coordinate")
        except OverflowError as exc:
            raise SourceError("bbox coordinate out of range") from exc
    west, south, east, north = value
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise SourceError("invalid trusted bbox")
    return value


def _inside(point, bbox):
    lon, lat = point
    if not bbox[0] <= lon <= bbox[2] or not bbox[1] <= lat <= bbox[3]:
        raise SourceError("official geometry outside incident AOI")


def _zone_prefixes(codes):
    return sorted({code[:2] for code in codes
                   if isinstance(code, str)
                   and re.fullmatch(r"[A-Z]{2}[CZ][0-9]{3}", code)})


def _geometry(candidate, bbox):
    geometry = candidate["geometry"]
    if candidate["source_id"] == "usgs":
        lon, lat, _depth = geometry["coordinates"]
        _inside((lon, lat), bbox)
        return {"type": "Point", "coordinates": [lon, lat]}, "point", None, None
    if geometry is None:
        label = candidate["area_label"]
        if not label:
            raise SourceError("null NWS geometry lacks area label")
        uncertainty = (
            "NWS area association only; geometry unavailable; AOI not spatially verified")
        query_area = re.search(r"[?&]area=([A-Z]{2})$", candidate["source_url"])
        prefixes = _zone_prefixes(candidate["ugc"])
        if query_area:
            outside_query = [code for code in prefixes if code != query_area.group(1)]
            if outside_query:
                uncertainty += (
                    "; source zones also " + ", ".join(outside_query)
                    + " outside queried " + query_area.group(1) + " area")
        return None, "area", label, uncertainty
    if geometry["type"] != "Polygon" or len(geometry["coordinates"]) != 1:
        raise SourceError("incident-v1 cannot represent NWS multipolygon or holes")
    ring = geometry["coordinates"][0]
    if not 4 <= len(ring) <= 256:
        raise SourceError("incident-v1 polygon vertex limit")
    copied = []
    for point in ring:
        if len(point) != 2:
            raise SourceError("incident-v1 cannot represent altitude")
        _inside(point, bbox)
        copied.append(list(point))
    return {"type": "Polygon", "coordinates": [copied]}, "polygon", None, None


def _lineage(candidate, context):
    if context.previous_revision is None:
        if context.previous_provider_item_id is not None:
            raise SourceError("prior provider item requires prior revision")
        if context.canonical_item_id not in (None, candidate["id"]):
            raise SourceError("initial canonical item must equal provider ID")
        if candidate["acceptance"] in ("provider_cancel", "provider_deleted"):
            raise SourceError("provider retraction requires linked prior revision")
        return candidate["id"], 1, None, None, False
    prior = context.previous_revision
    if type(prior) is not int or prior < 1 or context.previous_provider_item_id is None:
        raise SourceError("trusted prior revision and provider item ID required")
    item_id = context.canonical_item_id
    if not isinstance(item_id, str) or not item_id:
        raise SourceError("trusted canonical item ID required")
    old = context.previous_provider_item_id
    if candidate["source_id"] == "nws":
        if old not in {ref["identifier"] for ref in candidate["references"]}:
            raise SourceError("NWS correction lacks provider reference to prior message")
    elif old != candidate["id"] and old not in candidate["associated_ids"]:
        raise SourceError("USGS preferred-ID change lacks associated prior ID")
    if candidate["acceptance"] not in ("candidate_hazard", "provider_cancel", "provider_deleted"):
        raise SourceError("nonhazard update cannot correct hazard record")
    return item_id, prior + 1, [candidate["source_id"], item_id, prior], (
        context.first_seen_at), candidate["acceptance"] in (
            "provider_cancel", "provider_deleted")


def build_official_record(document, provider_item_id, context, *, contract):
    """Return (exact record, bound VerifiedSource) from one verified raw item.

    The caller must authenticate transport and construct IngestionContext itself.
    This function rehashes bytes and re-extracts every source-derived record value.
    """
    _contract(contract)
    if not isinstance(document, RawDocument) or not isinstance(context, IngestionContext):
        raise SourceError("raw document and trusted ingestion context required")
    if context.transport_verified is not True:
        raise SourceError("authenticated transport verification required")
    if document.source_id not in PROVIDERS:
        raise SourceError("unregistered official provider")
    if sha256(document.raw).hexdigest() != document.sha256:
        raise SourceError("raw source hash mismatch")
    first, first_utc = _trusted_time(context.first_seen_at, "first_seen_at")
    fetched, fetched_utc = _trusted_time(document.fetched_at, "fetched_at")
    accepted, accepted_utc = _trusted_time(context.accepted_at, "accepted_at")
    if not first <= fetched <= accepted:
        raise SourceError("trusted acceptance times out of order")
    bbox = _bbox(context.bbox_lonlat)
    candidates = (parse_nws_alerts(document) if document.source_id == "nws"
                  else parse_usgs_earthquakes(document))
    selected = [x for x in candidates if x["id"] == provider_item_id]
    if len(selected) != 1:
        raise SourceError("provider item ID missing or duplicated in verified bytes")
    c = selected[0]
    if (c["acceptance"] not in ("candidate_hazard", "provider_cancel", "provider_deleted")
            or (c["source_id"] == "usgs" and c["event_type"] != "earthquake")):
        raise SourceError("provider item cannot enter official hazard policy")
    geometry, precision, area_label, uncertainty = _geometry(c, bbox)
    item_id, revision, supersedes, correction_at, retracted = _lineage(c, context)
    if correction_at is not None:
        correction_at = first_utc
    if c["source_id"] == "nws":
        payload = {
            "event": c["event"], "status": c["status"],
            "message_type": c["message_type"], "provider_item_id": c["id"],
            "feature_url": c["feature_url"], "effective_at": c["effective"],
            "area_desc": c["area_label"], "ugc": list(c["ugc"]),
            "affected_zones": list(c["affected_zones"]),
            "references": [dict(ref) for ref in c["references"]],
        }
        source_kind = "official_forecast"
        published_at, observed_at = c["sent"], None
        valid_from, valid_through, expires_at = c["onset"], c["ends"], c["expires"]
        api_fields = NWS_FIELDS
    else:
        payload = {
            "event_type": c["event_type"], "status": c["status"],
            "magnitude": c["magnitude"], "depth_km": c["geometry"]["coordinates"][2],
            "place": c["place"], "provider_item_id": c["id"],
            "associated_ids": list(c["associated_ids"]),
        }
        source_kind = "observed"
        published_at, observed_at = c["updated"], c["time"]
        valid_from, valid_through, expires_at = c["time"], None, None
        api_fields = USGS_FIELDS
    record = {
        "source_id": c["source_id"], "item_id": item_id, "revision": revision,
        "source_url": document.final_url, "raw_sha256": document.sha256,
        "provider": PROVIDERS[c["source_id"]],
        "license": LICENSES[c["source_id"]],
        "source_type": "official_api", "category": "hazard",
        "source_kind": source_kind, "published_at": published_at,
        "observed_at": observed_at, "valid_from": valid_from,
        "valid_through": valid_through, "message_expires_at": expires_at,
        "first_seen_at": first_utc, "fetched_at": fetched_utc,
        "accepted_at": accepted_utc,
        "correction_available_at": correction_at, "superseded_at": None,
        "supersedes": supersedes, "retracted": retracted,
        "source_reference": {"api_fields": list(api_fields)},
        "geometry": geometry, "precision": precision, "area_label": area_label,
        "source_uncertainty": uncertainty, "payload": payload,
    }
    try:
        fingerprint = contract.record_fingerprint(record)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SourceError("official record exceeds incident-v1 bounds") from exc
    verification = contract.VerifiedSource(
        c["source_id"], document.final_url, document.sha256, True, fingerprint)
    return record, verification


def dispatcher_synopsis(snapshot, *, max_hazards=50):
    """Compact source-linked summary; all operational outcomes remain unknown."""
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != "knight26-incident-v1":
        raise SourceError("incident-v1 snapshot required")
    copied = dict(snapshot)
    expected_hash = copied.pop("snapshot_hash", None)
    try:
        actual_hash = sha256(json.dumps(
            copied, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise SourceError("invalid snapshot JSON") from exc
    if expected_hash != actual_hash:
        raise SourceError("snapshot hash mismatch")
    categories = snapshot.get("categories")
    if not isinstance(categories, dict):
        raise SourceError("snapshot categories required")
    hazards = categories.get("hazard") or []
    if not isinstance(hazards, list) or type(max_hazards) is not int or not 1 <= max_hazards <= 100:
        raise SourceError("invalid synopsis inputs")
    linked = []
    for record in hazards[:max_hazards]:
        if not isinstance(record, dict) or record.get("category") != "hazard":
            raise SourceError("invalid snapshot hazard")
        linked.append({
            "event": record.get("payload", {}).get("event",
                       record.get("payload", {}).get("event_type")),
            "location_label": (
                record.get("payload", {}).get("area_desc")
                or record.get("payload", {}).get("place")
                or record.get("area_label")),
            "geometry": deepcopy(record["geometry"]),
            "magnitude": record.get("payload", {}).get("magnitude"),
            "depth_km": record.get("payload", {}).get("depth_km"),
            "effective_at": record.get("payload", {}).get("effective_at"),
            "provider_status": record.get("payload", {}).get("status"),
            "source_zone_prefixes": _zone_prefixes(
                record.get("payload", {}).get("ugc", [])),
            "source_kind": record["source_kind"],
            "source_id": record["source_id"], "item_id": record["item_id"],
            "revision": record["revision"], "source_url": record["source_url"],
            "raw_sha256": record["raw_sha256"], "published_at": record["published_at"],
            "observed_at": record["observed_at"], "valid_from": record["valid_from"],
            "valid_through": record["valid_through"],
            "message_expires_at": record["message_expires_at"],
            "precision": record["precision"], "area_label": record["area_label"],
            "source_uncertainty": record["source_uncertainty"],
        })
    operational = {}
    for name in ("needs", "closures", "vehicles", "stock", "capacity"):
        operational[name] = "unknown"
    return {
        "incident_id": snapshot["incident_id"], "cutoff_utc": snapshot["cutoff_utc"],
        "hazards": linked, "hazards_omitted": len(hazards) - len(linked),
        "operational_categories": operational,
        "source_health": deepcopy(snapshot.get("source_health")),
        "can_calculate_operational_outcomes": False,
    }
