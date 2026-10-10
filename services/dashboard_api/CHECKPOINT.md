# Maps C1 checkpoint

All product authoring, processing, tests and serving occur on Radeon Cloud in `/workspace/knight26/worktrees/maps`, branch `codex/maps`. Exact tested/published SHA and file hashes are recorded in `/workspace/knight26/artifacts/maps/c1/publish-manifest.json`. Own draft PR: https://github.com/jrile018/knight26/pull/10; detailed Discussion: https://github.com/jrile018/knight26/discussions/1.

## Real geography and constructed replay

`fixtures/geography/paradise/` contains the official single bounded OSM API response and derived road/building/landuse geometry plus directed metric graph. 444 road ways, 199 buildings, 40 landuse/water ways; 3,046 graph nodes and 5,959 edges. Request bbox: [-121.621,39.742,-121.591,39.765], retrieved 2026-10-10T07:00:45Z. Raw/decompressed SHA256: b73334f6280cc756fee13ab9687ccbd7d47368785f0703fea9dafd97c6035897. OSM feature edits span 2007-10-25T04:57:29Z to 2026-09-09T03:34:43Z; retrieval time is distinct from edit dates. ODbL 1.0 attribution and official endpoint recorded in source_manifest.json. Terrain, fuels and current fire remain unavailable.

Full OSM ways can extend beyond the request. `coverage_bbox_lonlat` is acquisition bounds, `source_geometry_bbox_lonlat` is the full feature envelope, and `bbox_lonlat` is their viewport union. Outside acquisition bounds but within that envelope, API coverage says local coverage is unverified; it does not assert geometry at every point of the rectangular envelope.

`fixtures/replay_ui/paradise_mock.json` contains seven hand-authored constructed frames with exact recorded hashes. Vehicle paths, fire, closures, loads and the medical count illustrate UI behavior; they do not prove calculated routes, physical fire, a real incident or a conserved aid ledger. The client consumes recorded snapshots only and does not interpolate movement or perform routing/physics.

## Validation

Server commands, capped at two OMP/OPENBLAS/MKL threads:

- `/opt/venv/bin/python -m unittest discover -s services/dashboard_api/tests -p test_*.py -v`: 19 tests.
- `/opt/venv/bin/python -m unittest discover -s services/geography -p test_*.py -v`: 12 tests.

Working suite passed 31/31; commit-pinned validation is recorded in the publication manifest. Tests cover immutable hashes/identity/times, bounds, static traversal, read-only dispatch, exact exported frames/script escaping, source hashes, XML safety/limits, speed/access semantics, missing nodes and acquisition/context distinction. Actual loopback API verifies real geography counts, seven frame hashes and inside/context/outside coverage in api-trace.json.

Independent review corrected pre-decision mock detour leakage, movement-before-decision, provenance wording and the acquisition/context mismatch. The final extent wording makes local coverage unverified rather than claiming geometry in empty envelope corners.

## Service and viewing

Own tmux `maps-dashboard`, loopback127.0.0.1:8765, `/workspace/knight26/logs/maps-service.log`. `GET /api/bootstrap`, `/api/frame?index=N`, `/api/coverage?lat=X&lon=Y`, `/api/health`; POST actions return405 until actual integration. Shared V1 contracts unchanged; this is a maps-owned view adapter.

`/opt/venv/bin/python -m services.dashboard_api.export_preview --output /workspace/knight26/artifacts/maps/c1/preview.html` generates a self-contained saved replay on the server. It embeds exact frames/hashes and owned assets, visibly labels saved mock mode and unavailable live actions/coverage. Existing authenticated notebook file serving rendered earlier saved first/closure/final frames in actual Chrome; a later reload returned nginx403 even after one provider-auth refresh. Current real-map preview awaits authenticated browser inspection. SSH forwarding remains prohibited; no security/network settings were changed and no public service was exposed.

C1: real AOI and mock preview are reviewable; current real-map Chrome check pending. C2 authoritative routing/fire/MC/actions and C3 integrated walkthrough remain pending. Human advice for coordinator bundle: can the learner distinguish constructed replay from calculated routes and explain waiting/reroute?
