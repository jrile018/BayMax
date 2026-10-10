import copy
import pytest
from evals.planner.training_world import TrainingWorld


def situation():
    return {"schema":"training-situation-v1","scenario_id":"test","time_s":0,"horizon_s":40,"severity":3,
      "assumptions":{"road_failure_probability":0.1,"travel_multiplier_range":[1,1],"coverage_threshold_s":15},
      "command_id":"command","goals":{"priority_order":["urgent_service","coverage","protection","supply","time"]},
      "nodes":[{"id":x,"x_m":i*100,"y_m":0,"kind":"camp" if x in "AD" else "junction"} for i,x in enumerate("ABCD")],
      "roads":[{"id":i,"source":a,"target":b,"travel_s":t} for i,a,b,t in [("ab","A","B",2),("bc","B","C",2),("ad","A","D",3),("dc","D","C",3),("ba","B","A",2),("cb","C","B",2),("da","D","A",3),("cd","C","D",3)]],
      "vehicles":[{"id":"ambulance","node_id":"A","kind":"ambulance","capacity":1}],
      "facilities":[{"id":"clinic","node_id":"C","kind":"medical","capacity":2}],
      "requests":[{"id":"patient","node_id":"A","destination_id":"clinic","kind":"medical","quantity":1,"deadline_s":30,"source_id":"A"}],
      "stocks":{"supplies":5},"communications":{"agents":["command","A","D","ambulance"],"initially_informed":["A"],"links":[{"source":"ambulance","target":"command","delay_s":2,"success_probability":1,"contact_interval_s":0},{"source":"D","target":"command","delay_s":10,"success_probability":1,"contact_interval_s":0}]}}


def future(events=None,observations=None):
    return {"schema":"training-future-v1","scenario_id":"test","start_time_s":0,"horizon_end_s":40,"travel_multiplier":1,"truth_events":events or [],"observation_events":observations or []}


def direct(world):
    return next(a for a in world.actions() if a["kind"]=="dispatch" and a["route"]==["ab","bc"])


def test_real_arrival_fulfills_need_and_releases_vehicle():
    w=TrainingWorld(situation(),future())
    w.commit(direct(w)["id"])
    assert w.outcome()["metrics"]["medical_completed"]==0
    w.advance_to(10)
    assert w.outcome()["metrics"]["medical_on_time"]==1
    assert w.outcome()["final_state"]["vehicles"][0]["node_id"]=="C"


def test_mid_edge_closure_strands_people_without_teleporting():
    w=TrainingWorld(situation(),future([{"id":"close","kind":"road_closed","edge_id":"bc","time_s":3,"source_id":"D"}]))
    w.commit(direct(w)["id"])
    w.advance_to(4)
    v=w.outcome()["final_state"]["vehicles"][0]
    assert v["status"]=="stranded" and v["load"]==1
    assert v["edge_id"]=="bc" and v["edge_progress"]==pytest.approx(0.5)
    assert w.outcome()["metrics"]["medical_completed"]==0


def test_future_request_is_unmet_but_not_known_until_received():
    req={"id":"new","node_id":"D","destination_id":"clinic","kind":"medical","quantity":1,"deadline_s":30,"source_id":"D"}
    event={"id":"need","kind":"request_created","time_s":2,"request":req,"source_id":"D"}
    obs=dict(event,issued_at_s=2,received_at_s=12,recipient_id="command")
    w=TrainingWorld(situation(),future([event],[obs]))
    w.advance_to(3)
    assert w.outcome()["metrics"]["unmet_urgent_people"]==2
    assert "new" not in {r["id"] for r in w.knowledge()["requests"]}
    w.advance_to(12)
    assert "new" in {r["id"] for r in w.knowledge()["requests"]}


def test_hidden_facility_failure_does_not_leak_into_choices():
    event={"id":"loss","kind":"facility_failed","time_s":0,"facility_id":"clinic","source_id":"D"}
    obs=dict(event,issued_at_s=0,received_at_s=10,recipient_id="command")
    w=TrainingWorld(situation(),future([event],[obs]))
    assert any(a["kind"]=="dispatch" for a in w.actions())
    assert not w.knowledge()["facilities"][0].get("failed",False)
    w.advance_to(10)
    assert not any(a["kind"]=="dispatch" for a in w.actions())


def test_facility_loss_at_arrival_precedes_service():
    w=TrainingWorld(situation(),future([{"id":"loss","kind":"facility_failed","time_s":4,"facility_id":"clinic","source_id":"D"}]))
    w.commit(direct(w)["id"])
    w.advance_to(10)
    assert w.outcome()["metrics"]["medical_completed"]==0
    assert w.outcome()["final_state"]["vehicles"][0]["load"]==1


def test_rejected_stale_action_does_not_change_state():
    w=TrainingWorld(situation(),future())
    a=direct(w)
    w.commit(a["id"])
    before=w.outcome()
    with pytest.raises(ValueError): w.commit(a["id"])
    assert w.outcome()==before


def test_wait_and_dispatch_have_different_consequences():
    a=TrainingWorld(situation(),future()); b=copy.deepcopy(a)
    a.step("wait"); b.step(direct(b)["id"])
    assert a.outcome()["metrics"]["medical_completed"]==0
    assert b.outcome()["metrics"]["medical_completed"]==1


