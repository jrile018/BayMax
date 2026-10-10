"""Typed pending evidence for root review; this module cannot authorize incident use."""
from __future__ import annotations

from dataclasses import dataclass, field

from .broker import ExerciseRequestProposal, ReviewReceipt
from .contracts import CaseRecord, digest


_REVIEW_ACTOR_KINDS = ("scripted_demo", "unverified_human")
_COMMON_BLOCKERS = (
    "root_verified_casualty_source",
    "authenticated_record_bound_human_review",
    "root_record_construction",
)


@dataclass(frozen=True)
class PendingIncidentEvidence:
    """A case-bound exercise handoff, never a VerifiedSource or HumanReview."""

    case_id: str
    case_hash: str
    image_sha256: str
    request_id: str
    source_kind: str
    source_reference: str
    rights_status_claim: str
    reviewer_id: str
    review_actor_kind: str
    evidence_status: str
    blockers: tuple[str, ...]
    adoption_status: str = field(default="pending", init=False)
    operational_eligible: bool = field(default=False, init=False)


def make_pending_incident_evidence(
    case: CaseRecord,
    request: ExerciseRequestProposal,
    *,
    review_actor_kind: str,
) -> PendingIncidentEvidence:
    """Label an exercise proposal without promoting claims into trusted incident facts.

    Trusted application code must independently verify case source bytes, item rights,
    reviewer authentication, and the complete incident record before any append.
    """
    if not isinstance(case, CaseRecord) or not isinstance(request, ExerciseRequestProposal):
        raise ValueError("typed case and exercise request required")
    if review_actor_kind not in _REVIEW_ACTOR_KINDS:
        raise ValueError("review_actor_kind must be scripted_demo or unverified_human")
    need = case.exercise_need
    if need is None or (
        request.case_id,
        request.case_hash,
        request.image_sha256,
        request.request_id,
        request.origin_node,
        request.destination_node,
        request.persons,
        request.urgency,
        request.need_source_reference,
    ) != (
        case.case_id,
        case.content_hash,
        case.image.sha256,
        need.request_id,
        need.origin_node,
        need.destination_node,
        need.persons,
        need.urgency,
        need.source_reference,
    ):
        raise ValueError("case/request binding mismatch")
    expected_key = "casualty-exercise-need-" + digest(
        {"case_hash": case.content_hash, "request_id": need.request_id}
    )
    if request.idempotency_key != expected_key:
        raise ValueError("request key binding mismatch")
    receipt = request.review_receipt
    if not isinstance(receipt, ReviewReceipt):
        raise ValueError("typed receipt required")
    if (
        receipt.proposal_id != "casualty-proposal-" + receipt.proposal_hash
        or
        request.command_kind != "casualty_exercise_need_proposal"
        or request.need_provenance != "exercise_metadata_with_human_confirmation"
        or receipt.case_hash != case.content_hash
        or receipt.image_sha256 != case.image.sha256
        or receipt.decision != "accepted"
        or receipt.confirm_exercise_need is not True
        or not receipt.reviewer_id
    ):
        raise ValueError("receipt binding mismatch")
    blockers = _COMMON_BLOCKERS
    if case.rights.source_kind == "synthetic":
        blockers = ("synthetic_fixture_training_only",) + blockers
    else:
        blockers = ("independent_item_rights_review",) + blockers
    return PendingIncidentEvidence(
        case_id=case.case_id,
        case_hash=case.content_hash,
        image_sha256=case.image.sha256,
        request_id=need.request_id,
        source_kind=case.rights.source_kind,
        source_reference=case.rights.source_reference,
        rights_status_claim=case.rights.verification_status,
        reviewer_id=receipt.reviewer_id,
        review_actor_kind=review_actor_kind,
        evidence_status=request.evidence_status,
        blockers=blockers,
    )
