import copy

import pytest

from services.planner.policies.situational import plan_situation


def knowledge(*, resources=None, requests=None, observations=None, roads=None):
    result = {
        "time_s": 0,
        "observations": observations or [],
        "goals": {"priority_order": [
            "urgent_service", "coverage", "protection", "supply", "time"
        ]},
        "resources": resources or [
            {"id": "v1", "kind": "ambulance", "capacity": 2, "node_id": "a", "status": "idle"},
            {"id": "v2", "kind": "bus", "capacity": 3, "node_id": "a", "status": "idle"},
        ],
        "requests": requests or [
            {"id": "r1", "kind": "medical", "remaining": 2, "deadline_s": 50},
            {"id": "r2", "kind": "evacuation", "remaining": 3, "deadline_s": 50},
        ],
    }
    if roads is not None:
        result["roads"] = roads
    return result


def action(id, *, vehicle="v1", request="r1", quantity=1, kind="dispatch",
           urgent=0, supply=0, coverage=0, protection=0, travel=1,
           route=None, destination="b", deadline=None):
    return {
        "id": id, "kind": kind, "vehicle_id": vehicle,
        "request_id": request, "quantity": quantity, "route": route or [],
        "destination_id": destination, "travel_s": travel,
        "expected_urgent": urgent, "expected_supply": supply,
        "coverage_delta": coverage, "protection_delta": protection,
        "deadline_s": deadline, "explanation": {"known_only": True},
    }


def test_initial_resources_change_generated_choice():
    options = [
        action("medical", urgent=2, quantity=2, vehicle="v1"),
        action("evacuation", urgent=2, vehicle="v2", request="r2", quantity=2,
               coverage=-1),
    ]
    assert plan_situation(knowledge(), options)["chosen_action"]["id"] == "medical"
    only_bus = knowledge(resources=[
        {"id": "v2", "kind": "bus", "capacity": 3, "node_id": "a", "status": "idle"}
    ])
    assert plan_situation(only_bus, options)["chosen_action"]["id"] == "evacuation"


def test_newly_received_closure_changes_choice_and_future_fact_is_ignored():
    roads = [
        {"id": "ab", "source": "a", "target": "b", "travel_s": 1},
        {"id": "ac", "source": "a", "target": "c", "travel_s": 2},
        {"id": "cb", "source": "c", "target": "b", "travel_s": 2},
    ]
    options = [
        action("fast", urgent=1, route=["ab"], travel=1),
        action("detour", urgent=1, route=["ac", "cb"], travel=4),
    ]
    initial = knowledge(roads=roads)
    assert plan_situation(initial, options)["chosen_action"]["id"] == "fast"
    later = copy.deepcopy(initial)
    later["time_s"] = 10
    later["observations"] = [{
        "kind": "road_closed", "edge_id": "ab", "received_at_s": 10,
        "issued_at_s": 8, "source_id": "camp",
    }]
    assert plan_situation(later, options)["chosen_action"]["id"] == "detour"


def test_combination_respects_vehicle_capacity_and_shared_request_remaining():
    k = knowledge(requests=[
        {"id": "r1", "kind": "medical", "remaining": 2, "deadline_s": 50}
    ])
    options = [
        action("bad-capacity", urgent=3, quantity=3),
        action("v1-one", urgent=1, quantity=1),
        action("v1-two", urgent=2, quantity=2),
        action("v2-one", vehicle="v2", urgent=1, quantity=1),
        action("v2-two", vehicle="v2", urgent=2, quantity=2),
    ]
    result = plan_situation(k, options, depth=3)
    assert sum(item["quantity"] for item in result["plan"]) <= 2
    assert len({item["vehicle_id"] for item in result["plan"]}) == len(result["plan"])
    assert all(item["id"] != "bad-capacity" for item in result["plan"])
    assert result["score_components"]["urgent_service"] == 2


