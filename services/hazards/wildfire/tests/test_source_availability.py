"""Dated source availability is a temporal gate, not a source-fact check."""
import copy
import unittest

from services.hazards.wildfire.availability import source_availability

EPOCH = "2026-10-10T00:00:00Z"


def source(source_id="s", kind="synthetic", retrieved=EPOCH, observed=None):
    return {"source_id": source_id, "kind": kind, "retrieved_at_utc": retrieved,
            "observed_at_utc": observed, "license": "CC0-1.0",
            "uri": None if kind == "synthetic" else "https://example.test/source"}


class SourceAvailabilityTests(unittest.TestCase):
    def test_available_record_preserves_ledger_and_latest_time(self):
        ledger = [source("s1", "observed", "2026-10-10T00:00:20Z",
                         "2026-10-10T00:00:10Z"),
                  source("s2", retrieved="2026-10-10T00:00:15Z")]
        original = copy.deepcopy(ledger)
        result = source_availability(ledger, EPOCH, 20)
        self.assertEqual("available", result["status"])
        self.assertEqual(EPOCH, result["epoch_utc"])
        self.assertEqual(20, result["checked_at_s"])
        self.assertEqual(20, result["available_from_s"])
        self.assertEqual(["s1", "s2"], result["source_ids"])
        self.assertEqual(original, result["source_ledger"])
        self.assertEqual(original, ledger)
        result["source_ledger"][0]["source_id"] = "changed"
        self.assertEqual(original, ledger)

    def test_pre_epoch_sources_are_available_at_zero(self):
        result = source_availability([source(retrieved="2026-10-09T23:59:50Z")], EPOCH, 0)
        self.assertEqual(0, result["available_from_s"])

    def test_future_retrieval_cannot_be_issued_early(self):
        with self.assertRaises(ValueError):
            source_availability([source(retrieved="2026-10-10T00:00:20Z")], EPOCH, 19)

    def test_future_observation_and_bad_temporal_order_rejected(self):
        cases = [source("s", "observed", "2026-10-10T00:00:20Z",
                        "2026-10-10T00:00:15Z"),
                 source("s", "observed", "2026-10-10T00:00:05Z",
                        "2026-10-10T00:00:10Z")]
        for entry in cases:
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    source_availability([entry], EPOCH, 10)

    def test_missing_undated_duplicate_and_invalid_issue_rejected(self):
        cases = [([], EPOCH, 0), ([source(), source()], EPOCH, 0),
                 ([dict(source(), retrieved_at_utc=None)], EPOCH, 0),
                 ([dict(source(), kind="observed")], EPOCH, 0),
                 ([dict(source(), kind="unrecognized")], EPOCH, 0),
                 ([dict(source(), kind=[])], EPOCH, 0),
                 ([source()], "2026-10-10T00:00:00", 0),
                 ([source(retrieved="2026-10-10T00:00:00")], EPOCH, 0),
                 ([source()], EPOCH, float("inf")),
                 ([source()], EPOCH, -1)]
        for ledger, epoch, issue in cases:
            with self.subTest(ledger=ledger, epoch=epoch, issue=issue):
                with self.assertRaises(ValueError):
                    source_availability(ledger, epoch, issue)


    def test_nonsynthetic_sources_need_license_and_http_uri(self):
        for kind in ("observed", "mapped", "model_reference"):
            valid = source(kind=kind, observed=EPOCH if kind == "observed" else None)
            self.assertEqual("available", source_availability([valid], EPOCH, 0)["status"])
            for change in ({"license": ""}, {"license": None}, {"uri": None},
                           {"uri": ""}, {"uri": "ftp://example.test/source"},
                           {"uri": "https://"}):
                with self.subTest(kind=kind, change=change):
                    with self.assertRaises(ValueError):
                        source_availability([dict(valid, **change)], EPOCH, 0)

    def test_synthetic_source_still_needs_license(self):
        with self.assertRaises(ValueError):
            source_availability([dict(source(), license=" ")], EPOCH, 0)


if __name__ == "__main__":
    unittest.main()
