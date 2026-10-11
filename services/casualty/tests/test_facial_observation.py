"""Synthetic contract controls ONLY. Every 'actual' receipt below is fabricated.

No test input is a real photo, permission, execution, authentication or evaluation.
Source authored under a source-only assignment; execution requires root CPU grant.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from services.casualty.facial_codec import canonical_bytes, content_fingerprint, parse_json
from services.casualty.facial_observation import (
    InvalidEvidence, MissingEvidence, PermissionDenied, StaleBinding,
    TrustedRegistry, TrustedProof, EvaluationItem, EvaluationLineage, TrustedCaseBinding,
    VERSION, admit_observation, admit_localization, prepare_visual_request,
    record_fingerprint, frame_fingerprint, validate_frame, validate_envelope,
    validate_observation, validate_normalized_image, validate_human_review, resolve_case_bridge,
)
from services.casualty.contracts import CaseRecord, ImageRecord, RightsManifest

BASE = datetime(2026, 10, 11, tzinfo=timezone.utc)
NOW = BASE + timedelta(seconds=5)
IMAGE = b"contract_test_fixture-not-raster-not-permission"
BOX = {"x1": .1, "y1": .1, "x2": .9, "y2": .9}
CATEGORIES = ["bruise_like_discoloration", "cut_or_abrasion", "visible_blood"]


def time(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def h(label):
    return sha256(label.encode()).hexdigest()


def env(kind, record):
    return {"schema_version": VERSION, "message_kind": kind, "record": record}


def thaw(value):
    return parse_json(canonical_bytes(value))


def fixture(outcome="possible_visible_concern", categories=None, purposes=None, capture_expiry=900, capture_accepted=1,
            visual_start=3, visual_end=4, detector_eval_time=0, visual_eval_time=0, evaluation_issued=0):
    records, proofs = {}, {}

    def add(envelope):
        digest = record_fingerprint(envelope)
        records[digest] = envelope
        return digest

    def proof(digest, role, subject, actor=None):
        proofs[(digest, role, subject)] = TrustedProof(role, subject, BASE, BASE + timedelta(seconds=900), actor)

    artifact = {"model_id": "contract_test_fixture", "model_revision": "a" * 40,
        **{key: h(key) for key in ("weights_manifest_sha256", "processor_manifest_sha256", "runtime_manifest_sha256",
            "prompt_sha256", "decoding_config_sha256", "adapter_source_sha256")}}
    permission = env("capture_permission", {"camera_session_id": "camera-test", "arrival_id": "arrival-test",
        "actor_id": "actor-test", "assigned_role": "volunteer", "purposes": ["capture", "visual_assessment", "human_review"] if purposes is None else purposes,
        "consent_receipt_sha256": h("consent"), "rights_review_receipt_sha256": h("rights"),
        "issued_at": time(0), "expires_at": time(900), "retention_deadline": time(900),
        "derived_retention_deadline": time(900), "withdrawal_epoch": 0, "session_scope": "private_exercise",
        "capture_source": "live_webcam", "staging_label": "non_injury_stage_makeup", "public_use_allowed": False,
        "dataset_reuse_allowed": False})
    pd = add(permission)
    proof(h("consent"), "consent", pd, "actor-test")
    proof(h("rights"), "capture_rights", pd)
    frame = {"frame_id": "frame-test", "camera_session_id": "camera-test", "arrival_id": "arrival-test",
        "arrival_revision": 1, "capture_id": "capture-test", "capture_revision": 1,
        "source_kind": "live_webcam", "captured_at": time(1), "source_image_sha256": h("original-bytes"),
        "image_sha256": sha256(IMAGE).hexdigest(), "width": 100, "height": 100,
        "orientation": "upright_raw_raster", "permission_receipt_sha256": pd}
    capture = env("capture_receipt", {"frame_fingerprint": frame_fingerprint(frame), "permission_receipt_sha256": pd,
        "normalization_manifest_sha256": h("normalization"), "normalized_image_sha256": frame["image_sha256"],
        "accepted_at": time(capture_accepted), "expires_at": time(capture_expiry), "withdrawal_epoch": 0,
        "purpose": "capture", "storage_kind": "private_selected_capture", "issuer_identity_receipt_sha256": h("capture-issuer")})
    cd = add(capture)
    proof(h("capture-issuer"), "capture_issuer", cd)
    proof(h("normalization"), "normalization", frame_fingerprint(frame))
    ep = env("evaluation_permission", {"participant_ref": "test-participant", "camera_session_ids": ["camera-test"],
        "consent_receipt_sha256": h("evaluation-consent"), "rights_review_receipt_sha256": h("evaluation-rights"),
        "purposes": ["heldout_evaluation", "private_report_retention"], "issued_at": time(evaluation_issued), "expires_at": time(900),
        "media_retention_deadline": time(900), "derived_retention_deadline": time(900), "withdrawal_epoch": 0,
        "scope": "dedicated_consented_staged_evaluation", "model_training_allowed": False, "public_use_allowed": False,
        "deidentified_aggregate_retention_allowed": False, "issuer_identity_receipt_sha256": h("eval-perm-issuer")})
    epd = add(ep)
    for digest, role in ((h("evaluation-consent"), "evaluation_consent"), (h("evaluation-rights"), "evaluation_rights"),
                         (h("eval-perm-issuer"), "evaluation_permission_issuer")):
        proof(digest, role, epd)
    lineage = {}

    def evaluation(kind, task):
        r = {"evaluation_id": "test-" + task, "artifact": artifact, "task": task,
             **{key: h(task + key) for key in ("plan_sha256", "dataset_manifest_sha256", "split_manifest_sha256",
                "metrics_sha256", "review_receipt_sha256", "evaluation_permission_manifest_sha256")},
             "scope": "consented_staged_webcam_demo", "decision": "accepted_for_staged_demo",
             "evaluated_at": time(detector_eval_time if task == "face_localization" else visual_eval_time)}
        if task == "visible_facial_concerns":
            r["categories"] = CATEGORIES[:] if categories is None else categories
        digest = add(env(kind, r))
        proof(r["review_receipt_sha256"], "evaluation_review", digest)
        for key in ("plan_sha256", "dataset_manifest_sha256", "split_manifest_sha256", "metrics_sha256", "evaluation_permission_manifest_sha256"):
            proof(r[key], key, digest)
        lineage[digest] = EvaluationLineage(r["evaluation_permission_manifest_sha256"], (EvaluationItem(pd, epd, "camera-test"),))
        return digest

    le = evaluation("localization_evaluation_receipt", "face_localization")
    ve = evaluation("evaluation_receipt", "visible_facial_concerns")
    lr = env("localization_request", {"request_id": "loc-request", "frame": frame, "capture_receipt_sha256": cd,
        "artifact": artifact, "task": "face_localization", "evaluation_receipt_sha256": le, "deadline_at": time(60)})
    lrd = add(lr)
    lo = {"status": "localized", "boxes": [BOX], "selected_face_index": 0, "reason": "face_localized"}
    lex = env("localization_execution_receipt", {"execution_id": "loc-execution", "artifact": artifact,
        "origin": "actual_detector", "started_at": time(2), "ended_at": time(3), "state": "completed", "output": lo,
        "output_sha256": content_fingerprint(lo), "runtime_log_sha256": h("loc-log"), "process_exit_code": 0,
        "issuer_identity_receipt_sha256": h("detector-issuer"), "localization_request_fingerprint": lrd})
    led = add(lex)
    proof(h("loc-log"), "runtime_log", led)
    proof(h("detector-issuer"), "detector_issuer", led)
    localization = env("localization", {"frame": frame, "artifact": artifact, **lo, "origin": "actual_detector",
        "execution_receipt_sha256": led, "round_trip_ms": 1000, "capture_receipt_sha256": cd})
    ld = add(localization)
    vr = env("runner_request", {"request_id": "visual-request", "frame": frame, "capture_receipt_sha256": cd,
        "localization_receipt_sha256": ld, "evaluation_receipt_sha256": ve, "artifact": artifact,
        "task": "visible_facial_concerns", "deadline_at": time(60)})
    vrd = add(vr)
    output = {"outcome": outcome, "assessment_region": BOX, "cues": [], "reason_code": "uncertain_visible_evidence"}
    if outcome == "possible_visible_concern":
        output.update(cues=[{"cue_id": "cue-test", "category": "visible_blood", "region": {"x1": .2, "y1": .2, "x2": .3, "y2": .3}, "reason_code": "visible_red_fluid"}], reason_code="supported_visible_cue")
    elif outcome == "no_visible_concern_detected":
        output["reason_code"] = "no_supported_cue_in_region"
    vx = env("execution_receipt", {"execution_id": "visual-execution", "runner_request_fingerprint": vrd, "artifact": artifact,
        "origin": "actual_visual_runner", "started_at": time(visual_start), "ended_at": time(visual_end), "state": "completed", "output": output,
        "output_sha256": content_fingerprint(output), "runtime_log_sha256": h("visual-log"), "process_exit_code": 0,
        "issuer_identity_receipt_sha256": h("visual-issuer")})
    vxd = add(vx)
    proof(h("visual-log"), "runtime_log", vxd)
    proof(h("visual-issuer"), "visual_issuer", vxd)
    observation = env("concern_observation", {"observation_id": "observation-test", "frame": frame,
        "localization_receipt_sha256": ld, **output, "origin": "actual_evaluated_runner", "evaluation_receipt_sha256": ve,
        "execution_receipt_sha256": vxd, "created_at": time(4), "latency_ms": 1000, "operational_eligible": False,
        "capture_receipt_sha256": cd})
    od = add(observation)
    proof(od, "admitted_observation", od)
    registry = TrustedRegistry(records, proofs, {pd: 0, epd: 0}, lineage,
        {("camera-test", "arrival-test"): frame_fingerprint(frame)}, {})
    return frame, localization, observation, vr, registry


def admit(frame, loc, obs, registry, now=NOW):
    return admit_observation(obs, current_frame=frame, localization=loc, trusted_registry=registry, now=now)


@pytest.mark.parametrize("outcome", ["possible_visible_concern", "no_visible_concern_detected", "unable_to_assess"])
def test_fabricated_complete_graph_positive_control(outcome):
    frame, loc, obs, request, registry = fixture(outcome)
    assert record_fingerprint(admit(frame, loc, obs, registry)) == record_fingerprint(obs)
    prepare_visual_request(request, current_frame=frame, image_bytes=IMAGE, localization=loc, trusted_registry=registry, now=NOW)
    with pytest.raises(TypeError):
        admit(frame, loc, obs, registry)["record"]["origin"] = "scripted_training"


def test_shared_jcs_vectors():
    vectors = parse_json(Path(__file__).with_name("CANONICALIZATION_VECTORS_V1.json").read_bytes())
    for vector in vectors["vectors"]:
        value = parse_json(vector["input_json"])
        assert canonical_bytes(value) == vector["canonical_utf8"].encode()
        assert content_fingerprint(value) == vector["sha256"]
    for text in vectors["reject_inputs"]:
        with pytest.raises(InvalidEvidence):
            parse_json(text)


@pytest.mark.parametrize("kind", [[], {}, None, True, 7])
def test_malformed_kind_uses_concrete_denial_exception(kind):
    with pytest.raises(InvalidEvidence):
        validate_envelope({"schema_version": VERSION, "message_kind": kind, "record": {}})


@pytest.mark.parametrize("value,expected", [(1e-6, "0.000001"), (1e-7, "1e-7"), (1e21, "1e+21"),
    (-0.0, "0"), (295147905179352825856.0, "295147905179352830000"), (333333333.33333329, "333333333.3333333")])
def test_binary64_spellings(value, expected):
    assert canonical_bytes(value).decode() == expected


@pytest.mark.parametrize("field,value", [("capture_id", "retake"), ("capture_revision", 2), ("arrival_revision", 2),
    ("image_sha256", "f" * 64), ("source_image_sha256", "e" * 64), ("camera_session_id", "other-session")])
def test_full_current_frame_substitution_including_identical_bytes(field, value):
    frame, loc, obs, _, registry = fixture()
    current = deepcopy(frame)
    current[field] = value
    with pytest.raises(InvalidEvidence):
        admit(current, loc, obs, registry)


def test_wrong_normalized_bytes_denied_before_any_callback():
    frame, loc, _, request, registry = fixture()
    with pytest.raises(StaleBinding):
        prepare_visual_request(request, current_frame=frame, image_bytes=b"different", localization=loc, trusted_registry=registry, now=NOW)


@pytest.mark.parametrize("mutation", ["outcome", "reason", "region", "cue_id", "cue_region", "cue_category", "extra"])
def test_same_frame_output_substitution(mutation):
    frame, loc, obs, _, registry = fixture()
    changed = deepcopy(obs)
    o = changed["record"]
    if mutation == "outcome":
        o.update(outcome="no_visible_concern_detected", cues=[], reason_code="no_supported_cue_in_region")
    elif mutation == "reason":
        o.update(outcome="unable_to_assess", cues=[], reason_code="uncertain_visible_evidence")
    elif mutation == "region":
        o["assessment_region"] = {"x1": .11, "y1": .1, "x2": .9, "y2": .9}
    elif mutation == "cue_id":
        o["cues"][0]["cue_id"] = "changed-id"
    elif mutation == "cue_region":
        o["cues"][0]["region"]["x2"] = .4
    elif mutation == "cue_category":
        o["cues"][0].update(category="cut_or_abrasion", reason_code="visible_surface_break")
    else:
        o["diagnosis"] = "forbidden"
    with pytest.raises(InvalidEvidence):
        admit(frame, loc, changed, registry)


def test_forged_shape_without_root_registry_facts():
    frame, loc, obs, _, registry = fixture()
    with pytest.raises(MissingEvidence):
        admit(frame, loc, obs, replace(registry, proofs={}))
    with pytest.raises(MissingEvidence):
        admit(frame, loc, obs, {})


def test_negative_cannot_use_partial_category_evaluation():
    frame, loc, obs, _, registry = fixture("no_visible_concern_detected", categories=["visible_blood"])
    with pytest.raises(MissingEvidence):
        admit(frame, loc, obs, registry)


def test_selected_processing_cannot_substitute_for_capture_permission():
    frame, loc, obs, _, registry = fixture(purposes=["visual_assessment", "human_review"])
    with pytest.raises(PermissionDenied):
        admit(frame, loc, obs, registry)


def test_capture_lifetime_cannot_exceed_origin_grant():
    frame, loc, obs, _, registry = fixture(capture_expiry=901)
    with pytest.raises(PermissionDenied):
        admit(frame, loc, obs, registry)


def test_execution_cannot_precede_accepted_capture():
    frame, loc, obs, _, registry = fixture(capture_accepted=4)
    with pytest.raises(InvalidEvidence):
        admit(frame, loc, obs, registry)


@pytest.mark.parametrize("kwargs", [{"visual_start": 2, "visual_end": 2.5}, {"detector_eval_time": 3}, {"visual_eval_time": 4}])
def test_execution_must_follow_evaluation_and_selected_localization(kwargs):
    frame, loc, obs, _, registry = fixture(**kwargs)
    with pytest.raises(InvalidEvidence):
        admit(frame, loc, obs, registry)


@pytest.mark.parametrize("kwargs", [{"detector_eval_time": -1}, {"evaluation_issued": 1}])
def test_current_grant_cannot_authorize_evaluation_before_issuance(kwargs):
    frame, loc, obs, _, registry = fixture(**kwargs)
    with pytest.raises(PermissionDenied):
        admit(frame, loc, obs, registry)


def test_snapshot_detaches_original_records():
    frame, loc, obs, _, registry = fixture()
    obs["record"]["cues"][0]["cue_id"] = "mutated-after-registry"
    frozen = registry.records[next(k for k, v in registry.records.items() if v["message_kind"] == "concern_observation")]
    assert frozen["record"]["cues"][0]["cue_id"] == "cue-test"


def test_epoch_expiry_and_evaluation_withdrawal():
    frame, loc, obs, _, registry = fixture()
    for digest in registry.permission_epochs:
        epochs = dict(registry.permission_epochs)
        epochs[digest] += 1
        with pytest.raises(PermissionDenied):
            admit(frame, loc, obs, replace(registry, permission_epochs=epochs))
    with pytest.raises(PermissionDenied):
        admit(frame, loc, obs, registry, BASE + timedelta(seconds=900))


def test_localization_same_frame_substitution():
    frame, loc, _, _, registry = fixture()
    changed = deepcopy(loc)
    changed["record"]["boxes"][0]["x2"] = .8
    with pytest.raises(InvalidEvidence):
        admit_localization(changed, current_frame=frame, trusted_registry=registry, now=NOW)


def test_bad_region_nonfinite_boolean_and_category_reason():
    frame, loc, obs, _, _ = fixture()
    for value in (float("nan"), float("inf"), True, -.1, 1.1):
        changed = deepcopy(obs)
        changed["record"]["cues"][0]["region"]["x1"] = value
        with pytest.raises(InvalidEvidence):
            validate_observation(changed["record"], frame, loc)
    changed = deepcopy(obs)
    changed["record"]["cues"][0]["reason_code"] = "visible_surface_break"
    with pytest.raises(InvalidEvidence):
        validate_observation(changed["record"], frame, loc)


def test_human_review_after_assessment_revision_and_stale_capture():
    frame, _, obs, _, registry = fixture()
    current = {**frame, "arrival_revision": 2}
    review = env("human_review", {"review_id": "review-test", "observation_fingerprint": record_fingerprint(obs),
        "arrival_id": frame["arrival_id"], "capture_id": frame["capture_id"], "capture_revision": frame["capture_revision"],
        "reviewer_id": "reviewer-test", "reviewer_identity_receipt_sha256": h("reviewer"), "assigned_role": "care_reviewer",
        "decision": "confirm_visible_concern", "confirmed_cue_ids": ["cue-test"], "reviewed_at": time(5), "operational_eligible": False})
    proofs = dict(registry.proofs)
    rd = record_fingerprint(review)
    proofs[(h("reviewer"), "care_reviewer", rd)] = TrustedProof("care_reviewer", rd, BASE, BASE + timedelta(seconds=900), "reviewer-test")
    registry = replace(registry, proofs=proofs, current_frames={("camera-test", "arrival-test"): frame_fingerprint(current)})
    validate_human_review(review, current_observation=obs, current_frame=current, trusted_registry=registry, now=NOW)
    with pytest.raises(InvalidEvidence):
        validate_human_review(review, current_observation=obs, current_frame={**current, "capture_id": "retake"}, trusted_registry=registry, now=NOW)


def test_root_typed_case_time_bridge_and_no_fabrication():
    frame, _, _, _, registry = fixture()
    cd = next(k for k, v in registry.records.items() if v["message_kind"] == "capture_receipt")
    kwargs = dict(frame=frame, image_bytes=IMAGE, capture_receipt_sha256=cd, trusted_registry=registry, now=NOW)
    with pytest.raises(MissingEvidence):
        resolve_case_bridge(**kwargs)
    rights = RightsManifest("staged_photo", "test-item", "test-only-license", ("face_detection",), "verified",
        "test-only-rights", "test-only-consent", "test-author", "2026-10-11", "2026-10-11", True)
    case = CaseRecord("npc-case-test", rights, ImageRecord("test-image", frame["image_sha256"], 100, 100, "test-annotation", "test-author", "2026-10-11"))
    binding = TrustedCaseBinding(frame_fingerprint(frame), case, 1.0, h("rights"))
    bridge_digest = content_fingerprint({"frame_fingerprint": binding.frame_fingerprint, "case_content_hash": case.content_hash,
        "observed_time_s": 1.0, "rights_review_receipt_sha256": h("rights")})
    proofs = dict(registry.proofs)
    proofs[(bridge_digest, "typed_case_bridge", binding.frame_fingerprint)] = TrustedProof("typed_case_bridge", binding.frame_fingerprint, BASE, BASE + timedelta(seconds=900))
    trusted = replace(registry, proofs=proofs, case_bindings={binding.frame_fingerprint: binding})
    assert resolve_case_bridge(**{**kwargs, "trusted_registry": trusted}) == (case, 1.0)
    with pytest.raises(StaleBinding):
        resolve_case_bridge(**{**kwargs, "trusted_registry": trusted, "image_bytes": b"substituted"})
    altered = replace(trusted, case_bindings={binding.frame_fingerprint: replace(binding, observed_time_s=2.0)})
    with pytest.raises(MissingEvidence):
        resolve_case_bridge(**{**kwargs, "trusted_registry": altered})
    denied_case = replace(case, rights=replace(rights, permitted_uses=()))
    denied_binding = replace(binding, case=denied_case)
    denied_digest = content_fingerprint({"frame_fingerprint": binding.frame_fingerprint,
        "case_content_hash": denied_case.content_hash, "observed_time_s": 1.0,
        "rights_review_receipt_sha256": h("rights")})
    denied_proofs = {**proofs, (denied_digest, "typed_case_bridge", binding.frame_fingerprint):
        TrustedProof("typed_case_bridge", binding.frame_fingerprint, BASE, BASE + timedelta(seconds=900))}
    denied = replace(trusted, proofs=denied_proofs, case_bindings={binding.frame_fingerprint: denied_binding})
    with pytest.raises(PermissionDenied):
        resolve_case_bridge(**{**kwargs, "trusted_registry": denied})
