"""Offline typed run packs and optional injected object-store transfer."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "knight26.artifact-pack.v2"
ALLOWED = frozenset({"config.json", "snapshots.jsonl", "replay.jsonl",
                     "events.jsonl", "evaluation.json", "metrics.json"})
REQUIRED = frozenset({"config.json", "snapshots.jsonl"})
MAX_FILE_BYTES = 10_000_000
MAX_MANIFEST_BYTES = 65_536
REV = re.compile(r"[0-9a-f]{40}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
NONCE = re.compile(r"[0-9a-f]{16}\Z")
OPAQUE_ID = re.compile(r"[0-9a-f]{16,64}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
PARAMETERS = frozenset({"time_horizon_s", "vehicle_count", "max_routes",
                        "risk_weight", "distance_weight"})
METRICS = frozenset({"score", "route_count", "total_distance_km",
                     "mean_eta_minutes", "completed_count", "failed_count",
                     "mean_latency_ms"})
VALUES = frozenset({"progress", "eta_seconds", "distance_km", "risk_score",
                    "allocation_count"})
EVENT_KINDS = frozenset({"route", "closure", "allocation", "observation",
                         "progress", "eta", "snapshot"})


class ArtifactError(ValueError):
    """A pack is unsafe, incomplete, collided, or failed verification."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ArtifactError(f"nonstandard JSON constant: {value}")


