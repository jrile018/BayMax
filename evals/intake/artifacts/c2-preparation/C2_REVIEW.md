# C2 focused review

Status: **all focused findings closed** (see final follow-up). This was a read-only review of the cloud worktree; no model, GPU, dependency, or download action was run.

## Blocking finding

- **HIGH — Stop a real run after a GPU budget violation.** `services/intake/qwen.py:95` raises `RuntimeError('inference exceeded assigned 14GiB VRAM budget')` after generation, but `services/intake/batch.py:173-186` catches every `Exception`, records one failed case, and proceeds to the next report using the same loaded provider. Thus a run can keep invoking the model after it has exceeded its assigned resource limit and end with top-level `status: completed`. Treat a GPU budget breach (and other fatal GPU resource failures, if classified) as a run-level failure: checkpoint the case and run error, stop iteration, and close the provider in `finally`. Continue only for ordinary per-report extraction or schema failures. A CPU injected provider that raises the same budget exception on the first case and counts later `extract` calls would expose this behavior without GPU use.

## Earlier findings now closed

- **Source provenance:** `batch.py:36-80,112-120` records a SHA-256 fingerprint of exact Python source bytes plus a dirty flag. `batch.py:219-220` blocks the real-model CLI while owned Python source differs from Git HEAD, including untracked Python files. The manifest still records `source_sha`, but now explicitly distinguishes an uncommitted direct/injected batch run. The source fingerprint and dirty-gate tests cover this behavior.
- **Rejected return value:** `batch.py:167-175` saves `returned_payload` before validation, while leaving the evaluator-facing `payload` null on failure. `test_batch.py:63-65` checks this.
- **Exact fixture bytes on load failure:** `batch.py:221-237` records `fixture_file_sha256` in both load-failure and successful-run provider metadata; `test_batch.py:121-148` checks the load-failure branch.
- **Partial Qwen load cleanup:** `qwen.py:61-78,98-111` assigns the model to `self.model` before GPU transfer, clears model and tokenizer references on errors, and keeps the original exception if cache cleanup fails. `test_qwen.py:74-133` uses a fake runtime and weak references to verify transfer-error and cleanup paths. This establishes Python reference cleanup for the tested paths, not actual ROCm memory release.

## Smaller limitation

- `batch.py:168,186` places an arbitrary provider return value into `returned_payload` before JSON checkpointing. An invalid, non-JSON-serializable return value (for example, a `set`) causes the checkpoint to fail, so the intended per-case failure cannot be saved and later cases do not run. The real Qwen decoder returns JSON-compatible values, so this affects the general `run_batch` interface rather than the pinned Qwen path. Normalize or safely represent rejected non-JSON values if the generic provider contract is retained.

Reviewed source and focused tests; I did not rerun tests. The parent reported 9 batch and 54 intake focused tests passing and is responsible for the full-suite gate.

## Final fatal-path follow-up

Status update: **the blocking finding is closed; no remaining blocker found in this focused review**. The earlier sections record the findings at the time of the prior pass.

- `services/intake/qwen.py:8-9,78-82,90-109` now uses `ResourceBudgetError` for the model-load and inference 14 GiB cap. Torch OOM from input transfer, generation, or synchronization is translated to that error. `finally` clears temporary `inputs`, `out`, and `suffix` references. The mock tests at `test_qwen.py:136-267` cover the cap, both Torch OOM locations, transfer/synchronization, and temporary-reference release; no actual GPU behavior was tested.
- `services/intake/batch.py:188-221` checkpoints the current failed case and its raw metadata, re-raises `ResourceBudgetError`, writes top-level `status: failed` and `run_error`, leaves later reports pending, then calls `provider.close()`. `test_batch.py:251-294` checks this with an injected provider. Ordinary case failures still continue.
- The earlier non-JSON return-value limitation is closed by bounded diagnostic conversion at `batch.py:114-124,182-184`; `test_batch.py:297-319` checks that a rejected non-JSON return remains checkpointable.

I reviewed these final changes without rerunning tests, model loading, or GPU work. The parent reported 11 mock Qwen and 11 batch tests passing and owns the full-suite gate and commit.
