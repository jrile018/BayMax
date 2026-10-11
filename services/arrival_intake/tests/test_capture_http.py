"""Real HTTP controls for default-denied assigned capture routes.

All images and grants here are synthetic; no participant or camera is used.
"""

import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw

from services.arrival_intake.capture import CaptureAuthority, CaptureService
from services.arrival_intake.demo import build_demo_seed, illustration_bytes
from services.arrival_intake.photos import PhotoStore
from services.arrival_intake.server import make_server
from services.arrival_intake.store import IntakeStore


class CaptureHTTPTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.store = IntakeStore(root / "intake.sqlite")
        self.addCleanup(self.store.close)
        self.sid = self.store.create_session(build_demo_seed("capture-http"))["session_id"]
        self.aid = self.store.confirm_arrival(self.sid, "synthetic-arrival-1", "volunteer-a")["arrival_id"]
        self.other_aid = self.store.confirm_arrival(self.sid, "synthetic-arrival-2", "volunteer-a")["arrival_id"]
        self.now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
        self.grant = {
            "grant_id": "synthetic-http-grant", "consent_reference": "synthetic-control-only",
            "verified_by": "root-verifier", "verified_at": self.now - timedelta(minutes=1),
            "expires_at": self.now + timedelta(minutes=10),
            "purposes": frozenset({"preview", "capture", "display", "assessment"}),
        }
        self.later_grant = {**self.grant, "grant_id": "synthetic-http-later-grant",
                            "expires_at": self.now + timedelta(minutes=30)}
        self.authority = CaptureAuthority({
            (self.sid, self.aid, "volunteer-a"): self.grant,
            (self.sid, self.aid, "volunteer-b"): self.later_grant,
        },
                                          clock=lambda: self.now)
        self.authority.provision_grants(self.store)
        self.photos = PhotoStore(self.store, capture_authority=self.authority)
        self.capture = CaptureService(self.store, self.photos, self.authority)
        self.tokens = {role: secrets.token_hex(32) for role in
                       ("volunteer", "foreign", "coordinator", "care_reviewer")}
        registry = {}
        for role, token in self.tokens.items():
            registry[sha256(token.encode("ascii")).hexdigest()] = {
                "actor_id": {"volunteer": "volunteer-a", "foreign": "volunteer-b",
                             "coordinator": "coordinator-a", "care_reviewer": "reviewer-a"}[role],
                "role": "volunteer" if role == "foreign" else role,
                "session_ids": [self.sid],
            }
        assets = root / "static"
        assets.mkdir()
        for name in ("index.html", "app.js", "style.css"):
            (assets / name).write_text("synthetic fixture", encoding="utf-8")
        self.server = make_server(self.store, None, self.photos, registry, assets,
                                  capture_service=self.capture)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.image_b64 = base64.b64encode(illustration_bytes()).decode("ascii")
        with Image.open(BytesIO(illustration_bytes())) as synthetic:
            changed = synthetic.copy()
        ImageDraw.Draw(changed).rectangle((18, 18, 70, 65), fill=(12, 98, 166))
        changed_bytes = BytesIO()
        changed.save(changed_bytes, format="PNG")
        self.later_image_b64 = base64.b64encode(changed_bytes.getvalue()).decode("ascii")

    def _stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)

    def request(self, method, path, role=None, payload=None):
        headers = {}
        if role is not None:
            headers["Authorization"] = "Bearer " + self.tokens[role]
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        req = Request(self.base + path, data=body, headers=headers, method=method)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            parsed = json.loads(raw) if response.headers.get("Content-Type", "").startswith(
                "application/json") and raw else raw
            return response.status, parsed, response.headers

    def start(self, role="volunteer", revision=0):
        status, body, _ = self.request("POST", f"/api/arrivals/{self.aid}/capture-session",
                                       role, {"expected_revision": revision})
        self.assertEqual(status, 200)
        return body["capture_session_id"]

    def commit_http(self, handle, role="volunteer", revision=0, image_b64=None):
        return self.request("POST", f"/api/capture-sessions/{handle}/capture", role, {
            "expected_revision": revision,
            "image_base64": self.image_b64 if image_b64 is None else image_b64,
            "media_type": "image/png",
        })

    def test_default_denial_foreign_and_unknown_are_indistinguishable(self):
        path = f"/api/arrivals/{self.other_aid}/capture-session"
        self.assertEqual(self.request("POST", path, "volunteer", {"expected_revision": 0})[0], 403)
        self.assertEqual(self.request("POST", "/api/arrivals/unknown/capture-session",
                                      "volunteer", {"expected_revision": 0})[0], 404)
        self.assertEqual(self.request("POST", f"/api/arrivals/{self.aid}/capture-session",
                                      None, {"expected_revision": 0})[0], 401)
        self.assertEqual(self.request("POST", f"/api/arrivals/{self.aid}/capture-session",
                                      "coordinator", {"expected_revision": 0})[0], 403)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def test_http_capture_preview_status_and_private_display_lease(self):
        handle = self.start()
        status, preview, _ = self.request("POST", f"/api/capture-sessions/{handle}/preview",
                                           "volunteer", {"frame_id": 1,
                                           "image_base64": self.image_b64, "media_type": "image/png"})
        self.assertEqual(status, 200)
        self.assertEqual(preview["frame_id"], 1)
        self.assertEqual(preview["status"], "unavailable")
        status, saved, _ = self.request("POST", f"/api/capture-sessions/{handle}/capture",
                                         "volunteer", {"expected_revision": 0,
                                         "image_base64": self.image_b64, "media_type": "image/png"})
        self.assertEqual(status, 200)
        self.assertEqual(saved["arrival"]["revision"], 1)
        self.assertEqual(saved["photo"]["arrival_revision"], 1)
        self.assertEqual(self.request("GET", f"/api/capture-sessions/{handle}", "volunteer")[1]["photo"],
                         saved["photo"])
        status, detail, headers = self.request("GET", f"/api/arrivals/{self.aid}", "volunteer")
        self.assertEqual(status, 200)
        lease = detail["arrival"]["display_authorization"]
        self.assertEqual(lease["grant_id"], self.grant["grant_id"])
        self.assertLessEqual(lease["lease_ms"], 5000)
        self.assertGreater(lease["lease_ms"], 0)
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, photo, headers = self.request("GET", f"/api/arrivals/{self.aid}/photo", "volunteer")
        self.assertEqual(status, 200)
        self.assertEqual(sha256(photo).hexdigest(), saved["photo"]["image_sha256"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Display-Grant-Id"], self.grant["grant_id"])
        self.assertLessEqual(int(headers["X-Display-Lease-Ms"]), 5000)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def test_http_rejects_client_authority_and_hides_foreign_session(self):
        path = f"/api/arrivals/{self.aid}/capture-session"
        for extra in ({"consent_reference": "forged"}, {"grant_id": "forged"},
                      {"model_revision": "forged"}, {"actor_id": "volunteer-a"}):
            with self.subTest(extra=extra):
                self.assertEqual(self.request("POST", path, "volunteer",
                                              {"expected_revision": 0, **extra})[0], 400)
        handle = self.start()
        capture_path = f"/api/capture-sessions/{handle}/capture"
        for extra in ({"image_sha256": "0" * 64}, {"consent_reference": "forged"},
                      {"permission": {"source_kind": "adult_staged"}},
                      {"model_evidence": {"verified": True}}):
            with self.subTest(extra=extra):
                self.assertEqual(self.request("POST", capture_path, "volunteer", {
                    "expected_revision": 0, "image_base64": self.image_b64,
                    "media_type": "image/png", **extra})[0], 400)
        for cid in (handle, "unknown-capture"):
            self.assertEqual(self.request("GET", f"/api/capture-sessions/{cid}", "foreign")[0], 404)
        self.assertEqual(self.request("POST", capture_path, "care_reviewer", {
            "expected_revision": 0, "image_base64": self.image_b64,
            "media_type": "image/png"})[0], 403)
        self.assertEqual(self.store.detail(self.aid)["revision"], 0)

    def test_revoked_live_detail_photo_and_status_after_cleanup(self):
        handle = self.start()
        self.assertEqual(self.request("POST", f"/api/capture-sessions/{handle}/capture",
                                      "volunteer", {"expected_revision": 0,
                                      "image_base64": self.image_b64,
                                      "media_type": "image/png"})[0], 200)
        with IntakeStore(self.store.database_path) as other:
            self.authority.revoke_grant(other, self.grant["grant_id"], 1, "root-operator")
        status, detail, _ = self.request("GET", f"/api/arrivals/{self.aid}", "volunteer")
        self.assertIn(status, (200, 403))
        if status == 200:
            self.assertIsNone(detail["arrival"].get("current_photo"))
            self.assertNotIn("display_authorization", detail["arrival"])
        self.assertEqual(self.request("GET", f"/api/arrivals/{self.aid}/photo", "volunteer")[0], 403)
        self.photos.cleanup(self.sid, "coordinator-a")
        self.assertEqual(self.request("GET", f"/api/capture-sessions/{handle}", "volunteer")[0], 404)
        self.assertEqual(self.request("GET", f"/api/arrivals/{self.aid}/photo", "volunteer")[0], 404)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def _retake_while_display_paused(self, route_kind):
        first_handle = self.start()
        first_status, first_saved, _ = self.commit_http(first_handle)
        self.assertEqual(first_status, 200)
        first_id = first_saved["photo"]["image_id"]
        first_digest = first_saved["photo"]["image_sha256"]
        entered, resume = threading.Event(), threading.Event()
        outcome = {}

        if route_kind == "photo":
            original = PhotoStore._current_image

            def paused_read(instance, aid, purpose):
                result = original(instance, aid, purpose)
                if aid == self.aid and not entered.is_set():
                    entered.set()
                    if not resume.wait(5):
                        raise AssertionError("synthetic photo barrier timed out")
                return result

            context = patch.object(PhotoStore, "_current_image", paused_read)
            path = f"/api/arrivals/{self.aid}/photo"
        else:
            original = IntakeStore.detail

            def paused_detail(instance, aid):
                result = original(instance, aid)
                if (aid == self.aid and result["current_photo"] is not None and
                        result["current_photo"]["image_id"] == first_id and
                        not entered.is_set()):
                    entered.set()
                    if not resume.wait(5):
                        raise AssertionError("synthetic detail barrier timed out")
                return result

            context = patch.object(IntakeStore, "detail", paused_detail)
            path = f"/api/arrivals/{self.aid}"

        def read_private():
            outcome["response"] = self.request("GET", path, "volunteer")

        with context:
            reader = threading.Thread(target=read_private, daemon=True)
            reader.start()
            try:
                self.assertTrue(entered.wait(5), "the real HTTP read never reached its barrier")
                second_handle = self.start("foreign", revision=1)
                second_status, second_saved, _ = self.commit_http(
                    second_handle, "foreign", revision=1, image_b64=self.later_image_b64)
                self.assertEqual(second_status, 200)
                self.now = self.grant["expires_at"] + timedelta(seconds=1)
            finally:
                resume.set()
                reader.join(timeout=5)
        self.assertFalse(reader.is_alive())
        self.assertIn("response", outcome)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)
        self.assertEqual(self.store.detail(self.aid)["current_photo"]["image_id"],
                         second_saved["photo"]["image_id"])
        return outcome["response"], first_digest, first_id, second_saved

    def test_photo_bytes_and_display_lease_remain_bound_across_retake(self):
        (status, body, headers), first_digest, _, second = self._retake_while_display_paused("photo")
        if status == 200:
            digest = sha256(body).hexdigest()
            if digest == first_digest:
                self.assertEqual(headers["X-Display-Grant-Id"], self.grant["grant_id"])
                self.assertLessEqual(datetime.fromisoformat(headers["X-Display-Expires-At"]),
                                     self.grant["expires_at"])
            elif digest == second["photo"]["image_sha256"]:
                self.assertEqual(headers["X-Display-Grant-Id"], self.later_grant["grant_id"])
            else:
                self.fail("HTTP returned bytes from neither exact stored capture")
        else:
            self.assertIn(status, (403, 409))

    def test_detail_capture_and_display_lease_remain_bound_across_retake(self):
        (status, body, _), _, first_id, second = self._retake_while_display_paused("detail")
        if status == 200:
            displayed_id = body["arrival"]["current_photo"]["image_id"]
            grant_id = body["arrival"]["display_authorization"]["grant_id"]
            if displayed_id == first_id:
                self.assertEqual(grant_id, self.grant["grant_id"])
                self.assertLessEqual(
                    datetime.fromisoformat(body["arrival"]["display_authorization"]["expires_at"]),
                    self.grant["expires_at"])
            elif displayed_id == second["photo"]["image_id"]:
                self.assertEqual(grant_id, self.later_grant["grant_id"])
            else:
                self.fail("detail returned neither exact stored capture")
        else:
            self.assertIn(status, (403, 409))

    def test_consumed_http_retry_after_retake_marks_historical_receipt(self):
        first_handle = self.start()
        first_status, first_saved, _ = self.commit_http(first_handle)
        self.assertEqual(first_status, 200)
        current_status, current_retry, _ = self.commit_http(first_handle)
        self.assertEqual(current_status, 200)  # interrupted current save recovers
        self.assertEqual(current_retry["photo"], first_saved["photo"])
        self.assertTrue(self.request("GET", f"/api/capture-sessions/{first_handle}",
                                     "volunteer")[1]["is_current"])
        second_handle = self.start("foreign", revision=1)
        second_status, second_saved, _ = self.commit_http(
            second_handle, "foreign", revision=1, image_b64=self.later_image_b64)
        self.assertEqual(second_status, 200)
        stale_status, stale_retry, _ = self.commit_http(first_handle)
        if stale_status == 200:
            self.assertIs(stale_retry.get("is_current"), False)
            self.assertEqual(stale_retry["photo"], first_saved["photo"])
            self.assertEqual(stale_retry["arrival"]["current_photo"]["image_id"],
                             second_saved["photo"]["image_id"])
        else:
            self.assertEqual(stale_status, 409)
            self.assertFalse(self.request("GET", f"/api/capture-sessions/{first_handle}",
                                          "volunteer")[1]["is_current"])
        self.assertEqual(self.store.detail(self.aid)["revision"], 2)
        self.assertEqual(self.store.detail(self.aid)["current_photo"]["image_id"],
                         second_saved["photo"]["image_id"])
        self.assertEqual(self.store.connection.execute(
            "SELECT count(*) FROM photo_captures WHERE arrival_id=?", (self.aid,)).fetchone()[0], 2)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)

    def test_consumed_retry_recomputes_currentness_after_concurrent_retake(self):
        first_handle = self.start()
        first_status, first_saved, _ = self.commit_http(first_handle)
        self.assertEqual(first_status, 200)
        status_returned, resume = threading.Event(), threading.Event()
        outcome = {}
        original_status = CaptureService.status

        def pause_after_status(instance, cid, actor_id):
            result = original_status(instance, cid, actor_id)
            if cid == first_handle and actor_id == "volunteer-a" and not status_returned.is_set():
                status_returned.set()
                if not resume.wait(5):
                    raise AssertionError("synthetic recovery barrier timed out")
            return result

        def retry_first():
            outcome["response"] = self.commit_http(first_handle)

        with patch.object(CaptureService, "status", pause_after_status):
            retry = threading.Thread(target=retry_first, daemon=True)
            retry.start()
            try:
                self.assertTrue(status_returned.wait(5), "consumed retry never reached status barrier")
                second_handle = self.start("foreign", revision=1)
                second_status, second_saved, _ = self.commit_http(
                    second_handle, "foreign", revision=1, image_b64=self.later_image_b64)
                self.assertEqual(second_status, 200)
            finally:
                resume.set()
                retry.join(timeout=5)
        self.assertFalse(retry.is_alive())
        self.assertIn("response", outcome)
        retry_status, recovered, _ = outcome["response"]
        self.assertEqual(retry_status, 200)
        self.assertEqual(recovered["photo"], first_saved["photo"])
        self.assertEqual(recovered["arrival"]["current_photo"]["image_id"],
                         second_saved["photo"]["image_id"])
        self.assertIs(recovered["is_current"], False)
        self.assertEqual(self.store.detail(self.aid)["current_photo"]["image_id"],
                         second_saved["photo"]["image_id"])
        self.assertEqual(self.store.detail(self.aid)["revision"], 2)
        self.assertEqual(self.store.connection.execute(
            "SELECT count(*) FROM photo_captures WHERE arrival_id=?", (self.aid,)).fetchone()[0], 2)
        self.assertEqual(self.store.summary(self.sid)["confirmed_count"], 2)


if __name__ == "__main__":
    unittest.main()
