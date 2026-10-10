"""Restore physical trips and exactly-once commitments, rather than display-only state."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
from services.routing import Graph, Edge, Closure, SafetySnapshot
from services.routing.trip import TripExecutor
from test_trip import setup, vehicle

def clone(e,g):
    return TripExecutor.from_checkpoint(g,json.loads(json.dumps(e.checkpoint())))

class CheckpointTests(unittest.TestCase):
    def test_mid_edge_roundtrip_matches_uninterrupted_service(self):
        g,s,l,e=setup(service=2); e.advance(5,s)
        restored=clone(e,g)
        self.assertEqual(restored.snapshot(),e.snapshot())
        self.assertEqual(vehicle(restored)["position_m"],[50,0])
        e.advance(22,s); restored.advance(22,s)
        self.assertEqual(restored.snapshot(),e.snapshot())
        self.assertEqual(restored.ledger.export_state()["outcome_totals"]["safe_evacuated_people"],2)
    def test_service_and_loading_roundtrip(self):
        for when in (2,23,25):
            g,s,l,e=setup(loading=3,service=2); e.advance(when,s)
            restored=clone(e,g)
            self.assertEqual(restored.snapshot(),e.snapshot())
            e.advance(30,s); restored.advance(30,s)
            self.assertEqual(restored.snapshot(),e.snapshot())
    def test_branches_independent_and_known_history_preserved(self):
        g,s,l,e=setup(service=2); e.advance(5,s)
        newer=SafetySnapshot("k1",5,5,1000,(Closure("bd",5,100,5,5,"closure"),),
                             provenance="fictional",safe_nodes=frozenset(g.nodes))
        e.replan("dispatch1",newer,"report","closed road")
        original=e.snapshot()
        a=clone(e,g); b=clone(e,g)
        before=a.snapshot()
        a.replan("dispatch1",newer,"report","closed road")
        self.assertEqual(a.snapshot(),before)
        with self.assertRaises(ValueError):
            a.advance(10,s)
        a.advance(37,newer)
        self.assertEqual(e.snapshot(),original)
        self.assertEqual(b.snapshot(),original)
        self.assertEqual(a.ledger.export_state()["outcome_totals"]["safe_evacuated_people"],2)
        self.assertEqual(b.ledger.export_state()["outcome_totals"]["safe_evacuated_people"],0)
    def test_duplicate_original_dispatch_after_reroute_restore(self):
        g,s,l,e=setup(); e.advance(5,s)
        newer=SafetySnapshot("k1",5,5,1000,(Closure("bd",5,100,5,5,"closure"),),
                             provenance="fictional",safe_nodes=frozenset(g.nodes))
        e.replan("dispatch1",newer,"report","closed road")
        restored=clone(e,g); before=restored.snapshot()
        # Signature is preserved even though the current route starts at a future junction.
        original=json.loads(restored.trips["dispatch1"].signature)
        from services.routing.checkpoint import route_from_dict
        restored.dispatch("dispatch1","bus1","evac1",route_from_dict(original[2]),newer)
        self.assertEqual(restored.snapshot(),before)
    def test_stranded_completed_and_collapsed_connector_states(self):
        g,s,l,e=setup(); e.advance(5,s)
        unsafe=SafetySnapshot("k1",5,5,1000,(Closure("ab",5,100,5,5,"closure"),),
                              provenance="fictional",safe_nodes=frozenset(g.nodes))
        e.replan("dispatch1",unsafe,"r","closure")
        restored=clone(e,g); e.advance(25,unsafe); restored.advance(25,unsafe)
        self.assertEqual(restored.snapshot(),e.snapshot())
        self.assertEqual(vehicle(restored)["exposure_s"],20)
        # Zero geometric length cannot reconstruct timing from distance; entry time must be saved.
        from services.planner.ledger import Ledger, Vehicle, Request, Destination
        from services.routing import candidate_routes
        g=Graph({"A":(0,0),"D":(0,0)},[Edge("ad","A","D",0,10)])
        s=SafetySnapshot("k",0,0,100,provenance="fictional",safe_nodes=frozenset(g.nodes))
        ledger=Ledger([Vehicle("v","bus","A",1,0)],[Request("r","evacuation","A","D",("p",))],
                      [Destination("d","D","shelter",1)],{})
        e=TripExecutor(g,ledger); e.dispatch("d","v","r",candidate_routes(g,"A","D","bus",0,s).routes[0],s)
        e.advance(5,s); restored=clone(e,g)
        restored.advance(9,s); self.assertEqual(vehicle(restored)["phase"],"traveling")
        restored.advance(10,s); self.assertEqual(vehicle(restored)["phase"],"completed")
        again=clone(restored,g); self.assertEqual(again.snapshot(),restored.snapshot())
    def test_exact_exit_closure_preserves_reached_junction_after_restore(self):
        g,s,l,e=setup(); e.advance(5,s); restored=clone(e,g)
        closes=SafetySnapshot("k1",5,5,1000,(Closure("ab",10,100,5,5,"closes at exit"),),
                              provenance="fictional",safe_nodes=frozenset(g.nodes))
        restored.advance(10,closes)
        self.assertEqual(vehicle(restored)["position_m"],[100,0])
        self.assertIn("ab",vehicle(restored)["completed_edge_ids"])
        self.assertEqual(vehicle(restored)["phase"],"traveling")
    def test_failed_suffix_roundtrip_reaches_junction_then_strands(self):
        g,s,l,e=setup(); e.advance(5,s)
        closures=tuple(Closure(eid,5,100,5,5,"blocked suffix") for eid in ("bd","bc"))
        newer=SafetySnapshot("k1",5,5,1000,closures,provenance="fictional",safe_nodes=frozenset(g.nodes))
        e.replan("dispatch1",newer,"report","no suffix")
        restored=clone(e,g)
        self.assertEqual(restored.snapshot(),e.snapshot())
        before=restored.snapshot()
        restored.replan("dispatch1",newer,"report","no suffix")
        self.assertEqual(restored.snapshot(),before)
        e.advance(25,newer); restored.advance(25,newer)
        self.assertEqual(restored.snapshot(),e.snapshot())
        self.assertEqual(vehicle(restored)["position_m"],[100,0])
        self.assertEqual(vehicle(restored)["phase"],"stranded")
        self.assertEqual(vehicle(restored)["exposure_s"],15)
        self.assertEqual(clone(restored,g).snapshot(),restored.snapshot())
    def test_resealed_uncommitted_path_and_missing_trigger_reject(self):
        from services.planner.ledger.checkpoint import seal
        g,s,l,e=setup(); e.advance(5,s)
        payload=e.checkpoint(); payload.pop("checksum")
        payload["trips"]["dispatch1"]["pending"]=["bc","cd"]
        with self.assertRaises(ValueError):
            TripExecutor.from_checkpoint(g,seal(payload))
        newer=SafetySnapshot("k1",5,5,1000,(Closure("bd",5,100,5,5,"closure"),),
                             provenance="fictional",safe_nodes=frozenset(g.nodes))
        e.replan("dispatch1",newer,"report","closed road")
        payload=e.checkpoint(); payload.pop("checksum"); payload["triggers"]=[]
        with self.assertRaises(ValueError):
            TripExecutor.from_checkpoint(g,seal(payload))
    def test_resealed_false_failed_state_and_replaced_route_reject(self):
        from services.planner.ledger.checkpoint import seal
        from services.routing import candidate_routes
        g,s,l,e=setup(); e.advance(5,s)
        payload=e.checkpoint(); payload.pop("checksum")
        payload["trips"]["dispatch1"].update(pending=[],pending_failure="no_feasible_candidate",eta_arrival_s=None)
        with self.assertRaises(ValueError):
            TripExecutor.from_checkpoint(g,seal(payload))
        payload=e.checkpoint(); payload.pop("checksum")
        # A geometrically valid alternative must not replace the committed route.
        detour=candidate_routes(g,"A","D","bus",0,s).routes[-1]
        payload["trips"]["dispatch1"]["route"]=detour.to_dict()
        with self.assertRaises(ValueError):
            TripExecutor.from_checkpoint(g,seal(payload))

    def test_resealed_trail_or_movement_corruption_reject(self):
        from services.planner.ledger.checkpoint import seal
        g,s,l,e=setup(); e.advance(5,s)
        for mutation in ("trail","distance","time","position"):
            payload=e.checkpoint(); payload.pop("checksum")
            if mutation=="trail":
                payload["trips"]["dispatch1"]["trail"].insert(1,[9999,9999])
            else:
                movement=next(x for x in payload["events"] if x["type"]=="movement")
                if mutation=="distance":
                    movement["details"]["distance_m"]=40
                elif mutation=="time":
                    movement["time_s"]=4
                else:
                    movement["details"]["position_m"]=[9999,9999]
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                TripExecutor.from_checkpoint(g,seal(payload))

    def test_graph_identity_schema_and_corruption_reject(self):
        g,s,l,e=setup(); e.advance(5,s)
        changed=Graph(g.nodes,[replace(edge,travel_s=edge.travel_s+1) for edge in g.edges.values()],version=g.version)
        with self.assertRaises(ValueError):
            clone(e,changed)
        for field in ("schema","checksum"):
            payload=deepcopy(e.checkpoint()); payload[field]="invalid"
            with self.assertRaises(ValueError):
                TripExecutor.from_checkpoint(g,payload)

if __name__=="__main__":
    unittest.main()
