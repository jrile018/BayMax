import math

import pytest

from evals.planner.strategy_metrics import paired_strategy_metrics


METRICS = {
    "safe_arrivals": 1,
    "medical_on_time": 0,
    "supplies_delivered": 2,
    "travel_s": 10,
    "unmet_urgent_people": 5,
    "route_failures": 1,
    "constraint_violations": 0,
}


def row(policy, seed, *, metrics=None, failed=False):
    return {
        "policy": policy,
        "seed": seed,
        "evaluation_failed": failed,
        "metrics": METRICS.copy() if metrics is None and not failed else metrics,
    }


def measure(result, policy="adaptive", baseline="priority_greedy", name="safe_arrivals"):
    return result["comparisons"][policy][baseline]["measures"][name]


def test_hand_derived_paired_sharpe_downside_and_empirical_tail():
    baseline = [row("priority_greedy", i) for i in range(4)]
    candidate_metrics = []
    for gain in [2, 0, -1, 3]:
        metrics = METRICS.copy()
        metrics["safe_arrivals"] += gain
        candidate_metrics.append(metrics)
    report = paired_strategy_metrics({
        "runs": baseline + [
            row("adaptive", i, metrics=m) for i, m in enumerate(candidate_metrics)
        ]
    }, baselines=("priority_greedy",))
    summary = measure(report)
    assert summary["paired_deltas"] == [
        {"seed": 0, "gain": 2}, {"seed": 1, "gain": 0},
        {"seed": 2, "gain": -1}, {"seed": 3, "gain": 3},
    ]
    assert summary["paired_sample_count"] == 4
    assert summary["total_gain"] == 4
    assert summary["mean_gain"] == 1
    assert summary["sample_stddev"] == pytest.approx(math.sqrt(10 / 3))
    assert summary["sharpe_style_paired_gain"] == pytest.approx(1 / math.sqrt(10 / 3))
    assert summary["downside_rms"] == pytest.approx(0.5)
    assert summary["downside_adjusted_gain"] == pytest.approx(2)
    assert summary["worst_gain"] == -1
    assert summary["p10_gain"] == pytest.approx(-0.7)
    assert summary["lower_tail_mean_10pct"] == pytest.approx(-1)


def test_all_positive_constant_gain_has_undefined_zero_variance_ratio():
    runs = [row("priority_greedy", s) for s in range(3)]
    for s in range(3):
        metrics = METRICS.copy()
        metrics["safe_arrivals"] += 2
        runs.append(row("adaptive", s, metrics=metrics))
    summary = measure(paired_strategy_metrics({"runs": runs}, baselines=("priority_greedy",)))
    assert summary["total_gain"] == 6
    assert summary["sharpe_style_paired_gain"] is None
    assert summary["sharpe_style_reason"] == "zero_variance"
    assert summary["downside_adjusted_gain"] is None
    assert summary["downside_adjusted_reason"] == "zero_downside"


def test_zero_baseline_total_leaves_relative_gain_undefined():
    runs = []
    for seed in [1, 2]:
        base = METRICS.copy()
        base["safe_arrivals"] = 0
        candidate = base.copy()
        candidate["safe_arrivals"] = 1
        runs.extend([row("priority_greedy", seed, metrics=base),
                     row("adaptive", seed, metrics=candidate)])
    summary = measure(paired_strategy_metrics({"runs": runs}, baselines=("priority_greedy",)))
    assert summary["baseline_total"] == 0
    assert summary["relative_gain_percent"] is None
    assert summary["relative_gain_reason"] == "zero_baseline"


def test_cost_metrics_reverse_sign_and_humanitarian_metrics_stay_disaggregated():
    baseline = METRICS.copy()
    candidate = METRICS.copy()
    candidate.update(travel_s=7, unmet_urgent_people=3, route_failures=0,
                     safe_arrivals=2, medical_on_time=1, supplies_delivered=4)
    result = paired_strategy_metrics({"runs": [
        row("priority_greedy", 5, metrics=baseline),
        row("adaptive", 5, metrics=candidate),
    ]}, baselines=("priority_greedy",))
    comparison = result["comparisons"]["adaptive"]["priority_greedy"]
    assert comparison["measures"]["travel_s"]["paired_deltas"] == [
        {"seed": 5, "gain": 3}
    ]
    assert comparison["measures"]["unmet_urgent_people"]["paired_deltas"] == [
        {"seed": 5, "gain": 2}
    ]
    assert comparison["measures"]["route_failures"]["paired_deltas"] == [
        {"seed": 5, "gain": 1}
    ]
    assert comparison["measures"]["humanitarian_units"]["paired_deltas"] == [
        {"seed": 5, "gain": 2}
    ]
    assert {"safe_arrivals", "medical_on_time", "supplies_delivered"} <= set(comparison["measures"])


