"""Rights-gated CPU YuNet adapter; no imagery-derived triage or identity matching.

A successful empty model call is no_face. Unavailable runtime/assets and failed
calls raise distinct exceptions and must never be presented as no_face evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
import importlib
from itertools import islice
import math
from numbers import Integral, Real
from pathlib import Path
import struct
import tempfile
import warnings

from .contracts import (CaseRecord, DetectionResult, FaceBox, image_hash,
                        number, text, validate_detection, verify_image)

MODEL_REVISION = "3cc26e7f1014a5ee5d74a42acee58bafc9d0a310"
MODEL_URL = ("https://huggingface.co/opencv/face_detection_yunet/resolve/"
             + MODEL_REVISION + "/face_detection_yunet_2023mar.onnx")
MAX_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024


class DetectorUnavailable(RuntimeError):
    """No inference: verified assets or compatible runtime are unavailable."""


class DetectorFailure(RuntimeError):
    """Decode/model call/output failed; no valid face observation is emitted."""


@dataclass(frozen=True)
class ModelArtifact:
    path: Path
    sha256: str
    ingress_reference: str
    revision: str = MODEL_REVISION

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise ValueError("model path must be a Path")
        image_hash(self.sha256)
        text(self.ingress_reference, "ingress_reference")
        if self.revision != MODEL_REVISION:
            raise ValueError("model revision must match the audited YuNet pin")


def _float32(value: float) -> float:
    """OpenCV thresholds are C++ float; compare/record that effective value."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


@dataclass(frozen=True)
class YuNetSettings:
    score_threshold: float = .9
    nms_threshold: float = .3
    top_k: int = 50
    cpu_threads: int = 2

    def __post_init__(self) -> None:
        for name in ("score_threshold", "nms_threshold"):
            value = getattr(self, name)
            number(value, name, 0, 1)
            if _float32(value) <= 0:
                raise ValueError(f"{name} must remain positive as float32")
        if type(self.top_k) is not int or not 1 <= self.top_k <= 100:
            raise ValueError("top_k must be an integer from 1 to 100")
        if type(self.cpu_threads) is not int or not 1 <= self.cpu_threads <= 2:
            raise ValueError("cpu_threads must be one or two")


@dataclass(frozen=True)
class DetectorRun:
    detection: DetectionResult
    model_sha256: str
    model_source: str
    ingress_reference: str
    runtime_version: str
    settings: YuNetSettings
    device: str = "cpu"
    orientation: str = "raw_raster_ignore_exif"
    effective_score_threshold: float = field(init=False)
    effective_nms_threshold: float = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.detection, DetectionResult) or not isinstance(self.settings, YuNetSettings):
            raise ValueError("typed detection and settings required")
        image_hash(self.model_sha256)
        object.__setattr__(self, "effective_score_threshold", _float32(self.settings.score_threshold))
        object.__setattr__(self, "effective_nms_threshold", _float32(self.settings.nms_threshold))
        if self.model_source != MODEL_URL or self.detection.model_revision != MODEL_REVISION:
            raise ValueError("run must bind the pinned model")
        for name in ("ingress_reference", "runtime_version"):
            text(getattr(self, name), name)
        if self.device != "cpu" or self.orientation != "raw_raster_ignore_exif":
            raise ValueError("unsupported device or orientation")


