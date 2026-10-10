"""Proposals only; caller owns human authentication, durable storage and state application."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from .contracts import CaseRecord, DetectionResult, digest, number, text, validate_detection


@dataclass(frozen=True)
class CandidateEvidence:
    evidence_id: str
    label: str
    face_box_index: int
    source_reference: str
    provenance: str

    def __post_init__(self) -> None:
        text(self.evidence_id, "evidence_id")
        if self.label not in ("moulage_mark", "visible_mark", "visible_swelling", "visible_bruising", "unclear"):
            raise ValueError("unsupported visible-evidence label; diagnosis forbidden")
        if type(self.face_box_index) is not int or not 0 <= self.face_box_index < 100:
            raise ValueError("face_box_index must reference a box")
        text(self.source_reference, "source_reference")
        if self.provenance not in ("fixture_annotation", "human_annotation", "unvalidated_model_suggestion"):
            raise ValueError("unknown evidence provenance")


@dataclass(frozen=True)
class EvidenceProposal:
    proposal_id: str
    content_hash: str
    case: CaseRecord
    detection: DetectionResult
    candidates: tuple[CandidateEvidence, ...]
    created_time_s: float
    abstention_reason: str | None


@dataclass(frozen=True)
class ReviewReceipt:
    proposal_id: str
    proposal_hash: str
    case_hash: str
    image_sha256: str
    reviewer_id: str
    decision: str
    confirmed_evidence: tuple[str, ...]
    confirm_exercise_need: bool
    reviewed_time_s: float


@dataclass(frozen=True)
class ExerciseRequestProposal:
    command_kind: str
    idempotency_key: str
    request_id: str
    case_id: str
    case_hash: str
    image_sha256: str
    origin_node: str
    destination_node: str
    persons: int
    urgency: str
    need_source_reference: str
    need_provenance: str
    review_receipt: ReviewReceipt
    confirmed_evidence: tuple[CandidateEvidence, ...]
    detection_provenance: str
    evidence_status: str


class CaseBroker:
    """Serialized in-memory service. A root adapter must persist and atomically consume keys."""
    def __init__(self) -> None:
        self._cases: dict[str, CaseRecord] = {}
        self._proposals: dict[str, EvidenceProposal] = {}
        self._reviews: dict[str, ReviewReceipt] = {}

    def submit(self, case: CaseRecord, detection: DetectionResult, candidates: tuple[CandidateEvidence, ...], *, created_time_s: float) -> EvidenceProposal:
        if not isinstance(case, CaseRecord):
            raise ValueError("typed case required")
        case.rights.require("display")
        validate_detection(case, detection)
        number(created_time_s, "created_time_s", detection.observed_time_s)
        if not isinstance(candidates, tuple) or len(candidates) > 100 or not all(isinstance(c, CandidateEvidence) for c in candidates):
            raise ValueError("candidates must be a bounded immutable evidence tuple")
        if len({c.evidence_id for c in candidates}) != len(candidates):
            raise ValueError("duplicate evidence IDs")
        if detection.status != "localized" and candidates:
            raise ValueError("abstained detections cannot propose visual evidence")
        for c in candidates:
            if c.face_box_index >= len(detection.boxes):
                raise ValueError("candidate references nonexistent face box")
            if case.rights.source_kind == "synthetic" and c.provenance != "fixture_annotation":
                raise ValueError("synthetic controls require fixture annotation provenance")
            if case.rights.source_kind != "synthetic" and c.provenance == "fixture_annotation":
                raise ValueError("real photos cannot claim fixture annotation evidence")
        previous = self._cases.get(case.case_id)
        if previous is not None and previous != case:
            raise ValueError("conflicting content under case ID; use a new versioned case ID")
        content_hash = digest({"case":asdict(case), "detection":asdict(detection), "candidates":[asdict(c) for c in candidates]})
        proposal_id = "casualty-proposal-" + content_hash
        if proposal_id in self._proposals:
            return self._proposals[proposal_id]
        p = EvidenceProposal(proposal_id, content_hash, case, detection, candidates, created_time_s,
                             None if detection.status == "localized" else detection.status)
        self._cases[case.case_id] = case
        self._proposals[proposal_id] = p
        return p

    def review(self, proposal_id: str, *, reviewer_id: str, decision: str, confirmed_evidence: tuple[str, ...] = (),
               confirm_exercise_need: bool = False, reviewed_time_s: float) -> ReviewReceipt:
        p = self._proposal(proposal_id)
        text(reviewer_id, "reviewer_id")
        if decision not in ("accepted", "rejected"):
            raise ValueError("review decision must be accepted or rejected")
        number(reviewed_time_s, "reviewed_time_s", p.created_time_s)
        if type(confirm_exercise_need) is not bool:
            raise ValueError("confirm_exercise_need must be boolean")
        if not isinstance(confirmed_evidence, tuple) or not all(isinstance(e, str) for e in confirmed_evidence):
            raise ValueError("confirmed_evidence must be an immutable evidence ID tuple")
        ids = {c.evidence_id for c in p.candidates if c.label != "unclear"}
        if len(set(confirmed_evidence)) != len(confirmed_evidence) or not set(confirmed_evidence) <= ids:
            raise ValueError("review selected unsupported or unclear evidence")
        if decision == "rejected" and (confirmed_evidence or confirm_exercise_need):
            raise ValueError("rejected review cannot confirm evidence or exercise need")
        if confirm_exercise_need and p.case.exercise_need is None:
            raise ValueError("no authored exercise need to confirm")
        selected = tuple(sorted(confirmed_evidence))
        previous = self._reviews.get(proposal_id)
        if previous is not None:
            if (previous.reviewer_id, previous.decision, previous.confirmed_evidence, previous.confirm_exercise_need) != (reviewer_id, decision, selected, confirm_exercise_need):
                raise ValueError("conflicting terminal review")
            return previous
        receipt = ReviewReceipt(p.proposal_id, p.content_hash, p.case.content_hash, p.case.image.sha256,
                                reviewer_id, decision, selected, confirm_exercise_need, reviewed_time_s)
        self._reviews[proposal_id] = receipt
        return receipt

    def export_request(self, receipt: ReviewReceipt) -> ExerciseRequestProposal | None:
        if not isinstance(receipt, ReviewReceipt):
            raise ValueError("human review receipt required")
        p = self._proposal(receipt.proposal_id)
        if self._reviews.get(receipt.proposal_id) != receipt:
            raise ValueError("receipt does not match recorded review")
        if (receipt.proposal_hash, receipt.case_hash, receipt.image_sha256) != (p.content_hash, p.case.content_hash, p.case.image.sha256):
            raise ValueError("receipt case/proposal/image binding mismatch")
        if receipt.decision != "accepted" or not receipt.confirm_exercise_need:
            return None
        need = p.case.exercise_need
        if need is None:
            raise ValueError("reviewed exercise need missing")
        key = "casualty-exercise-need-" + digest({"case_hash":p.case.content_hash, "request_id":need.request_id})
        return ExerciseRequestProposal(command_kind="casualty_exercise_need_proposal", idempotency_key=key,
            request_id=need.request_id, case_id=p.case.case_id, case_hash=p.case.content_hash,
            image_sha256=p.case.image.sha256, origin_node=need.origin_node, destination_node=need.destination_node,
            persons=need.persons, urgency=need.urgency, need_source_reference=need.source_reference,
            need_provenance="exercise_metadata_with_human_confirmation", review_receipt=receipt,
            confirmed_evidence=tuple(c for c in p.candidates if c.evidence_id in receipt.confirmed_evidence),
            detection_provenance=p.detection.provenance,
            evidence_status="abstained" if p.abstention_reason else ("human_confirmed" if receipt.confirmed_evidence else "not_confirmed"))

    def _proposal(self, proposal_id: str) -> EvidenceProposal:
        text(proposal_id, "proposal_id")
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise ValueError("unknown proposal_id") from exc
