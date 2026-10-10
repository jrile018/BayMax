"""Known interval adapter. This is input validation, not a physical fire model."""
from dataclasses import dataclass
from math import isfinite
from .models import finite_nonnegative

@dataclass(frozen=True)
class Closure:
    edge_id: str
    start_s: float
    end_s: float
    issued_s: float
    received_s: float
    reason: str
    evidence: str = "fictional hazard interval"

    def __post_init__(self):
        for name in ("start_s","end_s","issued_s","received_s"):
            finite_nonnegative(getattr(self,name),name)
        if self.end_s<=self.start_s or self.received_s<self.issued_s:
            raise ValueError("closure needs increasing interval and received>=issued")

@dataclass(frozen=True)
class SafetySnapshot:
    version: str
    known_at_s: float
    issued_s: float
    horizon_s: float
    closures: tuple[Closure,...] = ()
    safety_buffer_s: float = 0
    covered_edges: frozenset[str] | None = None
    provenance: str = "declared scenario interval assumptions"

    safe_nodes: frozenset[str] = frozenset()
    operational_enabled: bool = True

    def __post_init__(self):
        for name in ("known_at_s","issued_s","horizon_s","safety_buffer_s"):
            finite_nonnegative(getattr(self,name),name)
        if self.issued_s>self.known_at_s or self.horizon_s<self.issued_s or not self.provenance:
            raise ValueError("invalid forecast issue/horizon/provenance")
        if type(self.operational_enabled) is not bool:
            raise ValueError("operational_enabled must be Boolean")

    def visible_closures(self, edge_id):
        return tuple(c for c in self.closures if c.edge_id==edge_id
                     and c.issued_s<=self.known_at_s and c.received_s<=self.known_at_s)

    def open_now(self, edge_id, when_s):
        return self.operational_enabled and not any(
            c.start_s<=when_s<c.end_s for c in self.visible_closures(edge_id))

    def traversal(self, edge_id, entry_s, exit_s):
        finite_nonnegative(entry_s,"entry_s")
        finite_nonnegative(exit_s,"exit_s")
        if entry_s<self.known_at_s or exit_s<entry_s:
            raise ValueError("traversal must not precede available information")
        if not self.operational_enabled:
            return False,"operational_disabled",self.provenance
        end=exit_s+self.safety_buffer_s
        if end>self.horizon_s or (self.covered_edges is not None and edge_id not in self.covered_edges):
            return False,"unknown_coverage",self.provenance
        for c in self.visible_closures(edge_id):
            # Half-open traversals permit exact exit at closure start with zero buffer.
            if (entry_s==end and c.start_s<=entry_s<c.end_s) or max(entry_s,c.start_s)<min(end,c.end_s):
                return False,"closed_during_traversal",f"{c.reason}; {c.evidence}; issued={c.issued_s}; received={c.received_s}"
        return True,"safe_under_declared_intervals",self.provenance

    def destination_safe(self,node_id,when_s):
        return (self.operational_enabled and self.known_at_s<=when_s<=self.horizon_s
                and node_id in self.safe_nodes)
