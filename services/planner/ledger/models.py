"""Resource records for the fictional aid simulation; all quantities are explicit units."""
from dataclasses import dataclass, field

class LedgerError(ValueError):
    pass

@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    kind: str
    node_id: str
    seats: int = 0
    cargo_capacity: int = 0

@dataclass(frozen=True)
class Request:
    request_id: str
    kind: str
    origin_node: str
    destination_node: str
    person_ids: tuple = ()
    goods: dict = field(default_factory=dict)
    deadline_s: float | None = None

@dataclass(frozen=True)
class Destination:
    destination_id: str
    node_id: str
    kind: str
    capacity: int

@dataclass
class Assignment:
    dispatch_id: str
    vehicle_id: str
    request_id: str
    person_ids: tuple
    cargo: dict
    loading_complete_s: float
    service_s: float
    arrival_eta_s: float
    created_s: float
    phase: str = "loading"
    actual_departure_s: float | None = None
    arrival_actual_s: float | None = None
    destination_id: str | None = None
    travel_s: float = 0
    last_event_s: float = 0
