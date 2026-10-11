"""Source-only runtime ports; no model, registry, codec or backend is configured.

Root-authority implementations must be independently reviewed. This module
does not mint permissions, accepted evaluations, JCS codecs or model results.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Literal, Protocol

Task = Literal["face_localization", "visible_facial_concerns"]
Envelope = dict[str, object]
_JSON_TYPES = (str, int, float, bool, type(None))
_SERIAL = Lock()
API_VERSION = "hf-visual-ports-v1"


class MissingEvidence(RuntimeError):
    """No genuine configured authority, worker or evidence."""


class InvalidEvidence(RuntimeError):
    """A strict envelope or complete execution binding failed."""


class RuntimeBusy(RuntimeError):
    """No backlog: the shared in-process detector/visual slot is occupied."""


class Cancelled(RuntimeError):
    """Cancel was observed; this alone proves no native worker was stopped."""


@dataclass(frozen=True)
class PortIdentity:
    import_path: str
    api_version: str
    source_sha256: str


@dataclass(frozen=True)
class PrivateExecution:
    state: Literal["completed", "failed", "cancelled"]
    origin: Literal["actual_detector", "actual_visual_runner", "contract_test_fixture"]
    started_at: str
    ended_at: str
    output: Envelope | None
    runtime_log: bytes
    process_exit_code: int | None


class Cancellation(Protocol):
    def raise_if_cancelled(self) -> None:
        """Raise on cancellation; root worker separately enforces termination."""


class RuntimeAuthority(Protocol):
    """Server-owned configuration, never an object parsed from HTTP.

    Admission validates exact Faces schema/JCS/source identity, authenticated
    current request/capture/normalization/permission, task-specific accepted
    evaluation and lineage/retention/resource deadlines BEFORE pixel access.
    Selected localization uses valid visual_assessment authority independently
    of a consumed preview session. No preview receipt can admit selected B.

    check_media then verifies permitted bytes/hash/dimensions and transport.
    execute owns the supervised worker, real watchdog/cancellation, shared
    cross-process CPU2/device/resource allocation, typed case/time mapping,
    model/runtime manifests, strict output and actual private evidence.
    issue_execution verifies full schema/semantics/JCS, current issuer/log and
    complete request-output provenance. Fixture issuance is test-only.
    verify_issued_execution authenticates issuance, semantics and exact full
    output. revalidate checks authoritative currentness/rights/evaluation and
    retention; it raises after retake/revocation/expiry. No method may silently
    substitute absent evidence, self-asserted digests or missing authority.
    Root owns private log/output/receipt cleanup and invalidation deadlines.
    """
    def admit_request(self, request: Envelope, *, task: Task,
                      port_identity: PortIdentity) -> object: ...
    def check_media(self, permit: object, image: bytes) -> None: ...
    def request_fingerprint(self, permit: object) -> str: ...
    def canonical_sha256(self, value: object) -> str:
        """Exact reviewed RFC8785 JCS; ordinary sorted JSON is forbidden."""
        ...
    def revalidate(self, permit: object) -> None: ...
    def execute(self, permit: object, *, request: Envelope,
                normalized_image_bytes: bytes,
                cancel: Cancellation) -> PrivateExecution: ...
    def issue_execution(self, permit: object, *, request: Envelope,
                        execution: PrivateExecution) -> Envelope: ...
    def verify_issued_execution(self, permit: object, receipt: Envelope) -> None: ...


def source_identity() -> PortIdentity:
    return PortIdentity("services.intake.visual_ports", API_VERSION,
                        sha256(Path(__file__).read_bytes()).hexdigest())


def _snapshot(value: object, depth: int = 0) -> object:
    # Exact builtins avoid custom mapping/copy hooks. Never accept nonfinite
    # JSON or integers outside the Faces/JCS interoperable range.
    if depth > 32:
        raise InvalidEvidence("JSON nesting limit")
    if type(value) in _JSON_TYPES:
        if type(value) is float and not isfinite(value):
            raise InvalidEvidence("nonfinite JSON")
        if type(value) is int and abs(value) > 2**53 - 1:
            raise InvalidEvidence("noninteroperable integer")
        return value
    if type(value) is list:
        return [_snapshot(item, depth + 1) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise InvalidEvidence("JSON keys must be strings")
        return {key: _snapshot(item, depth + 1) for key, item in value.items()}
    raise InvalidEvidence("only JSON builtins are allowed")


def _envelope(value: object, kind: str) -> Envelope:
    result = _snapshot(value)
    if type(result) is not dict or set(result) != {
            "schema_version", "message_kind", "record"}:
        raise InvalidEvidence("envelope keys")
    if result["schema_version"] != "faces-live-observation-v1":
        raise InvalidEvidence("schema version")
    if result["message_kind"] != kind or type(result["record"]) is not dict:
        raise InvalidEvidence("message kind/record")
    return result


def _checked_receipt(receipt: object, request: Envelope, permit: object,
                     execution: PrivateExecution, task: Task,
                     authority: RuntimeAuthority) -> Envelope:
    localized = task == "face_localization"
    kind = "localization_execution_receipt" if localized else "execution_receipt"
    result = _envelope(receipt, kind)
    record = result["record"]
    fingerprint_key = ("localization_request_fingerprint" if localized
                       else "runner_request_fingerprint")
    keys = {"execution_id", "artifact", "origin", "started_at", "ended_at",
            "state", "output", "output_sha256", "runtime_log_sha256",
            "process_exit_code", "issuer_identity_receipt_sha256",
            fingerprint_key}
    if set(record) != keys:
        raise InvalidEvidence("execution record keys")
    expected = {
        "artifact": request["record"]["artifact"],
        "origin": execution.origin,
        "started_at": execution.started_at,
        "ended_at": execution.ended_at,
        "state": execution.state,
        "output": execution.output,
        "output_sha256": (authority.canonical_sha256(_snapshot(execution.output))
                          if execution.output is not None else None),
        "runtime_log_sha256": sha256(execution.runtime_log).hexdigest(),
        "process_exit_code": execution.process_exit_code,
        fingerprint_key: authority.request_fingerprint(permit),
    }
    if any(record[key] != value for key, value in expected.items()):
        raise InvalidEvidence("complete execution/output mismatch")
    if execution.state not in {"completed", "failed", "cancelled"}:
        raise InvalidEvidence("execution state")
    if execution.state == "completed":
        if execution.output is None or type(execution.process_exit_code) is not int:
            raise InvalidEvidence("completed evidence missing")
        if execution.process_exit_code != 0:
            raise InvalidEvidence("completed exit must be zero")
        actual_origin = "actual_detector" if localized else "actual_visual_runner"
        if execution.origin not in {actual_origin, "contract_test_fixture"}:
            raise InvalidEvidence("wrong task execution origin")
    elif execution.output is not None:
        raise InvalidEvidence("failed/cancelled execution has output")
    # Strict output geometry/cues/task/evaluation/issuer/time semantics remain
    # mandatory in the reviewed authority; equality alone is not admission.
    authority.verify_issued_execution(permit, _envelope(result, kind))
    return result


def _invoke(request_envelope: Envelope, normalized_image_bytes: bytes, *,
            trusted_registry: RuntimeAuthority | None,
            cancel: Cancellation, task: Task) -> Envelope:
    if trusted_registry is None:
        raise MissingEvidence("root runtime authority is not configured")
    kind = "localization_request" if task == "face_localization" else "runner_request"
    request = _envelope(request_envelope, kind)
    if not _SERIAL.acquire(blocking=False):
        raise RuntimeBusy("detector/visual slot occupied")
    try:
        cancel.raise_if_cancelled()
        permit = trusted_registry.admit_request(
            _envelope(request, kind), task=task, port_identity=source_identity())
        if permit is None:
            raise MissingEvidence("authority did not admit request")
        # Only admission above may permit media inspection.
        if type(normalized_image_bytes) is not bytes:
            raise InvalidEvidence("normalized media must be exact bytes")
        trusted_registry.check_media(permit, normalized_image_bytes)
        trusted_registry.revalidate(permit)
        cancel.raise_if_cancelled()
        execution = trusted_registry.execute(
            permit, request=_envelope(request, kind),
            normalized_image_bytes=normalized_image_bytes, cancel=cancel)
        if type(execution) is not PrivateExecution:
            raise InvalidEvidence("untyped private execution")
        if execution.output is not None and type(execution.output) is not dict:
            raise InvalidEvidence("worker output must be an object or null")
        if (execution.process_exit_code is not None
                and type(execution.process_exit_code) is not int):
            raise InvalidEvidence("exit code must be an integer or null")
        if type(execution.runtime_log) is not bytes:
            raise InvalidEvidence("private runtime log must be exact bytes")
        # Isolate backend-owned mutable output before issuance/comparison.
        execution = PrivateExecution(execution.state, execution.origin,
                                     execution.started_at, execution.ended_at,
                                     _snapshot(execution.output),
                                     execution.runtime_log, execution.process_exit_code)
        cancel.raise_if_cancelled()
        trusted_registry.revalidate(permit)
        receipt = trusted_registry.issue_execution(
            permit, request=_envelope(request, kind),
            execution=PrivateExecution(execution.state, execution.origin,
                                       execution.started_at, execution.ended_at,
                                       _snapshot(execution.output),
                                       execution.runtime_log, execution.process_exit_code))
        checked = _checked_receipt(receipt, request, permit, execution, task,
                                   trusted_registry)
        cancel.raise_if_cancelled()
        trusted_registry.revalidate(permit)
        return checked
    finally:
        _SERIAL.release()


def localize(request_envelope: Envelope, normalized_image_bytes: bytes, *,
             trusted_registry: RuntimeAuthority | None,
             cancel: Cancellation) -> Envelope:
    return _invoke(request_envelope, normalized_image_bytes,
                   trusted_registry=trusted_registry, cancel=cancel,
                   task="face_localization")


def run(request_envelope: Envelope, normalized_image_bytes: bytes, *,
        trusted_registry: RuntimeAuthority | None,
        cancel: Cancellation) -> Envelope:
    return _invoke(request_envelope, normalized_image_bytes,
                   trusted_registry=trusted_registry, cancel=cancel,
                   task="visible_facial_concerns")


@dataclass(frozen=True)
class RuntimeCallbacks:
    """Server-configured keyword callbacks for the exact Faces call shape."""
    trusted_registry: RuntimeAuthority
    cancel: Cancellation

    def detect_frame(self, *, request: Envelope,
                     normalized_image_bytes: bytes) -> Envelope:
        return localize(request, normalized_image_bytes,
                        trusted_registry=self.trusted_registry, cancel=self.cancel)

    def run_visible_concerns(self, *, request: Envelope,
                            normalized_image_bytes: bytes) -> Envelope:
        return run(request, normalized_image_bytes,
                   trusted_registry=self.trusted_registry, cancel=self.cancel)