def strict_json_loads(data):
    """Decode JSON without silently discarding duplicate keys at any depth."""
    try:
        return json.loads(data, object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("invalid UTF-8 JSON") from exc


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _file_path(name: str) -> str:
    if not isinstance(name, str) or name not in ALLOWED:
        raise ArtifactError(f"file outside typed artifact allowlist: {name!r}")
    return name


def _safe_file(root: Path, name: str) -> Path:
    path = root / _file_path(name)
    if root.is_symlink() or path.is_symlink() or not path.is_file():
        raise ArtifactError(f"missing, symlinked, or non-file artifact: {name}")
    return path


def _number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _numeric_map(value, allowed):
    if not isinstance(value, dict) or not value or not set(value) <= allowed:
        raise ArtifactError("structured numeric fields outside reviewed schema")
    if any(not _number(v) for v in value.values()):
        raise ArtifactError("structured values must be finite numbers")


def _typed_json(name: str, obj):
    """Closed schema: no arbitrary top-level fields, text, media, or coordinates."""
    if name == "config.json":
        if not isinstance(obj, dict) or set(obj) != {"schema", "seed", "parameters"}:
            raise ArtifactError("invalid config schema")
        if obj["schema"] != "knight26.config.v1" or type(obj["seed"]) is not int or not 0 <= obj["seed"] < 2**63:
            raise ArtifactError("invalid config seed/schema")
        _numeric_map(obj["parameters"], PARAMETERS)
    elif name in ("metrics.json", "evaluation.json"):
        if not isinstance(obj, dict) or set(obj) != {"schema", "metrics"}:
            raise ArtifactError("invalid aggregate schema")
        if obj["schema"] != "knight26.aggregate.v1":
            raise ArtifactError("invalid aggregate version")
        _numeric_map(obj["metrics"], METRICS)
    else:
        if not isinstance(obj, dict) or set(obj) != {"tick", "kind", "entity_id", "values"}:
            raise ArtifactError("invalid replay event schema")
        if type(obj["tick"]) is not int or obj["tick"] < 0:
            raise ArtifactError("invalid replay tick")
        if not isinstance(obj["kind"], str) or obj["kind"] not in EVENT_KINDS or (name == "snapshots.jsonl" and obj["kind"] != "snapshot"):
            raise ArtifactError("invalid replay kind")
        if not isinstance(obj["entity_id"], str) or not OPAQUE_ID.fullmatch(obj["entity_id"]):
            raise ArtifactError("replay entity must be an opaque hex ID")
        _numeric_map(obj["values"], VALUES)


def _structured(path: Path) -> tuple[int, str]:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ArtifactError("structured artifact exceeds size cap")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise ArtifactError("structured artifact exceeds size cap")
    try:
        text = data.decode("utf-8")
        if path.suffix == ".jsonl":
            lines = [line for line in text.splitlines() if line.strip()]
            if not lines:
                raise ArtifactError("empty replay stream")
            for line in lines:
                _typed_json(path.name, strict_json_loads(line))
        else:
            _typed_json(path.name, strict_json_loads(text))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("artifact must contain typed UTF-8 JSON/JSONL") from exc
    return len(data), _digest(data)


def _repo_refs(value):
    if not isinstance(value, list) or len(value) > 16:
        raise ArtifactError("model/dataset references must be bounded lists")
    for item in value:
        if not isinstance(item, dict) or set(item) != {"repo_id", "revision"}:
            raise ArtifactError("invalid repository reference")
        if not isinstance(item["repo_id"], str) or not REPO.fullmatch(item["repo_id"]):
            raise ArtifactError("repository ID required")
        if not isinstance(item["revision"], str) or not REV.fullmatch(item["revision"]):
            raise ArtifactError("full immutable repository revision required")


def _provenance(prov):
    if not isinstance(prov, dict) or set(prov) != {
        "source", "model", "datasets", "solver", "policy", "snapshot", "config", "seed"
    }:
        raise ArtifactError("complete typed provenance required")
    for key in ("source", "solver", "policy"):
        if not isinstance(prov[key], str) or not REV.fullmatch(prov[key]):
            raise ArtifactError(f"{key} must be a full 40-hex revision")
    for key in ("config", "snapshot"):
        if not isinstance(prov[key], str) or not SHA.fullmatch(prov[key]):
            raise ArtifactError(f"{key} must be a full SHA-256")
    if type(prov["seed"]) is not int or not 0 <= prov["seed"] < 2**63:
        raise ArtifactError("seed must be an exact nonnegative integer")
    _repo_refs(prov["model"])
    _repo_refs(prov["datasets"])
    return prov


def make_run_id(completed_at: str, provenance: dict, run_nonce: str) -> str:
    """Derive timestamp/seed/provenance-bound ID with a caller-generated 64-bit nonce."""
    try:
        stamp = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError
    except (AttributeError, ValueError) as exc:
        raise ArtifactError("completed_at must be a UTC timestamp") from exc
    _provenance(provenance)
    if not isinstance(run_nonce, str) or not NONCE.fullmatch(run_nonce):
        raise ArtifactError("run_nonce must be 16 lowercase hex characters")
    fingerprint = _digest(_json_bytes(provenance))[:12]
    return f"{stamp.strftime('%Y%m%dT%H%M%SZ')}-s{provenance['seed']}-{fingerprint}-{run_nonce}"


def _metadata(metadata: dict) -> dict:
    if not isinstance(metadata, dict) or set(metadata) != {
        "run_id", "run_nonce", "status", "completed_at", "privacy", "provenance"
    }:
        raise ArtifactError("complete explicit completed-run metadata required")
    if metadata["status"] != "completed":
        raise ArtifactError("only finalized completed runs can be packed")
    privacy = metadata["privacy"]
    if (not isinstance(privacy, dict)
            or set(privacy) != {"sanitized", "contains_personal_data"}
            or privacy["sanitized"] is not True
            or privacy["contains_personal_data"] is not False):
        raise ArtifactError("explicit sanitized and no-personal-data attestation required")
    expected = make_run_id(metadata["completed_at"], metadata["provenance"], metadata["run_nonce"])
    if metadata["run_id"] != expected:
        raise ArtifactError("run_id must bind time, seed, provenance, and nonce")
    return metadata


def _manifest(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ArtifactError("unsupported pack schema")
    meta = {k: data[k] for k in ("run_id", "run_nonce", "status", "completed_at", "privacy", "provenance") if k in data}
    _metadata(meta)
    if set(data) != set(meta) | {"schema", "files", "remote_prefix"}:
        raise ArtifactError("unknown manifest fields")
    files = data["files"]
    if not isinstance(files, list) or not 2 <= len(files) <= len(ALLOWED):
        raise ArtifactError("manifest requires bounded explicit files")
    names = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise ArtifactError("invalid file entry")
        name = _file_path(item["path"])
        if name in names or type(item["size"]) is not int or not 0 <= item["size"] <= MAX_FILE_BYTES:
            raise ArtifactError("duplicate or invalid file length")
        if not isinstance(item["sha256"], str) or not SHA.fullmatch(item["sha256"]):
            raise ArtifactError("invalid SHA-256")
        names.append(name)
    if not REQUIRED <= set(names):
        raise ArtifactError("config and snapshot bytes must be included")
    if data["remote_prefix"] != f"runs/{meta['run_id']}/":
        raise ArtifactError("invalid run prefix")
    entry = {e["path"]: e for e in files}
    if entry["config.json"]["sha256"] != meta["provenance"]["config"]:
        raise ArtifactError("config provenance hash does not match included bytes")
    if entry["snapshots.jsonl"]["sha256"] != meta["provenance"]["snapshot"]:
        raise ArtifactError("snapshot provenance hash does not match included bytes")
    return data


def build_pack(source_dir, output_dir, metadata, files):
    """Copy exact reviewed, typed files from a completed local run."""
    meta = _metadata(metadata)
    if not isinstance(files, (list, tuple)) or not files or len(files) != len(set(files)):
        raise ArtifactError("files must be explicit and unique")
    if not REQUIRED <= set(files):
        raise ArtifactError("config.json and snapshots.jsonl are required")
    source, output = Path(source_dir), Path(output_dir)
    if source.is_symlink() or not source.is_dir() or output.exists() or output.is_symlink():
        raise ArtifactError("invalid source or existing pack destination")
    entries = []
    for name in files:
        path = _safe_file(source, name)
        size, digest = _structured(path)
        entries.append({"path": name, "size": size, "sha256": digest})
    manifest = {"schema": SCHEMA, **meta, "remote_prefix": f"runs/{meta['run_id']}/",
                "files": sorted(entries, key=lambda e: e["path"])}
    _manifest(manifest)
    if len(_json_bytes(manifest)) > MAX_MANIFEST_BYTES:
        raise ArtifactError("manifest exceeds size cap")
    output.mkdir(parents=True, exist_ok=False)
    try:
        for entry in manifest["files"]:
            shutil.copyfile(_safe_file(source, entry["path"]), output / entry["path"], follow_symlinks=False)
        (output / "manifest.json").write_bytes(_json_bytes(manifest))
        verify_pack(output)
    except BaseException:
        shutil.rmtree(output)
        raise
    return manifest


def _read_manifest(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ArtifactError("missing, linked, or oversized manifest")
    data = path.read_bytes()
    if len(data) > MAX_MANIFEST_BYTES:
        raise ArtifactError("oversized manifest")
    try:
        return _manifest(strict_json_loads(data.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("invalid manifest JSON") from exc


def verify_pack(pack_dir):
    """Reject missing, extra, linked, changed, or untyped files."""
    root = Path(pack_dir)
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("missing or linked pack")
    manifest = _read_manifest(root / "manifest.json")
    expected = {entry["path"] for entry in manifest["files"]} | {"manifest.json"}
    if {p.name for p in root.iterdir()} != expected:
        raise ArtifactError("pack has missing or unexpected files")
    for entry in manifest["files"]:
        size, digest = _structured(_safe_file(root, entry["path"]))
        if size != entry["size"] or digest != entry["sha256"]:
            raise ArtifactError(f"checksum/length mismatch: {entry['path']}")
    config = strict_json_loads((root / "config.json").read_text(encoding="utf-8"))
    if config["seed"] != manifest["provenance"]["seed"]:
        raise ArtifactError("config seed does not match provenance")
    return manifest


def fetch_pack(backend, run_id: str, destination):
    """Download exact manifest-listed files to staging; verify before publication."""
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,120}", run_id):
        raise ArtifactError("invalid run_id")
    dest = Path(destination)
    if dest.exists() or dest.is_symlink():
        raise ArtifactError("destination exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".artifact-fetch-", dir=dest.parent))
    try:
        prefix = f"runs/{run_id}/"
        backend.download_files([(prefix + "manifest.json", staging / "manifest.json")])
        manifest = _read_manifest(staging / "manifest.json")
        if manifest["run_id"] != run_id:
            raise ArtifactError("downloaded manifest run mismatch")
        backend.download_files([(prefix + e["path"], staging / e["path"]) for e in manifest["files"]])
        verify_pack(staging)
        staging.rename(dest)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def upload_pack(pack_dir, backend, *, dry_run=False):
    """Resume only matching partial objects; data first, manifest last."""
    pack = Path(pack_dir)
    manifest = verify_pack(pack)
    prefix = manifest["remote_prefix"]
    data_paths = {prefix + e["path"]: e for e in manifest["files"]}
    manifest_path = prefix + "manifest.json"
    expected = set(data_paths) | {manifest_path}
    existing = set(backend.list_files(prefix))
    if not existing <= expected:
        raise ArtifactError("run prefix contains foreign objects")
    if manifest_path in existing:
        if existing != expected:
            raise ArtifactError("published manifest has missing objects")
        with tempfile.TemporaryDirectory(prefix="artifact-check-") as temp:
            fetched = Path(temp) / "pack"
            fetch_pack(backend, manifest["run_id"], fetched)
            if (fetched / "manifest.json").read_bytes() != (pack / "manifest.json").read_bytes():
                raise ArtifactError("run prefix collision: manifest differs")
        return {"status": "already_verified", "prefix": prefix}
    if existing:
        with tempfile.TemporaryDirectory(prefix="artifact-partial-check-") as temp:
            for remote in sorted(existing):
                local = Path(temp) / remote.rsplit("/", 1)[-1]
                backend.download_files([(remote, local)])
                if local.is_symlink() or not local.is_file():
                    raise ArtifactError("invalid partial remote object")
                entry = data_paths[remote]
                if local.stat().st_size != entry["size"] or _digest(local.read_bytes()) != entry["sha256"]:
                    raise ArtifactError("partial prefix collision: existing bytes differ")
    missing = sorted(set(data_paths) - existing)
    if dry_run:
        return {"status": "dry_run", "prefix": prefix,
                "files": missing + [manifest_path]}
    if hasattr(backend, "preflight_upload"):
        backend.preflight_upload(sum(data_paths[p]["size"] for p in missing)
                                 + (pack / "manifest.json").stat().st_size)
    if missing:
        backend.upload_files([(pack / data_paths[p]["path"], p) for p in missing])
    backend.upload_files([(pack / "manifest.json", manifest_path)])
    with tempfile.TemporaryDirectory(prefix="artifact-check-") as temp:
        fetched = Path(temp) / "pack"
        fetch_pack(backend, manifest["run_id"], fetched)
        if (fetched / "manifest.json").read_bytes() != (pack / "manifest.json").read_bytes():
            raise ArtifactError("remote manifest changed during transfer")
    return {"status": "verified", "prefix": prefix}
