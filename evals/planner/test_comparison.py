import copy
import unittest
from evals.planner import runner
from evals.planner.mock_world import MockWorld
from services.planner.futures.conditional import build_ensemble
from services.planner.policies.dispatch import AdaptiveDispatch, PriorityGreedy, StaticDispatch

def snapshot():
    return {
      "scenario_id":"synthetic-civilian-recovery", "run_id":"checkpoint", "time_s":20,
      "snapshot_version":"mc-owned-v1", "label":"Synthetic humanitarian training fixture; MOCK routing and ledger",
      "roads":[
        {"edge_id":"active","source":"O","target":"S","length_m":100,"travel_time_s":20,"zone":"stable","uncertain_closure":False},
        {"edge_id":"direct","source":"A","target":"B","length_m":100,"travel_time_s":8,"zone":"damage"},
        {"edge_id":"clinic","source":"B","target":"H","length_m":100,"travel_time_s":12,"zone":"damage","closure_offset_s":2},
        {"edge_id":"alt1","source":"A","target":"C","length_m":100,"travel_time_s":18,"zone":"stable","uncertain_closure":False},
        {"edge_id":"alt2","source":"C","target":"H","length_m":100,"travel_time_s":18,"zone":"stable","uncertain_closure":False},
        {"edge_id":"supply","source":"D","target":"W","length_m":100,"travel_time_s":10,"zone":"stable","uncertain_closure":False}],
      "observations":[
        {"event_id":"forecast-direct","kind":"forecast","edge_id":"direct","issued_at_s":10,"received_at_s":15,"closes_at_s":45},
        {"event_id":"forecast-clinic","kind":"forecast","edge_id":"clinic","issued_at_s":10,"received_at_s":15,"closes_at_s":46},
        {"event_id":"forecast-alt1","kind":"forecast","edge_id":"alt1","issued_at_s":10,"received_at_s":15,"closes_at_s":150},
        {"event_id":"forecast-alt2","kind":"forecast","edge_id":"alt2","issued_at_s":10,"received_at_s":15,"closes_at_s":150}],
      "route_catalog":[
        {"route_id":"direct-medical","start_node":"A","destination":"H","edge_ids":["direct","clinic"]},
        {"route_id":"detour-medical","start_node":"A","destination":"H","edge_ids":["alt1","alt2"]},
        {"route_id":"supply-run","start_node":"D","destination":"W","edge_ids":["supply"]}],
      "vehicles":[
        {"vehicle_id":"committed-bus","type":"bus","phase":"traveling","node_id":None,"current_edge_id":"active","progress_m":40,
         "remaining_path":[],"request_id":"ongoing-evac","load":{"people":6,"patients":0,"supplies":0},"capacity":6},
        {"vehicle_id":"ambulance","type":"ambulance","phase":"idle","node_id":"A","current_edge_id":None,"progress_m":0,
         "remaining_path":[],"request_id":None,"load":{"people":0,"patients":0,"supplies":0},"capacity":1},
        {"vehicle_id":"truck","type":"truck","phase":"idle","node_id":"D","current_edge_id":None,"progress_m":0,
         "remaining_path":[],"request_id":None,"load":{"people":0,"patients":0,"supplies":0},"capacity":10}],
      "requests":[
        {"request_id":"ongoing-evac","kind":"evacuation","origin":"O","destination":"S","quantity":6,"remaining":6,"deadline_s":80,"service_s":0},
        {"request_id":"urgent-medical","kind":"medical","origin":"A","destination":"H","quantity":1,"remaining":1,"deadline_s":78,"service_s":2},
        {"request_id":"water","kind":"supply","origin":"D","destination":"W","quantity":8,"remaining":8,"deadline_s":None,"service_s":1}],
      "ledger":{"stock":10,"destination_capacity":{"S":12,"H":1,"W":100},
                "reservations":{"ongoing-evac":6},"occupancy":{"S":0,"H":0,"W":0},"delivered":{},
                "person_locations":{"evac-group":"vehicle:committed-bus"}}
    }

def future(seed=1):
    f=build_ensemble(snapshot(),[seed],horizon_s=100)[0]
    f["truth_events"]=[]
    f["observation_events"]=[]
    f["latent"]["travel_delay_multiplier"]=1.0
    return f

