# Independent exact-head review

Review date: 2026-10-10. Reviewer configuration: **GPT-6.1-Sol, high**, dispatched by the authorized coordinator for the mandatory human review policy. Exact reviewed head: **`02ebdc4b4a58f706564c6a56cb2eddf7958dde48`**, branch `codex/hf`, approved cloud worktree `/workspace/knight26/worktrees/hf`. Recorded tested source: `a2a9f70a5b66479d1cad1c9d3d9432034999dd65`.

**Result: changes required. One new HIGH archive privacy/schema bypass remains at this head.** The existing suite passes, but does not cover this bypass. This report supersedes prior narrow pass statements only for the issue below; it does not approve live transfer, AI performance, or the integrated simulator.

## Findings

### HIGH — Duplicate JSON keys hide free text while exact raw bytes are archived

Location: `services/artifact_store/__init__.py:105-114`, especially the ordinary `json.loads` calls at lines 111 and 113. Affected paths include `build_pack`, `verify_pack`, mock transfer, and verified retrieval.

Python's default JSON decoder keeps the last occurrence of a repeated key. The closed schema therefore sees only the final numeric object, while `_structured` hashes the original bytes and `build_pack` copies those bytes unchanged. This artifact is accepted:

```json
{"schema":"knight26.aggregate.v1","metrics":{"notes":"SYNTHETIC PERSON at SYNTHETIC ADDRESS; RAW REPORT CONTENT"},"metrics":{"score":1}}
```

At the exact reviewed head, an independent CPU-only probe created normal typed config/snapshot files, replaced `metrics.json` with the string above, computed normal metadata, and called `build_pack`, `verify_pack`, `upload_pack` against the existing in-memory `MockBucket`, then `fetch_pack`. Result:

```json
{"status":"verified","hidden_content_in_mock_remote":true,"hidden_content_in_verified_retrieval":true,"live_network_calls":0}
```

The bypass also applies to repeated nested keys and individual JSONL objects, so rejecting only top-level duplicates is insufficient. This violates the advertised rejection of freeform text independently of the separately disclosed caller attestation/de-identification limits. A real backend would receive the same unchecked raw bytes; no live backend was invoked in this review.

**Required change:** reject duplicate keys at every object level through a shared strict JSON loader (`object_pairs_hook`), before accepting/copying any artifact bytes. Apply it consistently to JSON, every JSONL row, and manifest parsing. Add regressions for overwritten top-level and nested fields across aggregate/config/event files and retrieved packs; reject before any upload. Preserve the explicit caller-attestation limits after fixing this syntactic bypass. Refresh source fingerprints/evidence and obtain a new exact-head review.

### LOW — Current intake README still claims no dependency installation

`services/intake/README.md`, the paragraph beginning “Upstream references,” says: “Planned isolated dependency target preserves image ROCm Torch; no dependency installation has run yet.” That unqualified present-status statement conflicts with the current preparation evidence and separately installed artifact SDK. The preceding C1 statements are explicitly historical, but this installation statement is not. Replace it with current, scoped preparation status or mark it as historical C1 context. The local publication draft `handoff/hf/pr-body.md` describes the current preparation accurately.

## Independently verified evidence

- All **22** paths in `evals/intake/artifacts/c2-followup/source.json` matched their SHA-256 values and the actual bytes at both `a2a9f70...` and `02ebdc4...`. Recomputed current intake provenance was `source_dirty=false`, fingerprint `021af8124cfb51fc32d5b5ec8d11cfe8eb4bca5abf7fd73ed5ba54119df7a3ef`.
- All **41** manifested files verified: artifact C2 preparation 23, intake C1 3, intake C2 preparation 7, and intake C2 follow-up 8. Both array and historical mapping manifest formats were checked; recorded lengths were checked where provided.
- Fresh cloud component suite: **107 passed, 18 subtests passed**, exit 0, 0.51 seconds. Exact command:

```sh
cd /workspace/knight26/worktrees/hf
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  /opt/venv/bin/python -m pytest services/intake/tests evals/intake/tests evals/artifact_store -q -p no:cacheprovider
```

