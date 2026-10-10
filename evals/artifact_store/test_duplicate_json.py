"""Duplicate-key regressions: mock storage only, no real Hub calls."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evals.artifact_store.test_store import MockBucket, metadata, source_files
from services.artifact_store import ArtifactError, build_pack, fetch_pack, upload_pack, verify_pack


FILES = ["config.json", "snapshots.jsonl", "metrics.json"]


class DuplicateJSONTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        source_files(self.source)
        self.meta = metadata(self.source)
        self.pack = self.root / "pack"

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        return build_pack(self.source, self.pack, self.meta, FILES)

    def test_top_level_and_nested_duplicate_artifact_keys_rejected_before_copy(self):
        payloads = (
            '{"schema":"knight26.aggregate.v1","metrics":{"notes":"raw audio"},"metrics":{"score":0.5}}',
            '{"schema":"knight26.aggregate.v1","metrics":{"score":"Jane Doe at 10 Main St","score":0.5}}',
        )
        for payload in payloads:
            (self.source / "metrics.json").write_text(payload)
            with self.subTest(payload=payload), self.assertRaises(ArtifactError):
                self.build()
            self.assertFalse(self.pack.exists())

    def test_escaped_equivalent_key_rejected(self):
        (self.source / "metrics.json").write_text(
            r'{"schema":"knight26.aggregate.v1","metrics":{"score":"raw report","\u0073core":0.5}}'
        )
        with self.assertRaises(ArtifactError):
            self.build()
        self.assertFalse(self.pack.exists())

    def test_jsonl_row_duplicate_rejected(self):
        (self.source / "snapshots.jsonl").write_text(
            '{"tick":0,"kind":"snapshot","entity_id":"Jane Doe","entity_id":"bbbbbbbbbbbbbbbb","values":{"progress":0.0}}\n'
        )
        self.meta = metadata(self.source)
        with self.assertRaises(ArtifactError):
            self.build()
        self.assertFalse(self.pack.exists())

    def test_hidden_duplicate_bytes_rejected_before_upload(self):
        self.build()
        payload = b'{"schema":"knight26.aggregate.v1","metrics":{"score":"raw report","score":0.5}}'
        (self.pack / "metrics.json").write_bytes(payload)
        manifest_path = self.pack / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        entry = next(x for x in manifest["files"] if x["path"] == "metrics.json")
        entry.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ArtifactError):
            verify_pack(self.pack)
        bucket = MockBucket()
        with self.assertRaises(ArtifactError):
            upload_pack(self.pack, bucket)
        self.assertEqual(bucket.files, {})

    def test_privacy_attestation_requires_json_booleans(self):
        bad = dict(self.meta, privacy={"sanitized": 1, "contains_personal_data": 0})
        with self.assertRaises(ArtifactError):
            build_pack(self.source, self.pack, bad, FILES)
        self.assertFalse(self.pack.exists())

    def test_cli_metadata_duplicate_rejected_before_pack(self):
        metadata_path = self.root / "metadata.json"
        raw = json.dumps(self.meta)
        metadata_path.write_text(raw.replace(
            '"privacy": {', '"privacy": {"sanitized": false}, "privacy": {'
        ))
        result = subprocess.run(
            [sys.executable, "-m", "services.artifact_store", "pack",
             "--source", str(self.source), "--output", str(self.pack),
             "--metadata", str(metadata_path),
             "--file", "config.json", "--file", "snapshots.jsonl", "--file", "metrics.json"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.pack.exists())

    def test_duplicate_downloaded_artifact_and_manifest_rejected(self):
        self.build()
        bucket = MockBucket()
        upload_pack(self.pack, bucket)
        prefix = self.meta["run_id"]
        metrics_key = next(k for k in bucket.files if k.endswith("metrics.json"))
        manifest_key = next(k for k in bucket.files if k.endswith("manifest.json"))
        original_manifest = bucket.files[manifest_key]
        original_metrics = bucket.files[metrics_key]
        payload = b'{"schema":"knight26.aggregate.v1","metrics":{"score":"raw report","score":0.5}}'
        bucket.files[metrics_key] = payload
        manifest = json.loads(original_manifest)
        entry = next(x for x in manifest["files"] if x["path"] == "metrics.json")
        entry.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        bucket.files[manifest_key] = json.dumps(manifest).encode()
        destination = self.root / "retrieved"
        with self.assertRaises(ArtifactError):
            fetch_pack(bucket, prefix, destination)
        self.assertFalse(destination.exists())
        bucket.files[metrics_key] = original_metrics
        bucket.files[manifest_key] = original_manifest.replace(
            b'"privacy":{', b'"privacy":{"sanitized":false,'
        )
        with self.assertRaises(ArtifactError):
            fetch_pack(bucket, prefix, destination)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
