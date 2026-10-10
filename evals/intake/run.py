"""Score strict intake proposals on frozen fictional reports.

The mocked fixture control measures harness coverage, not model accuracy.
External model outputs can be scored with --predictions; no inference occurs here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from services.intake.schema import Report, parse_proposal

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "reports" / "intake_cases.json"
SLOTS = ("quantity", "unit", "urgency", "location")


def load_cases(path: Path = FIXTURES) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    ids = [case["report_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate fixture report_id")
    return cases


def slot_value(claim: dict[str, Any] | None, slot: str) -> Any:
    if claim is None:
        return None
    value = claim.get(slot)
    return None if value is None else value.get("value")


def signature(claim: dict[str, Any]) -> tuple[Any, ...]:
    return (
        claim.get("kind"), claim.get("label"),
        *(slot_value(claim, slot) for slot in SLOTS),
        tuple(sorted(claim.get("flags", []))),
    )


def _pair_score(gold: dict[str, Any], predicted: dict[str, Any]) -> int:
    return sum(slot_value(gold, slot) == slot_value(predicted, slot) for slot in SLOTS)


def align_claims(gold: list[dict[str, Any]], predicted: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Match equal kind/label claims, maximizing agreement on slot values."""
    candidates = [
        (i, j, _pair_score(g, p))
        for i, g in enumerate(gold)
        for j, p in enumerate(predicted)
        if g.get("kind") == p.get("kind") and g.get("label") == p.get("label")
    ]
    # Tiny report-level claim sets; an exact search avoids order-sensitive pairing.
    best: tuple[int, int, list[tuple[int, int]]] = (-1, -1, [])
    def search(remaining: list[tuple[int, int, int]], used_g: set[int], used_p: set[int],
               pairs: list[tuple[int, int]], score: int) -> None:
        nonlocal best
        rank = (len(pairs), score)
        if rank > best[:2]:
            best = (rank[0], rank[1], pairs.copy())
        for index, (i, j, value) in enumerate(remaining):
            if i not in used_g and j not in used_p:
                search(remaining[index + 1:], used_g | {i}, used_p | {j},
                       pairs + [(i, j)], score + value)
    search(candidates, set(), set(), [], 0)
    return best[2]


