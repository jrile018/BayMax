"""Public resource invariants: literal hand-computed amounts and actual service gating."""
import unittest
from services.planner.ledger import Ledger, LedgerError, Vehicle, Request, Destination

def route(departure=0,arrival=10):
    return dict(status="feasible",safety_validated=True,source_node="A",destination_node="D",
                departure_s=departure,arrival_s=arrival,edge_ids=["ad"])
def bus(people=("p1","p2"),seats=2,capacity=2,deadline=None):
    return Ledger([Vehicle("v","bus","A",seats,0)],
                  [Request("r","evacuation","A","D",people,deadline_s=deadline)],
                  [Destination("s","D","shelter",capacity)],{})

class ResourceTests(unittest.TestCase):
    def test_seats_and_shelter_fail_without_partial_reservation(self):
        for l in (bus(seats=1),bus(capacity=1)):
            before=l.export_state()
            with self.assertRaises(LedgerError):
                l.commit_dispatch("d","v","r",route(),0)
            self.assertEqual(l.export_state(),before)
    def test_wrong_vehicle_or_destination_type_rejected(self):
        for kind in ("bus","truck"):
            l=Ledger([Vehicle("v",kind,"A",2,2)],
                     [Request("r","medical","A","D",("p",))],
                     [Destination("m","D","medical",2)],{})
            before=l.export_state()
            with self.assertRaises(LedgerError):
                l.commit_dispatch("d","v","r",route(),0)
            self.assertEqual(l.export_state(),before)
        l=Ledger([Vehicle("v","ambulance","A",1,0)],
                 [Request("r","medical","A","D",("p",))],
                 [Destination("s","D","shelter",2)],{})
        with self.assertRaises(LedgerError):
            l.commit_dispatch("d","v","r",route(),0)
    def test_partial_supply_dispatch_keeps_residual_need(self):
        l=Ledger([Vehicle("v","truck","A",0,5)],
                 [Request("r","supply","A","D",goods={"water":8})],[],{"A":{"water":10}})
        assignment=l.commit_dispatch("d","v","r",route(),0,cargo={"water":5})
        self.assertEqual(assignment.cargo,{"water":5})
        self.assertTrue(l.check_invariants())
        l.mark_departed("d",0)
        l.record_arrival("d",10,"D")
        result=l.complete_service("d",10,"D")
        self.assertEqual(result,l.complete_service("d",10,"D"))
        self.assertTrue(l.check_invariants())
        with self.assertRaises(LedgerError):
            l.commit_dispatch("d2","v","r",dict(route(),source_node="D"),10,cargo={"water":3})
    def test_need_and_stock_cannot_be_overserved(self):
        l=Ledger([Vehicle("v","truck","A",0,10)],
                 [Request("r","supply","A","D",goods={"water":4})],[],{"A":{"water":3}})
        for cargo in ({"water":4},{"water":5},{"water":0},{"water":-1},{"water":True}):
            before=l.export_state()
            with self.assertRaises(LedgerError):
                l.commit_dispatch("d","v","r",route(),0,cargo=cargo)
            self.assertEqual(l.export_state(),before)
    def test_duplicate_dispatch_is_idempotent_and_conflicts_reject(self):
        l=bus()
        a=l.commit_dispatch("d","v","r",route(),0)
        before=l.export_state()
        b=l.commit_dispatch("d","v","r",route(),0)
        self.assertEqual(a,b)
        self.assertEqual(l.export_state(),before)
        with self.assertRaises(LedgerError):
            l.commit_dispatch("d","v","r",route(),0,person_ids=("p1",))
        self.assertEqual(l.export_state(),before)
    def test_safe_physical_arrival_and_service_duration_required(self):
        l=bus()
        l.commit_dispatch("d","v","r",route(),0,service_s=2)
        l.mark_departed("d",0)
        for now,node,safe in ((9,"D",True),(10,"A",True),(10,"D",False)):
            with self.assertRaises(LedgerError):
                l.record_arrival("d",now,node,safe)
        l.record_arrival("d",12,"D",True)
        with self.assertRaises(LedgerError):
            l.complete_service("d",13,"D")
        l.complete_service("d",14,"D")
        self.assertTrue(l.check_invariants())
    def test_service_deadline_checked_and_actual_lateness_reported(self):
        l=Ledger([Vehicle("v","ambulance","A",1,0)],
                 [Request("r","medical","A","D",("p",),deadline_s=12)],
                 [Destination("m","D","medical",1)],{})
        with self.assertRaises(LedgerError):
            l.commit_dispatch("bad","v","r",route(arrival=11),0,service_s=2)
        l.commit_dispatch("d","v","r",route(),0,service_s=2)
        l.mark_departed("d",0)
        l.record_arrival("d",11,"D")
        result=l.complete_service("d",13,"D")
        self.assertFalse(result["on_time"])
    def test_transaction_restores_all_changes_and_nested_scope(self):
        l=bus()
        l.commit_dispatch("d","v","r",route(),0)
        before=l.export_state()
        with self.assertRaises(RuntimeError):
            with l.transaction():
                l.mark_departed("d",0)
                l.record_arrival("d",10,"D")
                l.complete_service("d",10,"D")
                raise RuntimeError("rollback")
        self.assertEqual(l.export_state(),before)
        with l.transaction():
            l.mark_departed("d",0)
            departed=l.export_state()
            try:
                with l.transaction():
                    l.record_arrival("d",10,"D")
                    raise RuntimeError("inner rollback")
            except RuntimeError:
                pass
            self.assertEqual(l.export_state(),departed)
        self.assertTrue(l.check_invariants())

if __name__=="__main__":
    unittest.main()
