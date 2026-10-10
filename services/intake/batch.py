"""Crash-recoverable, source-preserving batch extraction for fictional intake reports.

Importing this module does not load model libraries or perform inference.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import reprlib
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

from .schema import Report, parse_proposal
from .qwen import ResourceBudgetError

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "reports" / "intake_cases.json"
CASE_METADATA = ("latency_s", "input_tokens", "output_tokens",
                 "peak_vram_bytes", "hit_output_cap")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def _source_fingerprint() -> str:
    """Hash each executed intake/evaluator Python path and its exact bytes."""
    files = sorted(
        path for root in ("services/intake", "evals/intake")
        for path in (REPO_ROOT / root).rglob("*.py")
        if path.is_file()
    )
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(REPO_ROOT).as_posix().encode("utf-8")
        contents = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def _source_dirty() -> bool:
    """Require every owned Python file to match Git HEAD, including ignored files."""
    roots = ("services/intake", "evals/intake")
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "HEAD", "--", *roots],
        cwd=REPO_ROOT, text=True,
    ).splitlines()
    tracked = set(subprocess.check_output(
        ["git", "ls-files", "--cached", "--", *roots],
        cwd=REPO_ROOT, text=True,
    ).splitlines())
    current = {
        path.relative_to(REPO_ROOT).as_posix()
        for root in roots
        for path in (REPO_ROOT / root).rglob("*.py")
        if path.is_file()
    }
    return any(name.endswith(".py") for name in changed) or bool(current - tracked)


def _source_provenance() -> dict[str, Any]:
    # Git failures are deliberate failures, never silently substituted.
    return {
        "source_sha": _source_sha(),
        "source_dirty": _source_dirty(),
        "source_fingerprint_sha256": _source_fingerprint(),
    }


def _fixture_hash(cases: list[dict[str, Any]]) -> str:
    canonical = json.dumps(cases, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _returned_diagnostic(value: Any) -> Any:
    """Preserve JSON results; bound a fallback for non-JSON provider returns."""
    try:
        json.dumps(value, allow_nan=False)
        return value
    except (TypeError, ValueError, OverflowError, RecursionError):
        try:
            description = reprlib.repr(value)[:2000]
        except Exception:
            description = "<repr failed>"
        return {"non_json_type": type(value).__name__, "repr": description}


def _new_manifest(name: str, cases: list[dict[str, Any]],
                  metadata: dict[str, Any]) -> dict[str, Any]:
    provenance = _source_provenance()
    return {
        "provider": name,
        "provider_metadata": metadata,
        "source_status": "fictional",
        **provenance,
        "fixture_sha256": _fixture_hash(cases),
        "started_at_utc": _utc_now(),
        "ended_at_utc": None,
        "status": "running",
        "validated_count": 0,
        "predictions": [
            {"report_id": case["report_id"], "payload": None,
             "returned_payload": None, "raw_output": None, "error": None, "status": "pending",
             **{key: None for key in CASE_METADATA}}
            for case in cases
        ],
    }


def run_batch(provider: Any, cases: list[dict[str, Any]],
              output_path: str | Path,
              provider_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract all reports, validate each payload, and checkpoint after each case.

    A case error is recorded with null payload; later cases still run. The
    provider is closed even when setup, writing, or extraction fails.
    """
    output = Path(output_path)
    data = None
    try:
        if not isinstance(cases, list):
            raise ValueError("cases must be a list")
        identifiers = [case["report_id"] for case in cases]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate report_id")
        if provider_metadata is not None and not isinstance(provider_metadata, dict):
            raise ValueError("provider_metadata must be an object")
        name = provider.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("provider must have a nonempty name")
        metadata = dict(provider_metadata or {})
        metadata.update(dict(getattr(provider, "load_metadata", {}) or {}))
        data = _new_manifest(name, cases, metadata)
        _atomic_json(output, data)
        for case, record in zip(cases, data["predictions"]):
            start = time.perf_counter()
            try:
                report = Report(case["report_id"], "fictional_eval", 0.0,
                                case["text"])
                # Never carry raw output or counters over from a prior report.
                if hasattr(provider, "last_metadata"):
                    provider.last_metadata = {}
                payload = provider.extract(report)
                record["returned_payload"] = _returned_diagnostic(payload)
                parse_proposal(report, payload, name)
                record["payload"] = payload
                record["status"] = "validated"
                data["validated_count"] += 1
            except ResourceBudgetError as exc:
                record["payload"] = None
                record["error"] = _error(exc)
                record["status"] = "failed"
                raise
            except Exception as exc:
                record["payload"] = None
                record["error"] = _error(exc)
                record["status"] = "failed"
            finally:
                raw_metadata = getattr(provider, "last_metadata", {}) or {}
                if isinstance(raw_metadata, dict):
                    record["raw_output"] = raw_metadata.get("raw_output")
                    for key in CASE_METADATA:
                        if key in raw_metadata:
                            record[key] = raw_metadata[key]
                if record["latency_s"] is None:
                    record["latency_s"] = time.perf_counter() - start
                _atomic_json(output, data)
        data["status"] = "completed"
        data["ended_at_utc"] = _utc_now()
        _atomic_json(output, data)
        return data
    except BaseException as exc:
        if data is not None:
            data["status"] = "failed"
            data["run_error"] = _error(exc)
            data["ended_at_utc"] = _utc_now()
            _atomic_json(output, data)
        raise
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run pinned local Qwen extraction on fictional fixtures. "
                    "Requires an explicit exclusive GPU lease; never downloads weights."
    )
    parser.add_argument("--revision", required=True,
                        help="approved immutable 40-character model revision")
    parser.add_argument("--cache-dir", type=Path, required=True,
                        help="approved local model cache; local_files_only is enforced")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    # Deliberately loaded only during CLI invocation.
    from evals.intake.run import load_cases
    cases = load_cases(FIXTURES)
    if _source_provenance()["source_dirty"]:
        raise RuntimeError("real model run requires clean owned Python source")
    fixture_file_sha256 = hashlib.sha256(FIXTURES.read_bytes()).hexdigest()
    from .qwen import QwenProvider
    try:
        provider = QwenProvider(args.revision, str(args.cache_dir))
    except Exception as exc:
        failure = _new_manifest(
            QwenProvider.name, cases,
            {"revision": args.revision, "cache_dir": str(args.cache_dir),
             "fixture_file_sha256": fixture_file_sha256}
        )
        failure["status"] = "load_failed"
        failure["run_error"] = _error(exc)
        failure["ended_at_utc"] = _utc_now()
        _atomic_json(args.output, failure)
        raise
    run_batch(provider, cases, args.output,
              {"fixture_file_sha256": fixture_file_sha256})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
