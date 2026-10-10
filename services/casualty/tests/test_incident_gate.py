"""The casualty owner can label training evidence but cannot certify incident adoption."""
from dataclasses import replace
import pytest

from services.casualty.broker import CaseBroker
from services.casualty.contracts import DetectionResult
from services.casualty.demo import load_fixture


def reviewed_request(status="localized"):
    case, face = load_fixture()
    boxes = (face,) if status == "localized" else ()
    detection = DetectionResult(
        case.case_id, case.image.sha256, status, boxes,
        "synthetic-box-control", "fixture-v1", "mock_fixture", 5,
        "Hand-authored control; no inference",
    )
    broker = CaseBroker()
    proposal = broker.submit(case, detection, (), created_time_s=7)
    receipt = broker.review(
        proposal.proposal_id, reviewer_id="scripted-trainee-001",
        decision="accepted", confirm_exercise_need=True, reviewed_time_s=8,
    )
    return case, broker.export_request(receipt)


def test_illustrated_case_stays_pending_with_explicit_source_and_reviewer_limits():
    from services.casualty.incident_gate import make_pending_incident_evidence

    case, request = reviewed_request()
    evidence = make_pending_incident_evidence(
        case, request, review_actor_kind="scripted_demo"
    )
    assert evidence.case_hash == case.content_hash
    assert evidence.image_sha256 == case.image.sha256
    assert evidence.request_id == case.exercise_need.request_id
    assert evidence.source_kind == "synthetic"
    assert evidence.source_reference == "project:geometric-control-v1"
    assert evidence.rights_status_claim == "verified"
    assert evidence.review_actor_kind == "scripted_demo"
    assert evidence.reviewer_id == "scripted-trainee-001"
    assert evidence.adoption_status == "pending"
    assert evidence.operational_eligible is False
    assert "synthetic_fixture_training_only" in evidence.blockers
    assert "authenticated_record_bound_human_review" in evidence.blockers
    assert "root_verified_casualty_source" in evidence.blockers


def test_owner_cannot_self_assert_authenticated_review():
    from services.casualty.incident_gate import make_pending_incident_evidence

    case, request = reviewed_request()
    with pytest.raises(ValueError, match="review_actor_kind"):
        make_pending_incident_evidence(
            case, request, review_actor_kind="authenticated_operator"
        )


def test_case_or_receipt_mismatch_cannot_enter_pending_handoff():
    from services.casualty.incident_gate import make_pending_incident_evidence

    case, request = reviewed_request()
    with pytest.raises(ValueError, match="case"):
        make_pending_incident_evidence(
            replace(case, case_id="npc-case-other"), request,
            review_actor_kind="scripted_demo",
        )
    forged = replace(
        request,
        review_receipt=replace(request.review_receipt, image_sha256="0" * 64),
    )
    with pytest.raises(ValueError, match="receipt"):
        make_pending_incident_evidence(
            case, forged, review_actor_kind="scripted_demo",
        )


def test_no_face_keeps_authored_exercise_need_but_stays_pending():
    from services.casualty.incident_gate import make_pending_incident_evidence

    case, request = reviewed_request("no_face")
    evidence = make_pending_incident_evidence(
        case, request, review_actor_kind="scripted_demo"
    )
    assert evidence.request_id == case.exercise_need.request_id
    assert evidence.evidence_status == "abstained"
    assert evidence.operational_eligible is False


def test_proposal_hash_and_request_key_are_bound_to_exercise_source():
    from services.casualty.incident_gate import make_pending_incident_evidence

    case, request = reviewed_request()
    altered_receipt = replace(
        request,
        review_receipt=replace(request.review_receipt, proposal_hash="0" * 64),
    )
    with pytest.raises(ValueError, match="receipt"):
        make_pending_incident_evidence(
            case, altered_receipt, review_actor_kind="scripted_demo"
        )
    altered_key = replace(request, idempotency_key="casualty-exercise-need-forged")
    with pytest.raises(ValueError, match="request"):
        make_pending_incident_evidence(
            case, altered_key, review_actor_kind="scripted_demo"
        )
