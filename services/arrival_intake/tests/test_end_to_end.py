"""Simulator-backed exercise through the assigned, real HTTP boundary."""

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from services.arrival_intake.demo import (build_demo_seed, cleanup_demo, illustration_bytes,
                                          prepare_demo, serve_demo)
from services.arrival_intake.photos import PhotoStore
from services.arrival_intake.server import make_server
from services.arrival_intake.store import IntakeStore
from services.arrival_intake.workflow import ExerciseAssessor, Workflow


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "exercise.sqlite"
        self.store = IntakeStore(self.database)
        self.addCleanup(self.store.close)
        self.seed = build_demo_seed("http-end-to-end")
        self.assertEqual(self.seed.expected_count, 30)
        self.sid = self.store.create_session(self.seed)["session_id"]
        self.image = illustration_bytes()
        self.digest = sha256(self.image).hexdigest()
        self.source_reference = "task7-operator-illustration-v1"
        photos = PhotoStore(self.store, {self.source_reference: {
            "source_kind": "operator_created_illustration",
            "image_sha256s": frozenset({self.digest}),
            "capture_allowed": True, "display_allowed": True,
            "processing_allowed": True,
        }})
        labels = {number: "No" for number in range(1, 30)}
        labels[1] = "Yes"
        workflow = Workflow(self.store, photos, ExerciseAssessor(labels))
        self.tokens = {name: secrets.token_hex(32) for name in
                       ("volunteer", "care_reviewer", "coordinator", "unassigned")}
        registry = {}
        for name, token in self.tokens.items():
            registry[sha256(token.encode("ascii")).hexdigest()] = {
                "actor_id": name + "-e2e",
                "role": "volunteer" if name == "unassigned" else name,
                "session_ids": [] if name == "unassigned" else [self.sid],
            }
        assets = self.root / "static"
        assets.mkdir()
        for name in ("index.html", "app.js", "style.css"):
            (assets / name).write_text("/* isolated test */", encoding="utf-8")
        self.server = make_server(self.store, workflow, photos, registry, assets)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def _stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)

    def request(self, method, path, role, payload=None, binary=False):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Authorization": "Bearer " + self.tokens[role]}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            if binary and response.status == 200:
                return response.status, content
            return response.status, json.loads(content)

    def summary(self):
        status, body = self.request("GET", f"/api/intakes/{self.sid}/aggregate", "coordinator")
        self.assertEqual(status, 200)
        return body

    def detail(self, aid):
        status, body = self.request("GET", f"/api/arrivals/{aid}", "volunteer")
        self.assertEqual(status, 200)
        return body["arrival"]

    def confirm_arrivals(self, count):
        arrivals = []
        for number in range(1, count + 1):
            status, body = self.request("POST", f"/api/intakes/{self.sid}/arrivals",
                                        "volunteer", {"operation_key": f"e2e-{number}"})
            self.assertEqual(status, 200)
            self.assertEqual(body["arrival_number"], number)
            arrivals.append(body["arrival_id"])
        return arrivals

    def assess_arrivals(self, arrivals):
        permission = {
            "source_kind": "operator_created_illustration",
            "source_reference": self.source_reference,
            "capture_allowed": True, "display_allowed": True,
            "processing_allowed": True,
            "verified_by": "volunteer-e2e",
            "verified_at": "2026-10-10T12:00:00+00:00",
        }
        reviews = []
        for number, aid in enumerate(arrivals, 1):
            status, photo = self.request("POST", f"/api/arrivals/{aid}/photo", "volunteer", {
                "expected_revision": 0,
                "image_base64": base64.b64encode(self.image).decode("ascii"),
                "media_type": "image/png", "permission": permission,
            })
            self.assertEqual(status, 200)
            self.assertEqual(photo["photo"]["image_sha256"], self.digest)
            mode = "real" if number == 2 else "scripted"
            status, assessed = self.request("POST", f"/api/arrivals/{aid}/assessment",
                                            "volunteer", {"expected_revision": 1, "mode": mode})
            self.assertEqual(status, 200)
            self.assertEqual(assessed["arrival"]["assessment"]["origin"],
                             "unavailable" if number == 2 else "scripted_training")
            self.assertEqual(assessed["arrival"]["assessment"]["result"],
                             "Yes" if number == 1 else "Unsure" if number == 2 else "No")
            status, observed = self.request("POST", f"/api/arrivals/{aid}/observation",
                                            "volunteer", {"expected_revision": assessed["arrival"]["revision"],
                                                          "concern": number in (1, 2),
                                                          "text": "Illustrated exercise concern" if number in (1, 2) else ""})
            self.assertEqual(status, 200)
            if number in (1, 2):
                self.assertEqual(observed["arrival"]["care_state"], "awaiting_review")
                reviews.append(observed["arrival"]["review_revision"])
            else:
                self.assertEqual(observed["arrival"]["care_state"], "not_referred")
        return reviews

    def test_finish_and_care_completion_are_independent(self):
        self.assertEqual(self.request("GET", f"/api/intakes/{self.sid}", "unassigned")[0], 403)
        self.assertEqual(self.request("GET", f"/api/intakes/{self.sid}/aggregate", "volunteer")[0], 403)
        arrivals = self.confirm_arrivals(29)
        first, second = arrivals[:2]
        status, retried = self.request("POST", f"/api/intakes/{self.sid}/arrivals",
                                       "volunteer", {"operation_key": "e2e-1"})
        self.assertEqual((status, retried["arrival_id"]), (200, first))
        self.assertEqual(self.summary()["confirmed_count"], 29)
        reviews = self.assess_arrivals(arrivals)
        # Foreign and unknown arrival IDs are intentionally indistinguishable.
        self.assertEqual(self.request("GET", f"/api/arrivals/{first}/photo", "unassigned")[0], 404)
        self.assertEqual(self.request("POST", f"/api/arrivals/{first}/review-complete",
                                      "volunteer", {"expected_revision": reviews[0]})[0], 403)
        pre_finish = self.summary()
        self.assertEqual((pre_finish["expected_count"], pre_finish["confirmed_count"],
                          pre_finish["difference"], pre_finish["awaiting_reviews"]),
                         (30, 29, 1, 2))
        before_finish = self.request("GET", f"/api/intakes/{self.sid}", "volunteer")[1]["session_summary"]
        status, finished = self.request("POST", f"/api/intakes/{self.sid}/finish", "volunteer",
                                        {"expected_revision": before_finish["revision"]})
        self.assertEqual(status, 200)
        before = self.summary()
        self.assertEqual((before["expected_count"], before["confirmed_count"],
                          before["difference"], before["awaiting_reviews"]), (30, 29, 1, 2))
        self.assertEqual(finished["session_summary"]["intake_state"], "finished")
        # Complete the two pending human reviews over HTTP; no synthetic care rows.
        queue = self.request("GET", f"/api/intakes/{self.sid}/reviews", "care_reviewer")[1]["reviews"]
        self.assertEqual(len(queue), 2)
        for entry in queue:
            status, _ = self.request("POST", f"/api/arrivals/{entry['arrival_id']}/review-complete",
                                     "care_reviewer", {"expected_revision": entry["review_revision"]})
            self.assertEqual(status, 200)
        after = self.summary()
        self.assertEqual((after["confirmed_count"], after["difference"],
                          after["awaiting_reviews"], after["completed_reviews"]), (29, 1, 0, 2))
        self.assertEqual(self.store.summary(self.sid)["original_expected_count"], 30)
        self.assertEqual(self.store.connection.execute(
            "SELECT source_sha256 FROM sessions WHERE session_id=?", (self.sid,)).fetchone()[0],
            self.seed.source_sha256)

        # Coordinator records an attributable over-count, then corrects it.
        self.assertEqual(self.request("POST", f"/api/intakes/{self.sid}/corrections", "volunteer", {
            "expected_revision": 30, "reason": "unauthorized", "change": {"expected_count": 28}})[0], 403)
        revision = self.request("GET", f"/api/intakes/{self.sid}", "coordinator")[1]["session_summary"]["revision"]
        status, over = self.request("POST", f"/api/intakes/{self.sid}/corrections", "coordinator", {
            "expected_revision": revision, "reason": "Exercise over-count check",
            "change": {"expected_count": 28}})
        self.assertEqual(status, 200)
        self.assertEqual(over["session_summary"]["difference"], -1)
        status, corrected = self.request("POST", f"/api/intakes/{self.sid}/corrections", "coordinator", {
            "expected_revision": over["session_summary"]["revision"],
            "reason": "Restore source-backed count", "change": {"expected_count": 30}})
        self.assertEqual(status, 200)
        self.assertEqual(corrected["session_summary"]["difference"], 1)
        history = self.request("GET", f"/api/intakes/{self.sid}/history", "coordinator")[1]["history"]
        self.assertEqual([(entry["before"], entry["after"]) for entry in history], [(30, 28), (28, 30)])
        self.assertEqual(self.request("GET", f"/api/intakes/{self.sid}/history", "volunteer")[0], 403)

        # Stop the service before cleanup, then reopen SQLite and the HTTP service.
        self._stop()
        self.server.server_close()
        self.store.close()
        receipt = cleanup_demo(self.database, self.sid, "coordinator-e2e")
        self.assertEqual(receipt["removed_images"], 29)
        self.assertNotIn("image_base64", json.dumps(receipt))
        with IntakeStore(self.database) as reopened:
            self.assertEqual(reopened.summary(self.sid)["difference"], 1)
            self.assertEqual(reopened.summary(self.sid)["completed_reviews"], 2)
            self.assertIsNone(reopened.detail(first)["current_photo"])
            self.assertEqual(reopened.connection.execute("SELECT count(*) FROM images").fetchone()[0], 0)
            self.assertEqual(reopened.connection.execute("SELECT count(*) FROM photo_captures").fetchone()[0], 0)
        for suffix in ("-wal", "-journal"):
            artifact = Path(str(self.database) + suffix)
            self.assertTrue(not artifact.exists() or artifact.stat().st_size == 0)
        journal_sizes = {suffix: (artifact.stat().st_size if artifact.exists() else 0)
                         for suffix in ("-wal", "-journal")
                         for artifact in [Path(str(self.database) + suffix)]}
        # Fresh service confirms the private photo route is unavailable after cleanup.
        with IntakeStore(self.database) as reopened:
            photos = PhotoStore(reopened, {self.source_reference: {
                "source_kind": "operator_created_illustration",
                "image_sha256s": frozenset({self.digest}), "capture_allowed": True,
                "display_allowed": True, "processing_allowed": True}})
            server = make_server(reopened, Workflow(reopened, photos, ExerciseAssessor({})),
                                 photos, {sha256(self.tokens["volunteer"].encode()).hexdigest(): {
                                     "actor_id": "volunteer-e2e", "role": "volunteer", "session_ids": [self.sid]}},
                                 self.root / "static")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            prior_base, self.base = self.base, "http://127.0.0.1:%d" % server.server_address[1]
            try:
                for aid in arrivals:
                    self.assertEqual(self.request("GET", f"/api/arrivals/{aid}/photo", "volunteer")[0], 404)
            finally:
                self.base = prior_base
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
        # Safe for a controller's optional receipt runner only after every assertion.
        self.acceptance_trace = {
            "source_origin": "validated_TripExecutor_ledger_adapter",
            "source_sha256": self.seed.source_sha256,
            "source_refs": {"boarding_event_id": self.seed.boarding_event_id,
                            "departure_event_id": self.seed.departure_event_id,
                            "arrival_event_id": self.seed.arrival_event_id},
            "before_finish": {key: pre_finish[key] for key in
                              ("expected_count", "confirmed_count", "difference", "awaiting_reviews")},
            "after_finish": {key: before[key] for key in
                             ("expected_count", "confirmed_count", "difference", "awaiting_reviews")},
            "after_human_reviews": {key: after[key] for key in
                                    ("confirmed_count", "difference", "awaiting_reviews",
                                     "completed_reviews")},
            "correction_difference": [over["session_summary"]["difference"],
                                      corrected["session_summary"]["difference"]],
            "cleanup": receipt,
            "reopened_database": {"remaining_images": 0, "remaining_captures": 0,
                                  "journal_sizes": journal_sizes},
            "deleted_photo_http_404_count": len(arrivals),
        }


