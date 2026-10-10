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


def _raw_json(raw: bytes, label: str, max_bytes: int) -> dict:
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise ValueError(f"{label} size or type invalid")
    try:
        value = json.loads(raw)
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
