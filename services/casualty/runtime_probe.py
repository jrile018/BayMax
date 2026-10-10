"""CPU compatibility smoke on an author-generated blank raster, never a photo.

No CaseRecord, DetectionResult or broker receipt is emitted. Actual-case rights
and review gates remain in detector.py. Failed forwards retain diagnostic proof.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from numbers import Integral
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter

from .detector import (DetectorFailure, DetectorUnavailable, ModelArtifact, MODEL_URL,
                       YuNetSettings, _float32, _load_runtime, _verified_model_bytes,
                       normalize_yunet_rows)

YUNET_ARTIFACT_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"


class RuntimeProbeFailure(DetectorFailure):
    """Fail-closed diagnostic with completed observations and bounded diagnostics."""
    def __init__(self, report: dict):
        super().__init__('CPU runtime probe failed; see retained report')
        self.report = report


def source_provenance() -> dict:
    """Bind this module's clean tracked sources, independently of caller CWD."""
    root = Path(__file__).resolve().parents[2]
    source_paths = ('services/casualty/runtime_probe.py', 'services/casualty/detector.py',
                    'services/casualty/contracts.py')
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args])
    top = Path(git('rev-parse','--show-toplevel').decode().strip()).resolve()
    if top != root:
        raise ValueError('module source repository root mismatch')
    if git('status','--porcelain','--untracked-files=all','--',*source_paths).strip():
        raise ValueError('relevant source must be clean before inference')
    hashes = {}
    for name in source_paths:
        recorded = git('show','HEAD:'+name)
        actual = (root/name).read_bytes()
        if actual != recorded:
            raise ValueError('executed source differs from commit')
        hashes[name] = sha256(actual).hexdigest()
    return {'source_commit':git('rev-parse','HEAD').decode().strip(),
            'relevant_source_clean':True, 'source_sha256':hashes}


def _output_diagnostics(rows) -> dict:
    """Bounded shape/type information without consuming iterator outputs."""
    shape = getattr(rows, 'shape', None)
    result = {'kind':type(rows).__name__, 'shape':list(shape[:4]) if isinstance(shape,tuple) else None,
              'dtype':str(getattr(rows,'dtype',''))[:64], 'first_row_columns':None}
    try:
        result['row_count'] = len(rows)
        if len(rows) and isinstance(rows, (list,tuple)):
            result['first_row_columns'] = len(rows[0])
        elif isinstance(shape,tuple) and len(shape) == 2:
            result['first_row_columns'] = shape[1]
    except TypeError:
        result['row_count'] = None
    return result


