#!/bin/bash
cd /workspace/knight26/worktrees/amd
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1
log=viewer3d/evidence/native-prep-review-red.log
printf 'COMMAND: taskset -c 0,1 /opt/venv/bin/python -m pytest viewer3d/tests/test_render.py::test_camera_rejects_finite_bounds_that_overflow_derived_projection viewer3d/tests/test_render.py::test_sidecar_associates_each_primitive_with_its_exact_source -q -p no:cacheprovider\nCPU_ONLY: fake graphics contexts only\n' > "$log"
date -u '+STARTED_AT:%Y-%m-%dT%H:%M:%SZ' >> "$log"
taskset -c 0,1 /opt/venv/bin/python -m pytest viewer3d/tests/test_render.py::test_camera_rejects_finite_bounds_that_overflow_derived_projection viewer3d/tests/test_render.py::test_sidecar_associates_each_primitive_with_its_exact_source -q -p no:cacheprovider >> "$log" 2>&1
printf '\nEXIT_CODE:%s\n' "$?" >> "$log"
