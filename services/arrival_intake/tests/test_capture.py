"""Synthetic, file-backed controls for root-authorized live capture.

The raster is the repository's operator-created exercise illustration. These
tests provision fictional grants only in a temporary database.
"""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest

from PIL import Image, PngImagePlugin

from services.arrival_intake.capture import CaptureAuthority, CaptureService
from services.arrival_intake.contracts import Conflict, Forbidden, Missing
from services.arrival_intake.demo import build_demo_seed, illustration_bytes
from services.arrival_intake.photos import PhotoStore
from services.arrival_intake.store import IntakeStore
from services.arrival_intake.workflow import ExerciseAssessor, Workflow


class CaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "intake.sqlite"
        self.store = IntakeStore(self.path)
        self.addCleanup(self.store.close)
        self.sid = self.store.create_session(build_demo_seed("capture-contract"))["session_id"]
        self.aid = self.store.confirm_arrival(self.sid, "capture-person-1", "volunteer-test")["arrival_id"]
        self.other_aid = self.store.confirm_arrival(self.sid, "capture-person-2", "volunteer-test")["arrival_id"]
        self.now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.image = illustration_bytes()  # synthetic non-person illustration
        self.denied = CaptureService(self.store, PhotoStore(self.store),
                                     CaptureAuthority({}, clock=self.clock))
        self.grant = {
            "grant_id": "synthetic-consent-grant-1", "consent_reference": "synthetic-control-only",
            "verified_by": "root-verifier", "verified_at": self.now - timedelta(minutes=1),
            "expires_at": self.now + timedelta(minutes=10),
            "purposes": frozenset({"preview", "capture", "display", "assessment"}),
        }
        self.authority = CaptureAuthority({(self.sid, self.aid, "volunteer-test"): self.grant},
                                          clock=self.clock)
        self.authority.provision_grants(self.store)
        self.photos = PhotoStore(self.store, capture_authority=self.authority)
        self.capture = CaptureService(self.store, self.photos, self.authority)

    def _start(self):
        return self.capture.start(self.aid, "volunteer-test", self.store.detail(self.aid)["revision"])

    def _commit(self, handle, image=None, revision=None):
        return self.capture.commit(handle, "volunteer-test",
                                   self.store.detail(self.aid)["revision"] if revision is None else revision,
                                   self.image if image is None else image, "image/png")

    def test_empty_root_authority_denies_fresh_capture_and_ungranted_neighbor(self):
        with self.assertRaises(Forbidden):
            self.denied.start(self.aid, "volunteer-test", 0)
        with self.assertRaises(Forbidden):
            self.capture.start(self.other_aid, "volunteer-test", 0)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)
        self.assertEqual(self.store.detail(self.aid)["revision"], 0)

    def test_explicit_provision_only_and_root_verifier_is_distinct(self):
        empty_db_authority = CaptureAuthority({(self.sid, self.aid, "volunteer-test"): {
            **self.grant, "grant_id": "unprovisioned-control"}}, clock=self.clock)
        with self.assertRaises(Forbidden):
            CaptureService(self.store, PhotoStore(self.store), empty_db_authority).start(
                self.aid, "volunteer-test", 0)
        session = self._start()
        saved = self._commit(session["capture_session_id"])
        row = self.store.connection.execute(
            "SELECT permission_json,actor_id FROM photo_captures WHERE capture_id=?",
            (saved["photo"]["image_id"],)).fetchone()
        self.assertEqual(row["actor_id"], "volunteer-test")
        self.assertIn("root-verifier", row["permission_json"])
        self.assertIn("synthetic-control-only", row["permission_json"])

    def test_lost_commit_receipt_resolves_without_retake_or_recount(self):
        session = self._start()
        handle = session["capture_session_id"]
        saved = self._commit(handle, revision=0)
        recovered = self.capture.status(handle, "volunteer-test")
        self.assertEqual(recovered["state"], "consumed")
        self.assertTrue(recovered["is_current"])
        self.assertEqual(recovered["photo"], saved["photo"])
        self.assertEqual(self._commit(handle, revision=0)["photo"], saved["photo"])
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)
        self.assertEqual(self.store.detail(self.aid)["revision"], 1)
        self.assertEqual(self.store.connection.execute(
            "SELECT count(*) FROM photo_captures WHERE arrival_id=?", (self.aid,)).fetchone()[0], 1)

    def test_replay_different_bytes_or_actor_is_rejected_and_retake_retires_old_receipt(self):
        first = self._start()["capture_session_id"]
        saved = self._commit(first)
        rewritten = BytesIO()
        with Image.open(BytesIO(self.image)) as same_pixels:
            info = PngImagePlugin.PngInfo()
            info.add_text("synthetic-replay-marker", "different input bytes")
            same_pixels.save(rewritten, format="PNG", pnginfo=info)
        self.assertNotEqual(rewritten.getvalue(), self.image)
        with self.assertRaises(Conflict):
            self.capture.commit(first, "volunteer-test", 0, rewritten.getvalue(), "image/png")
        with self.assertRaises(Missing):
            self.capture.status(first, "foreign-actor")
        second = self._start()["capture_session_id"]
        retaken = self._commit(second)
        self.assertNotEqual(retaken["photo"]["image_id"], saved["photo"]["image_id"])
        self.assertFalse(self.capture.status(first, "volunteer-test")["is_current"])
        self.assertTrue(self.capture.status(second, "volunteer-test")["is_current"])
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)
        self.assertEqual(self.store.detail(self.aid)["revision"], 2)

    def test_revocation_on_second_connection_is_seen_by_existing_adapter(self):
        session = self._start()["capture_session_id"]
        other = IntakeStore(self.path)
        self.addCleanup(other.close)
        self.authority.revoke_grant(other, self.grant["grant_id"], 1, "root-operator")
        with self.assertRaises(Forbidden):
            self._commit(session)
        with self.assertRaises(Forbidden):
            self.capture.start(self.aid, "volunteer-test", 0)
        with self.assertRaises(Forbidden):
            self.authority.provision_grants(other)  # revoked IDs cannot resurrect
        self.assertIsNone(self.store.detail(self.aid)["current_photo"])

    def test_consumed_session_does_not_extend_display_or_assessment_rights(self):
        handle = self._start()["capture_session_id"]
        self._commit(handle)
        self.capture.close(handle, "volunteer-test")
        self.assertEqual(self.photos.read(self.aid, purpose="display")[1], "image/png")
        other = IntakeStore(self.path)
        self.addCleanup(other.close)
        self.authority.revoke_grant(other, self.grant["grant_id"], 1, "root-operator")
        for purpose in ("display", "assessment"):
            with self.subTest(purpose=purpose), self.assertRaises(Forbidden):
                self.photos.read(self.aid, purpose=purpose)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def test_voided_count_preserves_authorized_display_and_human_care(self):
        handle = self._start()["capture_session_id"]
        self._commit(handle)
        Workflow(self.store, self.photos, ExerciseAssessor({})).record_concern(
            self.aid, 1, "volunteer-test", "synthetic visible concern")
        self.store.correct(self.sid, self.store.summary(self.sid)["revision"],
                           "coordinator-test", "synthetic count correction",
                           {"arrival_id": self.aid, "counted": False})
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)
        self.assertEqual(self.store.detail(self.aid)["care_state"], "awaiting_review")
        self.assertEqual(self.photos.read(self.aid, purpose="display")[1], "image/png")
        with self.assertRaises(Conflict):
            self.capture.start(self.aid, "volunteer-test", self.store.detail(self.aid)["revision"])

    def test_expiry_and_purpose_are_checked_at_use(self):
        session = self._start()["capture_session_id"]
        self.now = self.grant["expires_at"] + timedelta(seconds=1)
        with self.assertRaises(Forbidden):
            self._commit(session)
        self.assertIsNone(self.store.detail(self.aid)["current_photo"])
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def test_capture_only_grant_cannot_preview_display_or_assess(self):
        limited = CaptureAuthority({(self.sid, self.aid, "volunteer-test"): {
            **self.grant, "grant_id": "synthetic-capture-only",
            "purposes": frozenset({"capture"})}}, clock=self.clock)
        limited.provision_grants(self.store)
        photos = PhotoStore(self.store, capture_authority=limited)
        capture = CaptureService(self.store, photos, limited)
        handle = capture.start(self.aid, "volunteer-test", 0)["capture_session_id"]
        with self.assertRaises(Forbidden):
            capture.preview(handle, "volunteer-test", 1, self.image, "image/png")
        saved = capture.commit(handle, "volunteer-test", 0, self.image, "image/png")
        self.assertEqual(saved["arrival"]["revision"], 1)
        for purpose in ("display", "assessment"):
            with self.subTest(purpose=purpose), self.assertRaises(Forbidden):
                photos.read(self.aid, purpose=purpose)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def test_preview_output_is_discarded_after_root_revocation_during_runner(self):
        handle = self._start()["capture_session_id"]

        def revoke_during_processing(_image, **_binding):
            with IntakeStore(self.path) as other:
                self.authority.revoke_grant(other, self.grant["grant_id"], 1, "root-operator")
            return {"status": "ready", "boxes": [{"x": 0, "y": 0, "w": 1, "h": 1}]}

        controlled = CaptureService(self.store, self.photos, self.authority,
                                    preview_runner=revoke_during_processing)
        with self.assertRaises(Forbidden):
            controlled.preview(handle, "volunteer-test", 1, self.image, "image/png")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM images").fetchone()[0], 0)

    def test_session_deadline_and_idempotent_close(self):
        handle = self._start()["capture_session_id"]
        self.now += timedelta(seconds=121)
        with self.assertRaises(Forbidden):
            self.capture.preview(handle, "volunteer-test", 1, self.image, "image/png")
        self.assertEqual(self.capture.close(handle, "volunteer-test")["state"], "closed")
        self.assertEqual(self.capture.close(handle, "volunteer-test")["state"], "closed")
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def test_frame_order_limit_and_preview_bytes_never_persist(self):
        handle = self._start()["capture_session_id"]
        first = self.capture.preview(handle, "volunteer-test", 1, self.image, "image/png")
        self.assertEqual(first["frame_id"], 1)
        self.assertEqual(first["status"], "unavailable")  # no model is configured
        with self.assertRaises(Conflict):
            self.capture.preview(handle, "volunteer-test", 1, self.image, "image/png")
        for frame in range(2, 241):
            self.capture.preview(handle, "volunteer-test", frame, self.image, "image/png")
        with self.assertRaises(Conflict):
            self.capture.preview(handle, "volunteer-test", 241, self.image, "image/png")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM images").fetchone()[0], 0)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM photo_captures").fetchone()[0], 0)
        self.assertNotIn(self.image, self.path.read_bytes())

    def test_stale_and_voided_arrivals_cannot_acquire_or_commit(self):
        with self.assertRaises(Conflict):
            self.capture.start(self.aid, "volunteer-test", 1)
        handle = self._start()["capture_session_id"]
        revision = self.store.summary(self.sid)["revision"]
        self.store.correct(self.sid, revision, "coordinator-test", "attendance correction",
                           {"arrival_id": self.aid, "counted": False})
        with self.assertRaises(Conflict):
            self._commit(handle, revision=0)
        with self.assertRaises(Conflict):
            self.capture.start(self.aid, "volunteer-test", 1)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)

    def test_atomic_attach_failure_leaves_session_active_and_no_photo(self):
        handle = self._start()["capture_session_id"]
        self.store.connection.execute("CREATE TRIGGER synthetic_abort_capture BEFORE INSERT ON photo_captures "
                                      "BEGIN SELECT RAISE(ABORT, 'synthetic rollback'); END")
        self.store.connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self._commit(handle)
        self.assertEqual(self.capture.status(handle, "volunteer-test")["state"], "active")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM images").fetchone()[0], 0)
        self.assertEqual(self.store.detail(self.aid)["revision"], 0)

    def test_normalized_selected_raster_strips_metadata_and_reduces_size(self):
        image = Image.new("RGB", (1600, 800), (20, 40, 60))
        info = PngImagePlugin.PngInfo()
        info.add_text("synthetic-private-marker", "must-not-survive")
        stream = BytesIO()
        image.save(stream, format="PNG", pnginfo=info)
        handle = self._start()["capture_session_id"]
        saved = self._commit(handle, stream.getvalue())
        normalized, media_type = self.photos.read(self.aid)
        self.assertEqual(media_type, saved["photo"]["media_type"])
        self.assertNotIn(b"synthetic-private-marker", normalized)
        self.assertEqual(sha256(normalized).hexdigest(), saved["photo"]["image_sha256"])
        with Image.open(BytesIO(normalized)) as stored:
            self.assertLessEqual(max(stored.size), 1280)
            self.assertEqual(stored.getexif(), {})

    def test_synthetic_icc_is_absent_from_selected_and_preview_rasters(self):
        marker = b"synthetic-icc-control-marker-not-a-real-profile"
        with Image.open(BytesIO(self.image)) as source:
            raster = source.convert("RGB")
        tagged = BytesIO()
        raster.save(tagged, format="PNG", icc_profile=marker)
        preview_payloads = []

        def controlled_preview(normalized, **_binding):
            preview_payloads.append(normalized)
            return None

        handle = self._start()["capture_session_id"]
        capture = CaptureService(self.store, self.photos, self.authority,
                                 preview_runner=controlled_preview)
        capture.preview(handle, "volunteer-test", 1, tagged.getvalue(), "image/png")
        self.assertEqual(len(preview_payloads), 1)
        with Image.open(BytesIO(preview_payloads[0])) as preview:
            self.assertNotIn("icc_profile", preview.info)
        self.assertNotIn(marker, preview_payloads[0])
        capture.commit(handle, "volunteer-test", 0, tagged.getvalue(), "image/png")
        selected, _ = self.photos.read(self.aid)
        with Image.open(BytesIO(selected)) as stored:
            self.assertNotIn("icc_profile", stored.info)
        self.assertNotIn(marker, selected)

    def test_actual_exif_orientation_is_applied_before_metadata_removal(self):
        source = Image.new("RGB", (30, 20), (40, 60, 100))
        exif = Image.Exif()
        exif[274] = 6  # rotate 90 degrees clockwise
        tagged = BytesIO()
        source.save(tagged, format="JPEG", exif=exif)
        handle = self._start()["capture_session_id"]
        self.capture.commit(handle, "volunteer-test", 0, tagged.getvalue(), "image/jpeg")
        selected, media_type = self.photos.read(self.aid)
        self.assertEqual(media_type, "image/png")
        with Image.open(BytesIO(selected)) as stored:
            self.assertEqual(stored.size, (20, 30))
            self.assertEqual(stored.getexif(), {})

    def test_encoded_and_decoded_image_limits_reject_without_photo(self):
        handle = self._start()["capture_session_id"]
        with self.assertRaises(ValueError):
            self._commit(handle, b"x" * (5 * 1024 * 1024 + 1))
        huge = Image.new("RGB", (4000, 4000), (5, 10, 15))
        stream = BytesIO()
        huge.save(stream, format="PNG")
        with self.assertRaises(ValueError):
            self._commit(handle, stream.getvalue())
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM images").fetchone()[0], 0)

    def test_capture_cleanup_reopen_removes_sessions_grants_and_receipts(self):
        active = self._start()["capture_session_id"]
        consumed = self._start()["capture_session_id"]
        self._commit(consumed)
        Workflow(self.store, self.photos, ExerciseAssessor({})).record_concern(
            self.aid, 1, "volunteer-test", "synthetic human review note")
        self.store.correct(self.sid, self.store.summary(self.sid)["revision"],
                           "coordinator-test", "synthetic expectation correction",
                           {"expected_count": 31})
        before = self.store.summary(self.sid)
        history_before = self.store.connection.execute(
            "SELECT count(*) FROM events WHERE session_id=?", (self.sid,)).fetchone()[0]
        self.photos.cleanup(self.sid, "coordinator-test")
        self.store.close()
        with IntakeStore(self.path) as reopened:
            self.assertEqual(reopened.summary(self.sid)["confirmed_count"], before["confirmed_count"])
            self.assertEqual(reopened.summary(self.sid)["expected_count"], 31)
            self.assertEqual(reopened.detail(self.aid)["current_photo"], None)
            self.assertEqual(reopened.detail(self.aid)["care_state"], "awaiting_review")
            self.assertEqual(len(reopened.detail(self.aid)["human_concerns"]), 1)
            self.assertEqual(reopened.connection.execute(
                "SELECT count(*) FROM events WHERE session_id=?", (self.sid,)).fetchone()[0],
                history_before)
            self.assertEqual(reopened.connection.execute(
                "SELECT count(*) FROM capture_sessions").fetchone()[0], 0)
            tombstone = reopened.connection.execute(
                "SELECT status,version FROM capture_grants WHERE grant_id=?",
                (self.grant["grant_id"],)).fetchone()
            self.assertEqual(tombstone["status"], "revoked")
            self.assertGreaterEqual(tombstone["version"], 2)
            self.assertIsNone(reopened.connection.execute(
                "SELECT exercise_session_id FROM capture_grants WHERE grant_id=?",
                (self.grant["grant_id"],)).fetchone()[0])
            rebound = self.capture.for_store(reopened, PhotoStore(reopened, capture_authority=self.authority))
            for handle in (active, consumed):
                with self.assertRaises(Missing):
                    rebound.status(handle, "volunteer-test")
            with self.assertRaises(Missing):
                PhotoStore(reopened, capture_authority=self.authority).read(self.aid)
            with self.assertRaises(Forbidden):
                self.authority.provision_grants(reopened)
            self.assertEqual(reopened.summary(self.sid)["confirmed_count"], before["confirmed_count"])


if __name__ == "__main__":
    unittest.main()
