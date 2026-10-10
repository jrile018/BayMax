"""Behavioral checks for finite trainee practice packs."""
import json
import re

import pytest

from evals.planner.practice import build_practice_pack, render_practice_html


class SmallWorld:
    def __init__(self, situation, future):
        self.situation = situation
        self.future = future
        self.time_s = 0
        self.horizon_end_s = 45
        self.served = 0
        self.moves = []

    def knowledge(self, recipient_id=None):
        return {
            "time_s": self.time_s,
            "observations": [{"source_id": "camp-a", "payload": {"note": "</script><img src=x onerror=alert(1)>"},
                              "received_at_s": 0}],
            "requests": [{"id": "need-a", "kind": "medical", "quantity": 1}],
            "goals": {"urgent": "serve people"},
        }

    def actions(self):
        return [
            {"id": "wait", "kind": "wait", "explanation": "Wait for radio"},
            {"id": "move-amb", "kind": "dispatch", "vehicle_id": "amb", "request_id": "need-a",
             "expected_urgent": 1, "explanation": "Move ambulance"},
            {"id": "move-bus", "kind": "reposition", "vehicle_id": "bus",
             "explanation": "Move bus"},
            {"id": "unsupported", "kind": "dispatch", "vehicle_id": "x", "feasible": False},
        ]

    def step(self, action_id):
        self.moves.append(action_id)
        if action_id == "move-amb":
            self.served += 1
        self.time_s = min(self.time_s + 15, self.horizon_end_s)
        return {"hidden": self.future}

    def advance_to(self, time_s):
        self.time_s = time_s

    def outcome(self):
        return {"metrics": {"safe_arrivals": self.served, "medical_on_time": self.served,
                            "supplies_delivered": 0, "travel_s": len(self.moves),
                            "route_failures": 0, "unmet_urgent_people": 1 - min(self.served, 1)},
                "events": self.moves, "final_state": {"served": self.served},
                "arrival_times_s": []}


def _episode():
    return {"name": "Practice 1", "situation": {"scenario_id": "private"},
            "future": {"truth_events": [{"id": "secret-closure", "time_s": 15}],
                       "seed": 999, "latent": "private"}}


def _walk(node):
    yield node
    for child in node.get("children", {}).values():
        yield from _walk(child)


def test_pack_has_bounds_distinct_choices_and_consequences():
    pack = build_practice_pack([_episode()], world_factory=SmallWorld, branch_limit=3, depth_limit=2)
    assert pack["limits"] == {"branch_limit": 3, "depth_limit": 2}
    root = pack["episodes"][0]["root"]
    assert [a["id"] for a in root["actions"]] == ["wait", "move-amb", "move-bus"]
    assert set(root["children"]) == {"wait", "move-amb", "move-bus"}
    assert "debrief" not in root
    assert max(n["depth"] for n in _walk(root)) == 2
    assert all(len(n.get("actions", [])) <= 3 for n in _walk(root))
    assert root["children"]["move-amb"]["children"]["wait"]["debrief"]["metrics"]["safe_arrivals"] == 1
    assert root["children"]["wait"]["children"]["wait"]["debrief"]["metrics"]["safe_arrivals"] == 0
    packed = json.dumps(pack)
    assert "secret-closure" not in packed
    assert '"seed"' not in packed
    assert '"truth_events"' not in packed
    assert '"latent"' not in packed
    for node in _walk(root):
        if node.get("children"):
            assert "debrief" not in node
            assert "outcome" not in node
            assert "final_state" not in node


def test_reproducible_and_html_script_safe():
    first = build_practice_pack([_episode()], world_factory=SmallWorld, depth_limit=1)
    second = build_practice_pack([_episode()], world_factory=SmallWorld, depth_limit=1)
    assert first == second
    html = render_practice_html()
    assert len(re.findall(r"</script", html, flags=re.I)) == 1
    assert "<img src=x" not in html
    assert "\\u003c/img" not in html  # no raw malicious HTML element in markup
    assert "branch_limit" in html
    assert "node.children" not in html
    assert "Restart" in html
    assert "Thinking time" in html
    assert "Instructor severity scale" in html
    assert [x["level"] for x in first["severity_scale"]] == list(range(1, 11))


