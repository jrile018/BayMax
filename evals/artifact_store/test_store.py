import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from services.artifact_store import ArtifactError, build_pack, verify_pack, upload_pack, fetch_pack, make_run_id


REV = "a" * 40
ENTITY = "b" * 16


def source_files(source: Path):
    source.mkdir()
    (source / "config.json").write_text(json.dumps({
        "schema": "knight26.config.v1", "seed": 7,
        "parameters": {"vehicle_count": 3, "risk_weight": 0.5}
    }), encoding="utf-8")
    (source / "snapshots.jsonl").write_text(json.dumps({
        "tick": 0, "kind": "snapshot", "entity_id": ENTITY,
        "values": {"progress": 0.0}
    }) + "\n", encoding="utf-8")
    (source / "metrics.json").write_text(json.dumps({
        "schema": "knight26.aggregate.v1",
        "metrics": {"score": 0.5, "route_count": 3}
    }), encoding="utf-8")


def metadata(source: Path):
    prov = {
        "source": REV, "model": [], "datasets": [],
        "solver": "c" * 40, "policy": "d" * 40,
        "snapshot": hashlib.sha256((source / "snapshots.jsonl").read_bytes()).hexdigest(),
        "config": hashlib.sha256((source / "config.json").read_bytes()).hexdigest(),
        "seed": 7,
    }
    stamp = "2026-10-10T12:00:00Z"
    nonce = "e" * 16
    return {
        "run_id": make_run_id(stamp, prov, nonce), "run_nonce": nonce,
        "status": "completed", "completed_at": stamp,
        "privacy": {"sanitized": True, "contains_personal_data": False},
        "provenance": prov,
    }


