"""Casualty v1 boundaries. Scores are uncalibrated; imagery never supplies triage."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
import re


def text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError(f"{name} must be a nonempty bounded string")


def number(value: object, name: str, minimum: float = 0, maximum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} outside range")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, ensure_ascii=False).encode()).hexdigest()


def iso_date(value: object, name: str) -> None:
    text(value, name)
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def image_hash(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("image sha256 must be lowercase hex")


@dataclass(frozen=True)
class RightsManifest:
    source_kind: str
    source_reference: str
    license_id: str
    permitted_uses: tuple[str, ...]
    verification_status: str
    license_evidence: str
    consent_evidence: str | None
    verified_by: str
    verified_at: str
    acquired_at: str
    adult_only: bool

    def __post_init__(self) -> None:
        if self.source_kind not in ("synthetic", "consented_photo", "licensed_photo", "staged_photo"):
            raise ValueError("unsupported source_kind")
        text(self.source_reference, "source_reference")
        text(self.license_id, "license_id")
        iso_date(self.acquired_at, "acquired_at")
        if self.verification_status not in ("pending", "verified", "denied"):
            raise ValueError("unsupported verification_status")
        if not isinstance(self.permitted_uses, tuple) or not set(self.permitted_uses) <= {"display", "face_detection", "evaluation", "public_demo", "video", "dataset_publication", "github_publication"}:
            raise ValueError("permitted_uses must be immutable operation permissions")
        if not isinstance(self.adult_only, bool):
            raise ValueError("adult_only must be boolean")
        for field in (self.license_evidence, self.verified_by, self.verified_at):
            if not isinstance(field, str):
                raise ValueError("verification fields must be strings")
        if self.consent_evidence is not None and not isinstance(self.consent_evidence, str):
            raise ValueError("consent_evidence must be a reference or null")

    def require(self, purpose: str) -> None:
        """Validate recorded permission; an external rights reviewer must verify its truth."""
        if purpose not in {"display", "face_detection", "evaluation", "public_demo", "video", "dataset_publication", "github_publication"} or purpose not in self.permitted_uses:
            raise ValueError(f"missing {purpose} permission")
        if self.verification_status != "verified":
            raise ValueError("rights not verified")
        text(self.license_evidence, "license_evidence")
        text(self.verified_by, "verified_by")
        iso_date(self.verified_at, "verified_at")
        if self.source_kind != "synthetic":
            if not self.adult_only:
                raise ValueError("adult-only consent required")
            text(self.consent_evidence, "consent_evidence")


@dataclass(frozen=True)
class ImageRecord:
    image_reference: str
    sha256: str
    width: int
    height: int
    annotation_reference: str
    annotation_author: str
    annotation_date: str

    def __post_init__(self) -> None:
        text(self.image_reference, "image_reference")
        image_hash(self.sha256)
        for name in ("width", "height"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 32768:
                raise ValueError(f"{name} must be an integer image dimension")
        text(self.annotation_reference, "annotation_reference")
        text(self.annotation_author, "annotation_author")
        iso_date(self.annotation_date, "annotation_date")


@dataclass(frozen=True)
class ExerciseNeed:
    request_id: str
    origin_node: str
    destination_node: str
    persons: int
    urgency: str
    source_reference: str

    def __post_init__(self) -> None:
        for name in ("request_id", "origin_node", "destination_node", "source_reference"):
            text(getattr(self, name), name)
        if type(self.persons) is not int or not 1 <= self.persons <= 100:
            raise ValueError("persons must be an explicit integer from 1 to 100")
        if self.urgency not in ("urgent", "routine", "unknown"):
            raise ValueError("urgency must be authored exercise metadata")


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    rights: RightsManifest
    image: ImageRecord
    exercise_need: ExerciseNeed | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or re.fullmatch(r"npc-case-[a-z0-9-]{1,48}", self.case_id) is None:
            raise ValueError("case_id must be an opaque npc-case identifier")
        if not isinstance(self.rights, RightsManifest) or not isinstance(self.image, ImageRecord):
            raise ValueError("typed rights and image records required")
        if self.exercise_need is not None and not isinstance(self.exercise_need, ExerciseNeed):
            raise ValueError("typed exercise_need required")

    @property
    def content_hash(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class FaceBox:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float

    def __post_init__(self) -> None:
        for name in ("x1", "y1", "x2", "y2", "score"):
            number(getattr(self, name), name, 0, 1)
        if self.x1 >= self.x2 or self.y1 >= self.y2:
            raise ValueError("boxes must have positive normalized XYXY area")


@dataclass(frozen=True)
class DetectionResult:
    case_id: str
    image_sha256: str
    status: str
    boxes: tuple[FaceBox, ...]
    provider: str
    model_revision: str
    provenance: str
    observed_time_s: float
    detail: str

    def __post_init__(self) -> None:
        text(self.case_id, "case_id")
        image_hash(self.image_sha256)
        if self.status not in ("localized", "no_face", "occluded", "failed"):
            raise ValueError("unknown detection status")
        if not isinstance(self.boxes, tuple) or len(self.boxes) > 100 or not all(isinstance(b, FaceBox) for b in self.boxes):
            raise ValueError("boxes must be a bounded immutable FaceBox tuple")
        if self.status == "localized" and not self.boxes:
            raise ValueError("localized requires face boxes")
        if self.status in ("no_face", "failed") and self.boxes:
            raise ValueError("no_face/failed cannot carry boxes")
        if self.provenance not in ("mock_fixture", "actual_detector"):
            raise ValueError("unknown detection provenance")
        text(self.provider, "provider")
        text(self.detail, "detail")
        if self.provenance == "actual_detector" and (not isinstance(self.model_revision, str) or re.fullmatch(r"[a-f0-9]{40,64}", self.model_revision) is None):
            raise ValueError("actual detector requires pinned model revision")
        text(self.model_revision, "model_revision")
        number(self.observed_time_s, "observed_time_s")


def verify_image(case: CaseRecord, image_bytes: bytes, purpose: str) -> str:
    case.rights.require(purpose)
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("nonempty immutable image bytes required")
    actual = hashlib.sha256(image_bytes).hexdigest()
    if actual != case.image.sha256:
        raise ValueError("image hash mismatch")
    return actual


def validate_detection(case: CaseRecord, result: DetectionResult) -> None:
    case.rights.require("face_detection")
    if not isinstance(result, DetectionResult):
        raise ValueError("typed detection required")
    if (result.case_id, result.image_sha256) != (case.case_id, case.image.sha256):
        raise ValueError("detection case/image mismatch")
    if case.rights.source_kind == "synthetic" and result.provenance == "actual_detector":
        raise ValueError("synthetic controls require explicit mock fixture provenance")
