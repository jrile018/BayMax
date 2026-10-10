"""Behavior checks: rights, image binding and uncertainty reject unsafe inputs."""
from dataclasses import replace
from hashlib import sha256
import pytest


def rights(kind="synthetic", **changes):
    from services.casualty.contracts import RightsManifest
    values = dict(source_kind=kind, source_reference="fixture:geometric-case", license_id="CC0-1.0",
                  permitted_uses=("display", "face_detection", "evaluation"),
                  verification_status="verified", license_evidence="fixture:authored-by-project",
                  consent_evidence=None, verified_by="fixture-author", verified_at="2026-10-10",
                  acquired_at="2026-10-10", adult_only=True)
    values.update(changes)
    return RightsManifest(**values)


def case(**changes):
    from services.casualty.contracts import CaseRecord, ImageRecord, ExerciseNeed
    values = dict(case_id="npc-case-001", rights=rights(),
        image=ImageRecord(image_reference="fixtures/casualty/geometric.svg", sha256=sha256(b"fixture").hexdigest(),
                          width=100, height=100, annotation_reference="fixture:box-001",
                          annotation_author="fixture-author", annotation_date="2026-10-10"),
        exercise_need=ExerciseNeed(request_id="exercise-med-001", origin_node="school", destination_node="clinic",
                                   persons=1, urgency="urgent", source_reference="exercise:manual-001"))
    values.update(changes)
    return CaseRecord(**values)


def detection(status="localized", **changes):
    from services.casualty.contracts import DetectionResult, FaceBox
    values = dict(case_id="npc-case-001", image_sha256=sha256(b"fixture").hexdigest(), status=status,
                  boxes=(FaceBox(0.1, 0.2, 0.6, 0.8, 0.9),) if status=="localized" else (),
                  provider="synthetic-box-fixture", model_revision="fixture-v1", provenance="mock_fixture",
                  observed_time_s=5.0, detail="Synthetic control; no image inference")
    values.update(changes)
    return DetectionResult(**values)


def test_synthetic_case_is_explicit_and_hash_bound():
    from services.casualty.contracts import verify_image
    c=case()
    assert c.rights.source_kind=="synthetic"
    assert verify_image(c, b"fixture", "face_detection") == c.image.sha256
    with pytest.raises(ValueError, match="hash"):
        verify_image(c, b"swapped", "face_detection")


def test_real_photo_requires_independent_license_and_adult_consent():
    for field, value in [("verification_status","pending"), ("license_evidence", ""),
                         ("consent_evidence",None), ("adult_only",False), ("verified_by","")]:
        r=rights("consented_photo", consent_evidence="consent:adult-approved-001", **{field:value}) if field != "consent_evidence" else rights("consented_photo",consent_evidence=None)
        with pytest.raises(ValueError):
            r.require("display")
    rights("consented_photo",consent_evidence="consent:adult-approved-001").require("display")


def test_each_operation_requires_its_own_permission():
    r=rights(permitted_uses=("display",))
    r.require("display")
    with pytest.raises(ValueError,match="permission"):
        r.require("face_detection")


@pytest.mark.parametrize("coords", [(-0.1,.2,.6,.8,.9),(.5,.2,.5,.8,.9),(.6,.2,.1,.8,.9),
                                      (.1,.2,1.1,.8,.9),(.1,.2,.6,float("nan"),.9),
                                      (.1,.2,.6,.8,float("inf")),(True,.2,.6,.8,.9)])
def test_malformed_box_cannot_become_face_evidence(coords):
    from services.casualty.contracts import FaceBox
    with pytest.raises(ValueError):
        FaceBox(*coords)


def test_no_face_status_cannot_smuggle_boxes():
    with pytest.raises(ValueError,match="boxes"):
        replace(detection(),status="no_face")


def test_actual_detector_requires_pinned_revision_and_real_photo():
    with pytest.raises(ValueError, match="revision"):
        replace(detection(),provenance="actual_detector", model_revision="")
    from services.casualty.contracts import validate_detection
    with pytest.raises(ValueError, match="synthetic"):
        validate_detection(case(), replace(detection(),provenance="actual_detector", model_revision="3cc26e7f1014a5ee5d74a42acee58bafc9d0a310"))


def test_case_rejects_real_identity_like_ids_and_boolean_quantity():
    with pytest.raises(ValueError, match="case_id"):
        replace(case(),case_id="alice@example.com")
    with pytest.raises(ValueError,match="persons"):
        replace(case().exercise_need,persons=True)


def test_time_dimensions_and_hash_are_strict():
    with pytest.raises(ValueError): replace(detection(),observed_time_s=float("nan"))
    with pytest.raises(ValueError): replace(case().image,width=True)
    with pytest.raises(ValueError): replace(case().image,sha256="not-a-hash")


def test_case_records_are_immutable():
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        case().case_id="npc-case-002"


def test_public_channels_are_separate_from_private_training_display():
    r=rights("staged_photo",consent_evidence="consent:adult-demo-001",permitted_uses=("display","public_demo"))
    r.require("public_demo")
    with pytest.raises(ValueError,match="permission"): r.require("video")
    with pytest.raises(ValueError,match="permission"): r.require("dataset_publication")
