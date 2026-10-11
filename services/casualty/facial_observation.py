"""Pure Faces v1 validation and root-trusted private exercise admission.

No detector, runner, camera, authentication, storage or transaction is owned here.
Root constructs TrustedRegistry from independently verified facts, never HTTP JSON.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from types import MappingProxyType

from .facial_codec import InvalidEvidence, canonical_bytes, content_fingerprint, parse_json
from .contracts import CaseRecord, verify_image

VERSION = "faces-live-observation-v1"
SCHEMA_SHA256 = "e9958bb33ed78c66eff53f82e4dffa16e1f11c019e22804f52f9bc6ad584c43d"
_schema_bytes = Path(__file__).with_name("OBSERVATION_V1.schema.json").read_bytes()
if sha256(_schema_bytes).hexdigest() != SCHEMA_SHA256:
    raise RuntimeError("reviewed Faces schema hash mismatch")
SCHEMA = parse_json(_schema_bytes)
KINDS = {s["properties"]["message_kind"]["const"]: s for s in SCHEMA["oneOf"]}
REASONS = {"bruise_like_discoloration": "bruise_like_color_pattern",
           "cut_or_abrasion": "visible_surface_break", "visible_blood": "visible_red_fluid"}
OUTPUT_FIELDS = ("outcome", "assessment_region", "cues", "reason_code")
LOC_FIELDS = ("status", "boxes", "selected_face_index", "reason")


class MissingEvidence(InvalidEvidence):
    """Required independently verified evidence is absent."""


class PermissionDenied(InvalidEvidence):
    """Current purpose, identity or lifetime authority is absent."""


class StaleBinding(InvalidEvidence):
    """Evidence belongs to a superseded capture or frame."""


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if type(value) in (list, tuple):
        return tuple(freeze(v) for v in value)
    return value


SCHEMA = freeze(SCHEMA)
KINDS = MappingProxyType({s["properties"]["message_kind"]["const"]: s for s in SCHEMA["oneOf"]})


def utc(value):
    if type(value) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value) is None:
        raise InvalidEvidence("fixed-millisecond UTC timestamp required")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise InvalidEvidence("invalid UTC timestamp") from exc


def _now(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise InvalidEvidence("timezone-aware UTC now required")
    return value


def _equal(left, right, message="evidence content mismatch"):
    if canonical_bytes(left) != canonical_bytes(right):
        raise InvalidEvidence(message)


def _shape(value, schema):
    if "$ref" in schema:
        return _shape(value, SCHEMA["$defs"][schema["$ref"].split("/")[-1]])
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                _shape(value, option)
                return
            except InvalidEvidence:
                pass
        raise InvalidEvidence("no allowed shape")
    if "const" in schema:
        _equal(value, schema["const"], "constant mismatch")
    if "enum" in schema and not any(canonical_bytes(value) == canonical_bytes(v) for v in schema["enum"]):
        raise InvalidEvidence("unsupported enum value")
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, Mapping) or set(value) != set(schema["required"]):
            raise InvalidEvidence("missing or extra object fields")
        for key, sub in schema["properties"].items():
            _shape(value[key], sub)
    elif kind == "array":
        if type(value) not in (list, tuple) or not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 25000):
            raise InvalidEvidence("array shape/bound mismatch")
        if schema.get("uniqueItems") and len({canonical_bytes(v) for v in value}) != len(value):
            raise InvalidEvidence("duplicate array items")
        for item in value:
            _shape(item, schema["items"])
    elif kind == "string":
        if type(value) is not str or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 1048576):
            raise InvalidEvidence("string shape/bound mismatch")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise InvalidEvidence("string pattern mismatch")
        if schema.get("format") == "date-time":
            utc(value)
    elif kind in ("integer", "number"):
        if type(value) not in ((int,) if kind == "integer" else (int, float)):
            raise InvalidEvidence("numeric shape mismatch")
        if value < schema.get("minimum", -float("inf")) or value > schema.get("maximum", float("inf")):
            raise InvalidEvidence("numeric range mismatch")
    elif kind == "null" and value is not None:
        raise InvalidEvidence("null required")
    elif kind == "boolean" and type(value) is not bool:
        raise InvalidEvidence("boolean required")


def validate_envelope(envelope, kind=None):
    canonical_bytes(envelope)
    if not isinstance(envelope, Mapping) or type(envelope.get("message_kind")) is not str or envelope["message_kind"] not in KINDS:
        raise InvalidEvidence("unknown envelope")
    actual = envelope["message_kind"]
    if kind is not None and actual != kind:
        raise InvalidEvidence("wrong task/message kind")
    _shape(envelope, KINDS[actual])
    return freeze(envelope)


def record_fingerprint(envelope):
    validate_envelope(envelope)
    return content_fingerprint(envelope)


def validate_frame(record):
    canonical_bytes(record)
    _shape(record, SCHEMA["$defs"]["frame"])
    if (record["capture_id"] is None) != (record["capture_revision"] is None):
        raise InvalidEvidence("capture identity and revision must occur together")
    selected = record["capture_id"] is not None
    limit = 12000000 if selected else 2000000
    if record["width"] * record["height"] > limit or (selected and max(record["width"], record["height"]) > 1280):
        raise InvalidEvidence("frame dimensions exceed reviewed intersection")
    return freeze(record)


def frame_fingerprint(frame):
    validate_frame(frame)
    return content_fingerprint(frame)


def _frame_equal(actual, current):
    validate_frame(actual)
    validate_frame(current)
    if canonical_bytes(actual) != canonical_bytes(current):
        raise StaleBinding("full frame/capture binding changed")


def _image_equal(actual, current):
    validate_frame(actual)
    validate_frame(current)
    left = {k: v for k, v in actual.items() if k != "arrival_revision"}
    right = {k: v for k, v in current.items() if k != "arrival_revision"}
    if canonical_bytes(left) != canonical_bytes(right):
        raise StaleBinding("current image/capture identity changed")


def validate_capture_receipt(record, frame):
    canonical_bytes(record)
    _shape(record, SCHEMA["$defs"]["capture_receipt"])
    validate_frame(frame)
    if record["frame_fingerprint"] != frame_fingerprint(frame) or record["normalized_image_sha256"] != frame["image_sha256"] or record["permission_receipt_sha256"] != frame["permission_receipt_sha256"]:
        raise StaleBinding("capture/normalization/frame binding mismatch")
    selected = frame["capture_id"] is not None
    if (record["purpose"], record["storage_kind"]) != (("capture", "private_selected_capture") if selected else ("preview_face_localization", "transient_preview")):
        raise PermissionDenied("wrong capture purpose/storage")
    if not utc(frame["captured_at"]) <= utc(record["accepted_at"]) < utc(record["expires_at"]):
        raise InvalidEvidence("capture time order invalid")
    if not selected and (utc(record["expires_at"]) - utc(frame["captured_at"])).total_seconds() > 2:
        raise InvalidEvidence("preview lifetime exceeds two seconds")
    return freeze(record)


def _box(box):
    _shape(box, SCHEMA["$defs"]["box"])
    if box["x2"] <= box["x1"] or box["y2"] <= box["y1"] or (box["x2"]-box["x1"])*(box["y2"]-box["y1"]) <= 0:
        raise InvalidEvidence("box must have positive representable area")


def _loc_output(output):
    _shape(output, SCHEMA["$defs"]["localization_output"])
    for box in output["boxes"]:
        _box(box)
    status, boxes, index = output["status"], output["boxes"], output["selected_face_index"]
    if status == "localized":
        if len(boxes) != 1 or index != 0 or output["reason"] != "face_localized":
            raise InvalidEvidence("localized requires one selected face")
    else:
        if index is not None:
            raise InvalidEvidence("ambiguous localization cannot select a face")
        if status in ("no_face", "failed") and boxes:
            raise InvalidEvidence("failed/no-face cannot carry boxes")
        if status == "multiple_faces" and len(boxes) < 2:
            raise InvalidEvidence("multiple-face status requires multiple boxes")
        reasons = {"no_face": {"no_face_found"}, "multiple_faces": {"multiple_faces_ambiguous"},
                   "occluded": {"face_occluded", "capture_unusable"}, "failed": {"detector_failed", "capture_unusable"}}
        if output["reason"] not in reasons[status]:
            raise InvalidEvidence("localization reason/status mismatch")


def validate_localization(record, frame):
    canonical_bytes(record)
    _shape(record, SCHEMA["$defs"]["localization"])
    _frame_equal(record["frame"], frame)
    _loc_output({k: record[k] for k in LOC_FIELDS})
    if record["origin"] == "actual_detector" and record["execution_receipt_sha256"] is None:
        raise MissingEvidence("actual localization needs execution proof")
    return freeze(record)


def validate_runner_request(record):
    canonical_bytes(record)
    _shape(record, SCHEMA["$defs"]["runner_request"])
    validate_frame(record["frame"])
    if record["frame"]["capture_id"] is None:
        raise InvalidEvidence("visual assessment requires selected capture")
    if utc(record["deadline_at"]) <= utc(record["frame"]["captured_at"]):
        raise InvalidEvidence("request deadline must follow capture")
    return freeze(record)


def validate_execution_receipt(record, request, *, localization=False):
    canonical_bytes(record)
    definition = "localization_execution_receipt" if localization else "execution_receipt"
    _shape(record, SCHEMA["$defs"][definition])
    request_kind = "localization_request" if localization else "runner_request"
    request = validate_envelope(request, request_kind)
    validate_frame(request["record"]["frame"])
    key = "localization_request_fingerprint" if localization else "runner_request_fingerprint"
    if record[key] != record_fingerprint(request):
        raise InvalidEvidence("execution request fingerprint mismatch")
    _equal(record["artifact"], request["record"]["artifact"], "execution artifact mismatch")
    start, end = utc(record["started_at"]), utc(record["ended_at"])
    if not utc(request["record"]["frame"]["captured_at"]) <= start <= end <= utc(request["record"]["deadline_at"]):
        raise InvalidEvidence("execution time outside request")
    if record["state"] == "completed":
        if record["process_exit_code"] != 0 or record["output"] is None or record["output_sha256"] != content_fingerprint(record["output"]):
            raise InvalidEvidence("completed execution/output digest mismatch")
        if localization:
            _loc_output(record["output"])
    elif record["output"] is not None or record["output_sha256"] is not None:
        raise InvalidEvidence("failed execution cannot certify output")
    return freeze(record)


def _concerns(output, selected):
    _shape(output, SCHEMA["$defs"]["runner_output"])
    region = output["assessment_region"]
    if region is not None:
        _box(region)
        _equal(region, selected, "assessment region differs from selected face")
    if selected is not None and region is None:
        raise InvalidEvidence("usable selected face requires its assessment region")
    ids = set()
    for cue in output["cues"]:
        if cue["cue_id"] in ids or cue["reason_code"] != REASONS[cue["category"]]:
            raise InvalidEvidence("duplicate cue or mismatched category reason")
        ids.add(cue["cue_id"])
        _box(cue["region"])
        if region is None or not (region["x1"] <= cue["region"]["x1"] < cue["region"]["x2"] <= region["x2"] and region["y1"] <= cue["region"]["y1"] < cue["region"]["y2"] <= region["y2"]):
            raise InvalidEvidence("cue outside selected face")
    outcome = output["outcome"]
    if outcome == "possible_visible_concern":
        if region is None or not ids or output["reason_code"] != "supported_visible_cue":
            raise InvalidEvidence("positive requires region and supported cues")
    elif outcome == "no_visible_concern_detected":
        if region is None or ids or output["reason_code"] != "no_supported_cue_in_region":
            raise InvalidEvidence("negative requires selected region and no cues")
    elif ids or output["reason_code"] in ("supported_visible_cue", "no_supported_cue_in_region"):
        raise InvalidEvidence("Unable requires empty cues and abstention reason")


def validate_observation(record, frame, localization):
    canonical_bytes(record)
    _shape(record, SCHEMA["$defs"]["observation"])
    _frame_equal(record["frame"], frame)
    if frame["capture_id"] is None:
        raise InvalidEvidence("observation requires selected capture")
    loc = validate_envelope(localization, "localization")
    validate_localization(loc["record"], frame)
    if record["localization_receipt_sha256"] != record_fingerprint(loc) or record["capture_receipt_sha256"] != loc["record"]["capture_receipt_sha256"]:
        raise InvalidEvidence("observation localization/capture mismatch")
    selected = loc["record"]["boxes"][0] if loc["record"]["status"] == "localized" else None
    _concerns({k: record[k] for k in OUTPUT_FIELDS}, selected)
    if record["origin"] == "actual_evaluated_runner":
        if record["evaluation_receipt_sha256"] is None or record["execution_receipt_sha256"] is None:
            raise MissingEvidence("actual observation needs evaluation and execution")
    elif record["origin"] == "unavailable":
        if record["outcome"] != "unable_to_assess" or record["evaluation_receipt_sha256"] is not None or record["execution_receipt_sha256"] is not None:
            raise InvalidEvidence("unavailable cannot carry actual proof/negative")
    if utc(record["created_at"]) < utc(frame["captured_at"]):
        raise InvalidEvidence("observation predates capture")
    return freeze(record)


@dataclass(frozen=True)
class TrustedProof:
    """Root-verified fact, not a self-authenticating receipt or JSON API."""
    role: str
    subject_fingerprint: str
    issued_at: datetime
    expires_at: datetime
    actor_id: str | None = None


@dataclass(frozen=True)
class EvaluationItem:
    capture_permission_sha256: str
    evaluation_permission_sha256: str
    camera_session_id: str


@dataclass(frozen=True)
class EvaluationLineage:
    permission_manifest_sha256: str
    items: tuple[EvaluationItem, ...]


@dataclass(frozen=True)
class TrustedCaseBinding:
    frame_fingerprint: str
    case: CaseRecord
    observed_time_s: float
    rights_review_receipt_sha256: str


@dataclass(frozen=True)
class TrustedRegistry:
    records: Mapping
    proofs: Mapping
    permission_epochs: Mapping
    evaluation_lineage: Mapping
    current_frames: Mapping
    case_bindings: Mapping

    def __post_init__(self):
        # Snapshot caller state; delayed calls cannot mutate stored JSON in place.
        for name in ("records", "proofs", "permission_epochs", "evaluation_lineage", "current_frames", "case_bindings"):
            object.__setattr__(self, name, freeze(getattr(self, name)))
        for digest, envelope in self.records.items():
            if record_fingerprint(envelope) != digest:
                raise InvalidEvidence("trusted record index digest mismatch")
        for epoch in self.permission_epochs.values():
            if type(epoch) is not int or not 0 <= epoch <= 2**53 - 1:
                raise InvalidEvidence("trusted permission epochs must be safe nonnegative integers")
        for lineage in self.evaluation_lineage.values():
            if not isinstance(lineage, EvaluationLineage) or type(lineage.items) is not tuple or not all(isinstance(item, EvaluationItem) for item in lineage.items):
                raise InvalidEvidence("immutable typed evaluation lineage required")

    def record(self, digest, kind):
        if digest not in self.records:
            raise MissingEvidence("trusted " + kind + " absent")
        return validate_envelope(self.records[digest], kind)

    def proof(self, digest, role, subject, now, actor_id=None):
        proof = self.proofs.get((digest, role, subject))
        if not isinstance(proof, TrustedProof) or proof.role != role or proof.subject_fingerprint != subject or (actor_id is not None and proof.actor_id != actor_id):
            raise MissingEvidence("verified " + role + " binding absent")
        if not _now(proof.issued_at) <= _now(now) < _now(proof.expires_at):
            raise PermissionDenied("verified proof expired/not yet valid")
        return proof


def _registry(registry):
    if not isinstance(registry, TrustedRegistry):
        raise MissingEvidence("root-owned TrustedRegistry required")
    return registry


def _lifetime(record, now, start, ends):
    if not utc(record[start]) <= now < min(utc(record[k]) for k in ends):
        raise PermissionDenied("authority outside lifetime")


def _permission(digest, registry, now, purpose=None):
    envelope = registry.record(digest, "capture_permission")
    p = envelope["record"]
    _lifetime(p, now, "issued_at", ("expires_at", "retention_deadline", "derived_retention_deadline"))
    if (utc(p["expires_at"]) - utc(p["issued_at"])).total_seconds() > 900:
        raise PermissionDenied("camera grant exceeds fifteen minutes")
    if type(registry.permission_epochs.get(digest)) is not int or registry.permission_epochs[digest] != p["withdrawal_epoch"]:
        raise PermissionDenied("permission epoch revoked or absent")
    if purpose is not None and purpose not in p["purposes"]:
        raise PermissionDenied("purpose not granted")
    registry.proof(p["consent_receipt_sha256"], "consent", digest, now, p["actor_id"])
    registry.proof(p["rights_review_receipt_sha256"], "capture_rights", digest, now)
    return p


def _capture(frame, capture_digest, registry, now, purpose, *, current_frame=None):
    validate_frame(frame)
    current_frame = frame if current_frame is None else current_frame
    validate_frame(current_frame)
    _image_equal(frame, current_frame)
    key = (frame["camera_session_id"], frame["arrival_id"])
    if registry.current_frames.get(key) != frame_fingerprint(current_frame):
        raise StaleBinding("root current frame does not match")
    p = _permission(frame["permission_receipt_sha256"], registry, now, purpose)
    if (p["camera_session_id"], p["arrival_id"]) != key:
        raise PermissionDenied("permission session/arrival mismatch")
    receipt = registry.record(capture_digest, "capture_receipt")
    c = validate_capture_receipt(receipt["record"], frame)
    _lifetime(c, now, "accepted_at", ("expires_at",))
    if c["purpose"] not in p["purposes"]:
        raise PermissionDenied("capture receipt's own purpose not granted")
    if utc(c["expires_at"]) > min(utc(p[k]) for k in ("expires_at", "retention_deadline", "derived_retention_deadline")):
        raise PermissionDenied("capture lifetime exceeds its origin grant")
    if c["withdrawal_epoch"] != p["withdrawal_epoch"] or utc(frame["captured_at"]) < utc(p["issued_at"]):
        raise PermissionDenied("capture permission epoch/time mismatch")
    registry.proof(c["issuer_identity_receipt_sha256"], "capture_issuer", capture_digest, now)
    registry.proof(c["normalization_manifest_sha256"], "normalization", frame_fingerprint(frame), now)
    return p


def _evaluation(digest, artifact, registry, now, localization=False, categories=(), executed_at=None):
    kind = "localization_evaluation_receipt" if localization else "evaluation_receipt"
    e = registry.record(digest, kind)["record"]
    _equal(e["artifact"], artifact, "evaluation artifact mismatch")
    if e["decision"] != "accepted_for_staged_demo" or utc(e["evaluated_at"]) > now:
        raise MissingEvidence("accepted evaluation absent")
    if executed_at is not None and utc(e["evaluated_at"]) > executed_at:
        raise InvalidEvidence("execution predates accepted task evaluation")
    if not localization and not set(categories) <= set(e["categories"]):
        raise MissingEvidence("requested category not evaluated")
    registry.proof(e["review_receipt_sha256"], "evaluation_review", digest, now)
    for field in ("plan_sha256", "dataset_manifest_sha256", "split_manifest_sha256", "metrics_sha256", "evaluation_permission_manifest_sha256"):
        registry.proof(e[field], field, digest, now)
    lineage = registry.evaluation_lineage.get(digest)
    if not isinstance(lineage, EvaluationLineage) or lineage.permission_manifest_sha256 != e["evaluation_permission_manifest_sha256"] or not lineage.items:
        raise MissingEvidence("complete independently verified evaluation lineage absent")
    for item in lineage.items:
        if not isinstance(item, EvaluationItem):
            raise InvalidEvidence("typed evaluation item required")
        p = _permission(item.capture_permission_sha256, registry, now)
        ep = registry.record(item.evaluation_permission_sha256, "evaluation_permission")["record"]
        if p["camera_session_id"] != item.camera_session_id or item.camera_session_id not in ep["camera_session_ids"]:
            raise PermissionDenied("evaluation item session mismatch")
        _lifetime(ep, now, "issued_at", ("expires_at", "media_retention_deadline", "derived_retention_deadline"))
        evaluated = utc(e["evaluated_at"])
        _lifetime(p, evaluated, "issued_at", ("expires_at", "retention_deadline", "derived_retention_deadline"))
        _lifetime(ep, evaluated, "issued_at", ("expires_at", "media_retention_deadline", "derived_retention_deadline"))
        if registry.permission_epochs.get(item.evaluation_permission_sha256) != ep["withdrawal_epoch"]:
            raise PermissionDenied("evaluation permission withdrawn")
        if not {"heldout_evaluation", "private_report_retention"} <= set(ep["purposes"]):
            raise PermissionDenied("dedicated evaluation purposes absent")
        registry.proof(ep["consent_receipt_sha256"], "evaluation_consent", item.evaluation_permission_sha256, now)
        registry.proof(ep["rights_review_receipt_sha256"], "evaluation_rights", item.evaluation_permission_sha256, now)
        registry.proof(ep["issuer_identity_receipt_sha256"], "evaluation_permission_issuer", item.evaluation_permission_sha256, now)
    return e


def _execution(digest, registry, now, localization=False):
    kind = "localization_execution_receipt" if localization else "execution_receipt"
    envelope = registry.record(digest, kind)
    r = envelope["record"]
    request_key = "localization_request_fingerprint" if localization else "runner_request_fingerprint"
    request_kind = "localization_request" if localization else "runner_request"
    request = registry.record(r[request_key], request_kind)
    validate_execution_receipt(r, request, localization=localization)
    capture = registry.record(request["record"]["capture_receipt_sha256"], "capture_receipt")["record"]
    validate_capture_receipt(capture, request["record"]["frame"])
    if utc(r["started_at"]) < utc(capture["accepted_at"]):
        raise InvalidEvidence("execution precedes accepted normalization/capture")
    expected_origin = "actual_detector" if localization else "actual_visual_runner"
    if r["origin"] != expected_origin or r["state"] != "completed" or utc(r["ended_at"]) > now:
        raise MissingEvidence("genuine completed execution absent")
    if not now < utc(request["record"]["deadline_at"]):
        raise PermissionDenied("request admission deadline expired")
    registry.proof(r["issuer_identity_receipt_sha256"], "detector_issuer" if localization else "visual_issuer", digest, now)
    registry.proof(r["runtime_log_sha256"], "runtime_log", digest, now)
    return r, request["record"]


def admit_localization(localization, *, current_frame, trusted_registry, now):
    registry, now = _registry(trusted_registry), _now(now)
    envelope = validate_envelope(localization, "localization")
    loc = validate_localization(envelope["record"], current_frame)
    _equal(registry.record(record_fingerprint(envelope), "localization"), envelope)
    purpose = "visual_assessment" if current_frame["capture_id"] is not None else "preview_face_localization"
    _capture(current_frame, loc["capture_receipt_sha256"], registry, now, purpose)
    if loc["origin"] != "actual_detector":
        raise MissingEvidence("fixture localization is not genuine evidence")
    execution, request = _execution(loc["execution_receipt_sha256"], registry, now, True)
    _frame_equal(request["frame"], current_frame)
    if request["capture_receipt_sha256"] != loc["capture_receipt_sha256"]:
        raise InvalidEvidence("localization capture receipt mismatch")
    _equal(request["artifact"], loc["artifact"])
    _equal(execution["output"], {k: loc[k] for k in LOC_FIELDS})
    _evaluation(request["evaluation_receipt_sha256"], loc["artifact"], registry, now, True,
                executed_at=utc(execution["started_at"]))
    return envelope


def validate_normalized_image(frame, image_bytes):
    validate_frame(frame)
    if type(image_bytes) is not bytes or not image_bytes:
        raise InvalidEvidence("nonempty immutable normalized bytes required")
    if len(image_bytes) > (5 * 1024 * 1024 if frame["capture_id"] is not None else 512 * 1024):
        raise InvalidEvidence("normalized image byte bound exceeded")
    if sha256(image_bytes).hexdigest() != frame["image_sha256"]:
        raise StaleBinding("normalized bytes differ from current frame")
    return frame_fingerprint(frame)


def prepare_visual_request(request, *, current_frame, image_bytes, localization, trusted_registry, now):
    registry, now = _registry(trusted_registry), _now(now)
    envelope = validate_envelope(request, "runner_request")
    r = validate_runner_request(envelope["record"])
    _frame_equal(r["frame"], current_frame)
    _equal(registry.record(record_fingerprint(envelope), "runner_request"), envelope)
    _capture(current_frame, r["capture_receipt_sha256"], registry, now, "visual_assessment")
    validate_normalized_image(current_frame, image_bytes)
    loc = admit_localization(localization, current_frame=current_frame, trusted_registry=registry, now=now)
    if loc["record"]["status"] != "localized":
        raise MissingEvidence("single selected face absent; no visual call permitted")
    if r["localization_receipt_sha256"] != record_fingerprint(loc) or r["capture_receipt_sha256"] != loc["record"]["capture_receipt_sha256"]:
        raise InvalidEvidence("visual request localization/capture mismatch")
    if now >= utc(r["deadline_at"]):
        raise PermissionDenied("request deadline expired")
    _evaluation(r["evaluation_receipt_sha256"], r["artifact"], registry, now, categories=REASONS)
    return envelope


def admit_observation(observation, *, current_frame, localization, trusted_registry, now):
    registry, now = _registry(trusted_registry), _now(now)
    envelope = validate_envelope(observation, "concern_observation")
    o = validate_observation(envelope["record"], current_frame, localization)
    if o["origin"] != "actual_evaluated_runner":
        raise MissingEvidence("fixtures/scripted/unavailable records cannot be admitted")
    _capture(current_frame, o["capture_receipt_sha256"], registry, now, "visual_assessment")
    loc = admit_localization(localization, current_frame=current_frame, trusted_registry=registry, now=now)
    if loc["record"]["status"] != "localized":
        raise MissingEvidence("actual concern run requires a usable selected face")
    execution, request = _execution(o["execution_receipt_sha256"], registry, now)
    localization_execution = registry.record(loc["record"]["execution_receipt_sha256"], "localization_execution_receipt")["record"]
    if utc(execution["started_at"]) < utc(localization_execution["ended_at"]):
        raise InvalidEvidence("visual execution precedes selected localization completion")
    _frame_equal(request["frame"], current_frame)
    if request["capture_receipt_sha256"] != o["capture_receipt_sha256"] or request["localization_receipt_sha256"] != record_fingerprint(loc) or request["evaluation_receipt_sha256"] != o["evaluation_receipt_sha256"]:
        raise InvalidEvidence("observation request lineage mismatch")
    _equal(execution["output"], {k: o[k] for k in OUTPUT_FIELDS}, "full observation output differs from execution")
    categories = REASONS if o["outcome"] == "no_visible_concern_detected" else {c["category"] for c in o["cues"]}
    _evaluation(o["evaluation_receipt_sha256"], execution["artifact"], registry, now, categories=categories,
                executed_at=utc(execution["started_at"]))
    if not utc(execution["ended_at"]) <= utc(o["created_at"]) <= now:
        raise InvalidEvidence("observation creation time outside execution/admission")
    return envelope


def validate_human_review(review, *, current_observation, current_frame, trusted_registry, now):
    registry, now = _registry(trusted_registry), _now(now)
    envelope = validate_envelope(review, "human_review")
    r = envelope["record"]
    observation = validate_envelope(current_observation, "concern_observation")
    o = observation["record"]
    # The writer's workflow revision may advance on assessment; image identity may not.
    _image_equal(o["frame"], current_frame)
    validate_frame(current_frame)
    if r["observation_fingerprint"] != record_fingerprint(observation) or (r["arrival_id"], r["capture_id"], r["capture_revision"]) != (current_frame["arrival_id"], current_frame["capture_id"], current_frame["capture_revision"]):
        raise StaleBinding("review observation/current capture mismatch")
    _equal(registry.record(r["observation_fingerprint"], "concern_observation"), observation)
    if current_frame["arrival_revision"] < o["frame"]["arrival_revision"]:
        raise StaleBinding("review workflow revision precedes assessment")
    _capture(o["frame"], o["capture_receipt_sha256"], registry, now, "human_review", current_frame=current_frame)
    loc = registry.record(o["localization_receipt_sha256"], "localization")
    validate_observation(o, o["frame"], loc)
    registry.proof(r["observation_fingerprint"], "admitted_observation", r["observation_fingerprint"], now)
    execution = registry.record(o["execution_receipt_sha256"], "execution_receipt")["record"]
    _evaluation(o["evaluation_receipt_sha256"], execution["artifact"], registry, now,
                categories=REASONS if o["outcome"] == "no_visible_concern_detected" else {c["category"] for c in o["cues"]})
    detector_execution = registry.record(loc["record"]["execution_receipt_sha256"], "localization_execution_receipt")["record"]
    detector_request = registry.record(detector_execution["localization_request_fingerprint"], "localization_request")["record"]
    _evaluation(detector_request["evaluation_receipt_sha256"], loc["record"]["artifact"], registry, now, True)
    ids = {c["cue_id"] for c in o["cues"]}
    confirmed = set(r["confirmed_cue_ids"])
    if r["decision"] == "confirm_visible_concern":
        if not confirmed or not confirmed <= ids:
            raise InvalidEvidence("confirmation needs existing exact cue IDs")
    elif confirmed:
        raise InvalidEvidence("non-confirming review cannot select cues")
    if not utc(o["created_at"]) <= utc(r["reviewed_at"]) <= now:
        raise InvalidEvidence("review time mismatch")
    registry.proof(r["reviewer_identity_receipt_sha256"], "care_reviewer", record_fingerprint(envelope), now, r["reviewer_id"])
    return envelope


def resolve_case_bridge(*, frame, image_bytes, capture_receipt_sha256, trusted_registry, now):
    """Return root-supplied typed case and time; never fabricate legacy fields."""
    registry, now = _registry(trusted_registry), _now(now)
    permission = _capture(frame, capture_receipt_sha256, registry, now,
                          "visual_assessment" if frame["capture_id"] is not None else "preview_face_localization")
    binding = registry.case_bindings.get(frame_fingerprint(frame))
    if not isinstance(binding, TrustedCaseBinding) or binding.frame_fingerprint != frame_fingerprint(frame) or not isinstance(binding.case, CaseRecord):
        raise MissingEvidence("root-constructed typed Case/time bridge absent")
    if type(binding.observed_time_s) not in (int, float) or binding.observed_time_s < 0:
        raise InvalidEvidence("verified legacy observed time must be finite nonnegative")
    canonical_bytes(binding.observed_time_s)
    case = binding.case
    if case.rights.source_kind not in ("consented_photo", "staged_photo") or case.exercise_need is not None:
        raise PermissionDenied("live bridge requires item-level adult photo without inferred need")
    if (case.image.sha256, case.image.width, case.image.height) != (frame["image_sha256"], frame["width"], frame["height"]):
        raise StaleBinding("typed case image/geometry mismatch")
    if binding.rights_review_receipt_sha256 != permission["rights_review_receipt_sha256"]:
        raise PermissionDenied("case rights receipt differs from capture authority")
    registry.proof(binding.rights_review_receipt_sha256, "capture_rights", frame["permission_receipt_sha256"], now)
    bridge_digest = content_fingerprint({"frame_fingerprint": binding.frame_fingerprint,
        "case_content_hash": case.content_hash, "observed_time_s": binding.observed_time_s,
        "rights_review_receipt_sha256": binding.rights_review_receipt_sha256})
    registry.proof(bridge_digest, "typed_case_bridge", frame_fingerprint(frame), now)
    try:
        case.rights.require("face_detection")
    except ValueError as exc:
        raise PermissionDenied("typed case face_detection rights invalid") from exc
    validate_normalized_image(frame, image_bytes)
    try:
        verify_image(case, image_bytes, "face_detection")
    except ValueError as exc:
        raise InvalidEvidence("typed image/rights verification failed") from exc
    return case, binding.observed_time_s
