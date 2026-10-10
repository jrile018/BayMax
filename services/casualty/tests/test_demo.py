import json


def test_scripted_case_review_trace_preserves_abstention_and_need(tmp_path):
    from services.casualty.demo import run_demo
    output=tmp_path / "case-review.json"
    run_demo(output)
    data=json.loads(output.read_text())
    assert data["data_kind"]=="synthetic_geometric_control"
    assert data["real_detector_status"]=="pending"
    assert data["clinical_validation_status"]=="unavailable"
    assert data["localized_review"]["request"]["persons"]==1
    assert data["localized_review"]["request"]["urgency"]=="urgent"
    assert data["no_face_review"]["request"]["evidence_status"]=="abstained"
    assert data["no_face_review"]["request"]["persons"]==1
    assert data["control_evaluation"]["counts"]=={"true_positive":1,"false_positive":1,"false_negative":1,"matched_iou_sum":1.0}
    assert data["control_evaluation"]["performance_claim"]=="harness_geometry_only"
    assert data["learning_debrief"]["urgency_source"]=="exercise_metadata_with_human_confirmation"
    assert data["integration_status"]=="pending_root_adapter"
