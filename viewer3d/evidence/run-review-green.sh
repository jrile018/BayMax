#!/bin/bash
cd /workspace/knight26/worktrees/amd
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1
CPUS=$(/opt/venv/bin/python -c 'import os; print(",".join(map(str, sorted(os.sched_getaffinity(0))[:2])))')
printf "COMMAND: taskset -c %s /opt/venv/bin/python -m pytest viewer3d/tests -q -p no:cacheprovider -k 'route_record_in_plain or horizontal'\n" "$CPUS" > viewer3d/evidence/review-green.log
printf 'ENV: OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1\n' >> viewer3d/evidence/review-green.log
date -u '+STARTED_AT:%Y-%m-%dT%H:%M:%SZ' >> viewer3d/evidence/review-green.log
taskset -c "$CPUS" /opt/venv/bin/python -m pytest viewer3d/tests -q -p no:cacheprovider -k 'route_record_in_plain or horizontal' >> viewer3d/evidence/review-green.log 2>&1
status=$?
printf '\nEXIT_CODE:%s\n' "$status" >> viewer3d/evidence/review-green.log
