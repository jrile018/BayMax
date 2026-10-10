# Proposed CPU YuNet boundary

This owned adapter is implemented and tested with generated raster controls, fabricated policy records and a mocked OpenCV API. It has not executed a real model or permitted real photo. C2 shared integration remains subject to root approval of `INTERFACE_V1.md`.

## Inputs and call

```python
from pathlib import Path
from services.casualty.detector import ModelArtifact, detect_case

artifact = ModelArtifact(
    path=Path(verified_cloud_model_path),
    sha256=expected_sha256_from_trusted_ingress_record,
    ingress_reference=trusted_record_binding_revision_to_artifact_hash,
)
run = detect_case(case, exact_recorded_image_bytes, artifact, observed_time_s=simulation_time)
```

The model pin is `3cc26e7f1014a5ee5d74a42acee58bafc9d0a310`, file `face_detection_yunet_2023mar.onnx`. The source URL is fixed in code. Its actual artifact checksum has not been acquired or verified. The caller must supply the independently verified ingress record and expected hash; a user-entered hash/reference alone cannot prove source authenticity.

`CaseRecord` must contain independently verified item-level license/use and applicable adult consent records allowing `face_detection`. The image byte hash must match. Current C1 synthetic records are mock-only and are rejected by this real-call adapter. Pure box-conversion controls remain available without inference. Future actual-model runs on synthetic images require an explicit data-kind contract rather than relabeling actual calls as mocks.

JPEG/PNG only; one raster; encoded size at most 16 MiB; recorded/parsed dimensions must agree; at most 16 million pixels. Rotated EXIF orientation is rejected. Ingress must normalize orientation before computing its image hash and annotation coordinates. Display/review must use that same raw raster. OpenCV decodes BGR with `IMREAD_IGNORE_ORIENTATION`; landmarks are discarded.

Model bytes are bounded to 16 MiB and checked against the expected checksum. OpenCV receives a private read-only temporary copy of those exact bytes, preventing the original path from changing between hashing and loading. The temporary artifact is removed on success or failure. Dependencies are imported lazily; this adapter does not install or download anything.

## Outputs and failure states

`DetectorRun` records immutable `DetectionResult`, artifact SHA256, pinned source URL, trusted ingress reference, runtime version, `YuNetSettings`, CPU device and raw-raster orientation convention. Face boxes are normalized XYXY, scores remain uncalibrated. No injury, identity, severity or medical priority is inferred.

- Successful nonempty model output: `localized`.
- Successful empty model output: `no_face`; human-confirmed authored exercise need remains available through the broker.
- `DetectorUnavailable`: missing/unsupported runtime or model file. No inference observation is produced.
- `DetectorFailure`: decode, model call or malformed output failure. No valid observation is produced; never translate this into `no_face`.
- `ValueError`: missing recorded permission/consent, swapped bytes, unverified model hash, invalid header/orientation, configuration or typed inputs.

YuNet rows must contain exactly 15 finite numeric columns: XYWH at 0–3, five keypoint pairs at 4–13, uncalibrated score at 14. Partly outside boxes are clipped to the raw raster. Nonpositive/nonintersecting boxes, malformed rows, nonfinite values, excessive rows and scores outside declared settings fail the whole result.

Default predeclared settings: score threshold 0.9, NMS threshold 0.3, top-k 50, two CPU threads. The effective float32 score/NMS thresholds are also retained in the run record; score filtering compares against the float32 boundary used by OpenCV. The detect return must be integer 1 before either localized or no-face output is accepted; in the audited 4.x source a normal empty result still returns 1, while empty input returns 0. The backend is `DNN_BACKEND_OPENCV`, target `DNN_TARGET_CPU`; no Torch/GPU fallback exists. `setNumThreads` is process-global, so the root service must serialize/configure this process consistently when integrating it. Actual compatibility, latency and accuracy remain unmeasured.

## Required proof before actual use

Root supplies approved photo bytes plus item-level permission/consent/annotation evidence, the trusted model revision-to-checksum record and compatible OpenCV runtime ingress. Run the actual model on the supplied cloud with the approved lease/runtime policy, retain raw/annotated observations and matched localization TP/FP/FN evidence including no-face/occlusion cases, then review the result. Current tests and scripted C1 trace cannot establish those gates.

## Primary API sources

- [OpenCV FaceDetectorYN](https://docs.opencv.org/doc/doxygen/html/df/d20/classcv_1_1FaceDetectorYN.html)
- [Pinned YuNet files](https://huggingface.co/opencv/face_detection_yunet/tree/3cc26e7f1014a5ee5d74a42acee58bafc9d0a310)
- [OpenCV detector implementation and return semantics](https://github.com/opencv/opencv/blob/4.x/modules/objdetect/src/face_detect.cpp)
- [Official OpenCV model wrapper](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/yunet.py)
- [Official HF CPU demo](https://huggingface.co/spaces/opencv/face_detection_yunet/blob/main/app.py)

These sources establish the adapter API design, not execution or permission for any training/photo data.