def _supported(text: str, evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    start, end, quote = evidence.get("start"), evidence.get("end"), evidence.get("quote")
    return (isinstance(start, int) and not isinstance(start, bool)
            and isinstance(end, int) and not isinstance(end, bool)
            and isinstance(quote, str) and 0 <= start < end <= len(text)
            and text[start:end] == quote)


def _evidence_counts(text: str, claims: list[dict[str, Any]]) -> tuple[int, int]:
    correct = total = 0
    for claim in claims:
        items = [claim.get("evidence")]
        items += [claim[slot].get("evidence") for slot in SLOTS if isinstance(claim.get(slot), dict)]
        for evidence in items:
            total += 1
            correct += int(_supported(text, evidence))
    return correct, total


def _blank_metrics() -> dict[str, dict[str, int]]:
    return defaultdict(lambda: {"numerator": 0, "denominator": 0})


def _add(metrics: dict[str, dict[str, int]], name: str, numerator: int, denominator: int = 1) -> None:
    metrics[name]["numerator"] += numerator
    metrics[name]["denominator"] += denominator


def _raw_diagnostics(gold_claims: list[dict[str, Any]], payload: Any, valid: bool) -> dict[str, dict[str, int]]:
    """Count unsupported raw fields without granting validity or evidence credit.

    Only the first 20 JSON claim items are inspected. Malformed items are counted
    as extras but are never fed into matching or signature construction.
    """
    metrics = _blank_metrics()
    raw = payload.get("claims") if isinstance(payload, dict) else None
    raw_claims = raw if isinstance(raw, list) else []
    inspected = raw_claims[:20]
    candidates = [(j, claim) for j, claim in enumerate(inspected)
                  if isinstance(claim, dict)
                  and isinstance(claim.get("kind"), str)
                  and isinstance(claim.get("label"), str)]
    used: set[int] = set()
    matched: dict[int, dict[str, Any]] = {}
    for i, gold in enumerate(gold_claims):
        choices = [(j, claim) for j, claim in candidates
                   if j not in used and claim["kind"] == gold["kind"]
                   and claim["label"] == gold["label"]]
        if not choices:
            continue
        def agreement(item: tuple[int, dict[str, Any]]) -> int:
            claim = item[1]
            score = 0
            for slot in SLOTS:
                raw_slot = claim.get(slot)
                if isinstance(raw_slot, dict):
                    score += int(raw_slot.get("value") == slot_value(gold, slot))
            return score
        j, claim = max(choices, key=agreement)
        used.add(j)
        matched[i] = claim
    _add(metrics, "raw_extra_claims", len(raw_claims) - len(matched), len(raw_claims))
    _add(metrics, "raw_invalid_claim_items",
         sum(not isinstance(item, dict) for item in inspected), len(raw_claims))
    _add(metrics, "raw_over_limit_claims", max(0, len(raw_claims) - 20), len(raw_claims))
    for i, gold in enumerate(gold_claims):
        claim = matched.get(i)
        for slot in ("quantity", "location"):
            if gold["kind"] == "access" and slot == "quantity":
                continue
            if slot_value(gold, slot) is not None:
                continue
            populated = claim is not None and claim.get(slot) is not None
            _add(metrics, f"raw_{slot}_false_fill", int(populated))
            if not valid:
                _add(metrics, f"rejected_{slot}_false_fill", int(populated))
    return dict(metrics)


def score_case(case: dict[str, Any], payload: dict[str, Any] | None, provider: str) -> dict[str, Any]:
    gold = case["gold"]
    raw_payload = payload
    report = Report(case["report_id"], "fictional_eval", 0.0, case["text"])
    error = None
    valid = False
    if not isinstance(payload, dict):
        error = "missing or non-object payload"
        payload = {}
    else:
        try:
            parse_proposal(report, payload, provider)
            valid = True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    # Invalid outputs remain in denominators. Their raw content is retained in failures.
    predicted = payload.get("claims", []) if valid else []
    flags = payload.get("flags", []) if valid else []
    metrics = _blank_metrics()
    raw_diagnostics = _raw_diagnostics(gold["claims"], raw_payload, valid)
    _add(metrics, "valid_schema", int(valid))
    _add(metrics, "language_exact", int(valid and payload.get("language") == gold["language"]))
    gold_claims = gold["claims"]
    pairs = align_claims(gold_claims, predicted)
    matched = {i: j for i, j in pairs}
    _add(metrics, "claim_recall", len(pairs), len(gold_claims))
    _add(metrics, "claim_precision", len(pairs), len(predicted))
    _add(metrics, "unsupported_extra_claims", len(predicted) - len(pairs), len(predicted))
    for kind in ("need", "access"):
        g = [c["label"] for c in gold_claims if c["kind"] == kind]
        p = [c["label"] for c in predicted if c["kind"] == kind]
        _add(metrics, f"{kind}_labels_exact", int(valid and Counter(g) == Counter(p)))
    for i, claim in enumerate(gold_claims):
        pred = predicted[matched[i]] if i in matched else None
        for slot in SLOTS:
            if claim["kind"] == "access" and slot in ("quantity", "unit", "urgency"):
                continue
            expected, actual = slot_value(claim, slot), slot_value(pred, slot)
            exact = pred is not None and expected == actual
            _add(metrics, f"{slot}_exact", int(exact))
            if expected is None:
                _add(metrics, f"{slot}_abstention", int(pred is not None and actual is None))
                _add(metrics, f"{slot}_false_fill", int(pred is not None and actual is not None))
            else:
                _add(metrics, f"{slot}_filled_recall", int(exact))
    supported, total_evidence = _evidence_counts(case["text"], predicted)
    if not valid:
        _, total_evidence = _evidence_counts(case["text"], gold_claims)
        supported = 0
    _add(metrics, "evidence_quote_support", supported, total_evidence)
    expected_signatures = Counter(signature(c) for c in gold_claims)
    actual_signatures = Counter(signature(c) for c in predicted)
    exact_claims = valid and expected_signatures == actual_signatures
    exact_flags = valid and set(flags) == set(gold["flags"])
    exact = exact_claims and exact_flags and payload.get("language") == gold["language"]
    _add(metrics, "exact_report", int(exact))
    _add(metrics, "flags_exact", int(exact_flags))
    for flag, name in (
        ("conflict", "conflict_detection"),
        ("qualified_access", "qualified_access_detection"),
        ("unknown_access", "unknown_access_detection"),
        ("no_need", "negation_no_need"),
        ("adversarial", "adversarial_resistance"),
        ("duplicate_repost", "duplicate_repost_handling"),
    ):
        if flag in gold["flags"]:
            success = valid and flag in flags
            if flag in ("no_need", "adversarial", "duplicate_repost"):
                success = success and exact_claims
            _add(metrics, name, int(success))
    reasons = []
    if error:
        reasons.append(error)
    if not exact_claims:
        reasons.append("claim signatures differ")
    if not exact_flags:
        reasons.append("flags differ")
    if valid and payload.get("language") != gold["language"]:
        reasons.append("language differs")
    return {
        "report_id": case["report_id"], "domain": case["domain"],
        "language": case["language"], "exact": bool(exact),
        "metrics": dict(metrics), "raw_diagnostics": raw_diagnostics,
        "failure_reasons": reasons, "prediction": raw_payload,
    }


def _aggregate(results: list[dict[str, Any]], key: str = "metrics") -> dict[str, dict[str, int | float | None]]:
    counts = _blank_metrics()
    for result in results:
        for name, item in result[key].items():
            _add(counts, name, item["numerator"], item["denominator"])
    return {
        name: {**count, "rate": count["numerator"] / count["denominator"] if count["denominator"] else None}
        for name, count in sorted(counts.items())
    }


def score_system(cases: list[dict[str, Any]], predictions: dict[str, dict[str, Any] | None],
                 provider: str, system_type: str) -> dict[str, Any]:
    results = [score_case(case, predictions.get(case["report_id"]), provider) for case in cases]
    return {
        "provider": provider,
        "system_type": system_type,
        "case_count": len(cases),
        "metrics": _aggregate(results),
        "raw_diagnostics": _aggregate(results, "raw_diagnostics"),
        "by_domain": {domain: _aggregate([r for r in results if r["domain"] == domain])
                      for domain in sorted({r["domain"] for r in results})},
        "by_language": {language: _aggregate([r for r in results if r["language"] == language])
                        for language in sorted({r["language"] for r in results})},
        "raw_diagnostics_by_domain": {domain: _aggregate([r for r in results if r["domain"] == domain], "raw_diagnostics")
                                      for domain in sorted({r["domain"] for r in results})},
        "raw_diagnostics_by_language": {language: _aggregate([r for r in results if r["language"] == language], "raw_diagnostics")
                                        for language in sorted({r["language"] for r in results})},
        "failures": [
            {key: result[key] for key in ("report_id", "failure_reasons", "prediction", "raw_diagnostics")}
            for result in results if not result["exact"]
        ],
    }


def load_external(path: Path, cases: list[dict[str, Any]]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        records, provider, metadata = data, "external_predictions", {}
    elif isinstance(data, dict):
        records = data["predictions"]
        provider = data.get("provider", "external_predictions")
        metadata = data.get("provider_metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("provider_metadata must be an object")
    else:
        raise ValueError("predictions must be an array or object with predictions array")
    known = {case["report_id"] for case in cases}
    result = {}
    for record in records:
        report_id = record["report_id"]
        if report_id not in known or report_id in result:
            raise ValueError(f"unknown or repeated report_id: {report_id}")
        result[report_id] = record.get("payload")
    return provider, result, metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, help="optional saved external predictions JSON")
    args = parser.parse_args(argv)
    cases = load_cases()
    systems = {}
    # Providers are loaded here so saved external predictions can be scored independently.
    if args.predictions:
        provider, predictions, metadata = load_external(args.predictions, cases)
        systems[provider] = score_system(cases, predictions, provider, "external_predictions")
        systems[provider]["provider_metadata"] = metadata
    else:
        from services.intake.providers import FixtureProvider, RuleBaseline
        fixture = FixtureProvider(cases)
        baseline = RuleBaseline()
        for provider_name, provider, system_type in (
            ("mocked_model_fixture", fixture, "harness_control"),
            ("rule_baseline", baseline, "deterministic_baseline"),
        ):
            predictions = {}
            for case in cases:
                report = Report(case["report_id"], "fictional_eval", 0.0, case["text"])
                try:
                    predictions[case["report_id"]] = provider.extract(report)
                except Exception as exc:
                    predictions[case["report_id"]] = {"provider_error": f"{type(exc).__name__}: {exc}"}
            systems[provider_name] = score_system(cases, predictions, provider_name, system_type)
    output = {
        "dataset": "intake_cases_v1", "fictional": True,
        "interpretation": "Mocked fixture scores measure harness coverage only; no real model inference was run.",
        "systems": systems,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    for name, system in systems.items():
        exact = system["metrics"]["exact_report"]
        print(f"{name}: exact {exact['numerator']}/{exact['denominator']}; failures {len(system['failures'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
