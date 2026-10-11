"""Pure accounting for caller-admitted hypothetical comparison fixtures.

This module does not issue bindings, evaluate policies, infer outcomes, or rank
candidates. All input capabilities and rate provenance are caller declarations.
Unavailable values are represented by null plus an explicit reason.
"""

from collections import Counter
from collections.abc import Mapping
from datetime import date
import math
import re


SCHEMA = "baymax.comparison-accounting.v1"
STATUSES = (
    "completed_valid", "crashed", "invalid", "unsupported",
    "canceled", "deadline_exceeded",
)
BINDING_KEYS = (
    "run_id", "generation", "mode", "place_id", "scenario_digest",
    "starting_state_digest", "sampling_version", "model_version",
    "objective_version", "resource_version", "graph_version",
    "horizon_version", "rate_version", "horizon_s",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _string(value):
    return isinstance(value, str) and bool(value)


def _number(value, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return finite and (not positive or value > 0) and (not nonnegative or value >= 0)


def _integer(value, *, positive=False, nonnegative=False):
    return isinstance(value, int) and not isinstance(value, bool) and (
        not positive or value > 0
    ) and (not nonnegative or value >= 0)


def _finite(value):
    """Return a JSON-safe float, or null when arithmetic overflowed."""
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_sum(values):
    total = 0.0
    for value in values:
        total = _finite(total + value)
        if total is None:
            return None
    return total


def _json_finite_tree(value):
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, list):
        return all(_json_finite_tree(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _json_finite_tree(item)
                   for key, item in value.items())
    return False


def _typed_equal(left, right):
    """Exact JSON identity; Boolean and numeric substitutes never match."""
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        return (
            isinstance(left, Mapping) and isinstance(right, Mapping)
            and left.keys() == right.keys()
            and all(_typed_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list) and isinstance(right, list)
            and len(left) == len(right)
            and all(_typed_equal(a, b) for a, b in zip(left, right))
        )
    return type(left) is type(right) and left == right


def _date(value):
    if not _string(value):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _path(mapping, keys):
    value = mapping
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def _validate_manifest(manifest, metric_specs, rate_catalog):
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != SCHEMA:
        raise ValueError("foreign or missing comparison schema")
    binding = manifest.get("binding")
    if not isinstance(binding, Mapping) or any(key not in binding for key in BINDING_KEYS):
        raise ValueError("missing binding fields")
    if not _json_finite_tree(binding):
        raise ValueError("binding must contain finite JSON values")
    for key in BINDING_KEYS:
        value = binding[key]
        if key == "generation":
            if not _integer(value, nonnegative=True):
                raise ValueError("invalid binding generation")
        elif key == "horizon_s":
            if not _number(value, positive=True):
                raise ValueError("invalid binding horizon_s")
        elif not _string(value):
            raise ValueError("invalid binding " + key)
    if binding["mode"] != "hypothetical":
        raise ValueError("comparison accounting fixture requires hypothetical mode")
    for key in ("candidate_set_digest", "seedset_digest"):
        if not isinstance(manifest.get(key), str) or not HEX64.fullmatch(manifest[key]):
            raise ValueError("invalid " + key)
    seeds = manifest.get("required_seed_ids")
    if not isinstance(seeds, list) or not seeds or any(not _string(s) for s in seeds):
        raise ValueError("required_seed_ids must be nonempty strings")
    if len(seeds) != len(set(seeds)):
        raise ValueError("duplicate required_seed_ids")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidates must be nonempty")
    ids = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or any(
            not _string(candidate.get(k))
            for k in ("candidate_id", "origin", "policy_revision")
        ):
            raise ValueError("invalid candidate declaration")
        ids.append(candidate["candidate_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate candidate_id")
    if manifest.get("baseline_candidate_id") not in ids:
        raise ValueError("baseline_candidate_id is not declared")
    if not isinstance(metric_specs, list):
        raise ValueError("metric_specs must be a list")
    names = []
    for spec in metric_specs:
        if not isinstance(spec, Mapping) or any(
            not _string(spec.get(k)) for k in ("name", "unit", "capability_version")
        ):
            raise ValueError("invalid metric specification")
        if type(spec.get("required")) is not bool or type(spec.get("supported")) is not bool:
            raise ValueError("metric required/supported must be Boolean")
        if spec.get("kind") not in ("scalar", "completion_time"):
            raise ValueError("invalid metric kind")
        path = spec.get("value_path")
        if not isinstance(path, list) or not path or any(not _string(k) for k in path):
            raise ValueError("invalid metric value_path")
        if spec["kind"] == "completion_time" and path != ["completion_time_s"]:
            raise ValueError("completion_time requires canonical value_path")
        q = spec.get("quantile")
        if q is not None:
            if not isinstance(q, Mapping):
                raise ValueError("invalid quantile declaration")
            if "method" in q and not isinstance(q["method"], str):
                raise ValueError("invalid quantile method")
            probs = q.get("probabilities")
            if not isinstance(probs, list) or any(
                not _number(p) or not 0 <= p <= 1 for p in probs
            ):
                raise ValueError("invalid quantile probabilities")
            if "minimum_completed_samples" in q and not _integer(
                q["minimum_completed_samples"], positive=True
            ):
                raise ValueError("invalid quantile support")
        names.append(spec["name"])
    if len(names) != len(set(names)):
        raise ValueError("duplicate metric name")
    if rate_catalog is not None:
        if not _json_finite_tree(rate_catalog):
            raise ValueError("rate catalog must contain finite JSON values")
        if not isinstance(rate_catalog, Mapping) or not _string(rate_catalog.get("version")):
            raise ValueError("invalid rate catalog")
        if not isinstance(rate_catalog.get("components"), list):
            raise ValueError("invalid rate components")
        rate_ids = [r.get("component_id") if isinstance(r, Mapping) else None
                    for r in rate_catalog["components"]]
        if any(not _string(i) for i in rate_ids) or len(rate_ids) != len(set(rate_ids)):
            raise ValueError("invalid or duplicate rate component_id")
        conversions = rate_catalog.get("conversions", [])
        if not isinstance(conversions, list):
            raise ValueError("invalid conversions")
    return binding, sorted(candidates, key=lambda c: c["candidate_id"]), seeds


def _outcome_errors(outcome, binding):
    if not isinstance(outcome, Mapping):
        return ["outcome_missing"]
    errors = []
    if type(outcome.get("target_attained")) is not bool:
        errors.append("target_attained_invalid")
    if "completion_time_s" not in outcome:
        errors.append("completion_time_missing")
        time = None
    else:
        time = outcome["completion_time_s"]
    valid_time = time is not None and _number(time, nonnegative=True)
    if time is not None and not valid_time:
        errors.append("completion_time_invalid")
    if type(outcome.get("horizon_censored")) is not bool:
        errors.append("horizon_censored_invalid")
    if valid_time and outcome.get("horizon_censored") is True:
        errors.append("completed_time_censored")
    if valid_time and time > binding["horizon_s"]:
        errors.append("completion_after_horizon")
    if outcome.get("modeled_termination_reason") is not None and not _string(
        outcome.get("modeled_termination_reason")
    ):
        errors.append("modeled_termination_reason_invalid")
    metrics = outcome.get("metrics")
    if not isinstance(metrics, Mapping) or any(not _number(v) for v in metrics.values()):
        errors.append("metrics_invalid")
    resources = outcome.get("resource_components")
    if not isinstance(resources, list):
        errors.append("resource_components_invalid")
    else:
        seen = set()
        for item in resources:
            if not isinstance(item, Mapping) or not _string(item.get("component_id")):
                errors.append("resource_component_invalid")
                continue
            if item["component_id"] in seen:
                errors.append("resource_component_duplicate")
            seen.add(item["component_id"])
            if (not _number(item.get("quantity"), nonnegative=True)
                    or not _string(item.get("unit"))
                    or item.get("resource_version") != binding["resource_version"]):
                errors.append("resource_component_invalid")
    for key in ("distinct_requests_served", "distinct_requests_unmet"):
        if key in outcome and not _integer(outcome[key], nonnegative=True):
            errors.append(key + "_invalid")
    return sorted(set(errors))


def _type7(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return _finite(ordered[lo])
    weight = position - lo
    return _finite(ordered[lo] * (1 - weight) + ordered[hi] * weight)


def _metrics(specs, outcomes, required, complete):
    summaries = []
    blocking = []
    for spec in sorted(specs, key=lambda s: s["name"]):
        name = spec["name"]
        reasons = []
        values = []
        if not spec["supported"]:
            reasons.append("capability_unsupported")
        elif spec["capability_version"] != "accounting.fixture.v1":
            reasons.append("capability_version_unadopted")
        else:
            for outcome in outcomes:
                value = _path(outcome, spec["value_path"])
                if value is None and spec["kind"] == "completion_time":
                    continue
                if not _number(value, nonnegative=spec["kind"] == "completion_time"):
                    reasons.append("value_missing_or_invalid")
                    break
                values.append(value)
        if not complete:
            reasons.append("incomplete_calculation_cohort")
        if spec["kind"] == "completion_time" and len(values) != len(outcomes):
            reasons.append("full_cohort_completion_time_unavailable")
        value = None
        if not reasons and values:
            total = _safe_sum(values)
            value = _finite(total / len(values)) if total is not None else None
            if value is None:
                reasons.append("arithmetic_overflow")
        summary = {
            "name": name, "kind": spec["kind"], "unit": spec["unit"],
            "capability_version": spec["capability_version"],
            "required": spec["required"], "supported": spec["supported"],
            "population": "required_cohort", "count": len(values),
            "denominator": required, "value": value,
            "status": "available" if value is not None and not reasons else "unavailable",
            "reasons": sorted(set(reasons)), "quantiles": [],
        }
        q = spec.get("quantile")
        if q is not None:
            for p in sorted(q.get("probabilities", [])):
                qreasons = []
                qvalue = None
                method = q.get("method")
                minimum = q.get("minimum_completed_samples")
                if spec["kind"] != "completion_time":
                    qreasons.append("quantile_kind_unsupported")
                if not spec["supported"] or spec["capability_version"] != "accounting.fixture.v1":
                    qreasons.append("capability_unsupported")
                if method != "linear_type7":
                    qreasons.append("quantile_method_unadopted")
                if p != 0.5:
                    qreasons.append("quantile_probability_unadopted")
                if minimum is None:
                    qreasons.append("quantile_support_unadopted")
                elif len(values) < minimum:
                    qreasons.append("insufficient_completed_samples")
                if not values:
                    qreasons.append("no_completed_samples")
                if "value_missing_or_invalid" in reasons:
                    qreasons.append("value_missing_or_invalid")
                if not complete:
                    qreasons.append("incomplete_calculation_cohort")
                if not qreasons:
                    qvalue = _type7(values, p)
                    if qvalue is None:
                        qreasons.append("arithmetic_overflow")
                summary["quantiles"].append({
                    "probability": p, "method": method, "value": qvalue,
                    "unit": spec["unit"], "population": "conditional_on_completion",
                    "count": len(values), "denominator": len(outcomes),
                    "minimum_completed_samples": minimum,
                    "reasons": sorted(set(qreasons)),
                })
        if spec["required"] and summary["status"] != "available":
            blocking.append("required_metric_unavailable:" + name)
        summaries.append(summary)
    return summaries, blocking


def _unpriced_components(resources, reason):
    """Keep observed resource evidence when monetary rates are unavailable."""
    return [{
        "component_id": component["component_id"],
        "quantity": component["quantity"],
        "resource_unit": component["unit"],
        "resource_version": component["resource_version"],
        "amount": None, "currency": None, "rate": None, "conversion": None,
        "reasons": [reason],
    } for component in resources]


def _cost(outcomes, required, complete, binding, catalog):
    resources = []
    for outcome in outcomes:
        resources.extend(outcome["resource_components"])
    resources.sort(key=lambda r: (r["component_id"], r["unit"], r["quantity"]))
    result = {
        "status": "unavailable", "label": "estimated_not_actual",
        "covered_components": 0, "required_components": len(resources),
        "covered_calculations": len(outcomes), "required_calculations": required,
        "components": [], "known_subtotal": None, "total": None,
        "currency": None, "reasons": [],
    }
    reasons = result["reasons"]
    if not complete:
        reasons.append("incomplete_calculation_cohort")
    if catalog is None:
        reason = "rate_catalog_unavailable"
        reasons.append(reason)
        result["components"] = _unpriced_components(resources, reason)
        return result
    if catalog["version"] != binding["rate_version"]:
        reason = "rate_catalog_version_mismatch"
        reasons.append(reason)
        result["components"] = _unpriced_components(resources, reason)
        return result
    if not resources:
        reasons.append("no_declared_resource_components")
        return result
    as_of = _date(binding.get("as_of"))
    locality = binding.get("locality")
    rates = {r["component_id"]: r for r in catalog["components"]}
    conversions = catalog.get("conversions", [])
    amounts = []
    currencies = set()
    for component in resources:
        cid = component["component_id"]
        rate = rates.get(cid)
        item_reasons = []
        amount = None
        currency = None
        conversion = None
        if rate is None:
            item_reasons.append("rate_missing")
        else:
            for field in ("resource_unit", "currency", "source", "locality",
                          "calculation_revision"):
                if not _string(rate.get(field)):
                    item_reasons.append(field + "_missing")
            if not _number(rate.get("unit_rate"), nonnegative=True):
                item_reasons.append("unit_rate_invalid")
            assumptions = rate.get("assumption_ids")
            if (not isinstance(assumptions, list) or not assumptions
                    or any(not _string(a) for a in assumptions)):
                item_reasons.append("assumptions_missing")
            issued = _date(rate.get("issued_at"))
            start = _date(rate.get("valid_from"))
            end = _date(rate.get("valid_until"))
            if issued is None or start is None or end is None:
                item_reasons.append("rate_dates_missing_or_invalid")
            if as_of is None:
                item_reasons.append("as_of_missing_or_invalid")
            elif issued and start and end and not (issued <= as_of and start <= as_of <= end):
                item_reasons.append("rate_date_inapplicable")
            if not _string(locality):
                item_reasons.append("locality_missing")
            elif _string(rate.get("locality")) and rate["locality"] != locality:
                item_reasons.append("rate_locality_inapplicable")
            if rate.get("resource_unit") != component["unit"]:
                matches = [
                    c for c in conversions if isinstance(c, Mapping)
                    and c.get("from_unit") == component["unit"]
                    and c.get("to_unit") == rate.get("resource_unit")
                    and _number(c.get("factor"), positive=True)
                    and _string(c.get("source"))
                ]
                if len(matches) != 1:
                    item_reasons.append("conversion_missing_or_ambiguous")
                else:
                    conversion = dict(matches[0])
            if not item_reasons:
                factor = 1 if conversion is None else conversion["factor"]
                amount = _finite(component["quantity"] * factor)
                if amount is not None:
                    amount = _finite(amount * rate["unit_rate"])
                if amount is None:
                    item_reasons.append("arithmetic_overflow")
                else:
                    currency = rate["currency"]
                    amounts.append(amount)
                    currencies.add(currency)
                    result["covered_components"] += 1
        result["components"].append({
            "component_id": cid, "quantity": component["quantity"],
            "resource_unit": component["unit"], "resource_version": component["resource_version"],
            "amount": amount, "currency": currency,
            "rate": dict(rate) if rate is not None else None,
            "conversion": conversion, "reasons": sorted(set(item_reasons)),
        })
        reasons.extend(cid + ":" + reason for reason in item_reasons)
    if len(currencies) > 1:
        reasons.append("mixed_currencies")
    elif currencies:
        result["currency"] = next(iter(currencies))
        subtotal = _safe_sum(amounts)
        if subtotal is None:
            reasons.append("arithmetic_overflow")
        else:
            result["known_subtotal"] = subtotal
    if result["covered_components"] == len(resources) and complete and not reasons:
        result["status"] = "complete"
        result["total"] = result["known_subtotal"]
    elif result["covered_components"]:
        result["status"] = "partial"
    result["reasons"] = sorted(set(reasons))
    return result


def summarize_comparison(manifest, results, *, metric_specs, rate_catalog=None):
    """Summarize exact candidate/seed slots without ranking or mutating inputs.

    Malformed manifest/spec/catalog declarations raise ValueError. Malformed
    result records remain visible validation errors and poison their exact slot.
    Counted attempts require explicit evaluator-entry evidence.
    """
    binding, candidates, seeds = _validate_manifest(manifest, metric_specs, rate_catalog)
    if not isinstance(results, list):
        raise ValueError("results must be a list")
    declared = {c["candidate_id"]: c for c in candidates}
    seedset = set(seeds)
    slots = {(cid, seed): [] for cid in declared for seed in seeds}
    errors = []
    for record in results:
        if not isinstance(record, Mapping):
            errors.append("result_not_mapping")
            continue
        cid, seed = record.get("candidate_id"), record.get("seed_id")
        if not _string(cid) or not _string(seed) or cid not in declared or seed not in seedset:
            errors.append("foreign_result:" + str(cid) + ":" + str(seed))
            continue
        slots[(cid, seed)].append(record)
    output = []
    for candidate in candidates:
        cid = candidate["candidate_id"]
        counts = {status: 0 for status in STATUSES}
        counts.update(required=len(seeds), missing=0, attempted=0, attempted_unknown=0,
                      incomplete_total=0)
        outcomes = []
        modeled_reasons = Counter()
        attained = 0
        for seed in sorted(seeds):
            records = slots[(cid, seed)]
            if not records:
                counts["missing"] += 1
                counts["attempted_unknown"] += 1
                continue
            if len(records) > 1:
                counts["invalid"] += 1
                counts["attempted_unknown"] += 1
                errors.append("duplicate_result:" + cid + ":" + seed)
                continue
            record = records[0]
            attempted = record.get("attempted")
            if type(attempted) is bool:
                counts["attempted"] += int(attempted)
            else:
                counts["attempted_unknown"] += 1
                if attempted is not None:
                    errors.append("attempted_invalid:" + cid + ":" + seed)
            status = record.get("calculation_status")
            slot_errors = []
            if record.get("policy_revision") != candidate["policy_revision"]:
                slot_errors.append("policy_revision_mismatch")
            result_binding = record.get("binding")
            if not isinstance(result_binding, Mapping) or not _json_finite_tree(result_binding):
                slot_errors.append("binding_invalid")
            elif not _typed_equal(result_binding, binding):
                slot_errors.append("binding_mismatch")
            if status not in STATUSES:
                slot_errors.append("calculation_status_invalid")
            if status == "completed_valid":
                if attempted is not True:
                    slot_errors.append("completed_without_attempt_evidence")
                slot_errors.extend(_outcome_errors(record.get("outcome"), binding))
            if slot_errors:
                counts["invalid"] += 1
                errors.extend(reason + ":" + cid + ":" + seed for reason in sorted(set(slot_errors)))
                continue
            counts[status] += 1
            if status == "completed_valid":
                outcome = record["outcome"]
                outcomes.append(outcome)
                attained += int(outcome["target_attained"])
                reason = outcome.get("modeled_termination_reason")
                if reason:
                    modeled_reasons[reason] += 1
        counts["incomplete_total"] = counts["required"] - counts["completed_valid"]
        complete = counts["incomplete_total"] == 0
        strict_rate = _finite(attained / len(seeds)) if complete else None
        partial_rate = _finite(attained / len(outcomes)) if outcomes else None
        completion_times = [o["completion_time_s"] for o in outcomes
                            if o["completion_time_s"] is not None]
        completion = {
            "completed": len(completion_times),
            "noncompleted": len(outcomes) - len(completion_times),
            "horizon_censored": sum(o["horizon_censored"] for o in outcomes),
            "denominator": len(outcomes), "horizon_s": binding["horizon_s"],
        }
        metrics, metric_reasons = _metrics(metric_specs, outcomes, len(seeds), complete)
        cost = _cost(outcomes, len(seeds), complete, binding, rate_catalog)
        output.append({
            "candidate_id": cid, "origin": candidate["origin"],
            "policy_revision": candidate["policy_revision"], "counts": counts,
            "attainment": {
                "attained_count": attained, "unmet_count": len(outcomes) - attained,
                "attainment_denominator": len(outcomes),
                "conditional_attainment": strict_rate,
                "partial_diagnostic": {
                    "value": partial_rate, "denominator": len(outcomes),
                    "label": "observed_completed_valid_only",
                },
            },
            "modeled_termination_reasons": dict(sorted(modeled_reasons.items())),
            "completion": completion, "metrics": metrics, "estimated_cost": cost,
            "strict_reasons": sorted(set(
                ([] if complete else ["incomplete_calculation_cohort"]) + metric_reasons
            )),
        })
    strict_reasons = list(errors)
    for candidate in output:
        strict_reasons.extend(candidate["candidate_id"] + ":" + reason
                              for reason in candidate["strict_reasons"])
    strict_reasons = sorted(set(strict_reasons))
    cost_reasons = list(errors)
    currencies = {candidate["estimated_cost"]["currency"] for candidate in output
                  if candidate["estimated_cost"]["status"] == "complete"}
    if len(currencies) > 1:
        cost_reasons.append("cross_candidate_currency_mismatch")
    for candidate in output:
        if candidate["estimated_cost"]["status"] != "complete":
            cost_reasons.append(candidate["candidate_id"] + ":cost_incomplete")
    return {
        "schema_version": SCHEMA, "binding": dict(binding),
        "candidate_set_digest": manifest["candidate_set_digest"],
        "seedset_digest": manifest["seedset_digest"],
        "baseline_candidate_id": manifest["baseline_candidate_id"],
        "required_seed_ids": sorted(seeds), "candidates": output,
        "validation_errors": sorted(set(errors)),
        "strict_ranking_eligible": not strict_reasons,
        "strict_reasons": strict_reasons,
        "cost_comparison_eligible": not cost_reasons,
        "cost_reasons": sorted(set(cost_reasons)),
    }
