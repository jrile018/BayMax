# Knight26 independent review — [Review 00]

Verdict: the workstreams fit the accepted aid-coordinator training direction, but the reviewed changes are not ready to certify a complete integrated simulator. Keep the PRs draft. Concrete source defects remain in report-to-effect binding, geography/access provenance, conditional service restoration and rendered-output metadata. The actual main seed contains coordination documents only. No code was fixed, merged or approved by this reviewer.

The reviewer inspected the actual source/test diffs in isolated cloud archives, reconciled Discussions and PR bodies, and ran scoped short detached CPU checks on Radeon Cloud with a two-thread cap. Product work stayed on cloud. Reports are pinned; moving owner heads require changed-scope review. Original Discussion snapshots were captured around06:59UTC October10; PR10 and PR9 changed during review and their deltas are included. New face cloud source is independently reviewed; no face PR or owner Discussion was published at the07:16UTC capture.

## Read the PRs in this order

| Human order | Workstream Discussion | Draft PR | Actual reviewed SHA and scope |
|---|---|---|---|
|00|[Independent review14](https://github.com/jrile018/knight26/discussions/14)|This audit-documents PR|Review documents only; the audit commit is recorded in this PR, not a feature implementation.|
|00A|[Coordinator7](https://github.com/jrile018/knight26/discussions/7)|Coordinator documents PR forthcoming at initial snapshot|Existing shared index and seed contracts reviewed; executable integration remains absent.|
|01|[Maps1](https://github.com/jrile018/knight26/discussions/1)|[PR10](https://github.com/jrile018/knight26/pull/10)|`82ce6bbd348718dad95f787281e185bc2ddb8500` plus preview delta `ed96513ce35666b3e20b3e30ef0f9b611942cddf`; latest published sourced head `cf5251e6897152e30be8defbd129610b9db4e2bb` (GitHub rechecked07:16UTC)|
|02|[Wildfire5](https://github.com/jrile018/knight26/discussions/5)|[PR11](https://github.com/jrile018/knight26/pull/11)|`e0df46b21f0805d9c9bbdb94b46a66ee06cdb494`|
|03|[Routing4](https://github.com/jrile018/knight26/discussions/4)|[PR8](https://github.com/jrile018/knight26/pull/8)|`d763eb61bed8276a24cce769684f58501e68b581`|
|04|[HF intake2](https://github.com/jrile018/knight26/discussions/2)|[PR12](https://github.com/jrile018/knight26/pull/12)|`a62bbd61b776b666615d58a31dc0f1053066030f`|
|05|Faces owner post pending on initial capture|PR pending on initial capture|Actual committed cloud source `4befc43a655aeeaaaf19dfbad9d4dfc87fd4e024`; 40 CPU tests and scripted receipt/need-key review; no real photo/model|
|06|[Monte Carlo3](https://github.com/jrile018/knight26/discussions/3)|[PR13](https://github.com/jrile018/knight26/pull/13)|`2e5da5e85f14357853bed4147ff4ad3f05c3a5ec`|
|07|[AMD6](https://github.com/jrile018/knight26/discussions/6)|[PR9](https://github.com/jrile018/knight26/pull/9)|`74ffaac3a7a7a850b8f5a9232a9dcb386556ffd6` plus native preparation delta `986bb303044118dde7062ce01487ceeeb606edf4`|

Main/base on reviewed source: `fe83b4bab024aa81fe06687ac1f502433f3c8ea7`. All six initial owner PRs were open/draft and had substantive diffs; source heads matched canonical cloud refs. A seed branch alone would not have counted as a feature PR. This human reading order is distinct from dependency integration order.

## Concrete fixes before integrated claims

| ID / severity | Evidence and consequence | Fix owner / review condition |
|---|---|---|
|HF1 HIGH|PR12 `schema.py:151-165`, `review.py:72-86`: `10 bottles were delivered to Pine School. Water is needed at Pine School.` with whole-report claim evidence emits a proposed10-bottle need command after scripted acceptance. The completed delivery's quantity is borrowed by another statement.|HF: bind claim/quantity/unit/location to a supported request clause; retain exact field evidence and completed-event adversarial cases. This repro is a proposed command, not actual human approval or simulator mutation.|
|HF2 HIGH|PR12 `schema.py:120-125,174-179`, `review.py:77-86`: `Highway A is open to bicycles only.` emits unscoped `status=open`. Vehicle qualification is lost.|HF: preserve reviewed allowed modes/time qualifications or abstain; coordinator must not apply unscoped open to every vehicle.|
|MC1 HIGH|PR13 `mock_world.py:32,273-274`: branching a known `phase=servicing` bus drops completion state and `advance_to(25)` raises `KeyError 'committed-bus'`. Every seed can fail from that valid checkpoint.|MC: serialize/restore service end or elapsed service and reservations; test service-in-progress branching and exactly-once terminal service.|
|GEO1 HIGH|Reviewed Maps `ingest` accepts nodes near0,0 and writes Paradise California label/graph despite fixed Paradise bounds.|Maps: validate AOI/source/coordinates, preserve exact actual area provenance, reject outside/mismatched source. Root byte-ingress alone does not close this.|
|GEO2 MED|Maps importer turns `access=destination` into unrestricted open edges; explicit blanket restrictions erase mode overrides. A route may transit a destination-only road or falsely report no bus access.|Maps: preserve restricted purposes/unknown conditions and resolve tag hierarchy under explicit vehicle policy. OSM bus permission is public-transit/context-dependent; do not grant every rescue bus that exemption.|
|MC2 MED|PR13 `mock_world.py:219` counts closure at exact exit32 as an occupied-edge encounter; result strands at100% progress with zero safe arrivals. Routing uses half-open traversal intervals.|MC/routing: share `[entry,exit)` convention and independently check later edge entry.|
|HF3 MED|PR12 evaluator ignores evidence spans in exact-report signature and accepts a whole-report quote as supported evidence; expanded WF01 quote still scores exact/evidence success.|HF: measure claim/field evidence alignment separately from schema and literal quote matching. Keep mock control as harness coverage.|
|FACE1 MED|Face `broker.py:96-107,151-159`: two scripted accepted cases with the same authored request ID emit distinct idempotency keys; deduplication on the command key alone can duplicate a need at integration.|Faces/coordinator: enforce stable authoritative request identity and atomic request-level dedupe while preserving case/receipt hashes. No actual state mutation occurred.|
|AMD1 MED|New `render.py:343-352`: failed EGL render for new frame leaves prior PNG bytes but overwrites sidecar with failed/new snapshot metadata, breaking image/hash pairing.|AMD: use unique output/atomic paired publication or preserve prior metadata on failed attempt; regression must check successful image plus metadata stay paired.|

Full exact source references, payloads, log paths and limits are in [routing/MC](routing_mc.md), [HF/wildfire](hf_fire.md), [maps/AMD](maps_amd.md) and [faces](faces.md) reports. The renderer's coincident line depth visibility concern is source-inferred and must be separately identified from the reproduced metadata failure; no actual GPU pixel output was obtained by this review.

Road-tag semantics were checked against primary OSM documentation: [access hierarchy](https://wiki.openstreetmap.org/wiki/Key:access), [destination restrictions](https://wiki.openstreetmap.org/wiki/Tag:access=destination), [bus scope](https://wiki.openstreetmap.org/wiki/Key:bus). Treat these as map-tag interpretation evidence, not a legal clearance or real-road safety guarantee.

## Shared structure and readiness

The components currently use different envelopes. MC is a hand-authored mock routing/ledger world; the real routing ledger is absent from published PR8; Maps hashes its normalized frame under the name `snapshot_hash`; the generated geography CRS declaration is rejected by the AMD validator. Authentic human review persistence/identity/alias versioning and atomic command consumption remain root integration work. Dashboard POST is405; it serves stored mock frames. Native graphics preparation has no rendered runtime proof. Existing saved-preview screenshots were inspected by the reviewer: they visibly label saved mock playback, constructed routes and no road data at their earlier snapshot; they do not certify the later real-AOI view or live actions.

Use [structure and integration](STRUCTURE_AND_INTEGRATION.md) for ownership, actual public shapes, adapters, dependency graph and ordered acceptance work. Coordinator freezes executable contracts and one authoritative state/clock/event/ledger boundary. Routing completes actual conserved service. Geography/hazard and reviewed report/case adapters attach to that mission; views preserve the same authoritative snapshot hash plus separate normalized view hashes. MC restores that same state and preserves every active phase, visible history and commitment.

The source reports reproduce defects despite passing existing tests. Tests validate scoped CPU components, not model quality, physical fire calibration, graphical frames or community benefit. The [evidence manifest](../../artifacts/review/publication/manifest.json) and selected logs record exact source SHAs, commands/results and content hashes. There is no whole-application passing-test claim.

## Discussion and claim reconciliation

Owner Discussions largely disclose their partial/mocked state accurately. Routing says C1 in progress and no real-ledger proof; Maps originally said mock replay and unverified browser/AOI; later saved-preview evidence and a source-hashed cloud AOI were separately added; HF says fixture control/no actual Qwen; wildfire says explicit training fallback/no physical reference; MC says MOCK routing/ledger; AMD says no genuine FSR4 execution. Their C1 labels are review checkpoints, not a complete product. Keep those labels through integration.

Coordinator Discussion7 and several shared handoff/status paragraphs are stale at capture: they still list PRs pending, older test counts and earlier empty-repo/SSH status. The reviewer index above uses actual heads. Root should maintain one dated manifest with exact Discussion/PR/tested-head links, annotate historical status, and incorporate the newer local pilot decision. Do not convert unpublished dirty working-tree changes into published-head evidence.

## Per-judge proof

[Accepted requirements and judge evidence](REQUIREMENTS_AND_JUDGE_EVIDENCE.md) maps every accepted feature and retrieved judging criterion to actual evidence and a remaining proof. The shared mission should drive the route/tracking showcase, real reviewed HF inference, a source-specific local learner test, and measured AMD product runtime. The local pilot is Gainesville heavy-rain/flood access/shelter training; global wildfire remains accepted. No hydrodynamics, diagnosis, real-world calibrated probability, global optimum or real community impact is established.

Meaningful ROCm and genuine same-server FSR4 remain separate user requirements. Basic tensor smoke, CPU projection/renderer preparation and provider labels cannot substitute for actual product inference/scoring or genuine ML upscaler frames. Google composition, model/physical-reference ingress, AOI validation, live browser actions, real case imagery/model, genuine rendering, measured learner evidence and public release/video remain honest unresolved gates.

## Re-review rule

A finding closes only with a changed exact head, a regression on its concrete example, and preserved related invariants. Update the same owner Discussion and PR with tested SHA/results; integration also needs one commit-pinned dispatch-to-service mission and matching views. Reviewer reports and own draft PR contain review documents/evidence only; no worker edits, self-approval or merge occurred.

## Review publication cutoff

GitHub capture07:16UTC October10 matched reviewed published heads: PR8d763eb6, PR9986bb3, PR10cf5251, PR11e0df46b, PR12a62bbd6, PR132e5da5e. Faces4befc43 is reviewed cloud source with no PR at capture; coordinator00A PR is forthcoming. Later updates require changed-scope continuation. Selected logs and the manifest are review evidence only; archived product trees are intentionally excluded from this audit PR. All three audit peer-review corrections were addressed before publication.
