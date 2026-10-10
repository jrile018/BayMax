#!/usr/bin/env bash
set -eu
cd /workspace/knight26/worktrees/amd
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1
taskset -c 0,1 /opt/venv/bin/python -m pytest platform/tests viewer3d/tests -q -p no:cacheprovider
