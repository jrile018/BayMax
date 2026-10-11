"""UNEXECUTED fictional controls; no dataset/model/rights or benchmark evidence."""
import json
import unittest
from services.evidence_lab.datasets import Bounds, SECTORS, SelectionError, fictional_rows, select_humset
from services.evidence_lab.select import pack_bytes


def row(ident, *, language="en", document=None, lead=None, text=None):
    return {"entry_id": ident, "document": document or f"fictional-doc-{ident}",
            "lead_id": lead or f"fictional-lead-{ident}", "project_id": "fictional-project",
            "lang": language, "sectors": ["Health"],
            "excerpt": text or f"FICTIONAL EXERCISE ONLY item {ident}: 20 people."}


def select(rows, **kwargs):
    options = {"dev_count": 1, "test_count": 2, "target_languages": {"en": 1, "fr": 1}}
    options.update(kwargs)
    return select_humset(rows, **options)


class SyntheticSelectionControls(unittest.TestCase):
    def test_default_selection_and_frozen_language_sector_counts(self):
        result = select_humset(fictional_rows()).to_dict()
        self.assertEqual((result["actual_dev"], result["actual_test"]), (16, 64))
        self.assertEqual(result["actual_test_languages"], {"en": 32, "es": 16, "fr": 16})
        self.assertEqual(set(result["sector_coverage"]), set(SECTORS))
        self.assertFalse(result["scoring_allowed"])
        self.assertEqual(result["benchmark_result"], "UNRUN")

    def test_stable_selection_despite_prefix_order_and_exact_diagnostic_hash(self):
        rows = fictional_rows()
        first = select_humset(rows)
        second = select_humset({key: list(reversed(value)) for key, value in rows.items()})
        self.assertEqual(first.metadata["dev"], second.metadata["dev"])
        self.assertEqual(first.metadata["test"], second.metadata["test"])
        self.assertNotEqual(first.metadata["canonical_split_id_prefix_sha256"],
                            second.metadata["canonical_split_id_prefix_sha256"])
        self.assertEqual(first.to_dict(), select_humset(rows).to_dict())

    def test_dev_first_document_lead_and_id_conflicts_excluded(self):
        rows = {"validation": [row("dev", document="same-doc", lead="same-lead")],
                "test": [row("dev"), row("doc", document="same-doc"),
                         row("lead", lead="same-lead"), row("safe"), row("fr", language="fr")]}
        result = select(rows).to_dict()
        self.assertEqual({value["entry_id"] for value in result["test"]}, {"safe", "fr"})
        self.assertEqual(result["exclusions"]["development_group_overlap"], 3)
        self.assertEqual(result["selected_project_overlap_count"], 1)

    def test_short_stratum_is_actual_shortfall_not_reallocated(self):
        result = select({"validation": [row("d")], "test": [row("e1"), row("e2")]}).to_dict()
        self.assertEqual(result["actual_test"], 1)
        self.assertEqual(result["language_shortfall"], {"en": 0, "fr": 1})
        self.assertFalse(result["selection_complete"])

    def test_no_excerpt_or_fabricated_quantity_gold_in_manifest(self):
        result = select({"validation": [row("d")], "test": [row("e"), row("f", language="fr")]})
        manifest = json.dumps(result.to_dict())
        self.assertNotIn("20 people", manifest)
        self.assertNotIn('"quantity"', manifest)
        self.assertEqual(result.metadata["operational_field_gold"], "not_annotated")
        self.assertTrue(all(value["data_label"] == "synthetic_exercise" for value in result.private_excerpts))

    def test_incomplete_stream_preserves_scanned_ids_and_blocks_scoring(self):
        def broken():
            yield row("seen")
            raise OSError("private raw exception must not be copied")
        result = select({"validation": broken(), "test": []}).to_dict()
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["actual_scanned_count"]["validation"], 1)
        self.assertEqual(result["ordered_candidate_ids"]["validation"], ["seen"])
        self.assertEqual(result["error_stage"], "source_stream")
        self.assertNotIn("private raw", json.dumps(result))
        self.assertFalse(result["scoring_allowed"])

    def test_fixed_prefix_stops_without_reading_beyond_endpoint(self):
        def limited():
            yield row("a")
            yield row("b")
            raise AssertionError("prefix overread")
        result = select({"validation": limited(), "test": []},
                        bounds=Bounds(max_scan_per_split=2)).to_dict()
        self.assertEqual(result["prefix_endpoints"]["validation"], "fixed_prefix")
        self.assertEqual(result["actual_scanned_count"]["validation"], 2)

    def test_utf8_byte_boundary_and_invalid_taxonomy_fail_incomplete(self):
        for text, valid in (("é" * 4, True), ("é" * 5, False)):
            result = select({"validation": [row("d", text=text)], "test": []},
                            bounds=Bounds(max_excerpt_utf8_bytes=8)).to_dict()
            self.assertEqual(result["status"] == "complete", valid)
        bad = row("bad")
        bad["sectors"] = ["Invented Sector"]
        result = select({"validation": [bad], "test": []}).to_dict()
        self.assertEqual(result["error_stage"], "row_validation")

    def test_candidate_text_and_transport_bounds_have_diagnostics(self):
        for bounds, stage in ((Bounds(max_candidate_bytes=4096), "candidate_memory_budget"),
                              (Bounds(max_private_selected_text_bytes=1), "private_text_budget"),
                              (Bounds(max_transport_bytes=1), "transport_budget")):
            with self.subTest(stage=stage):
                result = select({"validation": [row("d")], "test": []}, bounds=bounds).to_dict()
                self.assertEqual(result["status"], "incomplete")
                self.assertEqual(result["error_stage"], stage)

    def test_typed_id_identity_not_collapsed_and_duplicate_id_blocked(self):
        result = select({"validation": [row(1, document="integer-doc", lead="integer-lead")],
                         "test": [row("1", document="string-doc", lead="string-lead"),
                                  row("fr", language="fr")]}).to_dict()
        self.assertEqual(result["actual_test"], 2)
        duplicate = select({"validation": [row("d"), row("d")], "test": []}).to_dict()
        self.assertEqual(duplicate["status"], "incomplete")

    def test_normalized_near_duplicate_audit_is_bounded_not_upstream_proof(self):
        result = select({"validation": [row("d", text="FICTIONAL: Aid Item!")],
                         "test": [row("e", text="fictional aid item"), row("f", language="fr")]}).to_dict()
        self.assertEqual(result["bounded_near_duplicate_audit"]
                         ["test_ids_matching_validation_normalized_text"], ["e"])
        self.assertFalse(result["prefix_hash_is_upstream_full_file_verification"])

    def test_private_pack_has_manifest_last_exact_file_hashes_and_synthetic_labels(self):
        from hashlib import sha256
        files = pack_bytes(select_humset(fictional_rows()))
        self.assertEqual(list(files)[-1], "manifest.json")
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(manifest["data_label"], "synthetic_exercise")
        for name, info in manifest["files"].items():
            self.assertEqual(info, {"bytes": len(files[name]),
                                    "sha256": sha256(files[name]).hexdigest()})

    def test_empty_stream_budget_cannot_bypass_fixed_overhead(self):
        with self.assertRaises(SelectionError):
            select({"validation": [], "test": []}, bounds=Bounds(max_candidate_bytes=4095))
        result = select({"validation": [], "test": []},
                        bounds=Bounds(max_candidate_bytes=4096)).to_dict()
        self.assertEqual(result["candidate_memory_accounted_bytes"], 4096)
        self.assertEqual(result["status"], "complete")
        self.assertFalse(result["scoring_allowed"])

    def test_configuration_limits_cannot_expand_or_change_splits(self):
        with self.assertRaises(SelectionError):
            select({"validation": [], "test": []}, bounds=Bounds(max_scan_per_split=5001))
        with self.assertRaises(SelectionError):
            select_humset({"train": [], "test": []})
        with self.assertRaises(SelectionError):
            select_humset({"validation": [], "test": []}, target_languages={"en": 1})


if __name__ == "__main__":
    unittest.main()
