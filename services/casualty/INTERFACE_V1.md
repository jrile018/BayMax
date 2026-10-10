# Casualty C1 interface proposal (root approval required before C2)

This is an owned module boundary, not a modification to shared contracts. All types are frozen stdlib dataclasses. Tuples prevent nested list mutation. Photo/diagnosis/identity/GPU/dispatch performance is not established by C1.

## Case/rights boundary

`CaseRecord(case_id, rights: RightsManifest, image: ImageRecord, exercise_need: ExerciseNeed | None)` uses opaque `npc-case-*` IDs. `ImageRecord` records SHA256, dimensions and annotation reference/author/date. `verify_image(case, image_bytes, purpose)` checks recorded rights and actual bytes. An external trusted rights reviewer must verify license/consent evidence; these fields are an audit record, not a cryptographic proof of permission. Synthetic and adult staged/consented/licensed photos are distinct source kinds.

`RightsManifest.require(purpose)` gates each operation. `display` means private training display only. `public_demo`, `video`, `dataset_publication` and `github_publication` are independent permissions with applicable channel-specific consent. C1 fixture has none of those publication permissions. No photo/consent form is included in the command export. Real image ingest, EXIF removal, expiry/withdrawal enforcement and retention are pending the actual data gate and must be handled before C2.

`ExerciseNeed(request_id, origin_node, destination_node, persons, urgency, source_reference)` supplies explicit fictional medical-transport need metadata. `urgency` is `urgent`, `routine` or `unknown`; it never comes from a photograph/detector. Root validates actual node IDs, capacities, resource availability and human-confirmed priority. No internal trauma, clinical severity or treatment label exists.

## Detection/evidence boundary

`FaceBox(x1,y1,x2,y2,score)` uses finite normalized XYXY coordinates in [0,1], positive area, and an uncalibrated detector score. `DetectionResult(case_id,image_sha256,status,boxes,provider,model_revision,provenance,observed_time_s,detail)` binds to the case and image. Status is `localized`, `no_face`, `occluded` or `failed`; provenance is `mock_fixture` or `actual_detector`. Actual-detector provenance requires a full pinned revision. Synthetic controls use only mock provenance. A pinned revision is required metadata; the actual model run must separately be proved.

`CandidateEvidence(evidence_id,label,face_box_index,source_reference,provenance)` carries only visible cue suggestions. Allowed labels: `moulage_mark`, `visible_mark`, `visible_swelling`, `visible_bruising`, `unclear`. Provenance: `fixture_annotation`, `human_annotation`, `unvalidated_model_suggestion`. These are candidate cues, not an injury diagnosis. No-face/occluded/failed observations abstain from visual evidence; malformed/mismatched records fail validation.

## Review/export boundary

- `CaseBroker.submit(case, detection, candidates: tuple, *, created_time_s) -> EvidenceProposal`: immutable pending proposal; no known-state mutation. Same content returns original proposal. A case ID cannot be silently rebound to different image/rights/exercise facts.
- `CaseBroker.review(proposal_id, *, reviewer_id, decision, confirmed_evidence=(), confirm_exercise_need=False, reviewed_time_s) -> ReviewReceipt`: accepted/rejected terminal decision, reviewer provenance, chronology, exact proposal/case/image binding. Same decision by same reviewer returns original receipt. Conflicting terminal review fails. The application must authenticate the actual reviewer.
- `CaseBroker.export_request(receipt) -> ExerciseRequestProposal | None`: accepted explicit exercise-need confirmation yields `command_kind=casualty_exercise_need_proposal`; pending/rejected/unconfirmed exports produce no request. This is still a proposal for root/HF, never an intake acceptance, trip/ledger mutation or dispatch.

`ExerciseRequestProposal` carries `idempotency_key`, request/case/hash/image IDs, origin/destination node, persons, authored urgency, need source/provenance, review receipt, human-confirmed cue records and detection/evidence provenance. The key binds the case content + exercise request ID, so later detector runs cannot create a second need. Root must serialize/persist the broker and atomically consume keys in a common accepted-state adapter, provision trusted versioned node resolution and preserve accepted human review guards. Distinct cases can share an authored request ID while exporting different case-bound keys. Before shared consumption, root must atomically deduplicate the authoritative request identity across cases; the current broker does not establish this. No imports from or edits to `services/intake` occur here.

A face miss does not downgrade or suppress a medical need. A human can confirm explicit exercise facts with an abstained visual observation; the exported request has `evidence_status=abstained` and empty confirmed cues. Root must also keep manual intake available if image access or proposal creation fails.

## Evidence/evaluation

`localization_counts(predictions, truth, iou_threshold=.5)` performs score-ordered one-to-one box matching and retains raw TP/FP/FN/matched-IoU sums. Undefined denominators are null. `aggregate` pools counts. C1 controls are hand-authored synthetic boxes, so their metrics are geometry/harness evidence only. No real detector precision/recall, injury accuracy, clinical efficacy, learner benefit or safe-service outcome is claimed.

`python -m services.casualty.demo --output artifacts/casualty/c1-trace.json` uses scripted review calls and a geometric SVG. Shared ambulance route/tracking/learning measurement is pending root adapter + actual data/model gates. The original C1 checkpoint had no model/OpenCV ingress and used no model load or real photo display. The runtime follow-up verified public OpenCV YuNet revision `3cc26e7f1014a5ee5d74a42acee58bafc9d0a310` bytes and isolated OpenCV, then completed two actual CPU calls on a generated blank raster; see `artifacts/casualty/RUNTIME_MANIFEST.json`. This diagnostic did not process a photo or create a case observation, proposal, receipt or request.

## Owned detector boundary

`DETECTOR_V1.md` documents the lazy CPU YuNet adapter. Its mocked controls establish adapter behavior only. `RUNTIME_PROBE.md` describes the separate verified blank-input runtime check; permitted-photo localization and actual case-pipeline evidence remain pending. Shared integration still requires root approval of this interface.

## Pending incident provenance handoff

make_pending_incident_evidence(proposal, request, review_actor_kind=...) in
incident_gate.py produces a frozen PendingIncidentEvidence for the root
owner to inspect. It checks case, image, authored request and local receipt
bindings. The accepted actor kinds are scripted_demo and
unverified_human; this owner module has no authenticated-operator mode.
rights_status_claim preserves the case manifest's own statement and is
not independent item-level rights verification. The result always has
adoption_status=pending, operational_eligible=false, and blockers for
root-verified casualty source bytes, authenticated review bound to the full
incident record, and root record construction. Synthetic examples carry an
additional training-only blocker. It is not a VerifiedSource, HumanReview,
accepted incident record, resource request, or dispatch instruction.

The illustrated geometric.svg/case-001.json demo emits this handoff in
incident_gate next to its scripted review trace. Its face box and cue are
authored controls; its medical transport need is fictional authored exercise
metadata. A no-face control retains that metadata while visual evidence
abstains. Root must use its trusted source and identity services to construct
a complete record and obtain authenticated human review before considering
EvidenceLog.append. This module provides no path to clear those gates.