def test_individual_received_views_and_copy_isolation():
    obs={"id":"close","kind":"road_closed","edge_id":"bc","time_s":1,"issued_at_s":1,"received_at_s":2,"recipient_id":"D","source_id":"D"}
    w=TrainingWorld(situation(),future([], [obs])); w.advance_to(3)
    assert not w.knowledge()["observations"]
    assert w.knowledge("D")["observations"]
    k=w.knowledge("D"); k["observations"].clear()
    assert w.knowledge("D")["observations"]
    assert all(x not in w.knowledge() for x in ["seed","truth_events","future_events","latent"])


def test_empty_zero_horizon_and_invalid_times():
    f=future(); f["horizon_end_s"]=0
    w=TrainingWorld(situation(),f)
    assert [a["id"] for a in w.actions()]==["wait"]
    with pytest.raises(ValueError): w.advance_to(-1)
    with pytest.raises(ValueError): w.advance_to(float("nan"))


def test_late_safe_evacuation_remains_beneficial_and_is_selected():
    from services.planner.policies.situational import plan_situation
    s=situation();s['vehicles'][0]['kind']='bus';s['facilities'][0]['kind']='evacuation'
    s['requests'][0].update(kind='evacuation',deadline_s=1)
    w=TrainingWorld(s,future())
    dispatch=direct(w)
    assert dispatch['expected_urgent']>0
    choice=plan_situation(w.knowledge(),w.actions())['chosen_action']
    assert choice['kind']=='dispatch'
    w.step(choice['id'])
    assert w.outcome()['metrics']['safe_arrivals']==1

def test_unknown_stranding_does_not_change_command_resources_before_report():
    w=TrainingWorld(situation(),future([{'id':'close','kind':'road_closed','edge_id':'bc','time_s':3,'source_id':'D'}]))
    w.commit(direct(w)['id']);w.advance_to(4)
    assert w.outcome()['final_state']['vehicles'][0]['status']=='stranded'
    assert w.knowledge()['resources'][0]['status']=='busy'
    w.advance_to(5)
    assert w.knowledge()['resources'][0]['status']=='stranded'

def test_future_cannot_change_known_start_snapshot():
    s=situation();f=future();f['initial_snapshot']=copy.deepcopy(s);f['initial_snapshot']['severity']=8
    with pytest.raises(ValueError): TrainingWorld(s,f)

def test_known_choices_are_identical_under_different_hidden_truth():
    s=situation();a=TrainingWorld(s,future());b=TrainingWorld(s,future([{'id':'loss','kind':'facility_failed','time_s':0,'facility_id':'clinic','source_id':'D'}]))
    assert a.knowledge()==b.knowledge()
    assert a.actions()==b.actions()


def test_failure_before_pickup_releases_reservations_and_supply_stock():
    s=situation();s['vehicles'][0].update(kind='truck',capacity=2);s['facilities'][0]['kind']='supply'
    s['requests'][0].update(kind='supply',node_id='D',quantity=2)
    w=TrainingWorld(s,future([{'id':'close','kind':'road_closed','edge_id':'ad','time_s':0,'source_id':'D'}]))
    move=next(a for a in w.actions() if a['kind']=='dispatch' and a['route']==['ad','dc'])
    w.commit(move['id'])
    state=w.outcome()['final_state']
    assert state['vehicles'][0]['load']==0
    assert state['requests'][0]['reserved']==0
    assert state['facilities'][0]['reserved']==0
    assert state['stocks']['supplies']==5
    assert w.knowledge()['stocks']['supplies']==3
    w.advance_to(2)
    assert w.knowledge()['stocks']['supplies']==5
    assert w.knowledge()['requests'][0]['remaining']==2


def test_observation_cannot_be_issued_before_the_event_happens():
    obs={'id':'early','kind':'road_closed','edge_id':'bc','time_s':20,'issued_at_s':0,'received_at_s':0,'recipient_id':'command','source_id':'D'}
    with pytest.raises(ValueError): TrainingWorld(situation(),future([], [obs]))


def test_late_medical_service_remains_valuable_and_missed_deadline_is_reported():
    from services.planner.policies.situational import plan_situation
    s=situation();s['requests'][0]['deadline_s']=1
    w=TrainingWorld(s,future());move=direct(w)
    assert move['expected_urgent']>0
    chosen=plan_situation(w.knowledge(),w.actions())['chosen_action']
    assert chosen['kind']=='dispatch'
    w.step(chosen['id'])
    assert w.outcome()['metrics']['medical_completed']==1
    assert w.outcome()['metrics']['medical_on_time']==0


def test_closure_at_exact_exit_does_not_strand_completed_traversal():
    w=TrainingWorld(situation(),future([{'id':'exit-close','kind':'road_closed','edge_id':'bc','time_s':4,'source_id':'D'}]))
    w.commit(direct(w)['id']);w.advance_to(10)
    assert w.outcome()['metrics']['medical_completed']==1
    assert w.outcome()['metrics']['route_failures']==0

def test_closure_before_exit_still_strands_loaded_vehicle():
    w=TrainingWorld(situation(),future([{'id':'early-close','kind':'road_closed','edge_id':'bc','time_s':3.999,'source_id':'D'}]))
    w.commit(direct(w)['id']);w.advance_to(10)
    assert w.outcome()['metrics']['medical_completed']==0
    assert w.outcome()['metrics']['route_failures']==1

def test_closure_at_next_edge_entry_preserves_reachable_junction():
    w=TrainingWorld(situation(),future([{'id':'entry-close','kind':'road_closed','edge_id':'bc','time_s':2,'source_id':'D'}]))
    w.commit(direct(w)['id']);w.advance_to(10)
    v=w.outcome()['final_state']['vehicles'][0]
    assert v['node_id']=='B' and v['edge_progress']==0
    assert w.outcome()['metrics']['medical_completed']==0
