"""Private image tests. Fixtures are generated illustrations, never person media."""

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

from services.arrival_intake.contracts import Conflict, Missing, SessionSeed
from services.arrival_intake.photos import PhotoStore
from services.arrival_intake.server import make_server
from services.arrival_intake.store import IntakeStore
from services.arrival_intake.workflow import ExerciseAssessor, Workflow


def picture(format="PNG", size=(8, 8)):
    output = BytesIO()
    Image.new("RGB", size, (30, 100, 180)).save(output, format=format)
    return output.getvalue()


_DEFAULT_EVIDENCE = object()


def permission(**changes):
    evidence = {
        "source_kind": "operator_created_illustration",
        "source_reference": "fixture:blue-rectangle",
        "capture_allowed": True,
        "display_allowed": True,
        "processing_allowed": True,
        "verified_by": "volunteer-a",
        "verified_at": "2026-10-10T12:00:00+00:00",
    }
    evidence.update(changes)
    return evidence


def illustration_registry(*formats):
    return {"fixture:blue-rectangle": {
        "source_kind": "operator_created_illustration",
        "image_sha256s": frozenset(hashlib.sha256(picture(fmt)).hexdigest()
                                    for fmt in formats),
        "capture_allowed": True,
        "display_allowed": True,
        "processing_allowed": True,
    }}


