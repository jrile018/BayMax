"""Real HTTP integration for request-bound photos, assessment and care review."""

import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

from services.arrival_intake.contracts import SessionSeed
from services.arrival_intake.photos import PhotoStore
from services.arrival_intake.server import make_server
from services.arrival_intake.store import IntakeStore
from services.arrival_intake.workflow import ExerciseAssessor, Workflow


class WorkflowHTTPTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.database = root / "intake.sqlite"
        self.store = IntakeStore(self.database)
        self.addCleanup(self.store.close)
        self.sid = self.store.create_session(SessionSeed(
            case_id="http-care", run_id="run", dispatch_id="dispatch-a",
            vehicle_id="bus", destination_node="shelter", expected_count=3,
            boarding_event_id="boarding-a", arrival_event_id="arrival-a",
            source_sha256="b" * 64,
        ))["session_id"]
        self.other_sid = self.store.create_session(SessionSeed(
            case_id="http-care", run_id="run", dispatch_id="dispatch-b",
            vehicle_id="bus", destination_node="shelter", expected_count=1,
            boarding_event_id="boarding-b", arrival_event_id="arrival-b",
            source_sha256="b" * 64,
        ))["session_id"]
        stream = BytesIO()
        Image.new("RGB", (8, 8), (35, 90, 120)).save(stream, format="PNG")
        self.image = stream.getvalue()
        digest = sha256(self.image).hexdigest()
        photos = PhotoStore(self.store, {"illustration-http": {
            "source_kind": "operator_created_illustration",
            "image_sha256s": frozenset({digest}),
            "capture_allowed": True, "display_allowed": True, "processing_allowed": True,
        }})
        workflow = Workflow(self.store, photos, ExerciseAssessor({1: "No", 2: "Unsure"}))
        self.tokens = {role: secrets.token_hex(32) for role in
                       ("volunteer", "care_reviewer", "coordinator", "other")}
        registry = {}
        for role, token in self.tokens.items():
            registry[sha256(token.encode("ascii")).hexdigest()] = {
                "actor_id": role + "-a",
                "role": "volunteer" if role == "other" else role,
                "session_ids": [self.other_sid] if role == "other" else [self.sid],
            }
        assets = root / "static"
        assets.mkdir()
        for name in ("index.html", "app.js", "style.css"):
            (assets / name).write_text("/* test */", encoding="utf-8")
        self.server = make_server(self.store, workflow, photos, registry, assets)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def _stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)

    def request(self, method, path, role, payload=None):
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
            return response.status, json.loads(response.read())

    def arrival(self, number):
        status, body = self.request("POST", f"/api/intakes/{self.sid}/arrivals", "volunteer",
                                    {"operation_key": f"arrival-{number}"})
        self.assertEqual(status, 200)
        return body["arrival_id"]

    def photo(self, aid, revision):
        return self.request("POST", f"/api/arrivals/{aid}/photo", "volunteer", {
            "expected_revision": revision,
            "image_base64": base64.b64encode(self.image).decode("ascii"),
            "media_type": "image/png",
            "permission": {
                "source_kind": "operator_created_illustration",
                "source_reference": "illustration-http",
                "capture_allowed": True, "display_allowed": True,
                "processing_allowed": True, "verified_by": "volunteer-a",
                "verified_at": "2026-10-10T12:00:00+00:00",
            },
        })

    def test_assessment_is_server_scripted_and_reviewer_route_closes_exact_revision(self):
        aid = self.arrival(1)
        status, photo = self.photo(aid, 0)
        self.assertEqual(status, 200)
        revision = photo["photo"]["arrival_revision"]
        status, _ = self.request("POST", f"/api/arrivals/{aid}/assessment", "volunteer", {
            "expected_revision": revision, "mode": "scripted", "result": "Yes"})
        self.assertEqual(status, 400)
        status, result = self.request("POST", f"/api/arrivals/{aid}/assessment", "volunteer", {
            "expected_revision": revision, "mode": "scripted"})
        self.assertEqual(status, 200)
        self.assertEqual(result["arrival"]["assessment"]["result"], "No")
        status, observation = self.request("POST", f"/api/arrivals/{aid}/observation", "volunteer", {
            "expected_revision": result["arrival"]["revision"], "concern": False, "text": ""})
        self.assertEqual(status, 200)
        self.assertEqual(observation["arrival"]["care_state"], "not_referred")
        self.assertEqual(observation["arrival"]["latest_volunteer_observation"]["concern"], False)
        status, concern = self.request("POST", f"/api/arrivals/{aid}/observation", "volunteer", {
            "expected_revision": observation["arrival"]["revision"],
            "concern": True, "text": "Reported pain"})
        self.assertEqual(status, 200)
        self.assertEqual(concern["arrival"]["care_state"], "awaiting_review")
        status, queue = self.request("GET", f"/api/intakes/{self.sid}/reviews", "care_reviewer")
        self.assertEqual(status, 200)
        self.assertEqual([entry["arrival_id"] for entry in queue["reviews"]], [aid])
        required = concern["arrival"]["review_revision"]
        self.assertEqual(self.request("POST", f"/api/arrivals/{aid}/review-complete",
                                      "volunteer", {"expected_revision": required})[0], 403)
        self.assertEqual(self.request("POST", f"/api/arrivals/{aid}/review-complete",
                                      "care_reviewer", {"expected_revision": required + 1})[0], 409)
        status, completed = self.request("POST", f"/api/arrivals/{aid}/review-complete",
                                         "care_reviewer", {"expected_revision": required})
        self.assertEqual(status, 200)
        self.assertEqual(completed["arrival"]["care_state"], "review_complete")
        self.assertEqual(self.request("GET", f"/api/intakes/{self.sid}/reviews",
                                      "care_reviewer")[1]["reviews"], [])
        summary = self.request("GET", f"/api/intakes/{self.sid}/aggregate", "coordinator")[1]
        self.assertEqual((summary["confirmed_count"], summary["awaiting_reviews"],
                          summary["completed_reviews"]), (1, 0, 1))

    def test_finish_skips_unassessed_and_pending_photo_and_enforces_roles(self):
        first = self.arrival(1)
        second = self.arrival(2)
        self.assertEqual(self.photo(second, 0)[0], 200)
        self.assertEqual(self.request("GET", f"/api/intakes/{self.sid}/reviews",
                                      "volunteer")[0], 403)
        self.assertEqual(self.request("POST", f"/api/intakes/{self.sid}/finish",
                                      "care_reviewer", {"expected_revision": 2})[0], 403)
        self.assertEqual(self.request("GET", f"/api/intakes/{self.other_sid}/reviews",
                                      "care_reviewer")[0], 403)
        status, finished = self.request("POST", f"/api/intakes/{self.sid}/finish", "volunteer",
                                        {"expected_revision": 2})
        self.assertEqual(status, 200)
        summary = finished["session_summary"]
        self.assertEqual((summary["intake_state"], summary["confirmed_count"],
                          summary["awaiting_reviews"]), ("finished", 2, 2))
        for aid in (first, second):
            status, detail = self.request("GET", f"/api/arrivals/{aid}", "volunteer")
            self.assertEqual(status, 200)
            self.assertEqual(detail["arrival"]["assessment"]["result"], "Unsure")
        self.assertEqual(self.request("POST", f"/api/intakes/{self.sid}/finish", "volunteer",
                                      {"expected_revision": 2})[0], 409)
        self.assertEqual(self.request("GET", f"/api/intakes/{self.sid}/reviews",
                                      "care_reviewer")[1]["reviews"].__len__(), 2)

    def test_request_adapters_survive_original_store_closure(self):
        aid = self.arrival(1)
        self.store.close()
        status, photo = self.photo(aid, 0)
        self.assertEqual(status, 200)
        status, result = self.request("POST", f"/api/arrivals/{aid}/assessment", "volunteer", {
            "expected_revision": photo["photo"]["arrival_revision"], "mode": "real"})
        self.assertEqual(status, 200)
        self.assertEqual((result["arrival"]["assessment"]["result"],
                          result["arrival"]["assessment"]["origin"]), ("Unsure", "unavailable"))
        self.assertEqual(self.request("GET", f"/api/intakes/{self.sid}/reviews",
                                      "care_reviewer")[0], 200)
        with IntakeStore(self.database) as verification:
            self.assertEqual(verification.summary(self.sid)["confirmed_count"], 1)
            self.assertEqual(verification.summary(self.sid)["awaiting_reviews"], 1)


if __name__ == "__main__":
    unittest.main()
