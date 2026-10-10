"""Read-only graphics prerequisite inventory; never creates a GPU context."""
from __future__ import annotations
import argparse
import ctypes
import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

TOOLS = ('git', 'tmux', 'gcc', 'g++', 'cmake', 'ninja', 'pkg-config',
         'vulkaninfo', 'glxinfo', 'eglinfo', 'wine', 'wine64', 'Xvfb',
         'ffmpeg', 'node', 'npm', 'godot', 'blender', 'curl', 'wget')
LIBRARIES = ('libvulkan.so.1', 'libEGL.so.1', 'libGL.so.1', 'libOSMesa.so.8')


def read_file(path: str) -> dict:
    try:
        return {'value': Path(path).read_text().strip(), 'error': None}
    except (OSError, UnicodeError) as error:
        return {'value': None, 'error': str(error)}


def command(argv: list[str]) -> dict:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        return {'command': argv, 'exit_code': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
        return {'command': argv, 'exit_code': None, 'error': str(error),
                'timed_out': True, 'timeout_seconds': error.timeout,
                'stdout': decoded(error.stdout), 'stderr': decoded(error.stderr)}
    except OSError as error:
        return {'command': argv, 'exit_code': None, 'error': str(error)}


def probe() -> dict:
    libraries = {}
    for name in LIBRARIES:
        try:
            ctypes.CDLL(name)
            libraries[name] = {'loadable': True, 'error': None}
        except OSError as error:
            libraries[name] = {'loadable': False, 'error': str(error)}
    icds = {}
    for directory in ('/etc/vulkan/icd.d', '/usr/share/vulkan/icd.d'):
        for path in sorted(Path(directory).glob('*.json')):
            icds[str(path)] = read_file(str(path))
    modules = {}
    for name in ('torch', 'numpy', 'pillow', 'pytest'):
        try:
            modules[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            modules[name] = None
    nodes = []
    for path in sorted(Path('/dev/dri').glob('*')):
        stat = path.stat()
        device = f'/sys/dev/char/{os.major(stat.st_rdev)}:{os.minor(stat.st_rdev)}/device'
        nodes.append({'node': str(path), 'major': os.major(stat.st_rdev),
                      'minor': os.minor(stat.st_rdev),
                      'device_metadata': {name: read_file(f'{device}/{name}')
                                          for name in ('vendor', 'device', 'uevent')}})
    files = {path: read_file(path) for path in (
        '/etc/os-release', '/sys/fs/cgroup/cpu.max', '/sys/fs/cgroup/memory.max',
        '/sys/module/amdgpu/version', '/sys/module/amdgpu/srcversion')}
    cpu = files['/sys/fs/cgroup/cpu.max']['value']
    quota = None
    if cpu:
        amount, period = cpu.split()
        if amount != 'max':
            quota = int(amount) / int(period)
    missing = []
    if not libraries['libvulkan.so.1']['loadable']:
        missing.append('Vulkan loader is not loadable')
    if not icds:
        missing.append('No system Vulkan ICD manifest found')
    if not any(shutil.which(name) for name in ('wine', 'wine64')):
        missing.append('Wine/DX12 translation runtime is not installed')
    return {
        'report_schema': 'knight26-graphics-prerequisites-v1',
        'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'host': {'os': os.uname().sysname, 'kernel': os.uname().release,
                 'python': sys.version, 'python_executable': sys.executable},
        'allocation': {'cpu_quota_cores': quota,
                       'memory_limit_bytes': files['/sys/fs/cgroup/memory.max']['value'],
                       'accessible_drm_nodes': nodes,
                       'gpu_count': None,
                       'gpu_count_note': 'Device nodes and host sysfs do not establish allocated GPU count.'},
        'system_files': files,
        'tools': {name: shutil.which(name) for name in TOOLS},
        'module_versions_without_import': modules,
        'shared_libraries': libraries, 'vulkan_icd_manifests': icds,
        'display_environment': {name: os.getenv(name) for name in
                                ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR')},
        'storage': {'path': '/workspace',
                    'total_bytes': os.statvfs('/workspace').f_blocks * os.statvfs('/workspace').f_frsize,
                    'available_bytes': os.statvfs('/workspace').f_bavail * os.statvfs('/workspace').f_frsize},
        'cpu_package_candidates': command(['apt-cache', 'policy', 'libvulkan1',
                                          'mesa-vulkan-drivers', 'wine64', 'xvfb']),
        'graphics_prerequisite_gate': {'status': 'blocked' if missing else 'unverified',
                                      'missing_prerequisites': missing,
                                      'device_context_created': False},
        'fsr4': {'status': 'not_executed', 'provider_selected': None,
                 'ml_dispatch_verified': False,
                 'reason': 'Inventory only; no GPU lease/context/provider/dispatch in this probe.'},
        'rocm': {'status': 'not_executed_this_probe',
                 'reason': 'Torch package metadata is not ROCm execution evidence.'},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(probe(), indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