class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "intake.sqlite"
        self.store = IntakeStore(self.db)
        self.addCleanup(self.store.close)
        self.sid = self.store.create_session(SessionSeed(
            "case-demo", "run-demo", "dispatch-a", "bus-1", "shelter-1", 2,
            "boarding-a", "arrival-a", "a" * 64))["session_id"]
        self.aid = self.store.confirm_arrival(self.sid, "arrival-a", "volunteer-a")["arrival_id"]
        self.registry = illustration_registry("PNG", "JPEG")
        self.photos = PhotoStore(self.store, self.registry)

    def attach(self, data=None, media_type="image/png", expected_revision=0,
               evidence=_DEFAULT_EVIDENCE):
        return self.photos.attach(self.aid, "volunteer-a", expected_revision,
                                  picture() if data is None else data,
                                  media_type, permission() if evidence is _DEFAULT_EVIDENCE else evidence)

    def test_attach_records_permission_hash_current_pointer_and_single_attendance(self):
        raw = picture()
        result = self.attach(raw)
        detail = self.store.detail(self.aid)
        self.assertEqual(result["image_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["media_type"], "image/png")
        self.assertEqual(result["arrival_revision"], 1)
        self.assertEqual(detail["revision"], 1)
        self.assertEqual(detail["current_image_id"], result["image_id"])
        self.assertEqual(detail["current_image_sha256"], result["image_sha256"])
        self.assertEqual(self.photos.read(self.aid), (raw, "image/png"))
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)
        self.assertEqual(self.store.connection.execute(
            "PRAGMA secure_delete").fetchone()[0], 1)
        saved = self.store.connection.execute(
            "SELECT permitted_use_json FROM images WHERE image_sha256=?",
            (result["image_sha256"],)).fetchone()
        self.assertEqual(json.loads(saved[0]), permission())

    def test_missing_false_or_unverified_permission_is_rejected_before_write(self):
        bad = (
            None, {}, permission(capture_allowed=False),
            permission(display_allowed=False), permission(processing_allowed=False),
            permission(capture_allowed=1), permission(verified_by=""),
            permission(verified_by="someone-else"),
            permission(verified_at="not-a-time"), permission(source_reference=""),
            permission(source_kind="unknown"),
            permission(extra=True),
            permission(source_kind="adult_staged"),
            permission(source_kind="adult_staged", consent_reference=""),
        )
        for evidence in bad:
            with self.subTest(evidence=evidence):
                with self.assertRaises(ValueError):
                    self.attach(evidence=evidence)
                self.assertEqual(self.store.detail(self.aid)["revision"], 0)
                self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)
                with self.assertRaises(Missing):
                    self.photos.read(self.aid)

    def test_adult_staged_source_requires_actual_root_verified_release(self):
        adult = permission(
            source_kind="adult_staged", source_reference="staged-person-1",
            consent_reference="signed-release-1")
        with self.assertRaises(ValueError):
            self.attach(evidence=adult)
        self.registry["staged-person-1"] = {
            "source_kind": "adult_staged",
            "image_sha256s": frozenset({hashlib.sha256(picture()).hexdigest()}),
            "capture_allowed": True, "display_allowed": True,
            "processing_allowed": True,
            "consent_reference": "different-release",
        }
        with self.assertRaises(ValueError):
            self.attach(evidence=adult)
        self.registry["staged-person-1"]["consent_reference"] = "signed-release-1"
        # A new binding reads the trusted root configuration. The image remains
        # an artificial rectangle in this unit test, never real-person media.
        result = PhotoStore(self.store, self.registry).attach(
            self.aid, "volunteer-a", 0, picture(), "image/png", adult)
        self.assertEqual(result["arrival_revision"], 1)

    def test_missing_registry_or_invented_source_and_hash_cannot_attach(self):
        original = picture()
        attempts = (
            (PhotoStore(self.store), original, permission()),
            (self.photos, original, permission(source_reference="invented-ref")),
            (self.photos, picture(size=(9, 9)), permission()),
        )
        for photos, raw, evidence in attempts:
            with self.subTest(evidence=evidence, hash=hashlib.sha256(raw).hexdigest()):
                with self.assertRaises(ValueError):
                    photos.attach(self.aid, "volunteer-a", 0, raw, "image/png", evidence)
                self.assertEqual(self.store.detail(self.aid)["revision"], 0)
                self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)
        with self.assertRaises(Missing):
            self.photos.read(self.aid)

    def test_root_grant_must_itself_be_complete_and_exact(self):
        raw = picture()
        digest = hashlib.sha256(raw).hexdigest()
        for grant in (
            {"source_kind": "operator_created_illustration",
             "image_sha256s": frozenset({digest}),
             "capture_allowed": 1, "display_allowed": True, "processing_allowed": True},
            {"source_kind": "operator_created_illustration",
             "image_sha256s": frozenset({digest}),
             "capture_allowed": True, "display_allowed": True,
             "processing_allowed": False},
            {"source_kind": "operator_created_illustration",
             "image_sha256s": frozenset({"invalid"}),
             "capture_allowed": True, "display_allowed": True,
             "processing_allowed": True},
        ):
            with self.subTest(grant=grant):
                with self.assertRaises(ValueError):
                    PhotoStore(self.store, {"fixture:blue-rectangle": grant}).attach(
                        self.aid, "volunteer-a", 0, raw, "image/png", permission())
                self.assertEqual(self.store.detail(self.aid)["revision"], 0)

    def test_declared_type_must_match_static_image_and_size_limits(self):
        animated = BytesIO()
        Image.new("RGB", (4, 4), "red").save(
            animated, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (4, 4), "blue")], duration=100)
        bad = (
            (picture(), "image/jpeg"),
            (picture("JPEG"), "image/png"),
            (b"not an image", "image/png"),
            (picture(), "image/gif"),
            (animated.getvalue(), "image/png"),
            (b"x" * (5 * 1024 * 1024 + 1), "image/png"),
            (picture(size=(4000, 3001)), "image/png"),
        )
        for data, media_type in bad:
            with self.subTest(media_type=media_type, size=len(data)):
                with self.assertRaises(ValueError):
                    self.attach(data=data, media_type=media_type)
                self.assertEqual(self.store.detail(self.aid)["revision"], 0)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)

    def test_failed_retake_preserves_previous_image_and_attendance(self):
        original = picture()
        first = self.attach(original)
        for expected_revision, data, media_type in (
            (0, picture("JPEG"), "image/jpeg"),
            (1, b"invalid", "image/png"),
        ):
            with self.assertRaises((Conflict, ValueError)):
                self.attach(data, media_type, expected_revision)
            self.assertEqual(self.photos.read(self.aid), (original, "image/png"))
            self.assertEqual(self.store.detail(self.aid)["current_image_id"], first["image_id"])
            self.assertEqual(self.store.detail(self.aid)["revision"], 1)
            self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)

    def test_same_bytes_retake_has_new_capture_identity_and_revision(self):
        raw = picture()
        first = self.attach(raw)
        second = self.attach(raw, expected_revision=1)
        self.assertNotEqual(second["image_id"], first["image_id"])
        self.assertEqual(second["image_sha256"], first["image_sha256"])
        self.assertEqual(second["arrival_revision"], 2)
        self.assertEqual(self.store.detail(self.aid)["current_image_id"], second["image_id"])
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)

    def test_photo_binding_follows_request_store_without_original_connection(self):
        raw = picture()
        self.store.close()
        with IntakeStore(self.db) as request_store:
            rebound = self.photos.for_store(request_store)
            self.assertIsNot(rebound, self.photos)
            self.assertIs(rebound.store, request_store)
            rebound.attach(self.aid, "volunteer-a", 0, raw, "image/png", permission())
            self.assertEqual(rebound.read(self.aid), (raw, "image/png"))

    def test_cleanup_blanks_all_images_and_reopen_denies_photo(self):
        first = self.attach()
        later = picture("JPEG")
        self.attach(later, "image/jpeg", 1)
        self.store.close()
        with IntakeStore(self.db) as cleanup_store:
            result = PhotoStore(cleanup_store).cleanup(self.sid, "exercise-owner")
            self.assertEqual(result, {"removed_images": 2})
            self.assertEqual(cleanup_store.summary(self.sid)["confirmed_count"], 1)
            self.assertEqual(cleanup_store.detail(self.aid)["current_image_id"], None)
            self.assertEqual(cleanup_store.connection.execute(
                "SELECT count(*) FROM images WHERE private_bytes IS NOT NULL").fetchone()[0], 0)
        with IntakeStore(self.db) as reopened:
            with self.assertRaises(Missing):
                PhotoStore(reopened).read(self.aid)
            self.assertEqual(reopened.summary(self.sid)["confirmed_count"], 1)
            self.assertEqual(reopened.connection.execute(
                "SELECT count(*) FROM events WHERE event_type='arrival_confirmed'").fetchone()[0], 1)
        for suffix in ("-wal", "-journal"):
            artifact = Path(str(self.db) + suffix)
            if artifact.exists():
                self.assertNotIn(later, artifact.read_bytes())

    def test_cleanup_scrubs_capture_identifiers_from_all_event_snapshots(self):
        capture = self.attach()
        workflow = Workflow(self.store, self.photos, ExerciseAssessor({1: "Yes"}))
        assessed = workflow.request_assessment(self.aid, capture["arrival_revision"],
                                               "volunteer-a", "scripted")
        concerned = workflow.record_concern(self.aid, assessed["revision"],
                                             "volunteer-a", "Illustrated concern")
        self.store.correct(self.sid, self.store.summary(self.sid)["revision"],
                           "coordinator-a", "Duplicate count",
                           {"arrival_id": self.aid, "counted": False})
        before = self.store.connection.execute(
            "SELECT before_json,after_json FROM events WHERE session_id=?", (self.sid,)).fetchall()
        self.assertIn(capture["image_sha256"], json.dumps([tuple(row) for row in before]))
        self.assertIn(capture["image_id"], json.dumps([tuple(row) for row in before]))
        self.store.close()
        with IntakeStore(self.db) as cleanup_store:
            self.assertEqual(PhotoStore(cleanup_store).cleanup(self.sid, "exercise-owner"),
                             {"removed_images": 1})
        with IntakeStore(self.db) as reopened:
            events = [dict(row) for row in reopened.connection.execute(
                "SELECT event_type,actor_id,occurred_at,reason,before_json,after_json "
                "FROM events WHERE session_id=? ORDER BY rowid", (self.sid,))]
            snapshots = [json.loads(row[key]) for row in events
                         for key in ("before_json", "after_json")]
            serialized = json.dumps(snapshots)
            self.assertNotIn(capture["image_sha256"], serialized)
            self.assertNotIn(capture["image_id"], serialized)
            forbidden = {"image_sha256", "current_image_sha256", "capture_id",
                         "current_image_id", "capture_revision", "current_image_revision"}
            def walk(value):
                if isinstance(value, dict):
                    self.assertTrue(forbidden.isdisjoint(value))
                    for child in value.values(): walk(child)
                elif isinstance(value, list):
                    for child in value: walk(child)
            for snapshot in snapshots: walk(snapshot)
            self.assertIn("arrival_confirmed", [row["event_type"] for row in events])
            self.assertIn("assessment_recorded", [row["event_type"] for row in events])
            self.assertIn("attendance_correction", [row["event_type"] for row in events])
            self.assertIn("Illustrated concern", serialized)
            self.assertEqual(reopened.summary(self.sid)["confirmed_count"], 0)
            self.assertEqual(reopened.summary(self.sid)["awaiting_reviews"], 1)
            self.assertEqual(reopened.connection.execute(
                "SELECT source_sha256 FROM sessions WHERE session_id=?", (self.sid,)
            ).fetchone()[0], "a" * 64)

    def test_cleanup_rejects_active_reader_and_does_not_report_success(self):
        self.attach()
        self.store.close()
        with IntakeStore(self.db) as reader, IntakeStore(self.db) as cleanup_store:
            reader.connection.execute("BEGIN")
            reader.connection.execute("SELECT * FROM arrivals").fetchall()
            try:
                with self.assertRaises((Conflict, RuntimeError)):
                    PhotoStore(cleanup_store).cleanup(self.sid, "exercise-owner")
            finally:
                reader.connection.rollback()

    def test_busy_checkpoint_from_external_reader_is_incomplete(self):
        self.attach()
        self.store.close()
        reader = sqlite3.connect(self.db, timeout=1)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM arrivals").fetchall()
        try:
            with IntakeStore(self.db) as cleanup_store:
                with self.assertRaises(Conflict):
                    PhotoStore(cleanup_store).cleanup(self.sid, "exercise-owner")
                # The checkpoint may fail after the deletion transaction. A
                # failed cleanup never reports success, even if rows are blank.
                self.assertEqual(cleanup_store.connection.execute(
                    "SELECT count(*) FROM images WHERE private_bytes IS NOT NULL").fetchone()[0], 0)
        finally:
            reader.rollback()
            reader.close()
        with IntakeStore(self.db) as cleanup_store:
            self.assertEqual(PhotoStore(cleanup_store).cleanup(
                self.sid, "exercise-owner"), {"removed_images": 0})
        with IntakeStore(self.db) as reopened:
            with self.assertRaises(Missing):
                PhotoStore(reopened).read(self.aid)

    def test_cleanup_removes_only_recorded_owned_media_artifacts(self):
        self.attach()
        private = Path(self.temp.name) / "private_media"
        private.mkdir()
        owned = private / "demo-copy.png"
        owned.write_bytes(picture())
        unrecorded = private / "unrecorded.txt"
        unrecorded.write_text("keep", encoding="utf-8")
        outside = Path(self.temp.name) / "outside.png"
        outside.write_bytes(picture())
        with self.assertRaises(ValueError):
            self.photos.record_artifact(self.sid, outside)
        self.photos.record_artifact(self.sid, owned)
        self.store.close()
        with IntakeStore(self.db) as cleanup_store:
            self.assertEqual(PhotoStore(cleanup_store).cleanup(
                self.sid, "exercise-owner"), {"removed_images": 1})
        self.assertFalse(owned.exists())
        self.assertTrue(unrecorded.exists())
        self.assertTrue(outside.exists())

    def test_existing_schema_migrates_without_losing_rows(self):
        # A database made before Task 4 has no current-capture columns.
        legacy = Path(self.temp.name) / "legacy.sqlite"
        old_schema = Path(__file__).parent / "fixtures" / "legacy_schema.sql"
        with sqlite3.connect(legacy) as connection:
            connection.executescript(old_schema.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO sessions(session_id,case_id,run_id,dispatch_id,vehicle_id,destination_node,"
                "expected_count,original_expected_count,boarding_event_id,arrival_event_id,source_sha256,created_at)"
                " VALUES ('existing','case','run','dispatch','bus','destination',1,1,'boarding','arrival',?,?)",
                ("a" * 64, "2026-10-10T00:00:00+00:00"))
        with IntakeStore(legacy) as migrated:
            self.assertEqual(migrated.summary("existing")["expected_count"], 1)
            self.assertIn("current_image_id", {
                row[1] for row in migrated.connection.execute("PRAGMA table_info(arrivals)")})


class PhotoHTTPAssignmentTests(unittest.TestCase):
    def test_unassigned_photo_is_hidden_before_read_or_capture(self):
        with TemporaryDirectory() as root:
            db = Path(root) / "intake.sqlite"
            with IntakeStore(db) as store:
                def create(dispatch):
                    sid = store.create_session(SessionSeed(
                        "case", "run", dispatch, "bus", "shelter", 1,
                        "boarding-" + dispatch, "arrival-" + dispatch,
                        "a" * 64))["session_id"]
                    aid = store.confirm_arrival(sid, "one", "fixture")["arrival_id"]
                    return sid, aid
                own_sid, _ = create("own")
                _, other_aid = create("other")
                registry_grants = illustration_registry("PNG")
                PhotoStore(store, registry_grants).attach(other_aid, "volunteer-a", 0,
                                                          picture(), "image/png", permission())
                token = secrets.token_hex(32)
                registry = {hashlib.sha256(token.encode("ascii")).hexdigest(): {
                    "actor_id": "volunteer-a", "role": "volunteer", "session_ids": [own_sid]}}
                static = Path(root) / "static"
                static.mkdir()
                for name in ("index.html", "app.js", "style.css"):
                    (static / name).write_text("fixture", encoding="utf-8")
                server = make_server(store, None, PhotoStore(store, registry_grants), registry, static)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    url = f"http://127.0.0.1:{server.server_address[1]}/api/arrivals/{other_aid}/photo"
                    body = json.dumps({"expected_revision": 1,
                                       "image_base64": base64.b64encode(picture()).decode(),
                                       "media_type": "image/png", "permission": permission()}).encode()
                    for method, data in (("GET", None), ("POST", body)):
                        request = Request(url, data=data, method=method,
                                          headers={"Authorization": "Bearer " + token,
                                                   "Content-Type": "application/json"})
                        with self.assertRaises(HTTPError) as failure:
                            urlopen(request, timeout=5)
                        self.assertEqual(failure.exception.code, 404)
                    self.assertEqual(store.detail(other_aid)["revision"], 1)
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
