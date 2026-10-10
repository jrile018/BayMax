#!/usr/bin/env python3
"""One leased native storyboard job. Prepare is CPU-only; execution is GPU-gated.

Copy this reviewed file to platform/evidence/native-storyboard-job.py only after
the runtime manifest and exact source hash have been independently reviewed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
import time


HEAD = "32f3b6f6d371db824294b92092e5dda6eaacd63c"
FRAMES = ((0, 0), (3, 180), (6, 360))
SOURCE = {
    "viewer3d/__init__.py": "b454673e67cb64e2e56f3a009cda282ab942463dfa7aa1be45a04e720190fa31",
    "viewer3d/render.py": "d28a498198b7093d8f53b1a30f286cf361484c8bd3ba31413dce849675fbecf5",
    "viewer3d/replay_adapter.py": "de892c5f2cab6c666c736d7afd4725a0ba3dfb5c2a196e14e5e6761cdeda1b84",
    "viewer3d/scene.py": "c7b1865732f76d352d8fb6a43acb3e979d01e2e38fb4ddc80d44e4fe3a5b8e50",
}
INPUTS = {
    "viewer3d/evidence/replay-adapter-input-manifest.json": "058f5cbde8a1e451e0e7ec884d50f6308d708cf0cfebf29e5370cb34acb8a5bf",
    "viewer3d/evidence/replay-adapter-inputs/bootstrap.json": "2a0c593ffc9f9c3924344a30b500113f29b1105250ce15205075fdfb5b5f82b2",
    "viewer3d/evidence/replay-adapter-inputs/graph.json": "0b9350b23f099e8527accbf6c1d6e72fb1af196d86f4f9de004fb1a5807aa1c5",
    "viewer3d/evidence/replay-adapter-inputs/raw.osm": "b73334f6280cc756fee13ab9687ccbd7d47368785f0703fea9dafd97c6035897",
    "viewer3d/evidence/replay-adapter-inputs/bindings.json": "979ad8ba8bff2fedee3bb91494543b89222ec6e0817ca43cd904d443dad23f7f",
    "viewer3d/evidence/replay-adapter-inputs/frame-0.json": "2d2d7c6d3430be0812a083b19dfa2b5787b36dcd720bb2d032d32079896ac440",
    "viewer3d/evidence/replay-adapter-inputs/frame-3.json": "a78f6685cd2b5b2eb28a93545ea1b2f3986492be5e867492f6880e5f1a82b7be",
    "viewer3d/evidence/replay-adapter-inputs/frame-6.json": "77bfe058124788b26b71cbb72c450a21822e75b674b49015f5891ded00c94c4b",
}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SOFTWARE = ("llvmpipe", "softpipe", "swrast", "software", "swiftshader", "lavapipe")
_BINDING_FIELDS = ("run_id", "scenario_id", "index", "time_s", "snapshot_hash",
                   "bootstrap_hash", "graph_hash", "raw_source_sha256")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"regular nonsymlink file required: {path}")
    return path


def pinned(path, expected):
    if not isinstance(expected, str) or not _SHA.fullmatch(expected):
        raise ValueError("reviewed lowercase SHA-256 required")
    if sha256(regular(path)) != expected:
        raise ValueError(f"reviewed hash mismatch: {path}")
    return expected


def json_file(path):
    return json.loads(regular(path).read_text(encoding="utf-8"))


def write_once(path, data):
    payload = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with open(path, "xb") as stream:
        stream.write(payload)


def status_write(path, data):
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    write_once(temp, data)
    temp.replace(path)


def create_run_directory(run):
    run = Path(run)
    run.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(run, 0o700)


def output_name(index, time_s):
    if (index, time_s) not in FRAMES:
        raise ValueError("only frozen frames 0, 3, 6 are allowed")
    return f"frame-{index:02d}-{time_s:03d}s.png"


def binding_fields(row):
    if not isinstance(row, dict) or any(key not in row for key in _BINDING_FIELDS):
        raise ValueError("frozen frame binding fields missing")
    return {key: row[key] for key in _BINDING_FIELDS}


def reject_inherited_environment(env):
    forbidden = {"DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
                 "TMPDIR", "TMP", "TEMP", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    if forbidden.intersection(env) or any(key.casefold().endswith("_proxy") for key in env):
        raise ValueError("inherited display, temporary or network proxy environment refused")


def require_identity(*, uid=None, gid=None, groups=None, affinity=None):
    uid = os.geteuid() if uid is None else uid
    gid = os.getegid() if gid is None else gid
    groups = os.getgroups() if groups is None else groups
    affinity = os.sched_getaffinity(0) if affinity is None else affinity
    if (uid, gid) != (65534, 993) or groups or set(affinity) != {0, 1}:
        raise ValueError("native job requires UID65534/GID993/groups[]/CPU0,1")


def _utc(value):
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if when.tzinfo is None or when.utcoffset().total_seconds() != 0:
        raise ValueError("lease times must be UTC")
    return when


def validate_lease(lease, run_id, *, expected_job_sha, expected_runtime_sha, now=None):
    if not isinstance(lease, dict) or not isinstance(lease.get("id"), str) or not lease["id"]:
        raise ValueError("external lease ID required")
    expected = {"scope": "native-storyboard", "gpu": "W7900D", "gpu_count": 1,
                "vram_cap_gib": 12, "cpu_cores": [0, 1], "pci_vendor_id": 0x1002,
                "pci_device_id": 0x744b, "head": HEAD, "run_limit": 1, "run_id": run_id,
                "max_diagnostic_seconds": 280, "uid": 65534, "gid": 993,
                "supplementary_groups": [], "render_node": "/dev/dri/renderD128",
                "job_sha256": expected_job_sha,
                "runtime_manifest_sha256": expected_runtime_sha}
    for field, value in expected.items():
        if lease.get(field) != value or (type(value) is int and type(lease.get(field)) is not int):
            raise ValueError(f"native lease {field} mismatch")
    now = datetime.now(timezone.utc) if now is None else now
    if _utc(lease["start_utc"]) > now or (_utc(lease["end_utc"]) - now).total_seconds() < 330:
        raise ValueError("fresh active native lease with >=330 seconds required")
    return lease


def verify_pci(lease):
    device = Path("/sys/class/drm/renderD128/device")
    vendor = int((device / "vendor").read_text().strip(), 16)
    model = int((device / "device").read_text().strip(), 16)
    if (vendor, model) != (lease["pci_vendor_id"], lease["pci_device_id"]):
        raise ValueError("renderD128 differs from leased W7900D PCI identity")
    return {"render_node": "/dev/dri/renderD128", "vendor_id": vendor, "device_id": model}


def verify_head(root):
    git = ["git", "-c", f"safe.directory={root}"]
    result = subprocess.run([*git, "rev-parse", "HEAD"], cwd=root, check=True,
                            capture_output=True, text=True, timeout=5)
    if result.stdout.strip() != HEAD:
        raise ValueError("reviewed exact HEAD required")
    branch = subprocess.run([*git, "symbolic-ref", "--short", "HEAD"], cwd=root,
                            check=True, capture_output=True, text=True, timeout=5)
    if branch.stdout.strip() != "codex/amd":
        raise ValueError("reviewed codex/amd branch required")


def source_freeze(root, job_path, reviewed_job_sha):
    verify_head(root)
    if job_path != root / "platform/evidence/native-storyboard-job.py":
        raise ValueError("job must run from reviewed cloud evidence path")
    pinned(job_path, reviewed_job_sha)
    files = {"platform/evidence/native-storyboard-job.py": reviewed_job_sha}
    for rel, expected in {**SOURCE, **INPUTS}.items():
        pinned(root / rel, expected)
        files[rel] = expected
    return {"head": HEAD, "files": files}


def runtime_freeze(root, manifest_path, expected_sha):
    manifest_path = Path(manifest_path).absolute()
    if not manifest_path.is_relative_to(root / "platform"):
        raise ValueError("runtime manifest must be AMD-owned")
    pinned(manifest_path, expected_sha)
    manifest = json_file(manifest_path)
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("finalized native runtime inventory v1 required")
    files = manifest["files"]
    if not files:
        raise ValueError("runtime inventory cannot be empty")
    for name, expected in files.items():
        path = Path(name)
        if not path.is_absolute():
            raise ValueError("runtime inventory paths must be absolute")
        pinned(path, expected)
    for key in ("python_executable", "gl_library", "egl_library"):
        value = manifest.get(key)
        if not isinstance(value, str) or value not in files:
            raise ValueError(f"runtime {key} must name a pinned file")
    modules = manifest.get("modules")
    if not isinstance(modules, dict) or set(modules) != {"moderngl", "glcontext", "PIL"} or any(
            not isinstance(path, str) or path not in files for path in modules.values()):
        raise ValueError("ModernGL, glcontext and Pillow module files must be pinned")
    if Path(sys.executable).resolve() != Path(manifest["python_executable"]).resolve():
        raise ValueError("running Python differs from pinned runtime")
    paths = manifest.get("pythonpath")
    if not isinstance(paths, list) or not paths or any(not Path(p).is_dir() for p in paths):
        raise ValueError("reviewed Python package paths required")
    if not isinstance(manifest.get("libgl_drivers_path"), str) or not Path(
            manifest["libgl_drivers_path"]).is_dir():
        raise ValueError("reviewed private LIBGL_DRIVERS_PATH required")
    vendor_json = manifest.get("egl_vendor_json")
    if not isinstance(vendor_json, str) or vendor_json not in files:
        raise ValueError("reviewed GLVND Mesa vendor JSON must be pinned")
    validate_runtime_environment(manifest, os.environ)
    return {"manifest_sha256": expected_sha, "manifest_path": str(manifest_path),
            "files": files, "pythonpath": paths,
            "gl_library": manifest["gl_library"], "egl_library": manifest["egl_library"]}


def validate_runtime_environment(manifest, env):
    expected = {"PYTHONPATH": os.pathsep.join(manifest["pythonpath"]),
                "LD_LIBRARY_PATH": manifest["ld_library_path"],
                "LIBGL_DRIVERS_PATH": manifest["libgl_drivers_path"],
                "__EGL_VENDOR_LIBRARY_FILENAMES": manifest["egl_vendor_json"],
                "MESA_SHADER_CACHE_DISABLE": "true"}
    if any(not isinstance(value, str) or not value or env.get(key) != value
           for key, value in expected.items()):
        raise ValueError("private Python/Mesa/GLVND environment differs from reviewed runtime")


def adapted_frames(root):
    # This module and scene.py contain no graphics import or context creation.
    sys.path.insert(0, str(root))
    from viewer3d.replay_adapter import DashboardFrameBinding, adapt_dashboard_replay
    from viewer3d.scene import SourceMetadata

    base = root / "viewer3d/evidence/replay-adapter-inputs"
    bootstrap, graph = json_file(base / "bootstrap.json"), json_file(base / "graph.json")
    raw = regular(base / "raw.osm").read_bytes()
    bindings = json_file(base / "bindings.json")
    if isinstance(bindings, dict):
        bindings = bindings.get("frames")
    if not isinstance(bindings, list):
        raise ValueError("frozen bindings must list frame records")
    overlay = SourceMetadata("project-mock-dashboard", "project-authored mock training replay",
        "project-authorized-training-display", "fixture://replay-ui/paradise_mock.json", True,
        ("Explicit caller authorization to display project-authored mock training overlays",))
    results = []
    for index, time_s in FRAMES:
        rows = [row for row in bindings if isinstance(row, dict) and row.get("index") == index]
        if len(rows) != 1 or rows[0].get("time_s") != time_s:
            raise ValueError("exact frozen binding index/time required")
        frame = json_file(base / f"frame-{index}.json")
        adapted = adapt_dashboard_replay(bootstrap, frame, graph,
            binding=DashboardFrameBinding(**binding_fields(rows[0])),
            raw_source_bytes=raw, overlay_source=overlay)
        if adapted.metadata.get("mode") != "mock-replay" or not adapted.metadata.get("geometry_status"):
            raise ValueError("constructed mock replay label required")
        if adapted.metadata.get("identity", {}).get("index") != index:
            raise ValueError("adapted replay index mismatch")
        if adapted.scene.frame.time_s != time_s:
            raise ValueError("adapted frame time mismatch")
        results.append((index, time_s, adapted))
    return results


def validate_sidecar(meta, frame, view_hash):
    if any(meta.get(k) != v for k, v in {"status": "rendered", "backend": "egl",
            "width": 1280, "height": 720, "output_written": True,
            "hardware_required": True, "software_detected": False}.items()):
        raise ValueError("native sidecar is not successful hardware EGL 1280x720")
    provider = meta.get("provider")
    if not isinstance(provider, dict) or any(not isinstance(provider.get(k), str) or
            not provider[k].strip() for k in ("GL_VENDOR", "GL_RENDERER", "GL_VERSION")):
        raise ValueError("native GL provider metadata missing")
    description = " ".join(provider.values()).casefold()
    if any(token in description for token in _SOFTWARE):
        raise ValueError("software GL provider rejected")
    if "amd" not in provider["GL_VENDOR"].casefold() or "radeon" not in provider["GL_RENDERER"].casefold():
        raise ValueError("AMD Radeon provider required")
    if meta.get("frame") != frame:
        raise ValueError("native sidecar frame identity mismatch")
    replay = meta.get("replay")
    identity = replay.get("identity") if isinstance(replay, dict) else None
    if (not isinstance(replay, dict) or not isinstance(identity, dict) or
            any(identity.get(key) != value for key, value in frame.items()) or
            replay.get("mode") != "mock-replay" or replay.get("view_hash") != view_hash or
            not any(word in str(replay.get("geometry_status", "")).casefold()
                    for word in ("mock", "constructed", "illustration"))):
        raise ValueError("native sidecar lost exact mock replay binding")
    return provider


def png_size(path):
    with open(regular(path), "rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError("valid PNG IHDR required")
    return struct.unpack(">II", header[16:24])


def validate_frame_results(results):
    if not isinstance(results, list) or len(results) != 3 or [
            (row.get("index"), row.get("time_s")) for row in results] != list(FRAMES):
        raise ValueError("exactly three ordered frozen frame results required")
    return True


def run_dir(root, run_id):
    if not _RUN.fullmatch(run_id):
        raise ValueError("bounded run ID required")
    parent = root / "platform/evidence/native-storyboards"
    if parent.is_symlink() or not parent.is_dir():
        raise ValueError("pre-existing AMD-owned storyboard parent required")
    return parent / run_id


def prepare(root, run, job_path, job_sha, runtime_path, runtime_sha):
    require_identity()
    reject_inherited_environment(os.environ)
    create_run_directory(run)
    try:
        freeze = {"source": source_freeze(root, job_path, job_sha),
                  "runtime": runtime_freeze(root, runtime_path, runtime_sha)}
        frames = adapted_frames(root)
        freeze["frames"] = [{"index": index, "time_s": time_s,
            "frame": dict(vars(adapted.scene.frame)),
            "view_hash": adapted.metadata["view_hash"]} for index, time_s, adapted in frames]
        write_once(run / "source-freeze.json", freeze)
        write_once(run / "prepared.json", {"status": "prepared_cpu_only", "run_id": run.name,
                   "source_freeze_sha256": sha256(run / "source-freeze.json"),
                   "graphics_imported": False})
    except BaseException as error:
        status_write(run / "status.json", {"status": "prepare_failed", "error": str(error)})
        raise
    return freeze


def _deadline(_signum, _frame):
    raise TimeoutError("native storyboard deadline or termination signal")


def execute(root, run, job_path, job_sha, runtime_path, runtime_sha,
            lease_path, lease_sha):
    require_identity()
    reject_inherited_environment(os.environ)
    if not (run / "prepared.json").is_file() or (run / "execution-started.json").exists():
        raise ValueError("fresh CPU-prepared, never-executed run required")
    lease_path = Path(lease_path).absolute()
    if not lease_path.is_relative_to(root / "platform/evidence"):
        raise ValueError("external grant must reside in AMD evidence")
    pinned(lease_path, lease_sha)
    lease = validate_lease(json_file(lease_path), run.name,
                           expected_job_sha=job_sha, expected_runtime_sha=runtime_sha)
    # A valid external grant begins this one attempt. Even preflight drift then
    # consumes the run ID; a later launch cannot recycle the same marker.
    write_once(run / "execution-started.json", {"lease_id": lease["id"],
        "lease_sha256": lease_sha, "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "attempt_limit": 1})
    pci = verify_pci(lease)
    freeze = {"source": source_freeze(root, job_path, job_sha),
              "runtime": runtime_freeze(root, runtime_path, runtime_sha)}
    prior = json_file(run / "source-freeze.json")
    if prior["source"] != freeze["source"] or prior["runtime"] != freeze["runtime"]:
        raise ValueError("prepared source/runtime freeze differs from execution")
    if json_file(run / "prepared.json").get("source_freeze_sha256") != sha256(run / "source-freeze.json"):
        raise ValueError("prepared freeze digest mismatch")
    frames = adapted_frames(root)
    if prior["frames"] != [{"index": i, "time_s": t, "frame": dict(vars(a.scene.frame)),
            "view_hash": a.metadata["view_hash"]} for i, t, a in frames]:
        raise ValueError("prepared frame identities changed")
    previous = {kind: signal.signal(kind, _deadline)
                for kind in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)}
    signal.alarm(280)
    start = time.perf_counter()
    results = []
    try:
        # Graphics is imported only after all source, runtime, lease, identity and marker gates.
        from viewer3d.render import render_native
        for index, time_s, adapted in frames:
            validate_lease(json_file(lease_path), run.name,
                           expected_job_sha=job_sha, expected_runtime_sha=runtime_sha)
            verify_pci(lease)
            name = output_name(index, time_s)
            png = run / name
            sidecar = png.with_suffix(".json")
            if png.exists() or sidecar.exists():
                raise ValueError("storyboard output cannot overwrite a prior attempt")
            begun = time.perf_counter()
            render_native(adapted.scene, png, width=1280, height=720,
                require_hardware=True, replay_metadata=adapted.metadata,
                gl_library=freeze["runtime"]["gl_library"],
                egl_library=freeze["runtime"]["egl_library"])
            elapsed = time.perf_counter() - begun
            meta = json_file(sidecar)
            frame = dict(vars(adapted.scene.frame))
            provider = validate_sidecar(meta, frame, adapted.metadata["view_hash"])
            if png_size(png) != (1280, 720):
                raise ValueError("native PNG dimensions mismatch")
            results.append({"index": index, "time_s": time_s, "png": name,
                "png_sha256": sha256(png), "sidecar": sidecar.name,
                "sidecar_sha256": sha256(sidecar), "frame": frame,
                "view_hash": adapted.metadata["view_hash"],
                "provider": provider, "elapsed_seconds": elapsed})
        validate_frame_results(results)
        lines = ["# Paradise mock replay storyboard", "",
            "Constructed training replay; not an actual incident, dispatch, route calculation or FSR result.", ""]
        for row in results:
            lines += [f"- {row['time_s']} s, frame {row['index']}: [{row['png']}]({row['png']}) "
                      f"([native sidecar]({row['sidecar']}))"]
        with open(run / "README.md", "x", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
        receipt = {"status": "rendered", "mock_replay": True, "lease_id": lease["id"],
            "lease_sha256": lease_sha, "pci": pci, "source_freeze_sha256": sha256(run / "source-freeze.json"),
            "frames": results, "frame_count": 3, "readme_sha256": sha256(run / "README.md"),
            "total_elapsed_seconds": time.perf_counter() - start}
        write_once(run / "receipt.json", receipt)
        status_write(run / "status.json", {"status": "rendered", "lease_id": lease["id"],
                    "receipt_sha256": sha256(run / "receipt.json")})
        return receipt
    except BaseException as error:
        status_write(run / "status.json", {"status": "failed", "lease_id": lease["id"],
                    "error": f"{type(error).__name__}: {error}", "frames_completed": len(results),
                    "total_elapsed_seconds": time.perf_counter() - start})
        raise
    finally:
        signal.alarm(0)
        for kind, prior in previous.items():
            signal.signal(kind, prior)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--execute-authorized-lease", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reviewed-job-sha256", required=True)
    parser.add_argument("--runtime-manifest", type=Path, required=True)
    parser.add_argument("--reviewed-runtime-sha256", required=True)
    parser.add_argument("--lease-json", type=Path)
    parser.add_argument("--reviewed-lease-sha256")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    path = Path(__file__).resolve()
    run = run_dir(root, args.run_id)
    if args.prepare_only:
        if args.lease_json or args.reviewed_lease_sha256:
            raise ValueError("CPU preparation accepts no lease")
        prepare(root, run, path, args.reviewed_job_sha256,
                args.runtime_manifest, args.reviewed_runtime_sha256)
        print(json.dumps({"status": "prepared_cpu_only", "run_dir": str(run)}))
        return 0
    if not args.lease_json or not args.reviewed_lease_sha256:
        raise ValueError("external reviewed native-storyboard grant required")
    try:
        execute(root, run, path, args.reviewed_job_sha256,
                args.runtime_manifest, args.reviewed_runtime_sha256,
                args.lease_json, args.reviewed_lease_sha256)
    except BaseException as error:
        if (run / "execution-started.json").is_file():
            current = json_file(run / "status.json") if (run / "status.json").is_file() else {}
            if current.get("status") != "failed":
                status_write(run / "status.json", {"status": "failed", "phase": "preflight",
                    "error": f"{type(error).__name__}: {error}", "frames_completed": 0})
        raise
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"native storyboard job failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