def run_cpu_probe(artifact: ModelArtifact) -> dict:
    """Two blank forwards prove runtime/API behavior, not face/photo accuracy."""
    if not isinstance(artifact, ModelArtifact) or artifact.sha256 != YUNET_ARTIFACT_SHA256:
        raise ValueError('probe requires the published pinned model checksum')
    model_bytes = _verified_model_bytes(artifact)
    cv, np = _load_runtime()
    settings = YuNetSettings()
    image = np.zeros((128,128,3),dtype=np.uint8)
    report = {
        'schema_version':'casualty-cpu-runtime-smoke-v1', 'run_status':'running',
        'recorded_at':datetime.now(timezone.utc).isoformat(),
        'input_kind':'generated_zero_raster', 'input_dimensions':[128,128],
        'input_raw_sha256':sha256(image.tobytes()).hexdigest(), 'input_channel_order':'BGR',
        'photo_processed':False, 'case_pipeline_exercised':False, 'device':'cpu',
        'model_revision':artifact.revision, 'model_sha256':artifact.sha256,
        'model_source':MODEL_URL, 'ingress_reference':artifact.ingress_reference,
        'runtime_version':cv.__version__, 'numpy_version':np.__version__,
        'python_version':sys.version.split()[0], 'settings':asdict(settings),
        'effective_score_threshold':_float32(settings.score_threshold),
        'effective_nms_threshold':_float32(settings.nms_threshold),
        'runtime_module_origin':getattr(getattr(cv,'__spec__',None),'origin',None),
        'torch_imported':'torch' in sys.modules,
        'forward_calls_attempted':0, 'successful_forward_returns':0,
        'face_box_counts':[], 'normalized_boxes':[], 'output_diagnostics':[],
        'cold_create_and_forward_s':None, 'warm_forward_s':None,
        'timing_scope':'cold:create/input-size/forward/validation; warm:forward/validation; excludes imports/hash/copy',
        'clinical_or_face_accuracy_claim':'none',
        'limitation':'one generated blank control; no real-photo or case/review integration proof',
    }
    phase = 'configuration'
    iteration = None
    try:
        cv.setNumThreads(settings.cpu_threads)
        runtime_dir = Path(__file__).resolve().parents[2] / 'artifacts/casualty/runtime'
        runtime_dir.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='yunet-',dir=runtime_dir) as temporary:
            verified_path = Path(temporary)/'verified.onnx'
            verified_path.write_bytes(model_bytes)
            verified_path.chmod(0o400)
            phase = 'model_create'
            started = perf_counter()
            detector = cv.FaceDetectorYN.create(
                model=str(verified_path), config='', input_size=(128,128),
                score_threshold=settings.score_threshold, nms_threshold=settings.nms_threshold,
                top_k=settings.top_k, backend_id=cv.dnn.DNN_BACKEND_OPENCV,
                target_id=cv.dnn.DNN_TARGET_CPU)
            detector.setInputSize((128,128))
            for iteration in range(2):
                if iteration:
                    started = perf_counter()
                phase = 'forward'
                report['forward_calls_attempted'] += 1
                retval,rows = detector.detect(image)
                phase = 'success_validation'
                report['output_diagnostics'].append(_output_diagnostics(rows))
                if isinstance(retval,bool) or not isinstance(retval,Integral) or retval != 1:
                    raise DetectorFailure('probe forward did not report success')
                report['successful_forward_returns'] += 1
                phase = 'output_validation'
                boxes = normalize_yunet_rows(rows,width=128,height=128)
                if len(boxes)>settings.top_k or any(box.score<_float32(settings.score_threshold) for box in boxes):
                    raise DetectorFailure('probe output violates declared thresholds')
                report['face_box_counts'].append(len(boxes))
                report['normalized_boxes'].append([asdict(box) for box in boxes])
                report['warm_forward_s' if iteration else 'cold_create_and_forward_s'] = perf_counter()-started
    except Exception as exc:
        report.update(run_status='failed', failure_phase=phase, failure_iteration=iteration,
                      failure_kind=type(exc).__name__, no_face_negative_passed=None,
                      actual_model_forward_performed=True if report['successful_forward_returns'] else
                          (None if report['forward_calls_attempted'] else False))
        raise RuntimeProbeFailure(report) from exc
    report.update(run_status='success',actual_model_forward_performed=True,
                  no_face_negative_passed=all(count==0 for count in report['face_box_counts']))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--ingress-reference',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('each actual run requires a new evidence output path')
    provenance = source_provenance()  # before runtime/model work
    artifact = ModelArtifact(args.model,YUNET_ARTIFACT_SHA256,args.ingress_reference)
    failed = False
    with args.output.open('x',encoding='utf-8') as output:
        try:
            result = run_cpu_probe(artifact)
        except RuntimeProbeFailure as exc:
            result = exc.report
            failed = True
        except (ValueError,DetectorUnavailable,DetectorFailure) as exc:
            result = {'schema_version':'casualty-cpu-runtime-smoke-v1','run_status':'failed',
                      'recorded_at':datetime.now(timezone.utc).isoformat(),
                      'failure_phase':'preflight','failure_kind':type(exc).__name__,
                      'actual_model_forward_performed':False,'photo_processed':False,
                      'case_pipeline_exercised':False,'no_face_negative_passed':None}
            failed = True
        result.update(provenance)
        json.dump(result,output,indent=2,allow_nan=False)
        output.write('\n')
    print(json.dumps(result,indent=2,allow_nan=False))
    if failed:
        raise SystemExit(1)


if __name__=='__main__':
    main()
