"""Authored, unexecuted fixture checks for pure comparison accounting."""

import copy
import json
import math
import unittest

from services.planner.comparison_summary import SCHEMA, summarize_comparison


def fixture(seeds=("s1", "s2", "s3")):
    binding = {
        "run_id": "toy-run", "generation": 0, "mode": "hypothetical",
        "place_id": "toy-place", "scenario_digest": "scenario-toy",
        "starting_state_digest": "start-toy", "sampling_version": "sample-toy",
        "model_version": "model-toy", "objective_version": "objective-toy",
        "resource_version": "resource-toy", "graph_version": "graph-toy",
        "horizon_version": "horizon-toy", "rate_version": "rates-toy",
        "horizon_s": 30, "as_of": "2026-10-10", "locality": "toy-locality",
    }
    manifest = {
        "schema_version": SCHEMA, "binding": binding,
        "candidates": [
            {"candidate_id": "B", "origin": "baseline", "policy_revision": "b1"},
            {"candidate_id": "C", "origin": "candidate", "policy_revision": "c1"},
        ],
        "baseline_candidate_id": "B", "required_seed_ids": list(seeds),
        "candidate_set_digest": "a" * 64, "seedset_digest": "b" * 64,
    }
    results = []
    for cid, revision in (("B", "b1"), ("C", "c1")):
        for index, seed in enumerate(seeds):
            attained = index < 2
            results.append({
                "candidate_id": cid, "seed_id": seed,
                "policy_revision": revision, "binding": copy.deepcopy(binding),
                "calculation_status": "completed_valid", "attempted": True,
                "outcome": {
                    "target_attained": attained,
                    "completion_time_s": 10 * (index + 1) if attained else None,
                    "horizon_censored": False,
                    "modeled_termination_reason": None if attained else "UNMET_UNDER_MODEL",
                    "metrics": {"safe_arrivals": 1 if attained else 0},
                    "resource_components": [],
                },
            })
    specs = [{
        "name": "safe_arrivals", "unit": "people", "required": True,
        "supported": True, "capability_version": "accounting.fixture.v1",
        "value_path": ["metrics", "safe_arrivals"], "kind": "scalar",
    }]
    return manifest, results, specs


def candidate(summary, cid="C"):
    return next(row for row in summary["candidates"] if row["candidate_id"] == cid)


def vehicle(quantity=2, unit="vehicle_hour"):
    return {
        "component_id": "vehicle", "quantity": quantity,
        "unit": unit, "resource_version": "resource-toy",
    }


def rate_catalog(rate=10):
    return {
        "version": "rates-toy",
        "components": [{
            "component_id": "vehicle", "resource_unit": "vehicle_hour",
            "unit_rate": rate, "currency": "USD", "source": "toy-authored-fixture",
            "issued_at": "2026-10-01", "valid_from": "2026-10-01",
            "valid_until": "2026-10-31", "locality": "toy-locality",
            "assumption_ids": ["toy-rate-only"], "calculation_revision": "calc-toy",
        }],
    }


