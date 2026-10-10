"""Private Wine runtime support checks; no Wine or GPU call."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

MODULE=Path(__file__).resolve().parents[1]/"evidence/fsr-lease-runner.py"
spec=importlib.util.spec_from_file_location("fsr_lease_runner_support",MODULE)
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

class WineSupportTests(TestCase):
    def fixture(self,root):
        wine=root/"win64"
        nls=wine/"usr/share/wine/nls/l_intl.nls"
        zlib=wine/"usr/x86_64-w64-mingw32/lib/zlib1.dll"
        nls.parent.mkdir(parents=True)
        zlib.parent.mkdir(parents=True)
        nls.write_bytes(b"verified-nls")
        zlib.write_bytes(b"verified-zlib")
        run=root/"run"
        (run/"prefix").mkdir(parents=True)
        return wine,nls,zlib,run

    def test_stage_and_verify_owned_support(self):
        with TemporaryDirectory() as temp:
            wine,nls,zlib,run=self.fixture(Path(temp))
            with mock.patch.object(runner,"WINROOT",wine), mock.patch.object(runner,"NLS_SHA",runner.digest(nls)), mock.patch.object(runner,"ZLIB_SHA",runner.digest(zlib)):
                runner.stage_wine_support(run)
                self.assertEqual((wine/"usr/share/wine/wine").readlink(),Path("."))
                target=run/"prefix/drive_c/windows/system32/zlib1.dll"
                self.assertEqual(target.read_bytes(),zlib.read_bytes())
                runner.verify_wine_support(run)
                target.write_bytes(b"drift")
                with self.assertRaises(ValueError):
                    runner.verify_wine_support(run)

    def test_rejects_prefix_directory_symlink(self):
        with TemporaryDirectory() as temp:
            wine,nls,zlib,run=self.fixture(Path(temp))
            with mock.patch.object(runner,"WINROOT",wine), mock.patch.object(runner,"NLS_SHA",runner.digest(nls)), mock.patch.object(runner,"ZLIB_SHA",runner.digest(zlib)):
                runner.stage_wine_support(run)
                drive=run/"prefix/drive_c"
                real=run/"prefix/drive_c-real"
                drive.rename(real)
                drive.symlink_to(real,target_is_directory=True)
                with self.assertRaisesRegex(ValueError,"symlink"):
                    runner.verify_wine_support(run)

    def test_prelaunch_rejects_process_prefix_owner_mismatch(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            run=root/"run"
            (run/"prefix").mkdir(parents=True)
            for name in ("app","logs","shaders","cache","config","data","tmp"):
                (run/name).mkdir()
            with mock.patch.object(runner.os,"geteuid",return_value=123456789), mock.patch.object(runner.os,"getegid",return_value=123456789):
                with self.assertRaisesRegex(ValueError,"owner"):
                    runner.verify_prelaunch(run,"a"*64)

    def test_rejects_untrusted_nls_alias_and_source_drift(self):
        with TemporaryDirectory() as temp:
            wine,nls,zlib,run=self.fixture(Path(temp))
            alias=wine/"usr/share/wine/wine"
            alias.symlink_to(Path(temp),target_is_directory=True)
            with mock.patch.object(runner,"WINROOT",wine), mock.patch.object(runner,"NLS_SHA",runner.digest(nls)), mock.patch.object(runner,"ZLIB_SHA",runner.digest(zlib)):
                with self.assertRaises(ValueError):
                    runner.stage_wine_support(run)
                alias.unlink()
                zlib.write_bytes(b"drift")
                with self.assertRaises(ValueError):
                    runner.stage_wine_support(run)