class MockBucket:
    """In-memory transfer mock; no Hugging Face connection."""
    def __init__(self):
        self.files = {}
        self.fail_after = None
        self.uploaded = 0
        self.corrupt_download = False
        self.upload_calls = []

    def list_files(self, prefix):
        return sorted(k for k in self.files if k.startswith(prefix))

    def upload_files(self, pairs):
        for local, remote in pairs:
            if self.fail_after is not None and self.uploaded >= self.fail_after:
                raise OSError("mock partial batch failure")
            self.upload_calls.append(remote)
            self.files[remote] = Path(local).read_bytes()
            self.uploaded += 1

    def download_files(self, pairs):
        for remote, local in pairs:
            data = self.files[remote]
            if self.corrupt_download and remote.endswith("metrics.json"):
                data += b"x"
            p = Path(local)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        source_files(self.source)
        self.meta = metadata(self.source)
        self.pack = self.root / "pack"

    def tearDown(self):
        self.temp.cleanup()

    def build(self, meta=None, files=None, output=None):
        return build_pack(self.source, output or self.pack, meta or self.meta,
                          files or ["config.json", "snapshots.jsonl", "metrics.json"])

    def test_manifest_hashes_and_provenance(self):
        self.build()
        manifest = verify_pack(self.pack)
        self.assertEqual(manifest["provenance"], self.meta["provenance"])
        self.assertEqual(len(manifest["files"]), 3)
        (self.pack / "metrics.json").write_text("changed")
        with self.assertRaises(ArtifactError):
            verify_pack(self.pack)

    def test_completed_and_privacy_required(self):
        for patch in ({"status": "running"},
                      {"privacy": {"sanitized": False, "contains_personal_data": False}}):
            with self.subTest(patch=patch), self.assertRaises(ArtifactError):
                self.build(dict(self.meta, **patch))

    def test_paths_and_symlinks_rejected(self):
        for path in ("../metrics.json", "/tmp/metrics.json", "reports.json",
                     "audio.wav", "images.png", "config/../metrics.json"):
            with self.subTest(path=path), self.assertRaises(ArtifactError):
                self.build(files=["config.json", "snapshots.jsonl", path])
        (self.source / "metrics.json").unlink()
        (self.source / "metrics.json").symlink_to(self.root / "outside")
        with self.assertRaises(ArtifactError):
            self.build()

    def test_sensitive_or_untyped_content_rejected(self):
        bad = [
            '{"notes":"Jane Doe at 10 Main St","blob":"raw audio"}',
            '"Jane Doe at 10 Main St"',
            '["raw report"]',
            '{"schema":"knight26.aggregate.v1","metrics":{"latitude":27.0}}',
            '{"schema":"knight26.aggregate.v1","metrics":{"score":"Jane Doe"}}',
        ]
        for i, payload in enumerate(bad):
            (self.source / "metrics.json").write_text(payload)
            with self.subTest(i=i), self.assertRaises(ArtifactError):
                self.build()

    def test_malformed_replay_kind_rejected(self):
        (self.source / "snapshots.jsonl").write_text(json.dumps({
            "tick": 0, "kind": ["snapshot"], "entity_id": ENTITY,
            "values": {"progress": 0.0}
        }) + "\n")
        with self.assertRaises(ArtifactError):
            self.build()

    def test_config_snapshot_hash_and_seed_bound(self):
        bad = dict(self.meta)
        bad["provenance"] = dict(self.meta["provenance"], config="0" * 64)
        bad["run_id"] = make_run_id(bad["completed_at"], bad["provenance"], bad["run_nonce"])
        with self.assertRaises(ArtifactError):
            self.build(bad)
        bad = dict(self.meta)
        bad["provenance"] = dict(self.meta["provenance"], seed=8)
        bad["run_id"] = make_run_id(bad["completed_at"], bad["provenance"], bad["run_nonce"])
        with self.assertRaises(ArtifactError):
            self.build(bad)

    def test_idempotent_and_valid_collision(self):
        self.build()
        bucket = MockBucket()
        self.assertEqual(upload_pack(self.pack, bucket)["status"], "verified")
        self.assertEqual(upload_pack(self.pack, bucket)["status"], "already_verified")
        second_source = self.root / "second-source"
        source_files(second_source)
        (second_source / "metrics.json").write_text(json.dumps({
            "schema": "knight26.aggregate.v1", "metrics": {"score": 0.9}
        }))
        second = self.root / "second-pack"
        build_pack(second_source, second, self.meta,
                   ["config.json", "snapshots.jsonl", "metrics.json"])
        with self.assertRaises(ArtifactError):
            upload_pack(second, bucket)

    def test_partial_retry_matching_and_mismatch(self):
        self.build()
        bucket = MockBucket()
        bucket.fail_after = 1
        with self.assertRaises(OSError):
            upload_pack(self.pack, bucket)
        before = dict(bucket.files)
        self.assertFalse(any(k.endswith("manifest.json") for k in before))
        bucket.fail_after = None
        self.assertEqual(upload_pack(self.pack, bucket)["status"], "verified")
        for path, data in before.items():
            self.assertEqual(bucket.files[path], data)
            self.assertEqual(bucket.upload_calls.count(path), 1)
        bucket.files[next(k for k in before)] = b"changed"
        with self.assertRaises(ArtifactError):
            upload_pack(self.pack, bucket)

    def test_corrupted_download_refused(self):
        self.build()
        bucket = MockBucket()
        upload_pack(self.pack, bucket)
        bucket.corrupt_download = True
        with self.assertRaises(ArtifactError):
            fetch_pack(bucket, self.meta["run_id"], self.root / "retrieved")
        self.assertFalse((self.root / "retrieved").exists())

    def test_manifest_path_injection_refused(self):
        self.build()
        bucket = MockBucket()
        upload_pack(self.pack, bucket)
        key = next(k for k in bucket.files if k.endswith("manifest.json"))
        manifest = json.loads(bucket.files[key])
        manifest["files"][0]["path"] = "../escape.json"
        bucket.files[key] = json.dumps(manifest).encode()
        with self.assertRaises(ArtifactError):
            fetch_pack(bucket, self.meta["run_id"], self.root / "retrieved")
        self.assertFalse((self.root / "escape.json").exists())

    def test_dry_run_no_mutation(self):
        self.build()
        bucket = MockBucket()
        self.assertEqual(upload_pack(self.pack, bucket, dry_run=True)["status"], "dry_run")
        self.assertEqual(bucket.files, {})

    def test_live_backend_setup_gate(self):
        from services.artifact_store.hf_backend import HfBucketBackend, SetupNeeded
        with self.assertRaises(SetupNeeded):
            HfBucketBackend("user/private", remaining_free_bytes=100,
                            caller_confirmed_free_quota=True)


if __name__ == "__main__":
    unittest.main()
