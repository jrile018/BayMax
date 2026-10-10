"""Trusted, bounded persistence of incident cutoff snapshots and projection inputs.

This module consumes an application-owned EvidenceLog. A matching hash proves
integrity of that log's snapshot; it does not authenticate an external source.
No source parsing, dispatch, model execution, or outcome calculation occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from contracts.incident import EvidenceLog, VERSION, projection_input


PUBLICATION_VERSION = "knight26-snapshot-publication-v1"
MAX_METADATA_BYTES = 1_048_576
MAX_OPTION_BYTES = 65_536
MAX_PUBLICATION_BYTES = 16_777_216
UTC_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _copy(value, limit):
    try:
        encoded = _canonical(value)
        if len(encoded) > limit:
            raise ValueError("JSON input exceeds byte limit")
        return json.loads(encoded)
    except (TypeError, OverflowError, ValueError, RecursionError) as exc:
        raise ValueError("input must be bounded finite JSON") from exc


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utc(value, label):
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise ValueError(f"{label} must be a UTC Z timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be a real UTC timestamp") from exc


def _check_nested_as_of(value, cutoff, depth=0):
    if depth > 32:
        raise ValueError("metadata nesting exceeds limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "as_of_utc" and _utc(item, "nested as_of_utc") > cutoff:
                raise ValueError("metadata contains future as_of_utc")
            _check_nested_as_of(item, cutoff, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_nested_as_of(item, cutoff, depth + 1)


def _metadata(envelope, cutoff, label, *, list_value=False):
    if envelope is None:
        return None, None
    copied = _copy(envelope, MAX_METADATA_BYTES)
    if not isinstance(copied, dict) or set(copied) != {"as_of_utc", "value"}:
        raise ValueError(f"{label} requires exact as_of_utc/value envelope")
    if _utc(copied["as_of_utc"], f"{label}.as_of_utc") > cutoff:
        raise ValueError(f"{label} is later than cutoff")
    value = copied["value"]
    if value is None or (list_value and not isinstance(value, list)):
        raise ValueError(f"{label}.value must be non-null" +
                         (" list" if list_value else ""))
    _check_nested_as_of(value, cutoff)
    return value, {"as_of_utc": copied["as_of_utc"]}


def _geography(value, cutoff):
    if value is None:
        return None
    binding = _copy(value, MAX_OPTION_BYTES)
    if not isinstance(binding, dict) or set(binding) != {
            "graph_sha256", "crs", "origin", "epoch_utc"}:
        raise ValueError("geography_binding requires graph_sha256/crs/origin/epoch_utc")
    if not isinstance(binding["graph_sha256"], str) or not SHA_RE.fullmatch(
            binding["graph_sha256"]):
        raise ValueError("geography graph_sha256 must be lowercase SHA-256")
    for name in ("crs", "origin"):
        text = binding[name]
        if not isinstance(text, str) or not text or len(text) > 256:
            raise ValueError(f"geography {name} must be explicit bounded text")
    if _utc(binding["epoch_utc"], "geography epoch_utc") > cutoff:
        raise ValueError("geography epoch is later than cutoff")
    return binding


@dataclass(frozen=True)
class VerifiedSynopsis:
    """Trusted caller's reviewed display text for exactly one snapshot hash."""

    text: str
    as_of_utc: str
    snapshot_hash: str
    reviewer_id: str


def _synopsis(value, snapshot_hash, cutoff):
    if value is None:
        return None
    if type(value) is not VerifiedSynopsis:
        raise ValueError("synopsis requires trusted VerifiedSynopsis")
    if not isinstance(value.text, str) or not value.text or len(value.text) > 4096:
        raise ValueError("synopsis text must be bounded nonempty text")
    if not isinstance(value.reviewer_id, str) or not ID_RE.fullmatch(value.reviewer_id):
        raise ValueError("synopsis reviewer_id must be a stable identifier")
    if _utc(value.as_of_utc, "synopsis as_of_utc") > cutoff:
        raise ValueError("synopsis is later than cutoff")
    if value.snapshot_hash != snapshot_hash:
        raise ValueError("synopsis was not reviewed for this snapshot")
    return _copy({
        "text": value.text,
        "as_of_utc": value.as_of_utc,
        "snapshot_hash": value.snapshot_hash,
        "reviewer_id": value.reviewer_id,
    }, MAX_OPTION_BYTES)