class ComparisonAccountingVectors(unittest.TestCase):
    def test_v01_valid_unfavorable(self):
        manifest, results, specs = fixture()
        summary = summarize_comparison(manifest, results, metric_specs=specs)
        row = candidate(summary)
        self.assertEqual((row["counts"]["required"], row["counts"]["attempted"],
                          row["counts"]["completed_valid"], row["counts"]["incomplete_total"]),
                         (3, 3, 3, 0))
        self.assertEqual((row["attainment"]["attained_count"], row["attainment"]["unmet_count"]),
                         (2, 1))
        self.assertEqual(row["attainment"]["conditional_attainment"], 2 / 3)
        self.assertTrue(summary["strict_ranking_eligible"])

    def test_v02_crash_is_not_modeled_unmet(self):
        manifest, results, specs = fixture()
        results[-1]["calculation_status"] = "crashed"
        results[-1].pop("outcome")
        row = candidate(summarize_comparison(manifest, results, metric_specs=specs))
        self.assertEqual(row["counts"]["crashed"], 1)
        self.assertEqual(row["counts"]["completed_valid"], 2)
        self.assertEqual(row["attainment"]["attainment_denominator"], 2)
        self.assertEqual(row["attainment"]["unmet_count"], 0)
        self.assertIsNone(row["attainment"]["conditional_attainment"])

    def test_v03_blocked_route_is_valid_miss(self):
        manifest, results, specs = fixture()
        results[-1]["outcome"]["modeled_termination_reason"] = "UNREACHABLE_UNDER_MODEL"
        summary = summarize_comparison(manifest, results, metric_specs=specs)
        row = candidate(summary)
        self.assertEqual(row["counts"]["completed_valid"], 3)
        self.assertEqual(row["attainment"]["unmet_count"], 1)
        self.assertEqual(row["modeled_termination_reasons"], {"UNREACHABLE_UNDER_MODEL": 1})
        self.assertTrue(summary["strict_ranking_eligible"])

    def test_v04_empty_and_invalid_seedset(self):
        manifest, _, specs = fixture()
        summary = summarize_comparison(manifest, [], metric_specs=specs)
        for row in summary["candidates"]:
            self.assertEqual(row["counts"]["missing"], 3)
            self.assertEqual(row["counts"]["attempted_unknown"], 3)
            self.assertIsNone(row["attainment"]["conditional_attainment"])
        self.assertFalse(summary["strict_ranking_eligible"])
        manifest["required_seed_ids"] = []
        with self.assertRaises(ValueError):
            summarize_comparison(manifest, [], metric_specs=specs)

    def test_v05_foreign_seed_does_not_fill_missing_slot(self):
        manifest, results, specs = fixture()
        results[-1]["seed_id"] = "s4"
        summary = summarize_comparison(manifest, results, metric_specs=specs)
        self.assertEqual(candidate(summary)["counts"]["missing"], 1)
        self.assertTrue(any("foreign_result" in e for e in summary["validation_errors"]))
        self.assertFalse(summary["strict_ranking_eligible"])

    def test_v06_distinct_incomplete_statuses_and_attempts(self):
        for status in ("invalid", "unsupported", "canceled", "deadline_exceeded"):
            with self.subTest(status=status):
                manifest, results, specs = fixture()
                results[-1]["calculation_status"] = status
                results[-1]["attempted"] = status != "canceled"
                results[-1].pop("outcome")
                row = candidate(summarize_comparison(manifest, results, metric_specs=specs))
                self.assertEqual(row["counts"][status], 1)
                self.assertEqual(row["counts"]["attempted"], 2 if status == "canceled" else 3)
                self.assertEqual(row["counts"]["incomplete_total"], 1)
                self.assertEqual(row["attainment"]["unmet_count"], 0)

    def test_v07_duplicate_and_stale_binding(self):
        manifest, results, specs = fixture()
        results.append(copy.deepcopy(results[-1]))
        summary = summarize_comparison(manifest, results, metric_specs=specs)
        self.assertEqual(candidate(summary)["counts"]["invalid"], 1)
        self.assertEqual(candidate(summary)["counts"]["attempted_unknown"], 1)
        self.assertTrue(any("duplicate_result" in e for e in summary["validation_errors"]))
        manifest, results, specs = fixture()
        results[-1]["binding"]["starting_state_digest"] = "other"
        summary = summarize_comparison(manifest, results, metric_specs=specs)
        self.assertEqual(candidate(summary)["counts"]["invalid"], 1)
        self.assertTrue(any("binding_mismatch" in e for e in summary["validation_errors"]))

    def test_v08_nonfinite_and_negative_data(self):
        for mutation in (
            lambda row: row["outcome"].update(completion_time_s=math.nan),
            lambda row: row["outcome"]["metrics"].update(safe_arrivals=math.inf),
            lambda row: row["outcome"]["resource_components"].append(vehicle(-1)),
            lambda row: row["outcome"]["resource_components"].append(vehicle(math.inf)),
            lambda row: row["outcome"]["metrics"].update(safe_arrivals=True),
        ):
            with self.subTest(mutation=repr(mutation)):
                manifest, results, specs = fixture()
                mutation(results[-1])
                summary = summarize_comparison(manifest, results, metric_specs=specs)
                self.assertEqual(candidate(summary)["counts"]["invalid"], 1)
                self.assertFalse(summary["strict_ranking_eligible"])
                json.dumps(summary, allow_nan=False)
        manifest, results, specs = fixture(("s1",))
        with self.assertRaises(ValueError):
            summarize_comparison(manifest, results, metric_specs=specs,
                                 rate_catalog=rate_catalog(math.nan))
        manifest["binding"]["horizon_s"] = True
        with self.assertRaises(ValueError):
            summarize_comparison(manifest, results, metric_specs=specs)

    def test_v09_conditional_type7_and_censoring(self):
        manifest, results, specs = fixture()
        specs.append({
            "name": "completion", "unit": "s", "required": False,
            "supported": True, "capability_version": "accounting.fixture.v1",
            "value_path": ["completion_time_s"], "kind": "completion_time",
            "quantile": {"method": "linear_type7", "probabilities": [0.5, 0.95],
                         "minimum_completed_samples": 2},
        })
        row = candidate(summarize_comparison(manifest, results, metric_specs=specs))
        self.assertEqual((row["completion"]["completed"], row["completion"]["noncompleted"],
                          row["completion"]["horizon_censored"]), (2, 1, 0))
        completion_metric = next(m for m in row["metrics"] if m["name"] == "completion")
        self.assertIsNone(completion_metric["value"])
        self.assertEqual(completion_metric["quantiles"][0]["value"], 15)
        self.assertEqual(completion_metric["quantiles"][0]["count"], 2)
        self.assertEqual(completion_metric["quantiles"][0]["denominator"], 3)
        self.assertIsNone(completion_metric["quantiles"][1]["value"])
        self.assertIn("quantile_probability_unadopted",
                      completion_metric["quantiles"][1]["reasons"])
        results[-1]["outcome"]["horizon_censored"] = True
        row = candidate(summarize_comparison(manifest, results, metric_specs=specs))
        self.assertEqual(row["completion"]["horizon_censored"], 1)
        self.assertEqual(row["attainment"]["attainment_denominator"], 3)

    def test_v10_documented_toy_cost(self):
        manifest, results, specs = fixture(("s1",))
        results[0]["outcome"]["resource_components"] = [vehicle()]
        results[1]["outcome"]["resource_components"] = [vehicle()]
        summary = summarize_comparison(manifest, results, metric_specs=specs,
                                       rate_catalog=rate_catalog())
        cost = candidate(summary)["estimated_cost"]
        self.assertEqual(cost["status"], "complete")
        self.assertEqual(cost["total"], 20)
        self.assertEqual(cost["currency"], "USD")
        self.assertEqual(cost["label"], "estimated_not_actual")
        self.assertTrue(summary["cost_comparison_eligible"])

    def test_v11_missing_rate_preserves_partial_subtotal(self):
        manifest, results, specs = fixture(("s1",))
        responder = {"component_id": "responder", "quantity": 3,
                     "unit": "responder_hour", "resource_version": "resource-toy"}
        for row in results:
            row["outcome"]["resource_components"] = [vehicle(), responder]
        summary = summarize_comparison(manifest, results, metric_specs=specs,
                                       rate_catalog=rate_catalog())
        cost = candidate(summary)["estimated_cost"]
        self.assertEqual((cost["covered_components"], cost["required_components"]), (1, 2))
        self.assertEqual(cost["status"], "partial")
        self.assertEqual(cost["known_subtotal"], 20)
        self.assertIsNone(cost["total"])
        self.assertTrue(summary["strict_ranking_eligible"])
        self.assertFalse(summary["cost_comparison_eligible"])

    def test_v12_currency_and_conversion_require_compatibility(self):
        manifest, results, specs = fixture(("s1",))
        responder = {"component_id": "responder", "quantity": 3,
                     "unit": "responder_hour", "resource_version": "resource-toy"}
        for row in results:
            row["outcome"]["resource_components"] = [vehicle(), responder]
        catalog = rate_catalog()
        other = copy.deepcopy(catalog["components"][0])
        other.update(component_id="responder", resource_unit="responder_hour", currency="EUR")
        catalog["components"].append(other)
        cost = candidate(summarize_comparison(manifest, results, metric_specs=specs,
                                              rate_catalog=catalog))["estimated_cost"]
        self.assertIsNone(cost["total"])
        self.assertIn("mixed_currencies", cost["reasons"])
        for row in results:
            row["outcome"]["resource_components"] = [vehicle(unit="vehicle_day")]
        cost = candidate(summarize_comparison(manifest, results, metric_specs=specs,
                                              rate_catalog=catalog))["estimated_cost"]
        self.assertIn("vehicle:conversion_missing_or_ambiguous", cost["reasons"])
        catalog["conversions"] = [{
            "from_unit": "vehicle_day", "to_unit": "vehicle_hour",
            "factor": 24, "source": "toy-authored-conversion",
        }]
        cost = candidate(summarize_comparison(manifest, results, metric_specs=specs,
                                              rate_catalog=catalog))["estimated_cost"]
        self.assertEqual(cost["total"], 480)

    def test_v13_rate_applicability_and_provenance(self):
        for change, reason in (
            ({"valid_until": "2026-10-09"}, "rate_date_inapplicable"),
            ({"valid_from": "2026-10-11"}, "rate_date_inapplicable"),
            ({"locality": "other"}, "rate_locality_inapplicable"),
            ({"source": ""}, "source_missing"),
            ({"issued_at": None}, "rate_dates_missing_or_invalid"),
            ({"assumption_ids": []}, "assumptions_missing"),
        ):
            with self.subTest(change=change):
                manifest, results, specs = fixture(("s1",))
                for row in results:
                    row["outcome"]["resource_components"] = [vehicle()]
                catalog = rate_catalog()
                catalog["components"][0].update(change)
                cost = candidate(summarize_comparison(manifest, results, metric_specs=specs,
                                                      rate_catalog=catalog))["estimated_cost"]
                self.assertIn("vehicle:" + reason, cost["reasons"])
                self.assertIsNone(cost["total"])

    def test_v14_zero_purity_and_deterministic_order(self):
        manifest, results, specs = fixture(("s1",))
        for row in results:
            row["outcome"]["resource_components"] = [vehicle()]
        catalog = rate_catalog(0)
        before = copy.deepcopy((manifest, results, specs, catalog))
        first = summarize_comparison(manifest, results, metric_specs=specs,
                                     rate_catalog=catalog)
        second = summarize_comparison(manifest, list(reversed(results)), metric_specs=specs,
                                      rate_catalog=catalog)
        self.assertEqual(first, second)
        self.assertEqual((manifest, results, specs, catalog), before)
        self.assertEqual(candidate(first)["estimated_cost"]["total"], 0)
        json.dumps(first, allow_nan=False)

    def test_f1_completion_time_malformed_or_missing_is_invalid(self):
        for value, reason in (
            ("missing", "completion_time_missing"),
            ("bad", "completion_time_invalid"),
            ([], "completion_time_invalid"),
            ({}, "completion_time_invalid"),
        ):
            with self.subTest(value=value):
                manifest, results, specs = fixture(("s1",))
                outcome = results[-1]["outcome"]
                if value == "missing":
                    outcome.pop("completion_time_s")
                else:
                    outcome["completion_time_s"] = value
                summary = summarize_comparison(manifest, results, metric_specs=specs)
                self.assertEqual(candidate(summary)["counts"]["invalid"], 1)
                self.assertTrue(any(reason in item for item in summary["validation_errors"]))
                self.assertFalse(summary["strict_ranking_eligible"])
                json.dumps(summary, allow_nan=False)
        manifest, results, specs = fixture(("s1",))
        results[-1]["outcome"]["target_attained"] = False
        results[-1]["outcome"]["completion_time_s"] = None
        row = candidate(summarize_comparison(manifest, results, metric_specs=specs))
        self.assertEqual(row["counts"]["completed_valid"], 1)
        self.assertEqual(row["completion"]["noncompleted"], 1)

    def test_f2_result_binding_requires_typed_recursive_identity(self):
        for generation in (False, 0.0):
            with self.subTest(generation=generation):
                manifest, results, specs = fixture(("s1",))
                results[-1]["binding"]["generation"] = generation
                summary = summarize_comparison(manifest, results, metric_specs=specs)
                self.assertEqual(candidate(summary)["counts"]["invalid"], 1)
                self.assertTrue(any("binding_mismatch" in e for e in summary["validation_errors"]))
        manifest, results, specs = fixture(("s1",))
        manifest["binding"]["accepted_parent"] = {"offset": 0, "enabled": False}
        for result in results:
            result["binding"]["accepted_parent"] = {"offset": 0, "enabled": False}
        self.assertTrue(summarize_comparison(manifest, results,
                                             metric_specs=specs)["strict_ranking_eligible"])
        results[-1]["binding"]["accepted_parent"]["offset"] = False
        summary = summarize_comparison(manifest, results, metric_specs=specs)
        self.assertEqual(candidate(summary)["counts"]["invalid"], 1)
        self.assertTrue(any("binding_mismatch" in e for e in summary["validation_errors"]))

    def test_f3_cross_candidate_cost_currency_must_match(self):
        manifest, results, specs = fixture(("s1",))
        results[0]["outcome"]["resource_components"] = [vehicle()]
        results[1]["outcome"]["resource_components"] = [{
            "component_id": "responder", "quantity": 3,
            "unit": "responder_hour", "resource_version": "resource-toy",
        }]
        catalog = rate_catalog()
        euro = copy.deepcopy(catalog["components"][0])
        euro.update(component_id="responder", resource_unit="responder_hour", currency="EUR")
        catalog["components"].append(euro)
        summary = summarize_comparison(manifest, results, metric_specs=specs,
                                       rate_catalog=catalog)
        self.assertEqual(candidate(summary, "B")["estimated_cost"]["total"], 20)
        self.assertEqual(candidate(summary, "C")["estimated_cost"]["total"], 30)
        self.assertEqual(candidate(summary, "B")["estimated_cost"]["currency"], "USD")
        self.assertEqual(candidate(summary, "C")["estimated_cost"]["currency"], "EUR")
        self.assertTrue(summary["strict_ranking_eligible"])
        self.assertFalse(summary["cost_comparison_eligible"])
        self.assertIn("cross_candidate_currency_mismatch", summary["cost_reasons"])
        catalog["components"][1]["currency"] = "USD"
        summary = summarize_comparison(manifest, results, metric_specs=specs,
                                       rate_catalog=catalog)
        self.assertTrue(summary["cost_comparison_eligible"])

    def test_f4_quantile_method_metadata_is_safe(self):
        def completion_spec():
            return {
                "name": "completion", "unit": "s", "required": False,
                "supported": True, "capability_version": "accounting.fixture.v1",
                "value_path": ["completion_time_s"], "kind": "completion_time",
                "quantile": {"probabilities": [0.5], "minimum_completed_samples": 2},
            }

        for bad in (math.nan, math.inf, True, [], {}, lambda: None):
            with self.subTest(type=type(bad).__name__):
                manifest, results, specs = fixture(("s1",))
                spec = completion_spec()
                spec["quantile"]["method"] = bad
                with self.assertRaises(ValueError):
                    summarize_comparison(manifest, results,
                                         metric_specs=specs + [spec])
        for method in (None, "unsupported-v9"):
            manifest, results, specs = fixture(("s1",))
            spec = completion_spec()
            if method is not None:
                spec["quantile"]["method"] = method
            summary = summarize_comparison(manifest, results, metric_specs=specs + [spec])
            metric = next(m for m in candidate(summary)["metrics"]
                          if m["name"] == "completion")
            self.assertIsNone(metric["quantiles"][0]["value"])
            self.assertIn("quantile_method_unadopted", metric["quantiles"][0]["reasons"])
            json.dumps(summary, allow_nan=False)

    def test_f5_incomplete_computations_suppress_strict_quantile(self):
        def specs_with_completion(base):
            return base + [{
                "name": "completion", "unit": "s", "required": False,
                "supported": True, "capability_version": "accounting.fixture.v1",
                "value_path": ["completion_time_s"], "kind": "completion_time",
                "quantile": {"method": "linear_type7",
                             "probabilities": [0.5, 0.95],
                             "minimum_completed_samples": 2},
            }]

        manifest, results, specs = fixture()
        full = summarize_comparison(manifest, results,
                                    metric_specs=specs_with_completion(specs))
        full_metric = next(m for m in candidate(full)["metrics"] if m["name"] == "completion")
        self.assertEqual(full_metric["quantiles"][0]["value"], 15)
        self.assertEqual(full_metric["quantiles"][0]["denominator"], 3)
        self.assertIsNone(full_metric["quantiles"][1]["value"])
        for missing in (False, True):
            with self.subTest(missing=missing):
                manifest, results, specs = fixture()
                if missing:
                    results.pop()
                else:
                    results[-1]["calculation_status"] = "crashed"
                    results[-1].pop("outcome")
                summary = summarize_comparison(manifest, results,
                                               metric_specs=specs_with_completion(specs))
                row = candidate(summary)
                self.assertEqual(row["counts"]["completed_valid"], 2)
                self.assertEqual(row["counts"]["missing" if missing else "crashed"], 1)
                metric = next(m for m in row["metrics"] if m["name"] == "completion")
                self.assertIsNone(metric["quantiles"][0]["value"])
                self.assertIn("incomplete_calculation_cohort",
                              metric["quantiles"][0]["reasons"])
                self.assertIsNone(metric["quantiles"][1]["value"])

    def test_f6_unknown_attempt_capability_and_empty_completion(self):
        manifest, results, specs = fixture(("s1",))
        results[-1]["attempted"] = None
        summary = summarize_comparison(manifest, results, metric_specs=specs)
        row = candidate(summary)
        self.assertEqual(row["counts"]["attempted_unknown"], 1)
        self.assertEqual(row["counts"]["invalid"], 1)
        self.assertTrue(any("completed_without_attempt_evidence" in e
                            for e in summary["validation_errors"]))
        unsupported = {
            "name": "toy_gap", "unit": "count", "required": True,
            "supported": False, "capability_version": "accounting.fixture.v1",
            "value_path": ["metrics", "toy_gap"], "kind": "scalar",
        }
        manifest, results, specs = fixture(("s1",))
        summary = summarize_comparison(manifest, results,
                                       metric_specs=specs + [unsupported])
        self.assertFalse(summary["strict_ranking_eligible"])
        metric = next(m for m in candidate(summary)["metrics"] if m["name"] == "toy_gap")
        self.assertIn("capability_unsupported", metric["reasons"])
        unsupported["required"] = False
        summary = summarize_comparison(manifest, results,
                                       metric_specs=specs + [unsupported])
        self.assertTrue(summary["strict_ranking_eligible"])
        supported = next(m for m in candidate(summary)["metrics"]
                         if m["name"] == "safe_arrivals")
        self.assertEqual(supported["status"], "available")
        manifest, results, specs = fixture()
        for result in results:
            result["outcome"]["target_attained"] = False
            result["outcome"]["completion_time_s"] = None
            result["outcome"]["metrics"]["safe_arrivals"] = 0
        completion = {
            "name": "completion", "unit": "s", "required": False,
            "supported": True, "capability_version": "accounting.fixture.v1",
            "value_path": ["completion_time_s"], "kind": "completion_time",
            "quantile": {"method": "linear_type7", "probabilities": [0.5],
                         "minimum_completed_samples": 2},
        }
        summary = summarize_comparison(manifest, results,
                                       metric_specs=specs + [completion])
        row = candidate(summary)
        self.assertEqual(row["counts"]["completed_valid"], 3)
        self.assertEqual(row["completion"]["completed"], 0)
        self.assertEqual(row["attainment"]["attainment_denominator"], 3)
        self.assertEqual(row["attainment"]["unmet_count"], 3)
        metric = next(m for m in row["metrics"] if m["name"] == "completion")
        self.assertIsNone(metric["quantiles"][0]["value"])
        self.assertIn("no_completed_samples", metric["quantiles"][0]["reasons"])
        self.assertTrue(summary["strict_ranking_eligible"])

    def test_f7_resources_survive_absent_or_mismatched_rates(self):
        responder = {
            "component_id": "responder", "quantity": 3,
            "unit": "responder_hour", "resource_version": "resource-toy",
        }
        manifest, results, specs = fixture(("s1",))
        for result in results:
            result["outcome"]["resource_components"] = [vehicle(2), responder]
        for catalog, reason in (
            (None, "rate_catalog_unavailable"),
            ({**rate_catalog(), "version": "wrong-rates"}, "rate_catalog_version_mismatch"),
        ):
            with self.subTest(reason=reason):
                summary = summarize_comparison(manifest, results, metric_specs=specs,
                                               rate_catalog=catalog)
                row = candidate(summary)
                cost = row["estimated_cost"]
                self.assertEqual(cost["status"], "unavailable")
                self.assertIsNone(cost["total"])
                self.assertEqual((cost["covered_calculations"],
                                  cost["required_calculations"]), (1, 1))
                self.assertEqual(cost["required_components"], 2)
                components = {item["component_id"]: item for item in cost["components"]}
                self.assertEqual(set(components), {"vehicle", "responder"})
                self.assertEqual((components["vehicle"]["quantity"],
                                  components["vehicle"]["resource_unit"],
                                  components["vehicle"]["resource_version"]),
                                 (2, "vehicle_hour", "resource-toy"))
                self.assertEqual((components["responder"]["quantity"],
                                  components["responder"]["resource_unit"],
                                  components["responder"]["resource_version"]),
                                 (3, "responder_hour", "resource-toy"))
                for item in components.values():
                    self.assertIsNone(item["amount"])
                    self.assertIn(reason, item["reasons"])
                self.assertTrue(summary["strict_ranking_eligible"])
                self.assertFalse(summary["cost_comparison_eligible"])
                json.dumps(summary, allow_nan=False)
        manifest, results, specs = fixture(("s1", "s2"))
        for result in results:
            result["outcome"]["resource_components"] = [vehicle(2), responder]
        results[-1]["calculation_status"] = "crashed"
        results[-1].pop("outcome")
        row = candidate(summarize_comparison(manifest, results,
                                             metric_specs=specs))
        cost = row["estimated_cost"]
        self.assertEqual((cost["covered_calculations"],
                          cost["required_calculations"]), (1, 2))
        self.assertEqual(cost["required_components"], 2)
        self.assertEqual({item["component_id"]: item["quantity"]
                          for item in cost["components"]},
                         {"vehicle": 2, "responder": 3})
        self.assertIn("incomplete_calculation_cohort", cost["reasons"])

    def test_f8_completion_metric_uses_canonical_path_only(self):
        manifest, results, specs = fixture()
        for index, result in enumerate(results):
            result["outcome"]["metrics"]["alternate_s"] = (10, 20, 30)[index % 3]
        completion = {
            "name": "completion", "unit": "s", "required": False,
            "supported": True, "capability_version": "accounting.fixture.v1",
            "value_path": ["completion_time_s"], "kind": "completion_time",
            "quantile": {"method": "linear_type7", "probabilities": [0.5, 0.95],
                         "minimum_completed_samples": 2},
        }
        for path in (["metrics", "safe_arrivals"],
                     ["metrics", "alternate_s"], ["unrelated_missing"]):
            with self.subTest(path=path):
                alternate = copy.deepcopy(completion)
                alternate["value_path"] = path
                with self.assertRaises(ValueError):
                    summarize_comparison(manifest, results,
                                         metric_specs=specs + [alternate])
        summary = summarize_comparison(manifest, results,
                                       metric_specs=specs + [completion])
        row = candidate(summary)
        metric = next(item for item in row["metrics"] if item["name"] == "completion")
        self.assertEqual((row["completion"]["completed"],
                          row["completion"]["noncompleted"]), (2, 1))
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["quantiles"][0]["value"], 15)
        self.assertEqual((metric["quantiles"][0]["count"],
                          metric["quantiles"][0]["denominator"]), (2, 3))
        self.assertIsNone(metric["quantiles"][1]["value"])
        self.assertIn("quantile_probability_unadopted",
                      metric["quantiles"][1]["reasons"])
        results[-1]["outcome"]["horizon_censored"] = True
        row = candidate(summarize_comparison(manifest, results,
                                             metric_specs=specs + [completion]))
        self.assertEqual(row["completion"]["horizon_censored"], 1)
        metric = next(item for item in row["metrics"] if item["name"] == "completion")
        self.assertEqual(metric["quantiles"][0]["value"], 15)
        for result in results:
            result["outcome"]["target_attained"] = False
            result["outcome"]["completion_time_s"] = None
            result["outcome"]["horizon_censored"] = False
        row = candidate(summarize_comparison(manifest, results,
                                             metric_specs=specs + [completion]))
        self.assertEqual(row["completion"]["completed"], 0)
        metric = next(item for item in row["metrics"] if item["name"] == "completion")
        self.assertIsNone(metric["quantiles"][0]["value"])
        self.assertIn("no_completed_samples", metric["quantiles"][0]["reasons"])




if __name__ == "__main__":
    unittest.main()
