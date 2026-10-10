from dataclasses import FrozenInstanceError

import pytest

from services.planner.policies import (
    AdaptiveDispatch,
    Candidate,
    PolicyView,
    PriorityGreedy,
    StaticDispatch,
)


def candidate(action_id, *, vehicle="v1", request="r1", kind="supply", quantity=1,
              arrival=0.0, deadline=None, travel=1.0, route="route-a",
              margin=None, feasible=True):
    return Candidate(
        action_id, vehicle, request, kind, quantity, arrival, deadline,
        travel, route, margin, feasible,
    )


def view(*candidates, time=0.0, observations=()):
    return PolicyView(time, tuple(observations), tuple(candidates))


def test_priority_greedy_uses_humanitarian_tier_before_deadline_and_travel():
    supply = candidate("supply", kind="supply", deadline=1.0, travel=1.0)
    urgent_medical = candidate("medical", request="r2", kind="medical", deadline=50.0, travel=99.0)
    assert PriorityGreedy().choose(view(supply, urgent_medical)) == urgent_medical


def test_priority_greedy_deadline_travel_and_ids_are_deterministic():
    later = candidate("z", request="z", kind="medical", deadline=20, travel=2)
    faster = candidate("a", request="a", kind="medical", deadline=20, travel=1)
    earliest = candidate("m", request="m", kind="medical", deadline=10, travel=99)
    policy = PriorityGreedy()
    assert policy.choose(view(later, faster, earliest)) == earliest
    assert policy.choose(view(later, faster)) == faster
    tied = candidate("b", request="b", kind="medical", deadline=20, travel=1)
    assert policy.choose(view(tied, faster)) == faster


def test_policies_are_deterministic_for_identical_visible_history():
    options = (
        candidate("slow", kind="evacuation", travel=4, route="r2"),
        candidate("fast", kind="evacuation", travel=2, route="r1"),
    )
    observation = {"type": "closure", "route_id": "r2", "received_at_s": 1}
    visible = view(*options, observations=(observation,))
    assert PriorityGreedy().choose(visible) == PriorityGreedy().choose(visible)
    assert AdaptiveDispatch().choose(visible) == AdaptiveDispatch().choose(visible)


def test_adaptive_excludes_negative_margin_and_prefers_larger_known_margin_on_same_pair():
    unsafe = candidate("unsafe", kind="evacuation", route="closed", travel=1, margin=-0.1)
    unknown = candidate("unknown", kind="evacuation", route="unknown", travel=2, margin=None)
    narrow = candidate("narrow", kind="evacuation", route="near", travel=1, margin=0.0)
    detour = candidate("detour", kind="evacuation", route="open", travel=7, margin=4.0)
    assert AdaptiveDispatch().choose(view(unsafe, unknown, narrow, detour)) == detour


def test_adaptive_accepts_unknown_forecast_without_claiming_certainty():
    unknown = candidate("unknown", kind="medical", margin=None)
    assert AdaptiveDispatch().choose(view(unknown)) == unknown


def test_static_dispatch_does_not_adapt_to_a_later_detour():
    original = candidate("initial", kind="evacuation", route="r1", travel=2)
    policy = StaticDispatch()
    assert policy.choose(view(original)) == original

    detour = candidate("detour", kind="evacuation", route="r2", travel=8)
    assert policy.choose(view(detour, time=10)) is None


def test_static_dispatch_keeps_initial_route_when_it_remains_feasible():
    initial = candidate("initial", kind="medical", route="r1", travel=3)
    policy = StaticDispatch()
    policy.choose(view(initial))
    still_same = candidate("next-action", kind="medical", route="r1", travel=5)
    assert policy.choose(view(still_same, time=2)) == still_same


def test_infeasible_and_negative_margin_candidates_are_never_selected():
    infeasible = candidate("no", kind="medical", feasible=False)
    negative = candidate("negative", kind="medical", margin=-0.01)
    for policy in (PriorityGreedy(), AdaptiveDispatch(), StaticDispatch()):
        assert policy.choose(view(infeasible, negative)) is None


@pytest.mark.parametrize("kwargs", [
    {"quantity": 0},
    {"quantity": -1},
    {"quantity": True},
    {"arrival": float("nan")},
    {"arrival": float("inf")},
    {"deadline": float("nan")},
    {"travel": -1},
    {"travel": float("inf")},
    {"margin": float("nan")},
    {"kind": "water"},
    {"route": ""},
    {"feasible": 1},
])
def test_bad_candidates_are_rejected(kwargs):
    with pytest.raises((TypeError, ValueError)):
        candidate("bad", **kwargs)


def test_bad_view_time_is_rejected():
    with pytest.raises((TypeError, ValueError)):
        view(time=float("nan"))


def test_public_data_records_are_frozen():
    c = candidate("a")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        c.action_id = "mutated"
