"""Adapter controls: generated rasters/fabricated policy records and mocked OpenCV.

These tests do not establish photo permission, actual inference or model accuracy.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
from PIL import Image
import pytest

from services.casualty.tests.test_contracts import case, rights


MODEL_BYTES = b"test-only-model-control-never-real-weights"


def raster(width=100, height=100, orientation=None):
    output = BytesIO()
    image = Image.new("RGB", (width, height), "gray")
    if orientation is None:
        image.save(output, format="PNG")
    else:
        exif = Image.Exif()
        exif[274] = orientation
        image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def control_case(data=None, **changes):
    data = raster() if data is None else data
    base = case()
    values = dict(rights=rights("staged_photo", consent_evidence="test-only:policy-record"),
                  image=replace(base.image, sha256=sha256(data).hexdigest(),
                                image_reference="test-only:generated-raster"))
    values.update(changes)
    return replace(base, **values)


def artifact(tmp_path, **changes):
    from services.casualty.detector import ModelArtifact
    path = tmp_path / "test-only.onnx"
    path.write_bytes(MODEL_BYTES)
    values = dict(path=path, sha256=sha256(MODEL_BYTES).hexdigest(),
                  ingress_reference="test-only:fabricated-ingress-record")
    values.update(changes)
    return ModelArtifact(**values)


def row(x=10, y=20, w=50, h=60, score=.95):
    return [x, y, w, h, *([0] * 10), score]


class FakeCV:
    """Records calls without decoding through OpenCV or loading any model."""
    __version__ = "test-only-runtime"
    IMREAD_COLOR = 1
    IMREAD_IGNORE_ORIENTATION = 128
    dnn = SimpleNamespace(DNN_BACKEND_OPENCV=3, DNN_TARGET_CPU=0)

    def __init__(self, rows):
        self.rows = rows
        self.decoded = np.zeros((100, 100, 3), dtype=np.uint8)
        self.calls = []
        self.error_at = None
        self.FaceDetectorYN = SimpleNamespace(create=self.create)

    def setNumThreads(self, count):
        self.calls.append(("threads", count))

    def imdecode(self, encoded, flags):
        self.calls.append(("decode", bytes(encoded), flags))
        return self.decoded

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        self.loaded_path = Path(kwargs["model"])
        self.loaded_bytes = self.loaded_path.read_bytes()
        if self.error_at == "create":
            raise RuntimeError("test-only create failure")
        return self

    def setInputSize(self, size):
        self.calls.append(("input_size", size))

    def detect(self, image):
        self.calls.append(("detect", image.shape))
        if self.error_at == "detect":
            raise RuntimeError("test-only inference failure")
        return 1, self.rows


def install_fake(monkeypatch, rows):
    fake = FakeCV(rows)
    monkeypatch.setitem(sys.modules, "cv2", fake)
    return fake


def test_pixel_boxes_normalize_xywh_and_keep_uncalibrated_score():
    from services.casualty.detector import normalize_yunet_rows
    boxes = normalize_yunet_rows(np.asarray([row()], dtype=np.float32), width=100, height=100)
    assert (boxes[0].x1, boxes[0].y1, boxes[0].x2, boxes[0].y2) == (.1, .2, .6, .8)
    assert boxes[0].score == pytest.approx(.95)
    assert type(boxes[0].x1) is float


def test_partial_boxes_clip_to_pixel_bounds():
    from services.casualty.detector import normalize_yunet_rows
    boxes = normalize_yunet_rows([row(-10, 20, 40, 100)], width=100, height=100)
    assert (boxes[0].x1, boxes[0].y1, boxes[0].x2, boxes[0].y2) == (0, .2, .3, 1)


@pytest.mark.parametrize("rows", [None, [], np.empty((0, 15))])
def test_successful_empty_output_is_empty(rows):
    from services.casualty.detector import normalize_yunet_rows
    assert normalize_yunet_rows(rows, width=100, height=100) == ()


@pytest.mark.parametrize("rows", [
    [row(w=0)], [row(h=-1)], [row(x=100)], [row(y=-100)],
    [row(x=float("nan"))], [row(score=float("inf"))], [row(score=1.1)],
    [row(score=True)], [row(x="10")], [[0] * 14], [[0] * 16],
    [row(), row(x=-100)], [row(x=1e308, w=1e308)], [row()] * 101,
    [[10, 20, 50, 60, *([float("nan")] * 10), .9]], "not-rows",
])
def test_malformed_output_fails_whole_result(rows):
    from services.casualty.detector import normalize_yunet_rows
    with pytest.raises(ValueError):
        normalize_yunet_rows(rows, width=100, height=100)


@pytest.mark.parametrize("dimension", [True, 0, 1.5, 32769])
def test_normalizer_dimensions_are_strict(dimension):
    from services.casualty.detector import normalize_yunet_rows
    with pytest.raises(ValueError):
        normalize_yunet_rows(None, width=dimension, height=100)


def test_artifact_pin_and_hash_are_not_optional(tmp_path):
    with pytest.raises(ValueError, match="revision"):
        artifact(tmp_path, revision="a" * 40)
    with pytest.raises(ValueError, match="sha256"):
        artifact(tmp_path, sha256="not-a-hash")
    with pytest.raises(ValueError, match="ingress"):
        artifact(tmp_path, ingress_reference="")


def test_rights_and_image_hash_precede_runtime_and_model_access(tmp_path, monkeypatch):
    from services.casualty.detector import detect_case
    fake = install_fake(monkeypatch, [row()])
    data = raster()
    c = control_case(data)
    missing = artifact(tmp_path, path=tmp_path / "absent.onnx")
    for bad_case, image_bytes in [
        (replace(c, rights=replace(c.rights, verification_status="pending")), data),
        (replace(c, rights=replace(c.rights, permitted_uses=("display",))), data),
        (replace(c, rights=replace(c.rights, consent_evidence=None)), data),
        (c, b"swapped"),
    ]:
        with pytest.raises(ValueError):
            detect_case(bad_case, image_bytes, missing, observed_time_s=1)
    assert fake.calls == []


def test_current_synthetic_controls_cannot_claim_actual_detector(tmp_path, monkeypatch):
    from services.casualty.detector import detect_case
    fake = install_fake(monkeypatch, [row()])
    data = raster()
    c = replace(control_case(data), rights=rights())
    with pytest.raises(ValueError, match="synthetic"):
        detect_case(c, data, artifact(tmp_path), observed_time_s=1)
    assert fake.calls == []


def test_missing_weights_are_explicitly_unavailable(tmp_path):
    from services.casualty.detector import detect_case, DetectorUnavailable
    data = raster()
    with pytest.raises(DetectorUnavailable, match="model"):
        detect_case(control_case(data), data, artifact(tmp_path, path=tmp_path / "absent.onnx"), observed_time_s=1)


def test_modified_weights_fail_before_runtime_load(tmp_path, monkeypatch):
    from services.casualty.detector import detect_case
    fake = install_fake(monkeypatch, [row()])
    data = raster()
    model = artifact(tmp_path)
    model.path.write_bytes(b"replacement")
    with pytest.raises(ValueError, match="model.*hash"):
        detect_case(control_case(data), data, model, observed_time_s=1)
    assert fake.calls == []


def test_missing_opencv_is_explicitly_unavailable(tmp_path, monkeypatch):
    import importlib
    from services.casualty.detector import detect_case, DetectorUnavailable
    original = importlib.import_module
    def missing(name, *args, **kwargs):
        if name == "cv2":
            raise ModuleNotFoundError("test-only runtime unavailable")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(importlib, "import_module", missing)
    data = raster()
    with pytest.raises(DetectorUnavailable, match="OpenCV"):
        detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)


def test_cpu_call_binds_verified_bytes_runtime_and_orientation(tmp_path, monkeypatch):
    from services.casualty.detector import detect_case, MODEL_REVISION, MODEL_URL
    fake = install_fake(monkeypatch, [row()])
    data = raster()
    model = artifact(tmp_path)
    run = detect_case(control_case(data), data, model, observed_time_s=2)
    assert run.detection.status == "localized"
    assert run.detection.provenance == "actual_detector"  # mocked call-path control only
    assert run.detection.model_revision == MODEL_REVISION
    assert run.model_sha256 == sha256(MODEL_BYTES).hexdigest()
    assert run.model_source == MODEL_URL
    assert run.ingress_reference == model.ingress_reference
    assert run.runtime_version == "test-only-runtime"
    assert run.device == "cpu"
    assert run.orientation == "raw_raster_ignore_exif"
    assert fake.loaded_bytes == MODEL_BYTES
    assert fake.loaded_path != model.path
    assert not fake.loaded_path.exists()
    create = next(value for name, value, *rest in fake.calls if name == "create")
    assert create["backend_id"] == fake.dnn.DNN_BACKEND_OPENCV
    assert create["target_id"] == fake.dnn.DNN_TARGET_CPU
    assert create["input_size"] == (100, 100)
    assert create["score_threshold"] == .9
    assert create["nms_threshold"] == .3
    assert create["top_k"] == 50
    assert ("threads", 2) in fake.calls
    assert ("input_size", (100, 100)) in fake.calls
    decode = next(call for call in fake.calls if call[0] == "decode")
    assert decode[1:] == (data, fake.IMREAD_COLOR | fake.IMREAD_IGNORE_ORIENTATION)


def test_empty_detection_is_no_face_after_successful_call(tmp_path, monkeypatch):
    from services.casualty.detector import detect_case
    fake = install_fake(monkeypatch, None)
    data = raster()
    run = detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)
    assert run.detection.status == "no_face"
    assert run.detection.boxes == ()
    assert any(call[0] == "detect" for call in fake.calls)


@pytest.mark.parametrize("stage", ["create", "detect"])
def test_runtime_failures_never_become_no_face(tmp_path, monkeypatch, stage):
    from services.casualty.detector import detect_case, DetectorFailure
    fake = install_fake(monkeypatch, [row()])
    fake.error_at = stage
    data = raster()
    with pytest.raises(DetectorFailure):
        detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)
    if hasattr(fake, "loaded_path"):
        assert not fake.loaded_path.exists()


@pytest.mark.parametrize("decoded", [None, np.zeros((90, 100, 3), dtype=np.uint8)])
def test_failed_or_mismatched_decode_cannot_load_model(tmp_path, monkeypatch, decoded):
    from services.casualty.detector import detect_case, DetectorFailure
    fake = install_fake(monkeypatch, [row()])
    fake.decoded = decoded
    data = raster()
    with pytest.raises(DetectorFailure):
        detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)
    assert not any(call[0] == "create" for call in fake.calls)


@pytest.mark.parametrize("data", [b"invalid-raster", raster(width=90), raster(orientation=6)], ids=["invalid", "dimension-mismatch", "rotated-exif"])
def test_bad_raster_dimensions_or_orientation_rejected_before_cv(tmp_path, monkeypatch, data):
    from services.casualty.detector import detect_case
    fake = install_fake(monkeypatch, [row()])
    with pytest.raises(ValueError):
        detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)
    assert fake.calls == []


def test_malformed_inference_output_raises_not_no_face(tmp_path, monkeypatch):
    from services.casualty.detector import detect_case, DetectorFailure
    install_fake(monkeypatch, [row(), row(score=float("nan"))])
    data = raster()
    with pytest.raises(DetectorFailure, match="output"):
        detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)


def test_thresholds_and_cpu_limit_are_recorded_and_strict():
    from services.casualty.detector import YuNetSettings
    for changes in [dict(score_threshold=True), dict(score_threshold=0),
                    dict(nms_threshold=float("nan")), dict(top_k=101),
                    dict(cpu_threads=3), dict(cpu_threads=True)]:
        with pytest.raises(ValueError):
            YuNetSettings(**changes)


def test_float32_threshold_boundary_is_valid(tmp_path, monkeypatch):
    from services.casualty.detector import detect_case
    install_fake(monkeypatch, np.asarray([row(score=.9)], dtype=np.float32))
    data = raster()
    run = detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)
    assert run.detection.status == "localized"
    assert run.effective_score_threshold == float(np.float32(.9))
    assert run.effective_nms_threshold == float(np.float32(.3))


def test_float32_score_below_effective_threshold_is_rejected(tmp_path, monkeypatch):
    from services.casualty.detector import detect_case, DetectorFailure
    score = np.nextafter(np.float32(.9), np.float32(0))
    install_fake(monkeypatch, np.asarray([row(score=score)], dtype=np.float32))
    data = raster()
    with pytest.raises(DetectorFailure, match="threshold"):
        detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)


@pytest.mark.parametrize("rows", [np.empty((0, 14)), np.empty((0, 15, 2))], ids=["wrong-columns", "wrong-rank"])
def test_malformed_empty_array_is_not_valid_no_face(tmp_path, monkeypatch, rows):
    from services.casualty.detector import detect_case, normalize_yunet_rows, DetectorFailure
    with pytest.raises(ValueError, match="shape"):
        normalize_yunet_rows(rows, width=100, height=100)
    install_fake(monkeypatch, rows)
    data = raster()
    with pytest.raises(DetectorFailure, match="output"):
        detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)


@pytest.mark.parametrize("retval", [0, -1, None, True])
def test_unsuccessful_detect_return_is_never_no_face(tmp_path, monkeypatch, retval):
    from services.casualty.detector import detect_case, DetectorFailure
    fake = install_fake(monkeypatch, None)
    fake.detect = lambda image: (retval, None)
    data = raster()
    with pytest.raises(DetectorFailure, match="successful"):
        detect_case(control_case(data), data, artifact(tmp_path), observed_time_s=1)


def test_runtime_directory_failure_has_typed_failure(tmp_path, monkeypatch):
    from services.casualty.detector import detect_case, DetectorFailure
    install_fake(monkeypatch, [row()])
    model = artifact(tmp_path)
    data = raster()
    def denied(*args, **kwargs):
        raise PermissionError("test-only storage denied")
    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(DetectorFailure, match="model call"):
        detect_case(control_case(data), data, model, observed_time_s=1)
