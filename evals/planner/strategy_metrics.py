"""Paired, shared-seed outcome summaries for synthetic aid-strategy evaluations.

The Sharpe-style score is mean paired gain divided by its sample standard deviation.
It is a standardized scenario comparison, not annualized investment Sharpe or a
calibrated real-world risk estimate. See William F. Sharpe's differential-return
formula: https://web.stanford.edu/~wfsharpe/art/sr/sr.htm
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


_REQUIRED_METRICS = (
    "safe_arrivals",
    "medical_on_time",
    "supplies_delivered",
    "travel_s",
    "unmet_urgent_people",
    "route_failures",
    "constraint_violations",
)
_DEFAULT_BASELINES = ("priority_greedy", "static")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _metric_value(metrics: Mapping[str, Any], key: str, where: str) -> float:
    if key not in metrics:
        raise ValueError(f"{where} is missing required metric {key!r}")
    value = metrics[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{where}.{key} must be a finite nonnegative number")
    if not math.isfinite(value):
        raise ValueError(f"{where}.{key} must be finite")
    if value < 0:
        raise ValueError(f"{where}.{key} must be nonnegative")
    return float(value)


def _validate_report(report: dict) -> dict[str, dict[Any, dict]]:
    if not isinstance(report, dict):
        raise TypeError("report must be a dictionary")
    if "runs" not in report or not isinstance(report["runs"], list):
        raise TypeError("report['runs'] must be a list")
    if not report["runs"]:
        raise ValueError("report must contain at least one run")

    by_policy: dict[str, dict[Any, dict]] = {}
    for index, row in enumerate(report["runs"]):
        where = f"runs[{index}]"
        if not isinstance(row, dict):
            raise TypeError(f"{where} must be a dictionary")
        policy = _name(row.get("policy"), f"{where}.policy")
        seed = row.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError(f"{where}.seed must be an integer")
        failed = row.get("evaluation_failed")
        if not isinstance(failed, bool):
            raise TypeError(f"{where}.evaluation_failed must be a bool")
        metrics = row.get("metrics")
        if metrics is None:
            if not failed:
                raise ValueError(f"{where}.metrics may be None only for failed evaluations")
        else:
            if not isinstance(metrics, Mapping):
                raise TypeError(f"{where}.metrics must be a mapping or None")
            for key in _REQUIRED_METRICS:
                _metric_value(metrics, key, f"{where}.metrics")
        policy_rows = by_policy.setdefault(policy, {})
        if seed in policy_rows:
            raise ValueError(f"duplicate run for policy {policy!r}, seed {seed!r}")
        policy_rows[seed] = {"evaluation_failed": failed, "metrics": metrics}

    if any(not rows for rows in by_policy.values()):
        raise ValueError("every policy must have at least one run")
    expected_seeds = set(next(iter(by_policy.values())))
    for policy, rows in by_policy.items():
        if set(rows) != expected_seeds:
            raise ValueError("all policies must have identical seed sets")
    return by_policy


def _linear_quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _lower_tail_mean(values: list[float], tail_fraction: float = 0.10) -> float:
    ordered = sorted(values)
    mass = len(ordered) * tail_fraction
    whole = math.floor(mass)
    remainder = mass - whole
    total = math.fsum(ordered[:whole])
    if remainder and whole < len(ordered):
        total += remainder * ordered[whole]
    return total / mass


def _ratio(value: float | None, reason: str | None = None) -> tuple[float | None, str | None]:
    if value is None:
        return None, reason
    if not math.isfinite(value):
        raise ValueError("computed ratio is nonfinite")
    return value, None


def _summarize(
    name: str,
    paired_deltas: list[dict],
    baseline_total: float,
    failed_pair_count: int,
) -> dict:
    gains = [float(delta["gain"]) for delta in paired_deltas]
    n = len(gains)
    total_gain = math.fsum(gains)
    mean_gain = total_gain / n if n else None
    sample_stddev = None
    if n >= 2:
        sample_stddev = math.sqrt(math.fsum((gain - mean_gain) ** 2 for gain in gains) / (n - 1))
        if not math.isfinite(sample_stddev):
            raise ValueError(f"nonfinite sample standard deviation for {name}")
    downside_rms = (
        math.sqrt(math.fsum(min(gain, 0.0) ** 2 for gain in gains) / n)
        if n else None
    )
    if downside_rms is not None and not math.isfinite(downside_rms):
        raise ValueError(f"nonfinite downside RMS for {name}")

    incomplete = failed_pair_count > 0
    if incomplete:
        sharpe, sharpe_reason = None, "incomplete_evaluation"
        downside_adjusted, downside_reason = None, "incomplete_evaluation"
        relative, relative_reason = None, "incomplete_evaluation"
    else:
        if n < 2:
            sharpe, sharpe_reason = None, "insufficient_scenarios"
        elif sample_stddev == 0:
            sharpe, sharpe_reason = None, "zero_variance"
        else:
            sharpe, sharpe_reason = _ratio(mean_gain / sample_stddev)
        if not n:
            downside_adjusted, downside_reason = None, "insufficient_scenarios"
        elif downside_rms == 0:
            downside_adjusted, downside_reason = None, "zero_downside"
        else:
            downside_adjusted, downside_reason = _ratio(mean_gain / downside_rms)
        if baseline_total == 0:
            relative, relative_reason = None, "zero_baseline"
        else:
            relative, relative_reason = _ratio(100 * total_gain / baseline_total)

    return {
        "measure": name,
        "paired_deltas": paired_deltas,
        "paired_sample_count": n,
        "evaluation_failed_pair_count": failed_pair_count,
        "total_gain": total_gain,
        "mean_gain": mean_gain,
        "baseline_total": baseline_total,
        "relative_gain_percent": relative,
        "relative_gain_reason": relative_reason,
        "sample_stddev": sample_stddev,
        "sharpe_style_paired_gain": sharpe,
        "sharpe_style_reason": sharpe_reason,
        "standard_error": (
            sample_stddev / math.sqrt(n) if sample_stddev is not None and n else None
        ),
        "downside_rms": downside_rms,
        "downside_adjusted_gain": downside_adjusted,
        "downside_adjusted_reason": downside_reason,
        "worst_gain": min(gains) if gains else None,
        "p10_gain": _linear_quantile(gains, 0.10) if gains else None,
        "lower_tail_mean_10pct": _lower_tail_mean(gains) if gains else None,
        "statistics_scope": (
            "partial_completed_pairs" if incomplete else "all_paired_scenarios"
        ),
        "rankable": not incomplete,
    }


def paired_strategy_metrics(
    report: dict,
    baselines: tuple[str, ...] = _DEFAULT_BASELINES,
) -> dict:
    """Compare every policy to each requested baseline using its shared seeds.

    Rows are paired only when both policy evaluations for a seed completed. Failed
    pairs remain counted and force the comparison's ratios to be non-rankable.
    """
    if not isinstance(baselines, tuple):
        raise TypeError("baselines must be a tuple of policy names")
    clean_baselines = tuple(_name(value, "baseline") for value in baselines)
    if len(set(clean_baselines)) != len(clean_baselines):
        raise ValueError("baselines must be unique")

    by_policy = _validate_report(report)
    missing = [base for base in clean_baselines if base not in by_policy]
    if missing:
        raise ValueError(f"baseline policy missing from report: {missing[0]!r}")

    policies = sorted(by_policy)
    seeds = sorted(next(iter(by_policy.values())))
    comparisons: dict[str, dict[str, dict]] = {}
    failures_by_policy = {
        policy: sum(row["evaluation_failed"] for row in rows.values())
        for policy, rows in by_policy.items()
    }
    violations_by_policy = {
        policy: sum(
            _metric_value(row["metrics"], "constraint_violations", f"{policy}/{seed}.metrics")
            for seed, row in rows.items()
            if row["metrics"] is not None
        )
        for policy, rows in by_policy.items()
    }

    measure_defs = {
        "humanitarian_units": ("benefit", lambda m: m["safe_arrivals"] + m["medical_on_time"]),
        "safe_arrivals": ("benefit", lambda m: m["safe_arrivals"]),
        "medical_on_time": ("benefit", lambda m: m["medical_on_time"]),
        "supplies_delivered": ("benefit", lambda m: m["supplies_delivered"]),
        "travel_s": ("cost", lambda m: m["travel_s"]),
        "unmet_urgent_people": ("cost", lambda m: m["unmet_urgent_people"]),
        "route_failures": ("cost", lambda m: m["route_failures"]),
    }

    for policy in policies:
        for baseline in clean_baselines:
            if policy == baseline:
                continue
            failed_seeds = [
                seed for seed in seeds
                if by_policy[policy][seed]["evaluation_failed"]
                or by_policy[baseline][seed]["evaluation_failed"]
            ]
            complete_seeds = [seed for seed in seeds if seed not in set(failed_seeds)]
            measure_summaries = {}
            for measure_name, (direction, value_of) in measure_defs.items():
                deltas = []
                base_values = []
                for seed in complete_seeds:
                    candidate_metrics = by_policy[policy][seed]["metrics"]
                    baseline_metrics = by_policy[baseline][seed]["metrics"]
                    candidate_value = value_of(candidate_metrics)
                    baseline_value = value_of(baseline_metrics)
                    gain = (
                        candidate_value - baseline_value
                        if direction == "benefit"
                        else baseline_value - candidate_value
                    )
                    if not math.isfinite(gain):
                        raise ValueError(f"nonfinite paired gain for {measure_name}")
                    deltas.append({"seed": seed, "gain": gain})
                    base_values.append(baseline_value)
                measure_summaries[measure_name] = _summarize(
                    measure_name, deltas, math.fsum(base_values), len(failed_seeds)
                )

            candidate_metrics = [
                row["metrics"] for row in by_policy[policy].values()
                if row["metrics"] is not None
            ]
            candidate_violations = math.fsum(
                _metric_value(m, "constraint_violations", f"{policy}.metrics")
                for m in candidate_metrics
            )
            candidate_failed = failures_by_policy[policy]
            complete = not failed_seeds
            comparisons.setdefault(policy, {})[baseline] = {
                "policy": policy,
                "baseline": baseline,
                "measures": measure_summaries,
                "evaluation_failed_pair_count": len(failed_seeds),
                "failed_pair_seeds": failed_seeds,
                "candidate_evaluation_failed_count": candidate_failed,
                "baseline_evaluation_failed_count": failures_by_policy[baseline],
                "complete_evaluation": complete,
                "rankable": complete,
                "simulated_feasibility": candidate_failed == 0 and candidate_violations == 0,
                "candidate_constraint_violations": candidate_violations,
            }

    candidate_policies = [p for p in policies if p not in clean_baselines]
    overall_deployable = all(
        failures_by_policy[p] == 0 and violations_by_policy[p] == 0
        for p in candidate_policies
    )
    return {
        "method": (
            "synthetic shared-seed paired gains; Sharpe-style score is mean paired "
            "gain divided by sample standard deviation, not annualized"
        ),
        "provenance": (
            "Computed from paired synthetic evaluation scenarios with identical seeds. "
            "Differential-return formula follows William F. Sharpe, "
            "https://web.stanford.edu/~wfsharpe/art/sr/sr.htm. "
            "This is not a calibrated real-world risk estimate."
        ),
        "optimality_claim": "none",
        "policy_seed_sets": {policy: seeds.copy() for policy in policies},
        "comparisons": comparisons,
        "complete_evaluation": all(
            comparison["complete_evaluation"]
            for pairs in comparisons.values()
            for comparison in pairs.values()
        ),
        "simulated_feasibility": overall_deployable,
    }


__all__ = ["paired_strategy_metrics"]
