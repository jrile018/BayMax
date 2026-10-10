"""CPU-only FSR lease runner guards; subprocess calls are mocked, Wine is never started."""
import importlib.util
from contextlib import ExitStack
import json
import os
from datetime import datetime,timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

MODULE=Path(__file__).with_name("fsr-lease-runner.py")
spec=importlib.util.spec_from_file_location("fsr_lease_runner",MODULE)
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

def lease(end="2026-10-10T08:10:00Z"):
    return {"id":"Observer02-test","scope":"FSR","gpu":"W7900D","gpu_count":1,"cpu_cores":[0,1],
        "vram_cap_gib":12,"pci_vendor_id":4098,"pci_device_id":0x744b,
        "start_utc":"2026-10-10T07:59:00Z","end_utc":end}

class FrozenClock:
    now_value=datetime(2026,10,10,8,0,tzinfo=timezone.utc)
    @staticmethod
    def fromisoformat(value): return datetime.fromisoformat(value)
    @classmethod
    def now(cls,tz): return cls.now_value

class FsrRunnerTests(unittest.TestCase):
    def setUp(self):
        FrozenClock.now_value=datetime(2026,10,10,8,0,tzinfo=timezone.utc)

    def test_lease_scope_resource_and_freshness(self):
        now=datetime(2026,10,10,8,0,tzinfo=timezone.utc)
        self.assertEqual(runner.validate_lease(lease(),now=now)["id"],"Observer02-test")
        for key,value in (("scope","native"),("gpu","other"),("gpu_count",2),("cpu_cores",[0,1,2]),
            ("vram_cap_gib",13),("pci_vendor_id",4318),("pci_device_id",0x73bf)):
            bad=lease(); bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                runner.validate_lease(bad,now=now)
        with self.assertRaises(ValueError):
            runner.validate_lease(lease("2026-10-10T08:02:59Z"),now=now)

    def test_run_id_and_symlink_escape(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            evidence=Path(tempdir)/"evidence"; evidence.mkdir()
            runs=evidence/"fsr-runs"
            with mock.patch.object(runner,"EVIDENCE",evidence),mock.patch.object(runner,"RUNS",runs):
                for bad in ("../escape","..","/absolute","a/b"):
                    with self.subTest(run_id=bad),self.assertRaises(ValueError):
                        runner.run_dir_for(bad,create=True)
                good=runner.run_dir_for("fresh_001",create=True)
                self.assertEqual(good.parent,runs)
                with self.assertRaises(FileExistsError):
                    runner.run_dir_for("fresh_001",create=True)
                outside=Path(tempdir)/"outside"; outside.mkdir()
                (runs/"evil").symlink_to(outside,target_is_directory=True)
                with self.assertRaises(ValueError):
                    runner.run_dir_for("evil")

    def test_source_freeze_detects_drift(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            root=Path(tempdir)
            paths=[root/name for name in ("runner.py","probe.cpp","probe.exe","validator.py")]
            for path,content in zip(paths,(b"runner",b"source",b"executable",b"validator")):
                path.write_bytes(content)
            patches={"ROOT":root,"RUNNER":paths[0],"PROBE_SOURCE":paths[1],"PROBE_EXE":paths[2],
                "VALIDATOR":paths[3],"SOURCE_FILES":tuple(paths),
                "PROBE_SOURCE_SHA":runner.digest(paths[1]),"PROBE_EXE_SHA":runner.digest(paths[2]),
                "VALIDATOR_SHA":runner.digest(paths[3])}
            with ExitStack() as stack:
                for name,value in patches.items(): stack.enter_context(mock.patch.object(runner,name,value))
                reviewed=runner.digest(paths[0])
                files=runner.source_hashes(reviewed)
                self.assertEqual(files["validator.py"],runner.digest(paths[3]))
                (root/"source-freeze.json").write_text(json.dumps({"files":files,"reviewed_runner_sha256":reviewed}))
                runner.verify_source_freeze(root,reviewed)
                paths[3].write_bytes(b"validator drift")
                with self.assertRaises(ValueError):
                    runner.verify_source_freeze(root,reviewed)

    def test_stale_install_status_cannot_authorize_preparation(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            root=Path(tempdir); evidence=root/"evidence"; evidence.mkdir()
            (evidence/"win64-runtime-offline-status.json").write_text(json.dumps({
                "archive_sha256_verified":True,"extracted_package_count":145,"expected_package_count":145}))
            with mock.patch.object(runner,"EVIDENCE",evidence),mock.patch.object(runner,"WINROOT",root/"win64/root"):
                with self.assertRaises(ValueError):
                    runner.check_win64_status()

    def test_payload_copy_hash_mismatch(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            root=Path(tempdir); source=root/"source.dll"; source.write_bytes(b"correct")
            app=root/"app"; app.mkdir(); (app/"source.dll").write_bytes(b"wrong")
            with self.assertRaises(ValueError):
                runner.verify_payloads({"source.dll":(source,runner.digest(source))},app)

    def run_fixture(self,root):
        run=root/"run"; run.mkdir()
        for name in ("app","logs","shaders","prefix","home","cache","config","data","tmp"):
            (run/name).mkdir()
        (run/"source-freeze.json").write_text("{}")
        lease_path=root/"lease.json"; lease_path.write_text(json.dumps(lease()))
        wine={"wine64":"/private/wine64","wineserver":"/private/wineserver",
            "x86_64-unix":"/private/unix","x86_64-windows":"/private/windows"}
        return run,lease_path,wine

    def test_expired_lease_blocks_first_wine_call(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            run,lease_path,wine=self.run_fixture(Path(tempdir))
            FrozenClock.now_value=datetime(2026,10,10,8,8,tzinfo=timezone.utc)
            report={"phases":{}}
            with mock.patch.object(runner,"datetime",FrozenClock),mock.patch.object(runner,"verify_prelaunch",return_value=wine),mock.patch.object(runner,"verify_host_device",return_value={}),mock.patch.object(runner,"run_probe") as wine_call:
                with self.assertRaises(ValueError):
                    runner.run_phase("query-only",run,lease_path,"a"*64,report)
                wine_call.assert_not_called()

    def test_lease_rechecked_before_dispatch(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            run,lease_path,wine=self.run_fixture(Path(tempdir))
            report={"phases":{}}
            result=SimpleNamespace(stdout="mock query",stderr="mock diagnostic",returncode=0)
            with mock.patch.object(runner,"datetime",FrozenClock),mock.patch.object(runner,"verify_prelaunch",return_value=wine),mock.patch.object(runner,"verify_host_device",return_value={}),mock.patch.object(runner,"query_proof",return_value={"provider_id":"mock"}),mock.patch.object(runner,"run_probe",return_value=result) as wine_call:
                runner.run_phase("query-only",run,lease_path,"a"*64,report)
                FrozenClock.now_value=datetime(2026,10,10,8,8,tzinfo=timezone.utc)
                with self.assertRaises(ValueError):
                    runner.run_phase("dispatch",run,lease_path,"a"*64,report)
                self.assertEqual(wine_call.call_count,1)

    def test_lease_expires_during_final_hash_check_before_wine(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            run,lease_path,wine=self.run_fixture(Path(tempdir))
            report={"phases":{}}
            calls={"count":0}
            def hash_check(*args):
                calls["count"]+=1
                if calls["count"]==2:
                    FrozenClock.now_value=datetime(2026,10,10,8,8,tzinfo=timezone.utc)
                return wine
            with mock.patch.object(runner,"datetime",FrozenClock),mock.patch.object(runner,"verify_prelaunch",side_effect=hash_check),mock.patch.object(runner,"verify_host_device",return_value={}),mock.patch.object(runner,"query_proof",return_value={"provider_id":"mock"}),mock.patch.object(runner,"run_probe",return_value=SimpleNamespace(stdout="mock",stderr="",returncode=0)) as wine_call:
                with self.assertRaises(ValueError):
                    runner.run_phase("query-only",run,lease_path,"a"*64,report)
                wine_call.assert_not_called()
            self.assertFalse(report["phases"]["query"]["attempted"])

    def test_context_provider_must_match_411_provider(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            path=Path(tempdir)/"query.jsonl"
            events=[
                {"event":"adapter","luid":"0x1","vendor_id":4098,"device_id":0x744b,"name_utf8_bytes":"AMD Radeon PRO W7900D","software":False},
                {"event":"selected_adapter","luid":"0x1","name_utf8_bytes":"AMD Radeon PRO W7900D"},
                {"event":"module_path_verification","name_utf8_bytes":"amd_fidelityfx_loader_dx12.dll","matches_expected":True},
                {"event":"module_path_verification","name_utf8_bytes":"amd_fidelityfx_upscaler_dx12.dll","matches_expected":True},
                {"event":"provider","id":"0x7","name_bytes":"AMD FSR 4.1.1"},
                {"event":"provider","id":"0x8","name_bytes":"generic"},
                {"event":"context_provider","id":"0x8","selected_id_matches":True},
                {"event":"result","context_provider_verified":True,"dispatch_readback_completed":False,"ml_dispatch_verified":False}
            ]
            path.write_text("\n".join(json.dumps(row) for row in events)+"\n")
            with self.assertRaises(ValueError):
                runner.query_proof(path,lease())

    def test_query_timeout_receipt_records_attempt_without_completion(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            run,lease_path,wine=self.run_fixture(Path(tempdir))
            report={"phases":{}}
            error=subprocess.TimeoutExpired(cmd=["mock wine"],timeout=120,output=b"partial",stderr=b"timeout")
            with mock.patch.object(runner,"datetime",FrozenClock),mock.patch.object(runner,"verify_prelaunch",return_value=wine),mock.patch.object(runner,"verify_host_device",return_value={}),mock.patch.object(runner,"run_probe",side_effect=error) as wine_call:
                with self.assertRaises(subprocess.TimeoutExpired):
                    runner.run_phase("query-only",run,lease_path,"a"*64,report)
                wine_call.assert_called_once()
            phase=json.loads((run/"logs/query.exit.json").read_text())
            self.assertTrue(phase["attempted"])
            self.assertFalse(phase["completed"])
            self.assertEqual(phase["exit_code"],"timeout")
            self.assertIn("partial",(run/"logs/query.stdout.jsonl").read_text())

    def test_cpu_preparation_freezes_sources_and_copies_verified_payloads(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            root=Path(tempdir); evidence=root/"platform/evidence"; evidence.mkdir(parents=True)
            source=root/"evals/fsr4/probe.cpp"; source.parent.mkdir(parents=True)
            executable=root/"evals/fsr4/probe-build/probe.exe"; executable.parent.mkdir()
            validator=root/"evals/fsr4/probe-verify-json.py"
            own=evidence/"fsr-lease-runner.py"
            sdk=root/"platform/runtime/sdk"; sdk.mkdir(parents=True)
            mesa=root/"platform/runtime/root"
            icd=mesa/"usr/share/vulkan/icd.d/radeon_icd.json"; icd.parent.mkdir(parents=True)
            files=((own,b"reviewed runner"),(source,b"reviewed probe source"),(executable,b"reviewed probe executable"),
                (sdk/"vendor.dll",b"verified vendor payload"),(icd,b"private icd"),(validator,b"reviewed validator"))
            for path,content in files: path.write_bytes(content)
            for name in ("fsr-sdk-dll-stage.json","dx12-bridge-stage.json"):
                (evidence/name).write_text("{}")
            wine={"wine64":"/private/wine64","wineserver":"/private/wineserver",
                "x86_64-unix":"/private/unix","x86_64-windows":"/private/windows"}
            payloads={"vendor.dll":(sdk/"vendor.dll",runner.digest(sdk/"vendor.dll"))}
            patches={"ROOT":root,"EVIDENCE":evidence,"RUNS":evidence/"fsr-runs",
                "RUNNER":own,"PROBE_SOURCE":source,"PROBE_EXE":executable,"VALIDATOR":validator,
                "SOURCE_FILES":(own,source,executable,validator),"SDK":sdk,"MESA":mesa,
                "PROBE_SOURCE_SHA":runner.digest(source),"PROBE_EXE_SHA":runner.digest(executable),
                "VALIDATOR_SHA":runner.digest(validator)}
            with ExitStack() as stack:
                for name,value in patches.items(): stack.enter_context(mock.patch.object(runner,name,value))
                stack.enter_context(mock.patch.object(runner,"check_win64_status",return_value={"verified":True}))
                stack.enter_context(mock.patch.object(runner,"discover_wine",return_value=wine))
                stack.enter_context(mock.patch.object(runner,"payload_records",return_value=payloads))
                stack.enter_context(mock.patch.object(runner,"stage_wine_support",return_value={"nls_sha256":"test","zlib_sha256":"test"}))
                stack.enter_context(mock.patch.object(runner,"verify_wine_support",return_value={"nls_sha256":"test","zlib_sha256":"test"}))
                reviewed=runner.digest(own)
                run=runner.prepare("fresh001",reviewed)
                self.assertEqual((run/"app/probe.exe").read_bytes(),b"reviewed probe executable")
                self.assertEqual((run/"app/vendor.dll").read_bytes(),b"verified vendor payload")
                self.assertEqual(json.loads((run/"source-freeze.json").read_text())["reviewed_runner_sha256"],reviewed)
                runner.verify_prelaunch(run,reviewed)
                (run/"app/vendor.dll").write_bytes(b"tampered")
                with self.assertRaises(ValueError):
                    runner.verify_prelaunch(run,reviewed)

    def test_coherent_query_proof_requires_actual_amd_and_signed_modules(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            path=Path(tempdir)/"query.jsonl"
            events=[
                {"event":"adapter","luid":"0x1","vendor_id":4098,"device_id":0x744b,"name_utf8_bytes":"AMD Radeon PRO W7900D","software":False},
                {"event":"selected_adapter","luid":"0x1","name_utf8_bytes":"AMD Radeon PRO W7900D"},
                {"event":"module_path_verification","name_utf8_bytes":"amd_fidelityfx_loader_dx12.dll","matches_expected":True},
                {"event":"module_path_verification","name_utf8_bytes":"amd_fidelityfx_upscaler_dx12.dll","matches_expected":True},
                {"event":"provider","id":"0x7","name_bytes":"AMD FSR 4.1.1"},
                {"event":"context_provider","id":"0x7","selected_id_matches":True},
                {"event":"result","context_provider_verified":True,"dispatch_readback_completed":False,"ml_dispatch_verified":False}
            ]
            path.write_text("\n".join(json.dumps(row) for row in events)+"\n")
            proof=runner.query_proof(path,lease())
            self.assertEqual(proof["provider_id"],"0x7")
            events[0]["software"]=True
            path.write_text("\n".join(json.dumps(row) for row in events)+"\n")
            with self.assertRaises(ValueError):
                runner.query_proof(path,lease())

    def test_shader_audit_hashes_owned_dumps_without_claiming_ml(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            run=Path(tempdir); (run/"shaders/dispatch").mkdir(parents=True); (run/"logs").mkdir()
            shader=run/"shaders/dispatch/one.spv"; shader.write_bytes(b"shader bytes")
            audit=runner.audit_shaders(run)
            self.assertEqual(audit["files"][0]["sha256"],runner.digest(shader))
            self.assertFalse(audit["ml_dispatch_verified"])
            self.assertTrue((run/"logs/shader-audit.json").is_file())

    def test_dispatch_requires_its_own_matching_hardware_signed_modules_and_provider(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            path=Path(tempdir)/"dispatch.jsonl"
            base=[
                {"event":"adapter","luid":"0x1","vendor_id":4098,"device_id":0x744b,"name_utf8_bytes":"AMD Radeon PRO W7900D","software":False},
                {"event":"selected_adapter","luid":"0x1","name_utf8_bytes":"AMD Radeon PRO W7900D"},
                {"event":"module_path_verification","name_utf8_bytes":"amd_fidelityfx_loader_dx12.dll","matches_expected":True},
                {"event":"module_path_verification","name_utf8_bytes":"amd_fidelityfx_upscaler_dx12.dll","matches_expected":True},
                {"event":"provider","id":"0x7","name_bytes":"AMD FSR 4.1.1"},
                {"event":"context_provider","id":"0x7","selected_id_matches":True},
            ]
            for frame in range(3):
                base.append({"event":"api","api":"ffxDispatch synthetic upscale","ffx_code":0})
                base.append({"event":"dispatch_readback","frame":frame,"changed_components":96*96*4,"finite_components":96*96*4})
            base.append({"event":"result","context_provider_verified":True,"dispatch_readback_completed":True,"ml_dispatch_verified":False})
            query={"amd_adapter_luid":"0x1","pci_device_id":0x744b,"provider_id":"0x7"}
            def check(events):
                path.write_text("\n".join(json.dumps(row) for row in events)+"\n")
                return runner.dispatch_proof(path,query,lease())
            self.assertEqual(check(base)["dispatch_frames"],3)
            cases=(
                (0,{"vendor_id":4318}),
                (1,{"luid":"0x2"}),
                (2,{"matches_expected":False}),
                (4,{"name_bytes":"generic provider"}),
                (5,{"id":"0x8"}),
            )
            for index,change in cases:
                events=[dict(row) for row in base]
                events[index].update(change)
                with self.subTest(case=change),self.assertRaises(ValueError):
                    check(events)

    def test_validator_hash_drift_blocks_import(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            validator=Path(tempdir)/"validator.py"
            validator.write_text("raise RuntimeError('untrusted validator executed')\n")
            with mock.patch.object(runner,"VALIDATOR",validator):
                with self.assertRaises(ValueError):
                    runner.load_probe_validator()

    def test_private_environment_preserves_inherited_home(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            run,_,wine=self.run_fixture(Path(tempdir))
            with mock.patch.dict(os.environ,{"HOME":"/inherited/home"}):
                env=runner.private_env(run,wine,"query")
            self.assertEqual(env["HOME"],"/inherited/home")

    def test_hostile_inherited_overrides_are_absent_from_wine_environment(self):
        hostile={"VKD3D_SHADER_OVERRIDE":"/tmp/replacement.spv","VKD3D_FEATURE_LEVEL":"12_2",
            "VKD3D_CONFIG":"force_static_cbv","LD_PRELOAD":"/tmp/inject.so","LD_AUDIT":"/tmp/audit.so",
            "VK_INSTANCE_LAYERS":"VK_LAYER_FAKE","VK_LAYER_PATH":"/tmp/layers",
            "VK_ADD_LAYER_PATH":"/tmp/add-layers","VK_LOADER_LAYERS_ENABLE":"*",
            "VK_LOADER_LAYERS_DISABLE":"~implicit~"}
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            run,_,wine=self.run_fixture(Path(tempdir))
            with mock.patch.dict(os.environ,hostile):
                env=runner.private_env(run,wine,"query")
            for key in hostile:
                with self.subTest(key=key):
                    self.assertNotIn(key,env)
            self.assertEqual(env["MESA_SHADER_CACHE_DISABLE"],"true")
            self.assertEqual(env["VKD3D_SHADER_CACHE_PATH"],"0")
            for key in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"):
                self.assertEqual(env[key],"2")

    def test_shell_prelaunch_failure_never_spawns_wineserver_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            root=Path(tempdir)
            run=root/"platform/evidence/fsr-runs/fresh001"
            (run/"prefix").mkdir(parents=True)
            server=root/"platform/runtime/win64/root/usr/lib/x86_64-linux-gnu/wine/wineserver"
            server.parent.mkdir(parents=True)
            marker=root/"cleanup-called"
            env_marker=root/"cleanup-override"
            threads_marker=root/"cleanup-threads"
            server.write_text("#!/bin/sh\nprintf called > '"+str(marker)+"'\nprintenv VKD3D_SHADER_OVERRIDE > '"+str(env_marker)+"'\nprintf '%s,%s,%s' \"$OMP_NUM_THREADS\" \"$OPENBLAS_NUM_THREADS\" \"$MKL_NUM_THREADS\" > '"+str(threads_marker)+"'\n")
            server.chmod(0o755)
            original=runner.RUNNER.with_suffix(".sh").read_text()
            wrapper=root/"wrapper.sh"
            wrapper.write_text(original.replace("/workspace/knight26/worktrees/amd",str(root)))
            env=dict(os.environ,FSR_RUN_ID="fresh001",FSR_LEASE_JSON=str(root/"missing-lease.json"),
                FSR_REVIEWED_RUNNER_SHA256="a"*64,VKD3D_SHADER_OVERRIDE="/tmp/replacement.spv")
            result=subprocess.run(["bash",str(wrapper)],env=env,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(marker.exists(),"wineserver cleanup ran before any attempted Wine phase")
            receipt=run/"execute-runner.json"
            receipt.write_text(json.dumps({"run_id":"fresh001","phases":{"query":{"attempted":True}}}))
            (run/"shell.log").unlink()
            stale=subprocess.run(["bash",str(wrapper)],env=env,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(stale.returncode,0)
            self.assertFalse(marker.exists(),"stale receipt must not authorize wineserver cleanup")
            self.assertEqual(receipt.read_text(),json.dumps({"run_id":"fresh001","phases":{"query":{"attempted":True}}}))
            receipt.unlink()
            outside=root/"outside-receipt.json"
            outside.write_text(json.dumps({"run_id":"fresh001","phases":{"query":{"attempted":True}}}))
            for target in (outside,root/"dangling-receipt.json"):
                with self.subTest(receipt_symlink_target=target):
                    receipt.symlink_to(target)
                    rejected=subprocess.run(["bash",str(wrapper)],env=env,capture_output=True,text=True,timeout=10)
                    self.assertNotEqual(rejected.returncode,0)
                    self.assertFalse(marker.exists(),"symlink receipt must not authorize cleanup")
                    receipt.unlink()
            stub=root/"current-child.py"
            stub.write_text("import json\nfrom pathlib import Path\nPath("+repr(str(receipt))+").write_text(json.dumps("+repr({"run_id":"fresh001","phases":{"query":{"attempted":True}}})+"))\nraise SystemExit(17)\n")
            wrapper.write_text(original.replace("/workspace/knight26/worktrees/amd",str(root)).replace(
                "platform/evidence/fsr-lease-runner.py --execute-authorized-lease",
                str(stub)+" --execute-authorized-lease"))
            current=subprocess.run(["bash",str(wrapper)],env=env,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(current.returncode,0)
            self.assertTrue(marker.exists(),"dedicated cleanup should run after current child attempt")
            self.assertEqual(env_marker.read_text(),"","cleanup must not inherit shader override")
            self.assertEqual(threads_marker.read_text(),"2,2,2")

    def test_shell_execution_budget_reserves_cleanup_time(self):
        now=datetime(2026,10,10,8,0,tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            runner.validate_lease(lease("2026-10-10T08:05:00Z"),now=now,min_remaining=330)

    def test_query_proof_rejects_missing_actual_provider(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            output=Path(tempdir)/"query.jsonl"
            output.write_text('{"event":"result","context_provider_verified":true,"dispatch_readback_completed":false,"ml_dispatch_verified":false}\n')
            with self.assertRaises(ValueError):
                runner.query_proof(output,lease())

    def test_wrong_amd_pci_device_and_model_cannot_prove_query(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            path=Path(tempdir)/"query.jsonl"
            events=[
                {"event":"adapter","luid":"0000000000000001","vendor_id":4098,
                    "device_id":0x73bf,"name_utf8_bytes":"AMD Radeon RX 6800","software":False},
                {"event":"selected_adapter","luid":"0000000000000001",
                    "name_utf8_bytes":"AMD Radeon RX 6800"},
                {"event":"module_path_verification","name_utf8_bytes":"amd_fidelityfx_loader_dx12.dll","matches_expected":True},
                {"event":"module_path_verification","name_utf8_bytes":"amd_fidelityfx_upscaler_dx12.dll","matches_expected":True},
                {"event":"provider","id":"0x7","name_bytes":"AMD FSR 4.1.1"},
                {"event":"context_provider","id":"0x7","selected_id_matches":True},
                {"event":"result","context_provider_verified":True,"dispatch_readback_completed":False,"ml_dispatch_verified":False}]
            path.write_text("\n".join(json.dumps(row) for row in events)+"\n")
            with self.assertRaisesRegex(ValueError,"leased W7900D"):
                runner.query_proof(path,lease())

    def test_direct_execute_rejects_unsupervised_identity_and_affinity(self):
        with mock.patch.object(runner.os,"geteuid",return_value=0), \
            mock.patch.object(runner.os,"getegid",return_value=0):
            with self.assertRaisesRegex(ValueError,"isolated UID"):
                runner.require_execution_envelope()
        with mock.patch.object(runner.os,"geteuid",return_value=65534), \
            mock.patch.object(runner.os,"getegid",return_value=993), \
            mock.patch.object(runner.os,"getgroups",return_value=[]), \
            mock.patch.object(runner.os,"sched_getaffinity",return_value={0,1,2}):
            with self.assertRaisesRegex(ValueError,"affinity"):
                runner.require_execution_envelope()

    def test_host_render_node_must_match_external_pci_lease(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            node=Path(tempdir)
            (node/"vendor").write_text("0x1002\n")
            (node/"device").write_text("0x73bf\n")
            with mock.patch.object(runner,"RENDER_DEVICE",node):
                with self.assertRaisesRegex(ValueError,"differs"):
                    runner.verify_host_device(lease())
                (node/"device").write_text("0x744b\n")
                self.assertEqual(runner.verify_host_device(lease())["pci_device_id"],0x744b)

    def test_probe_command_pins_lease_device_before_wine(self):
        with tempfile.TemporaryDirectory(prefix="fsr-lease-test-") as tempdir:
            run,lease_path,wine=self.run_fixture(Path(tempdir))
            report={"phases":{}}
            result=SimpleNamespace(stdout="mock query",stderr="",returncode=0)
            with mock.patch.object(runner,"datetime",FrozenClock), \
                mock.patch.object(runner,"verify_prelaunch",return_value=wine), \
                mock.patch.object(runner,"verify_host_device",return_value={}), \
                mock.patch.object(runner,"query_proof",return_value={"provider_id":"mock"}), \
                mock.patch.object(runner,"run_probe",return_value=result) as call:
                runner.run_phase("query-only",run,lease_path,"a"*64,report)
            command=call.call_args.args[0]
            self.assertEqual(command[command.index("--adapter-device-id")+1],"744b")

if __name__=="__main__":
    unittest.main()
