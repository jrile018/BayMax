"""HTTP contracts for the assigned intake web entry and aggregate projection.

These tests exercise the threaded Python server. They do not execute browser JS.
"""

from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from services.arrival_intake.contracts import SessionSeed
from services.arrival_intake.server import make_server
from services.arrival_intake.store import IntakeStore


WEB_ROOT = Path(__file__).resolve().parents[3] / "web"
INTAKE_ROOT = WEB_ROOT / "intake"
AGGREGATE_KEYS = {
    "session_id", "case_id", "vehicle_id", "destination_node", "mode",
    "expected_count", "confirmed_count", "difference", "intake_state",
    "awaiting_reviews", "completed_reviews",
}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(value for name, value in attrs if name == "href")


class WebContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = IntakeStore(Path(directory.name) / "intake.sqlite")
        self.addCleanup(self.store.close)
        self.sid = self.store.create_session(SessionSeed(
            case_id="web-contract", run_id="run", dispatch_id="dispatch",
            vehicle_id="bus-7", destination_node="shelter-east", expected_count=2,
            boarding_event_id="board-web", arrival_event_id="arrive-web",
            source_sha256="d" * 64,
        ))["session_id"]
        self.tokens = {role: secrets.token_hex(32) for role in
                       ("coordinator", "volunteer", "care_reviewer", "unassigned")}
        registry = {}
        for role, token in self.tokens.items():
            registry[sha256(token.encode("ascii")).hexdigest()] = {
                "actor_id": role + "-web",
                "role": "coordinator" if role == "unassigned" else role,
                "session_ids": [] if role == "unassigned" else [self.sid],
            }
        # Materialize the asset directory for a useful RED when a page is
        # missing: the real allowlist returns 404, rather than setup failing.
        static_root = Path(directory.name) / "static"
        static_root.mkdir()
        for name in ("index.html", "app.js", "camera.js", "style.css"):
            source = INTAKE_ROOT / name
            if source.is_file():
                (static_root / name).write_bytes(source.read_bytes())
        self.server = make_server(self.store, None, None, registry, static_root)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def _stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)

    def request(self, path, role=None):
        headers = {"Authorization": "Bearer " + self.tokens[role]} if role else {}
        request = Request(self.base + path, headers=headers)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), response.headers

    def test_aggregate_http_response_is_exactly_bus_level(self):
        arrival = self.store.confirm_arrival(self.sid, "private-operation", "volunteer")
        status, raw, headers = self.request(
            f"/api/intakes/{self.sid}/aggregate", role="coordinator")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        aggregate = json.loads(raw)
        self.assertEqual(set(aggregate), AGGREGATE_KEYS)
        self.assertEqual(aggregate["vehicle_id"], "bus-7")
        self.assertEqual(aggregate["destination_node"], "shelter-east")
        self.assertEqual(aggregate["confirmed_count"], 1)
        self.assertNotIn(arrival["arrival_id"], raw.decode("utf-8"))
        forbidden = {
            "arrival_id", "arrival_number", "arrivals", "photo", "photos",
            "image_base64", "image_sha256", "current_photo", "symptoms",
            "name", "passenger_id", "person_ids", "human_concerns", "assessment",
        }
        self.assertTrue(set(aggregate).isdisjoint(forbidden))

    def test_correction_history_is_attributed_and_role_bound(self):
        arrival = self.store.confirm_arrival(self.sid, "one", "volunteer-web")
        summary = self.store.summary(self.sid)
        self.store.correct(self.sid, summary["revision"], "coordinator-web",
                           "dispatch count amended", {"expected_count": 3})
        summary = self.store.summary(self.sid)
        self.store.correct(self.sid, summary["revision"], "coordinator-web",
                           "duplicate attendance", {
                               "arrival_id": arrival["arrival_id"], "counted": False})
        path = f"/api/intakes/{self.sid}/history"
        status, raw, headers = self.request(path, role="coordinator")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        history = json.loads(raw)["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["actor_id"], "coordinator-web")
        self.assertEqual(history[0]["reason"], "dispatch count amended")
        self.assertEqual(history[0]["change"], "expected_count")
        self.assertEqual((history[0]["before"], history[0]["after"]), (2, 3))
        self.assertTrue(history[0]["occurred_at"])
        self.assertEqual(history[1]["change"], "attendance")
        self.assertEqual(history[1]["arrival_id"], arrival["arrival_id"])
        self.assertEqual((history[1]["before"], history[1]["after"]),
                         ("confirmed", "voided"))
        self.assertFalse({"photo", "image_sha256", "assessment", "human_concerns"}
                         & set(history[1]))
        self.assertEqual(self.request(path)[0], 401)
        for role in ("volunteer", "care_reviewer", "unassigned"):
            with self.subTest(role=role):
                self.assertEqual(self.request(path, role=role)[0], 403)

    def test_same_value_expected_count_has_honest_history_when_finished(self):
        summary = self.store.summary(self.sid)
        self.store.finish_intake(self.sid, summary["revision"], "volunteer-web")
        finished = self.store.summary(self.sid)
        self.store.correct(self.sid, finished["revision"], "coordinator-web",
                           "Verified count without changing it",
                           {"expected_count": finished["expected_count"]})
        status, raw, _ = self.request(f"/api/intakes/{self.sid}/history", role="coordinator")
        self.assertEqual(status, 200)
        history = json.loads(raw)["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["change"], "expected_count")
        self.assertEqual((history[0]["before"], history[0]["after"]),
                         (finished["expected_count"], finished["expected_count"]))
        self.assertEqual(self.store.summary(self.sid)["intake_state"], "finished")
        self.assertEqual(history[0]["actor_id"], "coordinator-web")

    def test_legacy_same_value_correction_is_not_invented_as_reopen(self):
        self.store.correct(self.sid, self.store.summary(self.sid)["revision"],
                           "coordinator-web", "Legacy equal count", {"expected_count": 2})
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE events SET correction_kind=NULL WHERE event_type='attendance_correction'")
        status, raw, _ = self.request(f"/api/intakes/{self.sid}/history", role="coordinator")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["history"][0]["change"], "unknown")

    def test_intake_assets_are_served_from_explicit_static_routes(self):
        assets = {
            "/": "text/html",
            "/index.html": "text/html",
            "/app.js": "text/javascript",
            "/camera.js": "text/javascript",
            "/style.css": "text/css",
        }
        for path, media_type in assets.items():
            with self.subTest(path=path):
                status, body, headers = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertTrue(headers["Content-Type"].startswith(media_type))
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(headers["Permissions-Policy"],
                                 "camera=(self), microphone=()")
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for path in ("/intake.sqlite", "/../intake.sqlite",
                     "/private.json", "/unknown.js", "/arrival-summary.js"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_unconfigured_dashboard_does_not_advertise_intake_route(self):
        # The separate legacy dashboard receives its entry only through trusted
        # bootstrap configuration; its static shell must not advertise one.
        body = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        links = _Links()
        links.feed(body)
        self.assertFalse(any(urlsplit(href).path.startswith("/intake/")
                             or urlsplit(href).path == "/intake"
                             for href in links.hrefs))
        summary_module = (WEB_ROOT / "arrival-summary.js").read_text(encoding="utf-8")
        self.assertNotIn("/intake/index.html", summary_module)
        self.assertNotIn('"arrival_intake_url":"/intake/index.html"', body)


if __name__ == "__main__":
    unittest.main()
