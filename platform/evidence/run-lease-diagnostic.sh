#!/usr/bin/env bash
set -eu
cd /workspace/knight26/worktrees/amd
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1
/opt/venv/bin/python - <<'PY'
import datetime,time
start=datetime.datetime.fromisoformat('2026-10-10T07:00:00+00:00')
delay=(start-datetime.datetime.now(datetime.timezone.utc)).total_seconds()
if delay>0: time.sleep(min(delay,30))
PY
/opt/venv/bin/python platform/graphics_probe.py --output platform/evidence/graphics-lease-prerequisites-20261010.json
/opt/venv/bin/python - <<'PY'
import datetime,hashlib,json
from pathlib import Path
probe=Path('platform/evidence/graphics-lease-prerequisites-20261010.json'); report=json.loads(probe.read_text()); runtime=json.loads(Path('platform/evidence/native-runtime-packages.json').read_text())
assert report['graphics_prerequisite_gate']['status']=='blocked'
result={'schema':'knight26-amd-graphics-lease-result-v1','checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'coordinator_lease_start_utc':'2026-10-10T07:00:00Z','coordinator_lease_end_utc':'2026-10-10T07:20:00Z','lease_status':'released_unused_prerequisites_blocked','gpu_context_created':False,'gpu_work_executed':False,'gpu_vram_allocated_by_job_bytes':0,'native_render_status':'not_executed','fsr4_provider_status':'not_executed','fsr4_ml_dispatch_verified':False,'missing_prerequisites':report['graphics_prerequisite_gate']['missing_prerequisites'],'runtime_status':runtime['status'],'downloaded_package_count':runtime['downloaded_package_count'],'probe_sha256':hashlib.sha256(probe.read_bytes()).hexdigest(),'unblocking_boundary':'Graphics libraries/runtime packages must become available on the supplied cloud before a fresh lease can run a graphics context. Network/auth/provider changes remain coordinator-owned.'}
Path('platform/evidence/graphics-lease-result-20261010.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))
PY
