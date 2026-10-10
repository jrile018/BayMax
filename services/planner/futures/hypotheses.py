"""Source-pinned, authored hypothetical hazard timelines.

These timelines do not infer access, resources, probabilities, or dispatch outcomes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any

from .incident import _copy_json, _digest, pin_incident_projection

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_REF_KEYS = {"source_id", "item_id", "revision", "raw_sha256"}
_SPEC_KEYS = {"branch_id", "accepted_hazard_refs", "authored_assumptions", "hypothetical_events"}
_EVENT_KEYS = {"event_id", "time_utc", "source_ref", "description"}
_MAX_BRANCHES = 16
_MAX_EVENTS = 128
_MAX_BYTES = 262144


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise ValueError("timestamp must be a UTC second with Z suffix")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError("invalid UTC timestamp")
    return parsed


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a bounded stable identifier")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 4096:
        raise ValueError(f"{label} must be nonempty bounded text")
    return value


def _ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _REF_KEYS:
        raise ValueError("source reference has unexpected fields")
    result = _copy_json(value)
    _id(result["source_id"], "source_id")
    _id(result["item_id"], "item_id")
    if type(result["revision"]) is not int or result["revision"] < 1:
        raise ValueError("revision must be a positive integer")
    digest = result["raw_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("raw_sha256 must be lowercase hex")
    return result


def _accepted_hazards(parent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    categories = parent["accepted_snapshot"]["categories"]
    claims = categories.get("hazard") or []
    refs = parent["projection_input"]["accepted_source_refs"]
    permitted = {_digest(_ref(ref)) for ref in refs}
    result = {}
    for claim in claims:
        ref = {key: claim[key] for key in _REF_KEYS}
        key = _digest(_ref(ref))
        if key in permitted:
            result[key] = claim
    return result


def materialize_hypothetical_branches(
    pinned_projection: Mapping[str, Any], branch_specs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind authored futures to active accepted hazard claims only."""
    if not isinstance(pinned_projection, Mapping):
        raise TypeError("pinned projection must be a mapping")
    parent = _copy_json(dict(pinned_projection))
    if not isinstance(parent, dict) or parent.get("scenario_branches") != []:
        raise ValueError("expected an evidence-only pinned projection")
    if parent.get("projection_hash") != _digest({k: v for k, v in parent.items() if k != "projection_hash"}):
        raise ValueError("pinned projection hash mismatch")
    expected = pin_incident_projection(parent["accepted_snapshot"], parent["projection_input"])
    if _digest(expected) != _digest(parent):
        raise ValueError("pinned projection differs from reviewed envelope")
    if isinstance(branch_specs, (str, bytes)) or not isinstance(branch_specs, Sequence):
        raise TypeError("branch specs must be a sequence")
    if not 1 <= len(branch_specs) <= _MAX_BRANCHES:
        raise ValueError("branch specs exceed bounds")
    specs = _copy_json(list(branch_specs))
    if len(json.dumps(specs, ensure_ascii=False).encode("utf-8")) > _MAX_BYTES:
        raise ValueError("branch specs exceed byte bound")
    cutoff = _utc(parent["cutoff_utc"])
    end = cutoff + timedelta(minutes=parent["projection_input"]["horizon_minutes"])
    hazards = _accepted_hazards(parent)
    branches = []
    seen_branches = set()
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) != _SPEC_KEYS:
            raise ValueError("branch spec has unexpected fields")
        branch_id = _id(spec["branch_id"], "branch_id")
        if branch_id in seen_branches:
            raise ValueError("duplicate branch ID")
        seen_branches.add(branch_id)
        assumptions = spec["authored_assumptions"]
        if not isinstance(assumptions, dict) or not assumptions or len(assumptions) > 16:
            raise ValueError("explicit authored assumptions required")
        for name, description in assumptions.items():
            _id(name, "assumption key")
            _text(description, "assumption text")
        refs = spec["accepted_hazard_refs"]
        if not isinstance(refs, list) or not 1 <= len(refs) <= 32:
            raise ValueError("accepted hazard refs required")
        seen_refs = set()
        claims = []
        for raw_ref in refs:
            key = _digest(_ref(raw_ref))
            if key in seen_refs or key not in hazards:
                raise ValueError("hazard ref is duplicate or not an active accepted hazard")
            seen_refs.add(key)
            claims.append(hazards[key])
        raw_events = spec["hypothetical_events"]
        if not isinstance(raw_events, list) or len(raw_events) > _MAX_EVENTS:
            raise ValueError("too many hypothetical events")
        seen_events = set()
        events = []
        for raw in raw_events:
            if not isinstance(raw, dict) or set(raw) != _EVENT_KEYS:
                raise ValueError("event has unexpected fields")
            event_id = _id(raw["event_id"], "event_id")
            if event_id in seen_events:
                raise ValueError("duplicate event ID")
            seen_events.add(event_id)
            instant = _utc(raw["time_utc"])
            if not cutoff < instant < end:
                raise ValueError("event is outside the half-open future horizon")
            if _digest(_ref(raw["source_ref"])) not in seen_refs:
                raise ValueError("event source is not pinned to this branch")
            _text(raw["description"], "event description")
            events.append({**raw, "lane": "authored_hypothetical"})
        events.sort(key=lambda event: (event["time_utc"], event["event_id"]))
        branch = {
            "branch_id": branch_id,
            "incident_id": parent["incident_id"],
            "cutoff_utc": parent["cutoff_utc"],
            "initial_snapshot_hash": parent["initial_snapshot_hash"],
            "projection_input_hash": parent["projection_input_hash"],
            "ledger_watermark": parent["ledger_watermark"],
            "in_flight_commitments": parent["in_flight_commitments"],
            "source_health": parent["accepted_snapshot"]["source_health"],
            "accepted_hazard_refs": refs,
            "accepted_hazard_claims": claims,
            "authored_assumptions": assumptions,
            "hypothetical_events": events,
            "provenance": "authored_hypothetical_uncalibrated",
            "operational_outcomes_available": False,
            "calibrated": False,
        }
        branch["branch_hash"] = _digest(branch)
        branches.append(branch)
    parent["scenario_branches"] = branches
    parent["status"] = "hypothetical_hazards_only_pending_routing_and_typed_completeness"
    parent["projection_hash"] = _digest({k: v for k, v in parent.items() if k != "projection_hash"})
    return _copy_json(parent)


def known_at_view(branch: Mapping[str, Any], time_utc: str) -> dict[str, Any]:
    """Show accepted initial hazards beside time-gated authored events."""
    if not isinstance(branch, Mapping):
        raise TypeError("branch must be a mapping")
    pinned = _copy_json(dict(branch))
    recorded = pinned.pop("branch_hash", None)
    if recorded != _digest(pinned) or pinned.get("provenance") != "authored_hypothetical_uncalibrated":
        raise ValueError("branch hash or provenance mismatch")
    instant = _utc(time_utc)
    if instant < _utc(pinned["cutoff_utc"]):
        raise ValueError("known-at view predates accepted cutoff")
    return _copy_json({
        "branch_id": pinned["branch_id"],
        "cutoff_utc": pinned["cutoff_utc"],
        "view_time_utc": time_utc,
        "accepted_hazard_claims": pinned["accepted_hazard_claims"],
        "hypothetical_events": [event for event in pinned["hypothetical_events"]
                                if _utc(event["time_utc"]) <= instant],
        "provenance": pinned["provenance"],
        "operational_outcomes_available": False,
    })
