"""Private SQLite-backed intake photos with revision-specific capture evidence."""

from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import sqlite3
from types import MappingProxyType
from uuid import uuid4
import warnings

from PIL import Image, UnidentifiedImageError

from .contracts import Conflict, Missing, bounded_text, canonical_json, nonnegative_int, sha256_text
from .store import IntakeStore


MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG"}
_PERMISSION_BASE = frozenset({
    "source_kind", "source_reference", "capture_allowed", "display_allowed",
    "processing_allowed", "verified_by", "verified_at",
})
_SOURCE_KINDS = frozenset({"operator_created_illustration", "adult_staged"})
_GRANT_BASE = frozenset({
    "source_kind", "image_sha256s", "capture_allowed", "display_allowed",
    "processing_allowed",
})
_IMAGE_EVENT_KEYS = frozenset({
    "image_id", "image_sha256", "current_image_id", "current_image_sha256",
    "current_image_revision", "capture_id", "capture_revision",
    "capture_session_id", "committed_digest", "committed_input_digest",
    "grant_id", "grant_version",
    "display_authorization", "receipt_json",
})


def _without_image_identifiers(value):
    if isinstance(value, dict):
        return {key: _without_image_identifiers(item) for key, item in value.items()
                if key not in _IMAGE_EVENT_KEYS}
    if isinstance(value, list):
        return [_without_image_identifiers(item) for item in value]
    return value


def _permission_json(permission, actor_id):
    if type(permission) is not dict:
        raise ValueError("verified permission evidence is required")
    expected = _PERMISSION_BASE | ({"consent_reference"} if permission.get("source_kind") == "adult_staged" else set())
    if set(permission) != expected:
        raise ValueError("permission evidence has missing or unexpected fields")
    if type(permission["source_kind"]) is not str or permission["source_kind"] not in _SOURCE_KINDS:
        raise ValueError("unsupported image source")
    bounded_text(permission["source_reference"], "source_reference")
    for name in ("capture_allowed", "display_allowed", "processing_allowed"):
        if permission[name] is not True:
            raise ValueError("capture, display and processing permission must be verified")
    bounded_text(permission["verified_by"], "verified_by")
    if permission["verified_by"] != actor_id:
        raise ValueError("permission verifier must be the authenticated actor")
    bounded_text(permission["verified_at"], "verified_at")
    try:
        verified_at = datetime.fromisoformat(permission["verified_at"])
    except ValueError as exc:
        raise ValueError("verified_at must be an ISO timestamp") from exc
    if verified_at.tzinfo is None or verified_at.utcoffset() is None:
        raise ValueError("verified_at must include a timezone")
    if permission["source_kind"] == "adult_staged":
        bounded_text(permission["consent_reference"], "consent_reference")
    return canonical_json(permission)


def _validated_image(image_bytes, media_type):
    if type(image_bytes) is not bytes or not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("image must contain at most 5 MiB encoded bytes")
    if type(media_type) is not str or media_type not in _FORMATS:
        raise ValueError("only static JPEG and PNG are accepted")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(image_bytes)) as image:
                width, height = image.size
                if (image.format != _FORMATS[media_type] or width < 1 or height < 1 or
                        width * height > MAX_IMAGE_PIXELS or
                        getattr(image, "is_animated", False) or
                        getattr(image, "n_frames", 1) != 1):
                    raise ValueError("image format, frame count or dimensions are invalid")
                image.load()
                if image.size != (width, height):
                    raise ValueError("image dimensions changed during decoding")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning,
            Image.DecompressionBombError) as exc:
        raise ValueError("invalid image raster") from exc
    return sha256(image_bytes).hexdigest()


