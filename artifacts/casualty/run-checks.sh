#!/usr/bin/env bash
set -eu
cd /workspace/knight26/worktrees/faces
printf 'TESTED_HEAD:'
git rev-parse HEAD
/opt/venv/bin/python --version
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /opt/venv/bin/python -m pytest -q
/opt/venv/bin/python -m services.casualty.demo --output artifacts/casualty/c1-trace.json
printf 'EXIT_CODE:0\n'
