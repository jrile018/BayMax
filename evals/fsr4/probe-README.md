# AMD FSR 4.1.1 signed-runtime DX12 probe

This is a single-process Windows diagnostic cross-built on the cloud host. It dynamically loads the unchanged official `amd_fidelityfx_loader_dx12.dll` and resolves all five C ABI entrypoints from SDK 2.3. It does not require the MSVC sample project, a swapchain, GUI, media inputs or SDK import libraries.

The four pinned official headers are under `platform/runtime/sdk/headers`. Their source manifest is adjacent. The original official prebuilt archive verified by parent orchestration is 127451548 bytes, SHA256 `f90890b9323bb2f4f2404ac4cdc9395e8495ecdac6f7aa0bcdf1ad1848422273`. Parent orchestration may transport only the individually verified signed DLL pair and pinned headers after checking the original archive; this probe does not modify DLLs.

## CPU-only build

Run `bash evals/fsr4/probe-build.sh` from the cloud checkout. The script builds/runs native CPU helper regressions, finds the isolated MinGW packages under `platform/runtime/win64/root`, and produces `evals/fsr4/probe-build/probe.exe`. No Wine, GPU query or graphics context is launched by this script. Link flags are C++17, O2, Wall/Wextra/Werror, municode, static C++/GCC runtime, d3d12/dxgi/dxguid. Official SDK headers are system includes; no copied ABI declarations or edited vendor headers are used.

The helper regressions first failed for the absent helper header, then passed after implementation. They reject wrong/incomplete version tokens (14.1.1, 4.1.10 and 4.1.1.2), reject invalid frame bounds, and exercise JSON control/quote/non-ASCII byte escaping.

## Authorized GPU run interface

Only the reviewed `platform/evidence/fsr-lease-runner.sh` may launch this probe, after the coordinator grants a fresh exclusive FSR lease. Prepare a new private run with the exact reviewed runner SHA, then launch the whole shell wrapper under the lease's specified temporary UID/GID and CPU affinity. The shell and Python runner enforce the wall deadline, dedicated Wine prefix cleanup, pinned payload hashes, and allocated render-node identity. Do not invoke Wine or the probe directly for a leased diagnostic.

The supervised runner supplies these probe arguments in both phases:

```text
probe.exe --query-only --adapter-device-id 744b --dll-dir Z:\\absolute\\cloud\\signed-dll-directory
probe.exe --dispatch --frames 3 --adapter-device-id 744b --dll-dir Z:\\absolute\\cloud\\signed-dll-directory
```

The `744b` PCI device ID must come from the external lease and match the host's allocated render node before launch. The probe filters the adapter by AMD vendor and the supplied PCI device ID before creating a D3D12 device; it fails if more than one matching hardware adapter is visible. A coordinator-pinned `--adapter-luid HEX64` may narrow that selection further. Modes are required and mutually exclusive. DLL directory must be an absolute drive path. Frames are bounded to 1..8. No provider ID is hard-coded.

JSONL stdout reports stages before operations, every HRESULT/FFX return code, adapter name/vendor/device/LUID, requested feature level 12_0, feature support, all returned provider IDs/names, SDK memory estimate, selected ID, and the context provider query. Loaded loader/upscaler paths must match the normalized absolute paths under the requested DLL directory; missing or unexpected modules fail before dispatch. Parent still verifies the exact observed file hashes/signatures. Names are copied before further SDK queries because the API documents reusable provider-global name storage. To produce valid JSON for arbitrary SDK strings, non-ASCII bytes use `\\u00XX` escapes; fields named `*_bytes` preserve bytes rather than assuming UTF-8. Wide Windows strings are converted to UTF-8 then escaped the same way.

The context chain includes `ffxCreateContextDescUpscale`, DX12 backend, returned 4.1.1 provider override and the mandatory `ffxCreateContextDescUpscaleVersion.version=FFX_UPSCALER_VERSION`. The memory query uses the same version override before creation. Missing/multiple target providers, failed queries, missing memory estimates, estimates above 1 GiB minus 4 MiB application allowance, and a mismatched context ID/name all fail closed. The estimate bounds requested allocations, not every possible driver/translation-layer allocation.

