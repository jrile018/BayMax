"""Deterministic first-action policies over the currently visible simulator view."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable


_KINDS = frozenset({"evacuation", "medical", "supply"})
_HUMANITARIAN_TIER = {"evacuation": 0, "medical": 0, "supply": 1}


def _finite_nonnegative(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _nonempty_string(name: str, value: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True)
class Candidate:
    """A dispatch action composed only of information available at decision time."""

    action_id: str
    vehicle_id: str
    request_id: str
    kind: str
    quantity: int
    arrival_time_s: float
    deadline_s: float | None
    travel_s: float
    route_id: str
    forecast_margin_s: float | None = None
    feasible: bool = True

    def __post_init__(self) -> None:
        for name in ("action_id", "vehicle_id", "request_id", "route_id"):
            _nonempty_string(name, getattr(self, name))
        if not isinstance(self.kind, str):
            raise TypeError("kind must be a string")
        if self.kind not in _KINDS:
            raise ValueError(f"unsupported kind: {self.kind!r}")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        _finite_nonnegative("arrival_time_s", self.arrival_time_s)
        _finite_nonnegative("travel_s", self.travel_s)
        if self.deadline_s is not None:
            _finite_nonnegative("deadline_s", self.deadline_s)
        if self.forecast_margin_s is not None:
            if isinstance(self.forecast_margin_s, bool) or not isinstance(
                self.forecast_margin_s, (int, float)
            ):
                raise TypeError("forecast_margin_s must be a finite number or None")
            if not math.isfinite(self.forecast_margin_s):
                raise ValueError("forecast_margin_s must be finite or None")
        if not isinstance(self.feasible, bool):
            raise TypeError("feasible must be a bool")


@dataclass(frozen=True)
class PolicyView:
    """The explicit visible snapshot passed to a policy; it has no hidden-future field."""

    time_s: float
    observations: tuple[dict, ...]
    candidates: tuple[Candidate, ...]

    def __post_init__(self) -> None:
        _finite_nonnegative("time_s", self.time_s)
        if not isinstance(self.observations, tuple):
            raise TypeError("observations must be a tuple")
        if any(not isinstance(item, dict) for item in self.observations):
            raise TypeError("observations must contain dictionaries")
        if not isinstance(self.candidates, tuple):
            raise TypeError("candidates must be a tuple")
        if any(not isinstance(item, Candidate) for item in self.candidates):
            raise TypeError("candidates must contain Candidate records")


@runtime_checkable
class Policy(Protocol):
    name: str

    def choose(self, view: PolicyView) -> Candidate | None: ...


def _is_usable(candidate: Candidate) -> bool:
    # A known negative full-traversal margin is a hard safety exclusion.
    return candidate.feasible and (
        candidate.forecast_margin_s is None or candidate.forecast_margin_s >= 0
    )


def _priority_key(candidate: Candidate) -> tuple:
    deadline = candidate.deadline_s if candidate.deadline_s is not None else math.inf
    return (
        _HUMANITARIAN_TIER[candidate.kind],
        deadline,
        candidate.travel_s,
        candidate.action_id,
        candidate.vehicle_id,
        candidate.request_id,
        candidate.route_id,
    )


def _choose_priority(candidates: tuple[Candidate, ...] | list[Candidate]) -> Candidate | None:
    usable = (candidate for candidate in candidates if _is_usable(candidate))
    return min(usable, key=_priority_key, default=None)


class PriorityGreedy:
    """Choose by humanitarian tier, deadline, travel time, then stable identifiers."""

    name: ClassVar[str] = "priority_greedy"

    def choose(self, view: PolicyView) -> Candidate | None:
        return _choose_priority(view.candidates)


class AdaptiveDispatch:
    """Prefer larger known safety margin among routes for the same vehicle and request."""

    name: ClassVar[str] = "adaptive_dispatch"

    def choose(self, view: PolicyView) -> Candidate | None:
        usable = [candidate for candidate in view.candidates if _is_usable(candidate)]
        if not usable:
            return None

        # Keep service urgency ahead of route choice across distinct requests.
        best_service = min(
            (_HUMANITARIAN_TIER[c.kind],
             c.deadline_s if c.deadline_s is not None else math.inf)
            for c in usable
        )
        urgent = [
            c for c in usable
            if (
                _HUMANITARIAN_TIER[c.kind],
                c.deadline_s if c.deadline_s is not None else math.inf,
            ) == best_service
        ]

        by_pair: dict[tuple[str, str], list[Candidate]] = {}
        for candidate in urgent:
            by_pair.setdefault((candidate.vehicle_id, candidate.request_id), []).append(candidate)

        pair_winners = []
        for options in by_pair.values():
            # Known nonnegative forecasts outrank unknown forecasts. Among known
            # forecasts, more seconds of full-traversal margin wins before travel.
            pair_winners.append(min(
                options,
                key=lambda c: (
                    c.forecast_margin_s is None,
                    -(c.forecast_margin_s if c.forecast_margin_s is not None else 0.0),
                    c.travel_s,
                    c.action_id,
                    c.route_id,
                ),
            ))
        return min(
            pair_winners,
            key=lambda c: (
                c.travel_s, c.action_id, c.vehicle_id, c.request_id, c.route_id
            ),
        )


class StaticDispatch:
    """Freeze each vehicle/request's first-view route choice and retain it thereafter."""

    name: ClassVar[str] = "static_dispatch"

    def __init__(self) -> None:
        self._initialized = False
        self._route_choices: dict[tuple[str, str], str] = {}

    def choose(self, view: PolicyView) -> Candidate | None:
        if not self._initialized:
            self._initialized = True
            initial = [candidate for candidate in view.candidates if _is_usable(candidate)]
            initial.sort(key=_priority_key)
            for candidate in initial:
                pair = (candidate.vehicle_id, candidate.request_id)
                self._route_choices.setdefault(pair, candidate.route_id)

        retained = [
            candidate
            for candidate in view.candidates
            if _is_usable(candidate)
            and self._route_choices.get((candidate.vehicle_id, candidate.request_id))
            == candidate.route_id
        ]
        return _choose_priority(retained)
