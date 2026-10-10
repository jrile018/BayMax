"""Budget reservations with a fully mocked SDK; no Hub/network/auth calls."""
import concurrent.futures
import tempfile
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

from services.artifact_store.hf_backend import HfBucketBackend, SetupNeeded


def mocked_backend(budget):
    sdk = types.ModuleType("huggingface_hub")
    sdk.bucket_info = lambda bucket_id: types.SimpleNamespace(private=True)
    sdk.list_bucket_tree = lambda *args, **kwargs: []
    sdk.batch_bucket_files = lambda *args, **kwargs: None
    sdk.download_bucket_files = lambda *args, **kwargs: None
    sdk.get_token = lambda: "mock-token"
    with patch.dict(sys.modules, {"huggingface_hub": sdk}), patch(
        "services.artifact_store.hf_backend.importlib.metadata.version", return_value="2.2.0"
    ):
        return HfBucketBackend("mock/private", remaining_free_bytes=budget,
                               caller_confirmed_free_quota=True,
                               isolated_client_environment=True)


class BackendBudgetTests(unittest.TestCase):
    def test_sequential_reservations_never_exceed_initial_budget(self):
        backend = mocked_backend(100)
        backend.preflight_upload(60)
        with self.assertRaises(SetupNeeded):
            backend.preflight_upload(50)
        self.assertEqual(backend.remaining_free_bytes, 40)
        backend.preflight_upload(40)
        self.assertEqual(backend.remaining_free_bytes, 0)
        with self.assertRaises(SetupNeeded):
            backend.preflight_upload(1)

    def test_concurrent_reservations_cannot_oversubscribe(self):
        backend = mocked_backend(100)
        barrier = threading.Barrier(10)

        def reserve():
            barrier.wait()
            try:
                backend.preflight_upload(15)
                return True
            except SetupNeeded:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: reserve(), range(10)))
        self.assertEqual(sum(results), 6)
        self.assertEqual(backend.remaining_free_bytes, 10)

    def test_upload_requires_reservation_and_failed_batch_does_not_refund(self):
        backend = mocked_backend(10)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "data.json"
            path.write_bytes(b"12345")
            with self.assertRaises(SetupNeeded):
                backend.upload_files([(path, "runs/mock/data.json")])
            self.assertEqual(backend.remaining_free_bytes, 10)
            backend.preflight_upload(5)
            backend._upload = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ambiguous mock failure"))
            with self.assertRaises(OSError):
                backend.upload_files([(path, "runs/mock/data.json")])
            self.assertEqual(backend.remaining_free_bytes, 5)
            with self.assertRaises(SetupNeeded):
                backend.upload_files([(path, "runs/mock/data.json")])

    def test_invalid_counts_rejected_without_changing_budget(self):
        backend = mocked_backend(100)
        for count in (True, False, -1, 1.5, "5"):
            with self.subTest(count=count), self.assertRaises(SetupNeeded):
                backend.preflight_upload(count)
        self.assertEqual(backend.remaining_free_bytes, 100)


if __name__ == "__main__":
    unittest.main()
