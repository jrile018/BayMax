"""CPU-only view binding for one accepted incident snapshot and hypothetical inputs.

The trusted caller supplies the reviewed snapshot hash. This adapter neither
authenticates sources nor converts WGS84 evidence into metric render geometry.
"""
from dataclasses import dataclass
import hashlib
import json
import re

from contracts.incident import VERSION, projection_input


_HASH = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_BYTES = 32 * 1024 * 1024
_MAX_BRANCHES = 32


@dataclass(frozen=True)
class AdaptedIncident:
    metadata: dict
    branches: tuple[dict, ...]


def _copy(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > _MAX_BYTES:
            raise ValueError("incident view input exceeds byte limit")
        return json.loads(raw)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("incident view requires bounded finite JSON") from exc


def _hash(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def adapt_incident(snapshot, branches, *, expected_snapshot_hash):
    """Bind an externally trusted cutoff snapshot to labeled hypothetical inputs.

    The expected hash must come from a trusted producer/export manifest.
    A self-hashed, attacker-supplied snapshot does not establish authenticity.
    Branches are exact outputs of the reviewed projection_input callable;
    this adapter performs no forecast or operational calculation.
    """
    if not isinstance(expected_snapshot_hash, str) or not _HASH.fullmatch(expected_snapshot_hash):
        raise ValueError("trusted snapshot hash must be lowercase SHA256")
    source = _copy(snapshot)
    if not isinstance(source, dict) or source.get("schema_version") != VERSION:
        raise ValueError("frozen incident snapshot version required")
    recorded = source.get("snapshot_hash")
    if recorded != expected_snapshot_hash or not _HASH.fullmatch(recorded):
        raise ValueError("trusted snapshot hash binding mismatch")
    unsigned = {key: value for key, value in source.items() if key != "snapshot_hash"}
    if _hash(unsigned) != recorded:
        raise ValueError("incident snapshot hash mismatch")
    if not isinstance(branches, (tuple, list)) or len(branches) > _MAX_BRANCHES:
        raise ValueError("hypothetical branches must be a bounded sequence")
    seen = set()
    views = []
    for item in branches:
        entry = _copy(item)
        if not isinstance(entry, dict) or set(entry) != {"branch_id", "input"}:
            raise ValueError("branch requires branch_id and projection input")
        branch_id, supplied = entry["branch_id"], entry["input"]
        if not isinstance(branch_id, str) or not _ID.fullmatch(branch_id):
            raise ValueError("branch ID must be stable bounded text")
        if branch_id in seen:
            raise ValueError("duplicate hypothetical branch ID")
        seen.add(branch_id)
        if not isinstance(supplied, dict):
            raise ValueError("projection input must be a JSON object")
        if supplied.get("initial_snapshot_hash") != recorded:
            raise ValueError("branches must share the same accepted snapshot")
        try:
            reproduced = projection_input(
                source, horizon_minutes=supplied["horizon_minutes"],
                model_version=supplied["model_version"],
                assumptions=supplied["authored_assumptions"],
                training_assumptions=supplied["authored_training_assumptions"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid projection input") from exc
        if _hash(supplied) != _hash(reproduced):
            raise ValueError("projection input differs from frozen contract output")
        views.append({
            "branch_id": branch_id,
            "label": "hypothetical",
            "initial_snapshot_hash": recorded,
            "can_calculate_operational_outcomes": False,
            "input": supplied,
        })
    metadata = {
        "schema_version": VERSION,
        "snapshot_hash": recorded,
        "cutoff_utc": source["cutoff_utc"],
        "source_snapshot": source,
        "accepted_categories": source["categories"],
        "unconfirmed_leads": source["unconfirmed_leads"],
        "source_health": source["source_health"],
        "geographic_projection": "none",
        "operational_outcomes": "unavailable",
        "hash_semantics": "snapshot_hash binds the accepted cutoff; projection inputs are authored hypothetical branches",
    }
    return AdaptedIncident(metadata, tuple(views))
