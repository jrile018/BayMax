#!/bin/bash
cd /workspace/knight26/worktrees/amd
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1
CPUS=$(/opt/venv/bin/python -c 'import os; print(",".join(map(str, sorted(os.sched_getaffinity(0))[:2])))')
printf 'COMMAND: taskset -c %s /opt/venv/bin/python -m pytest viewer3d/tests -q -p no:cacheprovider\n' "$CPUS" > viewer3d/evidence/review-red.log
printf 'ENV: OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1\n' >> viewer3d/evidence/review-red.log
taskset -c "$CPUS" /opt/venv/bin/python -m pytest viewer3d/tests -q -p no:cacheprovider >> viewer3d/evidence/review-red.log 2>&1
status=$?
printf '\nEXIT_CODE:%s\n' "$status" >> viewer3d/evidence/review-red.log
