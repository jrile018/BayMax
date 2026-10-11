"""Care referrals are tied to a confirmed arrival and its current evidence."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from services.arrival_intake.contracts import Assessment, Conflict, SessionSeed
from services.arrival_intake.photos import PhotoStore
from services.arrival_intake.store import IntakeStore
from services.arrival_intake.workflow import ExerciseAssessor, Workflow


def illustration():
    output = BytesIO()
    Image.new("RGB", (8, 8), (170, 80, 50)).save(output, format="PNG")
    return output.getvalue()


class CareReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = IntakeStore(Path(directory.name) / "intake.sqlite")
        self.addCleanup(self.store.close)
        self.sid = self.store.create_session(SessionSeed(
            case_id="care-case", run_id="care-run", dispatch_id="care-dispatch",
            vehicle_id="bus-1", destination_node="shelter-1", expected_count=3,
            boarding_event_id="boarding", arrival_event_id="arrival",
            source_sha256="a" * 64,
        ))["session_id"]
        self.image = illustration()
        self.digest = sha256(self.image).hexdigest()
        self.photos = PhotoStore(self.store, {"illustration-a": {
            "source_kind": "operator_created_illustration",
            "image_sha256s": frozenset({self.digest}),
            "capture_allowed": True, "display_allowed": True, "processing_allowed": True,
        }})
        self.workflow = Workflow(self.store, self.photos,
                                 ExerciseAssessor({1: "No", 2: "Unsure", 3: "Yes"}))

    def arrival(self, number):
        return self.store.confirm_arrival(self.sid, f"confirm-{number}", "volunteer-a")["arrival_id"]

    def photo(self, aid):
        detail = self.store.detail(aid)
        return self.photos.attach(aid, "volunteer-a", detail["revision"], self.image,
                                  "image/png", {
            "source_kind": "operator_created_illustration",
            "source_reference": "illustration-a", "capture_allowed": True,
            "display_allowed": True, "processing_allowed": True,
            "verified_by": "volunteer-a", "verified_at": "2026-10-10T12:00:00+00:00",
        })

    def test_no_with_human_concern_requires_review_and_preserves_attendance(self):
        aid = self.arrival(1)
        capture = self.photo(aid)
        detail = self.workflow.request_assessment(aid, capture["arrival_revision"],
                                                   "volunteer-a", "scripted")
        self.assertEqual(detail["assessment"]["result"], "No")
        self.assertEqual(detail["care_state"], "not_referred")
        flagged = self.workflow.record_concern(aid, detail["revision"],
                                                "volunteer-a", "Reported pain")
        self.assertEqual(flagged["care_state"], "awaiting_review")
        self.assertEqual(len(flagged["human_concerns"]), 1)
        self.assertEqual(self.store.summary(self.sid)["awaiting_reviews"], 1)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)
        self.assertEqual(len(self.workflow.list_reviews(self.sid)), 1)

    def test_repeated_unsure_does_not_duplicate_an_active_review(self):
        self.arrival(1)
        aid = self.arrival(2)
        self.photo(aid)
        first = self.workflow.request_assessment(aid, self.store.detail(aid)["revision"],
                                                  "volunteer-a", "scripted")
        self.assertEqual(first["assessment"]["result"], "Unsure")
        second = self.workflow.request_assessment(aid, first["revision"],
                                                   "volunteer-a", "scripted")
        self.assertEqual(second["care_state"], "awaiting_review")
        self.assertEqual(second["review_revision"], first["review_revision"])
        self.assertEqual(self.store.summary(self.sid)["awaiting_reviews"], 1)
        self.assertEqual(self.store.connection.execute(
            "SELECT count(*) FROM reviews WHERE arrival_id=? AND state='awaiting'", (aid,)
        ).fetchone()[0], 1)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def test_completion_requires_current_review_revision_and_later_concern_reopens(self):
        aid = self.arrival(1)
        first = self.workflow.record_concern(aid, 0, "volunteer-a", "Needs a person")
        required = first["review_revision"]
        with self.assertRaises(Conflict):
            self.workflow.complete_review(aid, required + 1, "reviewer-a")
        complete = self.workflow.complete_review(aid, required, "reviewer-a")
        self.assertEqual(complete["care_state"], "review_complete")
        self.assertEqual(self.store.summary(self.sid)["completed_reviews"], 1)
        with self.assertRaises(Conflict):
            self.workflow.complete_review(aid, required, "reviewer-a")
        reopened = self.workflow.record_concern(aid, complete["revision"],
                                                 "volunteer-a", "New concern")
        self.assertEqual(reopened["care_state"], "awaiting_review")
        self.assertNotEqual(reopened["review_revision"], required)
        summary = self.store.summary(self.sid)
        self.assertEqual((summary["awaiting_reviews"], summary["completed_reviews"]), (1, 0))
        rows = self.store.connection.execute(
            "SELECT state,completed_by,required_revision FROM reviews WHERE arrival_id=? "
            "ORDER BY created_at, rowid", (aid,)).fetchall()
        self.assertEqual([row["state"] for row in rows], ["completed", "awaiting"])
        self.assertEqual(rows[0]["completed_by"], "reviewer-a")
        self.assertEqual(rows[0]["required_revision"], required)
        with self.assertRaises(Conflict):
            self.workflow.complete_review(aid, required, "reviewer-a")
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)

    def test_voided_confirmed_arrival_keeps_pending_care_independent_of_count(self):
        aid = self.arrival(1)
        flagged = self.workflow.record_concern(aid, 0, "volunteer-a", "Reported pain")
        required = flagged["review_revision"]
        original = (flagged["confirmed_by"], flagged["confirmed_at"])
        self.store.correct(self.sid, self.store.summary(self.sid)["revision"],
                           "coordinator-a", "Duplicate count", {"arrival_id": aid, "counted": False})
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 0)
        self.assertEqual([item["arrival_id"] for item in self.workflow.list_reviews(self.sid)], [aid])
        with self.assertRaises(Conflict):
            self.workflow.complete_review(aid, required + 1, "reviewer-a")
        self.assertEqual(self.store.detail(aid)["care_state"], "awaiting_review")
        completed = self.workflow.complete_review(aid, required, "reviewer-a")
        self.assertEqual((completed["state"], completed["care_state"]),
                         ("voided", "review_complete"))
        self.assertEqual((completed["confirmed_by"], completed["confirmed_at"]), original)
        self.assertEqual((self.store.summary(self.sid)["confirmed_count"],
                          self.store.summary(self.sid)["completed_reviews"]), (0, 1))
        row = self.store.connection.execute(
            "SELECT completed_by,completed_at FROM reviews WHERE arrival_id=?", (aid,)).fetchone()
        self.assertEqual(row["completed_by"], "reviewer-a")
        self.assertTrue(row["completed_at"])

    def test_unconfirmed_draft_cannot_gain_care_completion(self):
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO arrivals(arrival_id,session_id,display_number,state) "
                "VALUES ('unconfirmed-draft',?,9,'draft')", (self.sid,))
            self.store.connection.execute(
                "INSERT INTO reviews(review_id,arrival_id,required_revision,state,reason,created_at) "
                "VALUES ('draft-review','unconfirmed-draft',0,'awaiting','invalid fixture',?)",
                (self.store._now(),))
        with self.assertRaises(Conflict):
            self.workflow.complete_review("unconfirmed-draft", 0, "reviewer-a")
        self.assertEqual(self.store.connection.execute(
            "SELECT state FROM reviews WHERE review_id='draft-review'").fetchone()[0], "awaiting")

    def test_later_no_does_not_close_pending_human_concern(self):
        aid = self.arrival(1)
        self.photo(aid)
        concerned = self.workflow.record_concern(aid, self.store.detail(aid)["revision"],
                                                 "volunteer-a", "Reported pain")
        result = self.workflow.request_assessment(aid, concerned["revision"],
                                                   "volunteer-a", "scripted")
        self.assertEqual(result["assessment"]["result"], "No")
        self.assertEqual(result["care_state"], "awaiting_review")
        self.assertEqual(result["review_revision"], concerned["review_revision"])
        self.assertEqual(len(result["human_concerns"]), 1)

    def test_explicit_no_additional_concern_is_attributed_without_erasing_care(self):
        aid = self.arrival(1)
        clean = self.workflow.record_observation(aid, 0, "volunteer-a", False)
        self.assertEqual(clean["care_state"], "not_referred")
        self.assertEqual(clean["latest_volunteer_observation"]["concern"], False)
        self.assertEqual(clean["latest_volunteer_observation"]["actor_id"], "volunteer-a")
        with self.assertRaises(ValueError):
            self.workflow.record_observation(aid, clean["revision"], "volunteer-a", False,
                                             "Do not turn this into a concern")
        pending = self.workflow.record_observation(aid, clean["revision"], "volunteer-a", True,
                                                    "Reported dizziness")
        self.assertEqual(pending["care_state"], "awaiting_review")
        after = self.workflow.record_observation(aid, pending["revision"], "volunteer-a", False)
        self.assertEqual(after["care_state"], "awaiting_review")
        self.assertEqual(len(after["human_concerns"]), 1)
        self.assertEqual(self.store.summary(self.sid)["awaiting_reviews"], 1)

    def test_same_bytes_retake_rejects_old_assessment_identity(self):
        aid = self.arrival(1)
        first = self.photo(aid)
        retake = self.photo(aid)
        self.assertEqual(first["image_sha256"], retake["image_sha256"])
        self.assertNotEqual(first["image_id"], retake["image_id"])
        stale = Assessment(aid, first["image_sha256"], first["arrival_revision"],
                           "No", "scripted_training", "Old result", None)
        with self.assertRaises(Conflict):
            self.workflow.record_assessment(stale, "volunteer-a")
        self.assertIsNone(self.store.detail(aid)["assessment"])
        self.assertEqual(self.store.summary(self.sid)["awaiting_reviews"], 0)

    def test_finish_reconciles_missing_and_pending_assessments_atomically(self):
        unphotographed = self.arrival(1)
        photographed = self.arrival(2)
        self.photo(photographed)
        summary = self.workflow.finish_intake(self.sid, self.store.summary(self.sid)["revision"],
                                              "volunteer-a")
        self.assertEqual(summary["intake_state"], "finished")
        self.assertEqual(summary["confirmed_count"], 2)
        self.assertEqual(summary["awaiting_reviews"], 2)
        for aid in (unphotographed, photographed):
            detail = self.store.detail(aid)
            self.assertEqual(detail["assessment"]["result"], "Unsure")
            self.assertEqual(detail["care_state"], "awaiting_review")
        with self.assertRaises(Conflict):
            self.workflow.finish_intake(self.sid, summary["revision"] - 1, "volunteer-a")
        self.assertEqual(self.store.summary(self.sid)["awaiting_reviews"], 2)

    def test_finish_requires_a_human_no_concern_decision_for_no_assessment(self):
        aid = self.arrival(1)
        self.photo(aid)
        no = self.workflow.request_assessment(aid, self.store.detail(aid)["revision"],
                                              "volunteer-a", "scripted")
        self.assertEqual(no["assessment"]["result"], "No")
        summary = self.workflow.finish_intake(self.sid, self.store.summary(self.sid)["revision"],
                                              "volunteer-a")
        self.assertEqual(summary["awaiting_reviews"], 1)
        self.assertEqual(self.store.detail(aid)["assessment"]["result"], "Unsure")


if __name__ == "__main__":
    unittest.main()
