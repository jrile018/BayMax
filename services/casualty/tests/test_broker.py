"""Human review must not fabricate priority or let image misses suppress exercise needs."""
from dataclasses import replace
import pytest
from .test_contracts import case, detection


def candidate():
    from services.casualty.broker import CandidateEvidence
    return CandidateEvidence(evidence_id="cue-001", label="moulage_mark", face_box_index=0,
                             source_reference="fixture:manual-makeup-cue", provenance="fixture_annotation")


def submitted(result=None,candidates=None):
    from services.casualty.broker import CaseBroker
    b=CaseBroker()
    p=b.submit(case(), result or detection(), candidates if candidates is not None else (candidate(),), created_time_s=7.0)
    return b,p


def test_pending_proposal_never_exports_a_medical_request():
    b,p=submitted()
    with pytest.raises(ValueError, match="review"):
        b.export_request(p.proposal_id)


def test_priority_is_the_authored_exercise_need_and_review_is_idempotent():
    b,p=submitted()
    receipt=b.review(p.proposal_id, reviewer_id="trainee-001", decision="accepted", confirmed_evidence=("cue-001",),
                     confirm_exercise_need=True, reviewed_time_s=8)
    command=b.export_request(receipt)
    assert command.urgency=="urgent"
    assert command.persons==1
    assert command.origin_node=="school"
    assert command.destination_node=="clinic"
    assert command.need_provenance=="exercise_metadata_with_human_confirmation"
    assert command.detection_provenance=="mock_fixture"
    assert b.review(p.proposal_id, reviewer_id="trainee-001", decision="accepted", confirmed_evidence=("cue-001",),
                    confirm_exercise_need=True, reviewed_time_s=9)==receipt
    assert b.export_request(receipt)==command


def test_rejection_or_missing_exercise_confirmation_emits_nothing():
    for decision in ("accepted","rejected"):
        b,p=submitted()
        r=b.review(p.proposal_id,reviewer_id="trainee-001", decision=decision, reviewed_time_s=8)
        assert b.export_request(r) is None


def test_conflicting_terminal_review_is_rejected():
    b,p=submitted()
    b.review(p.proposal_id,reviewer_id="trainee-001",decision="rejected",reviewed_time_s=8)
    with pytest.raises(ValueError,match="terminal"):
        b.review(p.proposal_id,reviewer_id="trainee-001",decision="accepted",confirm_exercise_need=True,reviewed_time_s=9)


def test_forged_receipt_cannot_export():
    b,p=submitted()
    r=b.review(p.proposal_id,reviewer_id="trainee-001",decision="accepted",confirm_exercise_need=True,reviewed_time_s=8)
    with pytest.raises(ValueError,match="receipt"):
        b.export_request(replace(r,image_sha256="0"*64))


def test_case_image_and_exercise_cannot_be_swapped_under_one_case_id():
    b,p=submitted()
    altered=replace(case(),exercise_need=replace(case().exercise_need,urgency="routine"))
    with pytest.raises(ValueError,match="case"):
        b.submit(altered,detection(),(candidate(),),created_time_s=8)
    with pytest.raises(ValueError,match="mismatch"):
        b.submit(case(),replace(detection(),image_sha256="0"*64),(candidate(),),created_time_s=8)


@pytest.mark.parametrize("status",["no_face","occluded","failed"])
def test_abstention_has_no_visual_claim_but_manual_exercise_request_survives(status):
    b,p=submitted(result=detection(status), candidates=())
    assert p.abstention_reason==status
    assert p.candidates==()
    r=b.review(p.proposal_id,reviewer_id="trainee-001",decision="accepted",confirm_exercise_need=True,reviewed_time_s=8)
    cmd=b.export_request(r)
    assert cmd.persons==1
    assert cmd.confirmed_evidence==()
    assert cmd.evidence_status=="abstained"
    with pytest.raises(ValueError,match="abstain"):
        submitted(result=detection(status),candidates=(candidate(),))


def test_unsupported_evidence_cannot_be_selected_by_review():
    b,p=submitted()
    with pytest.raises(ValueError,match="evidence"):
        b.review(p.proposal_id,reviewer_id="trainee-001",decision="accepted",confirmed_evidence=("invented",),reviewed_time_s=8)
    with pytest.raises(ValueError,match="label"):
        replace(candidate(),label="severe_internal_trauma")


def test_another_detection_cannot_create_a_second_request_key():
    b,p=submitted()
    r=b.review(p.proposal_id,reviewer_id="trainee-001",decision="accepted",confirm_exercise_need=True,reviewed_time_s=8)
    p2=b.submit(case(),replace(detection(),observed_time_s=9),(candidate(),),created_time_s=10)
    r2=b.review(p2.proposal_id,reviewer_id="trainee-001",decision="accepted",confirm_exercise_need=True,reviewed_time_s=11)
    assert b.export_request(r).idempotency_key==b.export_request(r2).idempotency_key


def test_review_requires_named_human_and_valid_chronology():
    b,p=submitted()
    with pytest.raises(ValueError,match="reviewer"):
        b.review(p.proposal_id,reviewer_id="",decision="accepted",reviewed_time_s=8)
    with pytest.raises(ValueError,match="time"):
        b.review(p.proposal_id,reviewer_id="trainee-001",decision="accepted",reviewed_time_s=1)


def test_candidate_face_reference_must_exist_and_unvalidated_model_is_explicit():
    b,p=submitted()
    with pytest.raises(ValueError,match="box"):
        b.submit(case(),detection(),(replace(candidate(),face_box_index=2),),created_time_s=7)
    with pytest.raises(ValueError,match="synthetic"):
        b.submit(case(),detection(),(replace(candidate(),provenance="human_annotation"),),created_time_s=7)
