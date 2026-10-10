# Genuine FSR4 experiment — supplied Linux W7900 only

Status: prerequisite blocked; provider/runtime/ML dispatch not tested. No GPU lease. Root owns lease and final signoff. All work on supplied server.

## Verified prerequisite report

Command: /opt/venv/bin/python platform/graphics_probe.py --output platform/evidence/graphics-prerequisites-20261010.json in /workspace/knight26/worktrees/amd. Inventory does not import Torch or create GPU contexts. Ubuntu26.04/kernel6.8; cgroup16CPU/55GiB;25GiB workspace. C++/CMake/Ninja/Python exist. No Vulkan loader/ICD, EGL/GL/OSMesa, Wine, display server, renderer or encoder. Device nodes establish neither usable graphics nor GPU allocation. Root's separate ROCm compute evidence is not graphics evidence.

## Compatibility gates

| Gate | Evidence / current result |
|---|---|
| Allocation | Root allocated1 W7900D/gfx1100; accessible card1/renderD128; host sysfs visibility must not expand allocation. |
| Official hardware | AMD SDK2.3 supports RX7000/9000 discrete for FSR4.1.1; PRO W7900 not explicitly listed. Actual provider proof or AMD confirmation needed. |
| Official API/OS | Signed DX12 DLLs, SM6.6, Windows10/11; native Linux/Vulkan FSR4 not verified. |
| Translation | vkd3d-proton v3.0 default float8 path targets RDNA4+. Custom RDNA3 emulation has cost/correctness caveats, not W7900/4.1.1 proof. |
| Harness | No Wine/vkd3d or Windows sample. Official sample requires Windows/VS2022/vcpkg tooling absent here. No UE install proposed. |
| Model proof | No enumeration/context/dispatch. Version query alone cannot distinguish genuine ML from analytical fallback. |
| Replay | CPU geometry preparation only; no rendered frame or timings. |

## Smallest experiment and stop conditions

1. CPU preparation without GPU: inspect package manifest platform/evidence/package-candidates.txt. Ubuntu Vulkan loader1.4.341.0-1:157194 download bytes. Mesa Vulkan26.0.8-1ubuntu0.3:19109714 bytes/110216KiB installed excluding dependencies. Wine10.0~repack-12ubuntu1 and Xvfb21.1.22 candidates. Propose exclusive workspace extraction with resolved dependencies and SHA256; preserve system/image Torch/kernel driver. Check actual HF cache/storage before download. No package downloads in this checkpoint.
2. Root GPU lease request:10–15min after HF releases GPU; detached unique tmux,2CPU threads. Enumerate only allocated W7900, record Vulkan device/driver/API/extensions, shaderFloat8 and cooperative-matrix features. Stop on missing device or permissions. Vulkan success proves graphics capability only.
3. Optional C2 preparation, not a prerequisite to provider experiment: native replay smoke test under lease: offscreen allocated-device context, exact-frame scene output, PNG plus identity/source manifest. If unavailable report boundary; later authorized server CPU raster can provide an honestly labeled replay. Neither is FSR4.
4. FSR4 prerequisites: retain unchanged official SDK2.3.0 signed amd_fidelityfx_loader_dx12.dll and amd_fidelityfx_upscaler_dx12.dll, license and hashes. Minimal release about125MiB excluding media. Need existing built tiny official DX12 sample/harness; none is available. Pin Wine/vkd3d versions/build flags. Default RDNA4 path is not W7900 compatibility; custom emulation must be separately tested/disclosed. No DLL replacement/patch.
5. Provider experiment with separate root signoff: create DX12/SM6.6 device. Query ffxQueryDescGetVersions for actual device/upscale creation type; copy paired names/IDs. Select returned4.1.1 ID via ffxOverrideVersion, never hard-code ID. For SDK2.1+, chain ffxCreateContextDescUpscaleVersion with version=FFX_UPSCALER_VERSION separately from provider-ID override. Create context and query ffxQueryGetProviderVersion; record errors/callbacks. Fail if4.1.1 absent, context fails or analytical provider selected.
6. Valid dispatch inputs: the harness must provide current-frame linear color, float depth with declared depth flags, two-component motion vectors with explicit scale/resolution, camera jitter, exposure or auto-exposure, temporal reset/sequence policy and GPU resource states. Record formats/dimensions/flags; transition DX12 inputs to NON_PIXEL_SHADER_RESOURCE before dispatch. A color-only PNG is not a valid temporal FSR test. Model proof: require trustworthy trace distinguishing actual4.1.1 ML kernel/model dispatch from FSR3 fallback, signed-binary provenance and successful dispatch/output. No decisive public translation-model diagnostic verified. Ambiguous evidence remains FSR4 unproven even when provider reports4.1.1. Root resolves signoff. No fake success toggle.
7. After genuine gate passes: identical independent scene, replay/camera/settings;1920x1080 output, render size from quality API; frame generation off. Warm native/FSR paths, collect synchronized per-frame GPU and FSR-pass timings, median/p95 and end-to-end time, matched PNGs/temporal road-fire-trail readability. Preserve failures. No promised speedup or mixed CPU/GPU timing claim.

