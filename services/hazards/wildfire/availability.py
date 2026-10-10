"""Temporal availability gate for wildfire source metadata.

This validates when dated inputs could have been known, not the truth of the
source or any current-incident claim.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import math
from urllib.parse import urlsplit

_ALLOWED_KINDS = frozenset({"synthetic", "observed", "mapped", "model_reference"})


def _datetime(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} requires a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} requires a timezone")
    return parsed.astimezone(timezone.utc)


def source_availability(source_ledger, epoch_utc, issued_time_s):
    """Return dated evidence availability for an issue time in epoch seconds.

    All retrieved timestamps and any observed timestamps must precede the
    issue. Returned ledger data is independent of the caller's input.
    """
    epoch = _datetime(epoch_utc, "epoch_utc")
    if (isinstance(issued_time_s, bool) or not isinstance(issued_time_s, (int, float))
            or not math.isfinite(issued_time_s) or issued_time_s < 0):
        raise ValueError("issued_time_s must be finite and nonnegative")
    issue = float(issued_time_s)
    if not isinstance(source_ledger, (list, tuple)) or not source_ledger:
        raise ValueError("source_ledger must be a nonempty sequence")
    ids = []
    seen = set()
    latest = epoch
    for source in source_ledger:
        if not isinstance(source, dict):
            raise ValueError("source ledger entry must be a mapping")
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError("source IDs must be unique nonempty strings")
        seen.add(source_id)
        ids.append(source_id)
        kind = source.get("kind")
        if not isinstance(kind, str) or kind not in _ALLOWED_KINDS:
            raise ValueError("unknown source kind")
        license_label = source.get("license")
        if not isinstance(license_label, str) or not license_label.strip():
            raise ValueError("source requires a nonempty license/rights label")
        if kind != "synthetic":
            uri = source.get("uri")
            if not isinstance(uri, str) or not uri or uri != uri.strip() or any(ch.isspace() for ch in uri):
                raise ValueError("nonsynthetic source requires an HTTP(S) URI")
            try:
                parts = urlsplit(uri)
                valid_uri = parts.scheme in ("http", "https") and bool(parts.hostname)
            except ValueError:
                valid_uri = False
            if not valid_uri:
                raise ValueError("nonsynthetic source requires an HTTP(S) URI")
        retrieved = _datetime(source.get("retrieved_at_utc"), "retrieved_at_utc")
        observed_raw = source.get("observed_at_utc")
        if kind == "observed" and observed_raw is None:
            raise ValueError("observed source needs observed_at_utc")
        if observed_raw is not None:
            observed = _datetime(observed_raw, "observed_at_utc")
            if observed > retrieved:
                raise ValueError("observed_at_utc cannot follow retrieval")
            latest = max(latest, observed)
        latest = max(latest, retrieved)
    available_from = max(0.0, (latest - epoch).total_seconds())
    if issue < available_from:
        raise ValueError("forecast issued before source metadata was available")
    return {"status": "available", "epoch_utc": epoch_utc,
            "checked_at_s": issue, "available_from_s": available_from,
            "source_ids": ids, "source_ledger": copy.deepcopy(list(source_ledger))}
