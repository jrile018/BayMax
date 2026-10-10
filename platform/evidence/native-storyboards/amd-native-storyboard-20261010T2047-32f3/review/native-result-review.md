# Independent native storyboard result review

**PASS_SCOPED_NATIVE_RESULT_REVIEW.** The original artifacts establish one successful three-frame mock replay capture through the reviewed native EGL path on the reported AMD W7900D provider. The result document is faithful within that scope. No blocking result mismatch or overclaim found. This does not establish FSR, ML, equal-depth correctness, polished presentation, real incident integration, or measured peak VRAM.

Independent GPT-6.1-Sol/high review on 2026-10-10. Only this report was written. After the parent confirmed SCP completion, I freshly hashed local copies, inspected original PNGs and selected sidecar fields, and performed CPU-only Pillow verification/full decoding. No remote command, GPU, Wine, graphics context, product edit, image edit, publication or foreign-job operation occurred.

## Exact reviewed evidence

Run `amd-native-storyboard-20261010T2047-32f3`; source HEAD `32f3b6f6d371db824294b92092e5dda6eaacd63c`, final job `60f4f3c355ae94d89642c4a4cba0d43460b9c5f3a9b911ea73024f9889f07de1`, selected runtime `3dfe6bebf1788b3e9078db3457d15b17e0b22113550e9c626237c2f5346cb8c8`, reviewed launcher `8ab34b60b63bc0d617d333f5e7bc6cdc3111fc66f7f18197d1d9abcb5e73299d`.

Fresh local hashes:

| Evidence | SHA-256 |
|---|---|
| `NATIVE_RESULT.md` | `888b253ba118cb531cf7836117ffd3524c4675e1535eee8ca37c720638d2e0c9` |
| `NATIVE_PASSIVE_READBACK.json` | `aecc82c1938dfe74acbbc2a32422c86127efb84266956241fee7c3d1ed6fd727` |
| `native-result/controller-hashes.json` | `1bf1d5d918065d2aa16f8984e9637118cbc3690023145b95be734c0c32667a6f` |
| Local original grant | `9a680cda0f58a813257fefe68e82a36bcf8df89fdd17aef01d5f5dca7c205088` |
| Success receipt | `3e76d810fb7da8ecf0f2967bf9e1d0a496f2079fa33b1299cdf0f80eee0273a9` |
| Status | `74118de8cfc332c4c85ad17b3ff8aac5024f0cf931de1f612097c01ca30a714f` |
| Execution marker | `52a6b9ed57b0ec875140980595c48da019e751679c6ab30409d827ea52d78d62` |
| Outer execute receipt | `648e79e1b9697307c9f3c2e64a42bfc74618b5f4ac2b4e1ed11ecf5e6ad2c4ea` |
| Execute log | `68f49249cf02da34d5d94ab57a613280ad25cf966ab78df97858ab1cb1c78071` |
| Tmux shell log | `5c69d8f1c16a0c44392d0f4d925f56ca418baaef148021b2cff02746448d150f` |
| Mock README | `db41c77c0560924808c6741cd6e306deabfa4e31f3f8eb9b3db044eddfc3ca9e` |
| Prepared receipt | `0b7b072f2ef0a2f98d3e7f11d538e69bd75c2a6272077759d825a3d94338f7e8` |
| Source/runtime/frame freeze | `bf3fe737c484af59d37ede5286658137e0f7eda836a8f31c1be4ce1ce15f146e` |
| Outer preparation receipt | `2c2fb2f67db0d785de5afb514c1e710c42216acfcf1962ad180ed8940d336525` |
| Preparation log | `076972000daab19e00563a2fd50be9cde2bb14dc8e91a9bf2b3bf2c168ba0f23` |
| Grant preflight, local copy | `6c95050a444396014a8c235e5bb8336923a70333ec97c2d532d4e65ba461276d` |

Every one of the 15 result files in the saved passive cloud-readback map matched my independent local rehash, including the six frame PNG/JSON files below. The two outer preparation files also match the prior independently reviewed CPU preparation cloud hashes. At inspection, the grant-preflight copy had a verified local checksum but its fresh remote checksum audit was still pending; the controller list correctly marks that item `matched_remote=false`. The saved remote process/device observations are parent-provided passive readback, not live hardware operations by this reviewer.

## Run, authorization and output coherence

The grant and marker bind `amd-native-reviewed-20261010T205203Z`, native-storyboard scope, one attempt, exact reviewed run/job/runtime/source, UID65534/GID993/groups[], CPUs0,1, renderD128 and PCI4098:29771. Grant interval20:52:03–21:07:03Z includes the actual execution and provides more than330 seconds remaining. The marker records20:54:49.083017Z. Outer receipt is exit0,20:54:49.030236–20:54:50.035220Z,1.004984 seconds elapsed, with the reviewed clean `env -i`, private runtime fields, two-thread settings, identity/affinity chain and280-second timeout/kill-after5-second envelope.

Success receipt/status/README/marker/freeze hashes refer to the actual matching files. The immutable prepared source/runtime/frame freeze is unchanged from the earlier CPU preparation. The receipt contains exactly three ordered completed frames, `mock_replay=true`, the actual PCI tuple and the same provider as each sidecar. No failure receipt substitutes for a completed frame. Native-call elapsed times0.138114,0.081641,0.076506 seconds and total job rendering section0.326603 seconds are measured process wall times, not GPU-only timing or a benchmark.

