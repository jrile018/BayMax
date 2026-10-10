"""A restored mixed-resource branch must conserve actual people and cargo."""
import unittest
from services.routing.checkpoint_demo import build_evidence

class CheckpointIntegrationTests(unittest.TestCase):
    def test_mixed_service_branches_preserve_resources_and_original(self):
        saved,proof=build_evidence()
        self.assertEqual(saved["schema"],"knight26.trip-executor")
        self.assertTrue(proof["original_unchanged"])
        before=proof["saved_snapshot"]
        self.assertEqual({t["vehicle_id"]:t["phase"] for t in before["trips"]},
                         {"bus":"servicing","ambulance":"servicing","truck":"traveling"})
        served=proof["served_snapshot"]["ledger"]
        self.assertEqual(served["outcome_totals"]["safe_evacuated_people"],2)
        self.assertEqual(served["outcome_totals"]["on_time_medical_people"],1)
        self.assertEqual(served["delivered"],{"water":5})
        self.assertEqual(served["requests"]["supply"]["remaining_goods"],{"water":3})
        self.assertEqual(proof["conservation"]["served"]["goods"]["water"],
                         {"stock":5,"carried":0,"delivered":5,"total":10})
        uncertain=proof["unknown_destination_snapshot"]
        self.assertTrue(all(t["phase"]=="stranded" for t in uncertain["trips"]))
        self.assertEqual(uncertain["ledger"]["delivered"],{})
        self.assertEqual(uncertain["ledger"]["outcome_totals"]["safe_evacuated_people"],0)
        self.assertEqual(uncertain["ledger"]["outcome_totals"]["on_time_medical_people"],0)
        self.assertEqual(proof["conservation"]["unknown_destination"]["goods"]["water"],
                         {"stock":5,"carried":5,"delivered":0,"total":10})
        self.assertEqual(proof["conservation"]["unknown_destination"]["people"]["total"],3)

if __name__=="__main__":
    unittest.main()
