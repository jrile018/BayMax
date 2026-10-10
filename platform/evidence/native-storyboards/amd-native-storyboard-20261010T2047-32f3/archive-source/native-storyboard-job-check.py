#!/usr/bin/env python3
"""CPU-only checks for the one-job native storyboard wrapper."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("storyboard_job", Path(__file__).with_name("native-storyboard-job.py"))
job = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(job)


class StoryboardJobChecks(unittest.TestCase):
    def test_help_exits_cleanly_without_graphics_import(self):
        result = subprocess.run([sys.executable, "-B",
            str(Path(__file__).with_name("native-storyboard-job.py")), "--help"],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--prepare-only", result.stdout)
        self.assertEqual(result.stderr, "")

    def lease(self):
        now = datetime.now(timezone.utc)
        return {
            "id": "native-test-grant", "scope": "native-storyboard", "gpu": "W7900D",
            "gpu_count": 1, "vram_cap_gib": 12, "cpu_cores": [0, 1],
            "pci_vendor_id": 0x1002, "pci_device_id": 0x744b,
            "max_diagnostic_seconds": 280, "uid": 65534, "gid": 993,
            "supplementary_groups": [], "render_node": "/dev/dri/renderD128",
            "job_sha256": "a" * 64, "runtime_manifest_sha256": "b" * 64,
            "start_utc": (now - timedelta(seconds=2)).isoformat(),
            "end_utc": (now + timedelta(seconds=400)).isoformat(),
            "head": job.HEAD, "run_limit": 1, "run_id": "fresh-one",
        }

    def test_lease_is_exact_and_fresh(self):
        lease = self.lease()
        check = lambda value: job.validate_lease(value, "fresh-one",
            expected_job_sha="a" * 64, expected_runtime_sha="b" * 64)
        check(lease)
        for key, bad in (("scope", "FSR"), ("gpu_count", 2), ("vram_cap_gib", 13),
                         ("cpu_cores", [0]), ("head", "0" * 40), ("run_limit", 2),
                         ("run_id", "another"), ("max_diagnostic_seconds", 281),
                         ("uid", 0), ("gid", 0), ("supplementary_groups", [993]),
                         ("render_node", "/dev/dri/renderD129"),
                         ("job_sha256", "c" * 64), ("runtime_manifest_sha256", "c" * 64)):
            wrong = dict(lease, **{key: bad})
            with self.subTest(key=key), self.assertRaises(ValueError):
                check(wrong)
        lease["end_utc"] = (datetime.now(timezone.utc) + timedelta(seconds=329)).isoformat()
        with self.assertRaises(ValueError):
            check(lease)

    def test_identity_and_inherited_display_rejected(self):
        with self.assertRaises(ValueError):
            job.require_identity(uid=0, gid=993, groups=[], affinity={0, 1})
        with self.assertRaises(ValueError):
            job.require_identity(uid=65534, gid=993, groups=[993], affinity={0, 1})
        with self.assertRaises(ValueError):
            job.reject_inherited_environment({"DISPLAY": ":99"})
        with self.assertRaises(ValueError):
            job.reject_inherited_environment({"TMPDIR": "/tmp"})

    def test_unique_run_marker_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "fresh-one"
            job.create_run_directory(run)
            with self.assertRaises(FileExistsError):
                job.create_run_directory(run)
            job.write_once(run / "execution-started.json", {"status": "started"})
            with self.assertRaises(FileExistsError):
                job.write_once(run / "execution-started.json", {"status": "started"})

    def test_sidecar_requires_hardware_mock_and_exact_frame(self):
        expected = {"run_id": "mock", "scenario_id": "mock", "time_s": 180,
                    "snapshot_hash": "a" * 64}
        sidecar = {
            "status": "rendered", "backend": "egl", "width": 1280, "height": 720,
            "output_written": True, "hardware_required": True, "software_detected": False,
            "provider": {"GL_VENDOR": "AMD", "GL_RENDERER": "AMD Radeon Pro W7900",
                         "GL_VERSION": "4.6"},
            "frame": expected,
            "replay": {"mode": "mock-replay", "geometry_status": "constructed mock geometry",
                       "identity": dict(expected, index=3, snapshot_version=1), "view_hash": "b" * 64},
        }
        job.validate_sidecar(sidecar, expected, "b" * 64)
        with self.assertRaises(ValueError):
            job.validate_sidecar(dict(sidecar, software_detected=True), expected, "b" * 64)
        with self.assertRaises(ValueError):
            job.validate_sidecar(dict(sidecar, provider=dict(sidecar["provider"], GL_VENDOR="Mesa")), expected, "b" * 64)
        with self.assertRaises(ValueError):
            job.validate_sidecar(dict(sidecar, replay=dict(sidecar["replay"], mode="live")), expected, "b" * 64)

    def test_only_three_fixed_frames(self):
        self.assertEqual(job.FRAMES, ((0, 0), (3, 180), (6, 360)))
        self.assertEqual(job.output_name(0, 0), "frame-00-000s.png")
        with self.assertRaises(ValueError):
            job.output_name(1, 60)
        rows = [{"index": i, "time_s": t} for i, t in job.FRAMES]
        self.assertTrue(job.validate_frame_results(rows))
        with self.assertRaises(ValueError):
            job.validate_frame_results(rows[:2])
        with self.assertRaises(ValueError):
            job.validate_frame_results(list(reversed(rows)))

    def test_hash_pin_rejects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact"
            path.write_bytes(b"frozen")
            good = job.sha256(path)
            self.assertEqual(job.pinned(path, good), good)
            path.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                job.pinned(path, good)

    def test_private_mesa_glvnd_environment_is_exact(self):
        manifest = {"pythonpath": ["/owned/python"], "ld_library_path": "/owned/lib",
                    "libgl_drivers_path": "/owned/dri", "egl_vendor_json": "/owned/50_mesa.json"}
        env = {"PYTHONPATH": "/owned/python", "LD_LIBRARY_PATH": "/owned/lib",
               "LIBGL_DRIVERS_PATH": "/owned/dri",
               "__EGL_VENDOR_LIBRARY_FILENAMES": "/owned/50_mesa.json",
               "MESA_SHADER_CACHE_DISABLE": "true"}
        job.validate_runtime_environment(manifest, env)
        with self.assertRaises(ValueError):
            job.validate_runtime_environment(manifest, dict(env, LIBGL_DRIVERS_PATH="/host/dri"))
        with self.assertRaises(ValueError):
            job.validate_runtime_environment(manifest, dict(env, MESA_SHADER_CACHE_DISABLE="false"))

    def test_binding_filters_extra_manifest_fields(self):
        source = {key: "x" for key in job._BINDING_FIELDS}
        source.update(index=3, time_s=180, unrelated="ignored")
        selected = job.binding_fields(source)
        self.assertEqual(set(selected), set(job._BINDING_FIELDS))
        self.assertNotIn("unrelated", selected)
        del source["snapshot_hash"]
        with self.assertRaises(ValueError):
            job.binding_fields(source)


if __name__ == "__main__":
    unittest.main()