class PhotoStore:
    def __init__(self, store, permission_registry=None, capture_authority=None):
        if not isinstance(store, IntakeStore):
            raise TypeError("PhotoStore requires an IntakeStore")
        self.store = store
        self.capture_authority = capture_authority
        # Copy root-supplied grants into immutable values, so later mutation
        # of the caller's dictionary cannot silently change capture rights.
        if permission_registry is None:
            permission_registry = {}
        if not hasattr(permission_registry, "items"):
            raise ValueError("permission registry must map source references to grants")
        grants = {}
        for source_reference, grant in permission_registry.items():
            bounded_text(source_reference, "source_reference")
            if not hasattr(grant, "keys"):
                raise ValueError("source grant must be a mapping")
            source_kind = grant.get("source_kind")
            if type(source_kind) is not str or source_kind not in _SOURCE_KINDS:
                raise ValueError("unsupported root-verified source kind")
            keys = _GRANT_BASE | ({"consent_reference"} if source_kind == "adult_staged" else set())
            if set(grant) != keys:
                raise ValueError("source grant has missing or unexpected fields")
            hashes = grant["image_sha256s"]
            if type(hashes) is not frozenset or not hashes:
                raise ValueError("source grant must list permitted image digests")
            for digest in hashes:
                sha256_text(digest, "permitted image digest")
            for name in ("capture_allowed", "display_allowed", "processing_allowed"):
                if grant[name] is not True:
                    raise ValueError("source grant must explicitly allow capture, display and processing")
            if source_kind == "adult_staged":
                bounded_text(grant["consent_reference"], "root consent_reference")
            grants[source_reference] = MappingProxyType(dict(grant))
        self.permission_registry = MappingProxyType(grants)

    def for_store(self, request_store):
        """Bind only the request-owned connection; retain no original handle."""
        return type(self)(request_store, self.permission_registry, self.capture_authority)

    def _trusted_grant(self, permission, digest):
        grant = self.permission_registry.get(permission["source_reference"])
        if (grant is None or grant["source_kind"] != permission["source_kind"] or
                digest not in grant["image_sha256s"]):
            raise ValueError("source and exact image are not root-authorized")
        if (permission["source_kind"] == "adult_staged" and
                permission["consent_reference"] != grant["consent_reference"]):
            raise ValueError("adult consent reference is not root-verified")

    def attach(self, arrival_id, actor_id, expected_revision, image_bytes,
               media_type, permission, authorization_callback=None):
        bounded_text(arrival_id, "arrival_id")
        bounded_text(actor_id, "actor_id")
        nonnegative_int(expected_revision, "expected_revision")
        if authorization_callback is None:
            evidence = _permission_json(permission, actor_id)
        else:
            if not callable(authorization_callback) or type(permission) is not dict:
                raise ValueError("trusted live authorization callback and permission required")
            live_keys = _PERMISSION_BASE | {"consent_reference", "grant_id", "grant_version",
                                             "exercise_session_id", "arrival_id", "capture_actor_id"}
            if set(permission) != live_keys or permission.get("source_kind") != "adult_staged":
                raise ValueError("invalid trusted live permission")
            for name in ("source_reference", "verified_by", "verified_at", "consent_reference",
                         "grant_id", "exercise_session_id", "arrival_id", "capture_actor_id"):
                bounded_text(permission[name], name)
            nonnegative_int(permission["grant_version"], "grant_version")
            if permission["capture_actor_id"] != actor_id or permission["arrival_id"] != arrival_id:
                raise ValueError("trusted live permission binding differs")
            if permission["capture_allowed"] is not True or any(
                    type(permission[name]) is not bool for name in
                    ("display_allowed", "processing_allowed")):
                raise ValueError("trusted live permission must declare exact uses")
            evidence = canonical_json(permission)
        digest = _validated_image(image_bytes, media_type)
        if authorization_callback is None:
            self._trusted_grant(permission, digest)
        connection = self.store.connection
        connection.execute("PRAGMA secure_delete=ON")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            arrival = self.store._arrival_row(arrival_id)
            if arrival["revision"] != expected_revision:
                raise Conflict("arrival changed; reload before attaching photo")
            if arrival["state"] != "confirmed":
                raise Conflict("only a confirmed arrival can receive a photo")
            if authorization_callback is not None:
                authorization_callback(connection, arrival, digest, phase="before")
            image = connection.execute(
                "SELECT image_id,private_bytes FROM images WHERE arrival_id=? AND image_sha256=?",
                (arrival_id, digest)).fetchone()
            now = self.store._now()
            if image is None:
                image_id = str(uuid4())
                connection.execute(
                    "INSERT INTO images(image_id,arrival_id,image_sha256,private_bytes,"
                    "permitted_use_json,created_at) VALUES (?,?,?,?,?,?)",
                    (image_id, arrival_id, digest, sqlite3.Binary(image_bytes), evidence, now))
            else:
                image_id = image["image_id"]
                if image["private_bytes"] is None:
                    connection.execute(
                        "UPDATE images SET private_bytes=?,permitted_use_json=?,deleted_at=NULL,"
                        "created_at=? WHERE image_id=?",
                        (sqlite3.Binary(image_bytes), evidence, now, image_id))
            capture_id = str(uuid4())
            revision = expected_revision + 1
            connection.execute(
                "INSERT INTO photo_captures(capture_id,arrival_id,image_id,arrival_revision,"
                "media_type,permission_json,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (capture_id, arrival_id, image_id, revision, media_type, evidence, actor_id, now))
            connection.execute(
                "UPDATE arrivals SET current_image_id=?,current_image_sha256=?,"
                "current_image_revision=?,revision=? WHERE arrival_id=?",
                (capture_id, digest, revision, revision, arrival_id))
            receipt = {"image_id": capture_id, "image_sha256": digest,
                       "media_type": media_type, "arrival_revision": revision}
            if authorization_callback is not None:
                authorization_callback(connection, arrival, digest, phase="after", photo=receipt)
            return receipt

    def _current_image(self, arrival_id, purpose):
        arrival = self.store._arrival_row(arrival_id)
        if arrival["current_image_id"] is None:
            raise Missing(arrival_id)
        binding = (arrival["current_image_id"], arrival["current_image_sha256"],
                   arrival["current_image_revision"])
        image = self.store.connection.execute(
            "SELECT i.private_bytes,c.media_type,c.permission_json FROM photo_captures c "
            "JOIN images i ON i.image_id=c.image_id "
            "WHERE c.capture_id=? AND c.arrival_id=? AND c.arrival_revision=? "
            "AND i.image_sha256=? AND i.deleted_at IS NULL",
            (arrival["current_image_id"], arrival_id, arrival["current_image_revision"],
             arrival["current_image_sha256"])).fetchone()
        if image is None or image["private_bytes"] is None:
            raise Missing(arrival_id)
        permission = json.loads(image["permission_json"])
        if "grant_id" in permission:
            if self.capture_authority is None:
                raise Missing(arrival_id)
            self.capture_authority.check_photo(self.store, permission, purpose)
        return image, permission, binding

    def _assert_current_binding(self, arrival_id, binding):
        arrival = self.store._arrival_row(arrival_id)
        if (arrival["current_image_id"], arrival["current_image_sha256"],
                arrival["current_image_revision"]) != binding:
            raise Conflict("current capture changed while private media was read")

    def display_authorization(self, arrival_id, *, expected_capture_id=None,
                              expected_digest=None, expected_revision=None):
        _, permission, binding = self._current_image(arrival_id, "display")
        if expected_capture_id is not None and binding != (
                expected_capture_id, expected_digest, expected_revision):
            raise Conflict("detail capture changed before display authorization")
        if "grant_id" not in permission:
            self._assert_current_binding(arrival_id, binding)
            return None
        lease = self.capture_authority.display_authorization(self.store, permission)
        self._assert_current_binding(arrival_id, binding)
        return lease

    def read_with_display_authorization(self, arrival_id):
        """Return bytes and lease derived from one exact capture permission."""
        image, permission, binding = self._current_image(arrival_id, "display")
        lease = (self.capture_authority.display_authorization(self.store, permission)
                 if "grant_id" in permission else None)
        self._assert_current_binding(arrival_id, binding)
        return bytes(image["private_bytes"]), image["media_type"], lease

    def read(self, arrival_id, purpose="display"):
        if purpose not in ("display", "assessment"):
            raise ValueError("unsupported private photo purpose")
        image, _, _ = self._current_image(arrival_id, purpose)
        return bytes(image["private_bytes"]), image["media_type"]

    def record_artifact(self, session_id, absolute_path):
        """Record an owned demo copy so cleanup can remove it explicitly."""
        self.store._session_row(session_id)
        path = self._owned_media_path(absolute_path)
        if not path.is_file():
            raise ValueError("image artifact must be an existing file")
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO photo_artifacts(artifact_id,session_id,absolute_path,recorded_at) "
                "VALUES (?,?,?,?)",
                (str(uuid4()), session_id, str(path), self.store._now()))

    def _owned_media_path(self, path):
        path = Path(path)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("artifact path must be an absolute owned regular file")
        resolved = path.resolve()
        private_root = (self.store.database_path.parent / "private_media").resolve()
        if resolved == private_root or private_root not in resolved.parents:
            raise ValueError("artifact path escapes private media directory")
        return resolved

    @staticmethod
    def _checkpoint(connection):
        try:
            row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.Error as exc:
            raise Conflict("private image WAL checkpoint failed") from exc
        if row is None or row[0] != 0:
            raise Conflict("private image WAL checkpoint is busy")

    def cleanup(self, session_id, actor_id):
        """Remove all session image data in a quiescent owned intake process.

        The caller stops the intake service first. The registry blocks new
        in-process owned connections while the writer transaction, checkpoints
        and VACUUM run. External readers are detected by the checkpoint.
        """
        bounded_text(session_id, "session_id")
        bounded_text(actor_id, "actor_id")
        with IntakeStore._registry_lock:
            if not IntakeStore._sole_owned_connection(self.store):
                raise Conflict("close other owned intake connections before cleanup")
            self.store._session_row(session_id)
            connection = self.store.connection
            connection.execute("PRAGMA secure_delete=ON")
            self._checkpoint(connection)
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                removed = connection.execute(
                    "SELECT count(*) FROM images i JOIN arrivals a ON a.arrival_id=i.arrival_id "
                    "WHERE a.session_id=? AND i.private_bytes IS NOT NULL", (session_id,)).fetchone()[0]
                now = self.store._now()
                # Retain only non-reusable grant tombstones after deleting every
                # session/receipt and grant-to-arrival linkage for this exercise.
                connection.execute(
                    "UPDATE capture_grants SET status='revoked',version=version+1,"
                    "facts_sha256=NULL,exercise_session_id=NULL "
                    "WHERE status='active' AND exercise_session_id=?", (session_id,))
                connection.execute(
                    "UPDATE capture_grants SET facts_sha256=NULL,exercise_session_id=NULL "
                    "WHERE status='revoked' AND exercise_session_id=?", (session_id,))
                connection.execute(
                    "DELETE FROM capture_sessions WHERE exercise_session_id=?", (session_id,))
                connection.execute(
                    "UPDATE images SET private_bytes=NULL,deleted_at=? WHERE arrival_id IN "
                    "(SELECT arrival_id FROM arrivals WHERE session_id=?) AND private_bytes IS NOT NULL",
                    (now, session_id))
                # Keep review/result labels while removing image identifiers and
                # all evidence objects associated with the deleted image.
                connection.execute(
                    "UPDATE assessments SET image_sha256=NULL,capture_id=NULL,capture_revision=NULL "
                    "WHERE arrival_id IN "
                    "(SELECT arrival_id FROM arrivals WHERE session_id=?)", (session_id,))
                connection.execute(
                    "UPDATE arrivals SET current_image_id=NULL,current_image_sha256=NULL,"
                    "current_image_revision=NULL,revision=revision+1 WHERE session_id=? "
                    "AND current_image_id IS NOT NULL", (session_id,))
                # Corrections and assessment events retain non-image history,
                # but their JSON snapshots must not outlive deleted captures.
                events = connection.execute(
                    "SELECT event_id,before_json,after_json FROM events WHERE session_id=?",
                    (session_id,)).fetchall()
                for event in events:
                    before = canonical_json(_without_image_identifiers(json.loads(event["before_json"])))
                    after = canonical_json(_without_image_identifiers(json.loads(event["after_json"])))
                    if before != event["before_json"] or after != event["after_json"]:
                        connection.execute(
                            "UPDATE events SET before_json=?,after_json=? WHERE event_id=?",
                            (before, after, event["event_id"]))
                connection.execute(
                    "DELETE FROM photo_captures WHERE arrival_id IN "
                    "(SELECT arrival_id FROM arrivals WHERE session_id=?)", (session_id,))
                connection.execute(
                    "DELETE FROM images WHERE arrival_id IN "
                    "(SELECT arrival_id FROM arrivals WHERE session_id=?)", (session_id,))
            self._checkpoint(connection)
            try:
                connection.execute("VACUUM")
            except sqlite3.Error as exc:
                raise Conflict("private image database compaction failed") from exc
            self._checkpoint(connection)
            artifacts = connection.execute(
                "SELECT artifact_id,absolute_path FROM photo_artifacts WHERE session_id=? "
                "AND deleted_at IS NULL", (session_id,)).fetchall()
            for artifact in artifacts:
                try:
                    path = self._owned_media_path(artifact["absolute_path"])
                    if path.exists():
                        if not path.is_file():
                            raise ValueError("owned artifact is not a file")
                        path.unlink()
                except (OSError, ValueError) as exc:
                    raise Conflict("an owned image artifact could not be removed") from exc
                with connection:
                    connection.execute("DELETE FROM photo_artifacts WHERE artifact_id=?",
                                       (artifact["artifact_id"],))
            self._checkpoint(connection)
            for suffix in ("-wal", "-journal"):
                artifact = Path(str(self.store.database_path) + suffix)
                if artifact.exists() and artifact.stat().st_size != 0:
                    raise Conflict("private image journal still contains data")
            if connection.execute(
                    "SELECT 1 FROM images i JOIN arrivals a ON a.arrival_id=i.arrival_id "
                    "WHERE a.session_id=? AND i.private_bytes IS NOT NULL LIMIT 1",
                    (session_id,)).fetchone() is not None:
                raise Conflict("private image deletion is incomplete")
            return {"removed_images": removed}
