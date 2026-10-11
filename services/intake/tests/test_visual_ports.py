"""UNEXECUTED source-only fixture controls, not model/JCS/acceptance evidence."""
import unittest
from hashlib import sha256
from services.intake.visual_ports import (
    Cancelled, InvalidEvidence, MissingEvidence, PrivateExecution,
    RuntimeCallbacks, RuntimeBusy, localize, run,
)

DIGEST = "a" * 64
TIME = "2026-10-11T00:00:00.000Z"


class FixtureCancel:
    def __init__(self):
        self.cancelled = False
    def raise_if_cancelled(self):
        if self.cancelled:
            raise Cancelled("fixture")


class FixtureAuthority:
    """Only protocol controls; fixed test digests are NOT an RFC8785 codec."""
    def __init__(self):
        self.calls = []
        self.execution_origin = "contract_test_fixture"
        self.rechecks = 0
        self.reject = False
        self.stale_after = None
        self.tamper = False
        self.mutate_issued_execution = False
        self.mutate_verification_input = False
        self.nested = None
    def admit_request(self, request, *, task, port_identity):
        self.calls.append(("admit", task, request, port_identity))
        if self.reject:
            raise MissingEvidence("fixture admission denied")
        return object()
    def check_media(self, permit, image):
        self.calls.append(("media", image))
    def request_fingerprint(self, permit):
        return DIGEST
    def canonical_sha256(self, value):
        return DIGEST
    def revalidate(self, permit):
        self.rechecks += 1
        if self.stale_after == self.rechecks:
            raise MissingEvidence("fixture retake/revocation")
    def execute(self, permit, *, request, normalized_image_bytes, cancel):
        self.calls.append(("execute", request, normalized_image_bytes))
        if self.nested:
            self.nested()
        return PrivateExecution("completed", self.execution_origin, TIME, TIME,
                                {"fixture_value": "unchanged"}, b"fixture-only", 0)
    def issue_execution(self, permit, *, request, execution):
        localized = request["message_kind"] == "localization_request"
        key = ("localization_request_fingerprint" if localized
               else "runner_request_fingerprint")
        if self.mutate_issued_execution:
            execution.output["fixture_value"] = "changed-in-place"
        output = execution.output.copy()
        if self.tamper:
            output["fixture_value"] = "changed"
        return {
            "schema_version": "faces-live-observation-v1",
            "message_kind": ("localization_execution_receipt" if localized
                             else "execution_receipt"),
            "record": {
                "execution_id": "fixture-only", "artifact": request["record"]["artifact"],
                "origin": execution.origin, "started_at": TIME, "ended_at": TIME,
                "state": "completed", "output": output, "output_sha256": DIGEST,
                "runtime_log_sha256": sha256(execution.runtime_log).hexdigest(),
                "process_exit_code": 0, "issuer_identity_receipt_sha256": DIGEST,
                key: DIGEST,
            },
        }
    def verify_issued_execution(self, permit, receipt):
        self.calls.append(("verify-fixture-only", receipt))
        if self.mutate_verification_input:
            receipt["record"]["output"]["fixture_value"] = "changed-in-verification"


def request(localized=True):
    # Deliberately minimal protocol fixture. Never a schema/permission-valid
    # real request or model artifact; real authority must reject this.
    return {"schema_version": "faces-live-observation-v1",
            "message_kind": "localization_request" if localized else "runner_request",
            "record": {"artifact": {"fixture": True}, "frame": {"capture_id": "B"}}}


