"""Convert wildfire edge-access forecasts to interval-safe routing input.

The routing package is imported only when this optional bridge is called. A
forecast row establishes coverage for its named edge until its declared end;
an unknown or absent edge never inherits that coverage.
"""
from __future__ import annotations

from collections.abc import Mapping
import math


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return float(value)


def _label(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def safety_snapshot_from_access(rows, known_at_s, version, safe_nodes=(), expected_edge_ids=None):
    """Build a routing snapshot from `edge_access` rows available at `known_at_s`.

    All row issue and coverage starts must already be known. The common horizon
    is the earliest row end, and only explicit `forecast` rows cover edges.
    `expected_edge_ids` accepts graph.edges.keys() or tuple(graph.edges); omitted
    graph edges remain uncovered. Wildfire closures are already buffered, so
    routing receives zero additional safety buffer.
    """
    from services.routing.safety import Closure, SafetySnapshot
    from .availability import source_availability

    known = _time(known_at_s, "known_at_s")
    _label(version, "version")
    def selector_ids(values, name):
        if isinstance(values, (str, bytes, Mapping)):
            raise ValueError(f"{name} must be an iterable of IDs")
        try:
            ids = frozenset(values)
        except TypeError as exc:
            raise ValueError(f"{name} must be an iterable of hashable IDs") from exc
        if any(not isinstance(item, str) or not item for item in ids):
            raise ValueError(f"{name} must contain nonempty string IDs")
        return ids

    expected = selector_ids(expected_edge_ids, "expected_edge_ids") if expected_edge_ids is not None else None
    if expected is not None and not expected:
        raise ValueError("expected_edge_ids must contain edge IDs")
    nodes = selector_ids(safe_nodes, "safe_nodes")
    if isinstance(rows, (str, bytes, Mapping)):
        raise ValueError("rows must be an iterable of edge-access records")
    try:
        records = tuple(rows)
    except TypeError as exc:
        raise ValueError("rows must be iterable") from exc
    if not records:
        raise ValueError("at least one edge-access row is required")

    seen = set()
    covered = set()
    closures = []
    evidence_parts = set()
    horizons = []
    issues = []
    epoch_utc = None
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("edge-access row must be a mapping")
        try:
            edge_id = _label(row["edge_id"], "edge_id")
            if edge_id in seen:
                raise ValueError("duplicate edge ID")
            seen.add(edge_id)
            if expected is not None and edge_id not in expected:
                raise ValueError("edge ID is absent from expected graph")
            status = row["status"]
            if status not in ("forecast", "unknown"):
                raise ValueError("edge-access status must be forecast or unknown")
            issued = _time(row["issued_time_s"], "issued_time_s")
            start = _time(row["coverage_start_s"], "coverage_start_s")
            end = _time(row["coverage_end_s"], "coverage_end_s")
            if issued > known or start > known or issued > start or end <= start or end <= known:
                raise ValueError("forecast issue/coverage is unavailable or expired")
            ids = row["source_ids"]
            if not isinstance(ids, (list, tuple)) or not ids or any(not isinstance(x, str) or not x for x in ids):
                raise ValueError("source_ids must name evidence")
            availability = row["source_availability"]
            if not isinstance(availability, Mapping):
                raise ValueError("source_availability record is required")
            row_epoch = availability["epoch_utc"]
            if epoch_utc is None:
                epoch_utc = row_epoch
            elif row_epoch != epoch_utc:
                raise ValueError("edge-access rows require a common epoch")
            verified = source_availability(availability["source_ledger"], row_epoch, issued)
            for time_key in ("checked_at_s", "available_from_s"):
                _time(availability[time_key], f"source_availability {time_key}")
            for key in ("status", "epoch_utc", "checked_at_s", "available_from_s", "source_ids"):
                if availability.get(key) != verified[key]:
                    raise ValueError(f"source_availability {key} does not match dated ledger")
            if list(ids) != verified["source_ids"]:
                raise ValueError("edge source_ids differ from dated source ledger")
            spatial = _label(row["spatial_rule"], "spatial_rule")
            reason = _label(row["reason"], "reason")
            intervals = row["closed_intervals"]
            if not isinstance(intervals, (list, tuple)):
                raise ValueError("closed_intervals must be a sequence")
            horizons.append(end)
            issues.append(issued)
            source_dates = ",".join(
                f"{item['source_id']}:observed={item.get('observed_at_utc')};retrieved={item['retrieved_at_utc']}"
                for item in verified["source_ledger"])
            evidence = (f"wildfire sources={','.join(ids)}; epoch={row_epoch}; "
                        f"available_from_s={verified['available_from_s']}; checked_at_s={issued}; "
                        f"source_dates={source_dates}; spatial_rule={spatial}; "
                        f"status={status}; reason={reason}")
            evidence_parts.add(evidence)
            if status == "forecast":
                covered.add(edge_id)
            for interval in intervals:
                if not isinstance(interval, Mapping):
                    raise ValueError("closed interval must be a mapping")
                close_start = _time(interval["start_s"], "closure start_s")
                close_end = _time(interval["end_s"], "closure end_s")
                if not start <= close_start < close_end <= end:
                    raise ValueError("closure must lie within its row coverage")
                closures.append(Closure(edge_id, close_start, close_end, issued, known, reason, evidence))
        except (KeyError, TypeError) as exc:
            raise ValueError(f"malformed edge-access row: {exc}") from exc
    return SafetySnapshot(version=version, known_at_s=known, issued_s=max(issues),
                          horizon_s=min(horizons), closures=tuple(closures),
                          safety_buffer_s=0, covered_edges=frozenset(covered),
                          provenance="wildfire edge_access: " + " | ".join(sorted(evidence_parts)),
                          safe_nodes=nodes)
