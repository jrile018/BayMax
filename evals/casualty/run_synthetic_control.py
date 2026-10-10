"""One-shot CPU YuNet run on a pinned Commons synthetic montage.

Run from repository root with isolated OpenCV runtime on PYTHONPATH. No case,
triage, real-person photo, or published image is produced.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json

import numpy as np
from PIL import Image, ImageOps

from evals.casualty.synthetic_control import (
    IMAGE_SHA256, MODEL_SHA256, NMS_THRESHOLD, SCORE_THRESHOLD, SOURCE_URL,
    TOP_K, validate_montage_boxes,
)
from services.casualty.detector import MODEL_REVISION, normalize_yunet_rows

ROOT = Path(__file__).resolve().parents[2]
IMAGE = ROOT / "artifacts/casualty/assets/artbreeder-example-portraits.jpg"
MODEL = ROOT / "artifacts/casualty/assets/face_detection_yunet_2023mar.onnx"
OUTPUT = ROOT / "artifacts/casualty/review/synthetic-control-v1.json"


def checked_bytes(path: Path, expected: str, maximum: int) -> bytes:
    data = path.read_bytes()
    if not data or len(data) > maximum or sha256(data).hexdigest() != expected:
        raise ValueError(f"pinned asset unavailable or mismatched: {path.name}")
    return data


def decode_verified_image(image_bytes: bytes) -> np.ndarray:
    """Decode the exact bytes already checked against the pinned source hash."""
    with Image.open(BytesIO(image_bytes)) as raw:
        if raw.format != "JPEG" or raw.size != (1024, 512) or raw.getexif().get(274, 1) != 1:
            raise ValueError("unexpected synthetic image format, dimensions or orientation")
        upright = ImageOps.exif_transpose(raw).convert("RGB")
        return np.asarray(upright, dtype=np.uint8)[:, :, ::-1].copy()


def main() -> None:
    import cv2 as cv  # optional isolated runtime; pure controls need no OpenCV
    image_bytes = checked_bytes(IMAGE, IMAGE_SHA256, 2_000_000)
    model_bytes = checked_bytes(MODEL, MODEL_SHA256, 16_000_000)
    bgr = decode_verified_image(image_bytes)
    cv.setNumThreads(2)
    with TemporaryDirectory(prefix="synthetic-control-", dir=OUTPUT.parent) as directory:
        private_model = Path(directory) / "yunet.onnx"
        private_model.write_bytes(model_bytes)
        private_model.chmod(0o400)
        detector = cv.FaceDetectorYN.create(
            model=str(private_model), config="", input_size=(1024, 512),
            score_threshold=SCORE_THRESHOLD, nms_threshold=NMS_THRESHOLD,
            top_k=TOP_K, backend_id=cv.dnn.DNN_BACKEND_OPENCV,
            target_id=cv.dnn.DNN_TARGET_CPU,
        )
        retval, rows = detector.detect(bgr)
    if isinstance(retval, bool) or retval != 1:
        raise ValueError("CPU YuNet call did not succeed")
    boxes = normalize_yunet_rows(rows, width=1024, height=512)
    cells = validate_montage_boxes(boxes)
    report = {
        "schema_version": "casualty-synthetic-control-v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_url": SOURCE_URL,
        "source_image_sha256": IMAGE_SHA256,
        "source_license": "Commons CC0/PD-algorithm; derivative-work caveat applies",
        "model_revision": MODEL_REVISION,
        "model_sha256": MODEL_SHA256,
        "runtime_version": cv.__version__,
        "device": "cpu",
        "cpu_threads": cv.getNumThreads(),
        "score_threshold": SCORE_THRESHOLD,
        "nms_threshold": NMS_THRESHOLD,
        "top_k": TOP_K,
        "face_box_count": len(boxes),
        "occupied_cells": list(cells),
        "normalized_boxes": [asdict(box) for box in boxes],
        "image_kind": "AI-generated illustrated montage; selected after two misses",
        "interpretation": "exploratory synthetic positive control only",
        "photo_of_person_processed": False,
        "case_pipeline_exercised": False,
        "real_photo_accuracy_claim": False,
        "clinical_claim": False,
    }
    with OUTPUT.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write("\n")
    print(json.dumps({"report": str(OUTPUT), "face_box_count": len(boxes), "occupied_cells": cells}))


if __name__ == "__main__":
    main()