class ComparisonTests(unittest.TestCase):
    def test_snapshot_continuity_and_load_are_preserved(self):
        s=snapshot()
        w=MockWorld(s,future())
        self.assertEqual(w.state,s)
        self.assertEqual(w.state["vehicles"][0]["progress_m"],40)
        self.assertEqual(w.state["ledger"]["reservations"],{"ongoing-evac":6})
        w.advance_to(25)
        bus=w.state["vehicles"][0]
        self.assertEqual(bus["progress_m"],65)
        self.assertEqual(bus["load"]["people"],6)

    def test_unique_arrival_and_delivery_conserve_stock_and_reservations(self):
        s=snapshot()
        result=runner.evaluate(s,[future()],{"greedy":PriorityGreedy},MockWorld)
        row=result["runs"][0]
        self.assertEqual(row["metrics"]["safe_arrivals"],6)
        self.assertEqual(row["metrics"]["medical_on_time"],1)
        self.assertEqual(row["metrics"]["supplies_delivered"],8)
        self.assertEqual(row["final_state"]["ledger"]["stock"],2)
        self.assertEqual(row["final_state"]["ledger"]["reservations"],{})
        self.assertEqual(row["final_state"]["vehicles"][0]["load"]["people"],0)
        self.assertEqual(s,snapshot())

    def test_initial_actions_do_not_see_hidden_future(self):
        a=future(1); b=future(2)
        a["truth_events"]=[{"event_id":"damage","kind":"road_closed","edge_id":"clinic","time_s":35}]
        b["truth_events"]=[{"event_id":"damage","kind":"road_closed","edge_id":"clinic","time_s":70}]
        r=runner.evaluate(snapshot(),[a,b],{"greedy":PriorityGreedy},MockWorld)
        self.assertEqual(r["runs"][0]["actions"][0]["action"],r["runs"][1]["actions"][0]["action"])
        self.assertEqual(r["runs"][0]["actions"][0]["view"],r["runs"][1]["actions"][0]["view"])
        self.assertNotIn("truth_events",str(r["runs"][0]["actions"][0]["view"]))
        self.assertEqual(r["runs"][0]["metrics"]["route_failures"],1)
        self.assertEqual(r["runs"][1]["metrics"]["route_failures"],0)

    def test_mid_edge_closure_strands_in_place_and_retains_load(self):
        f=future()
        f["truth_events"]=[{"event_id":"blocked","kind":"road_closed","edge_id":"active","time_s":25}]
        w=MockWorld(snapshot(),f)
        w.advance_to(70)
        bus=w.state["vehicles"][0]
        self.assertEqual(bus["phase"],"stranded")
        self.assertEqual(bus["progress_m"],65)
        self.assertEqual(bus["current_edge_id"],"active")
        self.assertEqual(bus["load"]["people"],6)
        self.assertEqual(w.outcome()["metrics"]["safe_arrivals"],0)
        self.assertEqual(w.state["ledger"]["reservations"]["ongoing-evac"],6)

    def test_common_seeds_and_failed_cases_retained_in_quantiles(self):
        good=future(10); bad=future(20)
        bad["truth_events"]=[{"event_id":"blocked","kind":"road_closed","edge_id":"active","time_s":25}]
        r=runner.evaluate(snapshot(),[good,bad],{"greedy":PriorityGreedy,"adaptive":AdaptiveDispatch},MockWorld)
        self.assertEqual([(x["policy"],x["seed"]) for x in r["runs"]],
                         [("greedy",10),("greedy",20),("adaptive",10),("adaptive",20)])
        agg=r["aggregates"]["greedy"]
        self.assertEqual(agg["sample_count"],2)
        self.assertEqual(agg["raw_totals"]["route_failures"],1)
        self.assertEqual(agg["arrival_quantiles_s"]["sample_count"],5)
        self.assertEqual(agg["tested_scenario_success_fraction"],0.5)
        self.assertEqual(r["calibration"],"uncalibrated tested-scenario fractions")

    def test_mock_adapter_rejects_duplicate_or_stale_commit(self):
        w=MockWorld(snapshot(),future())
        action=PriorityGreedy().choose(w.policy_view())
        w.commit(action)
        with self.assertRaises(ValueError):
            w.commit(action)
        self.assertEqual(w.state["ledger"]["reservations"]["urgent-medical"],1)

    def test_eval_errors_are_recorded_as_failed_runs(self):
        def broken(s,f):
            raise RuntimeError("adapter unavailable")
        r=runner.evaluate(snapshot(),[future()],{"greedy":PriorityGreedy},broken)
        self.assertEqual(len(r["runs"]),1)
        self.assertEqual(r["aggregates"]["greedy"]["evaluation_failed_count"],1)
        self.assertIn("adapter unavailable",r["runs"][0]["error"])
        self.assertIsNone(r["aggregates"]["greedy"]["arrival_quantiles_s"]["p50"])

    def test_future_observation_cannot_be_passed_to_policy(self):
        s=snapshot(); s["observations"][0]["received_at_s"]=21
        with self.assertRaises(ValueError):
            build_ensemble(s,[1])

    def test_heldout_seeds_must_be_disjoint(self):
        with self.assertRaises(ValueError):
            runner.compare_with_holdout(snapshot(),[1,2],[2,3],{"greedy":PriorityGreedy},MockWorld)

    def test_invalid_or_mismatched_future_rejected(self):
        f=future(); f["initial_snapshot"]["vehicles"][0]["progress_m"]=0
        with self.assertRaises(ValueError):
            runner.evaluate(snapshot(),[f],{"greedy":PriorityGreedy},MockWorld)


    def test_invalid_stock_or_overreserved_destination_rejected(self):
        for mutate in (
            lambda s:s["ledger"].update(stock=-1),
            lambda s:s["ledger"]["destination_capacity"].update(S=5),
            lambda s:s["vehicles"][0]["load"].update(people=7),
        ):
            s=snapshot();mutate(s)
            with self.assertRaises(ValueError):
                MockWorld(s,future())

    def test_previously_delivered_people_not_counted_as_future_unmet(self):
        s=snapshot()
        s["requests"].append({"request_id":"past","kind":"evacuation","origin":"O",
          "destination":"S","quantity":2,"remaining":0,"deadline_s":10,"service_s":0})
        s["ledger"]["delivered"]["past"]=2
        s["ledger"]["occupancy"]["S"]=2
        f=build_ensemble(s,[1],100)[0]
        f["truth_events"]=[];f["observation_events"]=[]
        r=runner.evaluate(s,[f],{"greedy":PriorityGreedy},MockWorld)
        self.assertEqual(r["runs"][0]["metrics"]["unmet_urgent_people"],0)

    def test_zero_horizon_does_not_create_new_commitments(self):
        s=snapshot();f=build_ensemble(s,[1],0)[0]
        r=runner.evaluate(s,[f],{"greedy":PriorityGreedy},MockWorld)
        self.assertEqual(r["runs"][0]["actions"],[])
        self.assertEqual(r["runs"][0]["final_state"]["ledger"]["reservations"],{"ongoing-evac":6})


    def test_blocked_at_edge_entry_retains_node_and_can_reroute_commitment(self):
        f=future()
        f["truth_events"]=[{"event_id":"entry-blocked","kind":"road_closed","edge_id":"direct","time_s":20}]
        w=MockWorld(snapshot(),f)
        w.commit(PriorityGreedy().choose(w.policy_view()))
        w.advance_to(25)
        ambulance=w.state["vehicles"][1]
        self.assertEqual(ambulance["phase"],"waiting")
        self.assertEqual(ambulance["node_id"],"A")
        self.assertEqual(ambulance["load"]["patients"],1)
        action=PriorityGreedy().choose(w.policy_view())
        self.assertEqual(action.route_id,"detour-medical")
        w.commit(action)
        self.assertEqual(w.state["ledger"]["reservations"]["urgent-medical"],1)
        w.advance_to(70)
        self.assertEqual(w.outcome()["metrics"]["medical_on_time"],1)

    def test_known_access_uses_received_order_not_list_order(self):
        s=snapshot()
        s["observations"].extend([
          {"event_id":"open","kind":"road_open","edge_id":"active","issued_at_s":15,"received_at_s":16},
          {"event_id":"older-close","kind":"road_closed","edge_id":"active","issued_at_s":10,"received_at_s":11}])
        f=build_ensemble(s,[1],100)[0]
        f["truth_events"]=[];f["observation_events"]=[]
        w=MockWorld(s,f);w.advance_to(60)
        self.assertEqual(w.outcome()["metrics"]["safe_arrivals"],6)

    def test_new_evacuation_changes_person_locations_on_commit_and_arrival(self):
        s=snapshot()
        s["vehicles"].append({"vehicle_id":"spare-bus","type":"bus","phase":"idle","node_id":"O",
          "current_edge_id":None,"progress_m":0,"remaining_path":[],"request_id":None,
          "load":{"people":0,"patients":0,"supplies":0},"capacity":2})
        s["requests"].append({"request_id":"new-evac","kind":"evacuation","origin":"O","destination":"S",
          "quantity":2,"remaining":2,"deadline_s":60,"service_s":0,"person_ids":["p1","p2"]})
        s["ledger"]["person_locations"].update(p1="origin:O",p2="origin:O")
        s["route_catalog"].append({"route_id":"new-evac-route","start_node":"O","destination":"S","edge_ids":["active"]})
        f=build_ensemble(s,[1],100)[0]
        f["truth_events"]=[];f["observation_events"]=[]
        w=MockWorld(s,f)
        w.commit(PriorityGreedy().choose(w.policy_view()))
        self.assertEqual(w.state["ledger"]["person_locations"]["p1"],"vehicle:spare-bus")
        w.advance_to(55)
        self.assertEqual(w.state["ledger"]["person_locations"]["p1"],"destination:S")
        self.assertEqual(w.outcome()["metrics"]["safe_arrivals"],8)


    def test_empty_and_duplicate_routes_rejected_before_commit(self):
        for route in (
          {"route_id":"empty","start_node":"A","destination":"A","edge_ids":[]},
          {"route_id":"direct-medical","start_node":"D","destination":"W","edge_ids":["supply"]},
        ):
            s=snapshot();s["route_catalog"].append(route)
            with self.assertRaises(ValueError):
                MockWorld(s,future())

if __name__=="__main__":
    unittest.main()
