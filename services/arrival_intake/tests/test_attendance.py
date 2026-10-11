"""Attendance tests use durable SQLite records and independent connections."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from services.arrival_intake.contracts import Conflict, Missing, SessionSeed
from services.arrival_intake.store import IntakeStore


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "intake.sqlite"
        self.store = IntakeStore(self.db)
        self.addCleanup(self.store.close)
        self.sid = self.store.create_session(SessionSeed(
            "case-demo", "run-1", "dispatch-1", "bus-1", "shelter-1", 2,
            "boarding-1", "arrival-event-1", "a" * 64, "departure-1"))["session_id"]

    def confirm(self, key="person-1"):
        return self.store.confirm_arrival(self.sid, key, "volunteer-a")

    def test_lost_response_and_process_reopen_count_once(self):
        first = self.confirm()
        with IntakeStore(self.db) as reopened:
            retry = reopened.confirm_arrival(self.sid, "person-1", "volunteer-a")
            self.assertEqual(retry, first)
            self.assertEqual(reopened.summary(self.sid)["confirmed_count"], 1)
            detail = reopened.detail(first["arrival_id"])
            self.assertEqual(detail["confirmed_by"], "volunteer-a")
            self.assertEqual(detail["state"], "confirmed")
            self.assertEqual(detail["arrival_number"], 1)

    def test_reusing_key_with_different_actor_conflicts_without_counting(self):
        self.confirm()
        with self.assertRaises(Conflict):
            self.store.confirm_arrival(self.sid, "person-1", "volunteer-b")
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)

    def test_independent_connections_same_operation_count_once(self):
        barrier = Barrier(2)
        def submit(_):
            with IntakeStore(self.db) as store:
                barrier.wait(timeout=5)
                return store.confirm_arrival(self.sid, "same-operation", "volunteer-a")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        self.assertEqual(results[0]["arrival_id"], results[1]["arrival_id"])
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)

    def test_concurrent_distinct_operations_allocate_distinct_numbers(self):
        barrier = Barrier(2)
        def submit(key):
            with IntakeStore(self.db) as store:
                barrier.wait(timeout=5)
                return store.confirm_arrival(self.sid, key, "volunteer-a")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, ("person-1", "person-2")))
        self.assertEqual({r["arrival_number"] for r in results}, {1, 2})
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def test_overcount_is_preserved(self):
        for key in ("one", "two", "three"):
            self.confirm(key)
        summary = self.store.summary(self.sid)
        self.assertEqual(summary["confirmed_count"], 3)
        self.assertEqual(summary["difference"], -1)
        self.assertEqual(summary["expected_count"], 2)

    def test_finish_preserves_mismatch_and_pending_care(self):
        arrival = self.confirm()
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO reviews(review_id,arrival_id,required_revision,state,reason,created_at) "
                "VALUES ('review-1',?,0,'awaiting','human concern','2026-10-10T00:00:00Z')",
                (arrival["arrival_id"],))
        summary = self.store.finish_intake(self.sid, 1, "volunteer-a")
        self.assertEqual(summary["intake_state"], "finished")
        self.assertEqual(summary["difference"], 1)
        self.assertEqual(summary["awaiting_reviews"], 1)
        self.assertEqual(summary["completed_reviews"], 0)
        self.assertEqual(summary["revision"], 2)

    def test_stale_finish_or_correction_does_not_mutate(self):
        self.confirm()
        for operation in (
            lambda: self.store.finish_intake(self.sid, 0, "volunteer-a"),
            lambda: self.store.correct(self.sid, 0, "coordinator-a", "recount", {"expected_count": 3}),
        ):
            with self.assertRaises(Conflict):
                operation()
        self.assertEqual(self.store.summary(self.sid)["intake_state"], "open")
        self.assertEqual(self.store.summary(self.sid)["expected_count"], 2)

    def test_corrections_keep_original_values_actor_and_history(self):
        first = self.confirm("one")
        self.confirm("two")
        summary = self.store.correct(self.sid, 2, "coordinator-a", "boarding recount", {"expected_count": 3})
        self.assertEqual(summary["original_expected_count"], 2)
        self.assertEqual(summary["expected_count"], 3)
        summary = self.store.correct(self.sid, 3, "coordinator-a", "duplicate entry", {
            "arrival_id": first["arrival_id"], "counted": False})
        self.assertEqual(summary["confirmed_count"], 1)
        third = self.confirm("three")
        self.assertEqual(third["arrival_number"], 3)
        self.assertEqual(self.store.detail(first["arrival_id"])["state"], "voided")
        events = self.store.connection.execute(
            "SELECT * FROM events WHERE event_type='attendance_correction' ORDER BY rowid").fetchall()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["actor_id"], "coordinator-a")
        self.assertEqual(events[0]["reason"], "boarding recount")
        self.assertEqual(json.loads(events[0]["before_json"])["expected_count"], 2)
        self.assertEqual(json.loads(events[0]["after_json"])["expected_count"], 3)
        self.assertEqual(json.loads(events[1]["before_json"])["state"], "confirmed")
        self.assertEqual(json.loads(events[1]["after_json"])["state"], "voided")

    def test_finished_intake_rejects_new_arrival_but_allows_retry_and_explicit_reopen(self):
        first = self.confirm()
        self.store.finish_intake(self.sid, 1, "volunteer-a")
        self.assertEqual(self.confirm(), first)
        with self.assertRaises(Conflict):
            self.confirm("new-person")
        reopened = self.store.correct(self.sid, 2, "coordinator-a", "late passenger", {"intake_state": "open"})
        self.assertEqual(reopened["intake_state"], "open")
        self.assertEqual(self.confirm("new-person")["session_summary"]["confirmed_count"], 2)

    def test_invalid_corrections_never_change_records(self):
        for change in ({"expected_count": True}, {"expected_count": -1},
                       {"intake_state": "finished"}, {"expected_count": 3, "extra": 4}):
            with self.assertRaises(ValueError):
                self.store.correct(self.sid, 0, "coordinator-a", "reason", change)
        with self.assertRaises(ValueError):
            self.store.correct(self.sid, 0, "coordinator-a", "", {"expected_count": 3})
        with self.assertRaises(ValueError):
            self.store.finish_intake(self.sid, True, "volunteer-a")
        self.assertEqual(self.store.summary(self.sid)["revision"], 0)
        with self.assertRaises(Missing):
            self.store.detail("missing-arrival")


if __name__ == "__main__":
    unittest.main()