def _finite_real(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("YuNet columns must be numeric, not booleans or strings")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("YuNet column outside finite float range") from exc
    if not math.isfinite(result):
        raise ValueError("YuNet columns must be finite")
    return result


def normalize_yunet_rows(rows: object, *, width: int, height: int) -> tuple[FaceBox, ...]:
    """Convert N x 15 XYWH/landmark/score rows, clipping only partial boxes.

    Landmarks are validated then discarded. Malformed rows invalidate the whole
    result; only a successful empty output may represent no detected face.
    """
    for dimension in (width, height):
        if type(dimension) is not int or not 1 <= dimension <= 32768:
            raise ValueError("dimensions must be positive bounded integers")
    if rows is None:
        return ()
    shape = getattr(rows, "shape", None)
    if shape is not None and (not isinstance(shape, tuple) or len(shape) != 2 or shape[1] != 15):
        raise ValueError("YuNet output shape must be N x 15, including empty arrays")
    if isinstance(rows, (str, bytes)):
        raise ValueError("YuNet output must be rows")
    try:
        bounded = tuple(islice(iter(rows), 101))
    except TypeError as exc:
        raise ValueError("YuNet output must be iterable rows") from exc
    if len(bounded) > 100:
        raise ValueError("too many YuNet output rows")
    boxes = []
    for row in bounded:
        try:
            values = tuple(islice(iter(row), 16))
        except TypeError as exc:
            raise ValueError("YuNet output row must have 15 columns") from exc
        if len(values) != 15:
            raise ValueError("YuNet output row must have 15 columns")
        values = tuple(_finite_real(value) for value in values)
        x, y, w, h = values[:4]
        if w <= 0 or h <= 0 or not math.isfinite(x + w) or not math.isfinite(y + h):
            raise ValueError("YuNet box must have finite positive pixel dimensions")
        x1, y1 = max(0., x), max(0., y)
        x2, y2 = min(float(width), x + w), min(float(height), y + h)
        if x1 >= x2 or y1 >= y2:
            raise ValueError("YuNet box must intersect the image")
        boxes.append(FaceBox(x1 / width, y1 / height, x2 / width, y2 / height, values[14]))
    return tuple(boxes)


def _validate_raster(case: CaseRecord, data: bytes) -> None:
    """Check header dimensions/format/orientation before OpenCV allocates pixels."""
    if len(data) > MAX_BYTES or case.image.width * case.image.height > MAX_PIXELS:
        raise ValueError("image exceeds bounded raster budget")
    try:
        image_module = importlib.import_module("PIL.Image")
    except ImportError as exc:
        raise DetectorUnavailable("Pillow header validation runtime unavailable") from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", image_module.DecompressionBombWarning)
            with image_module.open(BytesIO(data)) as image:
                if image.format not in ("JPEG", "PNG") or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("one JPEG or PNG raster required")
                if image.size != (case.image.width, case.image.height):
                    raise ValueError("raster dimensions disagree with image record")
                if image.getexif().get(274, 1) != 1:
                    raise ValueError("orientation must be normalized before recorded ingress")
    except Exception as exc:
        raise ValueError("invalid raster header, dimensions or orientation") from exc


def _verified_model_bytes(artifact: ModelArtifact) -> bytes:
    try:
        if not artifact.path.is_file():
            raise DetectorUnavailable("model artifact unavailable")
        with artifact.path.open("rb") as source:
            data = source.read(MAX_BYTES + 1)
    except OSError as exc:
        raise DetectorUnavailable("model artifact unavailable") from exc
    if not data or len(data) > MAX_BYTES:
        raise ValueError("model artifact exceeds bounded byte budget")
    if sha256(data).hexdigest() != artifact.sha256:
        raise ValueError("model artifact hash mismatch")
    return data


def _load_runtime():
    try:
        cv = importlib.import_module("cv2")
        np = importlib.import_module("numpy")
        # This named API and explicit backend/target are the audited boundary.
        for name in ("create",):
            if not callable(getattr(cv.FaceDetectorYN, name, None)):
                raise AttributeError(name)
        cv.dnn.DNN_BACKEND_OPENCV
        cv.dnn.DNN_TARGET_CPU
        cv.IMREAD_COLOR
        cv.IMREAD_IGNORE_ORIENTATION
        text(cv.__version__, "OpenCV runtime version")
    except (ImportError, AttributeError, ValueError) as exc:
        raise DetectorUnavailable("compatible OpenCV/NumPy CPU runtime unavailable") from exc
    return cv, np


def detect_case(case: CaseRecord, image_bytes: bytes, artifact: ModelArtifact, *,
                observed_time_s: float, settings: YuNetSettings = YuNetSettings()) -> DetectorRun:
    """Call YuNet on exact verified bytes; root owns the truth of ingress records.

    Current C1 synthetic controls remain mock-only. Actual-model synthetic runs
    require a later explicit data-kind contract. No dependency/asset is fetched.
    """
    if not isinstance(case, CaseRecord) or not isinstance(artifact, ModelArtifact) or not isinstance(settings, YuNetSettings):
        raise ValueError("typed case, artifact and settings required")
    verify_image(case, image_bytes, "face_detection")
    if case.rights.source_kind == "synthetic":
        raise ValueError("synthetic controls require explicit mock fixture provenance")
    number(observed_time_s, "observed_time_s")
    _validate_raster(case, image_bytes)
    model_bytes = _verified_model_bytes(artifact)
    cv, np = _load_runtime()
    try:
        cv.setNumThreads(settings.cpu_threads)
        image = cv.imdecode(np.frombuffer(image_bytes, dtype=np.uint8),
                            cv.IMREAD_COLOR | cv.IMREAD_IGNORE_ORIENTATION)
        if (not isinstance(image, np.ndarray) or image.ndim != 3 or image.dtype != np.uint8
                or image.shape != (case.image.height, case.image.width, 3)):
            raise DetectorFailure("OpenCV decode failed or dimensions disagree")
    except DetectorFailure:
        raise
    except Exception as exc:
        raise DetectorFailure("OpenCV decode failed") from exc
    # Hash/load binding: OpenCV gets a private copy of these exact hashed bytes,
    # not the input path that could change after verification. Always clean up.
    runtime_dir = Path(__file__).resolve().parents[2] / "artifacts/casualty/runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="yunet-", dir=runtime_dir) as temporary:
            verified_path = Path(temporary) / "verified.onnx"
            verified_path.write_bytes(model_bytes)
            verified_path.chmod(0o400)
            detector = cv.FaceDetectorYN.create(
                model=str(verified_path), config="", input_size=(case.image.width, case.image.height),
                score_threshold=settings.score_threshold, nms_threshold=settings.nms_threshold,
                top_k=settings.top_k, backend_id=cv.dnn.DNN_BACKEND_OPENCV,
                target_id=cv.dnn.DNN_TARGET_CPU)
            detector.setInputSize((case.image.width, case.image.height))
            retval, rows = detector.detect(image)
            if isinstance(retval, bool) or not isinstance(retval, Integral) or retval != 1:
                raise DetectorFailure("YuNet call did not report successful inference")
            try:
                boxes = normalize_yunet_rows(rows, width=case.image.width, height=case.image.height)
            except (ValueError, TypeError, OverflowError) as exc:
                raise DetectorFailure("malformed YuNet output") from exc
            if len(boxes) > settings.top_k or any(box.score < _float32(settings.score_threshold) for box in boxes):
                raise DetectorFailure("YuNet output violates declared thresholds")
    except DetectorFailure:
        raise
    except Exception as exc:
        raise DetectorFailure("YuNet CPU model call failed") from exc
    result = DetectionResult(case_id=case.case_id, image_sha256=case.image.sha256,
        status="localized" if boxes else "no_face", boxes=boxes, provider="opencv-yunet-cpu",
        model_revision=artifact.revision, provenance="actual_detector", observed_time_s=observed_time_s,
        detail="CPU face localization only; score uncalibrated; no injury or identity claim")
    validate_detection(case, result)
    return DetectorRun(result, artifact.sha256, MODEL_URL, artifact.ingress_reference,
                       cv.__version__, settings)