def test_rejects_leaky_visible_payload():
    class LeakyWorld(SmallWorld):
        def knowledge(self, recipient_id=None):
            known = super().knowledge(recipient_id)
            known["truth_events"] = self.future["truth_events"]
            return known
    with pytest.raises(ValueError, match="truth_events"):
        build_practice_pack([_episode()], world_factory=LeakyWorld)


def test_cli_artifacts_are_paired_and_reproducible():
    from evals.planner.run_training import create_training_artifacts

    class CompleteWorld(SmallWorld):
        def outcome(self):
            base = super().outcome()
            base["metrics"].update({
                "medical_completed": self.served, "unmet_goods": 0,
                "constraint_violations": 0, "stranded_vehicle_s": 0,
            })
            return base

    def situation(seed, severity):
        return {"scenario_id": f"example-{seed}", "severity": severity,
                "assumptions": {"level": severity}}

    def future(situation, seed):
        return {"seed": seed, "truth_events": [{"id": f"private-{seed}"}]}

    def planner(knowledge, actions):
        return {"chosen_action": next(a for a in actions if a["id"] == "move-amb"),
                "reasons": ["Received medical need"], "score_components": {}}

    kwargs = dict(situation_factory=situation, future_factory=future,
                  world_factory=CompleteWorld, planner=planner, depth_limit=1)
    first = create_training_artifacts(17, 7, 2, **kwargs)
    second = create_training_artifacts(17, 7, 2, **kwargs)
    assert first == second
    situations, futures, evaluations, summary, pack = first
    full = evaluations["full_mission"]
    finite = evaluations["finite_practice"]
    assert [row["seed"] for row in situations] == [17, 19]
    assert [row["seed"] for row in futures] == [18, 20]
    assert all(row["situational"]["metrics"]["safe_arrivals"] ==
               row["priority_greedy"]["metrics"]["safe_arrivals"] for row in full)
    assert all(len(row["situational"]["trace"]) == len(row["priority_greedy"]["trace"]) == 1
               for row in finite)
    assert all(len(row["situational"]["trace"]) == len(row["priority_greedy"]["trace"]) == 3
               for row in full)
    assert pack["episodes"][0]["root"]["children"]["wait"]["debrief"]["comparison"]["decision_budget"] == 1
    assert summary["paired"]["service"]["safe_arrivals"]["paired_sample_count"] == 2
    assert summary["finite_practice_paired"]["service"]["safe_arrivals"]["paired_sample_count"] == 2
    assert summary["paired"]["service"]["safe_arrivals"]["standardized_reason"] == "zero_variance"
    assert "private-18" not in json.dumps(pack)


def test_real_finite_comparators_follow_exported_menu_and_outcome():
    from evals.planner.run_training import create_training_artifacts

    _, _, evaluations, _, pack = create_training_artifacts(
        0, 7, 1, depth_limit=2, branch_limit=3)
    finite = evaluations["finite_practice"][0]
    for policy in ("situational", "priority_greedy"):
        node = pack["episodes"][0]["root"]
        for step in finite[policy]["trace"]:
            assert step["action_id"] in {a["id"] for a in node["actions"]}
            node = node["children"][step["action_id"]]
        assert node["debrief"]["metrics"] == finite[policy]["metrics"]


def test_instructor_profile_and_coverage_threshold_are_recorded():
    from evals.planner.run_training import create_training_artifacts

    class FullWorld(SmallWorld):
        def outcome(self):
            result = super().outcome()
            result["metrics"].update({"medical_completed": self.served, "unmet_goods": 0,
                                      "constraint_violations": 0, "stranded_vehicle_s": 0})
            return result

    def situation(seed, severity):
        return {"scenario_id": f"s-{seed}", "assumptions": {}, "goals": {}}

    def planner(knowledge, actions):
        return {"chosen_action": actions[0], "reasons": [], "score_components": {}}

    situations, _, _, summary, _ = create_training_artifacts(
        5, 7, 1, situation_factory=situation,
        future_factory=lambda situation, seed: {"seed": seed},
        world_factory=FullWorld, planner=planner, depth_limit=1,
        profile_overrides={"road_failure_probability": 0.2},
        coverage_threshold_s=90)
    assert situations[0]["situation"]["assumptions"]["road_failure_probability"] == 0.2
    assert situations[0]["situation"]["goals"]["coverage_threshold_s"] == 90
    assert summary["coverage_threshold_s"] == 90
