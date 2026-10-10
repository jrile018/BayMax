# Focused peer review of audit documents

Initial peer-pass scope (before first publication): `docs/reviews/README.md`, `STRUCTURE_AND_INTEGRATION.md`, `REQUIREMENTS_AND_JUDGE_EVIDENCE.md`, and the three pinned domain reports `routing_mc.md`, `hf_fire.md`, `maps_amd.md` on the review worktree. This checks the synthesis against those reports and the accepted mission boundary; it does not rerun source reviews. Maps' newer delta and the faces report are intentionally pending.

## Corrections before publication

1. **Remove numeric quality gates imported from the reviewer role.** `maps_amd.md`, final Verification and limits bullet, says “Coverage percentage above 80%, cyclomatic complexity below 10 ... checklist gates are unconfirmed.” Neither numeric threshold belongs to the accepted Knight26 task contract. The synthesis does not repeat them, but the linked report would make them appear project acceptance criteria. Remove the threshold/gate language. A factual note that this review did not measure coverage or complexity is sufficient if desired. `routing_mc.md` already removed those gates.

2. **Fix the mission diagram's execution order.** `STRUCTURE_AND_INTEGRATION.md` currently draws `Atomic dispatch and conserved ledger` → `Routing and trip executor`. PR 8's `TripExecutor.dispatch` requires a feasible, interval-validated route before the ledger commit (`routing_mc.md`, Public boundary). A reader could infer that allocation commits before route feasibility is known. Draw known state → route candidate/interval validation → atomic dispatch/ledger commit → trip movement/events. Keep route search and trip execution distinct even if they share the routing owner.

3. **Name the HF repro as a proposed command at the point of the claim.** `README.md`'s HF1 row says the report “emits a new10-bottle need after scripted acceptance.” The pinned `hf_fire.md` is narrower: scripted `ReviewStore.review` emits `propose_need(...)`; there was no authenticated human acceptance, durable command consumption, or simulator mutation. Change the table consequence to “emits a proposed 10-bottle need command after scripted acceptance.” The following sentence already explains the limit; matching the row wording prevents skimmers from reading it as an applied ledger effect.

## Consistency checked

- The index distinguishes human reading order from dependency integration order. The dependency list starts with root executable contracts and actual ledger, then attaches geography/hazard/intake and moves to views and conditional evaluation.
- The reports and synthesis consistently identify MC's hand-authored mock adapter, absent real routing ledger, incomplete executable integration, and the confirmed servicing-state and exact-exit repros. Existing passing fixture tests are not presented as an end-to-end pass.
- The shared authoritative snapshot hash versus per-view hash, metric CRS versus WGS84 origin, and known observations versus hidden evaluator truth are stated consistently as integration invariants. The Maps→3D CRS rejection and HF source/issue-time gap are identified as unresolved.
- Product ROCm, genuine FSR4 frames, real HF inference, physical wildfire calibration, source-specific AOIs, learner benefit and community impact remain labeled as unresolved evidence gates. The organizer/judge matrix distinguishes current fit from proof still needed.

## Publication resolution

The primary reviewer corrected the diagram and proposed-command wording, and the domain reviewer removed invented numerical gates before publication. Latest Maps cf5251 and faces4bef reports were subsequently reviewed with exact logs by the primary reviewer; this peer pass did not independently re-review those later source deltas.

## Later publication consistency pass

The maps/AMD reviewer read the three synthesis documents after initial publication and identified stale face/routing pins, a renderer-existence overstatement, initial-six-head scope wording, a Gainesville implemented-versus-planned ambiguity, and missing visible OSM source-date proof. The primary reviewer corrected these synthesis claims. Routing's changed scope is independently reviewed at6ca28e2 and resolves the historical missing-ledger finding; other concrete MC and shared-restoration gates remain. This pass did not add numeric coverage/complexity requirements or certify later source heads.

Casualty changed-scope source at4ebda08 independently passed47 tests. Its broker is byte-identical to historical4befc43, and the same request ID still produces distinct per-case command keys; FACE1 stays open as an integration deduplication condition. The additional rights/count/box regression fixes are present, without actual photo/model/authentication proof.

Final intake delta a28b890 was independently source-reviewed and tested:71 CPU checks pass; three earlier semantic/evidence probes still reproduce. The optional revision precondition adds a MED caller guard, qualified as scripted acceptance without proof of an actual UI race or human approval. Corrected current-head command line references and cloud-only clone wording were checked. Automatic approval review initially blocked the revised report transfer; after the human instructed publication to main, a same-route exact-payload transfer was reviewed and allowed. The cloud file SHA256 matches33d59cf249071c77edba497dc06acfeedcb0dd9f9b4336167fa299d05816ca09.