class PrivatePreparationTests(unittest.TestCase):
    def test_prepare_creates_private_roles_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "demo.sqlite"
            credentials = root / "credentials.json"
            result = prepare_demo(database, credentials)
            self.assertEqual(result["expected_count"], 30)
            self.assertNotIn("token", json.dumps(result).lower())
            self.assertEqual(result["illustration_sha256"], sha256(illustration_bytes()).hexdigest())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(credentials.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)
            config = json.loads(credentials.read_text(encoding="utf-8"))
            self.assertEqual(set(config["tokens"]), {"volunteer", "care_reviewer", "coordinator"})
            for role, token in config["tokens"].items():
                principal = config["token_registry"][sha256(token.encode()).hexdigest()]
                self.assertEqual((principal["role"], principal["session_ids"]),
                                 (role, [result["session_id"]]))
            with self.assertRaises(FileExistsError):
                prepare_demo(database, credentials)

    def test_custom_case_prepares_serves_bound_session_and_default_cleans(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, credentials = root / "custom.sqlite", root / "private.json"
            prepared = prepare_demo(database, credentials, case_id="custom-case")
            config = json.loads(credentials.read_text(encoding="utf-8"))
            self.assertEqual(config["case_id"], "custom-case")
            self.assertEqual(config["session_id"], prepared["session_id"])
            class NoServe:
                called = False
                def serve_forever(self): self.called = True
                def server_close(self): pass
            fake = NoServe()
            with patch("services.arrival_intake.demo.make_server", return_value=fake) as factory:
                serve_demo(database, credentials, 9901)
            self.assertTrue(fake.called)
            registry = factory.call_args.args[3]
            self.assertEqual({tuple(entry["session_ids"]) for entry in registry.values()},
                             {(prepared["session_id"],)})
            self.assertEqual(cleanup_demo(database)["session_id"], prepared["session_id"])

    def test_default_cleanup_refuses_ambiguous_exercise_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, credentials = root / "custom.sqlite", root / "private.json"
            prepare_demo(database, credentials, case_id="custom-case")
            with IntakeStore(database) as store:
                store.create_session(build_demo_seed("another-case"))
            with self.assertRaises(ValueError):
                cleanup_demo(database)


if __name__ == "__main__":
    unittest.main()
