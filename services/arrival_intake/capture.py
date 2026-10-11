"""Default-denied, root-provisioned live capture sessions.

This module does not configure a detector or any participant grant. Browser
requests can use only the immutable root facts and current SQLite grant state.
"""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import re
from types import MappingProxyType
from uuid import uuid4
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .contracts import Conflict, Forbidden, Missing, bounded_text, canonical_json, nonnegative_int
from .photos import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS, PhotoStore
from .store import IntakeStore


PURPOSES = frozenset({"preview", "capture", "display", "assessment"})
PREVIEW_MAX_BYTES = 512 * 1024
PREVIEW_MAX_PIXELS = 2_000_000
MAX_PREVIEWS = 240
SESSION_SECONDS = 120
DISPLAY_LEASE_MS = 5000
_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG"}


def _aware(value, name):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be a timezone-aware timestamp") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    return value.astimezone(timezone.utc)


def normalize_frame(image_bytes, media_type, *, preview=False):
    """Decode once with hard input/pixel limits and strip all source metadata."""
    maximum = PREVIEW_MAX_BYTES if preview else MAX_IMAGE_BYTES
    pixels = PREVIEW_MAX_PIXELS if preview else MAX_IMAGE_PIXELS
    if type(image_bytes) is not bytes or not image_bytes or len(image_bytes) > maximum:
        raise ValueError("image exceeds encoded-byte limit")
    if type(media_type) is not str or media_type not in _FORMATS:
        raise ValueError("only static JPEG and PNG are accepted")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(image_bytes)) as source:
                width, height = source.size
                if (source.format != _FORMATS[media_type] or width < 1 or height < 1 or
                        width * height > pixels or getattr(source, "is_animated", False) or
                        getattr(source, "n_frames", 1) != 1):
                    raise ValueError("image format, dimensions or frame count are invalid")
                source.load()
                if source.size != (width, height):
                    raise ValueError("image dimensions changed during decoding")
                raster = ImageOps.exif_transpose(source).convert("RGB")
                if max(raster.size) > 1280:
                    raster.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
                # Pillow copies source.info (including ICC) through convert.
                # Serialize pixels from a fresh raster after EXIF orientation.
                clean = Image.new("RGB", raster.size)
                clean.paste(raster)
                output = BytesIO()
                clean.save(output, format="PNG")
                normalized = output.getvalue()
                return normalized, "image/png", clean.width, clean.height, sha256(normalized).hexdigest()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning,
            Image.DecompressionBombError) as exc:
        raise ValueError("invalid image raster") from exc


