"""Actual movement and ledger outcomes on the tiny fictional exercise."""
import unittest
from services.routing import Edge, Graph, Closure, SafetySnapshot, candidate_routes
from services.routing.trip import TripExecutor
from services.planner.ledger import Ledger, Vehicle, Request, Destination

def setup(loading=0,service=0):
    g=Graph({"A":(0,0),"B":(100,0),"C":(100,100),"D":(200,0)},[
        Edge("ab","A","B",100,10),Edge("bd","B","D",100,10),
        Edge("ac","A","C",141.421356,15),Edge("bc","B","C",100,10),
        Edge("cd","C","D",141.421356,15)],version="tiny-v1")
    s=SafetySnapshot("k0",0,0,1000,provenance="fictional exercise",safe_nodes=frozenset(g.nodes))
    ledger=Ledger([Vehicle("bus1","bus","A",2,0)],
                  [Request("evac1","evacuation","A","D",("p1","p2"))],
                  [Destination("shelter1","D","shelter",2)],{})
    engine=TripExecutor(g,ledger)
    route=candidate_routes(g,"A","D","bus",loading,s).routes[0]
    engine.dispatch("dispatch1","bus1","evac1",route,s,loading_s=loading,service_s=service)
    return g,s,ledger,engine

def vehicle(engine):
    return engine.snapshot()["trips"][0]

class TripTests(unittest.TestCase):
    def test_actual_halfway_position_and_route_drive_movement(self):
        g,s,l,e=setup()
        e.advance(5,s)
        t=vehicle(e)
        self.assertEqual(t["position_m"],[50.0,0.0])
        self.assertEqual(t["current_edge"]["edge_id"],"ab")
        self.assertEqual(t["current_edge"]["distance_m"],50)
        self.assertEqual(t["remaining_path"],["ab","bd"])
        self.assertEqual(t["completed_edge_ids"],[])
        self.assertEqual(t["elapsed_s"],5)
        self.assertEqual(t["passengers"],["p1","p2"])
        self.assertEqual(t["phase"],"traveling")
    def test_loading_and_service_are_distinct_from_actual_evacuated_count(self):
        g,s,l,e=setup(loading=3,service=2)
        e.advance(2,s)
        self.assertEqual(vehicle(e)["phase"],"loading")
        self.assertEqual(vehicle(e)["position_m"],[0,0])
        e.advance(3,s)
        self.assertEqual(vehicle(e)["phase"],"traveling")
        e.advance(23,s)
        self.assertEqual(vehicle(e)["phase"],"servicing")
        self.assertEqual(vehicle(e)["position_m"],[200,0])
        e.advance(25,s)
        self.assertEqual(vehicle(e)["phase"],"completed")
        self.assertEqual(vehicle(e)["passengers"],[])
        self.assertEqual(len([x for x in e.snapshot()["events"] if x["type"]=="service_completed"]),1)
        e.advance(40,s)
        self.assertEqual(len([x for x in e.snapshot()["events"] if x["type"]=="service_completed"]),1)
    def test_mid_edge_reroute_preserves_position_load_time_and_reaches_junction(self):
        g,s,l,e=setup(service=2)
        e.advance(5,s)
        before=vehicle(e)
        closure=SafetySnapshot("k1",5,5,1000,(Closure("bd",5,100,5,5,"new road report"),),
                               provenance="fictional exercise",safe_nodes=frozenset(g.nodes))
        result=e.replan("dispatch1",closure,"report1","bridge closed")
        after=vehicle(e)
        self.assertEqual(result.status,"feasible")
        self.assertEqual(after["position_m"],before["position_m"])
        self.assertEqual(after["time_s"],5)
        self.assertEqual(after["passengers"],before["passengers"])
        self.assertEqual(after["remaining_path"],["ab","bc","cd"])
        self.assertEqual(after["eta_arrival_s"],35)
        self.assertEqual(after["route_version"],2)
        e.advance(10,closure)
        self.assertEqual(vehicle(e)["position_m"],[100,0])
        e.advance(15,closure)
        self.assertEqual(vehicle(e)["position_m"],[100,50])
        e.advance(37,closure)
        self.assertEqual(vehicle(e)["completed_edge_ids"],["ab","bc","cd"])
        self.assertEqual(vehicle(e)["phase"],"completed")
    def test_closed_current_edge_strands_at_exact_actual_position(self):
        g,s,l,e=setup()
        e.advance(5,s)
        closure=SafetySnapshot("k1",5,5,1000,(Closure("ab",5,100,5,5,"current-edge closure"),),
                               provenance="fictional exercise",safe_nodes=frozenset(g.nodes))
        e.replan("dispatch1",closure,"report1","unsafe continuation")
        e.advance(25,closure)
        t=vehicle(e)
        self.assertEqual(t["position_m"],[50,0])
        self.assertEqual(t["phase"],"stranded")
        self.assertEqual(t["completed_edge_ids"],[])
        self.assertEqual(t["passengers"],["p1","p2"])
        self.assertEqual(t["exposure_s"],20)
        self.assertIsNone(t["eta_arrival_s"])
        self.assertFalse(any(x["type"]=="service_completed" for x in e.snapshot()["events"]))
    def test_no_candidate_suffix_strands_only_after_reachable_junction(self):
        g,s,l,e=setup()
        e.advance(5,s)
        closures=tuple(Closure(x,5,100,5,5,"blocked suffix") for x in ("bd","bc"))
        newer=SafetySnapshot("k1",5,5,1000,closures,provenance="fictional",safe_nodes=frozenset(g.nodes))
        result=e.replan("dispatch1",newer,"report","no suffix")
        self.assertEqual(result.status,"no_feasible_candidate")
        self.assertEqual(vehicle(e)["position_m"],[50,0])
        e.advance(10,newer)
        self.assertEqual(vehicle(e)["phase"],"stranded")
        self.assertEqual(vehicle(e)["position_m"],[100,0])
    def test_duplicate_advance_and_snapshot_hash_are_stable(self):
        g,s,l,e=setup()
        e.advance(5,s)
        first=e.snapshot()
        e.advance(5,s)
        self.assertEqual(e.snapshot(),first)
    def test_dispatch_checks_actual_safety_instead_of_trusting_route_label(self):
        g,s,l,e=setup()
        other=Ledger([Vehicle("bus2","bus","A",2,0)],
                     [Request("evac2","evacuation","A","D",("x1","x2"))],
                     [Destination("s2","D","shelter",2)],{})
        executor=TripExecutor(g,other)
        route=candidate_routes(g,"A","D","bus",0,s).routes[0]
        blocked=SafetySnapshot("k1",0,0,1000,(Closure("bd",15,100,0,0,"forecast"),),
                               provenance="fictional",safe_nodes=frozenset(g.nodes))
        with self.assertRaises(ValueError):
            executor.dispatch("d2","bus2","evac2",route,blocked)
        self.assertEqual(executor.snapshot()["trips"],[])
    def test_unknown_destination_safety_cannot_count_success(self):
        g,s,l,e=setup()
        uncertain=SafetySnapshot("k1",0,0,1000,provenance="roads only")
        e.advance(20,uncertain)
        self.assertEqual(vehicle(e)["phase"],"stranded")
        self.assertEqual(vehicle(e)["passengers"],["p1","p2"])
    def test_observation_cannot_be_used_before_current_time(self):
        g,s,l,e=setup()
        future=SafetySnapshot("k1",5,5,1000,provenance="future")
        with self.assertRaises(ValueError):
            e.replan("dispatch1",future,"r","future report")
        with self.assertRaises(ValueError):
            e.advance(10,future)

if __name__=="__main__":
    unittest.main()
