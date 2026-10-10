# Intake audit proof (HF1/HF2/HF3)

Worktree: `/workspace/knight26/worktrees/hf`. Source edits are limited to `services/intake/schema.py` and `evals/intake/run.py`; new regressions are `services/intake/tests/test_intake_audit.py` and `evals/intake/tests/test_evidence_alignment.py`. No files were staged or committed by the intake worker.

## Retained logs

- `intake-audit-red.log`: focused intake test after adding the reviewer's conjunction and next-sentence coreference cases, before their guards were implemented. Result: **3 failed, 10 passed**. Both `, but` and ` and` completed-delivery count transfers passed validation when they should have raised; `Highway A is open. Only bicycles may use it.` lacked `qualified_access`. This red log was created with stdout/stderr redirected to disk. The shell wrapper's attempted exit propagation had a quoting error after the pytest output; the pytest summary itself is retained in the log.
- `intake-audit-green.log`: `PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /opt/venv/bin/python -m pytest services/intake/tests evals/intake/tests -q`; **86 passed in 0.46s** after the guards.
- `intake-audit-combined.log`: same CPU environment, `/opt/venv/bin/python -m pytest services/intake/tests evals/intake/tests evals/artifact_store -q`; **106 passed, 18 subtests passed in 0.49s** after the guards.

The preexisting `precommit-checks.log` records a parent's earlier combined **99 passed, 13 subtests passed** and a 20/20 fixture evaluation. It predates the new reviewer regressions and should not be presented as the latest source validation.

## Earlier failing-first results observed in tool output only

These initial red results were not redirected to persistent files:

- The original HF1/HF2 audit regression run: **5 failed, 2 passed**. The completed-delivery count passed unexpectedly, and four qualified-open cases lacked `qualified_access`.
- A trailing-period completed-delivery case passed unexpectedly before the need context boundary was fixed: **1 failed**.
- An unrelated next-sentence vehicle mention falsely scoped an open road before the access context boundary was fixed: **1 failed**.
- The two HF3 evidence-alignment regressions raised `KeyError: 'evidence_span_alignment'` before the metric was added: **2 failed**.

The final HF3 metric compares each matched claim and slot evidence span with the authored reference. It preserves `exact_report` as a comparable label/slot/flag metric, and reports `evidence_span_alignment` and `evidence_aligned_report` separately. Exact span agreement is a strict reference measure, so a semantically equivalent alternative quote can score lower.