## Required owned evidence fields

Device/API/driver/runtime hashes; allocated node; SDK/DLL hashes/license; enumerated name-ID pairs/requested/selected ID/provider; context/dispatch return codes; quality and dimensions; framegeneration=false; model-proof trace source/hash; scenario/run/time/snapshot hash; scene hash; per-frame native/FSR GPU ms; PNG hashes; failures; root signoff. This is evidence, not a shared simulation schema.

## Primary references

- [AMD SDK hardware/platform](https://gpuopen.com/amd-fsr-sdk/)
- [FSR4.1.1 requirements](https://gpuopen.com/manuals/fsr_sdk/techniques/super-resolution-ml/)
- [FSR API signed DLLs/version/provider queries](https://gpuopen.com/manuals/fsr_sdk/getting-started/ffx-api/)
- [Official sample](https://gpuopen.com/manuals/fsr_sdk/samples/super-resolution/)
- [SDK2.3.0 release](https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/releases/tag/v2.3.0)
- [vkd3d-proton v3.0](https://github.com/HansKristian-Work/vkd3d-proton/releases/tag/v3.0)
- [RDNA3 emulation report, not W7900 validation](https://github.com/HansKristian-Work/vkd3d-proton/issues/2489)

## Actual leased prerequisite result — 2026-10-10T07:00:19Z

Coordinator granted07:00–07:20Z with12GiB maximum. The shortest prerequisite inventory completed and the lease was released unused at07:00:19Z. Vulkan loader/ICD and Wine/DX12 runtime remain absent. A prior detached two-CPU download of33 exact native graphics packages (32,818,418bytes) failed exit123 with repository network-unreachable/timeouts and downloaded zero packages. No graphics context, GPU work, provider query/context, FSR4 ML dispatch, project frame or native/FSR comparison ran. This is a prerequisite block, not a failed on-device FSR4 provider result.

Evidence: `platform/evidence/graphics-lease-result-20261010.json`, `graphics-lease-prerequisites-20261010.json`, `graphics-lease-diagnostic.log`, `native-runtime-packages.json`, and `native-runtime-prep.log`. No system/driver/Torch/network/auth/provider configuration was changed. Graphics dependencies must become available on the supplied cloud before another graphics lease. The private native EGL renderer preparation does not supply DX12 or satisfy FSR4.

For native renderer preparation only, primary PyPI metadata confirms Python3.14 Linuxx86_64 wheels for ModernGL5.13.0/glcontext3.1.0; future installation pins exact hashes in `platform/native-runtime-requirements.txt`. They are not downloaded or installed. Their availability is not a graphics-device or FSR provider test. Sources: https://pypi.org/project/moderngl/5.13.0/#files and https://pypi.org/project/glcontext/3.1.0/#files .
