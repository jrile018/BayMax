import json
from copy import deepcopy

import pytest

from evals.intake.run import load_cases, load_external, score_system
from services.intake import batch


def test_retains_valid_and_rejected_cases_with_raw_diagnostics(tmp_path):
    cases = load_cases()[:2]

    class Provider:
        name = "test_injected_provider"

        def __init__(self):
            self.last_metadata = {}
            self.closed = False

        def extract(self, report):
            if report.report_id == cases[0]["report_id"]:
                self.last_metadata = {
                    "raw_output": '{"claims":"valid"}',
                    "latency_s": 0.25,
                    "input_tokens": 30,
                    "output_tokens": 11,
                    "peak_vram_bytes": 123,
                }
                return deepcopy(cases[0]["gold"])
            self.last_metadata = {
                "raw_output": '{"language":"bad"}',
                "latency_s": 0.5,
                "input_tokens": 31,
                "output_tokens": 12,
                "peak_vram_bytes": 124,
            }
            return {"language": "unsupported", "flags": [], "claims": []}

        def close(self):
            self.closed = True

    provider = Provider()
    output = tmp_path / "predictions.json"
    data = batch.run_batch(provider, cases, output, {"test_mode": "injected"})
    assert provider.closed
    assert data["provider"] == provider.name
    assert data["provider_metadata"]["test_mode"] == "injected"
    assert data["source_status"] == "fictional"
    assert len(data["source_sha"]) == 40
    assert isinstance(data["source_dirty"], bool)
    assert len(data["source_fingerprint_sha256"]) == 64
    assert len(data["fixture_sha256"]) == 64
    assert data["started_at_utc"] and data["ended_at_utc"]
    saved = json.loads(output.read_text())
    assert len(saved["predictions"]) == 2
    good, bad = saved["predictions"]
    assert good["payload"] == cases[0]["gold"]
    assert good["error"] is None
    assert good["raw_output"] == '{"claims":"valid"}'
    assert good["input_tokens"] == 30
    assert good["output_tokens"] == 11
    assert good["peak_vram_bytes"] == 123
    assert bad["payload"] is None
    assert bad["returned_payload"] == {"language": "unsupported", "flags": [], "claims": []}
    assert bad["raw_output"] == '{"language":"bad"}'
    assert "ValidationError" in bad["error"]
    assert saved["validated_count"] == 1
    name, predictions, metadata = load_external(output, cases)
    scored = score_system(cases, predictions, name, "external_predictions")
    assert scored["metrics"]["valid_schema"]["numerator"] == 1
    assert metadata["test_mode"] == "injected"


def test_exception_keeps_recovery_artifact_and_later_cases(tmp_path):
    cases = load_cases()[:3]
    output = tmp_path / "predictions.json"

    class Provider:
        name = "injected_error"

        def __init__(self):
            self.last_metadata = {}
            self.closed = False

        def extract(self, report):
            if report.report_id == cases[1]["report_id"]:
                intermediate = json.loads(output.read_text())
                assert len(intermediate["predictions"]) == 3
                assert intermediate["predictions"][0]["payload"] == cases[0]["gold"]
                assert intermediate["predictions"][1]["payload"] is None
                assert intermediate["predictions"][2]["payload"] is None
                self.last_metadata = {"raw_output": "{bad json", "latency_s": 0.7}
                raise ValueError("decode failed")
            return deepcopy(next(c["gold"] for c in cases if c["report_id"] == report.report_id))

        def close(self):
            self.closed = True

    provider = Provider()
    data = batch.run_batch(provider, cases, output)
    assert provider.closed
    assert data["predictions"][1]["payload"] is None
    assert data["predictions"][1]["raw_output"] == "{bad json"
    assert "decode failed" in data["predictions"][1]["error"]
    assert data["predictions"][2]["payload"] == cases[2]["gold"]
    assert not list(tmp_path.glob("*.tmp"))