def test_failed_pair_keeps_partial_totals_but_is_not_rankable():
    runs = []
    for seed in [1, 2, 3]:
        runs.append(row("priority_greedy", seed, failed=(seed == 2), metrics=None))
        candidate = METRICS.copy()
        candidate["safe_arrivals"] += (2 if seed == 1 else 0)
        runs.append(row("adaptive", seed, failed=(seed == 2), metrics=None if seed == 2 else candidate))
    result = paired_strategy_metrics({"runs": runs}, baselines=("priority_greedy",))
    comparison = result["comparisons"]["adaptive"]["priority_greedy"]
    summary = comparison["measures"]["safe_arrivals"]
    assert summary["evaluation_failed_pair_count"] == 1
    assert comparison["complete_evaluation"] is False
    assert comparison["failed_pair_seeds"] == [2]
    assert summary["paired_sample_count"] == 2
    assert summary["total_gain"] == 2
    assert summary["statistics_scope"] == "partial_completed_pairs"
    assert summary["sharpe_style_paired_gain"] is None
    assert summary["sharpe_style_reason"] == "incomplete_evaluation"
    assert summary["downside_adjusted_gain"] is None
    assert summary["relative_gain_percent"] is None
    assert comparison["simulated_feasibility"] is False


def test_constraints_remain_visible_and_make_candidate_infeasible():
    baseline = METRICS.copy()
    candidate = METRICS.copy()
    candidate["constraint_violations"] = 1
    result = paired_strategy_metrics({"runs": [
        row("priority_greedy", 7, metrics=baseline),
        row("adaptive", 7, metrics=candidate),
    ]}, baselines=("priority_greedy",))
    comparison = result["comparisons"]["adaptive"]["priority_greedy"]
    assert comparison["candidate_constraint_violations"] == 1
    assert comparison["simulated_feasibility"] is False


@pytest.mark.parametrize("runs", [
    [row("priority_greedy", 1), row("adaptive", 2)],
    [row("priority_greedy", 1), row("adaptive", 1), row("adaptive", 1)],
])
def test_mismatched_or_duplicate_policy_seed_sets_are_rejected(runs):
    with pytest.raises((TypeError, ValueError)):
        paired_strategy_metrics({"runs": runs}, baselines=("priority_greedy",))


@pytest.mark.parametrize("bad", [None, -1, float("nan"), float("inf"), "1"])
def test_missing_negative_or_nonfinite_metric_values_are_rejected(bad):
    metrics = METRICS.copy()
    metrics["travel_s"] = bad
    with pytest.raises((TypeError, ValueError)):
        paired_strategy_metrics({"runs": [
            row("priority_greedy", 1, metrics=metrics),
            row("adaptive", 1),
        ]})


def test_missing_required_metric_is_rejected():
    metrics = METRICS.copy()
    del metrics["safe_arrivals"]
    with pytest.raises((TypeError, ValueError)):
        paired_strategy_metrics({"runs": [
            row("priority_greedy", 1, metrics=metrics),
            row("adaptive", 1),
        ]})


def test_provenance_labels_synthetic_paired_gain_not_investment_sharpe():
    result = paired_strategy_metrics({"runs": [
        row("priority_greedy", 1),
        row("adaptive", 1),
        row("static", 1),
    ]})
    assert "synthetic" in result["method"].lower()
    assert "paired" in result["method"].lower()
    assert "not annualized" in result["method"].lower()
    assert result["optimality_claim"] == "none"



def test_signed_integer_seeds_are_valid_shared_seed_keys():
    result = paired_strategy_metrics({"runs": [
        row("priority_greedy", -3),
        row("adaptive", -3),
        row("static", -3),
    ]})
    assert result["policy_seed_sets"]["adaptive"] == [-3]
