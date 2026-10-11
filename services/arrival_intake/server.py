"""Private, role-bound HTTP boundary for bus-arrival intake."""

import base64
import binascii
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .auth import Unauthorized, authenticate
from .contracts import Conflict, Forbidden, Missing, nonnegative_int
from .policy import authorize
from .store import IntakeStore


_ID = r"[A-Za-z0-9._-]{1,256}"
_INTAKE = re.compile(rf"/api/intakes/({_ID})(?:/(aggregate|arrivals|finish|corrections|reviews|history))?\Z")
_ARRIVAL = re.compile(rf"/api/arrivals/({_ID})(?:/(photo|assessment|concerns|observation|review-complete|capture-session))?\Z")
_CAPTURE_SESSION = re.compile(rf"/api/capture-sessions/({_ID})(?:/(preview|capture|close))?\Z")
_ASSETS = {"/": "index.html", "/index.html": "index.html",
           "/app.js": "app.js", "/camera.js": "camera.js",
           "/style.css": "style.css"}
_MIME = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
         "camera.js": "text/javascript; charset=utf-8",
         "style.css": "text/css; charset=utf-8"}
_CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob: mediastream:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'"
_MAX_JSON = 7 * 1024 * 1024  # accommodates a 5 MiB base64-encoded image
_MAX_IMAGE = 5 * 1024 * 1024


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _bad_constant(_):
    raise ValueError("nonfinite JSON number")


def _fields(value, required, optional=()):
    if type(value) is not dict or not set(required) <= set(value) or not set(value) <= set(required) | set(optional):
        raise ValueError("invalid request fields")
    return value


def _for_photo_store(template, store):
    if template is None:
        raise Unavailable("photo store unavailable")
    if callable(getattr(template, "for_store", None)):
        return template.for_store(store)
    # Task 4's declared constructor is PhotoStore(store).
    return type(template)(store)


def _for_workflow(template, store, photo_store):
    if template is None:
        raise Unavailable("workflow unavailable")
    if callable(getattr(template, "for_store", None)):
        return template.for_store(store, photo_store)
    # Task 5's declared constructor is Workflow(store, photo_store, assessor).
    return type(template)(store, photo_store, template.assessor)


def _for_capture(template, store, photo_store):
    if template is None:
        raise Unavailable("capture service unavailable")
    return template.for_store(store, photo_store)


class Unavailable(RuntimeError):
    """A Task 4/5 dependency has not been configured."""


