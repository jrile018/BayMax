"""Bounded, in-memory incident evidence and cutoff snapshot contract.

Only trusted application code may create OfficialPolicy, VerifiedSource, or
HumanReview values. External source bytes and parsed records are untrusted data.
This module validates structure and provenance binding; it does not authenticate
networks, people, semantic truth, or execute dispatch/simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import re
from urllib.parse import urlsplit, urlunsplit


VERSION = "knight26-incident-v1"
CATEGORIES = ("hazard", "needs", "closures", "vehicles", "stock", "capacity")
OPERATIONAL = CATEGORIES[1:]
SOURCE_TYPES = ("official_api", "agency_notice", "news", "ocr", "authored")
SOURCE_KINDS = ("observed", "reported", "official_forecast", "authored")
RECORD_FIELDS = {
    "source_id", "item_id", "revision", "source_url", "raw_sha256", "provider",
    "license", "source_type", "category", "source_kind", "published_at",
    "observed_at", "valid_from", "valid_through", "message_expires_at",
    "first_seen_at", "fetched_at",
    "accepted_at", "correction_available_at", "superseded_at", "supersedes", "retracted",
    "source_reference", "geometry", "precision", "area_label",
    "source_uncertainty", "payload",
}
UTC_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
HOST_RE = re.compile(r"^[a-z0-9.-]+$")
MAX_RECORDS = 5000
MAX_RECORD_BYTES = 65536
MAX_VERTEX_COUNT = 256


def _json_copy(value, *, max_bytes=MAX_RECORD_BYTES):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > max_bytes:
            raise ValueError("JSON value exceeds byte limit")
        return json.loads(encoded)
    except (TypeError, OverflowError, ValueError, RecursionError) as exc:
        raise ValueError("value must be bounded finite JSON") from exc


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _string(value, name, *, limit=4096, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{name} must be nonempty bounded text")


def _id(value, name):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"{name} must be a stable identifier")


def _time(value, name, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise ValueError(f"{name} must be a UTC Z timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} is not a real UTC timestamp") from exc


def _number(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number in range")


def _bbox(value):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("bbox_lonlat must be [min_lon,min_lat,max_lon,max_lat]")
    for i, (low, high) in enumerate(((-180, 180), (-90, 90), (-180, 180), (-90, 90))):
        _number(value[i], f"bbox_lonlat[{i}]", low, high)
    if value[0] >= value[2] or value[1] >= value[3]:
        raise ValueError("bbox_lonlat must have positive extent")
    return value


def _url(value):
    _string(value, "source_url", limit=2048)
    if any(c.isspace() for c in value):
        raise ValueError("source_url contains whitespace")
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid source_url") from exc
    if (parts.scheme != "https" or not host or not HOST_RE.fullmatch(host)
            or parts.username is not None or parts.password is not None
            or parts.fragment or port not in (None, 443)):
        raise ValueError("source_url must be canonical HTTPS without credentials or fragment")
    return urlunsplit(("https", host, parts.path or "/", parts.query, "")), host


def _point(value, bbox):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("coordinate must be [lon,lat]")
    _number(value[0], "longitude", bbox[0], bbox[2])
    _number(value[1], "latitude", bbox[1], bbox[3])


def _geometry(record, bbox):
    geometry = record["geometry"]
    precision = record["precision"]
    if precision not in ("point", "polygon", "area", "unknown"):
        raise ValueError("unsupported geometry precision")
    if geometry is None:
        if precision not in ("area", "unknown"):
            raise ValueError("null geometry requires area/unknown precision")
        _string(record["area_label"], "area_label", nullable=precision == "unknown")
        return
    if record["area_label"] is not None:
        raise ValueError("area_label is reserved for null geometry")
    if not isinstance(geometry, dict) or set(geometry) != {"type", "coordinates"}:
        raise ValueError("geometry must be a bounded GeoJSON Point/Polygon")
    if geometry["type"] == "Point" and precision == "point":
        _point(geometry["coordinates"], bbox)
    elif geometry["type"] == "Polygon" and precision == "polygon":
        rings = geometry["coordinates"]
        if not isinstance(rings, list) or len(rings) != 1:
            raise ValueError("Polygon must have one exterior ring")
        ring = rings[0]
        if not isinstance(ring, list) or not 4 <= len(ring) <= MAX_VERTEX_COUNT:
            raise ValueError("Polygon ring vertex limit")
        for coordinate in ring:
            _point(coordinate, bbox)
        if ring[0] != ring[-1]:
            raise ValueError("Polygon ring must be closed")
    else:
        raise ValueError("geometry type and precision mismatch")


@dataclass(frozen=True)
class OfficialPolicy:
    source_id: str
    provider: str
    host: str
    allowed_api_fields: tuple[str, ...]
    allowed_payload_fields: tuple[str, ...]
    rule_id: str


@dataclass(frozen=True)
class VerifiedSource:
    source_id: str
    source_url: str
    raw_sha256: str
    transport_verified: bool


@dataclass(frozen=True)
class HumanReview:
    identity: tuple[str, str, int]
    raw_sha256: str
    reviewer_id: str
    reviewed_fields: tuple[str, ...]
    reviewed_at: str
    authenticated: bool


class EvidenceLog:
    """Append-only canonical evidence; returned values are defensive JSON copies."""

    def __init__(self, incident_id, bbox_lonlat, *, official_policies=()):
        _id(incident_id, "incident_id")
        bbox = _json_copy(bbox_lonlat)
        self.incident_id = incident_id
        self.bbox_lonlat = tuple(_bbox(bbox))
        self._records = []
        self._by_identity = {}
        self._latest = {}
        self._last_accepted = None
        self._sealed_through = None
        policies = {}
        for policy in official_policies:
            if not isinstance(policy, OfficialPolicy):
                raise ValueError("official_policies requires trusted OfficialPolicy values")
            _id(policy.source_id, "policy.source_id")
            _id(policy.rule_id, "policy.rule_id")
            _string(policy.provider, "policy.provider")
            if not HOST_RE.fullmatch(policy.host):
                raise ValueError("policy host must be lowercase DNS host")
            if not policy.allowed_api_fields or not policy.allowed_payload_fields:
                raise ValueError("policy needs exact allowed fields")
            if policy.source_id in policies:
                raise ValueError("duplicate official source policy")
            policies[policy.source_id] = OfficialPolicy(
                policy.source_id, policy.provider, policy.host,
                tuple(policy.allowed_api_fields), tuple(policy.allowed_payload_fields),
                policy.rule_id)
        self._policies = policies

    def append(self, record, *, verification, review=None):
        """Accept one trusted-context-bound revision, atomically and idempotently."""
        r = _json_copy(record)
        if not isinstance(r, dict) or set(r) != RECORD_FIELDS:
            raise ValueError("record has missing or unsupported fields")
        self._validate_record(r)
        identity = (r["source_id"], r["item_id"], r["revision"])
        if not isinstance(verification, VerifiedSource) or verification.transport_verified is not True:
            raise ValueError("trusted verified source context is required")
        canonical_url, host = _url(r["source_url"])
        verified_url, verified_host = _url(verification.source_url)
        if (verification.source_id != r["source_id"] or
                verified_url != canonical_url or verified_host != host or
                verification.raw_sha256 != r["raw_sha256"]):
            raise ValueError("source host/url/raw hash binding mismatch")
        r["source_url"] = canonical_url
        acceptance = self._acceptance(r, host, review)
        r["acceptance"] = acceptance
        encoded = _canonical(r)
        if identity in self._by_identity:
            if self._by_identity[identity] == encoded:
                return json.loads(encoded)
            raise ValueError("identity already has a different revision")
        accepted_time = _time(r["accepted_at"], "accepted_at")
        if self._last_accepted is not None and accepted_time < self._last_accepted:
            raise ValueError("accepted_at cannot backdate append-only history")
        if self._sealed_through is not None and accepted_time <= self._sealed_through:
            raise ValueError("accepted_at falls within an already issued snapshot cutoff")
        item_key = identity[:2]
        previous = self._latest.get(item_key)
        if previous is None:
            if r["supersedes"] is not None:
                raise ValueError("first revision cannot supersede")
        elif r["supersedes"] != list(previous) or r["revision"] <= previous[2]:
            raise ValueError("revision must supersede latest same-source item")
        if previous is not None:
            prior = json.loads(self._by_identity[previous])
            if r["category"] != prior["category"] or r["provider"] != prior["provider"]:
                raise ValueError("correction must retain item category and provider")
        if len(self._records) >= MAX_RECORDS:
            raise ValueError("evidence log count limit")
        self._records.append(encoded)
        self._by_identity[identity] = encoded
        self._latest[item_key] = identity
        self._last_accepted = accepted_time
        return json.loads(encoded)

    def _validate_record(self, r):
        _id(r["source_id"], "source_id")
        _id(r["item_id"], "item_id")
        if type(r["revision"]) is not int or r["revision"] < 1:
            raise ValueError("revision must be positive integer")
        _url(r["source_url"])
        if not isinstance(r["raw_sha256"], str) or not SHA_RE.fullmatch(r["raw_sha256"]):
            raise ValueError("raw_sha256 must be lowercase SHA-256")
        _string(r["provider"], "provider", limit=256)
        _string(r["license"], "license", limit=256)
        if r["source_type"] not in SOURCE_TYPES or r["category"] not in CATEGORIES:
            raise ValueError("unsupported source type or category")
        if r["source_kind"] not in SOURCE_KINDS:
            raise ValueError("unsupported source kind")
        for field in ("published_at", "observed_at", "valid_from",
                      "valid_through", "message_expires_at",
                      "correction_available_at"):
            _time(r[field], field, nullable=True)
        for field in ("first_seen_at", "fetched_at", "accepted_at"):
            _time(r[field], field)
        if _time(r["first_seen_at"], "first_seen_at") > _time(r["fetched_at"], "fetched_at"):
            raise ValueError("first seen cannot be after fetch")
        if _time(r["fetched_at"], "fetched_at") > _time(r["accepted_at"], "accepted_at"):
            raise ValueError("fetch cannot be after acceptance")
        if (r["published_at"] is not None and
                _time(r["published_at"], "published_at") >
                _time(r["accepted_at"], "accepted_at")):
            raise ValueError("publication cannot be after acceptance")
        if (r["correction_available_at"] is not None and
                _time(r["correction_available_at"], "correction_available_at") >
                _time(r["accepted_at"], "accepted_at")):
            raise ValueError("correction cannot be accepted before available")
        if r["superseded_at"] is not None:
            raise ValueError("superseded_at is derived from accepted later revisions")
        if r["supersedes"] is not None:
            link = r["supersedes"]
            if (not isinstance(link, list) or len(link) != 3 or
                    link[:2] != [r["source_id"], r["item_id"]] or
                    type(link[2]) is not int or link[2] < 1 or
                    r["correction_available_at"] is None):
                raise ValueError("invalid correction link or availability")
        elif r["correction_available_at"] is not None:
            raise ValueError("correction availability needs supersedes")
        if type(r["retracted"]) is not bool or (r["retracted"] and r["supersedes"] is None):
            raise ValueError("retraction needs a prior revision")
        _geometry(r, self.bbox_lonlat)
        _string(r["source_uncertainty"], "source_uncertainty", nullable=True)
        if not isinstance(r["payload"], dict) or not r["payload"] or len(r["payload"]) > 32:
            raise ValueError("payload must have bounded explicit fields")
        for field in r["payload"]:
            _id(field, "payload field")
        reference = r["source_reference"]
        if not isinstance(reference, dict):
            raise ValueError("source_reference must be an object")
        if r["source_type"] == "official_api":
            if set(reference) != {"api_fields"} or not isinstance(reference["api_fields"], list):
                raise ValueError("official API requires exact field references")
            if not reference["api_fields"] or len(reference["api_fields"]) != len(set(reference["api_fields"])):
                raise ValueError("API field references must be nonempty and unique")
            for field in reference["api_fields"]:
                _string(field, "api field", limit=256)
        else:
            allowed = {"quote", "page", "crop"}
            if not {"quote"} <= set(reference) or not set(reference) <= allowed:
                raise ValueError("notice/news/OCR requires quoted span")
            _string(reference["quote"], "quote", limit=4096)
            if "page" in reference and (type(reference["page"]) is not int or reference["page"] < 1):
                raise ValueError("page must be positive integer")
            if r["source_type"] == "ocr":
                if "page" not in reference or "crop" not in reference:
                    raise ValueError("OCR requires page and crop")
                crop = reference["crop"]
                if not isinstance(crop, list) or len(crop) != 4:
                    raise ValueError("OCR crop must be four normalized coordinates")
                for value in crop:
                    _number(value, "OCR crop", 0, 1)
                if crop[0] >= crop[2] or crop[1] >= crop[3]:
                    raise ValueError("OCR crop must have positive extent")

    def _acceptance(self, r, host, review):
        identity = (r["source_id"], r["item_id"], r["revision"])
        if review is not None:
            if (not isinstance(review, HumanReview) or review.authenticated is not True or
                    tuple(review.identity) != identity or
                    review.raw_sha256 != r["raw_sha256"] or
                    set(review.reviewed_fields) != set(r["payload"]) or
                    len(review.reviewed_fields) != len(r["payload"])):
                raise ValueError("authenticated per-record field review required")
            _id(review.reviewer_id, "reviewer_id")
            reviewed_time = _time(review.reviewed_at, "reviewed_at")
            if (reviewed_time < _time(r["fetched_at"], "fetched_at") or
                    reviewed_time > _time(r["accepted_at"], "accepted_at")):
                raise ValueError("review must follow fetch and precede acceptance")
            return {"method": "human_review", "reviewer_id": review.reviewer_id,
                    "reviewed_fields": sorted(review.reviewed_fields),
                    "reviewed_at": review.reviewed_at}
        policy = self._policies.get(r["source_id"])
        reference = r["source_reference"]
        if (policy is None or r["source_type"] != "official_api" or
                r["category"] != "hazard" or r["provider"] != policy.provider or
                host != policy.host or
                r["source_kind"] not in ("observed", "official_forecast") or
                not set(reference["api_fields"]) <= set(policy.allowed_api_fields) or
                not set(r["payload"]) <= set(policy.allowed_payload_fields)):
            raise ValueError("claim requires authenticated human review")
        return {"method": "official_policy", "rule_id": policy.rule_id}

    def snapshot(self, cutoff_utc, *, ledger_watermark=None,
                 in_flight_commitments=None, source_health=None):
        """Return a defensive canonical JSON snapshot of knowledge at cutoff."""
        cutoff = _time(cutoff_utc, "cutoff_utc")
        ledger = _json_copy(ledger_watermark)
        commitments = _json_copy(in_flight_commitments)
        health = _json_copy(source_health)
        if commitments is not None and not isinstance(commitments, list):
            raise ValueError("in_flight_commitments must be a list or null")
        if health is not None:
            if not isinstance(health, dict):
                raise ValueError("source_health must be an object")
            for value in health.values():
                if (not isinstance(value, dict) or
                        value.get("status") not in ("alive", "stale", "failure") or
                        set(value) - {"status", "source_time", "reason"}):
                    raise ValueError("source health requires explicit alive/stale/failure")
                source_time = _time(value.get("source_time"), "source_time", nullable=True)
                if source_time is not None and source_time > cutoff:
                    raise ValueError("source health cannot include future source time")
                _string(value.get("reason"), "reason", nullable=True)
                if value["status"] == "stale" and (not value.get("source_time") or not value.get("reason")):
                    raise ValueError("stale source needs last-good time and failure reason")
                if value["status"] == "failure" and not value.get("reason"):
                    raise ValueError("failed source needs failure reason")
        latest = {}
        known_history = []
        for encoded in self._records:
            r = json.loads(encoded)
            if (_time(r["accepted_at"], "accepted_at") <= cutoff and
                    (r["correction_available_at"] is None or
                     _time(r["correction_available_at"], "correction_available_at") <= cutoff)):
                key = (r["source_id"], r["item_id"])
                if key in latest:
                    latest[key]["superseded_at"] = r["accepted_at"]
                known_history.append(r)
                latest[key] = r
        known_history.sort(key=lambda r: (r["source_id"], r["item_id"], r["revision"]))
        active = sorted((r for r in latest.values() if not r["retracted"]),
                        key=lambda r: (r["category"], r["source_id"],
                                       r["item_id"], r["revision"]))
        leads = [r for r in active if r["category"] == "hazard" and r["source_type"] == "news"]
        categories = {category: None for category in CATEGORIES}
        for category in CATEGORIES:
            matching = [r for r in active if r["category"] == category and r not in leads]
            if matching:
                categories[category] = matching
        refs = [{"source_id": r["source_id"], "item_id": r["item_id"],
                 "revision": r["revision"], "raw_sha256": r["raw_sha256"]}
                for r in active]
        result = {
            "schema_version": VERSION,
            "incident_id": self.incident_id,
            "bbox_lonlat": _json_copy(self.bbox_lonlat),
            "cutoff_utc": cutoff_utc,
            "categories": categories,
            "revision_history": known_history,
            "unconfirmed_leads": leads,
            "accepted_source_refs": refs,
            "ledger_watermark": ledger,
            "in_flight_commitments": commitments,
            "source_health": health,
        }
        result["snapshot_hash"] = _hash(result)
        if self._sealed_through is None or cutoff > self._sealed_through:
            self._sealed_through = cutoff
        return result


def projection_input(snapshot, *, horizon_minutes, model_version,
                     assumptions, training_assumptions=None):
    """Pin cutoff evidence and explicitly authored assumptions; run no model."""
    s = _json_copy(snapshot, max_bytes=MAX_RECORD_BYTES * MAX_RECORDS)
    if not isinstance(s, dict) or s.get("schema_version") != VERSION:
        raise ValueError("incident snapshot version required")
    recorded_hash = s.pop("snapshot_hash", None)
    if recorded_hash != _hash(s):
        raise ValueError("snapshot hash mismatch")
    if type(horizon_minutes) is not int or not 1 <= horizon_minutes <= 10080:
        raise ValueError("horizon_minutes must be 1..10080")
    _id(model_version, "model_version")
    authored = _json_copy(assumptions)
    training = _json_copy(training_assumptions)
    for label, value in (("assumptions", authored),
                         ("training_assumptions", training)):
        if label == "training_assumptions" and value is None:
            continue
        if not isinstance(value, dict) or (label == "assumptions" and not value):
            raise ValueError(f"{label} must be explicit authored provenance")
        for name, description in value.items():
            _id(name, f"{label} key")
            _string(description, f"{label} value")
    missing = [category for category in OPERATIONAL
               if s["categories"][category] is None]
    can_calculate = all(category in (training or {}) for category in missing)
    result = {
        "schema_version": VERSION,
        "projection_input_version": VERSION,
        "initial_snapshot_hash": recorded_hash,
        "incident_id": s["incident_id"],
        "cutoff_utc": s["cutoff_utc"],
        "accepted_source_refs": s["accepted_source_refs"],
        "bbox_lonlat": s["bbox_lonlat"],
        "categories": s["categories"],
        "unconfirmed_leads": s["unconfirmed_leads"],
        "ledger_watermark": s["ledger_watermark"],
        "in_flight_commitments": s["in_flight_commitments"],
        "source_health": s["source_health"],
        "horizon_minutes": horizon_minutes,
        "model_version": model_version,
        "authored_assumptions": authored,
        "authored_training_assumptions": training,
        "unknown_operational_categories": missing,
        "can_calculate_operational_outcomes": can_calculate,
        "calibrated": False,
        "frequency_label": "uncalibrated_scenario_frequencies",
    }
    result["projection_input_hash"] = _hash(result)
    return result
