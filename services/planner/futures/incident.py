"""Pinned, evidence-only incident projection envelopes for the reviewed v1 contract.

This adapter does not map claims to roads or calculate operational outcomes.
Trusted application code must supply the EvidenceLog snapshot and its projection
input; their hashes provide integrity, not source authentication.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from collections.abc import Mapping
from typing import Any


INCIDENT_SCHEMA_VERSION = "knight26-incident-v1"
ADAPTER_VERSION = "incident-futures-v1"
SUPPORTED_MODEL_VERSION = "scenario-v1"
REVIEWED_CONTRACT_SHA256 = "e456253dfee508171ceb45a818560d002f47b58ef8d79968dc041c245489fc1f"


def _copy_json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("incident input must be finite JSON") from exc


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def pin_incident_projection(
    accepted_snapshot: Mapping[str, Any],
    reviewed_projection_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy and bind known-at evidence without claiming operational capability.

    `contracts.incident` must be the exact reviewed v1 dependency. The full
    snapshot is retained because projection_input omits superseded history.
    """
    if not isinstance(accepted_snapshot, Mapping) or not isinstance(reviewed_projection_input, Mapping):
        raise TypeError("snapshot and projection input must be mappings")
    snapshot = _copy_json(dict(accepted_snapshot))
    projection = _copy_json(dict(reviewed_projection_input))
    if (snapshot.get("schema_version") != INCIDENT_SCHEMA_VERSION or
            projection.get("schema_version") != INCIDENT_SCHEMA_VERSION or
            projection.get("projection_input_version") != INCIDENT_SCHEMA_VERSION):
        raise ValueError("unsupported incident contract version")
    if projection.get("model_version") != SUPPORTED_MODEL_VERSION:
        raise ValueError("unsupported incident scenario model version")

    # Re-derive the complete projection from the frozen root contract. This
    # validates the snapshot hash and every field of the supplied projection,
    # including cutoff, source references, assumptions, and capability flags.
    from contracts import incident as contract
    if (contract.VERSION != INCIDENT_SCHEMA_VERSION or
            hashlib.sha256(Path(contract.__file__).read_bytes()).hexdigest() != REVIEWED_CONTRACT_SHA256):
        raise ValueError("incident contract is not the frozen reviewed v1 source")

    expected = contract.projection_input(
        snapshot,
        horizon_minutes=projection.get("horizon_minutes"),
        model_version=projection["model_version"],
        assumptions=projection.get("authored_assumptions"),
        training_assumptions=projection.get("authored_training_assumptions"),
    )
    if _digest(projection) != _digest(expected):
        raise ValueError("projection input does not match accepted snapshot and reviewed contract")
    if projection["can_calculate_operational_outcomes"] is not False:
        raise ValueError("incident v1 cannot authorize operational outcomes")

    envelope = {
        "adapter_version": ADAPTER_VERSION,
        "schema_version": INCIDENT_SCHEMA_VERSION,
        "model_version": projection["model_version"],
        "incident_id": snapshot["incident_id"],
        "cutoff_utc": snapshot["cutoff_utc"],
        "initial_snapshot_hash": snapshot["snapshot_hash"],
        "projection_input_hash": projection["projection_input_hash"],
        "accepted_snapshot": snapshot,
        "projection_input": projection,
        "ledger_watermark": snapshot["ledger_watermark"],
        "in_flight_commitments": snapshot["in_flight_commitments"],
        "operational_outcomes_available": False,
        "calibrated": False,
        "frequency_label": "uncalibrated_scenario_frequencies",
        "scenario_branches": [],
        "status": "evidence_only_pending_routing_and_typed_completeness",
    }
    envelope["projection_hash"] = _digest(envelope)
    return _copy_json(envelope)