- Fresh in-memory evaluator outputs equalled the committed complete system objects, including failures and all metrics. Baseline: **5/20 label/slot/flag exact, 2/20 reference-span aligned, 15 retained failures**. Fixture control: **20/20** on each measure, harness control only. Historical C1 7/20 is not a current result. Source-quote fidelity, reference alignment, and slot equality remain distinct metrics.
- Reviewed the previous HF1 delivery-count, HF2 qualified/coreferential access, HF3 reference-span, batch fatal-budget/checkpoint, and Qwen temporary/partial-load cleanup changes and their passing regressions. These support the covered lexical/mock paths, not universal semantic understanding or actual GPU behavior. A focused attempted idempotent-return mutation did **not** alter stored accepted command data: `get` already returns a deep copy; no finding was raised for that path.
- Reverified all six isolated artifact wheel files against recorded SHA-256 values. With `PYTHONPATH=/workspace/knight26/deps/hf-buckets`, all six modules imported from that isolated target. Independently evaluated all **15** active installed `Requires-Dist` constraints successfully. Actual SDK signatures bound the adapter's `bucket_info`, `list_bucket_tree`, `batch_bucket_files(add=...)`, `download_bucket_files(files=...)`, and `get_token` argument shapes without invoking those functions. Torch was not imported. This is offline metadata/import/call-shape compatibility, not a live auth/quota/transfer result.
- The committed synthetic offline v2 demo pack passed `verify_pack` independently. The cloud Qwen snapshot directory under `/workspace/knight26/cache/huggingface/models--Qwen--Qwen3-4B` contained no files. The reviewed source keeps model loads local-only and disables remote model code. The controller's 12-file model-hash record is manifested evidence; this reviewer did not rehash the controller's 8,044,982,000 weight bytes.
- The trace explicitly labels human calls as scripted demonstrations and reports `simulator_mutation=false`. It returns proposals for root integration; it is not evidence of actual human approval or authoritative state application.

All cloud reads/checks used PowerShell here-strings piped through `ssh -F handoff/ssh/config knight26-cloud "tr -d '\r' | bash"` with the approved escalation. Meaningful Python checks used two CPU threads and `PYTHONDONTWRITEBYTECODE=1`. An initial standalone verifier assumed only the newer array manifest shape and stopped before the probe; it was corrected to verify historical mapping formats. An initial test invocation with `/usr/local/bin/python3` had no pytest; the successful fresh suite used the recorded `/opt/venv/bin/python`. Existing untracked `__pycache__` directories predated these checks and were left untouched. No source edit, installation, stage, commit, model load, GPU action, auth function call, live Bucket action, credentials inspection, or network-policy change was made.

## Publication and adoption scope

Read the full local `handoff/hf/pr-body.md` and `MODALITY_OPTIONS.md`. The publication draft accurately distinguishes offline preparation, synthetic/mock results, caller privacy attestation, revision syntax from actual repository resolution, point-in-time mutable Bucket integrity, and root-owned reviewer authentication/revision/aliases/persistence/atomic application. Its archive shape guarantee must not be approved until the HIGH finding is fixed.

Checked public primary sources, without downloading model weights:

- [Pinned Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B/blob/1cfa9a7208912126459214e8b04321603b3df60c/README.md) and [pinned license](https://huggingface.co/Qwen/Qwen3-4B/blob/1cfa9a7208912126459214e8b04321603b3df60c/LICENSE): the reference exists, Apache-2.0 metadata agrees, and the documented Transformers interface/version floor supports the proposed adoption shape. This is not local inference proof.
- [Official Bucket guide](https://huggingface.co/docs/huggingface_hub/guides/buckets): mutable storage and the adapter's documented API families agree. No account storage availability or runtime transfer is inferred from that guide.
- [Pinned Whisper tiny.en tree](https://huggingface.co/openai/whisper-tiny.en/tree/87c7102498dcde7456f24cfd30239ca606ed9063), [smolagents 1.26.0 metadata](https://pypi.org/project/smolagents/1.26.0/), [YuNet card](https://huggingface.co/opencv/face_detection_yunet), and [Florence-2 card](https://huggingface.co/microsoft/Florence-2-base-ft): research-note metadata and capability framing agree with those primary pages. Whisper's displayed 151 MB is checkpoint size, not measured latency/memory/accuracy; smolagents is proposal-layer research; YuNet face boxes and Florence suggestions are not injury/identity/triage evidence. Florence's remote-code quickstart is disclosed as an unresolved adoption gate. No extra model/framework was installed or executed.

No claim of >80% measured code coverage, cyclomatic complexity <10, a comprehensive dependency vulnerability scan, actual ROCm resource release, AI effectiveness, real incident truth, guaranteed de-identification, complete replay/restoration, live private Bucket service, quota/egress, or an integrated mission pass is established by this review. Final gate at `02ebdc4...`: **HIGH finding open; do not publish a clean-review claim for this head.**
