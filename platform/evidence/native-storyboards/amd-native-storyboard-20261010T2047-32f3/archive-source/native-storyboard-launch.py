#!/usr/bin/env python3
"""Concrete bounded launcher; GPU execution additionally requires root's grant."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path('/workspace/knight26/worktrees/amd')
RUN_ID = 'amd-native-storyboard-20261010T2047-32f3'
JOB_SHA = '60f4f3c355ae94d89642c4a4cba0d43460b9c5f3a9b911ea73024f9889f07de1'
RUNTIME_SHA = '3dfe6bebf1788b3e9078db3457d15b17e0b22113550e9c626237c2f5346cb8c8'
MANIFEST = ROOT / 'platform/evidence/native-storyboard-runtime-20261010T2032.json'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'execute'))
    parser.add_argument('--lease-json')
    parser.add_argument('--reviewed-lease-sha256')
    args = parser.parse_args()
    if args.mode == 'prepare' and (args.lease_json or args.reviewed_lease_sha256):
        parser.error('preparation accepts no lease')
    if args.mode == 'execute' and not (args.lease_json and args.reviewed_lease_sha256):
        parser.error('execution requires a fresh reviewed root grant')
    if hashlib.sha256(MANIFEST.read_bytes()).hexdigest() != RUNTIME_SHA:
        raise ValueError('runtime manifest drift')
    manifest = json.loads(MANIFEST.read_text())
    environment = {
        'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
        'HOME': str(ROOT / 'platform/evidence/native-storyboards'),
        'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '2',
        'OPENBLAS_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2',
        'PYTHONPATH': ':'.join(manifest['pythonpath']),
        'LD_LIBRARY_PATH': manifest['ld_library_path'],
        'LIBGL_DRIVERS_PATH': manifest['libgl_drivers_path'],
        '__EGL_VENDOR_LIBRARY_FILENAMES': manifest['egl_vendor_json'],
        'MESA_SHADER_CACHE_DISABLE': 'true',
    }
    seconds = '60s' if args.mode == 'prepare' else '280s'
    command = ['/usr/bin/timeout', '--signal=TERM', '--kill-after=5s', seconds,
        '/usr/bin/taskset', '-c', '0,1', '/usr/bin/setpriv', '--reuid=65534',
        '--regid=993', '--clear-groups', '/usr/bin/env', '-i',
        *[f'{key}={value}' for key, value in environment.items()],
        manifest['python_executable'], '-B',
        str(ROOT / 'platform/evidence/native-storyboard-job.py'),
        '--prepare-only' if args.mode == 'prepare' else '--execute-authorized-lease',
        '--run-id', RUN_ID, '--reviewed-job-sha256', JOB_SHA,
        '--runtime-manifest', str(MANIFEST), '--reviewed-runtime-sha256', RUNTIME_SHA]
    if args.mode == 'execute':
        command += ['--lease-json', args.lease_json,
                    '--reviewed-lease-sha256', args.reviewed_lease_sha256]
    base = ROOT / 'platform/evidence' / f'{RUN_ID}-{args.mode}'
    with base.with_suffix('.log').open('xb') as log:
        start = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    receipt = {'mode': args.mode, 'run_id': RUN_ID, 'start_utc': start,
               'end_utc': datetime.now(timezone.utc).isoformat(),
               'exit_code': result.returncode, 'command': command,
               'environment': environment, 'job_sha256': JOB_SHA,
               'runtime_manifest_sha256': RUNTIME_SHA,
               'log_sha256': hashlib.sha256(base.with_suffix('.log').read_bytes()).hexdigest()}
    with base.with_suffix('.json').open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write('\n')
    print(json.dumps(receipt, sort_keys=True))
    return result.returncode

if __name__ == '__main__':
    sys.exit(main())