class CaptureAuthority:
    """Immutable root facts plus authoritative per-database status and version."""

    def __init__(self, authorization_registry, clock=None):
        if not hasattr(authorization_registry, "items"):
            raise ValueError("authorization registry must be a mapping")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        entries, by_id = {}, {}
        for key, raw in authorization_registry.items():
            if type(key) is not tuple or len(key) != 3 or not hasattr(raw, "keys"):
                raise ValueError("grant needs (exercise session, arrival, actor) and fields")
            sid, aid, actor = key
            for name, value in (("exercise_session_id", sid), ("arrival_id", aid), ("actor_id", actor)):
                bounded_text(value, name)
            required = {"grant_id", "consent_reference", "verified_by", "verified_at",
                        "expires_at", "purposes"}
            if set(raw) != required or type(raw["purposes"]) is not frozenset:
                raise ValueError("grant has missing or unexpected fields")
            grant_id = bounded_text(raw["grant_id"], "grant_id")
            if re.fullmatch(r"[A-Za-z0-9._-]{1,256}", grant_id) is None:
                raise ValueError("grant_id must be safe for private receipts")
            if grant_id in by_id:
                raise ValueError("grant IDs must be unique")
            bounded_text(raw["consent_reference"], "consent_reference")
            bounded_text(raw["verified_by"], "verified_by")
            if raw["verified_by"] == actor:
                raise ValueError("root verifier must differ from capture actor")
            verified = _aware(raw["verified_at"], "verified_at")
            expires = _aware(raw["expires_at"], "expires_at")
            if expires <= verified or not raw["purposes"] or not raw["purposes"] <= PURPOSES:
                raise ValueError("invalid grant expiry or purposes")
            facts = MappingProxyType({
                "grant_id": grant_id, "exercise_session_id": sid, "arrival_id": aid,
                "actor_id": actor, "consent_reference": raw["consent_reference"],
                "verified_by": raw["verified_by"], "verified_at": verified,
                "expires_at": expires, "purposes": frozenset(raw["purposes"]),
            })
            entries[key] = facts
            by_id[grant_id] = facts
        self.registry = MappingProxyType(entries)
        self.by_id = MappingProxyType(by_id)

    def _now(self):
        return _aware(self.clock(), "clock")

    @staticmethod
    def _fingerprint(facts):
        return sha256(canonical_json({
            "grant_id": facts["grant_id"], "exercise_session_id": facts["exercise_session_id"],
            "arrival_id": facts["arrival_id"], "actor_id": facts["actor_id"],
            "consent_reference": facts["consent_reference"], "verified_by": facts["verified_by"],
            "verified_at": facts["verified_at"].isoformat(),
            "expires_at": facts["expires_at"].isoformat(),
            "purposes": sorted(facts["purposes"]),
        }).encode("utf-8")).hexdigest()

    def provision_grants(self, store):
        if not isinstance(store, IntakeStore):
            raise TypeError("root provisioning requires IntakeStore")
        blocked = []
        with store.connection:
            store.connection.execute("BEGIN IMMEDIATE")
            # Treat this registry as the complete root configuration. Removed
            # or changed facts retire the old IDs before any new grant is used.
            for row in store.connection.execute(
                    "SELECT grant_id,facts_sha256 FROM capture_grants WHERE status='active'").fetchall():
                configured = self.by_id.get(row["grant_id"])
                if configured is None or row["facts_sha256"] != self._fingerprint(configured):
                    store.connection.execute(
                        "UPDATE capture_grants SET status='revoked',version=version+1,"
                        "facts_sha256=NULL,exercise_session_id=NULL WHERE grant_id=?",
                        (row["grant_id"],))
            for facts in self.by_id.values():
                row = store.connection.execute(
                    "SELECT status,version,facts_sha256 FROM capture_grants WHERE grant_id=?",
                    (facts["grant_id"],)).fetchone()
                fingerprint = self._fingerprint(facts)
                if row is None:
                    store.connection.execute(
                        "INSERT INTO capture_grants(grant_id,status,version,facts_sha256,exercise_session_id) "
                        "VALUES (?,'active',1,?,?)",
                        (facts["grant_id"], fingerprint, facts["exercise_session_id"]))
                elif row["status"] != "active":
                    blocked.append(facts["grant_id"])
                elif row["facts_sha256"] != fingerprint:
                    blocked.append(facts["grant_id"])
        if blocked:
            raise Forbidden("a revoked or changed grant ID cannot be provisioned again")

    def revoke_grant(self, store, grant_id, expected_version, root_actor_id):
        if not isinstance(store, IntakeStore):
            raise TypeError("root revocation requires IntakeStore")
        bounded_text(grant_id, "grant_id")
        bounded_text(root_actor_id, "root_actor_id")
        nonnegative_int(expected_version, "expected_version")
        with store.connection:
            store.connection.execute("BEGIN IMMEDIATE")
            row = store.connection.execute(
                "SELECT status,version FROM capture_grants WHERE grant_id=?", (grant_id,)).fetchone()
            if row is None:
                raise Missing(grant_id)
            if row["version"] != expected_version or row["status"] != "active":
                raise Conflict("grant state changed")
            store.connection.execute(
                "UPDATE capture_grants SET status='revoked',version=version+1,"
                "facts_sha256=NULL,exercise_session_id=NULL "
                "WHERE grant_id=?", (grant_id,))
            return {"grant_id": grant_id, "status": "revoked", "version": expected_version + 1}

    def check(self, store, exercise_session_id, arrival_id, actor_id, purpose,
              *, grant_id=None, grant_version=None):
        facts = self.registry.get((exercise_session_id, arrival_id, actor_id))
        if (facts is None or purpose not in facts["purposes"] or
                (grant_id is not None and facts["grant_id"] != grant_id)):
            raise Forbidden("capture purpose is not root-authorized")
        now = self._now()
        if now < facts["verified_at"] or now >= facts["expires_at"]:
            raise Forbidden("capture grant is outside its permitted time")
        row = store.connection.execute(
            "SELECT status,version,facts_sha256 FROM capture_grants WHERE grant_id=?",
            (facts["grant_id"],)).fetchone()
        if (row is None or row["status"] != "active" or
                row["facts_sha256"] != self._fingerprint(facts) or
                (grant_version is not None and row["version"] != grant_version)):
            raise Forbidden("capture grant is not active")
        return facts, row["version"]

    def check_photo(self, store, permission, purpose):
        if purpose not in ("display", "assessment"):
            raise Forbidden("unsupported photo purpose")
        allowed_key = "display_allowed" if purpose == "display" else "processing_allowed"
        if permission.get(allowed_key) is not True:
            raise Forbidden("stored permission does not allow this purpose")
        return self.check(store, permission["exercise_session_id"], permission["arrival_id"],
                          permission["capture_actor_id"], purpose,
                          grant_id=permission["grant_id"], grant_version=permission["grant_version"])

    def display_authorization(self, store, permission):
        facts, version = self.check_photo(store, permission, "display")
        remaining = int((facts["expires_at"] - self._now()).total_seconds() * 1000)
        if remaining <= 0:
            raise Forbidden("display grant expired")
        return {"grant_id": facts["grant_id"], "version": version,
                "expires_at": facts["expires_at"].isoformat(),
                "lease_ms": min(DISPLAY_LEASE_MS, remaining)}


