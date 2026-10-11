"""Bounded WFIGS source candidates; no incident acceptance or fire forecast.

The caller verifies HTTPS transport and fetch time separately. These functions
only validate and summarize saved ArcGIS responses. Returned feature links
are references, not proof of the acquisition URL. These functions never publish
an accepted incident, infer active status, or redistribute polygon coordinates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re
from urllib.parse import parse_qs, urlsplit

_IRWIN = re.compile(r"\{[0-9A-F]{8}-(?:[0-9A-F]{4}-){3}[0-9A-F]{12}\}")
_POINT_SERVICE = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0"
)
_PERIMETER_SERVICE = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
    "WFIGS_Interagency_Perimeters_Current/FeatureServer/0"
)


def _utc_text(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise ValueError("fetch time must be a complete UTC timestamp with Z suffix")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid fetch time") from exc
    if result.utcoffset().total_seconds() != 0:
        raise ValueError("fetch time must be UTC")
    return result


def _epoch_ms(value: object, label: str) -> tuple[datetime, str]:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be nonnegative epoch milliseconds")
    try:
        moment = datetime.fromtimestamp(value / 1000, timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} is out of range") from exc
    timespec = "seconds" if value % 1000 == 0 else "milliseconds"
    return moment, moment.isoformat(timespec=timespec).replace("+00:00", "Z")


def _number(value: object, label: str, low: float, high: float | None = None) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be finite")
    if value < low or (high is not None and value > high):
        raise ValueError(f"{label} is out of range")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{label} must be finite")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite JSON constant")


def _finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid JSON float") from exc
    if not math.isfinite(parsed):
        raise ValueError("nonfinite JSON float")
    return parsed


def _raw_json(raw: bytes, label: str, max_bytes: int) -> dict:
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise ValueError(f"{label} size or type invalid")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant,
                           parse_float=_finite_float)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label} is not JSON") from exc
    if not isinstance(value, dict) or "error" in value:
        raise ValueError(f"{label} is an ArcGIS error or not an object")
    if value.get("exceededTransferLimit") is not None and value["exceededTransferLimit"] is not False:
        raise ValueError(f"{label} exceeded transfer limit")
    return value


def _paired(ids_raw: bytes, features_raw: bytes) -> list[dict]:
    ids = _raw_json(ids_raw, "IDs", 1_000_000)
    result = _raw_json(features_raw, "features", 4_000_000)
    object_ids = ids.get("objectIds")
    features = result.get("features")
    if (not isinstance(object_ids, list) or len(object_ids) > 2000 or
            any(type(x) is not int or x < 0 for x in object_ids) or
            len(set(object_ids)) != len(object_ids)):
        raise ValueError("invalid object ID list")
    spatial_reference = result.get("spatialReference")
    if (not isinstance(features, list) or len(features) > 2000 or
            not isinstance(spatial_reference, dict) or
            spatial_reference.get("wkid") != 4326):
        raise ValueError("invalid feature list or spatial reference")
    found = []
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
            raise ValueError("invalid feature")
        object_id = feature["attributes"].get("OBJECTID")
        if type(object_id) is not int or object_id < 0:
            raise ValueError("invalid feature OBJECTID")
        found.append(object_id)
    if len(set(found)) != len(found) or set(found) != set(object_ids):
        raise ValueError("feature IDs do not exactly match ID response")
    return features


def _expected_irwin(value: str) -> str:
    if not isinstance(value, str) or not _IRWIN.fullmatch(value):
        raise ValueError("invalid expected IRWIN ID")
    return value


def incident_candidate(ids_raw: bytes, features_raw: bytes,
                       irwin_id: str, fetched_at_utc: str) -> dict:
    """Return a source-linked point candidate without asserting active fire."""
    irwin_id = _expected_irwin(irwin_id)
    fetched = _utc_text(fetched_at_utc)
    features = _paired(ids_raw, features_raw)
    matches = [f for f in features if f["attributes"].get("IrwinID") == irwin_id]
    if len(matches) != 1:
        raise ValueError("expected exactly one matching incident point")
    feature = matches[0]
    a = feature["attributes"]
    if a.get("IncidentTypeCategory") != "WF":
        raise ValueError("incident is not a wildfire")
    name = a.get("IncidentName")
    if not isinstance(name, str) or not name.strip() or len(name) > 256:
        raise ValueError("invalid incident name")
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("missing point geometry")
    lon = _number(geometry.get("x"), "longitude", -180, 180)
    lat = _number(geometry.get("y"), "latitude", -90, 90)
    discovered, discovered_text = _epoch_ms(a.get("FireDiscoveryDateTime"), "discovery")
    modified, modified_text = _epoch_ms(a.get("ModifiedOnDateTime_dt"), "modification")
    if discovered > modified or modified > fetched:
        raise ValueError("discovery/modification chronology invalid")
    initial_lat = a.get("InitialLatitude")
    initial_lon = a.get("InitialLongitude")
    if initial_lat is None or initial_lon is None:
        initial_point = None
    else:
        initial_point = [
            _number(initial_lon, "initial longitude", -180, 180),
            _number(initial_lat, "initial latitude", -90, 90),
        ]
    size = a.get("IncidentSize")
    if size is not None:
        size = _number(size, "incident size", 0)
    contained = a.get("PercentContained")
    if contained is not None:
        contained = _number(contained, "percent contained", 0, 100)
    out_at = a.get("FireOutDateTime")
    out_text = None
    if out_at is not None:
        out_moment, out_text = _epoch_ms(out_at, "fire out")
        if out_moment < discovered or out_moment > fetched:
            raise ValueError("fire out time is outside discovery/fetch interval")
    return {
        "status": "candidate_unreviewed",
        "active_status_verified": False,
        "irwin_id": irwin_id,
        "object_id": a["OBJECTID"],
        "incident_name": name,
        "point_lonlat": [lon, lat],
        "initial_point_lonlat": initial_point,
        "discovered_at_utc": discovered_text,
        "modified_at_utc": modified_text,
        "fire_out_at_utc": out_text,
        "size_acres": size,
        "percent_contained": contained,
        "fetched_at_utc": fetched_at_utc,
        "feature_reference_url": f"{_POINT_SERVICE}/{a['OBJECTID']}",
        "ids_raw_sha256": sha256(ids_raw).hexdigest(),
        "features_raw_sha256": sha256(features_raw).hexdigest(),
        "point_is_fire_boundary": False,
    }


def perimeter_candidate(ids_raw: bytes, features_raw: bytes,
                        irwin_id: str, fetched_at_utc: str) -> dict:
    """Return dated perimeter metadata; do not return polygon coordinates."""
    irwin_id = _expected_irwin(irwin_id)
    fetched = _utc_text(fetched_at_utc)
    features = _paired(ids_raw, features_raw)
    if not features:
        return {
            "status": "perimeter_unavailable",
            "irwin_id": irwin_id,
            "fetched_at_utc": fetched_at_utc,
            "absence_means_no_fire": False,
            "ids_raw_sha256": sha256(ids_raw).hexdigest(),
            "features_raw_sha256": sha256(features_raw).hexdigest(),
        }
    matches = [f for f in features
               if f["attributes"].get("attr_IrwinID") == irwin_id
               or f["attributes"].get("poly_IRWINID") == irwin_id]
    if len(matches) != 1:
        raise ValueError("expected exactly one matching perimeter")
    feature = matches[0]
    a = feature["attributes"]
    if a.get("attr_IrwinID") != irwin_id or a.get("poly_IRWINID") != irwin_id:
        raise ValueError("perimeter incident IDs disagree")
    if (a.get("poly_FeatureAccess") != "Public" or
            a.get("poly_FeatureStatus") != "Approved" or
            a.get("poly_IsVisible") != "Yes"):
        raise ValueError("perimeter is not public, approved, and visible")
    name = a.get("poly_IncidentName")
    method = a.get("poly_MapMethod")
    if (not isinstance(name, str) or not name.strip() or len(name) > 256 or
            not isinstance(method, str) or not method.strip() or len(method) > 256):
        raise ValueError("invalid perimeter name or map method")
    captured, captured_text = _epoch_ms(a.get("poly_PolygonDateTime"), "polygon capture")
    edited, edited_text = _epoch_ms(a.get("poly_DateCurrent"), "polygon edit")
    if captured > edited or edited > fetched:
        raise ValueError("perimeter capture/edit chronology invalid")
    acres = a.get("poly_GISAcres")
    if acres is not None:
        acres = _number(acres, "GIS acres", 0)
    geometry = feature.get("geometry")
    rings = geometry.get("rings") if isinstance(geometry, dict) else None
    if not isinstance(rings, list) or not rings or len(rings) > 1000:
        raise ValueError("invalid perimeter rings")
    coordinates = []
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
            raise ValueError("open or invalid perimeter ring")
        coordinates.extend(ring)
        if len(coordinates) > 50_000:
            raise ValueError("perimeter has too many vertices")
    for xy in coordinates:
        if not isinstance(xy, list) or len(xy) != 2:
            raise ValueError("invalid perimeter vertex")
        _number(xy[0], "polygon longitude", -180, 180)
        _number(xy[1], "polygon latitude", -90, 90)
    return {
        "status": "candidate_unreviewed",
        "irwin_id": irwin_id,
        "object_id": a["OBJECTID"],
        "incident_name": name,
        "map_method": method,
        "captured_at_utc": captured_text,
        "edited_at_utc": edited_text,
        "gis_acres": acres,
        "bbox_lonlat": [
            min(xy[0] for xy in coordinates),
            min(xy[1] for xy in coordinates),
            max(xy[0] for xy in coordinates),
            max(xy[1] for xy in coordinates),
        ],
        "ring_count": len(rings),
        "vertex_count": len(coordinates),
        "public_approved_visible": True,
        "topology_validated": False,
        "polygon_redistribution_approved": False,
        "fetched_at_utc": fetched_at_utc,
        "feature_reference_url": f"{_PERIMETER_SERVICE}/{a['OBJECTID']}",
        "ids_raw_sha256": sha256(ids_raw).hexdigest(),
        "features_raw_sha256": sha256(features_raw).hexdigest(),
    }
_QUERY_PATH = (
    "/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)
_QUERY_FIELDS = (
    "OBJECTID,GlobalID,IrwinID,IncidentName,IncidentTypeCategory,"
    "FireDiscoveryDateTime,ModifiedOnDateTime_dt,IncidentSize,PercentContained,"
    "FireOutDateTime,InitialLatitude,InitialLongitude"
)
_API_FIELDS = [
    "features[].attributes.OBJECTID",
    "features[].attributes.IrwinID",
    "features[].attributes.IncidentName",
    "features[].attributes.IncidentTypeCategory",
    "features[].attributes.FireDiscoveryDateTime",
    "features[].attributes.ModifiedOnDateTime_dt",
    "features[].attributes.IncidentSize",
    "features[].attributes.PercentContained",
    "features[].attributes.FireOutDateTime",
    "features[].attributes.InitialLatitude",
    "features[].attributes.InitialLongitude",
    "features[].geometry.x",
    "features[].geometry.y",
]


def _query_url(value: str, irwin_id: str, *, ids: bool) -> str:
    """Validate a narrow, exact WFIGS query URL; do not verify transport."""
    if (not isinstance(value, str) or len(value) > 4096 or
            any(char.isspace() or ord(char) < 32 or ord(char) == 127
                for char in value)):
        raise ValueError("invalid WFIGS acquisition URL")
    parts = urlsplit(value)
    if (parts.scheme != "https" or parts.netloc != "services3.arcgis.com"
            or parts.path != _QUERY_PATH or parts.fragment):
        raise ValueError("WFIGS acquisition URL outside exact endpoint")
    try:
        query = parse_qs(parts.query, strict_parsing=True, keep_blank_values=True)
    except ValueError as exc:
        raise ValueError("malformed WFIGS query") from exc
    if any(len(values) != 1 for values in query.values()):
        raise ValueError("ambiguous WFIGS query parameter")
    actual = {key: values[0] for key, values in query.items()}
    expected = {"f": "json", "where": "IrwinID='" + irwin_id + "'"}
    if ids:
        expected["returnIdsOnly"] = "true"
    else:
        expected.update({
            "outFields": _QUERY_FIELDS,
            "returnGeometry": "true",
            "outSR": "4326",
            "orderByFields": "OBJECTID ASC",
            "resultRecordCount": "10",
        })
    if actual != expected:
        raise ValueError("WFIGS query does not match bounded IRWIN selector")
    return value


def reported_record_proposal(
    ids_raw: bytes, features_raw: bytes, irwin_id: str, *,
    ids_query_url: str, feature_query_url: str,
    first_seen_at_utc: str, fetched_at_utc: str,
    proposed_acceptance_at_utc: str,
) -> dict:
    """Draft a complete incident-v1 reported record for exact human review.

    This does not verify transport, authenticate a reviewer, construct a
    VerifiedSource, append evidence, or publish a snapshot. The trusted caller
    must independently verify the acquisition receipts and present every field
    of this exact draft for authenticated per-record review before acceptance.
    """
    irwin_id = _expected_irwin(irwin_id)
    _query_url(ids_query_url, irwin_id, ids=True)
    source_url = _query_url(feature_query_url, irwin_id, ids=False)
    first = _utc_text(first_seen_at_utc)
    fetched = _utc_text(fetched_at_utc)
    proposed = _utc_text(proposed_acceptance_at_utc)
    if first > fetched or fetched > proposed:
        raise ValueError("record draft chronology invalid")
    if len(_paired(ids_raw, features_raw)) != 1:
        raise ValueError("narrow IRWIN query must return exactly one feature")
    point = incident_candidate(ids_raw, features_raw, irwin_id, fetched_at_utc)
    return {
        "source_id": "wfigs",
        "item_id": irwin_id[1:-1],
        "revision": 1,
        "source_url": source_url,
        "raw_sha256": point["features_raw_sha256"],
        "provider": "Wildland Fire Interagency Geospatial Services",
        "license": "WFIGS public layer; redistribution terms unresolved",
        "source_type": "official_api",
        "category": "hazard",
        "source_kind": "reported",
        "published_at": None,
        "observed_at": None,
        "valid_from": None,
        "valid_through": None,
        "message_expires_at": None,
        "first_seen_at": first_seen_at_utc,
        "fetched_at": fetched_at_utc,
        "accepted_at": proposed_acceptance_at_utc,
        "correction_available_at": None,
        "superseded_at": None,
        "supersedes": None,
        "retracted": False,
        "source_reference": {"api_fields": list(_API_FIELDS)},
        "geometry": {"type": "Point", "coordinates": point["point_lonlat"]},
        "precision": "point",
        "area_label": None,
        "source_uncertainty": (
            "Reported incident point, not a perimeter or observed fire front; "
            "source modification is an edit time, not an observation; "
            "reuse rights require separate review."
        ),
        "payload": {
            "incident_name": point["incident_name"],
            "incident_type_category": "WF",
            "size_acres": point["size_acres"],
            "percent_contained": point["percent_contained"],
            "discovered_at": point["discovered_at_utc"],
            "source_modified_at": point["modified_at_utc"],
            "fire_out_at": point["fire_out_at_utc"],
            "initial_point_lonlat": point["initial_point_lonlat"],
            "feature_reference_url": point["feature_reference_url"],
        },
    }
