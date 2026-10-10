"""Literal C1 replay expectations, independent of the demo's summary calculation."""
import unittest
from services.routing.demo import build_replays, measure_operations

class DemoTests(unittest.TestCase):
    def test_midpoint_reroute_is_actual_and_conserved(self):
        data=build_replays()
        frames={f["label"]:f["snapshot"] for f in data["reroute"]["frames"]}
        before=frames["midpoint"]["trips"][0]; after=frames["rerouted"]["trips"][0]
        self.assertEqual(before["position_m"],[50,0])
        self.assertEqual(after["position_m"],before["position_m"])
        self.assertEqual(after["passengers"],["p1","p2"])
        self.assertEqual(after["time_s"],5)
        self.assertEqual(after["remaining_path"],["ab","bc","cd"])
        self.assertEqual(after["eta_arrival_s"],35)
        end=frames["served"]
        self.assertEqual(end["time_s"],37)
        self.assertEqual(end["ledger"]["outcome_totals"]["safe_evacuated_people"],2)
        self.assertEqual(end["ledger"]["destinations"]["shelter"]["occupancy"],2)
    def test_stranded_replay_retains_unmet_people_and_no_service(self):
        case=build_replays()["stranded"]
        t=case["frames"][-1]["snapshot"]["trips"][0]
        self.assertEqual(t["phase"],"stranded")
        self.assertEqual(t["position_m"],[50,0])
        self.assertEqual(t["passengers"],["p1","p2"])
        self.assertEqual(t["exposure_s"],20)
        self.assertEqual(case["conservation"]["people"],dict(origin=0,in_transit=2,destination=0,total=2))
        self.assertEqual(case["frames"][-1]["snapshot"]["ledger"]["outcomes"],{})
    def test_actual_aid_replay_counts_people_and_partial_goods_once(self):
        case=build_replays()["aid"]
        middle=case["frames"][2]["snapshot"]["ledger"]
        self.assertEqual(middle["delivered"],{})
        self.assertEqual(middle["outcome_totals"]["safe_evacuated_people"],0)
        end=case["frames"][-1]["snapshot"]["ledger"]
        self.assertEqual(end["outcome_totals"],dict(safe_evacuated_people=2,medical_people_served=1,
                                                   on_time_medical_people=1,delivered_goods={"water":5}))
        self.assertEqual(end["stocks"]["A"]["water"],5)
        self.assertEqual(end["requests"]["supply"]["remaining_goods"]["water"],3)
        self.assertEqual(case["conservation"]["goods"]["water"],dict(stock=5,carried=0,delivered=5,total=10))
        self.assertEqual(len(end["outcomes"]),3)
    def test_snapshot_hashes_reproduce_for_same_inputs(self):
        a=build_replays(); b=build_replays()
        for case in a:
            self.assertEqual([f["snapshot"]["snapshot_hash"] for f in a[case]["frames"]],
                             [f["snapshot"]["snapshot_hash"] for f in b[case]["frames"]])
    def test_benchmark_reports_measured_samples_separately(self):
        stats=measure_operations(3)
        for kind in ("route_search","mid_edge_replan"):
            self.assertEqual(stats[kind]["sample_count"],3)
            self.assertGreaterEqual(stats[kind]["p50_ms"],0)
            self.assertGreaterEqual(stats[kind]["p95_ms"],stats[kind]["p50_ms"])

if __name__=="__main__":
    unittest.main()
