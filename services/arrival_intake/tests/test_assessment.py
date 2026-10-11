"""Assessment origin and input binding at the pure decision boundary."""

import unittest

from services.arrival_intake.assessment import assess


HASH = "a" * 64
RECEIPT = {
    "task": "visible_marks",
    "model_revision": "fixture-model-revision",
    "evaluation_artifact_sha256": "b" * 64,
    "verified": True,
}


class AssessmentTests(unittest.TestCase):
    def test_no_photo_is_unsure_even_in_scripted_mode(self):
        for mode in ("scripted", "real", "skipped"):
            with self.subTest(mode=mode):
                result = assess("arrival-7", 3, None, mode=mode,
                                scripted_result="No")
                self.assertEqual((result.result, result.origin), ("Unsure", "unavailable"))
                self.assertIsNone(result.image_sha256)
                self.assertIsNone(result.model_revision)
                self.assertIn("photo", result.reason.lower())

    def test_no_runner_means_unsure(self):
        result = assess("arrival-7", 3, HASH, mode="real")
        self.assertEqual((result.result, result.origin), ("Unsure", "unavailable"))
        self.assertIsNone(result.model_revision)

    def test_scripted_no_is_visibly_scripted(self):
        result = assess("arrival-7", 3, HASH, mode="scripted", scripted_result="No")
        self.assertEqual((result.result, result.origin), ("No", "scripted_training"))
        self.assertEqual((result.arrival_revision, result.image_sha256), (3, HASH))
        self.assertIsNone(result.model_revision)
        self.assertIn("Scripted", result.reason)

    def test_scripted_fixture_accepts_only_declared_labels(self):
        for value in (None, "Clear", "no", True, 0, {}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    assess("arrival-7", 3, HASH, mode="scripted",
                           scripted_result=value)
        for label in ("Yes", "No", "Unsure"):
            self.assertEqual(assess("arrival-7", 3, HASH, mode="scripted",
                                    scripted_result=label).result, label)

    def test_skipped_is_unsure_and_never_calls_runner(self):
        called = []
        def runner(*args):
            called.append(args)
            return {"result": "No", "model_revision": RECEIPT["model_revision"],
                    "arrival_revision": 3, "image_sha256": HASH}
        result = assess("arrival-7", 3, HASH, mode="skipped",
                        evaluated_runner=runner, evaluation_receipt=RECEIPT)
        self.assertEqual((result.result, result.origin), ("Unsure", "unavailable"))
        self.assertEqual(called, [])

    def test_unverified_or_malformed_receipt_never_calls_runner(self):
        called = []
        def runner(*args):
            called.append(args)
            return {"result": "No", "model_revision": RECEIPT["model_revision"],
                    "arrival_revision": 3, "image_sha256": HASH}
        bad_receipts = (
            None, {}, True,
            {**RECEIPT, "verified": 1},
            {**RECEIPT, "verified": False},
            {**RECEIPT, "task": "face_identity"},
            {**RECEIPT, "model_revision": ""},
            {**RECEIPT, "evaluation_artifact_sha256": "x" * 64},
            {**RECEIPT, "evaluation_artifact_sha256": "b" * 63},
            {**RECEIPT, "extra": "browser-supplied"},
        )
        for receipt in bad_receipts:
            with self.subTest(receipt=receipt):
                result = assess("arrival-7", 3, HASH, mode="real",
                                evaluated_runner=runner, evaluation_receipt=receipt)
                self.assertEqual((result.result, result.origin), ("Unsure", "unavailable"))
                self.assertIsNone(result.model_revision)
        self.assertEqual(called, [])

    def test_real_runner_result_must_match_current_image_revision_and_configured_model(self):
        # A late result must never become current, including a same-bytes retake.
        for response in (
            {"result": "No", "model_revision": RECEIPT["model_revision"],
             "arrival_revision": 2, "image_sha256": HASH},
            {"result": "No", "model_revision": RECEIPT["model_revision"],
             "arrival_revision": 3, "image_sha256": "c" * 64},
            {"result": "No", "model_revision": "different-model",
             "arrival_revision": 3, "image_sha256": HASH},
            {"result": "No", "model_revision": RECEIPT["model_revision"]},
        ):
            with self.subTest(response=response):
                result = assess("arrival-7", 3, HASH, mode="real",
                                evaluated_runner=lambda *_: response,
                                evaluation_receipt=RECEIPT)
                self.assertEqual((result.result, result.origin), ("Unsure", "unavailable"))
                self.assertIsNone(result.model_revision)

    def test_runner_failures_and_nonclassifications_are_unsure(self):
        def failing(*_):
            raise TimeoutError("runner timed out")
        for runner in (
            failing,
            lambda *_: None,
            lambda *_: {"status": "no_face"},
            lambda *_: {"status": "decode_failed"},
            lambda *_: {"result": "clear", "model_revision": RECEIPT["model_revision"],
                        "arrival_revision": 3, "image_sha256": HASH},
        ):
            with self.subTest(runner=runner):
                result = assess("arrival-7", 3, HASH, mode="real",
                                evaluated_runner=runner, evaluation_receipt=RECEIPT)
                self.assertEqual((result.result, result.origin), ("Unsure", "unavailable"))
                self.assertIsNone(result.model_revision)

    def test_verified_root_configured_runner_can_report_evaluated_origin(self):
        def runner(arrival_id, arrival_revision, image_sha256):
            self.assertEqual((arrival_id, arrival_revision, image_sha256),
                             ("arrival-7", 3, HASH))
            return {"result": "No", "model_revision": RECEIPT["model_revision"],
                    "arrival_revision": arrival_revision, "image_sha256": image_sha256}
        result = assess("arrival-7", 3, HASH, mode="real",
                        evaluated_runner=runner, evaluation_receipt=RECEIPT)
        self.assertEqual((result.result, result.origin), ("No", "evaluated_model"))
        self.assertEqual(result.model_revision, RECEIPT["model_revision"])

    def test_invalid_mode_revision_and_hash_are_rejected(self):
        for mode in ("unlabeled", "REAL", None):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    assess("arrival-7", 3, HASH, mode=mode)
        for revision in (True, -1, 1.0):
            with self.subTest(revision=revision):
                with self.assertRaises(ValueError):
                    assess("arrival-7", revision, HASH, mode="real")
        with self.assertRaises(ValueError):
            assess("arrival-7", 3, "invalid", mode="real")


if __name__ == "__main__":
    unittest.main()
