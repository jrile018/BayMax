#!/usr/bin/env python3
"""Prepare and, only with a fresh external Observer02 lease, run the isolated FSR probe."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=ROOT/"platform/evidence"
RUNS=EVIDENCE/"fsr-runs"
WINROOT=ROOT/"platform/runtime/win64/root"
MESA=ROOT/"platform/runtime/root"
SDK=ROOT/"platform/runtime/sdk"
PROBE_SOURCE=ROOT/"evals/fsr4/probe.cpp"
PROBE_EXE=ROOT/"evals/fsr4/probe-build/probe.exe"
VALIDATOR=ROOT/"evals/fsr4/probe-verify-json.py"
RUNNER=Path(__file__).resolve()
PROBE_SOURCE_SHA="8aa7948ed095d0896919b2e6c18862e66c0e0beae8790e90d88abd24f041c759"
PROBE_EXE_SHA="1769521f2dad0699d6f26186875a0bb6826daaf7f126fdc64de14431558426c0"
VALIDATOR_SHA="0ee3cc65e7cadf70d1b28558214efbd5a6e571fd4355d59ccf39c895e4ded9b6"
NLS_SHA="e045c89e59d1c760252178c2432ff5227b1952d16b977275a1789e2b7daa29df"
ZLIB_SHA="c7f3b6817ffe0a33b1cdf5aa7ed9a6babb3e792957f1cc0f7c0587f3398cdb12"
SOURCE_FILES=(RUNNER,PROBE_SOURCE,PROBE_EXE,VALIDATOR)
SIGNED_NAMES=("amd_fidelityfx_loader_dx12.dll","amd_fidelityfx_upscaler_dx12.dll")
BRIDGE_NAMES=("d3d12.dll","d3d12core.dll","dxgi.dll")

def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def require_hash(path, expected):
    if not re.fullmatch(r"[0-9a-f]{64}",expected or "") or digest(path)!=expected:
        raise ValueError(f"SHA256 mismatch: {path}")
    return {"path":str(path),"bytes":Path(path).stat().st_size,"sha256":expected}

def inside(path, parent):
    resolved=Path(path).resolve()
    root=Path(parent).resolve()
    if resolved==root or not resolved.is_relative_to(root):
        raise ValueError(f"path must remain strictly inside {root}")
    return resolved

def run_dir_for(run_id, *, create=False):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",run_id or ""):
        raise ValueError("run id must be a fresh simple identifier")
    evidence=EVIDENCE.resolve()
    if RUNS.is_symlink():
        raise ValueError("fsr-runs must not be a symlink")
    runs=RUNS.resolve()
    if runs.parent!=evidence:
        raise ValueError("fsr-runs must resolve directly under evidence")
    if create:
        RUNS.mkdir(mode=0o700,exist_ok=True)
    run=RUNS/run_id
    if run.is_symlink():
        raise ValueError("run directory must not be a symlink")
    if create:
        run.mkdir(mode=0o700,exist_ok=False)
    elif not run.is_dir():
        raise ValueError("prepared run directory missing")
    if run.resolve().parent!=runs:
        raise ValueError("run directory escaped fsr-runs")
    return run

def utc(value):
    parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds()!=0:
        raise ValueError("lease times require explicit UTC")
    return parsed

def validate_lease(lease, *, now=None, min_remaining=180):
    if not isinstance(lease,dict) or not isinstance(lease.get("id"),str) or not lease["id"].strip():
        raise ValueError("external lease identity required")
    if lease.get("scope")!="FSR" or lease.get("gpu")!="W7900D" or lease.get("gpu_count")!=1:
        raise ValueError("lease scope must be FSR on one W7900D GPU")
    if lease.get("cpu_cores")!=[0,1] or lease.get("vram_cap_gib")!=12:
        raise ValueError("lease must bound CPU 0,1 and VRAM to 12 GiB")
    beginning,ending=utc(lease["start_utc"]),utc(lease["end_utc"])
    current=now or datetime.now(timezone.utc)
    if not beginning<=current<ending or (ending-current).total_seconds()<min_remaining:
        raise ValueError(f"fresh active FSR lease with at least {min_remaining} seconds remaining required")
    return lease

def check_win64_status():
    assembly_path=EVIDENCE/"win64-assembly-status.json"
    install_path=EVIDENCE/"win64-runtime-offline-status.json"
    archive=WINROOT.parent/"win64-runtime-assembled.tar"
    package_state=WINROOT.parent/"extracted-packages.json"
    transport=WINROOT.parent/"transport-packages.json"
    if not all(path.is_file() for path in (assembly_path,install_path,archive,package_state,transport)):
        raise ValueError("complete Win64 assembly, extraction and package receipts required")
    assembly=json.loads(assembly_path.read_text())
    install=json.loads(install_path.read_text())
    if (assembly.get("status")!="full_archive_sha256_verified" or
        assembly.get("archive_sha256_verified") is not True or
        assembly.get("observed_bytes")!=352943104 or
        len(assembly.get("chunks",[]))!=4 or
        not all(row.get("transport_chunk_hash_verified") is True for row in assembly["chunks"])):
        raise ValueError("full Win64 byte archive is not independently assembled and verified")
    if (install.get("status")!="full_hash_verified_extracted" or
        install.get("archive_sha256_verified") is not True or
        install.get("fresh_private_root") is not True or
        install.get("extracted_package_count")!=145 or
        install.get("expected_package_count")!=145 or not WINROOT.is_dir()):
        raise ValueError("full verified Win64 private extraction (145/145) required")
    manifest=json.loads(transport.read_text())
    expected={Path(row["Filename"]).name:row["SHA256"] for row in manifest["packages"]}
    state=json.loads(package_state.read_text())
    if len(expected)!=145 or state!=expected:
        raise ValueError("published Win64 package state does not match all 145 manifest hashes")
    archive_proof=require_hash(archive,"5bec0aa8038b1206a4f4ff407c4ee05d1d65585c7a2fbfd894427d41b29dcb34")
    if archive_proof["bytes"]!=352943104:
        raise ValueError("Win64 archive byte count mismatch")
    return {"assembly":require_hash(assembly_path,digest(assembly_path)),
        "install":require_hash(install_path,digest(install_path)),
        "package_state":require_hash(package_state,digest(package_state)),
        "archive":archive_proof}


def verify_wine_support(run):
    """Require verified private NLS layout and one prefix-local PE zlib DLL."""
    base=WINROOT/"usr/share/wine"
    nls=base/"nls/l_intl.nls"
    alias=base/"wine"
    zlib=WINROOT/"usr/x86_64-w64-mingw32/lib/zlib1.dll"
    target=run/"prefix/drive_c/windows/system32/zlib1.dll"
    prefix=run/"prefix"
    if any(part.is_symlink() for part in (prefix,prefix/"drive_c",prefix/"drive_c/windows",prefix/"drive_c/windows/system32")):
        raise ValueError("private Wine prefix has a symlinked directory")
    if not prefix.is_dir() or not target.parent.resolve().is_relative_to(prefix.resolve()):
        raise ValueError("private Wine support escaped run prefix")
    if nls.is_symlink() or zlib.is_symlink() or target.is_symlink():
        raise ValueError("Wine support files must be regular, not symlinks")
    require_hash(nls,NLS_SHA)
    require_hash(zlib,ZLIB_SHA)
    if not alias.is_symlink() or os.readlink(alias)!="." or alias.resolve()!=base.resolve():
        raise ValueError("private Wine NLS compatibility path is missing or unsafe")
    if target.resolve().parent != (run/"prefix/drive_c/windows/system32").resolve():
        raise ValueError("private Wine zlib escaped run prefix")
    require_hash(target,ZLIB_SHA)
    return {"nls_sha256":NLS_SHA,"zlib_sha256":ZLIB_SHA}

def stage_wine_support(run):
    """Stage package-verified Wine startup files without touching system paths."""
    base=WINROOT/"usr/share/wine"
    nls=base/"nls/l_intl.nls"
    zlib=WINROOT/"usr/x86_64-w64-mingw32/lib/zlib1.dll"
    alias=base/"wine"
    if nls.is_symlink() or zlib.is_symlink():
        raise ValueError("Wine support source cannot be a symlink")
    require_hash(nls,NLS_SHA)
    require_hash(zlib,ZLIB_SHA)
    if alias.exists() and not alias.is_symlink():
        raise ValueError("unexpected private Wine NLS compatibility path")
    if not alias.is_symlink():
        alias.symlink_to(".")
    if os.readlink(alias)!="." or alias.resolve()!=base.resolve():
        raise ValueError("unsafe private Wine NLS compatibility path")
    prefix=run/"prefix"
    if not prefix.is_dir() or prefix.is_symlink():
        raise ValueError("private Wine prefix missing")
    system32=prefix/"drive_c/windows/system32"
    system32.mkdir(parents=True,exist_ok=False)
    target=system32/"zlib1.dll"
    shutil.copyfile(zlib,target)
    return verify_wine_support(run)

def discover_wine():
    binaries={
        "wine64":(WINROOT/"usr/lib/x86_64-linux-gnu/wine/wine",WINROOT/"usr/lib/wine/wine64",WINROOT/"usr/bin/wine64"),
        "wineserver":(WINROOT/"usr/lib/x86_64-linux-gnu/wine/wineserver",WINROOT/"usr/lib/wine/wineserver64",WINROOT/"usr/bin/wineserver"),
    }
    selected={}
    for name,candidates in binaries.items():
        matches=sorted({p.resolve() for p in candidates if p.is_file()})
        if len(matches)!=1 or not matches[0].is_relative_to(WINROOT.resolve()):
            raise ValueError(f"one private {name} binary required")
        selected[name]=str(matches[0])
    for kind in ("x86_64-unix","x86_64-windows"):
        candidates=(WINROOT/"usr/lib/x86_64-linux-gnu/wine"/kind,WINROOT/"usr/lib/wine"/kind)
        matches=sorted({p.resolve() for p in candidates if p.is_dir()})
        if len(matches)!=1 or not matches[0].is_relative_to(WINROOT.resolve()):
            raise ValueError(f"one private Wine {kind} directory required")
        selected[kind]=str(matches[0])
    return selected

def payload_records():
    sdk_manifest=json.loads((EVIDENCE/"fsr-sdk-dll-stage.json").read_text())
    if sdk_manifest.get("status")!="official_pinned_signedbin_bytes_verified":
        raise ValueError("official signed AMD pair not verified")
    signed={}
    for item in sdk_manifest.get("files",[]):
        name=item.get("filename")
        if name in SIGNED_NAMES and item.get("modified") is False and item.get("embedded_certificate_table_present") is True:
            signed[name]=(SDK/name,item["sha256"])
    if set(signed)!=set(SIGNED_NAMES):
        raise ValueError("verified signed AMD pair incomplete")
    bridge_manifest=json.loads((EVIDENCE/"dx12-bridge-stage.json").read_text())
    selected={}
    for item in bridge_manifest.get("selected_x64_manual_copy",[]):
        name=Path(item["path"]).name
        if name in BRIDGE_NAMES and item.get("pe_machine_hex")=="0x8664" and item.get("unchanged_after_extraction") is True:
            source=Path(item["path"]).resolve()
            if not source.is_relative_to(SDK.resolve()):
                raise ValueError("bridge payload outside private SDK root")
            selected[name]=(source,item["sha256"])
    if set(selected)!=set(BRIDGE_NAMES):
        raise ValueError("verified x64 bridge payload incomplete")
    return {**signed,**selected}

def verify_payloads(records, app=None):
    result=[]
    for name,(source,sha) in records.items():
        result.append(require_hash(source,sha))
        if app is not None:
            target=Path(app)/name
            if target.is_symlink():
                raise ValueError("staged payload must not be a symlink")
            result.append(require_hash(inside(target,app),sha))
    return result

def source_hashes(reviewed_runner_sha):
    if require_hash(RUNNER,reviewed_runner_sha)["sha256"]!=reviewed_runner_sha:
        raise ValueError("reviewed runner mismatch")
    require_hash(PROBE_SOURCE,PROBE_SOURCE_SHA)
    require_hash(PROBE_EXE,PROBE_EXE_SHA)
    require_hash(VALIDATOR,VALIDATOR_SHA)
    return {str(p.relative_to(ROOT)):digest(p) for p in SOURCE_FILES}

def verify_source_freeze(run, reviewed_runner_sha):
    expected=source_hashes(reviewed_runner_sha)
    saved=json.loads((run/"source-freeze.json").read_text())
    if saved.get("files")!=expected or saved.get("reviewed_runner_sha256")!=reviewed_runner_sha:
        raise ValueError("source freeze manifest mismatch")
    return saved

def require_run_paths(run):
    for name in ("app","prefix","logs","shaders","cache","config","data","tmp"):
        path=run/name
        if not path.is_dir() or path.is_symlink() or not path.resolve().is_relative_to(run.resolve()):
            raise ValueError(f"private run path missing or escaped: {name}")

def prepare(run_id, reviewed_runner_sha):
    status=check_win64_status()
    wine=discover_wine()
    files=source_hashes(reviewed_runner_sha)
    records=payload_records()
    verify_payloads(records)
    icd=MESA/"usr/share/vulkan/icd.d/radeon_icd.json"
    if not icd.is_file():
        raise ValueError("private RADV ICD missing")
    run=run_dir_for(run_id,create=True)
    for name in ("app","prefix","logs","shaders","cache","config","data","tmp"):
        (run/name).mkdir(mode=0o700)
    support=stage_wine_support(run)
    app=run/"app"
    shutil.copy2(PROBE_EXE,app/"probe.exe")
    require_hash(app/"probe.exe",PROBE_EXE_SHA)
    for name,(source,sha) in records.items():
        shutil.copy2(source,app/name)
        require_hash(app/name,sha)
    (run/"source-freeze.json").write_text(json.dumps({"files":files,"reviewed_runner_sha256":reviewed_runner_sha},indent=2)+"\n")
    (run/"input-manifest.json").write_text(json.dumps({"win64_status":status,"sdk_stage_sha256":digest(EVIDENCE/"fsr-sdk-dll-stage.json"),
        "bridge_stage_sha256":digest(EVIDENCE/"dx12-bridge-stage.json"),
        "payloads":{name:{"source":str(source),"sha256":sha} for name,(source,sha) in records.items()},
        "probe_exe_sha256":PROBE_EXE_SHA,"wine":wine,"wine_support":support,"private_radv_icd":str(icd)},indent=2)+"\n")
    print(json.dumps({"status":"prepared_cpu_only","run_dir":str(run),"source_freeze":files,"wine":wine}))
    return run

def verify_prelaunch(run, reviewed_runner_sha):
    require_run_paths(run)
    owner=(run/"prefix").stat()
    if owner.st_uid!=os.geteuid():
        raise ValueError("Wine process and private prefix owner mismatch")
    support=verify_wine_support(run)
    status=check_win64_status()
    wine=discover_wine()
    verify_source_freeze(run,reviewed_runner_sha)
    manifest=json.loads((run/"input-manifest.json").read_text())
    if (manifest.get("win64_status")!=status or manifest.get("sdk_stage_sha256")!=digest(EVIDENCE/"fsr-sdk-dll-stage.json")
        or manifest.get("bridge_stage_sha256")!=digest(EVIDENCE/"dx12-bridge-stage.json")):
        raise ValueError("staged input manifest drift")
    records=payload_records()
    expected={name:{"source":str(source),"sha256":sha} for name,(source,sha) in records.items()}
    if manifest.get("wine_support")!=support:
        raise ValueError("private Wine support manifest drift")
    if manifest.get("payloads")!=expected or manifest.get("wine")!=wine:
        raise ValueError("staged payload/Wine manifest drift")
    verify_payloads(records,run/"app")
    require_hash(run/"app/probe.exe",PROBE_EXE_SHA)
    return wine

def private_env(run,wine,phase):
    mesa_lib=MESA/"usr/lib/x86_64-linux-gnu"
    wine_libs=(WINROOT/"usr/lib/x86_64-linux-gnu",WINROOT/"lib/x86_64-linux-gnu")
    icd=MESA/"usr/share/vulkan/icd.d/radeon_icd.json"
    allowed={"PATH","LANG","HOME","USER","LOGNAME"}
    env={key:value for key,value in os.environ.items() if key in allowed or key.startswith("LC_")}
    env.update(OMP_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2",MKL_NUM_THREADS="2",
        WINEARCH="win64",WINEPREFIX=str(run/"prefix"),WINELOADER=wine["wine64"],WINESERVER=wine["wineserver"],
        WINEDLLPATH=":".join((wine["x86_64-unix"],wine["x86_64-windows"])),
        WINEDLLOVERRIDES="d3d12,d3d12core,dxgi=n;mscoree,mshtml,winemenubuilder=d",
        WINEDEBUG="+loaddll",XDG_CACHE_HOME=str(run/"cache"),
        XDG_CONFIG_HOME=str(run/"config"),XDG_DATA_HOME=str(run/"data"),TMPDIR=str(run/"tmp"),
        LD_LIBRARY_PATH=":".join(map(str,(wine["x86_64-unix"],*wine_libs,mesa_lib))),
        VK_DRIVER_FILES=str(icd),VK_ICD_FILENAMES=str(icd),
        LIBGL_DRIVERS_PATH=str(mesa_lib/"dri"),MESA_SHADER_CACHE_DISABLE="true",
        VKD3D_SHADER_CACHE_PATH="0",VKD3D_DEBUG="trace",VKD3D_SHADER_DEBUG="trace",
        VKD3D_LOG_FILE=str(run/"logs"/f"{phase}.vkd3d.log"),
        VKD3D_SHADER_DUMP_PATH=str(run/"shaders"/phase))
    (run/"shaders"/phase).mkdir(mode=0o700,exist_ok=False)
    return env

def load_probe_validator():
    import importlib.util
    require_hash(VALIDATOR,VALIDATOR_SHA)
    spec=importlib.util.spec_from_file_location("fsr_probe_verify",VALIDATOR)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def actual_provider_proof(path, mode):
    validator=load_probe_validator()
    validated=validator.validate(path,mode)
    events=[json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    adapters=[e for e in events if e.get("event")=="adapter" and e.get("vendor_id")==4098 and e.get("software") is False]
    selected=[e for e in events if e.get("event")=="selected_adapter"]
    modules={e.get("name_utf8_bytes") for e in events if e.get("event")=="module_path_verification" and e.get("matches_expected") is True}
    providers=[e for e in events if e.get("event")=="provider" and "4.1.1" in e.get("name_bytes","")]
    contexts=[e for e in events if e.get("event")=="context_provider"]
    if len(selected)!=1 or not any(e.get("luid")==selected[0].get("luid") for e in adapters):
        raise ValueError("actual AMD hardware adapter proof missing")
    if (not set(SIGNED_NAMES).issubset(modules) or len(providers)!=1 or
        len(contexts)!=1 or contexts[0].get("id")!=providers[0].get("id")):
        raise ValueError("signed module or retained 4.1.1 context provider proof missing")
    return {"amd_adapter_luid":selected[0]["luid"],"provider_id":providers[0]["id"],
        "provider_name_bytes":providers[0]["name_bytes"],"signed_modules":sorted(modules),
        "dispatch_frames":validated["dispatch_frames"]}

def query_proof(path):
    return actual_provider_proof(path,"query-only")

def dispatch_proof(path, expected_query):
    if not isinstance(expected_query,dict):
        raise ValueError("accepted query proof required before dispatch")
    proof=actual_provider_proof(path,"dispatch")
    if proof["dispatch_frames"]!=3:
        raise ValueError("exactly three complete synthetic frames required")
    for key in ("amd_adapter_luid","provider_id"):
        if proof[key]!=expected_query.get(key):
            raise ValueError(f"dispatch {key} differs from accepted query")
    if ("provider_name_bytes" in expected_query and
        proof["provider_name_bytes"]!=expected_query["provider_name_bytes"]):
        raise ValueError("dispatch provider name differs from accepted query")
    return proof


def audit_shaders(run):
    root=run/"shaders"
    files=[]
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("shader dump symlink rejected")
        if path.is_file():
            checked=inside(path,root)
            files.append({"path":str(checked.relative_to(run)),"bytes":checked.stat().st_size,
                "sha256":digest(checked)})
    audit={"files":files,"file_count":len(files),"ml_dispatch_verified":False,
        "classification":"raw translated shader byte audit; ML path unresolved"}
    write_json(run/"logs/shader-audit.json",audit)
    return audit

def write_json(path,value):
    tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")
    tmp.replace(path)

def save_output(path,data):
    if isinstance(data,bytes):
        data=data.decode("utf-8",errors="replace")
    path.write_text(data or "",encoding="utf-8")

def run_phase(mode,run,lease_path,reviewed_runner_sha,report):
    phase="query" if mode=="query-only" else "dispatch"
    wine=verify_prelaunch(run,reviewed_runner_sha)
    lease=json.loads(lease_path.read_text())
    validate_lease(lease)
    env=private_env(run,wine,phase)
    command=[wine["wine64"],str(run/"app/probe.exe"),f"--{mode}"]
    if mode=="dispatch":
        command+=["--frames","3"]
    command+=["--dll-dir","Z:"+str((run/"app").resolve()).replace("/","\\")]
    visible_keys=("WINEARCH","WINEPREFIX","WINELOADER","WINESERVER","WINEDLLPATH","WINEDLLOVERRIDES",
        "WINEDEBUG","OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS",
        "XDG_CACHE_HOME","XDG_CONFIG_HOME","XDG_DATA_HOME","TMPDIR",
        "LD_LIBRARY_PATH","VK_DRIVER_FILES","VK_ICD_FILENAMES","LIBGL_DRIVERS_PATH",
        "MESA_SHADER_CACHE_DISABLE","VKD3D_SHADER_CACHE_PATH","VKD3D_DEBUG","VKD3D_SHADER_DEBUG",
        "VKD3D_LOG_FILE","VKD3D_SHADER_DUMP_PATH")
    write_json(run/"logs"/f"{phase}.command-env.json",
        {"command":command,"cwd":str(run/"app"),"environment":{key:env[key] for key in visible_keys},
         "source_freeze_sha256":digest(run/"source-freeze.json"),"lease_id":lease["id"]})
    report["phases"][phase]={"attempted":False,"completed":False,"exit_code":None}
    write_json(run/"execute-runner.json",report)
    # These checks are repeated immediately before each Wine/device launch.
    verify_prelaunch(run,reviewed_runner_sha)
    validate_lease(json.loads(lease_path.read_text()))
    report["phases"][phase]["attempted"]=True
    report["phases"][phase]["started_at_utc"]=datetime.now(timezone.utc).isoformat()
    write_json(run/"execute-runner.json",report)
    try:
        result=subprocess.run(command,cwd=run/"app",env=env,capture_output=True,text=True,
            errors="replace",timeout=120)
    except subprocess.TimeoutExpired as error:
        save_output(run/"logs"/f"{phase}.stdout.jsonl",error.stdout)
        save_output(run/"logs"/f"{phase}.stderr.log",error.stderr)
        report["phases"][phase].update(timeout_seconds=120,exit_code="timeout",completed=False)
        write_json(run/"logs"/f"{phase}.exit.json",report["phases"][phase])
        write_json(run/"execute-runner.json",report)
        raise
    save_output(run/"logs"/f"{phase}.stdout.jsonl",result.stdout)
    save_output(run/"logs"/f"{phase}.stderr.log",result.stderr)
    report["phases"][phase].update(completed=True,exit_code=result.returncode)
    write_json(run/"logs"/f"{phase}.exit.json",report["phases"][phase])
    write_json(run/"execute-runner.json",report)
    if result.returncode:
        raise RuntimeError(f"{phase} Wine probe failed: exit {result.returncode}")
    path=run/"logs"/f"{phase}.stdout.jsonl"
    if mode=="query-only":
        report["query_proof"]=query_proof(path)
        report["gpu_context_created"]=True
    else:
        report["dispatch_proof"]=dispatch_proof(path,report.get("query_proof"))
        audit_shaders(run)
        report["shader_audit_sha256"]=digest(run/"logs/shader-audit.json")
    write_json(run/"execute-runner.json",report)

def execute(run_id,lease_path,reviewed_runner_sha):
    run=run_dir_for(run_id)
    lease_path=inside(lease_path,EVIDENCE)
    if not lease_path.is_file():
        raise ValueError("external lease JSON missing")
    if (run/"execute-runner.json").exists():
        raise ValueError("fresh prepared run required; prior execution receipt preserved")
    # The 280-second shell bound, 5-second forced kill and 12-second dedicated cleanup
    # must all fit within the external grant, with headroom for preparation and hashes.
    validate_lease(json.loads(lease_path.read_text()),min_remaining=330)
    verify_prelaunch(run,reviewed_runner_sha)
    report={"status":"execution_pending","run_id":run_id,"lease":json.loads(lease_path.read_text()),
        "phases":{},"ml_dispatch_verified":False,
        "ml_evidence_status":"unresolved_requires_shader_or_trace_discriminator",
        "gpu_context_created":None,"wine_executed":False}
    try:
        run_phase("query-only",run,lease_path,reviewed_runner_sha,report)
        report["wine_executed"]=True
        run_phase("dispatch",run,lease_path,reviewed_runner_sha,report)
        report["status"]="query_and_dispatch_completed"
        return 0
    except Exception as error:
        report.update(status="failed",error=f"{type(error).__name__}: {error}")
        raise
    finally:
        report["finished_at_utc"]=datetime.now(timezone.utc).isoformat()
        report["wine_executed"]=any(p.get("attempted") for p in report["phases"].values())
        write_json(run/"execute-runner.json",report)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only",action="store_true")
    mode.add_argument("--execute-authorized-lease",action="store_true")
    parser.add_argument("--run-id",required=True)
    parser.add_argument("--reviewed-runner-sha256",required=True)
    parser.add_argument("--lease-json",type=Path)
    args=parser.parse_args(argv)
    if args.prepare_only:
        if args.lease_json is not None:
            raise ValueError("CPU preparation does not accept a lease")
        prepare(args.run_id,args.reviewed_runner_sha256)
        return 0
    if args.lease_json is None:
        raise ValueError("externally granted FSR lease JSON required")
    return execute(args.run_id,args.lease_json,args.reviewed_runner_sha256)

if __name__=="__main__":
    raise SystemExit(main())
