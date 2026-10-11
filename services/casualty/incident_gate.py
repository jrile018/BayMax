"""Typed pending evidence for root review; this module cannot authorize incident use."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .broker import EvidenceProposal, ExerciseRequestProposal, ReviewReceipt
from .contracts import CaseRecord, DetectionResult, digest


_REVIEW_ACTOR_KINDS = ("scripted_demo", "unverified_human")
_COMMON_BLOCKERS = (
    "root_verified_casualty_source",
    "authenticated_record_bound_human_review",
    "root_record_construction",
)


@dataclass(frozen=True)
class PendingIncidentEvidence:
    """A proposal-bound exercise handoff, never a VerifiedSource or HumanReview."""

    case_id: str
    case_hash: str
    image_sha256: str
    proposal_id: str
    proposal_hash: str
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
    proposal: EvidenceProposal,
    request: ExerciseRequestProposal,
    *,
    review_actor_kind: str,
) -> PendingIncidentEvidence:
    """Label an exercise proposal without promoting claims into trusted incident facts.

    Trusted application code must independently verify case source bytes, item rights,
    reviewer authentication, and the complete incident record before any append.
    """
    if not isinstance(proposal, EvidenceProposal) or not isinstance(request, ExerciseRequestProposal):
        raise ValueError("typed proposal and exercise request required")
    if review_actor_kind not in _REVIEW_ACTOR_KINDS:
        raise ValueError("review_actor_kind must be scripted_demo or unverified_human")
    case = proposal.case
    if not isinstance(case, CaseRecord) or not isinstance(proposal.detection, DetectionResult):
        raise ValueError("typed case and detection required")
    expected_proposal_hash = digest({
        "case": asdict(case),
        "detection": asdict(proposal.detection),
        "candidates": [asdict(candidate) for candidate in proposal.candidates],
    })
    if (
        proposal.content_hash != expected_proposal_hash
        or proposal.proposal_id != "casualty-proposal-" + expected_proposal_hash
        or proposal.detection.case_id != case.case_id
        or proposal.detection.image_sha256 != case.image.sha256
        or proposal.abstention_reason != (
            None if proposal.detection.status == "localized" else proposal.detection.status
        )
    ):
        raise ValueError("proposal observation binding mismatch")
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
    allowed_ids = {candidate.evidence_id for candidate in proposal.candidates if candidate.label != "unclear"}
    if (
        receipt.proposal_id != proposal.proposal_id
        or receipt.proposal_hash != proposal.content_hash
        or request.command_kind != "casualty_exercise_need_proposal"
        or request.need_provenance != "exercise_metadata_with_human_confirmation"
        or receipt.case_hash != case.content_hash
        or receipt.image_sha256 != case.image.sha256
        or receipt.decision != "accepted"
        or receipt.confirm_exercise_need is not True
        or not receipt.reviewer_id
        or len(set(receipt.confirmed_evidence)) != len(receipt.confirmed_evidence)
        or not set(receipt.confirmed_evidence) <= allowed_ids
    ):
        raise ValueError("receipt binding mismatch")
    expected_evidence = tuple(
        candidate for candidate in proposal.candidates
        if candidate.evidence_id in receipt.confirmed_evidence
    )
    if request.confirmed_evidence != expected_evidence:
        raise ValueError("confirmed evidence binding mismatch")
    expected_status = (
        "abstained" if proposal.detection.status != "localized"
        else "human_confirmed" if receipt.confirmed_evidence
        else "not_confirmed"
    )
    if request.evidence_status != expected_status:
        raise ValueError("evidence_status contradicts proposal and receipt")
    if request.detection_provenance != proposal.detection.provenance:
        raise ValueError("detection provenance binding mismatch")
    blockers = _COMMON_BLOCKERS
    if case.rights.source_kind == "synthetic":
        blockers = ("synthetic_fixture_training_only",) + blockers
    else:
        blockers = ("independent_item_rights_review",) + blockers
    return PendingIncidentEvidence(
        case_id=case.case_id,
        case_hash=case.content_hash,
        image_sha256=case.image.sha256,
        proposal_id=proposal.proposal_id,
        proposal_hash=proposal.content_hash,
        request_id=need.request_id,
        source_kind=case.rights.source_kind,
        source_reference=case.rights.source_reference,
        rights_status_claim=case.rights.verification_status,
        reviewer_id=receipt.reviewer_id,
        review_actor_kind=review_actor_kind,
        evidence_status=expected_status,
        blockers=blockers,
    )
