"""Independent, versioned actual ledger state restoration."""
import json
import unittest
from copy import deepcopy
from services.planner.ledger import Ledger, LedgerError, Vehicle, Request, Destination

def supply():
    l=Ledger([Vehicle("truck","truck","A",0,5)],
      [Request("need","supply","A","D",goods={"water":8})],[],{"A":{"water":10}})
    route=dict(status="feasible",safety_validated=True,source_node="A",destination_node="D",
               departure_s=0,arrival_s=10,edge_ids=["ad"])
    l.commit_dispatch("d","truck","need",route,0,cargo={"water":5},service_s=2)
    return l,route

class CheckpointTests(unittest.TestCase):
    def test_json_roundtrip_preserves_baseline_and_duplicate_dispatch(self):
        l,route=supply()
        payload=json.loads(json.dumps(l.checkpoint()))
        restored=Ledger.from_checkpoint(payload)
        self.assertEqual(restored.export_state(),l.export_state())
        before=restored.export_state()
        restored.commit_dispatch("d","truck","need",route,0,cargo={"water":5},service_s=2)
        self.assertEqual(before,restored.export_state())
        restored.mark_departed("d",0)
        self.assertNotEqual(restored.export_state(),l.export_state())
        self.assertTrue(restored.check_invariants())
        self.assertTrue(l.check_invariants())
    def test_mid_service_restores_and_completes_once(self):
        l,_=supply(); l.mark_departed("d",0); l.record_arrival("d",10,"D")
        restored=Ledger.from_checkpoint(json.loads(json.dumps(l.checkpoint())))
        outcome=restored.complete_service("d",12,"D")
        self.assertEqual(outcome,restored.complete_service("d",12,"D"))
        self.assertEqual(restored.export_state()["delivered"],{"water":5})
        self.assertEqual(restored.export_state()["requests"]["need"]["remaining_goods"],{"water":3})
        self.assertEqual(l.export_state()["delivered"],{})
        self.assertTrue(restored.check_invariants())
    def test_stranded_and_completed_states_roundtrip(self):
        for phase in ("stranded","completed"):
            l,_=supply(); l.mark_departed("d",0)
            if phase=="stranded":
                l.strand("d",5,"closure")
            else:
                l.record_arrival("d",10,"D"); l.complete_service("d",12,"D")
            restored=Ledger.from_checkpoint(json.loads(json.dumps(l.checkpoint())))
            self.assertEqual(restored.export_state(),l.export_state())
            self.assertTrue(restored.check_invariants())
    def test_corruption_and_unknown_schema_rejected(self):
        l,_=supply()
        for field in ("schema","checksum"):
            payload=deepcopy(l.checkpoint()); payload[field]="invalid"
            with self.assertRaises(ValueError):
                Ledger.from_checkpoint(payload)
        payload=deepcopy(l.checkpoint())
        payload["state"]["stocks"]["A"]["water"]+=1
        with self.assertRaises(ValueError):
            Ledger.from_checkpoint(payload)

class CheckpointReviewRegressions(unittest.TestCase):
    def reseal(self,payload):
        from services.planner.ledger.checkpoint import seal
        payload.pop("checksum")
        return seal(payload)

    def test_recomputed_checksum_rejects_boolean_number_substitution(self):
        l,_=supply(); l.mark_departed("d",0); l.record_arrival("d",10,"D"); l.complete_service("d",12,"D")
        payload=l.checkpoint(); payload["state"]["outcomes"]["d"]["on_time"]=1
        with self.assertRaises(LedgerError):
            Ledger.from_checkpoint(self.reseal(payload))

    def test_recomputed_checksum_rejects_noninteger_goods_baseline(self):
        l,_=supply(); payload=l.checkpoint(); payload["initial_goods"]["water"]=10.0
        with self.assertRaises(LedgerError):
            Ledger.from_checkpoint(self.reseal(payload))

    def loading(self):
        l=Ledger([Vehicle("truck","truck","A",0,5)],
                 [Request("need","supply","A","D",goods={"water":8})],[],{"A":{"water":10}})
        route=dict(status="feasible",safety_validated=True,source_node="A",destination_node="D",
                   departure_s=2+5e-9,arrival_s=12+5e-9,edge_ids=["ad"])
        l.commit_dispatch("d","truck","need",route,0,cargo={"water":5},loading_s=2)
        return l

    def test_untouched_loading_roundoff_preserves_exact_state(self):
        l=self.loading(); restored=Ledger.from_checkpoint(json.loads(json.dumps(l.checkpoint())))
        self.assertEqual(restored.export_state(),l.export_state())
        self.assertEqual(restored.assignments["d"].travel_s,l.assignments["d"].travel_s)

    def test_loading_reroute_then_strand_roundtrip(self):
        l=self.loading(); l.update_eta("d",20); l.strand("d",1,"closure before pickup")
        restored=Ledger.from_checkpoint(json.loads(json.dumps(l.checkpoint())))
        self.assertEqual(restored.export_state(),l.export_state())
        self.assertIsNone(restored.assignments["d"].actual_departure_s)
        self.assertEqual(restored.vehicles["truck"]["commitment"],"d")
        self.assertTrue(restored.check_invariants())

    def test_same_time_vehicle_reuse_follows_audit_order(self):
        l=Ledger([Vehicle("truck","truck","A",0,1)],
                 [Request(r,"supply","A","A",goods={"water":1}) for r in ("r1","r2")],[],{"A":{"water":2}})
        route=dict(status="feasible",safety_validated=True,source_node="A",destination_node="A",
                   departure_s=0,arrival_s=0,edge_ids=[])
        for dispatch,request in (("z","r1"),("a","r2")):
            l.commit_dispatch(dispatch,"truck",request,route,0)
            l.mark_departed(dispatch,0); l.record_arrival(dispatch,0,"A"); l.complete_service(dispatch,0,"A")
        restored=Ledger.from_checkpoint(json.loads(json.dumps(l.checkpoint())))
        self.assertEqual(restored.export_state(),l.export_state())
        self.assertEqual(restored.delivered,{"water":2})
        self.assertTrue(restored.check_invariants())

if __name__=="__main__":
    unittest.main()