class VisualPortControls(unittest.TestCase):
    def test_both_ports_accept_contract_test_fixture_origin(self):
        for port, localized in ((localize, True), (run, False)):
            with self.subTest(port=port.__name__):
                receipt = port(request(localized), b"fictional",
                               trusted_registry=FixtureAuthority(), cancel=FixtureCancel())
                self.assertEqual(receipt["record"]["origin"], "contract_test_fixture")

    def test_both_ports_reject_wrong_fixture_origin(self):
        for port, localized in ((localize, True), (run, False)):
            with self.subTest(port=port.__name__):
                authority = FixtureAuthority()
                authority.execution_origin = "fixture"
                with self.assertRaises(InvalidEvidence):
                    port(request(localized), b"fictional",
                         trusted_registry=authority, cancel=FixtureCancel())

    def test_missing_authority_and_rejected_admission_make_zero_calls(self):
        with self.assertRaises(MissingEvidence):
            localize(request(), b"fictional", trusted_registry=None, cancel=FixtureCancel())
        authority = FixtureAuthority()
        authority.reject = True
        with self.assertRaises(MissingEvidence):
            localize(request(), b"fictional", trusted_registry=authority, cancel=FixtureCancel())
        self.assertEqual([item[0] for item in authority.calls], ["admit"])

    def test_keyword_wrappers_forward_whole_selected_request_and_exact_bytes(self):
        authority = FixtureAuthority()
        callback = RuntimeCallbacks(authority, FixtureCancel())
        original = request()
        callback.detect_frame(request=original, normalized_image_bytes=b"selected-B")
        executed = next(item for item in authority.calls if item[0] == "execute")
        self.assertEqual(executed[1], original)
        self.assertIsNot(executed[1], original)
        self.assertEqual(executed[2], b"selected-B")
        self.assertEqual(authority.rechecks, 3)

    def test_changed_output_rejected_even_with_same_fixture_digest(self):
        authority = FixtureAuthority()
        authority.tamper = True
        with self.assertRaises(InvalidEvidence):
            run(request(False), b"fictional", trusted_registry=authority, cancel=FixtureCancel())

    def test_issuer_cannot_mutate_expected_worker_output(self):
        authority = FixtureAuthority()
        authority.mutate_issued_execution = True
        with self.assertRaises(InvalidEvidence):
            localize(request(), b"fictional", trusted_registry=authority, cancel=FixtureCancel())

    def test_verifier_receives_isolated_receipt_copy(self):
        authority = FixtureAuthority()
        authority.mutate_verification_input = True
        receipt = localize(request(), b"fictional", trusted_registry=authority, cancel=FixtureCancel())
        self.assertEqual(receipt["record"]["output"]["fixture_value"], "unchanged")

    def test_post_execute_retake_discards_before_issuance(self):
        authority = FixtureAuthority()
        authority.stale_after = 2
        with self.assertRaises(MissingEvidence):
            localize(request(), b"fictional", trusted_registry=authority, cancel=FixtureCancel())
        self.assertNotIn("verify-fixture-only", [item[0] for item in authority.calls])

    def test_detector_and_visual_share_one_slot_with_no_queue(self):
        authority = FixtureAuthority()
        def nested():
            with self.assertRaises(RuntimeBusy):
                run(request(False), b"fictional", trusted_registry=FixtureAuthority(),
                    cancel=FixtureCancel())
        authority.nested = nested
        localize(request(), b"fictional", trusted_registry=authority, cancel=FixtureCancel())

    def test_cancel_before_admission_and_slot_released_after_denial(self):
        authority = FixtureAuthority()
        cancel = FixtureCancel()
        cancel.cancelled = True
        with self.assertRaises(Cancelled):
            localize(request(), b"fictional", trusted_registry=authority, cancel=cancel)
        self.assertEqual(authority.calls, [])
        cancel.cancelled = False
        localize(request(), b"fictional", trusted_registry=authority, cancel=cancel)

    def test_nonfinite_request_rejected_without_worker(self):
        authority = FixtureAuthority()
        value = request()
        value["record"]["bad"] = float("nan")
        with self.assertRaises(InvalidEvidence):
            localize(value, b"fictional", trusted_registry=authority, cancel=FixtureCancel())
        self.assertEqual(authority.calls, [])


if __name__ == "__main__":
    unittest.main()
