"""Scripted C1 proof, not real model inference, actual human approval or shared dispatch."""
from dataclasses import asdict, replace
import argparse
import json
from pathlib import Path
from .contracts import CaseRecord, RightsManifest, ImageRecord, ExerciseNeed, FaceBox, DetectionResult, verify_image
from .broker import CaseBroker, CandidateEvidence
from evals.casualty.localization import localization_counts, aggregate


def load_fixture() -> tuple[CaseRecord,FaceBox]:
    root=Path(__file__).resolve().parents[2]
    raw=json.loads((root/'fixtures/casualty/case-001.json').read_text())
    rights=RightsManifest(**{**raw['rights'],'permitted_uses':tuple(raw['rights']['permitted_uses'])})
    case=CaseRecord(raw['case_id'],rights,ImageRecord(**raw['image']),ExerciseNeed(**raw['exercise_need']))
    verify_image(case,(root/case.image.image_reference).read_bytes(),'display')
    return case,FaceBox(**raw['face_box'])


def run_demo(output: Path) -> None:
    case,face=load_fixture()
    broker=CaseBroker()
    result=DetectionResult(case.case_id,case.image.sha256,'localized',(face,),
        'synthetic-box-control','fixture-v1','mock_fixture',5,'Hand-authored geometric control; no inference')
    cue=CandidateEvidence('cue-001','moulage_mark',0,'fixture:drawn-red-stroke','fixture_annotation')
    p=broker.submit(case,result,(cue,),created_time_s=7)
    r=broker.review(p.proposal_id,reviewer_id='scripted-trainee-001',decision='accepted',
        confirmed_evidence=('cue-001',),confirm_exercise_need=True,reviewed_time_s=8)
    request=broker.export_request(r)
    absent=replace(result,status='no_face',boxes=(),observed_time_s=9)
    p2=broker.submit(case,absent,(),created_time_s=10)
    r2=broker.review(p2.proposal_id,reviewer_id='scripted-trainee-001',decision='accepted',
        confirm_exercise_need=True,reviewed_time_s=11)
    request2=broker.export_request(r2)
    counts=aggregate((localization_counts((face,),(face,)), localization_counts((face,),()),localization_counts((),(face,))))
    trace={'schema_version':'casualty-c1-v1','data_kind':'synthetic_geometric_control',
        'review_actor_kind':'scripted_demo_calls','case':asdict(case),'case_hash':case.content_hash,
        'real_detector_status':'pending','actual_photo_status':'pending_rights_and_bytes',
        'clinical_validation_status':'unavailable','integration_status':'pending_root_adapter',
        'localized_review':{'proposal':asdict(p),'receipt':asdict(r),'request':asdict(request)},
        'no_face_review':{'proposal':asdict(p2),'receipt':asdict(r2),'request':asdict(request2)},
        'unique_need_keys':len({request.idempotency_key,request2.idempotency_key}),
        'control_evaluation':{'counts':asdict(counts),'precision':counts.precision,'recall':counts.recall,
            'mean_matched_iou':counts.mean_matched_iou,'iou_threshold':.5,'performance_claim':'harness_geometry_only'},
        'learning_debrief':{'urgency_source':request.need_provenance,
            'detector_miss_effect':'visual_abstention_does_not_suppress_explicit_exercise_need',
            'service_outcome':'pending_shared_routing_and_ledger','learning_measurement':'not_yet_measured'}}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(trace,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    run_demo(parser.parse_args().output)