Each sidecar records `rendered`, `egl`,1280×720, `output_written=true`, `hardware_required=true`, `software_detected=false`, `GL_VENDOR=AMD`, `GL_RENDERER=AMD Radeon Pro W7900D (radeonsi, navi31, ACO, DRM 3.64, 6.8.0-79-generic)`, and `GL_VERSION=4.6 (Core Profile) Mesa 26.0.8-1ubuntu0.3`. Frame identity, replay index/time/snapshot version, canonical snapshot hash and prepared view hash match the prepared freeze for all three. All retain `maps-mock-001`, `paradise-constructed-ui-exercise`, `mock-replay`, and constructed-illustration geometry wording. Sidecars state FSR is not implemented and the lease is caller-managed. Their camera/bounds are identical across frames.

| Index/time | PNG SHA-256 | Sidecar SHA-256 |
|---|---|---|
| 0 / 0s | `153e779d791c32c1b7e95aad49ef965b7fd2355e5c8dffd99ef9c377fe299a91` | `546c35cd42290ffcdeec38b30d555be55245b86ad13b7883dc84ab27cd85e715` |
| 3 / 180s | `511d725c34820067e2610c7f642b73240b31e9152eb33af9c71cdfc2c128aee7` | `3568396fc21a6d9a3399d846e270b8afc1a3ac9433569b1e3ee07f9ec474f39a` |
| 6 / 360s | `b8bad5f69536ebe24a6592810ab3ec8710341825f10cc47f5d0c2d51dbeedbe8` | `93295818672a30aca7f432d1a512ee4ef0c31509a5e40eaf9c0c1f94e92e46fa` |

Frame3 PNG and sidecar are byte-identical to the previously reviewed17:46 capture; the other two are distinct new artifacts. This supports reproducibility of that selected frame, not an independent depth-regression comparison.

## Direct image observations and diagnostic limits

I viewed all three original PNGs at original resolution. Local Pillow `verify()` and complete `load()` succeeded for each:1280×720, RGB. Roads, red constructed hazard regions, green path segments and cyan tracking marks are visible. Red and cyan overlays differ across frames under a consistent camera and dark background. The visual content occupies a modest central area with substantial empty background. No image has a burned-in mock caption; preserve the README, sidecars and document captions with shared images.

Result document lines3–38 accurately describe successful native capture, original identities/hashes, temporal differences and presentation limitations. These observations do not establish calibrated hazard evolution, actual route planning, equal-depth line correctness, a before/after fix comparison, polished presentation or a quality benchmark.

The execute log contains the amdgpu `os_same_file_description` warning and the following warning about potentially shared DRM file descriptions. Exit0 and three coherent pairs establish successful capture despite the warning, not a proven cause or absence of driver issues. Document line42 accurately retains it. No failure reproduction or driver diagnosis occurred here.

## Cleanup and released grant

Saved preflight records GPU busy0, no render-node descriptor holders and VRAM28,028,928 bytes before. Passive post-run readback records no live owned job process, no renderD128 descriptor holder, owned tmux absent, GPU busy0, the four original foreign tmux sessions present, and VRAM28,028,928 bytes after. These are snapshots; they do not measure peak VRAM or prove a hard12GiB limit. They support prompt owned-process cleanup at the recorded readback, without certifying all host activity or every possible descriptor. The parent reports the additional reviewer session ended before preflight without AMD intervention; that attribution is retained rather than presented as an independent causal observation.

I independently read/hash-checked local `handoff/GPU_LEASE.json` as `69b127113b3c4ce6e2ce83a4d2d0d14669bc54c3a1a910f414667b1f4aac85a9`: root's last release is USED at20:56:13Z for this exact lease, run_count1, matching success/status/outer/log hashes, `current_lease=null`, HF next. The parent reports matching cloud state and separate root process confirmation. The grant is spent and cannot authorize another execution.

Result document lines42–53 accurately separate the warning, snapshot cleanup/resource evidence, release and still-failed FSR work. The174-file inventory remains selected rather than a full host/ELF freeze. The scoped native result is suitable for evidence publication with its existing mock labels and limits; publication itself was not performed or authorized by this review.

## Final remote checksum audit confirmation

**PASS_SCOPED_NATIVE_RESULT_REVIEW remains unchanged; the earlier pending preflight checksum limitation is resolved.** I independently hashed/read the parent-supplied `NATIVE_REMOTE_HASH_AUDIT.json`: SHA-256 `f00f3081f98818eaed54926eab61c3ae4571d154010775f2a05e0b3ac76ea8fa`. I freshly rehashed every one of its18 local raw result/preparation/preflight files against the saved cloud map:18 matches, zero mismatches. In particular, grant-preflight SHA-256 `6c95050a444396014a8c235e5bb8336923a70333ec97c2d532d4e65ba461276d` now has matching fresh cloud and local checksum evidence. The original controller-hashes list retains its earlier inspection state; this later audit supersedes its three pending `matched_remote=false` entries.

The audit records cloud HEAD `32f3b6f6d371db824294b92092e5dda6eaacd63c`, `current_lease=null`, `release_used=true` and shared-state SHA-256 `69b127113b3c4ce6e2ce83a4d2d0d14669bc54c3a1a910f414667b1f4aac85a9`, which I freshly reconfirmed for the local coordinator file. Remote values remain attributed to the saved parent audit; I made no remote/hardware call. `NATIVE_RESULT.md` remains byte-identical at SHA-256 `888b253ba118cb531cf7836117ffd3524c4675e1535eee8ca37c720638d2e0c9`. No source/publication action, image change or new execution occurred in this addendum. All warning, visual, VRAM and hardware-scope limits remain.