def test_close_even_when_batch_setup_fails(tmp_path):
    class Provider:
        name = "broken"
        def __init__(self):
            self.closed = False
        def close(self):
            self.closed = True
    provider = Provider()
    with pytest.raises(ValueError, match="duplicate"):
        batch.run_batch(provider, [{"report_id": "same"}, {"report_id": "same"}], tmp_path / "out.json")
    assert provider.closed

def test_cli_load_failure_saves_all_pending_reports(tmp_path, monkeypatch):
    from services.intake import qwen

    class Unavailable:
        name = "Qwen/Qwen3-4B"

        def __init__(self, revision, cache_dir):
            raise RuntimeError("local checkpoint missing")

    monkeypatch.setattr(qwen, "QwenProvider", Unavailable)
    monkeypatch.setattr(batch, "_source_provenance", lambda: {
        "source_sha": "a" * 40, "source_dirty": False,
        "source_fingerprint_sha256": "b" * 64,
    })
    output = tmp_path / "failed-load.json"
    with pytest.raises(RuntimeError, match="local checkpoint missing"):
        batch.main([
            "--revision", "a" * 40,
            "--cache-dir", str(tmp_path / "cache"),
            "--output", str(output),
        ])
    saved = json.loads(output.read_text())
    assert saved["status"] == "load_failed"
    assert saved["provider_metadata"]["fixture_file_sha256"] == batch.hashlib.sha256(batch.FIXTURES.read_bytes()).hexdigest()
    assert saved["provider"] == "Qwen/Qwen3-4B"
    assert "local checkpoint missing" in saved["run_error"]
    assert len(saved["predictions"]) == len(load_cases())
    assert all(record["payload"] is None for record in saved["predictions"])


def test_source_fingerprint_tracks_executed_python_bytes(tmp_path, monkeypatch):
    package = tmp_path / "services" / "intake"
    package.mkdir(parents=True)
    evaluator = tmp_path / "evals" / "intake"
    evaluator.mkdir(parents=True)
    (package / "a.py").write_text("first\n")
    (evaluator / "b.py").write_text("second\n")
    (package / "ignored.txt").write_text("irrelevant")
    monkeypatch.setattr(batch, "REPO_ROOT", tmp_path)
    first = batch._source_fingerprint()
    assert len(first) == 64
    assert batch._source_fingerprint() == first
    (package / "ignored.txt").write_text("changed")
    assert batch._source_fingerprint() == first
    (package / "a.py").write_text("changed\n")
    assert batch._source_fingerprint() != first


def test_dirty_source_blocks_model_constructor_before_load(tmp_path, monkeypatch):
    from services.intake import qwen

    constructed = []
    class Provider:
        name = "Qwen/Qwen3-4B"
        def __init__(self, revision, cache_dir):
            constructed.append(True)

    monkeypatch.setattr(qwen, "QwenProvider", Provider)
    monkeypatch.setattr(batch, "_source_provenance", lambda: {
        "source_sha": "a" * 40, "source_dirty": True,
        "source_fingerprint_sha256": "b" * 64,
    })
    with pytest.raises(RuntimeError, match="clean owned Python source"):
        batch.main(["--revision", "a" * 40,
                    "--cache-dir", str(tmp_path / "cache"),
                    "--output", str(tmp_path / "out.json")])
    assert constructed == []


def test_factual_load_metadata_cannot_be_overridden(tmp_path):
    cases = load_cases()[:1]
    class Provider:
        name = "injected"
        load_metadata = {"revision": "actual", "device": "actual-gpu"}
        def extract(self, report):
            return deepcopy(cases[0]["gold"])
        def close(self):
            pass
    data = batch.run_batch(
        Provider(), cases, tmp_path / "predictions.json",
        {"revision": "false", "device": "false", "fixture_file_sha256": "f" * 64})
    assert data["provider_metadata"]["revision"] == "actual"
    assert data["provider_metadata"]["device"] == "actual-gpu"
    assert data["provider_metadata"]["fixture_file_sha256"] == "f" * 64


