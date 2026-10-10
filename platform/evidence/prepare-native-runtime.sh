#!/usr/bin/env bash
set -eu
cd /workspace/knight26/worktrees/amd
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1
apt-get --simulate --no-install-recommends install libvulkan1 mesa-vulkan-drivers libegl1 libegl-mesa0 libgl1-mesa-dri libgl1 vulkan-tools | sed -n 's/^Inst \([^ ]*\) (\([^ ]*\).*/\1=\2/p' > platform/runtime/package-specs.txt
/opt/venv/bin/python - <<'PY'
import json, subprocess
from pathlib import Path
packages = []
for spec in Path('platform/runtime/package-specs.txt').read_text().splitlines():
    raw = subprocess.check_output(['apt-cache','show',spec],text=True)
    fields = dict(line.split(': ',1) for line in raw.split('\n\n')[0].splitlines() if ': ' in line and not line.startswith(' '))
    packages.append({key: fields[key] for key in ('Package','Version','Size','Installed-Size','SHA256')})
manifest = {'status':'download_pending','gpu_context_created':False,'package_count':len(packages),'download_bytes':sum(int(p['Size']) for p in packages),'installed_kib':sum(int(p['Installed-Size']) for p in packages),'packages':packages}
Path('platform/evidence/native-runtime-packages.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({k:v for k,v in manifest.items() if k != 'packages'}))
PY
cd platform/runtime/debs
xargs -r apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=12 -o Acquire::https::Timeout=12 download < ../package-specs.txt
cd ../../..
/opt/venv/bin/python - <<'PY'
import hashlib,json,subprocess
from pathlib import Path
path=Path('platform/evidence/native-runtime-packages.json'); manifest=json.loads(path.read_text()); expected={(p['Package'],p['Version']):p for p in manifest['packages']}; found=set()
for file in sorted(Path('platform/runtime/debs').glob('*.deb')):
    name,version=subprocess.check_output(['dpkg-deb','-f',str(file),'Package','Version'],text=True).splitlines()
    if name.startswith('Package: '): name=name[9:]
    if version.startswith('Version: '): version=version[9:]
    package=expected[(name,version)]
    assert hashlib.sha256(file.read_bytes()).hexdigest()==package['SHA256'], f'checksum mismatch for {name}'
    found.add((name,version)); subprocess.run(['dpkg-deb','-x',str(file),'platform/runtime/root'],check=True)
assert found==set(expected), 'incomplete package set'
manifest['status']='extracted_checksums_verified'; path.write_text(json.dumps(manifest,indent=2)+'\n'); print('Verified and extracted',len(found),'packages')
PY
/opt/venv/bin/python -m pip download --disable-pip-version-check --timeout 8 --retries 0 --only-binary=:all: --require-hashes --dest platform/runtime/wheels -r platform/native-runtime-requirements.txt
/opt/venv/bin/python -m venv --system-site-packages platform/runtime/venv
platform/runtime/venv/bin/python -m pip install --disable-pip-version-check --no-index --find-links platform/runtime/wheels --require-hashes -r platform/native-runtime-requirements.txt