def test_lexicographic_coverage_and_protection_and_reasons():
    k = knowledge()
    options = [
        action("urgent", urgent=1, coverage=-2, protection=1),
        action("coverage", kind="reposition", vehicle="v2", request=None,
               quantity=0, urgent=0, coverage=3, protection=2),
        action("supply", vehicle="v2", request="r2", quantity=1, supply=1),
    ]
    result = plan_situation(k, options, depth=2)
    assert [item["id"] for item in result["plan"]] == ["urgent", "coverage"]
    assert result["score_components"]["coverage"] == 1
    assert "urgent" in " ".join(result["reasons"]).lower()
    assert "coverage" in " ".join(result["reasons"]).lower()
    assert "protection" in " ".join(result["reasons"]).lower()


def test_search_limits_are_reported_and_deterministic():
    k = knowledge()
    options = [
        action(f"a{i}", vehicle="v1" if i % 2 else "v2", urgent=i % 2,
               request="r1" if i % 2 else "r2")
        for i in range(12)
    ]
    one = plan_situation(k, options, beam_width=2, depth=1)
    two = plan_situation(k, list(reversed(options)), beam_width=2, depth=1)
    assert one["plan"] == two["plan"]
    assert len(one["plan"]) == 1
    assert one["search_limits"]["beam_width"] == 2
    assert one["search_limits"]["depth"] == 1


def test_wait_is_legal_fallback_and_useless_moves_are_not_selected():
    k = knowledge()
    wait = action("wait", kind="wait", vehicle=None, request=None, quantity=0,
                  destination=None, travel=5)
    zero = action("zero", kind="reposition", request=None, quantity=0,
                  destination="a", travel=4)
    result = plan_situation(k, [zero, wait])
    assert result["chosen_action"]["id"] == "wait"
    assert result["plan"] == [wait]
    assert "wait" in " ".join(result["reasons"]).lower()
    assert plan_situation(k, [])["chosen_action"]["kind"] == "wait"


def test_hidden_inputs_are_rejected_before_scoring():
    k = knowledge()
    k["future_events"] = [{"kind": "road_closed", "edge_id": "ab"}]
    with pytest.raises(ValueError, match="hidden|future"):
        plan_situation(k, [action("a", urgent=1)])
    a = action("a", urgent=1)
    a["seed"] = 17
    with pytest.raises(ValueError, match="hidden|seed"):
        plan_situation(knowledge(), [a])


def test_noncontiguous_route_is_excluded_when_endpoints_are_known():
    k = knowledge(roads=[
        {"id": "ab", "source": "a", "target": "b", "travel_s": 1},
        {"id": "cd", "source": "c", "target": "d", "travel_s": 1},
    ])
    bad = action("teleport", urgent=2, route=["cd"], destination="d")
    good = action("reachable", urgent=1, route=["ab"], destination="b")
    assert plan_situation(k, [bad, good])["chosen_action"]["id"] == "reachable"


def test_directed_road_cannot_be_traversed_backward():
    k = knowledge(roads=[
        {"id": "ab", "source": "a", "target": "b", "travel_s": 1},
        {"id": "bc", "source": "b", "target": "c", "travel_s": 2},
    ], resources=[
        {"id": "v1", "kind": "ambulance", "capacity": 2, "node_id": "b", "status": "idle"}
    ])
    backward = action("backward", urgent=2, quantity=2, route=["ab"], destination="a")
    forward = action("forward", urgent=1, route=["bc"], destination="c")
    assert plan_situation(k, [backward, forward])["chosen_action"]["id"] == "forward"


def test_shared_facility_capacity_is_conserved_across_actions():
    k = knowledge(requests=[
        {"id": "r1", "kind": "medical", "remaining": 2},
        {"id": "r2", "kind": "evacuation", "remaining": 2},
    ])
    k["facilities"] = [{
        "id": "clinic", "capacity": 2, "occupied": 0, "reserved": 0, "failed": False
    }]
    options = [
        action("first", vehicle="v1", request="r1", quantity=2, urgent=2,
               destination="clinic"),
        action("second", vehicle="v2", request="r2", quantity=2, urgent=2,
               destination="clinic"),
    ]
    result = plan_situation(k, options, depth=2)
    assert sum(item["quantity"] for item in result["plan"]) <= 2
    assert result["score_components"]["urgent_service"] == 2


