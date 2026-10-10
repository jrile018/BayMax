# Evidence-linked humanitarian intake

This module proposes needs/access observations for a **fictional preparedness exercise**. It does not geocode, dispatch, mutate the simulator, confirm current incidents, predict outcomes or verify whether a report is true. Exact source slices plus conservative semantic guards make review possible; a human must still check meaning and veracity.

## API and effect gate

`Report(report_id, source, received_time_s, text)` uses scenario seconds and preserves source text. `parse_proposal(report, payload, provider)` strictly validates `language`, `flags`, `claims`. A claim has an ID, `kind`, category/status `label`, exact `evidence` (`start`, `end`, `quote`, Unicode character offsets), explicit quantity+unit, urgency and literal location slots. Slots are null or `{value,evidence}`. Unknown fields/coordinates/confidence, wrong spans/types, unsupported category/status, inferred counts, approximate/range quantities, cross-clause quantities and unrelated locations fail closed. Conservative English/Spanish lexical guards are not universal semantic verification; only the English fictional fixture set is evaluated here.

`ReviewStore(aliases).submit(...)` creates pending records. `edit(proposal_id,payload,editor_id,expected_revision=...)` supports source-bound corrections while pending and records revision/editor. `review(proposal_id,'accepted'|'rejected',reviewer_id,expected_revision=...)` is terminal and idempotent for the same decision/reviewer. It emits commands only for accepted, unblocked, supported and independently mapped claims. Unknown/unmapped/conflicting/adversarial/negated/qualified claims do not automatically alter state. Exact normalized reposts are deduplicated within identical source and received time; distinct later observers remain reviewable. This is a limited repost rule, not cross-source entity/incident resolution.

Aliases contain exact literal mention -> `{entity_id,entity_type:'node'|'edge',source}`. Resolution records carry alias provenance; they establish a match in the supplied exercise graph, not verified coordinates. Root must provision a trusted versioned graph manifest, authenticate actual human identity, serialize/persist store operations, and atomically apply command `idempotency_key` at the simulator ledger/known-state boundary. An RLock serializes in-memory store operations and optional expected_revision rejects stale actions. Every external edit/review adapter must authenticate identity and require a concrete inspected revision; this core is not a persistent network service.

Commands are `propose_need` (category, quantity, unit, urgency) or `propose_access_observation` (status), with report/source/received time, reviewer, revision/editors, complete claim evidence, mapped entity and idempotency key. Repeated retrieval returns the same command; downstream exactly-once application is required. No automatic dismissal/acceptance based on model score.

## Providers and evidence

`FixtureProvider` is explicitly `mocked_model_fixture`; it returns authored gold data to exercise the harness. Its score is **harness coverage, not AI accuracy**. `RuleBaseline` is a frozen, narrow English pattern baseline. The twenty authored fictional development/evaluation reports and Dataset Card are under `fixtures/reports/`; never represent them as real incident reports.

`QwenProvider` requires an immutable revision, cached official `Qwen/Qwen3-4B`, real ROCm GPU, no CPU fallback and no remote model code. Model quotes are converted into unique exact offsets deterministically. Official pinned model bytes are verified on the controller only. Read-only cloud residency checks find no model files, and no load/inference has run. The model dependency target is installed, while cloud byte ingress and a fresh exclusive GPU lease remain gates; a CPU fixture is never substituted as Qwen output.

Upstream references: [Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B) (Apache-2.0; Transformers >=4.51), [official Qwen3 Transformers docs](https://huggingface.co/docs/transformers/v4.57.1/model_doc/qwen3), [Transformers 4.57.6](https://pypi.org/project/transformers/4.57.6/). The isolated model target `/workspace/knight26/deps/hf` has Transformers4.57.6/Hub0.36.2 and verified dependencies. The separate artifact-only target `/workspace/knight26/deps/hf-buckets` has Hub2.2.0 and its verified dependencies; it must run in a separate process. Offline imports/call bindings preserve supplied ROCm Torch. Neither target establishes model inference or live Bucket access. Preparation and current audit evidence are under `evals/intake/artifacts/c2-preparation/`, `evals/intake/artifacts/c2-followup/` and `evals/artifact_store/artifacts/c2-preparation/`.

## Cloud validation

Run on supplied Radeon Cloud from `/workspace/knight26/worktrees/hf`, initial CPU cap two threads, detached tmux with logs:

```sh
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /opt/venv/bin/python -m pytest services/intake/tests evals/intake/tests -q
/opt/venv/bin/python -m evals.intake.run --output /workspace/knight26/artifacts/hf/cpu-evaluation.json
/opt/venv/bin/python -m services.intake.demo --output /workspace/knight26/artifacts/hf/review-trace.json
```

The development trace labels its accept/edit/reject calls as scripted demonstrations, not actual human approvals. It emits one pending need command after a scripted correction, shows rejection and repost suppression, and never changes simulator state. C2 must connect an actually human-reviewed real-model output to root's tracked route/ledger. C3 must measure model latency/VRAM and preserve all failures on the declared evaluation set. No optional model or model-confidence safety claim belongs to C1.