def make_server(store, workflow, photo_store, token_registry, web_root,
                host="127.0.0.1", port=0, capture_service=None):
    """Build a loopback HTTP server; request handlers own their SQLite connections.

    Construct this in the same thread that created ``store``.  Only its database
    filename crosses into request threads; the original connection never does.
    """
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("intake server must bind to loopback")
    database_rows = store.connection.execute("PRAGMA database_list").fetchall()
    database_path = next((row[2] for row in database_rows if row[1] == "main"), "")
    if not database_path or database_path == ":memory:":
        raise ValueError("intake HTTP requires a file-backed database")
    asset_root = Path(web_root).resolve()
    if not asset_root.is_dir():
        raise ValueError("web_root must be an existing directory")
    if Path(database_path).resolve().is_relative_to(asset_root):
        raise ValueError("private database must be outside the static asset root")
    if workflow is not None:
        required = ("for_store", "list_reviews", "finish_intake", "request_assessment",
                    "record_concern", "record_observation", "complete_review")
        if any(not callable(getattr(workflow, name, None)) for name in required):
            raise ValueError("workflow does not implement the private route contract")

    class Handler(BaseHTTPRequestHandler):
        server_version = "ArrivalIntake"
        sys_version = ""

        def log_message(self, _format, *_args):
            # Never log private paths, request bodies or Authorization headers.
            pass

        def _headers(self, status, content_type, length, extra_headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", _CSP)
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Permissions-Policy", "camera=(self), microphone=()")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, str(value))
            self.end_headers()

        def _json(self, status, value):
            encoded = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(encoded))
            self.wfile.write(encoded)

        def _error(self, status, code):
            self._json(status, {"error": {"code": code}})

        def _read_json(self):
            if self.headers.get("Transfer-Encoding") is not None:
                raise ValueError("chunked request unsupported")
            if self.headers.get("Content-Type", "").lower() not in (
                    "application/json", "application/json; charset=utf-8"):
                raise ValueError("expected JSON media type")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or re.fullmatch(r"[0-9]+", lengths[0]) is None:
                raise ValueError("invalid Content-Length")
            length = int(lengths[0])
            if length < 1 or length > _MAX_JSON:
                raise ValueError("request too large")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete request")
            try:
                return json.loads(raw.decode("utf-8"), object_pairs_hook=_json_pairs,
                                  parse_constant=_bad_constant)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid JSON") from exc

        @contextmanager
        def _request_store(self):
            with IntakeStore(database_path) as request_store:
                yield request_store

        @staticmethod
        def _arrival_session(request_store, arrival_id, principal):
            # Restrict the lookup itself to assigned sessions. Both a missing ID
            # and an existing ID in another session therefore have the same 404.
            assigned = tuple(principal.session_ids)
            if not assigned:
                raise Missing(arrival_id)
            placeholders = ",".join("?" for _ in assigned)
            row = request_store.connection.execute(
                "SELECT session_id FROM arrivals WHERE arrival_id=? AND session_id IN (" + placeholders + ")",
                (arrival_id, *assigned)).fetchone()
            if row is None:
                raise Missing(arrival_id)
            return row["session_id"]

        def _bound_workflow(self, request_store):
            request_photo = None if photo_store is None else _for_photo_store(photo_store, request_store)
            return _for_workflow(workflow, request_store, request_photo)

        def _bound_photo(self, request_store):
            return _for_photo_store(photo_store, request_store)

        def _bound_capture(self, request_store):
            request_photo = self._bound_photo(request_store)
            bound = _for_capture(capture_service, request_store, request_photo)

            def check_assignment(sid, actor_id):
                current = authenticate(self.headers.get("Authorization"), token_registry)
                if current.actor_id != actor_id:
                    raise Forbidden("capture actor changed")
                authorize(current, "capture_session", sid)

            bound.assignment_check = check_assignment
            return bound

        @staticmethod
        def _decode_image(body, maximum=_MAX_IMAGE):
            encoded = body["image_base64"]
            if type(encoded) is not str or len(encoded) > (maximum * 4 // 3 + 8):
                raise ValueError("image exceeds encoded limit")
            try:
                image = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("invalid image encoding") from exc
            if not image or len(image) > maximum or body["media_type"] not in (
                    "image/jpeg", "image/png"):
                raise ValueError("invalid image")
            return image

        def _detail_with_display(self, request_store, aid):
            detail = request_store.detail(aid)
            if detail["current_photo"] is not None and photo_store is not None:
                lease = self._bound_photo(request_store).display_authorization(
                    aid, expected_capture_id=detail["current_photo"]["image_id"],
                    expected_digest=detail["current_photo"]["image_sha256"],
                    expected_revision=detail["current_photo"]["arrival_revision"])
                if lease is not None:
                    detail["display_authorization"] = lease
            return detail

        def _run(self, method):
            parsed = urlsplit(self.path)
            if parsed.query or parsed.fragment or parsed.scheme or parsed.netloc:
                raise ValueError("query strings are not accepted")
            path = parsed.path
            if method == "GET" and path in _ASSETS:
                name = _ASSETS[path]
                target = (asset_root / name).resolve()
                if target.parent != asset_root or not target.is_file():
                    raise Missing(name)
                data = target.read_bytes()
                self._headers(200, _MIME[name], len(data))
                self.wfile.write(data)
                return
            if not path.startswith("/api/"):
                raise Missing(path)
            principal = authenticate(self.headers.get("Authorization"), token_registry)
            if method == "GET" and path == "/api/me":
                self._json(200, {"actor_id": principal.actor_id, "role": principal.role,
                                 "session_ids": sorted(principal.session_ids)})
                return
            if method == "GET" and path == "/api/intakes":
                with self._request_store() as request_store:
                    intakes = []
                    for sid in sorted(principal.session_ids):
                        authorize(principal, "read_intake", sid)
                        try:
                            intakes.append(request_store.summary(sid))
                        except Missing:
                            continue
                    self._json(200, {"intakes": intakes})
                return
            intake = _INTAKE.fullmatch(path)
            if intake is not None:
                sid, suffix = intake.groups()
                self._intake(method, sid, suffix, principal)
                return
            arrival = _ARRIVAL.fullmatch(path)
            if arrival is not None:
                aid, suffix = arrival.groups()
                self._arrival(method, aid, suffix, principal)
                return
            capture = _CAPTURE_SESSION.fullmatch(path)
            if capture is not None:
                cid, suffix = capture.groups()
                self._capture(method, cid, suffix, principal)
                return
            raise Missing(path)

        def _intake(self, method, sid, suffix, principal):
            action = {
                ("GET", None): "read_intake",
                ("GET", "aggregate"): "read_aggregate",
                ("GET", "history"): "read_history",
                ("GET", "reviews"): "read_reviews",
                ("POST", "arrivals"): "confirm_arrival",
                ("POST", "finish"): "finish_intake",
                ("POST", "corrections"): "correct_attendance",
            }.get((method, suffix))
            if action is None:
                self._error(405, "method_not_allowed")
                return
            authorize(principal, action, sid)  # assignment precedes record lookup
            with self._request_store() as request_store:
                if method == "GET":
                    if suffix is None:
                        arrivals = []
                        for item in request_store.list_arrivals(sid)["arrivals"]:
                            if item["current_photo"] is not None and photo_store is not None:
                                try:
                                    item = self._detail_with_display(request_store, item["arrival_id"])
                                except (Forbidden, Missing):
                                    item = dict(item)
                                    for key in ("current_photo", "current_image_id",
                                                "current_image_sha256", "current_image_revision"):
                                        item[key] = None
                                    if item["assessment"] is not None:
                                        item["assessment"] = {key: value for key, value in
                                                              item["assessment"].items() if key not in
                                                              ("image_sha256", "capture_id", "capture_revision")}
                            arrivals.append(item)
                        self._json(200, {"session_summary": request_store.summary(sid),
                                         "arrivals": arrivals})
                    elif suffix == "aggregate":
                        summary = request_store.summary(sid)
                        keys = ("session_id", "case_id", "vehicle_id", "destination_node", "mode",
                                "expected_count", "confirmed_count", "difference", "intake_state",
                                "awaiting_reviews", "completed_reviews")
                        self._json(200, {key: summary[key] for key in keys})
                    elif suffix == "history":
                        request_store.summary(sid)
                        rows = request_store.connection.execute(
                            "SELECT event_id,arrival_id,actor_id,occurred_at,reason,before_json,after_json,correction_kind "
                            "FROM events WHERE session_id=? AND event_type='attendance_correction' "
                            "ORDER BY rowid", (sid,)).fetchall()
                        history = []
                        for row in rows:
                            before, after = json.loads(row["before_json"]), json.loads(row["after_json"])
                            kind = row["correction_kind"]
                            if kind == "attendance" or (kind is None and row["arrival_id"] is not None):
                                change, prior, later = "attendance", before["state"], after["state"]
                            elif kind == "expected_count" or (kind is None and
                                    before["expected_count"] != after["expected_count"]):
                                change, prior, later = ("expected_count", before["expected_count"],
                                                        after["expected_count"])
                            elif kind == "reopen" or (kind is None and
                                    before["intake_state"] != after["intake_state"]):
                                change, prior, later = ("reopen", before["intake_state"],
                                                        after["intake_state"])
                            else:
                                change = "unknown"
                                prior = {key: before[key] for key in ("expected_count", "intake_state")}
                                later = {key: after[key] for key in ("expected_count", "intake_state")}
                            history.append({"event_id": row["event_id"],
                                            "arrival_id": row["arrival_id"],
                                            "actor_id": row["actor_id"],
                                            "occurred_at": row["occurred_at"],
                                            "reason": row["reason"], "change": change,
                                            "before": prior, "after": later})
                        self._json(200, {"history": history})
                    else:
                        request_store.summary(sid)
                        bound = self._bound_workflow(request_store)
                        self._json(200, {"reviews": bound.list_reviews(sid)})
                    return
                # Check record existence only after authorization, before any mutation.
                request_store.summary(sid)
                if suffix == "arrivals":
                    body = _fields(self._read_json(), {"operation_key"})
                    self._json(200, request_store.confirm_arrival(sid, body["operation_key"],
                                                                  principal.actor_id))
                elif suffix == "finish":
                    body = _fields(self._read_json(), {"expected_revision"})
                    revision = nonnegative_int(body["expected_revision"], "expected_revision")
                    bound = self._bound_workflow(request_store)
                    self._json(200, {"session_summary": bound.finish_intake(
                        sid, revision, principal.actor_id)})
                else:
                    body = _fields(self._read_json(), {"expected_revision", "reason", "change"})
                    self._json(200, {"session_summary": request_store.correct(
                        sid, body["expected_revision"], principal.actor_id, body["reason"], body["change"])})

        def _arrival(self, method, aid, suffix, principal):
            action = {
                ("GET", None): "read_detail", ("GET", "photo"): "read_photo",
                ("POST", "photo"): "attach_photo", ("POST", "assessment"): "request_assessment",
                ("POST", "capture-session"): "capture_session",
                ("POST", "concerns"): "report_concern",
                ("POST", "observation"): "report_concern",
                ("POST", "review-complete"): "complete_review",
            }.get((method, suffix))
            if action is None:
                self._error(405, "method_not_allowed")
                return
            with self._request_store() as request_store:
                sid = self._arrival_session(request_store, aid, principal)
                authorize(principal, action, sid)
                if method == "GET" and suffix is None:
                    self._json(200, {"arrival": self._detail_with_display(request_store, aid)})
                    return
                if method == "GET" and suffix == "photo":
                    bound_photo = self._bound_photo(request_store)
                    image, media_type, lease = bound_photo.read_with_display_authorization(aid)
                    lease_headers = None if lease is None else {
                        "X-Display-Grant-Id": lease["grant_id"],
                        "X-Display-Grant-Version": lease["version"],
                        "X-Display-Expires-At": lease["expires_at"],
                        "X-Display-Lease-Ms": lease["lease_ms"],
                    }
                    self._headers(200, media_type, len(image), lease_headers)
                    self.wfile.write(image)
                    return
                if suffix == "capture-session":
                    body = _fields(self._read_json(), {"expected_revision"})
                    nonnegative_int(body["expected_revision"], "expected_revision")
                    self._json(200, self._bound_capture(request_store).start(
                        aid, principal.actor_id, body["expected_revision"]))
                    return
                if suffix == "photo":
                    body = _fields(self._read_json(),
                                   {"expected_revision", "image_base64", "media_type", "permission"})
                    image = self._decode_image(body)
                    bound_photo = _for_photo_store(photo_store, request_store)
                    self._json(200, {"photo": bound_photo.attach(
                        aid, principal.actor_id, body["expected_revision"], image,
                        body["media_type"], body["permission"])})
                    return
                body = self._read_json()
                if suffix == "assessment":
                    _fields(body, {"expected_revision", "mode"})
                    nonnegative_int(body["expected_revision"], "expected_revision")
                    if body["mode"] not in ("scripted", "real", "skipped"):
                        raise ValueError("invalid assessment mode")
                    bound = self._bound_workflow(request_store)
                    self._json(200, {"arrival": bound.request_assessment(
                        aid, body["expected_revision"], principal.actor_id, body["mode"])})
                elif suffix == "concerns":
                    _fields(body, {"expected_revision", "text"})
                    nonnegative_int(body["expected_revision"], "expected_revision")
                    bound = self._bound_workflow(request_store)
                    self._json(200, {"arrival": bound.record_concern(
                        aid, body["expected_revision"], principal.actor_id, body["text"])})
                elif suffix == "observation":
                    _fields(body, {"expected_revision", "concern", "text"})
                    nonnegative_int(body["expected_revision"], "expected_revision")
                    if type(body["concern"]) is not bool:
                        raise ValueError("concern must be a boolean")
                    bound = self._bound_workflow(request_store)
                    self._json(200, {"arrival": bound.record_observation(
                        aid, body["expected_revision"], principal.actor_id,
                        body["concern"], body["text"])})
                else:
                    _fields(body, {"expected_revision"})
                    nonnegative_int(body["expected_revision"], "expected_revision")
                    bound = self._bound_workflow(request_store)
                    self._json(200, {"arrival": bound.complete_review(
                        aid, body["expected_revision"], principal.actor_id)})

        def _capture(self, method, cid, suffix, principal):
            if (method, suffix) not in (("GET", None), ("POST", "preview"),
                                        ("POST", "capture"), ("POST", "close")):
                self._error(405, "method_not_allowed")
                return
            if principal.role != "volunteer":
                raise Forbidden("capture is volunteer-only")
            with self._request_store() as request_store:
                bound = self._bound_capture(request_store)
                row = bound._row(cid, principal.actor_id)
                sid = self._arrival_session(request_store, row["arrival_id"], principal)
                authorize(principal, "capture_session", sid)
                if method == "GET":
                    self._json(200, bound.status(cid, principal.actor_id))
                    return
                if suffix == "close":
                    _fields(self._read_json(), set())
                    self._json(200, bound.close(cid, principal.actor_id))
                    return
                if suffix == "preview":
                    body = _fields(self._read_json(), {"frame_id", "image_base64", "media_type"})
                    nonnegative_int(body["frame_id"], "frame_id")
                    image = self._decode_image(body, 512 * 1024)
                    result = bound.preview(cid, principal.actor_id, body["frame_id"],
                                           image, body["media_type"])
                    # Assignment can be withdrawn while an external runner works.
                    refreshed = authenticate(self.headers.get("Authorization"), token_registry)
                    authorize(refreshed, "capture_session", sid)
                    self._json(200, result)
                    return
                body = _fields(self._read_json(), {"expected_revision", "image_base64", "media_type"})
                nonnegative_int(body["expected_revision"], "expected_revision")
                image = self._decode_image(body)
                self._json(200, bound.commit(cid, principal.actor_id,
                                              body["expected_revision"], image, body["media_type"]))

        def _dispatch(self, method):
            try:
                self._run(method)
            except Unauthorized:
                self._error(401, "unauthorized")
            except Forbidden:
                self._error(403, "forbidden")
            except Missing:
                self._error(404, "not_found")
            except Conflict:
                self._error(409, "conflict")
            except Unavailable:
                self._error(503, "unavailable")
            except (ValueError, TypeError, OverflowError):
                self._error(400, "invalid_request")

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_PATCH(self):
            self._dispatch("PATCH")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return ThreadingHTTPServer((host, port), Handler)
