"""Generate reproducible synthetic first-responder training artifacts."""
from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
from pathlib import Path

from evals.planner.practice import build_practice_pack, render_practice_html, select_practice_actions
from services.planner.futures.training import build_training_future, generate_situation, severity_profile
from services.planner.policies.situational import plan_situation


_SERVICE = ("safe_arrivals", "medical_on_time", "medical_completed", "supplies_delivered")
_COSTS = ("unmet_urgent_people", "unmet_goods", "travel_s", "stranded_vehicle_s",
          "route_failures", "constraint_violations")
_ALL_METRICS = _SERVICE + _COSTS


def _json_file(path, value):
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False,
                               allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _legal_actions(world):
    actions = world.actions()
    return [a for a in actions if a.get("feasible", True) and a.get("supported", True)]


def _greedy_action(actions):
    """Visible-state comparator: urgent service, supply, shorter estimated travel."""
    moves = [a for a in actions if a.get("kind") != "wait"]
    if not moves:
        return next((a for a in actions if a.get("kind") == "wait"), None)
    return min(moves, key=lambda a: (
        -float(a.get("expected_urgent") or 0),
        -float(a.get("expected_supply") or 0),
        float(a.get("travel_s") or 0),
        str(a.get("id")),
    ))


def evaluate_episode(situation, future, policy, *, world_factory=None, planner=plan_situation, decision_limit=None, branch_limit=None):
    """Run one policy with received knowledge only on a fresh copy of a fixed future."""
    if policy not in ("situational", "priority_greedy"):
        raise ValueError("unsupported policy")
    if world_factory is None:
        from evals.planner.training_world import TrainingWorld
        world_factory = TrainingWorld
    world = world_factory(copy.deepcopy(situation), copy.deepcopy(future))
    if decision_limit is not None and (isinstance(decision_limit, bool) or not isinstance(decision_limit, int) or decision_limit < 1):
        raise ValueError("decision_limit must be a positive integer")
    trace = []
    while world.time_s < world.horizon_end_s and (decision_limit is None or len(trace) < decision_limit):
        before = world.time_s
        knowledge = world.knowledge()
        actions = (select_practice_actions(world.actions(), branch_limit)
                   if branch_limit is not None else _legal_actions(world))
        if policy == "situational":
            decision = planner(copy.deepcopy(knowledge), copy.deepcopy(actions))
            chosen = decision.get("chosen_action")
            if chosen is not None and chosen.get("id") not in {a["id"] for a in actions}:
                raise ValueError("planner selected an unavailable action")
            reason = decision.get("reasons", [])
            scores = decision.get("score_components", {})
        else:
            chosen = _greedy_action(actions)
            reason = ["Comparison rule: highest visible urgent service, then supply, then shorter travel."]
            scores = {}
        if chosen is None:
            world.advance_to(min(world.horizon_end_s, before + 15))
            action_id = None
        else:
            action_id = chosen["id"]
            world.step(action_id)
        if world.time_s <= before:
            raise ValueError("world failed to advance")
        trace.append({"time_s": before, "action_id": action_id, "chosen_action": copy.deepcopy(chosen),
                      "reasons": copy.deepcopy(reason), "score_components": copy.deepcopy(scores),
                      "received_observations": copy.deepcopy(knowledge.get("observations", []))})
    if decision_limit is not None:
        world.advance_to(world.horizon_end_s)
    result = world.outcome()
    for name in _ALL_METRICS:
        value = result["metrics"][name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid outcome metric: {name}")
    return {"policy": policy, "trace": trace, **result}


def _metric_summary(rows, metric, service):
    pairs = []
    for row in rows:
        candidate = row["situational"]["metrics"][metric]
        baseline = row["priority_greedy"]["metrics"][metric]
        gain = candidate - baseline if service else baseline - candidate
        pairs.append({"episode": row["episode"], "situational": candidate,
                      "priority_greedy": baseline, "gain": gain})
    gains = [p["gain"] for p in pairs]
    count = len(gains)
    mean = statistics.fmean(gains)
    spread = statistics.stdev(gains) if count >= 2 else None
    if count < 2:
        standardized, reason = None, "insufficient_scenarios"
    elif spread == 0:
        standardized, reason = None, "zero_variance"
    else:
        standardized, reason = mean / spread, None
    return {"unit": metric, "direction": "more_is_better" if service else "less_is_better",
            "paired_sample_count": count, "total_gain": math.fsum(gains), "mean_gain": mean,
            "sample_stddev": spread, "standardized_paired_gain": standardized,
            "standardized_reason": reason, "pairs": pairs}


def summarize_paired(rows):
    if not rows:
        raise ValueError("at least one paired episode required")
    return {
        "method": "Identical synthetic situation and future for each policy within an episode; raw paired gains.",
        "interpretation": "Positive gains favor the situational planner in this synthetic sample. These results do not establish real-world performance improvement.",
        "service": {m: _metric_summary(rows, m, True) for m in _SERVICE},
        "costs": {m: _metric_summary(rows, m, False) for m in _COSTS},
    }


def create_training_artifacts(
    seed, severity, episodes, *,
    situation_factory=generate_situation,
    future_factory=build_training_future,
    world_factory=None,
    planner=plan_situation,
    branch_limit=3,
    depth_limit=3,
    profile_overrides=None,
    coverage_threshold_s=120,
):
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if isinstance(episodes, bool) or not isinstance(episodes, int) or episodes < 1:
        raise ValueError("episodes must be a positive integer")
    if (isinstance(coverage_threshold_s, bool) or not isinstance(coverage_threshold_s, (int, float))
            or not math.isfinite(coverage_threshold_s) or coverage_threshold_s <= 0):
        raise ValueError("coverage_threshold_s must be finite and positive")
    if world_factory is None:
        from evals.planner.training_world import TrainingWorld
        world_factory = TrainingWorld
    instructor_situations = []
    instructor_futures = []
    evaluations = []
    finite_evaluations = []
    practice_episodes = []
    for index in range(episodes):
        situation_seed = seed + 2 * index
        future_seed = seed + 2 * index + 1
        situation = situation_factory(situation_seed, severity=severity)
        if profile_overrides is not None:
            situation["assumptions"] = severity_profile(severity, profile_overrides)
        situation.setdefault("goals", {})["coverage_threshold_s"] = coverage_threshold_s
        future = future_factory(situation, future_seed)
        situational = evaluate_episode(situation, future, "situational",
                                       world_factory=world_factory, planner=planner)
        greedy = evaluate_episode(situation, future, "priority_greedy",
                                  world_factory=world_factory, planner=planner)
        finite_situational = evaluate_episode(situation, future, "situational",
            world_factory=world_factory, planner=planner, decision_limit=depth_limit,
            branch_limit=branch_limit)
        finite_greedy = evaluate_episode(situation, future, "priority_greedy",
            world_factory=world_factory, planner=planner, decision_limit=depth_limit,
            branch_limit=branch_limit)
        label = f"Episode {index + 1}"
        instructor_situations.append({"episode": index + 1, "seed": situation_seed,
                                      "situation": situation})
        instructor_futures.append({"episode": index + 1, "seed": future_seed, "future": future})
        evaluations.append({"episode": index + 1, "situation_seed": situation_seed,
                            "future_seed": future_seed, "situational": situational,
                            "priority_greedy": greedy})
        finite_evaluations.append({"episode": index + 1, "situation_seed": situation_seed,
                            "future_seed": future_seed, "decision_limit": depth_limit,
                            "situational": finite_situational, "priority_greedy": finite_greedy})
        practice_episodes.append({"name": label, "situation": situation, "future": future,
                                  "comparison": {
                                      "decision_budget": depth_limit,
                                      "decision_step_s": 15,
                                      "situational": finite_situational["metrics"],
                                      "priority_greedy": finite_greedy["metrics"],
                                  }})
    summary = {"schema": "synthetic-first-responder-training-v1", "seed": seed,
               "severity": severity, "coverage_threshold_s": coverage_threshold_s,
               "episode_count": episodes,
               "assumptions": instructor_situations[0]["situation"]["assumptions"],
               "paired": summarize_paired(evaluations),
               "paired_scope": "full_mission_autonomous",
               "finite_practice_paired": summarize_paired(finite_evaluations),
               "finite_practice_decision_budget": depth_limit}
    pack = build_practice_pack(practice_episodes, world_factory=world_factory,
                               branch_limit=branch_limit, depth_limit=depth_limit)
    return (instructor_situations, instructor_futures,
            {"full_mission": evaluations, "finite_practice": finite_evaluations}, summary, pack)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate synthetic first-responder practice")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--severity", type=int, default=5, help="instructor-defined ordinal level 1-10")
    parser.add_argument("--episodes", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", "--profile-file", dest="profile_file", type=Path,
                        help="JSON severity assumption overrides")
    parser.add_argument("--coverage-threshold", type=float, default=120,
                        help="instructor response-time coverage goal in seconds")
    args = parser.parse_args(argv)
    profile = json.loads(args.profile_file.read_text(encoding="utf-8")) if args.profile_file else None
    situations, futures, evaluations, summary, pack = create_training_artifacts(
        args.seed, args.severity, args.episodes, profile_overrides=profile,
        coverage_threshold_s=args.coverage_threshold)
    args.output.mkdir(parents=True, exist_ok=True)
    _json_file(args.output / "situations.json", situations)
    _json_file(args.output / "instructor_futures.json", futures)
    _json_file(args.output / "evaluations.json", evaluations)
    _json_file(args.output / "summary.json", summary)
    _json_file(args.output / "practice.json", pack)
    (args.output / "practice.html").write_text(render_practice_html(), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "episodes": args.episodes,
                      "severity": args.severity, "practice_limits": pack["limits"]}, sort_keys=True))


if __name__ == "__main__":
    main()