class CaptureService:
    def __init__(self, store, photo_store, authority, preview_runner=None):
        if not isinstance(store, IntakeStore) or not isinstance(photo_store, PhotoStore):
            raise TypeError("capture needs IntakeStore and PhotoStore")
        if not isinstance(authority, CaptureAuthority):
            raise TypeError("capture needs root CaptureAuthority")
        self.store, self.photo_store, self.authority = store, photo_store, authority
        if self.photo_store.capture_authority is None:
            self.photo_store.capture_authority = authority
        self.preview_runner = preview_runner
        self.assignment_check = None  # trusted request binding, never HTTP body data

    def for_store(self, request_store, request_photo_store):
        return type(self)(request_store, request_photo_store, self.authority, self.preview_runner)

    def _row(self, handle, actor_id):
        bounded_text(handle, "capture_session_id")
        bounded_text(actor_id, "actor_id")
        row = self.store.connection.execute(
            "SELECT * FROM capture_sessions WHERE capture_session_id=? AND actor_id=?",
            (handle, actor_id)).fetchone()
        if row is None:
            raise Missing(handle)
        return row

    def _current(self, row, purpose, *, require_active=True):
        if self.assignment_check is not None:
            self.assignment_check(row["exercise_session_id"], row["actor_id"])
        arrival = self.store._arrival_row(row["arrival_id"])
        if arrival["session_id"] != row["exercise_session_id"]:
            raise Conflict("capture arrival changed")
        if arrival["state"] != "confirmed" or not arrival["confirmed_by"] or not arrival["confirmed_at"]:
            raise Conflict("arrival is not currently counted")
        if require_active and (row["state"] != "active" or
                arrival["revision"] != row["arrival_revision"]):
            raise Conflict("capture session or arrival revision changed")
        self.authority.check(self.store, row["exercise_session_id"], row["arrival_id"],
                             row["actor_id"], purpose, grant_id=row["grant_id"],
                             grant_version=row["grant_version"])
        if require_active and self.authority._now() >= _aware(row["expires_at"], "expires_at"):
            raise Forbidden("capture session expired")
        return arrival

    def start(self, arrival_id, actor_id, expected_revision):
        bounded_text(arrival_id, "arrival_id")
        bounded_text(actor_id, "actor_id")
        nonnegative_int(expected_revision, "expected_revision")
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            arrival = self.store._arrival_row(arrival_id)
            if self.assignment_check is not None:
                self.assignment_check(arrival["session_id"], actor_id)
            if arrival["revision"] != expected_revision or arrival["state"] != "confirmed" or not (
                    arrival["confirmed_by"] and arrival["confirmed_at"]):
                raise Conflict("arrival is stale or not counted")
            facts, version = self.authority.check(self.store, arrival["session_id"], arrival_id,
                                                  actor_id, "capture")
            expires = min(self.authority._now() + timedelta(seconds=SESSION_SECONDS),
                          facts["expires_at"])
            handle = str(uuid4())
            self.store.connection.execute(
                "INSERT INTO capture_sessions(capture_session_id,exercise_session_id,arrival_id,"
                "actor_id,grant_id,grant_version,arrival_revision,expires_at,state) "
                "VALUES (?,?,?,?,?,?,?,?,'active')",
                (handle, arrival["session_id"], arrival_id, actor_id, facts["grant_id"],
                 version, expected_revision, expires.isoformat()))
            return {"capture_session_id": handle, "expires_at": expires.isoformat(),
                    "arrival_revision": expected_revision, "purposes": sorted(facts["purposes"])}

    def status(self, capture_session_id, actor_id):
        row = self._row(capture_session_id, actor_id)
        result = {"capture_session_id": capture_session_id, "state": row["state"],
                  "is_current": False}
        if row["state"] == "consumed":
            saved = json.loads(row["receipt_json"])
            arrival = self.store._arrival_row(row["arrival_id"])
            capture = self.store.connection.execute(
                "SELECT permission_json FROM photo_captures WHERE capture_id=? AND arrival_id=?",
                (saved["photo"]["image_id"], row["arrival_id"])).fetchone()
            if capture is None:
                raise Missing(capture_session_id)
            self.authority.check_photo(self.store, json.loads(capture["permission_json"]), "display")
            result.update(saved)
            result["is_current"] = arrival["current_image_id"] == saved["photo"]["image_id"]
        return result

    def _recovered_commit(self, capture_session_id, actor_id):
        recovered = self.status(capture_session_id, actor_id)
        current_arrival = self.store.detail(self._row(capture_session_id, actor_id)["arrival_id"])
        return {"photo": recovered["photo"], "arrival": current_arrival,
                "is_current": current_arrival["current_image_id"] == recovered["photo"]["image_id"]}

    def preview(self, capture_session_id, actor_id, frame_id, image_bytes, media_type):
        nonnegative_int(frame_id, "frame_id")
        if frame_id == 0:
            raise ValueError("frame_id must be positive")
        row = self._row(capture_session_id, actor_id)
        self._current(row, "preview")
        normalized, normalized_type, width, height, digest = normalize_frame(
            image_bytes, media_type, preview=True)
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            row = self._row(capture_session_id, actor_id)
            self._current(row, "preview")
            if frame_id <= row["last_frame_id"] or row["preview_count"] >= MAX_PREVIEWS:
                raise Conflict("preview frame is stale or session limit reached")
            self.store.connection.execute(
                "UPDATE capture_sessions SET last_frame_id=?,preview_count=preview_count+1 "
                "WHERE capture_session_id=?", (frame_id, capture_session_id))
        result = {"capture_session_id": capture_session_id, "frame_id": frame_id,
                  "image_sha256": digest, "width": width, "height": height,
                  "status": "unavailable", "boxes": [], "landmarks": [],
                  "detector_revision": None}
        if self.preview_runner is not None:
            runner = getattr(self.preview_runner, "detect", self.preview_runner)
            try:
                runner(normalized, frame_id=frame_id, capture_session_id=capture_session_id)
            except Exception:
                # Task 3 binds a reviewed detector/output adapter. Until then
                # controlled runner calls are authority-race probes only.
                pass
        row = self._row(capture_session_id, actor_id)
        self._current(row, "preview")
        if row["last_frame_id"] != frame_id:
            raise Conflict("preview response belongs to an obsolete frame")
        return result

    def commit(self, capture_session_id, actor_id, expected_revision, image_bytes, media_type):
        nonnegative_int(expected_revision, "expected_revision")
        row = self._row(capture_session_id, actor_id)
        if row["state"] == "active":
            self._current(row, "capture")
        input_digest = sha256(image_bytes).hexdigest() if type(image_bytes) is bytes else None
        normalized, normalized_type, _, _, digest = normalize_frame(image_bytes, media_type)
        if row["state"] == "consumed":
            if (digest != row["committed_digest"] or input_digest != row["committed_input_digest"] or
                    expected_revision != row["arrival_revision"]):
                raise Conflict("capture handle already belongs to a different selected frame")
            return self._recovered_commit(capture_session_id, actor_id)
        if expected_revision != row["arrival_revision"]:
            raise Conflict("capture uses stale arrival revision")
        self._current(row, "capture")
        facts, version = self.authority.check(self.store, row["exercise_session_id"],
                                               row["arrival_id"], actor_id, "capture",
                                               grant_id=row["grant_id"],
                                               grant_version=row["grant_version"])
        permission = {
            "source_kind": "adult_staged", "source_reference": facts["grant_id"],
            "capture_allowed": True, "display_allowed": "display" in facts["purposes"],
            "processing_allowed": "assessment" in facts["purposes"],
            "verified_by": facts["verified_by"], "verified_at": facts["verified_at"].isoformat(),
            "consent_reference": facts["consent_reference"], "grant_id": facts["grant_id"],
            "grant_version": version, "exercise_session_id": row["exercise_session_id"],
            "arrival_id": row["arrival_id"], "capture_actor_id": actor_id,
        }

        def authorize_attach(connection, arrival, actual_digest, *, phase, photo=None):
            current = self._row(capture_session_id, actor_id)
            if phase == "before":
                self._current(current, "capture")
                if actual_digest != digest or arrival["revision"] != expected_revision:
                    raise Conflict("selected image changed")
            if phase == "after":
                if current["state"] != "active" or actual_digest != digest:
                    raise Conflict("capture session changed during selected attach")
                if self.assignment_check is not None:
                    self.assignment_check(row["exercise_session_id"], actor_id)
                self.authority.check(self.store, row["exercise_session_id"], row["arrival_id"],
                                     actor_id, "capture", grant_id=row["grant_id"],
                                     grant_version=row["grant_version"])
                receipt = {"photo": photo, "arrival": self.store.detail(row["arrival_id"])}
                connection.execute(
                    "UPDATE capture_sessions SET state='consumed',committed_digest=?,"
                    "committed_input_digest=?,receipt_json=? "
                    "WHERE capture_session_id=? AND state='active'",
                    (digest, input_digest, canonical_json(receipt), capture_session_id))

        try:
            self.photo_store.attach(row["arrival_id"], actor_id, expected_revision,
                                    normalized, normalized_type, permission,
                                    authorization_callback=authorize_attach)
        except Conflict:
            current = self._row(capture_session_id, actor_id)
            if (current["state"] == "consumed" and current["committed_digest"] == digest and
                    current["committed_input_digest"] == input_digest and
                    current["arrival_revision"] == expected_revision):
                return self._recovered_commit(capture_session_id, actor_id)
            raise
        saved = json.loads(self._row(capture_session_id, actor_id)["receipt_json"])
        current_arrival = self.store.detail(row["arrival_id"])
        return {"photo": saved["photo"], "arrival": current_arrival,
                "is_current": current_arrival["current_image_id"] == saved["photo"]["image_id"]}

    def close(self, capture_session_id, actor_id):
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            row = self._row(capture_session_id, actor_id)
            if row["state"] == "active":
                self.store.connection.execute(
                    "UPDATE capture_sessions SET state='closed' WHERE capture_session_id=?",
                    (capture_session_id,))
                return {"capture_session_id": capture_session_id, "state": "closed"}
            return {"capture_session_id": capture_session_id, "state": row["state"]}
