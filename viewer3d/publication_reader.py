"""CPU-only reader for an externally pinned incident publication.

The caller owns the directory and supplies the expected publication SHA256 from
a trusted channel. A digest copied from the directory's own current.json is not
an independent trust anchor. This reader authenticates no upstream provider,
renders no geography, and executes no projection or dispatch.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from viewer3d.incident_adapter import AdaptedIncident, adapt_incident


VERSION = "knight26-snapshot-publication-v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_POINTER_MAX = 4096
_PUBLICATION_MAX = 16_777_216


@dataclass(frozen=True)
class PublishedIncident:
    pointer_sha256: str
    publication_sha256: str
    view_hash: str
    mission_hash: str
    snapshot_hash: str
    view: AdaptedIncident


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_constant(value):
    raise ValueError("publication JSON contains non-finite number")


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("publication JSON contains duplicate key")
        value[key] = item
    return value


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                          object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("publication requires valid UTF-8 JSON") from exc


def _read_regular(directory_fd, name, maximum, label):
    try:
        file_fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                          dir_fd=directory_fd)
    except OSError as exc:
        raise ValueError(f"{label} must be a regular file") from exc
    try:
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise ValueError(f"{label} must be a regular file")
        with os.fdopen(file_fd, "rb") as stream:
            file_fd = -1
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError(f"{label} exceeds byte limit")
        return data
    finally:
        if file_fd >= 0:
            os.close(file_fd)


def load_accepted_publication(directory: str | Path, *,
                              expected_publication_sha256: str) -> PublishedIncident:
    """Bind the current root publication to a caller-trusted file digest.

    The directory path itself must be application-owned. The final directory,
    pointer and publication may not be symlinks. A concurrent pointer replacement
    is detected before returning. The incident adapter verifies the snapshot
    hash and retains its null and stale fields unchanged.
    """
    if not isinstance(expected_publication_sha256, str) or not _SHA.fullmatch(
            expected_publication_sha256):
        raise ValueError("trusted publication SHA256 must be lowercase hex")
    try:
        directory_fd = os.open(os.fspath(directory),
                               os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                               os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError("publication directory must be a trusted non-symlink directory") from exc
    try:
        pointer_bytes = _read_regular(directory_fd, "current.json", _POINTER_MAX,
                                      "publication pointer")
        pointer = _json(pointer_bytes)
        if not isinstance(pointer, dict) or set(pointer) != {
                "publication_version", "publication_file",
                "publication_sha256", "view_hash"}:
            raise ValueError("publication pointer has invalid fields")
        view_hash = pointer["view_hash"]
        if (pointer["publication_version"] != VERSION or
                not isinstance(view_hash, str) or not _SHA.fullmatch(view_hash) or
                pointer["publication_file"] != f"publication-{view_hash}.json"):
            raise ValueError("publication filename or version is invalid")
        if pointer["publication_sha256"] != expected_publication_sha256:
            raise ValueError("trusted publication SHA256 does not match current pointer")
        publication_bytes = _read_regular(directory_fd, pointer["publication_file"],
                                          _PUBLICATION_MAX, "publication")
        actual_sha = hashlib.sha256(publication_bytes).hexdigest()
        if actual_sha != expected_publication_sha256:
            raise ValueError("publication digest does not match trusted SHA256")
        publication = _json(publication_bytes)
        if not isinstance(publication, dict) or set(publication) != {
                "publication_version", "incident_id", "cutoff_utc", "mission_hash",
                "view_hash", "snapshot", "projection_input", "geography_binding",
                "metadata_attestations", "synopsis", "capabilities"}:
            raise ValueError("publication has invalid fields")
        capabilities = publication["capabilities"]
        if (not isinstance(capabilities, dict) or set(capabilities) != {
                "can_calculate_operational_outcomes", "can_dispatch"} or
                any(value is not False for value in capabilities.values())):
            raise ValueError("publication capability mismatch")
        if (publication["publication_version"] != VERSION or
                publication["view_hash"] != view_hash or
                not isinstance(publication["mission_hash"], str) or
                not _SHA.fullmatch(publication["mission_hash"])):
            raise ValueError("publication identity mismatch")
        snapshot = publication["snapshot"]
        if not isinstance(snapshot, dict):
            raise ValueError("publication snapshot must be an object")
        if (publication["incident_id"] != snapshot.get("incident_id") or
                publication["cutoff_utc"] != snapshot.get("cutoff_utc")):
            raise ValueError("publication snapshot identity mismatch")
        snapshot_hash = snapshot.get("snapshot_hash")
        view = adapt_incident(snapshot, [], expected_snapshot_hash=snapshot_hash)
        try:
            mission_input = {
                "publication_version": VERSION,
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
        except KeyError as exc:
            raise ValueError("publication mission fields missing") from exc
        if _digest(mission_input) != publication["mission_hash"]:
            raise ValueError("publication mission hash mismatch")
        projection = publication["projection_input"]
        if projection is None:
            projection_hash = None
        else:
            if not isinstance(projection, dict):
                raise ValueError("publication projection input must be an object")
            projection_hash = projection.get("projection_input_hash")
            if (not isinstance(projection_hash, str) or
                    not _SHA.fullmatch(projection_hash) or
                    _digest({key: value for key, value in projection.items()
                             if key != "projection_input_hash"}) != projection_hash or
                    projection.get("initial_snapshot_hash") != snapshot_hash or
                    projection.get("can_calculate_operational_outcomes") is not False):
                raise ValueError("publication projection input hash mismatch")
        view_input = {
            "publication_version": VERSION,
            "mission_hash": publication["mission_hash"],
            "snapshot_hash": snapshot_hash,
            "source_health": snapshot["source_health"],
            "synopsis": publication["synopsis"],
            "projection_input_hash": projection_hash,
        }
        if _digest(view_input) != view_hash:
            raise ValueError("publication view hash mismatch")
        if _read_regular(directory_fd, "current.json", _POINTER_MAX,
                         "publication pointer") != pointer_bytes:
            raise ValueError("publication pointer changed during read")
        return PublishedIncident(
            pointer_sha256=hashlib.sha256(pointer_bytes).hexdigest(),
            publication_sha256=actual_sha,
            view_hash=view_hash,
            mission_hash=publication["mission_hash"],
            snapshot_hash=snapshot_hash,
            view=view)
    finally:
        os.close(directory_fd)
