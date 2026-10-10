#!/bin/bash
cd /workspace/knight26/worktrees/amd || exit 90
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
cpus=$(/opt/venv/bin/python -c 'import os; print(",".join(str(c) for c in sorted(os.sched_getaffinity(0))[:2]))')
printf 'COMMAND: taskset -c %s /opt/venv/bin/python -m pytest -q platform/tests\n' "$cpus"
taskset -c "$cpus" /opt/venv/bin/python -m pytest -q platform/tests
result=$?
printf '\nEXIT_CODE:%s\n' "$result"
exit "$result"
