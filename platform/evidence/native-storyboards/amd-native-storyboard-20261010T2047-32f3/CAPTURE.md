# Native Paradise mock storyboard capture

This private PR packet records the capture at `platform/evidence/native-storyboards/amd-native-storyboard-20261010T2047-32f3/`. The images show a **MOCK constructed training replay**, run `maps-mock-001`, scenario `paradise-constructed-ui-exercise`; they do not depict an actual incident or operational route. Road/building source: © OpenStreetMap contributors, ODbL 1.0; provenance remains in each original sidecar.

| Mock frame/time | Original PNG | Original JSON sidecar | Native-call wall time |
| --- | --- | --- | ---: |
| 0 / 0 s | [frame-00-000s.png](frame-00-000s.png) | [frame-00-000s.json](frame-00-000s.json) | 0.138114 s |
| 3 / 180 s | [frame-03-180s.png](frame-03-180s.png) | [frame-03-180s.json](frame-03-180s.json) | 0.081641 s |
| 6 / 360 s | [frame-06-360s.png](frame-06-360s.png) | [frame-06-360s.json](frame-06-360s.json) | 0.076506 s |

All three are 1280×720 PNG/JSON pairs from native EGL/OpenGL on `GL_VENDOR=AMD`, `GL_RENDERER=AMD Radeon Pro W7900D (radeonsi, navi31, ACO, DRM 3.64, 6.8.0-79-generic)`, `GL_VERSION=4.6 (Core Profile) Mesa 26.0.8-1ubuntu0.3`. The original [receipt](receipt.json) reports three completed mock frames, 0.326603 s for the renderer section. The supervised job ran once at 20:54:49–20:54:50Z, exited 0, and measured 1.004984 s wall time. These are process wall times, **not GPU benchmarks**.

Historical capture source: private `codex/amd` HEAD `32f3b6f6d371db824294b92092e5dda6eaacd63c`; job SHA-256 `60f4f3c355ae94d89642c4a4cba0d43460b9c5f3a9b911ea73024f9889f07de1`, selected 174-file runtime-manifest SHA-256 `3dfe6bebf1788b3e9078db3457d15b17e0b22113550e9c626237c2f5346cb8c8`, launcher SHA-256 `8ab34b60b63bc0d617d333f5e7bc6cdc3111fc66f7f18197d1d9abcb5e73299d`. [Source/frame freeze](source-freeze.json) SHA-256 `bf3fe737c484af59d37ede5286658137e0f7eda836a8f31c1be4ce1ce15f146e` binds the selected input hashes. The exclusive grant `amd-native-reviewed-20261010T205203Z` was spent and released **USED at 20:56:13Z**; it cannot authorize another run.

The raw [execute receipt](logs/amd-native-storyboard-20261010T2047-32f3-execute.json), [execute log](logs/amd-native-storyboard-20261010T2047-32f3-execute.log), [tmux shell log](logs/amd-native-storyboard-20261010T2047-32f3-tmux-shell.log), and [independent result review](review/native-result-review.md) belong with this packet. The original execute log retains the amdgpu `os_same_file_description` warning; successful output does not diagnose or negate it. The review checks the exact frame pairs and provider claims. Any `archive-source/` copies are inspection-only exact bytes, not newly executable tools.

The selected runtime manifest does not freeze every host transitive ELF dependency. The frozen OpenStreetMap source, graph and bootstrap total about 7 MB; they and the other input blobs remain external hash-bound prerequisites. Including their manifest alone does not make this packet fully reproducible. This capture provides no FSR provider/context, ML dispatch, real routing, equal-depth correctness proof or measured peak VRAM claim. Visible changes between mock frames are presentation evidence only.
