"""Validated frozen values shared by the intake service boundary."""
from dataclasses import dataclass
import hashlib
import json
import re


class Conflict(ValueError):
    """An existing record is bound to a different request or source."""


class Forbidden(PermissionError):
    """The actor is not assigned or permitted to perform this action."""


class Missing(KeyError):
    """The requested intake record does not exist."""


def bounded_text(value, name, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a nonempty string of at most {limit} characters")
    return value


def nonnegative_int(value, name):
    if type(value) is not int or value < 0 or value > 9223372036854775807:
        raise ValueError(f"{name} must be an exact nonnegative SQLite integer")
    return value


def sha256_text(value, name):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def canonical_json(value):
    """Reject non-JSON values and nonfinite numbers rather than coercing them."""
    def validate(item):
        if item is None or type(item) in (str, bool, int, float):
            return
        if type(item) is list:
            for child in item: validate(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values(): validate(child)
            return
        raise ValueError("value must contain only JSON-compatible values")
    validate(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionSeed:
    case_id: str
    run_id: str
    dispatch_id: str
    vehicle_id: str
    destination_node: str
    expected_count: int
    boarding_event_id: str
    arrival_event_id: str
    source_sha256: str
    # Live ledger departure events do not carry person_ids. Preserve both references.
    departure_event_id: str | None = None

    def __post_init__(self):
        for name in ("case_id", "run_id", "dispatch_id", "vehicle_id", "destination_node",
                     "boarding_event_id", "arrival_event_id"):
            bounded_text(getattr(self, name), name)
        nonnegative_int(self.expected_count, "expected_count")
        sha256_text(self.source_sha256, "source_sha256")
        if self.departure_event_id is not None:
            bounded_text(self.departure_event_id, "departure_event_id")


@dataclass(frozen=True)
class Principal:
    actor_id: str
    role: str
    session_ids: frozenset[str]

    def __post_init__(self):
        bounded_text(self.actor_id, "actor_id")
        if self.role not in ("volunteer", "coordinator", "care_reviewer"):
            raise ValueError("unknown intake role")
        if type(self.session_ids) is not frozenset:
            raise ValueError("session_ids must be a frozenset")
        for session_id in self.session_ids: bounded_text(session_id, "session_id")


@dataclass(frozen=True)
class Assessment:
    arrival_id: str
    image_sha256: str | None
    arrival_revision: int
    result: str
    origin: str
    reason: str
    model_revision: str | None

    def __post_init__(self):
        bounded_text(self.arrival_id, "arrival_id")
        nonnegative_int(self.arrival_revision, "arrival_revision")
        if self.image_sha256 is not None: sha256_text(self.image_sha256, "image_sha256")
        if self.result not in ("Yes", "No", "Unsure"): raise ValueError("unknown assessment result")
        if self.origin not in ("scripted_training", "evaluated_model", "unavailable"):
            raise ValueError("unknown assessment origin")
        bounded_text(self.reason, "reason", 4096)
        if self.model_revision is not None: bounded_text(self.model_revision, "model_revision")
