# AMD C1 server continuation

Branch codex/amd; source baseline fe83b4bab024aa81fe06687ac1f502433f3c8ea7. Actual checkpoint source SHA, logs/hashes and external review links are recorded after commit in owned ignored artifact platform/evidence/CHECKPOINT.json. Local owner handoff contains the same exact SHA.

C1 ready for review: actual current-image prerequisite JSON and genuine FSR4 experiment plan; internal CPU scene projection reviewed. Discussion: https://github.com/jrile018/knight26/discussions/6. C2/C3 pending. No shared transport schema changed. No GPU contexts, renderer output, ML dispatch or performance results in this checkpoint.

APIs: graphics_probe.probe()->dict returns inventory/prerequisite blocked-or-unverified, FSR4 not_executed; graphics_probe.command(list[str])->dict preserves command result/errors/partial timeout output. viewer3d.build_scene(SceneInput, SceneLimits)->PreparedScene validates internal typed geometry, exact frame identity, metre declaration, provenance, primitive categories and civilian unit kinds; preserves exact positions/trails/route versions. Root shared JSON adapter remains pending; declarations are not audited CRS/license facts.

Tests: taskset -c0,1 /opt/venv/bin/python -m pytest -q -p no:cacheprovider, with OMP/OPENBLAS/MKL_NUM_THREADS=2 and PYTHONDONTWRITEBYTECODE=1, detached tmux. Combined53passed in0.08s,exit0; platform/evidence/checkpoint-tests.log. Diagnostic red2failed->green2passed. Scene initial38failed->38passed; boundary3failed->green; review7failed/44passed->focused7passed->final51passed. Synthetic scene inputs, actual CPU code execution. Read-only diagnostic is actual image evidence, not a mock graphics result.

Review fixes: partial timeout output preservation; SDK API compatibility descriptor/temporal input contract; minimal provider experiment independent from replay renderer; strict layer classes prevent route metadata loss; explicit metre declarations required. No remaining important issues found by independent review. No active AMD tmux at completion; root-owned unrelated sessions are untouched.

Resource request: after HF releases GPU, root to grant10–15min allocated-device graphics capability/offscreen test slot following isolated userspace prerequisite preparation. No SDK/UE/runtime download or driver/Torch change yet. W7900 FSR4 support, Linux translation, usable graphics context and distinguishable ML trace are separate unresolved gates. See evals/fsr4/EXPERIMENT_PLAN.md.

Next: root review/contract adapter, isolated graphics runtime preparation, then lease-controlled capability experiment. Genuine FSR4 must never be inferred from ROCm, sysfs, a version label or analytical output. No self-merge.
