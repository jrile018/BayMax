# Sourced Paradise road adapter and training replay

The routing engine can read the Paradise OSM graph and its source manifest without modifying the maps owner's files. This adapter accepts the published `graph.json` shape only when its declared metric CRS, WGS84 longitude/latitude origin, OSM raw hash, acquisition/geometry bounds, IDs, geometry, speed and time agree with the manifest. Each node metric point must match its WGS84 point under the declared projection within 0.25m. The accepted `Graph` keeps 3,046 mapped nodes and 5,959 directed edges for the source fixture used below.

`graph_from_geography(payload, source_manifest) -> Graph` preserves stable OSM edge IDs, direction, metric geometry, travel-time estimates, way/segment and speed provenance. Vehicle permissions use declared proxies: OSM bus→bus, motorcar→ambulance, hgv→truck, also requiring motor_vehicle=true. These are route-model approximations, not legal emergency-vehicle permissions.

`safety_from_access(records, graph, *, alignment, known_at_s, horizon_s, version, safe_nodes, default_received_s=None, safety_buffer_s=0) -> SafetySnapshot` requires matching graph version, area, metric CRS, WGS84 origin and graph-source SHA. It accepts only records issued and received by the decision time. An edge counts as covered only when the latest visible report covers the whole requested horizon and the full edge geometry lies in the acquired OSM bbox. Missing, unknown, partially covered, future and outside-bbox roads remain unavailable. An observed-open road report is only a present observation; it cannot certify a future travel horizon without a separate forecast or authored interval. Destination safety is supplied explicitly. Closed intervals are half-open; exiting exactly at closure start remains permitted without a buffer. No coordinate transform or spatial fire-to-road overlay is implemented.

The source adapter adds `metric_crs`, `origin_lonlat` and `source_metadata` to sourced trip snapshots. Source metadata joins sourced checkpoint fingerprints, while version-1 fingerprints for earlier fictional graphs stay unchanged. The previous published checkpoint state restores with this code.

## Actual sourced-road exercise

```text
/opt/venv/bin/python -m services.routing.sourced_demo \
  --graph /workspace/knight26/worktrees/maps/fixtures/geography/paradise/graph.json \
  --manifest /workspace/knight26/worktrees/maps/fixtures/geography/paradise/source_manifest.json \
  --fire-hazard /workspace/knight26/artifacts/wildfire/checkpoint-c1/run-committed/hazard.json \
  --fire-access /workspace/knight26/artifacts/wildfire/checkpoint-c1/run-committed/edge-access.json \
  --output-dir /workspace/knight26/artifacts/routing/c2-sourced
```

The route uses five actual directed Paradise OSM edges selected by verified source/junction/destination connectivity. One bus starts at source node9266995295, reaches junction9266995291, and heads to destination9266995290. At the halfway point on the first road, the training script injects a report closing the direct edge. The independent restored branch keeps its actual position and takes the three-edge detour. A branch with destination safety withheld retains its person and counts no service.
The selected OSM ways include service roads and parking aisles. This corridor demonstrates geometry and rerouting; it does not establish that a real bus can use those roads.

For the current source bytes, direct:70.146m, actual arrival12.526s; detour:96.110m, actual arrival17.163s. Each branch counts one safe service after arrival; unknown destination counts zero. Full actual snapshots, checkpoint state, selected OSM nodes/edges, authored access records and source hashes are in `artifacts/routing/c2-sourced/c2-sourced-replay.json` with a compact summary. These small corridor timings do not establish performance or effectiveness across the full Paradise road graph.

The fire mismatch proof reads the current synthetic wildfire artifacts only to reject them. Their `LOCAL_METRIC` grid origin[0,0] differs from the Paradise road CRS/origin[-121.607,39.754], and their five synthetic edge IDs are absent from the OSM graph. Both independent checks raise explicit errors. No physical wildfire field is joined or treated as a live closure.

## Input/source register

| Input | Role in this replay | Source and time | License/status |
|---|---|---|---|
| Paradise road nodes, edge IDs, geometry | Used for actual simulated position and directed paths | OSM API bbox extract in maps source manifest; downloaded2026-10-10T07:00:45Z; raw SHA256 `b73334f6280cc756fee13ab9687ccbd7d47368785f0703fea9dafd97c6035897` | ODbL1.0, © OpenStreetMap contributors; sourced geographic data, not live road status |
| Travel speeds and access | Used as map-input estimates and route proxies | Per-edge `speed_assumption`, `speed_mps` and OSM access flags; source manifest and graph preserve their origin | Some OSM maxspeed, some authored highway-class speed assumptions; ambulance/truck proxy mappings declared |
| Open-road coverage, safe destination and closure | Used to exercise dispatch, reroute and service | Authored corridor records; report issued and received at halfway simulated time | Training assumption; neither observed road access nor physical wildfire output |
| Synthetic wildfire grid and edge access | Used only for a rejected-join test | Existing wildfire C1 artifact, grid `LOCAL_METRIC`, origin[0,0], five synthetic IDs | Modeled training data; mismatched coordinates and IDs |
| Aligned physical fire/access or reviewed live road reports | Planned for another owner/integration | Requires identical road CRS/origin/IDs or a verified transform, issue/receipt time and coverage | Unavailable here; no current-incident claim |

The maps source fixture is owned by the maps workstream and has not yet entered the current main branch at this routing checkpoint. The command above depends on that fixture being present at the stated path. Routing code and schema tests remain runnable without importing the maps worktree.