def test_shared_supply_stock_is_conserved_across_actions():
    k = knowledge(resources=[
        {"id": "t1", "kind": "truck", "capacity": 2, "node_id": "a", "status": "idle"},
        {"id": "t2", "kind": "truck", "capacity": 2, "node_id": "a", "status": "idle"},
    ], requests=[
        {"id": "s1", "kind": "supply", "remaining": 2},
        {"id": "s2", "kind": "supply", "remaining": 2},
    ])
    k["stocks"] = {"supplies": 2}
    options = [
        action("s1", vehicle="t1", request="s1", quantity=2, supply=2),
        action("s2", vehicle="t2", request="s2", quantity=2, supply=2),
    ]
    for option in options:
        option["request_kind"] = "supply"
    result = plan_situation(k, options, depth=2)
    assert sum(item["quantity"] for item in result["plan"]) <= 2
    assert result["score_components"]["supply"] == 2


def test_joint_coverage_union_does_not_double_count_two_repositions():
    k = knowledge(requests=[])
    k["coverage_by_vehicle"] = {"v1": ["camp-a"], "v2": ["camp-a"]}
    options = [
        action("move-one", kind="reposition", vehicle="v1", request=None,
               quantity=0, coverage=1, destination="b"),
        action("move-two", kind="reposition", vehicle="v2", request=None,
               quantity=0, coverage=1, destination="b"),
    ]
    for option in options:
        option["covered_camps_after"] = ["camp-b"]
    result = plan_situation(k, options, depth=2)
    assert len(result["plan"]) == 1
    assert result["score_components"]["coverage"] == 1


def test_dispatch_removes_its_vehicle_from_joint_coverage():
    k = knowledge(requests=[
        {"id": "r1", "kind": "medical", "remaining": 1}
    ])
    k["coverage_by_vehicle"] = {"v1": ["camp-a"], "v2": ["camp-b"]}
    dispatch = action("dispatch", vehicle="v1", urgent=1, quantity=1, coverage=-1)
    dispatch["covered_camps_after"] = []
    result = plan_situation(k, [dispatch])
    assert result["score_components"]["coverage"] == -1


def test_declared_goal_order_changes_choice_for_same_visible_situation():
    k = knowledge()
    urgent = action("urgent", vehicle="v1", request="r1", urgent=1)
    cover = action("cover", kind="reposition", vehicle="v1", request=None,
                   quantity=0, coverage=1)
    assert plan_situation(k, [urgent, cover])["chosen_action"]["id"] == "urgent"
    k["goals"]["priority_order"] = [
        "coverage", "urgent_service", "protection", "supply", "time"
    ]
    assert plan_situation(k, [urgent, cover])["chosen_action"]["id"] == "cover"


@pytest.mark.parametrize("limits", [
    {"beam_width": 129}, {"depth": 17}, {"beam_width": 0}, {"depth": 0}
])
def test_search_budget_must_be_small_and_positive(limits):
    with pytest.raises(ValueError):
        plan_situation(knowledge(), [], **limits)


def test_raw_diffused_closure_blocks_received_road_at_decision_time():
    from services.planner.futures.information import diffuse_information

    received = diffuse_information(
        [{"id": "closure-ab", "kind": "road_closed", "time_s": 1,
          "source_id": "camp", "payload": {"edge_id": "ab"}}],
        {"agents": ["camp", "command"], "links": [{
            "source": "camp", "target": "command", "delay_s": 1,
            "contact_interval_s": 0, "success_probability": 1,
        }]},
        horizon_s=10,
        seed=7,
    )
    command = [row for row in received if row["recipient_id"] == "command"]
    assert command[0]["received_at_s"] == 2
    assert command[0]["kind"] == "road_closed"
    assert command[0]["payload"] == {"edge_id": "ab"}
    k = knowledge(roads=[
        {"id": "ab", "source": "a", "target": "b", "travel_s": 1},
        {"id": "ac", "source": "a", "target": "c", "travel_s": 2},
        {"id": "cb", "source": "c", "target": "b", "travel_s": 2},
    ], observations=command)
    k["time_s"] = 3
    options = [
        action("fast", urgent=1, route=["ab"], travel=1),
        action("detour", urgent=1, route=["ac", "cb"], travel=4),
    ]
    assert plan_situation(k, options)["chosen_action"]["id"] == "detour"
