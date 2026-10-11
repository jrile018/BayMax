"""Real threaded HTTP tests for the separate assigned intake API."""

import hashlib
import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from services.arrival_intake.contracts import SessionSeed
from services.arrival_intake.server import make_server
from services.arrival_intake.store import IntakeStore


class IntakeHTTPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.store = IntakeStore(root / "intake.sqlite")
        self.addCleanup(self.store.close)
        self.sid = self._seed("dispatch-a")
        self.other_sid = self._seed("dispatch-b")
        self.tokens = {role: secrets.token_hex(32) for role in
                       ("volunteer", "coordinator", "care_reviewer", "other_volunteer")}
        self.registry = {}
        for role, token in self.tokens.items():
            actual_role = "volunteer" if role == "other_volunteer" else role
            sessions = [self.other_sid] if role == "other_volunteer" else [self.sid]
            self.registry[hashlib.sha256(token.encode("ascii")).hexdigest()] = {
                "actor_id": role + "-a", "role": actual_role, "session_ids": sessions,
            }
        self.web_root = root / "static"
        self.web_root.mkdir()
        for name in ("index.html", "app.js", "style.css"):
            (self.web_root / name).write_text("/* fixture */", encoding="utf-8")
        self.server = make_server(self.store, None, None, self.registry, self.web_root)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def _stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)

    def _seed(self, dispatch_id):
        return self.store.create_session(SessionSeed(
            case_id="case-demo", run_id="run-demo", dispatch_id=dispatch_id,
            vehicle_id="bus-3", destination_node="shelter-a", expected_count=3,
            boarding_event_id="board-" + dispatch_id,
            arrival_event_id="arrive-" + dispatch_id,
            source_sha256="a" * 64,
        ))["session_id"]

    def request(self, method, path, role=None, payload=None, headers=None):
        request_headers = dict(headers or {})
        if role is not None:
            request_headers["Authorization"] = "Bearer " + self.tokens[role]
        data = None
        if payload is not None:
            data = json.dumps(payload, allow_nan=True).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        req = Request(self.base + path, data=data, headers=request_headers, method=method)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            body = json.loads(raw) if raw and content_type.startswith("application/json") else raw
            return response.status, body, response.headers

    def test_unauthenticated_private_routes_are_401(self):
        routes = (
            ("GET", "/api/me", None),
            ("GET", "/api/intakes", None),
            ("GET", f"/api/intakes/{self.sid}", None),
            ("GET", f"/api/intakes/{self.sid}/aggregate", None),
            ("GET", f"/api/intakes/{self.sid}/reviews", None),
            ("GET", "/api/arrivals/guessed", None),
            ("GET", "/api/arrivals/guessed/photo", None),
            ("POST", f"/api/intakes/{self.sid}/arrivals", {"operation_key": "op-a"}),
            ("POST", f"/api/intakes/{self.sid}/finish", {"expected_revision": 0}),
            ("POST", f"/api/intakes/{self.sid}/corrections", {"expected_revision": 0,
                "reason": "exercise", "change": {"expected_count": 2}}),
            ("POST", "/api/arrivals/guessed/photo", None),
            ("POST", "/api/arrivals/guessed/assessment", {}),
            ("POST", "/api/arrivals/guessed/concerns", {}),
            ("POST", "/api/arrivals/guessed/review-complete", {}),
        )
        for method, path, payload in routes:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(method, path, payload=payload)[0], 401)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 0)

    def test_identity_list_detail_and_aggregate_shapes(self):
        status, me, headers = self.request("GET", "/api/me", "volunteer")
        self.assertEqual(status, 200)
        self.assertEqual(me, {"actor_id": "volunteer-a", "role": "volunteer",
                              "session_ids": [self.sid]})
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        status, listing, _ = self.request("GET", "/api/intakes", "volunteer")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["intakes"]), 1)
        self.assertEqual(listing["intakes"][0]["session_id"], self.sid)
        status, detail, _ = self.request("GET", f"/api/intakes/{self.sid}", "volunteer")
        self.assertEqual(status, 200)
        self.assertEqual(detail["session_summary"]["session_id"], self.sid)
        self.assertEqual(detail["arrivals"], [])
        status, aggregate, _ = self.request("GET", f"/api/intakes/{self.sid}/aggregate", "coordinator")
        self.assertEqual(status, 200)
        self.assertEqual(aggregate["session_id"], self.sid)
        self.assertTrue(set(aggregate).isdisjoint({"arrivals", "arrival_id", "reported_symptoms",
                                                  "observed_concern", "person_ids", "photos"}))

    def test_explicit_unassigned_session_is_403_before_lookup(self):
        for sid in (self.other_sid, "missing-session"):
            for path in (f"/api/intakes/{sid}", f"/api/intakes/{sid}/aggregate",
                         f"/api/intakes/{sid}/reviews"):
                with self.subTest(path=path):
                    self.assertEqual(self.request("GET", path, "volunteer")[0], 403)
            self.assertEqual(self.request("POST", f"/api/intakes/{sid}/arrivals", "volunteer",
                                          {"operation_key": "op-a"})[0], 403)

    def test_arrival_lookup_hides_existing_unassigned_and_missing_ids(self):
        own = self.store.confirm_arrival(self.sid, "own", "fixture")["arrival_id"]
        other = self.store.confirm_arrival(self.other_sid, "other", "fixture")["arrival_id"]
        for aid in (other, "missing-arrival"):
            for suffix in ("", "/photo"):
                with self.subTest(aid=aid, suffix=suffix):
                    self.assertEqual(self.request("GET", f"/api/arrivals/{aid}{suffix}", "volunteer")[0], 404)
            self.assertEqual(self.request("POST", f"/api/arrivals/{aid}/concerns", "volunteer",
                                          {"expected_revision": 0, "text": "check"})[0], 404)
        self.assertEqual(self.request("GET", f"/api/arrivals/{own}", "volunteer")[0], 200)

    def test_confirmation_uses_authenticated_actor_and_retry_key(self):
        path = f"/api/intakes/{self.sid}/arrivals"
        status, first, _ = self.request("POST", path, "volunteer", {"operation_key": "capture-07"})
        self.assertEqual(status, 200)
        self.assertEqual(first["session_summary"]["confirmed_count"], 1)
        self.assertEqual(self.request("POST", path, "volunteer",
                                      {"operation_key": "capture-07"})[1]["arrival_id"], first["arrival_id"])
        self.assertEqual(self.store.detail(first["arrival_id"])["confirmed_by"], "volunteer-a")
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)
        status, _, _ = self.request("POST", path, "volunteer", {"operation_key": "forged",
                                                                 "actor_id": "coordinator-a", "role": "coordinator"})
        self.assertEqual(status, 400)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 1)

    def test_role_denials_and_stale_revision_do_not_mutate(self):
        correction = {"expected_revision": 0, "reason": "count correction",
                      "change": {"expected_count": 2}}
        self.assertEqual(self.request("POST", f"/api/intakes/{self.sid}/corrections",
                                      "volunteer", correction)[0], 403)
        self.assertEqual(self.request("POST", f"/api/intakes/{self.sid}/finish",
                                      "coordinator", {"expected_revision": 0})[0], 403)
        self.assertEqual(self.request("POST", f"/api/intakes/{self.sid}/arrivals",
                                      "care_reviewer", {"operation_key": "x"})[0], 403)
        self.assertEqual(self.store.summary(self.sid)["revision"], 0)
        self.assertEqual(self.request("POST", f"/api/intakes/{self.sid}/corrections",
                                      "coordinator", {**correction, "expected_revision": 1})[0], 409)
        self.assertEqual(self.request("POST", f"/api/intakes/{self.sid}/corrections",
                                      "coordinator", correction)[0], 200)
        self.assertEqual(self.store.summary(self.sid)["expected_count"], 2)

    def test_volunteer_cannot_close_care_review_even_with_forged_role(self):
        aid = self.store.confirm_arrival(self.sid, "own", "fixture")["arrival_id"]
        status, _, headers = self.request("POST", f"/api/arrivals/{aid}/review-complete",
                                          "volunteer", {"expected_revision": 0,
                                                        "role": "care_reviewer", "actor_id": "reviewer-a"})
        self.assertEqual(status, 403)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.store.detail(aid)["revision"], 0)

    def test_unavailable_workflow_and_photo_routes_return_503_without_mutation(self):
        aid = self.store.confirm_arrival(self.sid, "a", "fixture")["arrival_id"]
        before = self.store.detail(aid)
        routes = (
            ("POST", f"/api/arrivals/{aid}/assessment", {"expected_revision": 0,
                "mode": "scripted"}),
            ("POST", f"/api/arrivals/{aid}/concerns", {"expected_revision": 0,
                "text": "check"}),
            ("POST", f"/api/arrivals/{aid}/review-complete", {"expected_revision": 0}),
            ("GET", f"/api/intakes/{self.sid}/reviews", None),
            ("GET", f"/api/arrivals/{aid}/photo", None),
        )
        for method, path, payload in routes:
            role = "care_reviewer" if "review" in path else "volunteer"
            with self.subTest(path=path):
                self.assertEqual(self.request(method, path, role, payload)[0], 503)
        self.assertEqual(self.store.detail(aid), before)

    def test_rejects_unknown_fields_nan_media_type_and_oversized_or_chunked_body(self):
        path = f"/api/intakes/{self.sid}/arrivals"
        for payload in ({"operation_key": "x", "extra": True},
                        {"operation_key": "x", "weight": float("nan")}):
            with self.subTest(payload=payload):
                self.assertEqual(self.request("POST", path, "volunteer", payload)[0], 400)
        self.assertEqual(self.request("POST", path, "volunteer", headers={
            "Content-Type": "text/plain"}, payload={"operation_key": "x"})[0], 400)
        self.assertEqual(self.request("POST", path, "volunteer", headers={
            "Content-Type": "application/json", "Content-Length": "99999999"},
            payload={"operation_key": "x"})[0], 400)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        self.addCleanup(connection.close)
        connection.putrequest("POST", path)
        connection.putheader("Authorization", "Bearer " + self.tokens["volunteer"])
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Transfer-Encoding", "chunked")
        connection.endheaders()
        connection.send(b"1\r\nx\r\n0\r\n\r\n")
        self.assertEqual(connection.getresponse().status, 400)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 0)

    def test_static_assets_are_fixed_and_private_paths_not_served(self):
        for path in ("/", "/index.html", "/app.js", "/style.css"):
            status, _, headers = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        for path in ("/intake.sqlite", "/../intake.sqlite", "/schema.sql", "/random.js"):
            self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("PUT", f"/api/intakes/{self.sid}", "volunteer", {})[0], 405)
        self.assertEqual(self.request("GET", f"/api/intakes/{self.sid}?token=ignored",
                                      "volunteer")[0], 400)


if __name__ == "__main__":
    unittest.main()
