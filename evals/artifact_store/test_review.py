"""Focused regression tests for the independent Bucket review."""
import json
import tempfile
import unittest
from pathlib import Path

from evals.artifact_store.test_store import MockBucket, metadata, source_files
from services.artifact_store import ArtifactError, build_pack, fetch_pack, upload_pack


class ReviewRegressions(unittest.TestCase):
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
        return build_pack(self.source, self.pack, self.meta,
                          ["config.json", "snapshots.jsonl", "metrics.json"])

    def test_freeform_private_content_rejected(self):
        for payload in ('{"notes":"Jane Doe at 10 Main St","blob":"raw audio"}',
                        '{"schema":"knight26.aggregate.v1","metrics":{"score":"Jane Doe"}}'):
            (self.source / "metrics.json").write_text(payload)
            with self.assertRaises(ArtifactError):
                self.build()

    def test_unbound_provenance_rejected(self):
        bad = dict(self.meta)
        bad["provenance"] = dict(self.meta["provenance"], source="x")
        with self.assertRaises(ArtifactError):
            build_pack(self.source, self.pack, bad,
                       ["config.json", "snapshots.jsonl", "metrics.json"])

    def test_partial_upload_can_resume_without_overwriting(self):
        self.build()
        bucket = MockBucket()
        bucket.fail_after = 1
        with self.assertRaises(OSError):
            upload_pack(self.pack, bucket)
        before = dict(bucket.files)
        bucket.fail_after = None
        self.assertEqual(upload_pack(self.pack, bucket)["status"], "verified")
        for key, value in before.items():
            self.assertEqual(bucket.files[key], value)
            self.assertEqual(bucket.upload_calls.count(key), 1)

    def test_oversized_manifest_rejected(self):
        self.build()
        bucket = MockBucket()
        upload_pack(self.pack, bucket)
        key = next(k for k in bucket.files if k.endswith("manifest.json"))
        bucket.files[key] = b" " * 100000 + bucket.files[key]
        with self.assertRaises(ArtifactError):
            fetch_pack(bucket, self.meta["run_id"], self.root / "retrieved")
        self.assertFalse((self.root / "retrieved").exists())

    def test_manifest_file_count_bound(self):
        self.build()
        bucket = MockBucket()
        upload_pack(self.pack, bucket)
        key = next(k for k in bucket.files if k.endswith("manifest.json"))
        manifest = json.loads(bucket.files[key])
        manifest["files"] *= 100
        bucket.files[key] = json.dumps(manifest).encode()
        with self.assertRaises(ArtifactError):
            fetch_pack(bucket, self.meta["run_id"], self.root / "retrieved")


if __name__ == "__main__":
    unittest.main()
