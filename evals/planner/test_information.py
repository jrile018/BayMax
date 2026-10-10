import copy

import pytest

from services.planner.futures.information import diffuse_information


def network():
    return {
        "agents": ["camp-a", "vehicle-b", "command", "camp-isolated"],
        "initially_informed": ["command"],
        "links": [
            {"source": "camp-a", "target": "vehicle-b", "delay_s": 2,
             "contact_interval_s": 10, "success_probability": 1},
            {"source": "vehicle-b", "target": "command", "delay_s": 3,
             "contact_interval_s": 5, "success_probability": 1},
            {"source": "command", "target": "camp-a", "delay_s": 1,
             "contact_interval_s": 0, "success_probability": 1},
        ],
    }


def test_multihop_directed_contact_schedule_and_isolation():
    fact = {
        "id": "closure-1", "kind": "road_closed", "time_s": 3,
        "issued_at_s": 3, "source_id": "camp-a",
        "payload": {"edge_id": "road-2"},
    }
    original = copy.deepcopy(fact)
    received = diffuse_information([fact], network(), 30, 17)
    assert fact == original
    times = {e["recipient_id"]: e["received_at_s"] for e in received}
    assert times == {"camp-a": 3, "vehicle-b": 12, "command": 18}
    assert "camp-isolated" not in times
    assert all(e["source_id"] == "camp-a" and e["issued_at_s"] == 3 for e in received)
    assert all(e["payload"] == {"edge_id": "road-2"} and e["edge_id"] == "road-2" for e in received)
    assert all(e["time_s"] == 3 and e["kind"] == "road_closed" for e in received)
    assert diffuse_information([fact], network(), 17, 17) == received[:2]


def test_no_reverse_route_or_early_information_and_link_losses():
    net = network()
    fact = {
        "id": "request-1", "kind": "request_created", "time_s": 1,
        "source_id": "command", "payload": {"request": {"id": "new-need"}},
    }
    received = diffuse_information([fact], net, 20, 7)
    assert {e["recipient_id"] for e in received} == {"command", "camp-a", "vehicle-b"}
    assert next(e for e in received if e["recipient_id"] == "camp-a")["received_at_s"] == 2
    assert next(e for e in received if e["recipient_id"] == "vehicle-b")["received_at_s"] == 12
    net["links"][0]["success_probability"] = 0
    cut = diffuse_information([fact], net, 20, 7)
    assert {e["recipient_id"] for e in cut} == {"command", "camp-a"}
    assert diffuse_information([fact], net, 20, 7) == cut


def test_intermediate_loss_can_retry_at_later_contact_without_changing_issue_time():
    net = {
        "agents": ["a", "b"],
        "links": [{"source": "a", "target": "b", "delay_s": 1,
                   "contact_interval_s": 4, "success_probability": 0.5}],
        "initially_informed": [],
    }
    fact = {"id": "f", "kind": "facility_failed", "time_s": 2,
            "issued_at_s": 2, "source_id": "a", "payload": {"facility_id": "clinic"}}
    first = diffuse_information([fact], net, 50, 987)
    assert first == diffuse_information([fact], net, 50, 987)
    assert first[0]["recipient_id"] == "a"
    assert first[0]["received_at_s"] == 2
    assert len(first) == 2
    assert first[1]["received_at_s"] in {5 + 4 * n for n in range(12)}
    assert first[1]["issued_at_s"] == 2
    assert first[1]["facility_id"] == "clinic"



def test_link_reordering_does_not_change_loss_draws_or_received_facts():
    net = {
        "agents": ["a", "b", "c"],
        "initially_informed": [],
        "links": [
            {"source": "a", "target": "b", "delay_s": 1,
             "contact_interval_s": 4, "success_probability": 0.35},
            {"source": "b", "target": "c", "delay_s": 2,
             "contact_interval_s": 5, "success_probability": 0.4},
            {"source": "a", "target": "c", "delay_s": 3,
             "contact_interval_s": 7, "success_probability": 0.2},
        ],
    }
    facts = [
        {"id": f"fact-{i}", "kind": "road_closed", "time_s": i,
         "source_id": "a", "payload": {"edge_id": f"road-{i}"}}
        for i in range(8)
    ]
    first = diffuse_information(facts, net, 100, 901)
    net["links"].reverse()
    assert diffuse_information(facts, net, 100, 901) == first


def test_invalid_links_and_duplicate_parallel_links_are_rejected():
    base = {"agents": ["a", "b"], "initially_informed": [],
            "links": [{"source": "a", "target": "b", "delay_s": 1,
                       "contact_interval_s": 4, "success_probability": 0.8}]}
    fact = {"id": "f", "kind": "road_closed", "time_s": 0,
            "source_id": "a", "payload": {"edge_id": "r"}}
    for field, bad in (("delay_s", -1), ("delay_s", float("inf")),
                       ("contact_interval_s", -2), ("success_probability", -0.1),
                       ("success_probability", 1.1), ("success_probability", float("nan"))):
        net = copy.deepcopy(base)
        net["links"][0][field] = bad
        with pytest.raises((TypeError, ValueError)):
            diffuse_information([fact], net, 20, 1)
    net = copy.deepcopy(base)
    net["links"].append(copy.deepcopy(net["links"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        diffuse_information([fact], net, 20, 1)
