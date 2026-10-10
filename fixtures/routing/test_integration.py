"""Regression checks for independent ledger review and real engine rollback."""
import unittest
from unittest.mock import patch
from dataclasses import replace
from services.planner.ledger import Ledger, LedgerError, Vehicle, Request, Destination
from services.routing import candidate_routes, Closure, SafetySnapshot
from test_trip import setup, vehicle

class IntegrationTests(unittest.TestCase):
    def test_public_keyword_names(self):
        _,_,l,_=setup()
        l.update_eta("dispatch1",arrival_eta_s=20)
        l.mark_departed("dispatch1",0)
        l.record_arrival("dispatch1",20,arrived_node="D")
        l.complete_service("dispatch1",20,arrived_node="D")
        self.assertTrue(l.check_invariants())

    def test_vehicle_cannot_reenter_past_after_actual_completion(self):
        l=Ledger([Vehicle("v","truck","A",0,5)],
          [Request("r","supply","A","D",goods={"w":5}),Request("r2","supply","D","E",goods={"w":5})],
          [],{"A":{"w":5},"D":{"w":5}})
        route=dict(status="feasible",safety_validated=True,source_node="A",destination_node="D",
                   departure_s=0,arrival_s=10,edge_ids=["ad"])
        l.commit_dispatch("d","v","r",route,0)
        l.mark_departed("d",0); l.record_arrival("d",100,"D"); l.complete_service("d",100,"D")
        before=l.export_state()
        with self.assertRaises(LedgerError):
            l.commit_dispatch("d2","v","r2",dict(route,source_node="D",destination_node="E"),0)
        self.assertEqual(before,l.export_state())

    def test_accepted_roundoff_does_not_reject_actual_graph_arrival(self):
        g,s,l,e=setup(loading=2)
        # New isolated executor: a tiny serialization roundoff is accepted at dispatch.
        l2=Ledger([Vehicle("v","bus","A",2,0)],
          [Request("r","evacuation","A","D",("p1","p2"))],[Destination("d","D","shelter",2)],{})
        from services.routing.trip import TripExecutor
        e2=TripExecutor(g,l2)
        route=candidate_routes(g,"A","D","bus",2,s).routes[0]
        route=replace(route,departure_s=2+5e-9,arrival_s=22+5e-9,
                      legs=tuple(replace(leg,entry_s=leg.entry_s+5e-9,exit_s=leg.exit_s+5e-9) for leg in route.legs))
        e2.dispatch("d","v","r",route,s,loading_s=2)
        e2.advance(22,s)
        self.assertEqual(e2.snapshot()["trips"][0]["phase"],"completed")

    def test_loading_failed_replan_can_strand_before_loading_complete(self):
        g,s,l,e=setup(loading=3)
        e.advance(1,s)
        closure=SafetySnapshot("k1",1,1,1000,
            tuple(Closure(x,1,100,1,1,"no path") for x in ("ab","ac")),
            provenance="fictional",safe_nodes=frozenset(g.nodes))
        e.replan("dispatch1",closure,"r","all exits closed")
        self.assertEqual(vehicle(e)["phase"],"stranded")
        self.assertEqual(vehicle(e)["passengers"],[])
        self.assertEqual(l.export_state()["outcome_totals"]["safe_evacuated_people"],0)
        self.assertTrue(l.check_invariants())

    def test_service_unsafe_destination_retains_people_and_capacity(self):
        g,s,l,e=setup(service=2)
        e.advance(20,s)
        uncertain=SafetySnapshot("k1",20,20,1000,provenance="destination unverified")
        e.advance(22,uncertain)
        self.assertEqual(vehicle(e)["phase"],"stranded")
        self.assertEqual(l.export_state()["outcome_totals"]["safe_evacuated_people"],0)
        self.assertTrue(l.check_invariants())

    def test_real_ledger_service_exception_restores_full_engine_and_ledger(self):
        g,s,l,e=setup(service=2)
        e.advance(5,s)
        before=e.snapshot()
        original=l.complete_service
        def fail_after_mutation(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError("injected after actual resource transfer")
        with patch.object(l,"complete_service",side_effect=fail_after_mutation):
            with self.assertRaises(RuntimeError):
                e.advance(22,s)
        self.assertEqual(e.snapshot(),before)
        e.advance(22,s)
        self.assertEqual(l.export_state()["outcome_totals"]["safe_evacuated_people"],2)
        self.assertTrue(l.check_invariants())

    def test_danger_during_unfinished_service_cannot_be_erased_by_later_safety(self):
        g,s,l,e=setup(service=10)
        e.advance(24,s)
        unsafe=SafetySnapshot("k1",24,24,1000,provenance="D known unsafe")
        e.advance(25,unsafe)
        self.assertEqual(vehicle(e)["phase"],"stranded")
        restored=SafetySnapshot("k2",25,25,1000,provenance="D later safe",safe_nodes=frozenset(g.nodes))
        e.advance(30,restored)
        self.assertEqual(l.export_state()["outcome_totals"]["safe_evacuated_people"],0)
        self.assertEqual(vehicle(e)["passengers"],["p1","p2"])
        self.assertTrue(l.check_invariants())

    def test_service_coverage_gap_cannot_count_continuous_service(self):
        g,s,l,e=setup(service=10)
        e.advance(24,s)
        ends=SafetySnapshot("k1",24,24,24,provenance="coverage ends",safe_nodes=frozenset(g.nodes))
        e.advance(25,ends)
        self.assertEqual(vehicle(e)["phase"],"stranded")

    def test_dispatch_timing_tolerances_cannot_compose_past_actual_arrival(self):
        g,s,l,e=setup(loading=2)
        from services.routing.trip import TripExecutor
        ledger=Ledger([Vehicle("v","bus","A",2,0)],
          [Request("r","evacuation","A","D",("p1","p2"))],[Destination("d","D","shelter",2)],{})
        executor=TripExecutor(g,ledger)
        route=candidate_routes(g,"A","D","bus",2,s).routes[0]
        route=replace(route,departure_s=2+7.5e-9,arrival_s=22+15e-9,
                      legs=tuple(replace(leg,entry_s=leg.entry_s+7.5e-9,exit_s=leg.exit_s+7.5e-9) for leg in route.legs))
        with self.assertRaises(ValueError):
            executor.dispatch("d","v","r",route,s,loading_s=2)
        self.assertEqual(executor.snapshot()["trips"],[])

if __name__=="__main__":
    unittest.main()
