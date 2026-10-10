# Maps C1 checkpoint in progress

All implementation and tests are on Radeon Cloud in `/workspace/knight26/worktrees/maps`, branch `codex/maps`. Parent records tested commit after review. No published branch/PR claim.

## Artifacts

- `fixtures/replay_ui/paradise_mock.json`: seven hand-authored frames, immutable hash; constructed route/fire/closure/load/outcome illustrations. **Not calculated routes, physical fire, live location, confirmed incident or routing-ledger proof.**
- `fixtures/geography/paradise/`: intended Paradise California AOI; initial source acquisition failed, empty roads/buildings/graph clearly unavailable. ODbL source attribution is an intended source notice; raw download/hash remains absent. No sourced road claim.
- `web/`: thin HTML/CSS/JS/SVG dashboard consumes GET frames only; geographic map, fleet/trails/remaining path/ETA, source coverage, needs/stocks, events and replay controls.
- `/workspace/knight26/artifacts/maps/c1/api-trace.json`: actual service fetch/check of all seven frames and hashes, medical mock count switches once.

## Server tests

`OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 /opt/venv/bin/python -m unittest discover -s services/dashboard_api/tests -v` -> 15/15 OK, exit0; `/workspace/knight26/logs/maps-fixture-regression-green.log`. Replay tests include mutation isolation, corrupted hashes, identity/time and bounds; HTTP tests cover exact payload, no-cache, invalid inputs, missing source coverage, static traversal, read-only dispatch boundary.

Geography importer/ingestion now8/8 with explicit unit, access, missing-node and provenance regression checks. Final numeric exit status/pinned-head rerun is recorded in artifacts. Client static DOM/asset checks pass; **JS runtime/actual browser checks pending**.

## Running service

`tmux maps-dashboard`: `OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 /opt/venv/bin/python -m services.dashboard_api.server --port 8765`, server loopback127.0.0.1:8765. Log `/workspace/knight26/logs/maps-service.log`.

SSH -L display access rejected `channel open failed: administratively prohibited`; failed tunnel closed. Server has no existing Jupyter proxy/Playwright package. Coordinator handles service access; no sshd/firewall/DNS/credential changes by worker.

## Adapter shape

`GET /api/bootstrap` -> `{mode,label,area,replay:{run_id,scenario_id,frame_count,frame_times_s,description}}`.
`GET /api/frame?index=N` -> the exact stored view frame including run/scenario/version/time/hash, vehicles, hazards, closures, events, metrics and optional needs/stocks. WGS84 geometry explicit longitude/latitude. No movement or physics calculation.
`GET /api/coverage?lat=X&lon=Y` -> available, in_loaded_area, individual coverage/missing information. Merely falling inside an AOI with no acquired layers is not available.

This is a maps-owned view adapter, **not a replacement for root's shared contract**. Add an adapter for actual routing/hazard snapshots after root supplies frozen envelope/records. POST dispatch deliberately405 until real action integration.

## Human checkpoint

C1 incomplete until small real open-data AOI and Chrome interaction inspection. C2 authoritative shared mission and C3 measured browser walkthrough remain pending. Focused advice for coordinator bundle: Can the learner distinguish a constructed replay illustration from a calculated route and explain the vehicle's waiting/reroute state?