def test_git_provenance_failure_is_not_silently_replaced(tmp_path, monkeypatch):
    cases = load_cases()[:1]
    class Provider:
        name = "injected"
        closed = False
        def extract(self, report):
            pytest.fail("must not extract without provenance")
        def close(self):
            self.closed = True
    provider = Provider()
    def missing_git():
        raise RuntimeError("git unavailable")
    monkeypatch.setattr(batch, "_source_provenance", missing_git)
    with pytest.raises(RuntimeError, match="git unavailable"):
        batch.run_batch(provider, cases, tmp_path / "predictions.json")
    assert provider.closed


def test_dirty_gate_ignores_data_and_catches_python_edits(tmp_path, monkeypatch):
    package = tmp_path / "services" / "intake"
    package.mkdir(parents=True)
    (package / "qwen.py").write_text("tracked")
    monkeypatch.setattr(batch, "REPO_ROOT", tmp_path)

    outputs = iter([
        "evals/intake/artifacts/evidence.json\n",
        "services/intake/qwen.py\n",
    ])
    monkeypatch.setattr(batch.subprocess, "check_output",
                        lambda *args, **kwargs: next(outputs))
    assert batch._source_dirty() is False

    outputs = iter([
        "services/intake/qwen.py\n",
        "services/intake/qwen.py\n",
    ])
    assert batch._source_dirty() is True

    # Even an ignored, untracked .py can change imports and must block a run.
    (package / "extra.py").write_text("untracked")
    outputs = iter(["", "services/intake/qwen.py\n"])
    assert batch._source_dirty() is True


def test_budget_error_checkpoints_current_case_and_aborts_later_cases(tmp_path):
    from services.intake.qwen import ResourceBudgetError

    cases = load_cases()[:3]
    output = tmp_path / "fatal.json"
    seen = []

    class Provider:
        name = "injected_budget"
        def __init__(self):
            self.last_metadata = {}
            self.closed = False
        def extract(self, report):
            seen.append(report.report_id)
            if report.report_id == cases[1]["report_id"]:
                self.last_metadata = {
                    "raw_output": '{"partial":true}',
                    "latency_s": 0.8,
                    "peak_vram_bytes": 15 * 1024**3,
                }
                raise ResourceBudgetError("VRAM cap exceeded")
            return deepcopy(cases[0]["gold"])
        def close(self):
            self.closed = True

    provider = Provider()
    with pytest.raises(ResourceBudgetError, match="VRAM cap exceeded"):
        batch.run_batch(provider, cases, output)
    assert provider.closed
    assert seen == [case["report_id"] for case in cases[:2]]
    saved = json.loads(output.read_text())
    assert saved["status"] == "failed"
    assert "ResourceBudgetError" in saved["run_error"]
    first, fatal, pending = saved["predictions"]
    assert first["status"] == "validated"
    assert fatal["status"] == "failed"
    assert fatal["payload"] is None
    assert fatal["raw_output"] == '{"partial":true}'
    assert fatal["peak_vram_bytes"] == 15 * 1024**3
    assert "VRAM cap exceeded" in fatal["error"]
    assert pending["status"] == "pending"
    assert pending["payload"] is None
    assert saved["validated_count"] == 1
    assert saved["ended_at_utc"]


def test_non_json_returned_value_cannot_break_failure_checkpoint(tmp_path):
    cases = load_cases()[:1]
    output = tmp_path / "bad-payload.json"

    class NonJSON:
        def __repr__(self):
            return "nonjson-payload"

    class Provider:
        name = "injected_nonjson"
        def extract(self, report):
            return NonJSON()
        def close(self):
            pass

    batch.run_batch(Provider(), cases, output)
    saved = json.loads(output.read_text())
    result = saved["predictions"][0]
    assert result["status"] == "failed"
    assert result["payload"] is None
    assert result["returned_payload"]["non_json_type"] == "NonJSON"
    assert "nonjson-payload" in result["returned_payload"]["repr"]
    assert "ValidationError" in result["error"]
