#!/bin/bash
cd /workspace/knight26/worktrees/amd
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1
log=viewer3d/evidence/native-prep-final-green.log
printf 'COMMAND: taskset -c 0,1 /opt/venv/bin/python -m pytest viewer3d/tests -q -p no:cacheprovider\nCPU_ONLY: fake graphics contexts only\n' > "$log"
date -u '+STARTED_AT:%Y-%m-%dT%H:%M:%SZ' >> "$log"
taskset -c 0,1 /opt/venv/bin/python -m pytest viewer3d/tests -q -p no:cacheprovider >> "$log" 2>&1
printf '\nEXIT_CODE:%s\n' "$?" >> "$log"