class SnapshotPublisher:
    """Persist immutable publications and atomically advance current.json."""

    def __init__(self, directory):
        path = Path(directory)
        if not path.is_absolute() or ".." in path.parts or str(path) == "/":
            raise ValueError("publication directory must be an explicit absolute path")
        self.directory = path
        for component in path.parents:
            if component.is_symlink():
                raise ValueError("publication directory contains a symlink")
        if path.is_symlink():
            raise ValueError("publication directory contains a symlink")

    def publish(self, log, cutoff_utc, *, ledger_watermark=None,
                in_flight_commitments=None, source_health=None,
                geography_binding=None, projection_request=None, synopsis=None):
        if type(log) is not EvidenceLog:
            raise TypeError("publication requires a trusted EvidenceLog instance")
        cutoff = _utc(cutoff_utc, "cutoff_utc")
        ledger, ledger_attestation = _metadata(
            ledger_watermark, cutoff, "ledger_watermark")
        commitments, commitments_attestation = _metadata(
            in_flight_commitments, cutoff, "in_flight_commitments", list_value=True)
        geography = _geography(geography_binding, cutoff)
        health = _copy(source_health, MAX_OPTION_BYTES)
        request = _copy(projection_request, MAX_OPTION_BYTES)
        if request is not None:
            if not isinstance(request, dict) or not {
                    "horizon_minutes", "model_version", "assumptions"} <= set(request) or (
                    set(request) - {
                        "horizon_minutes", "model_version", "assumptions",
                        "training_assumptions"}):
                raise ValueError("projection_request has unsupported or missing fields")
        snapshot = log.snapshot(
            cutoff_utc, ledger_watermark=ledger,
            in_flight_commitments=commitments, source_health=health)
        if not isinstance(snapshot, dict):
            raise ValueError("EvidenceLog returned invalid snapshot")
        snap = _copy(snapshot, MAX_PUBLICATION_BYTES)
        recorded_hash = snap.pop("snapshot_hash", None)
        if (snap.get("schema_version") != VERSION or
                snap.get("incident_id") != log.incident_id or
                snap.get("cutoff_utc") != cutoff_utc or
                recorded_hash != _digest(snap)):
            raise ValueError("EvidenceLog snapshot integrity mismatch")
        snap["snapshot_hash"] = recorded_hash
        projection = None
        if request is not None:
            projection = projection_input(snap, **request)
            p = _copy(projection, MAX_PUBLICATION_BYTES)
            projected_hash = p.pop("projection_input_hash", None)
            if (projected_hash != _digest(p) or
                    p.get("initial_snapshot_hash") != recorded_hash or
                    p.get("can_calculate_operational_outcomes") is not False):
                raise ValueError("projection input integrity mismatch")
            projection = p | {"projection_input_hash": projected_hash}
        reviewed_synopsis = _synopsis(synopsis, recorded_hash, cutoff)
        attestations = {
            "ledger_watermark": ledger_attestation,
            "in_flight_commitments": commitments_attestation,
        }
        mission_input = {
            "publication_version": PUBLICATION_VERSION,
            "incident_id": snap["incident_id"],
            "bbox_lonlat": snap["bbox_lonlat"],
            "cutoff_utc": snap["cutoff_utc"],
            "categories": snap["categories"],
            "revision_history": snap["revision_history"],
            "unconfirmed_leads": snap["unconfirmed_leads"],
            "accepted_source_refs": snap["accepted_source_refs"],
            "ledger_watermark": snap["ledger_watermark"],
            "in_flight_commitments": snap["in_flight_commitments"],
            "metadata_attestations": attestations,
            "geography_binding": geography,
        }
        mission_hash = _digest(mission_input)
        view_input = {
            "publication_version": PUBLICATION_VERSION,
            "mission_hash": mission_hash,
            "snapshot_hash": recorded_hash,
            "source_health": snap["source_health"],
            "synopsis": reviewed_synopsis,
            "projection_input_hash": (
                projection["projection_input_hash"] if projection is not None else None),
        }
        view_hash = _digest(view_input)
        publication = {
            "publication_version": PUBLICATION_VERSION,
            "incident_id": snap["incident_id"],
            "cutoff_utc": cutoff_utc,
            "mission_hash": mission_hash,
            "view_hash": view_hash,
            "snapshot": snap,
            "projection_input": projection,
            "geography_binding": geography,
            "metadata_attestations": attestations,
            "synopsis": reviewed_synopsis,
            "capabilities": {
                "can_calculate_operational_outcomes": False,
                "can_dispatch": False,
            },
        }
        content = _canonical(publication) + b"\n"
        if len(content) > MAX_PUBLICATION_BYTES:
            raise ValueError("publication exceeds byte limit")
        self._persist(view_hash, content)
        return json.loads(content)

    def _directory_fd(self):
        # Walk from root using directory descriptors. No component may be a
        # symlink, and only the final directory may be created.
        parts = self.directory.parts
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for index, component in enumerate(parts[1:], 1):
                if component in ("", ".", ".."):
                    raise ValueError("invalid publication directory component")
                if index == len(parts) - 1:
                    try:
                        os.mkdir(component, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                new_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY |
                                 os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new_fd
            return fd
        except OSError as exc:
            os.close(fd)
            raise ValueError("publication directory has an invalid or symlink component") from exc
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _read_regular(fd, name, limit):
        try:
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ValueError(f"unsafe existing {name}") from exc
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError(f"unsafe existing {name}")
            chunks = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(file_fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > limit:
                raise ValueError(f"unsafe existing {name}")
            return data
        finally:
            os.close(file_fd)

    @staticmethod
    def _write_new(fd, name, data):
        file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                          os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(file_fd, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(file_fd)
        finally:
            os.close(file_fd)

    def _replace_pointer(self, fd, temporary_name):
        os.replace(temporary_name, "current.json", src_dir_fd=fd, dst_dir_fd=fd)

    def _persist(self, view_hash, content):
        fd = self._directory_fd()
        try:
            name = f"publication-{view_hash}.json"
            existing = self._read_regular(fd, name, MAX_PUBLICATION_BYTES)
            if existing is None:
                temporary_publication = f".publication-{secrets.token_hex(16)}.tmp"
                try:
                    self._write_new(fd, temporary_publication, content)
                    try:
                        os.link(temporary_publication, name, src_dir_fd=fd,
                                dst_dir_fd=fd, follow_symlinks=False)
                        os.fsync(fd)
                    except FileExistsError:
                        existing = self._read_regular(fd, name, MAX_PUBLICATION_BYTES)
                        if existing != content:
                            raise ValueError("existing publication differs")
                finally:
                    try:
                        os.unlink(temporary_publication, dir_fd=fd)
                    except FileNotFoundError:
                        pass
            elif existing != content:
                raise ValueError("existing publication differs")
            pointer = {
                "publication_version": PUBLICATION_VERSION,
                "view_hash": view_hash,
                "publication_file": name,
                "publication_sha256": hashlib.sha256(content).hexdigest(),
            }
            pointer_bytes = _canonical(pointer) + b"\n"
            old_pointer = self._read_regular(fd, "current.json", 4096)
            if old_pointer is not None:
                try:
                    old = json.loads(old_pointer)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("existing current pointer is malformed") from exc
                if (not isinstance(old, dict) or
                        old.get("publication_version") != PUBLICATION_VERSION or
                        set(old) != {"publication_version", "view_hash",
                                     "publication_file", "publication_sha256"}):
                    raise ValueError("existing current pointer is malformed")
                if old_pointer == pointer_bytes:
                    return
            temporary_name = f".current-{secrets.token_hex(16)}.tmp"
            try:
                self._write_new(fd, temporary_name, pointer_bytes)
                self._replace_pointer(fd, temporary_name)
                os.fsync(fd)
            except BaseException:
                try:
                    os.unlink(temporary_name, dir_fd=fd)
                except FileNotFoundError:
                    pass
                raise
        finally:
            os.close(fd)
