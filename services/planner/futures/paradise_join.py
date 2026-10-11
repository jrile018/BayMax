"""Join an immutable accepted publication to a separate Paradise exercise input.

No statewide alert is localized to Paradise by this module. The output is an
as-known source context plus authored, unverified scenario assumptions, not a
calibrated forecast, road/resource claim, or dispatch recommendation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

from contracts.incident import projection_input
from integration.incident_artifacts import PUBLICATION_VERSION
from .incident import (
    SUPPORTED_MODEL_VERSION, _copy_json, _digest, pin_incident_projection,
)

JOIN_VERSION = "paradise-hypothetical-join-v1"
AREA_SHA256 = "8d30c559e94bdcf6fd3db8db7c442015a874d94fb060a0273656535f2c9b0cb6"
MANIFEST_SHA256 = "e58dbf698d3a50bba58bd23ddc806eeb5458094f19b99a053e697ef8604f0f5e"
RAW_OSM_SHA256 = "b73334f6280cc756fee13ab9687ccbd7d47368785f0703fea9dafd97c6035897"
AREA_DIR = Path(__file__).resolve().parents[3] / "fixtures/geography/paradise"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z\Z")
_ASSUMPTION_KEYS = {"weather", "fuel", "ignition"}
_PUBLICATION_KEYS = {
    "publication_version", "incident_id", "cutoff_utc", "mission_hash",
    "view_hash", "snapshot", "projection_input", "geography_binding",
    "metadata_attestations", "synopsis", "capabilities",
}


def _regular_bytes(fd: int, name: str, maximum: int) -> bytes:
    try:
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                          dir_fd=fd)
    except OSError as exc:
        raise ValueError("unsafe or missing publication/geography file") from exc
    try:
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError("publication or geography input is not a bounded regular file")
        chunks = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum:
            raise ValueError("publication or geography input exceeds byte limit")
        return data
    finally:
        os.close(file_fd)


def _directory_fd(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts or str(path) == "/":
        raise ValueError("publication directory must be an absolute trusted path")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY |
                              os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _json_bytes(data: bytes) -> dict:
    try:
        value = json.loads(data.decode("utf-8"))
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError,
            OverflowError, RecursionError) as exc:
        raise ValueError("publication requires canonical finite UTF-8 JSON") from exc
    if not isinstance(value, dict) or canonical != data:
        raise ValueError("publication requires canonical JSON object")
    return value


def _load_publication(directory: Path) -> tuple[dict, str]:
    fd = _directory_fd(directory)
    try:
        pointer = _json_bytes(_regular_bytes(fd, "current.json", 4096))
        if (set(pointer) != {"publication_version", "view_hash",
                             "publication_file", "publication_sha256"} or
                pointer["publication_version"] != PUBLICATION_VERSION or
                not isinstance(pointer["view_hash"], str) or
                not _SHA.fullmatch(pointer["view_hash"]) or
                not isinstance(pointer["publication_sha256"], str) or
                not _SHA.fullmatch(pointer["publication_sha256"]) or
                pointer["publication_file"] !=
                "publication-" + pointer["view_hash"] + ".json"):
            raise ValueError("invalid accepted publication pointer")
        content = _regular_bytes(fd, pointer["publication_file"], 16_777_216)
        digest = hashlib.sha256(content).hexdigest()
        if digest != pointer["publication_sha256"]:
            raise ValueError("accepted publication artifact hash mismatch")
        publication = _json_bytes(content)
    finally:
        os.close(fd)
    if publication.get("view_hash") != pointer["view_hash"]:
        raise ValueError("accepted publication view hash mismatch")
    return publication, digest


def _checked_area() -> dict:
    fd = _directory_fd(AREA_DIR)
    try:
        area_bytes = _regular_bytes(fd, "area.json", 2_000_000)
        manifest_bytes = _regular_bytes(fd, "source_manifest.json", 65_536)
        osm_bytes = _regular_bytes(fd, "raw.osm", 2_000_000)
    finally:
        os.close(fd)
    if (hashlib.sha256(area_bytes).hexdigest() != AREA_SHA256 or
            hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256 or
            hashlib.sha256(osm_bytes).hexdigest() != RAW_OSM_SHA256):
        raise ValueError("Paradise geography fixture differs from reviewed bytes")
    area = json.loads(area_bytes)
    manifest = json.loads(manifest_bytes)
    if (not isinstance(area, dict) or area.get("area_id") != "paradise-ca" or
            area.get("source_manifest") != "source_manifest.json" or
            not isinstance(manifest, dict) or
            manifest.get("raw_sha256") != RAW_OSM_SHA256 or
            manifest.get("coverage_bbox_lonlat") != area.get("coverage_bbox_lonlat")):
        raise ValueError("Paradise geography manifest mismatch")
    return {
        "area_id": "paradise-ca",
        "label": area["label"],
        "county_context": "Butte County (authored exercise label)",
        "bbox_lonlat": area["bbox_lonlat"],
        "coverage_bbox_lonlat": area["coverage_bbox_lonlat"],
        "area_sha256": AREA_SHA256,
        "source_manifest_sha256": MANIFEST_SHA256,
        "raw_osm_sha256": RAW_OSM_SHA256,
        "status": "versioned_exercise_geography_not_accepted_incident_binding",
        "unavailable_layers": sorted(
            item["layer"] for item in area["coverage"]
            if item["status"] == "unavailable"),
    }


def _bbox(value, label):
    if (not isinstance(value, list) or len(value) != 4 or
            any(type(item) not in (int, float) or not math.isfinite(item)
                for item in value) or
            not -180 <= value[0] < value[2] <= 180 or
            not -90 <= value[1] < value[3] <= 90):
        raise ValueError(label + " requires a valid WGS84 bbox")
    return value


def _checked_publication(publication: dict) -> dict:
    if not isinstance(publication, dict) or set(publication) != _PUBLICATION_KEYS:
        raise ValueError("accepted publication has unsupported fields")
    if publication["publication_version"] != PUBLICATION_VERSION:
        raise ValueError("unsupported accepted publication version")
    capabilities = publication["capabilities"]
    if (not isinstance(capabilities, dict) or
            set(capabilities) != {"can_calculate_operational_outcomes", "can_dispatch"} or
            capabilities["can_calculate_operational_outcomes"] is not False or
            capabilities["can_dispatch"] is not False):
        raise ValueError("accepted publication cannot authorize operations")
    snapshot = publication["snapshot"]
    if (not isinstance(snapshot, dict) or
            publication["incident_id"] != snapshot.get("incident_id") or
            publication["cutoff_utc"] != snapshot.get("cutoff_utc")):
        raise ValueError("accepted publication identity mismatch")
    _bbox(snapshot.get("bbox_lonlat"), "accepted source scope")
    mission = {
        "publication_version": PUBLICATION_VERSION,
        "incident_id": snapshot["incident_id"],
        "bbox_lonlat": snapshot["bbox_lonlat"],
        "cutoff_utc": snapshot["cutoff_utc"],
        "categories": snapshot["categories"],
        "revision_history": snapshot["revision_history"],
        "unconfirmed_leads": snapshot["unconfirmed_leads"],
        "accepted_source_refs": snapshot["accepted_source_refs"],
        "ledger_watermark": snapshot["ledger_watermark"],
        "in_flight_commitments": snapshot["in_flight_commitments"],
        "metadata_attestations": publication["metadata_attestations"],
        "geography_binding": publication["geography_binding"],
    }
    if _digest(mission) != publication["mission_hash"]:
        raise ValueError("accepted publication mission hash mismatch")
    published_projection = publication["projection_input"]
    if published_projection is not None:
        pin_incident_projection(snapshot, published_projection)
        published_projection_hash = published_projection["projection_input_hash"]
    else:
        published_projection_hash = None
    view = {
        "publication_version": PUBLICATION_VERSION,
        "mission_hash": publication["mission_hash"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "source_health": snapshot["source_health"],
        "synopsis": publication["synopsis"],
        "projection_input_hash": published_projection_hash,
    }
    if _digest(view) != publication["view_hash"]:
        raise ValueError("accepted publication view hash mismatch")
    return snapshot


def _authored(assumptions):
    if not isinstance(assumptions, dict) or set(assumptions) != _ASSUMPTION_KEYS:
        raise ValueError("weather, fuel, and ignition require explicit authored assumptions")
    result = {}
    for name, value in assumptions.items():
        if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 1024:
            raise ValueError(name + " requires bounded authored text")
        result[name] = value
    result["exercise_scope"] = (
        "Paradise/Butte exercise only; statewide accepted claims are cutoff "
        "context, not verified local hazard, road, resource, or forecast input")
    return result


def _utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise ValueError(label + " requires UTC Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(label + " is not a real UTC instant") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError(label + " requires UTC")
    return parsed


def join_current_paradise(publication_directory, *,
                          expected_publication_sha256: str,
                          caller_as_of_utc: str,
                          horizon_minutes: int,
                          authored_assumptions: dict[str, str]) -> dict:
    """Read an application-pinned publication, then derive a separate exercise."""
    if (not isinstance(expected_publication_sha256, str) or
            not _SHA.fullmatch(expected_publication_sha256)):
        raise ValueError("trusted expected publication SHA-256 is required")
    publication, artifact_sha256 = _load_publication(Path(publication_directory))
    if artifact_sha256 != expected_publication_sha256:
        raise ValueError("current publication differs from trusted expected identity")
    snapshot = _checked_publication(publication)
    area = _checked_area()
    accepted_bbox = _bbox(snapshot["bbox_lonlat"], "accepted source scope")
    exercise_bbox = _bbox(area["bbox_lonlat"], "Paradise exercise area")
    if not (accepted_bbox[0] <= exercise_bbox[0] and
            accepted_bbox[1] <= exercise_bbox[1] and
            accepted_bbox[2] >= exercise_bbox[2] and
            accepted_bbox[3] >= exercise_bbox[3]):
        raise ValueError("Paradise exercise area is outside accepted source scope")
    authored = _authored(authored_assumptions)
    if type(horizon_minutes) is not int or not 1 <= horizon_minutes <= 1440:
        raise ValueError("exercise horizon_minutes must be 1..1440")
    cutoff = _utc(snapshot["cutoff_utc"], "accepted cutoff")
    caller_as_of = _utc(caller_as_of_utc, "caller as-of")
    if caller_as_of < cutoff:
        raise ValueError("caller as-of cannot predate accepted cutoff")
    end = cutoff + timedelta(minutes=horizon_minutes)
    horizon_end_utc = end.isoformat(timespec="microseconds").replace("+00:00", "Z")
    projected = projection_input(
        snapshot, horizon_minutes=horizon_minutes,
        model_version=SUPPORTED_MODEL_VERSION, assumptions=authored)
    pinned = pin_incident_projection(snapshot, projected)
    result = {
        "join_version": JOIN_VERSION,
        "accepted_publication": {
            "incident_id": publication["incident_id"],
            "view_hash": publication["view_hash"],
            "mission_hash": publication["mission_hash"],
            "snapshot_hash": snapshot["snapshot_hash"],
            "artifact_sha256": artifact_sha256,
            "cutoff_utc": snapshot["cutoff_utc"],
            "published_projection_input_hash": (
                publication["projection_input"]["projection_input_hash"]
                if publication["projection_input"] is not None else None),
            "source_health": snapshot["source_health"],
            "source_health_as_of_utc": snapshot["cutoff_utc"],
            "geography_binding": publication["geography_binding"],
            "role": "statewide_as_known_context_only",
        },
        "exercise_area": area,
        "spatial_link_status": "unverified_for_paradise",
        "accepted_local_hazard_refs": [],
        "pinned_projection": pinned,
        "assumption_provenance": "authored_exercise_unverified",
        "model_execution": "none_metadata_only",
        "caller_as_of_utc": caller_as_of_utc,
        "horizon_end_utc": horizon_end_utc,
        "horizon_expired_at_caller_as_of": caller_as_of >= end,
        "forecast_available": False,
        "operational_outcomes_available": False,
        "calibrated": False,
        "can_dispatch": False,
    }
    result["join_hash"] = _digest(result)
    return _copy_json(result)
