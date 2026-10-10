from copy import deepcopy

from evals.intake.run import load_cases, score_case, score_system


def _case(report_id):
    return next(case for case in load_cases() if case["report_id"] == report_id)


def test_fixture_gold_passes_parser_and_exact_scoring():
    cases = load_cases()
    system = score_system(cases, {c["report_id"]: c["gold"] for c in cases},
                          "mocked_model_fixture", "harness_control")
    assert system["metrics"]["valid_schema"]["numerator"] == 20
    assert system["metrics"]["exact_report"]["numerator"] == 20
    assert system["failures"] == []


def test_wrong_quantity_stays_in_denominator_and_failure_record():
    case = _case("WF10")
    prediction = deepcopy(case["gold"])
    prediction["claims"][0]["quantity"] = deepcopy(prediction["claims"][1]["quantity"])
    result = score_case(case, prediction, "wrong_quantity")
    assert not result["exact"]
    assert result["metrics"]["quantity_exact"]["numerator"] < result["metrics"]["quantity_exact"]["denominator"]
    assert "claim signatures differ" in result["failure_reasons"]
    assert result["prediction"] == prediction


def test_extra_invented_claim_fails_case_precision():
    case = _case("WF01")
    prediction = deepcopy(case["gold"])
    invented = deepcopy(prediction["claims"][0])
    invented["claim_id"] = "invented-repeat"
    prediction["claims"].append(invented)
    result = score_case(case, prediction, "invented_claim")
    assert result["metrics"]["claim_precision"] == {"numerator": 2, "denominator": 3}
    assert result["metrics"]["unsupported_extra_claims"] == {"numerator": 1, "denominator": 3}
    assert not result["exact"]


def test_vague_number_false_fill_is_counted():
    case = _case("CR06")
    prediction = deepcopy(case["gold"])
    claim = prediction["claims"][0]
    text = case["text"]
    start = text.index("20")
    claim["quantity"] = {"value": 20, "evidence": {"start": start, "end": start + 2, "quote": "20"}}
    start = text.index("boxes")
    claim["unit"] = {"value": "boxes", "evidence": {"start": start, "end": start + 5, "quote": "boxes"}}
    result = score_case(case, prediction, "false_fill")
    assert result["metrics"]["valid_schema"]["numerator"] == 0
    assert result["raw_diagnostics"]["rejected_quantity_false_fill"] == {"numerator": 1, "denominator": 1}
    assert result["metrics"]["evidence_quote_support"]["numerator"] == 0
    assert not result["exact"]


def test_invalid_prediction_remains_a_scored_failure():
    case = _case("WF01")
    result = score_case(case, {"language": "en", "flags": [], "claims": []}, "bad")
    assert result["metrics"]["valid_schema"] == {"numerator": 1, "denominator": 1}
    assert result["metrics"]["exact_report"]["numerator"] == 0

    result = score_case(case, {"language": "en", "claims": []}, "malformed")
    assert result["metrics"]["valid_schema"] == {"numerator": 0, "denominator": 1}
    assert result["metrics"]["evidence_quote_support"]["denominator"] > 0
    assert result["failure_reasons"]



def test_rejected_invented_location_is_counted_without_validity_credit():
    case = _case("WF07")
    prediction = deepcopy(case["gold"])
    claim = prediction["claims"][0]
    start = case["text"].index("road")
    claim["location"] = {
        "value": "road",
        "evidence": {"start": start, "end": start + 4, "quote": "road"},
    }
    result = score_case(case, prediction, "rejected_location")
    assert result["metrics"]["valid_schema"]["numerator"] == 0
    assert result["raw_diagnostics"]["rejected_location_false_fill"] == {
        "numerator": 1, "denominator": 1
    }
    assert result["metrics"]["claim_precision"]["numerator"] == 0
    assert result["metrics"]["evidence_quote_support"]["numerator"] == 0


def test_malformed_claim_shapes_are_retained_without_crash_or_precision_credit():
    case = _case("WF01")
    malformed = {
        "language": "en",
        "flags": ["not-a-valid-flag"],
        "claims": [
            ["not an object"],
            {"kind": [], "label": {"unhashable": "label"}, "quantity": {"value": [6]}},
            {"kind": "need", "label": "evacuation", "quantity": {"value": {"bad": "count"}},
             "location": {"value": ["Pine Creek School"]}},
        ] + [[] for _ in range(30)],
    }
    result = score_case(case, malformed, "malformed")
    assert result["metrics"]["valid_schema"]["numerator"] == 0
    assert result["raw_diagnostics"]["raw_over_limit_claims"] == {
        "numerator": 13, "denominator": 33
    }
    assert result["raw_diagnostics"]["raw_extra_claims"]["numerator"] == 32
    assert result["metrics"]["claim_precision"]["numerator"] == 0
    assert result["prediction"] == malformed


def test_nonlist_claims_and_nonobject_payload_remain_failures():
    case = _case("WF01")
    for payload in ({"language": "en", "flags": [], "claims": {"kind": "need"}},
                    {"language": "en", "flags": [], "claims": "invented"},
                    ["not a proposal"]):
        result = score_case(case, payload, "malformed")
        assert result["metrics"]["valid_schema"]["numerator"] == 0
        assert result["metrics"]["exact_report"]["numerator"] == 0
        assert result["raw_diagnostics"]["raw_extra_claims"] == {
            "numerator": 0, "denominator": 0
        }
        assert result["prediction"] == payload
