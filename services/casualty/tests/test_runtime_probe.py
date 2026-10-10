"""Runtime-probe controls use generated zero rasters and fake OpenCV calls."""
from dataclasses import replace
from pathlib import Path
import pytest
from services.casualty.tests.test_detector import artifact, install_fake, MODEL_BYTES, row


def control_artifact(tmp_path, monkeypatch):
    from services.casualty import runtime_probe
    model = artifact(tmp_path)
    # Fixture substitution tests call behavior, not authenticity or actual ML.
    monkeypatch.setattr(runtime_probe, 'YUNET_ARTIFACT_SHA256', model.sha256)
    return model


def test_probe_rejects_unpublished_artifact_hash_before_runtime(tmp_path, monkeypatch):
    from services.casualty.runtime_probe import run_cpu_probe
    fake = install_fake(monkeypatch, None)
    with pytest.raises(ValueError, match='published'):
        run_cpu_probe(artifact(tmp_path))
    assert fake.calls == []


def test_probe_rejects_changed_bytes_before_runtime(tmp_path, monkeypatch):
    from services.casualty.runtime_probe import run_cpu_probe
    fake = install_fake(monkeypatch, None)
    model = control_artifact(tmp_path, monkeypatch)
    model.path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash'):
        run_cpu_probe(model)
    assert fake.calls == []


def test_probe_records_blank_control_and_two_cpu_calls(tmp_path, monkeypatch):
    from services.casualty.runtime_probe import run_cpu_probe
    fake = install_fake(monkeypatch, None)
    result = run_cpu_probe(control_artifact(tmp_path, monkeypatch))
    assert result['input_kind'] == 'generated_zero_raster'
    assert result['input_dimensions'] == [128, 128]
    assert result['actual_model_forward_performed'] is True  # simulated call path only
    assert result['case_pipeline_exercised'] is False
    assert result['photo_processed'] is False
    assert result['device'] == 'cpu'
    assert result['runtime_version'] == 'test-only-runtime'
    assert result['face_box_counts'] == [0, 0]
    assert result['no_face_negative_passed'] is True
    assert result['clinical_or_face_accuracy_claim'] == 'none'
    assert result['cold_create_and_forward_s'] >= 0
    assert result['warm_forward_s'] >= 0
    assert len([call for call in fake.calls if call[0]=='detect']) == 2
    assert ('threads', 2) in fake.calls
    assert fake.loaded_bytes == MODEL_BYTES
    assert not fake.loaded_path.exists()


@pytest.mark.parametrize('rows,retval', [([row(score=float('nan'))],1),(None,0)])
def test_failed_probe_does_not_emit_success_evidence(tmp_path, monkeypatch, rows, retval):
    from services.casualty.runtime_probe import run_cpu_probe
    from services.casualty.detector import DetectorFailure
    fake = install_fake(monkeypatch, rows)
    fake.detect = lambda image: (retval, rows)
    with pytest.raises(DetectorFailure):
        run_cpu_probe(control_artifact(tmp_path, monkeypatch))
    assert not fake.loaded_path.exists()


def test_false_positive_on_blank_is_retained(tmp_path, monkeypatch):
    from services.casualty.runtime_probe import run_cpu_probe
    install_fake(monkeypatch, [row()])
    result = run_cpu_probe(control_artifact(tmp_path, monkeypatch))
    assert result['face_box_counts'] == [1,1]
    assert result['no_face_negative_passed'] is False
    assert len(result['normalized_boxes'][0]) == 1


def test_failed_second_call_retains_first_fp_and_failure_diagnostics(tmp_path, monkeypatch):
    from services.casualty.runtime_probe import run_cpu_probe
    from services.casualty.detector import DetectorFailure
    fake = install_fake(monkeypatch, [row()])
    calls = 0
    def second_failure(image):
        nonlocal calls
        calls += 1
        return (1,[row()]) if calls == 1 else (1,[[0]*14])
    fake.detect = second_failure
    with pytest.raises(DetectorFailure) as captured:
        run_cpu_probe(control_artifact(tmp_path,monkeypatch))
    report = captured.value.report
    assert report['run_status'] == 'failed'
    assert report['failure_phase'] == 'output_validation'
    assert report['failure_iteration'] == 1
    assert report['face_box_counts'] == [1]
    assert len(report['normalized_boxes'][0]) == 1
    assert report['cold_create_and_forward_s'] >= 0
    assert report['warm_forward_s'] is None
    assert report['output_diagnostics'][1]['first_row_columns'] == 14
    assert report['no_face_negative_passed'] is None


def fixture_repository(tmp_path):
    import subprocess
    root=tmp_path/'source-repository'
    source=root/'services'/'casualty'
    source.mkdir(parents=True)
    for name in ('contracts.py','detector.py','runtime_probe.py'):
        (source/name).write_text('test-only tracked source\n')
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
    git('init')
    git('config','user.name','test-fixture')
    git('config','user.email','test-only@example.invalid')
    git('add','services')
    git('commit','-m','Test-only source fixture')
    return root,git('rev-parse','HEAD')


def test_source_provenance_resolves_module_repository_from_other_cwd(tmp_path,monkeypatch):
    from services.casualty import runtime_probe
    root,expected=fixture_repository(tmp_path)
    other=tmp_path/'different-working-directory'
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setattr(runtime_probe,'__file__',str(root/'services/casualty/runtime_probe.py'))
    result=runtime_probe.source_provenance()
    assert result['source_commit']==expected
    assert result['relevant_source_clean'] is True
    assert len(result['source_sha256'])==3


def test_dirty_relevant_source_cannot_claim_clean_commit(tmp_path,monkeypatch):
    from services.casualty import runtime_probe
    root,_=fixture_repository(tmp_path)
    monkeypatch.setattr(runtime_probe,'__file__',str(root/'services/casualty/runtime_probe.py'))
    (root/'services/casualty/detector.py').write_text('modified source\n')
    with pytest.raises(ValueError,match='source'):
        runtime_probe.source_provenance()


def test_cli_failure_writes_retained_json_and_exits_nonzero(tmp_path,monkeypatch):
    import json,sys
    from services.casualty import runtime_probe
    fake=install_fake(monkeypatch,None)
    fake.error_at='detect'
    model=control_artifact(tmp_path,monkeypatch)
    monkeypatch.setattr(runtime_probe,'source_provenance',lambda:{'source_commit':'a'*40,'relevant_source_clean':True,'source_sha256':{'test-only':'b'*64}})
    output=tmp_path/'failed.json'
    monkeypatch.setattr(sys,'argv',['runtime-probe','--model',str(model.path),'--ingress-reference','test-only:record','--output',str(output)])
    with pytest.raises(SystemExit) as captured:
        runtime_probe.main()
    assert captured.value.code==1
    record=json.loads(output.read_text())
    assert record['run_status']=='failed'
    assert record['failure_phase']=='forward'
    assert record['forward_calls_attempted']==1
    assert record['no_face_negative_passed'] is None
    assert record['source_commit']=='a'*40


def test_cli_existing_output_prevents_forward_and_overwrite(tmp_path,monkeypatch):
    import sys
    from services.casualty import runtime_probe
    fake=install_fake(monkeypatch,None)
    output=tmp_path/'existing.json'
    output.write_text('historical-test-only-evidence')
    monkeypatch.setattr(sys,'argv',['runtime-probe','--model',str(tmp_path/'absent.onnx'),'--ingress-reference','test-only:record','--output',str(output)])
    with pytest.raises(SystemExit) as captured:
        runtime_probe.main()
    assert captured.value.code==2
    assert fake.calls==[]
    assert output.read_text()=='historical-test-only-evidence'
