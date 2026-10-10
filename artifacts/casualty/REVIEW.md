# C1 independent review

Reviewer: fresh code-reviewer GPT6.1-sol, read-only review of cloud-created source diff, seed `fe83b4bab024aa81fe06687ac1f502433f3c8ea7` → source `4befc43a655aeeaaaf19dfbad9d4dfc87fd4e024`. Evidence diff SHA256 `f6b69b43a17ca9aa207b41506f5060aacb6f8c02e2f2a1ae109f2ca763ea6db7`.

No Critical/Important broker findings. Reviewer checked case/image/rights/need binding, conflicting terminal decisions, forged receipts, stable need keys, preservation of medical need during visual abstention and absence of clinical/identity claims. Review was source-only, not an independent product test run.

Three findings initially graded Minor were regraded Important by owner because each affects a promised permission/valid-input/evaluation boundary:

1. Demo evaluated its fixture without the separate `evaluation` permission. `test_demo_cannot_evaluate_without_evaluation_permission` failed first; `RightsManifest.require('evaluation')` now runs before the demo constructs results.
2. Manually constructed count records allowed negative/bool counts, NaN and impossible IoU sums. Five `test_impossible_counts_cannot_publish_misleading_metrics` cases failed first; counts now require nonnegative exact integers and finite IoU sums in `[0,TP]`.
3. Extremely small positive coordinates permitted a box with underflowed zero area, causing division by zero in IoU. `test_underflowing_box_area_is_rejected_before_evaluation` failed first; box area must now be positive and representable.

Cloud red proof `artifacts/casualty/red-review-fixes.log`: 7 failed/11 passed. Green suite `artifacts/casualty/green-review-fixes.log`: 47 passed, exit0. Fix source head recorded in HANDOFF after command output. No deferred reviewer findings remain.

Caller responsibilities remain explicit: actual rights verification; authenticating/persisting/serializing review; atomic downstream key use; trusted node resolution; actual image/model provenance. Actual model/photo/injury/shared mission/learner performance is unproved. Review approval of C1 code cannot close those evidence gates.
