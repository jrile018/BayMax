"""Trip-only fault regressions. Stub ledger is labeled and proves no ledger outcomes."""
import unittest
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from services.routing import Edge, Graph, Closure, SafetySnapshot, candidate_routes
from services.routing.trip import TripExecutor

class StubLedger:
    # The actual ledger is an external dependency, temporarily unavailable at approval boundary.
    def __init__(self):
        self.state={}
        self.fail_eta=False
        self.fail_strand=False
        self.fail_complete=False
    @contextmanager
    def transaction(self):
        before=deepcopy(self.state)
        try:
            yield self
        except BaseException:
            self.state=before
            raise
    def commit_dispatch(self,d,v,r,route,now_s,**kwargs):
        self.state[d]={"phase":"loading","eta":route["arrival_s"]}
        return SimpleNamespace(person_ids=("p1",),cargo={},loading_complete_s=now_s+kwargs["loading_s"],service_s=kwargs["service_s"])
    def mark_departed(self,d,now_s):
        self.state[d]["phase"]="traveling"
    def record_arrival(self,d,now_s,arrived_node,safe=True):
        self.state[d]["phase"]="servicing"
    def complete_service(self,d,now_s,arrived_node,safe=True):
        if self.fail_complete:
            raise ValueError("injected ledger failure")
        self.state[d]["phase"]="completed"
        return {"fixture_only":True}
    def strand(self,d,now_s,reason):
        if self.fail_strand:
            raise ValueError("injected ledger failure")
        self.state[d]["phase"]="stranded"
    def update_eta(self,d,eta):
        if self.fail_eta:
            raise ValueError("injected ledger failure")
        self.state[d]["eta"]=eta
    def export_state(self):
        return deepcopy(self.state)

def build(collapsed=False):
    nodes={"A":(0,0),"B":(0,0) if collapsed else (100,0),"C":(100,100),"D":(200,0)}
    edges=[Edge("ab","A","B",0 if collapsed else 100,10),
           Edge("bd","B","D",200 if collapsed else 100,10),
           Edge("bc","B","C",141.421356 if collapsed else 100,10),
           Edge("cd","C","D",141.421356,15)]
    graph=Graph(nodes,edges)
    safety=SafetySnapshot("k0",0,0,1000,provenance="fictional",safe_nodes=frozenset(nodes))
    ledger=StubLedger()
    engine=TripExecutor(graph,ledger)
    route=candidate_routes(graph,"A","D","bus",0,safety).routes[0]
    engine.dispatch("d","v","r",route,safety)
    return graph,safety,ledger,engine

class TripFaultTests(unittest.TestCase):
    def test_collapsed_connector_still_spends_declared_travel_time(self):
        g,s,l,e=build(True)
        e.advance(5,s)
        t=e.snapshot()["trips"][0]
        self.assertEqual(t["completed_edge_ids"],[])
        self.assertEqual(t["current_edge"]["edge_id"],"ab")
        self.assertEqual(t["position_m"],[0,0])
        updated=SafetySnapshot("k1",5,5,1000,provenance="fictional",safe_nodes=frozenset(g.nodes))
        result=e.replan("d",updated,"r","new observation")
        self.assertEqual(result.routes[0].departure_s,10)
        self.assertEqual(e.snapshot()["trips"][0]["eta_arrival_s"],20)
    def test_failed_service_advance_rolls_back_entire_authoritative_state(self):
        g,s,l,e=build()
        before=e.snapshot()
        l.fail_complete=True
        with self.assertRaises(ValueError):
            e.advance(25,s)
        self.assertEqual(e.snapshot(),before)
        l.fail_complete=False
        e.advance(5,s)
        self.assertEqual(e.snapshot()["trips"][0]["position_m"],[50,0])
    def test_failed_eta_update_preserves_old_route_and_events(self):
        g,s,l,e=build()
        e.advance(5,s)
        before=e.snapshot()
        newer=SafetySnapshot("k1",5,5,1000,(Closure("bd",5,100,5,5,"closure"),),
                             provenance="fictional",safe_nodes=frozenset(g.nodes))
        l.fail_eta=True
        with self.assertRaises(ValueError):
            e.replan("d",newer,"r","new closure")
        self.assertEqual(e.snapshot(),before)
    def test_failed_strand_preserves_state_and_allows_retry(self):
        g,s,l,e=build()
        e.advance(5,s)
        before=e.snapshot()
        newer=SafetySnapshot("k1",5,5,1000,(Closure("ab",5,100,5,5,"closure"),),
                             provenance="fictional",safe_nodes=frozenset(g.nodes))
        l.fail_strand=True
        with self.assertRaises(ValueError):
            e.replan("d",newer,"r","unsafe current edge")
        self.assertEqual(e.snapshot(),before)
        l.fail_strand=False
        e.replan("d",newer,"r","unsafe current edge")
        self.assertEqual(e.snapshot()["trips"][0]["phase"],"stranded")

if __name__=="__main__":
    unittest.main()