## Synthetic dispatch contract

The input is explicitly a **synthetic static plane minimal diagnostic**, not a frame from the project 3D camera. The fixed render size is 64x64 and output 96x96. Resources are application-owned linear RGBA32 float color, R32 float conventional finite perspective depth, RG32 float motion, 1x1 R32 float exposure=1, R8 zero reactive and composition masks, and RGBA32 float UAV output. SDK resource requirements are queried first, and unknown mandatory resources fail.

A static analytic color plane is sampled at jittered pixel centres using the SDK jitter phase/offset queries. Camera near/far are 0.1/100 metres, plane distance 2 metres, vertical FOV pi/3, conventional depth range 0..1, and viewSpaceToMeters=1. Static unjittered motion is zero; display-resolution/jitter-cancellation flags are unset. Frame time is 16.6667 ms, preExposure=1, sharpening disabled, reset on the first frame only. Color values are linear LDR and the HDR flag is unset. These choices represent a valid bounded static temporal input and expose API/translation failures; they do not establish project image quality.

Upload copies transition input resources to NON_PIXEL_SHADER_RESOURCE and output to UAV; imported FFX resources carry those matching states. The SDK restores external imports to supplied states. Output then receives a UAV barrier, transitions to COPY_SOURCE for readback, and returns to UAV. Each frame is submitted and fenced before allocator or upload memory reuse. A 60-second fence bound terminates the process without releasing in-flight resources on timeout/error.

Each frame fills output with -123 sentinels, submits real `ffxDispatch`, waits, checks device removal and reads only unpadded pixel rows. The report includes FNV-1a64 hash, changed/finite component counts and min/max. Success requires every component finite and changed from the sentinel. Hash is diagnostic, not cryptographic and not necessarily repeatable across driver implementations. No output image is presented as a quality comparison.

## Evidence interpretation and capture

`--query-only` exit 0 means the device, explicit 4.1.1 provider and retained context identity worked. It proves no upscaling dispatch. `--dispatch` exit 0 adds completed queue/fence/readback with changed finite output. **Neither automatically verifies ML execution.** Every result retains `ml_dispatch_verified:false` and `ml_evidence_status:unresolved_requires_shader_or_trace_discriminator`.

Parent orchestration should store separate `probe-query.stdout.jsonl`, `probe-query.stderr.log`, `probe-dispatch.stdout.jsonl`, `probe-dispatch.stderr.log`, their commands/environment manifest and exit status. Capture vkd3d-proton info/debug logs and shader dumps under an explicit `probe-shaders/` directory using the variables supported by the chosen vkd3d-proton build (e.g. `VKD3D_DEBUG`, `VKD3D_LOG_FILE`, `VKD3D_SHADER_DUMP_PATH` after confirming its README). Save Wine DLL loading diagnostics separately (`WINEDEBUG=+loaddll`) to prove loader/upscaler module paths. vkd3d-proton v3.0.1 remains the default; emulation changes belong to parent orchestration.

Inspect actual translated shader/trace evidence for a documented FSR4 ML discriminator and associate it with submitted work. A provider display name, a selected ID, successful context creation or changed output alone is insufficient. The public SDK does not supply a simple internal ML-path boolean. Preserve this unresolved status until evidence establishes the path. A DLL loading failure, missing provider or failed dispatch is a measured incompatibility, not a reason to patch the signed runtime or relabel a fallback as ML.

Primary API sources: [API guide](https://gpuopen.com/manuals/fsr_sdk/getting-started/ffx-api/), [SDK v2.3 upscaler header](https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/blob/v2.3.0/Kits/FidelityFX/upscalers/include/ffx_upscale.h), [DX12 header](https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/blob/v2.3.0/Kits/FidelityFX/api/include/dx12/ffx_api_dx12.h).

Saved JSONL can be checked without GPU access using `python3 evals/fsr4/probe-verify-json.py PATH --mode query-only|dispatch`. This checks report coherence and stage separation, not log authenticity or an ML path. Its five CPU contract regressions use temporary fabricated parser fixtures explicitly labelled as such; no fixture is saved as GPU evidence.
