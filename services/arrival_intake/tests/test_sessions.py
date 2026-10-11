"""Session acceptance tests; fixtures follow the live RoutingExecutor snapshot."""
import copy
import dataclasses
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.arrival_intake.contracts import Assessment, Conflict, Missing, Principal, SessionSeed
from services.arrival_intake.store import IntakeStore
from services.arrival_intake.trip_adapter import session_seed


def completed_snapshot():
    people = [f"sim-person-{i}" for i in range(30)]
    return {
        "run_id": "run-demo", "snapshot_version": 8,
        "trips": [{"dispatch_id": "dispatch-3", "vehicle_id": "bus-3",
                   "request_id": "request-3", "phase": "completed",
                   "passenger_ids": [], "committed_passengers": []}],
        "ledger": {
            "requests": {"request-3": {"request_id": "request-3", "kind": "evacuation",
                                       "destination_node": "shelter-1", "remaining_people": []}},
            "assignments": {"dispatch-3": {"dispatch_id": "dispatch-3", "vehicle_id": "bus-3",
                "request_id": "request-3", "person_ids": people, "phase": "completed"}},
            "audit_events": [
                {"event_id": "ledger-1", "type": "dispatch_committed", "dispatch_id": "dispatch-3",
                 "time_s": 0, "details": {"person_ids": people, "cargo": {}}},
                {"event_id": "ledger-2", "type": "departure", "dispatch_id": "dispatch-3",
                 "time_s": 10, "details": {}},
                {"event_id": "ledger-3", "type": "arrival", "dispatch_id": "dispatch-3",
                 "time_s": 20, "details": {"node_id": "shelter-1"}},
            ],
        }, "events": [],
    }


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database_path = Path(self.temp.name) / "intake.sqlite"
        self.completed_bus_snapshot = completed_snapshot()

    def store(self):
        store = IntakeStore(self.database_path)
        self.addCleanup(store.close)
        return store

    def seed(self, snapshot=None):
        return session_seed("case-demo", snapshot or self.completed_bus_snapshot, "dispatch-3")

    def test_completed_trip_preserves_boarding_count(self):
        seed = self.seed()
        self.assertEqual(seed.expected_count, 30)
        self.assertEqual(seed.boarding_event_id, "ledger-1")
        self.assertEqual(seed.departure_event_id, "ledger-2")
        store = self.store()
        first = store.create_session(seed)
        again = store.create_session(seed)
        self.assertEqual(first["session_id"], again["session_id"])
        self.assertEqual(store.summary(first["session_id"])["confirmed_count"], 0)

    def test_reopened_database_preserves_session_and_summary_contract(self):
        original_store = self.store()
        first = original_store.create_session(self.seed())
        original_store.close()
        summary = self.store().summary(first["session_id"])
        self.assertEqual(first, summary)
        self.assertEqual(set(summary), {"session_id", "case_id", "run_id", "dispatch_id", "vehicle_id",
            "destination_node", "mode", "expected_count", "original_expected_count", "confirmed_count",
            "difference", "intake_state", "awaiting_reviews", "completed_reviews", "revision"})
        self.assertEqual((summary["mode"], summary["intake_state"], summary["difference"]), ("exercise", "open", 30))
        self.assertEqual((summary["awaiting_reviews"], summary["completed_reviews"], summary["revision"]), (0, 0, 0))
        self.assertNotIn("sim-person-", json.dumps(summary, allow_nan=False))

    def test_source_is_immutable_and_hash_is_canonical(self):
        original = copy.deepcopy(self.completed_bus_snapshot)
        seed = self.seed()
        self.assertEqual(self.completed_bus_snapshot, original)
        reordered = json.loads(json.dumps(original, sort_keys=True))
        self.assertEqual(seed, self.seed(reordered))
        unrelated = copy.deepcopy(original)
        unrelated["snapshot_version"] = 999
        unrelated["ledger"]["requests"]["request-3"]["remaining_people"] = ["changed"]
        self.assertEqual(seed, self.seed(unrelated))
        selected = {"run_id": "run-demo", "dispatch_id": "dispatch-3", "vehicle_id": "bus-3",
            "request_id": "request-3", "kind": "evacuation", "destination_node": "shelter-1",
            "boarding": original["ledger"]["audit_events"][0],
            "departure": original["ledger"]["audit_events"][1],
            "arrival": original["ledger"]["audit_events"][2]}
        self.assertEqual(seed.source_sha256, hashlib.sha256(json.dumps(selected, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            seed.expected_count = 1

    def test_missing_departure_or_arrival_or_boarding_is_rejected(self):
        for event_type in ("departure", "arrival", "dispatch_committed"):
            with self.subTest(event_type=event_type):
                snapshot = copy.deepcopy(self.completed_bus_snapshot)
                snapshot["ledger"]["audit_events"] = [e for e in snapshot["ledger"]["audit_events"] if e["type"] != event_type]
                with self.assertRaises(ValueError): self.seed(snapshot)

    def test_duplicate_person_ids_are_rejected(self):
        snapshot = copy.deepcopy(self.completed_bus_snapshot)
        snapshot["ledger"]["audit_events"][0]["details"]["person_ids"].append("sim-person-0")
        with self.assertRaises(ValueError): self.seed(snapshot)

    def test_supply_and_medical_trips_are_rejected(self):
        for kind in ("supply", "medical"):
            snapshot = copy.deepcopy(self.completed_bus_snapshot)
            snapshot["ledger"]["requests"]["request-3"]["kind"] = kind
            with self.assertRaises(ValueError): self.seed(snapshot)

    def test_mismatched_destination_vehicle_and_boarding_are_rejected(self):
        for mutation in ("destination", "vehicle", "people", "dispatch", "request", "run"):
            with self.subTest(mutation=mutation):
                snapshot = copy.deepcopy(self.completed_bus_snapshot)
                if mutation == "destination": snapshot["ledger"]["audit_events"][2]["details"]["node_id"] = "other"
                if mutation == "vehicle": snapshot["trips"][0]["vehicle_id"] = "other"
                if mutation == "people": snapshot["ledger"]["assignments"]["dispatch-3"]["person_ids"] = ["other"]
                if mutation == "dispatch": snapshot["ledger"]["assignments"]["dispatch-3"]["dispatch_id"] = "other"
                if mutation == "request": snapshot["trips"][0]["request_id"] = "other"
                if mutation == "run": snapshot["ledger"]["audit_events"][1]["run_id"] = "other"
                with self.assertRaises(ValueError): self.seed(snapshot)

    def test_ambiguous_or_misordered_events_are_rejected(self):
        snapshot = copy.deepcopy(self.completed_bus_snapshot)
        snapshot["ledger"]["audit_events"].append(copy.deepcopy(snapshot["ledger"]["audit_events"][1]))
        with self.assertRaises(ValueError): self.seed(snapshot)
        snapshot = copy.deepcopy(self.completed_bus_snapshot)
        snapshot["ledger"]["audit_events"][2]["time_s"] = 1
        with self.assertRaises(ValueError): self.seed(snapshot)

    def test_conflicting_source_does_not_rewrite_expected_count(self):
        seed = self.seed()
        store = self.store()
        first = store.create_session(seed)
        for field, value in (("source_sha256", "f" * 64), ("expected_count", 29),
                             ("vehicle_id", "other"), ("destination_node", "other"),
                             ("boarding_event_id", "other"), ("arrival_event_id", "other")):
            with self.subTest(field=field):
                with self.assertRaises(Conflict): store.create_session(dataclasses.replace(seed, **{field: value}))
        self.assertEqual(store.summary(first["session_id"])["expected_count"], 30)

    def test_cases_and_runs_keep_distinct_sessions(self):
        store = self.store()
        seed = self.seed()
        ids = {store.create_session(s)["session_id"] for s in (seed,
            dataclasses.replace(seed, case_id="case-other"), dataclasses.replace(seed, run_id="run-other"))}
        self.assertEqual(len(ids), 3)

    def test_contract_validation(self):
        seed = self.seed()
        for field, value in (("case_id", ""), ("vehicle_id", " " * 2), ("run_id", "a" * 257),
                             ("expected_count", True), ("expected_count", -1),
                             ("source_sha256", "not-a-hash")):
            with self.assertRaises(ValueError): dataclasses.replace(seed, **{field: value})
        for principal in (("actor", "wrong", frozenset()), ("", "volunteer", frozenset()),
                          ("actor", "volunteer", frozenset({""}))):
            with self.assertRaises(ValueError): Principal(*principal)
        valid = Assessment("arrival", None, 0, "Unsure", "unavailable", "No model available", None)
        for field, value in (("result", "maybe"), ("origin", "model"), ("arrival_revision", True),
                             ("image_sha256", "bad"), ("reason", "")):
            with self.assertRaises(ValueError): dataclasses.replace(valid, **{field: value})

    def test_nonfinite_and_empty_boarding_sources_are_rejected(self):
        for value in (float("nan"), float("inf")):
            snapshot = copy.deepcopy(self.completed_bus_snapshot)
            snapshot["ledger"]["audit_events"][1]["time_s"] = value
            with self.assertRaises(ValueError): self.seed(snapshot)
        snapshot = copy.deepcopy(self.completed_bus_snapshot)
        snapshot["ledger"]["audit_events"][0]["details"]["person_ids"] = []
        snapshot["ledger"]["assignments"]["dispatch-3"]["person_ids"] = []
        with self.assertRaises(ValueError): self.seed(snapshot)

    def test_schema_constraints_and_connection_settings(self):
        store = self.store()
        store.create_session(self.seed())
        self.assertEqual(store.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(store.connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertGreater(store.connection.execute("PRAGMA busy_timeout").fetchone()[0], 0)
        tables = {r[0] for r in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"sessions", "arrivals", "operations", "events", "images", "assessments", "reviews"}.issubset(tables))
        with self.assertRaises(sqlite3.IntegrityError):
            store.connection.execute("INSERT INTO arrivals(arrival_id,session_id,display_number,state,revision) VALUES ('a','missing',1,'draft',0)")

    def test_missing_session_is_reported(self):
        with self.assertRaises(Missing): self.store().summary("unknown")
        with self.assertRaises(ValueError): self.store().summary("")


if __name__ == "__main__":
    unittest.main()


