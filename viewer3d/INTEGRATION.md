# Replay integration boundary

Current status (2026-10-10): the dashboard replay adapter has consumed seven frozen Paradise frames with captured OpenStreetMap roads/buildings and explicitly project-authored mock response, route and fire overlays. This is a display replay, not an integrated routing/ledger/fire mission. The shared `knight26-mission-v1` adapter remains disconnected from a trusted actual export; its 213-test viewer/root-contract result uses fictional mission fixtures and fake graphics contexts. The separately staged Win64 runtime is ready for runner verification, but FSR success is unproven.

The captured dashboard source is identified by `viewer3d/evidence/replay-adapter-input-manifest.json`: maps revision `cf5251e6897152e30be8defbd129610b9db4e2bb`, frozen raw OSM SHA256 `b73334f6280cc756fee13ab9687ccbd7d47368785f0703fea9dafd97c6035897`, canonical bootstrap/graph binding hashes and seven original frame hashes. The source manifest declares ODbL 1.0 and `© OpenStreetMap contributors`, with a requested bbox and wider partial way-context geometry. The adapter verifies the supplied WGS84 origin `[-121.607, 39.754]`, local equirectangular metres at `R=6371008.8`, source hashes and exact frame identity. Its scene uses real OSM base geography while preserving mock overlay labels and original `snapshot_hash`; `view_hash` identifies only the display projection. Missing elevations are explicitly visual `z=0`, and unknown building heights remain absent.

An initial scan on 2026-10-10 inspected maps revision `82ce6bbd348718dad95f787281e185bc2ddb8500` and found empty geography with `unavailable_source`/`acquisition_failed` labels. That observation is historical. The later captured maps revision above supplies real OSM geography. The dashboard export still has no authoritative bridge to `TripExecutor.snapshot()`, ledger or fire outcomes; its upstream `mock-replay` label remains accurate. Routing's generic metric declaration alone does not establish the OSM origin or a shared frame binding.

The root `contracts.mission.validate_mission` is imported at call time from `/workspace/knight26/repo`, with current uncommitted/unfrozen source SHA256 `8a85e2d8b6517c68c1c6bd0a7f00e72cece1581054e43ee6ac23f4d7dda312cc`. A trusted, authorized mission export and caller-supplied expected hash/source permissions are still unavailable. The mission adapter preserves the original nested routing `snapshot_hash`, distinct wrapper `mission_hash` and display `view_hash`. It checks full routes against directed graph geometry; at a node it checks the supplied node position, and inflight it checks supplied edge progress and remaining directed geometry. A retained entry-node ID is permitted during edge travel. These checks do not advance trips, interpolate positions, call `graph.segment`, or generate replacement coordinates. Unversioned `previous_path` edge IDs remain undrawn; terrain, measured height, aid locations and hazard polygons are not inferred.

`viewer3d/evidence/mission-raster-review-final.log` records 213 viewer/root-contract CPU tests passing with the validator hash above. `viewer3d/evidence/mission-raster-retained-node-red.log` records the reviewed compatibility regression before its fix. The older native EGL PNG `platform/evidence/native-ui-20261010T0754.png` (SHA256 `4488f49a9feaa7e27fbc168397ca25b3efc4cbb3aacb66d851e6e47c48059087`) was captured on AMD Radeon Pro W7900D with the prior renderer. The renderer now permits later lines at exactly equal depth while keeping nearer occlusion; a fake-depth raster test passed, and a fresh native capture of that revision is pending a new lease. Linux graphics dependencies and the full 145-package Win64 runtime are staged privately; FSR runner final review and actual FSR execution remain pending.


## Frozen incident v1 CPU view binding

The reviewed root incident contract is pinned by
`/workspace/knight26/artifacts/coordinator/incident-frozen-v1/frozen.json`
(reviewed commit `a294c868e75d8f8de3f3f9fb3ed7e52bee225ae6`).
`viewer3d.incident_adapter.adapt_incident` accepts one caller-bound cutoff
snapshot and zero or more exact `projection_input` outputs. The caller supplies
the snapshot hash from a trusted producer/export manifest; the adapter checks
that hash and regenerates each hypothetical projection input against the same
snapshot. Branches retain explicit hypothetical labels. Accepted categories,
UNKNOWN/null categories, source health, source geography, validity and message
times, unconfirmed leads, and original records remain unchanged in metadata.

This is a CPU presentation binding, not a scene projection or live-source
adapter. It draws no WGS84 geometry, assigns no metric coordinates, infers no
operational outcomes, and cannot turn authored training assumptions into
verified completeness. It remains separate from the historical mock dashboard
replay and the fictional mission fixtures. Source text is data and any UI
consumer must escape it. At the time of these fixture tests, a trusted
root publication and complete UI wiring were pending; these tests consumed no
real incident export. The later CPU probe below consumed a production snapshot.

## Accepted situation publication CPU probe — 2026-10-10T17Z

A production `accepted-situation/current.json` pointer became available after the
fixture tests. The bounded CPU probe recorded in
`viewer3d/evidence/accepted-publication-cpu-20261010T17.json` binds pointer
SHA256 `f79238ede8f515abc293d0e64b2a3d8ecc44af28ed1675566edc8a25d331c039`
to publication SHA256 `663de4f5187412cc7269812d0d856a891b36d8a699b677c76487cecd858477db`,
recomputes the snapshot, mission and view hashes, checks the content-addressed
source sidecar and scoped source/producer reviews, then calls `adapt_incident`
with snapshot hash `f6cbf6402ccbe13fe40d085154cfa9cceb9afd584a0c25706335a435b553de2d`
and zero hypothetical branches. The adapter preserved 15 accepted hazards,
unknown operational categories, source records and source health; no scene
geometry, forecast or operational outcome was generated. The saved receipt is
SHA256 `dc5c932d8d301c663e8f26e6b560cdc9b85592935f9dfc15e3f3fabf70f83303`.

Both NWS and USGS samples are marked stale in the accepted snapshot: their last
verified fetches were at 16:39Z, while publication cutoff was 17:06:59Z. These
hash and scoped review checks establish a bounded binding to that publication;
they do not establish current source freshness or a complete live mission.
The publication has no geography binding or projection input, and the actual
viewer UI has not consumed this publication. The mock dashboard replay is
separate from this accepted situation.

## Digest-pinned publication reader — 2026-10-10T17Z

The viewer3d.publication_reader.load_accepted_publication function provides a
repeatable CPU-only read of the root publisher's current.json. The caller must
obtain expected_publication_sha256 through a trusted channel and own the
directory path; copying that digest from the pointer being checked is only a
structural smoke test. The reader rejects symlinked final directory, pointer
and publication, nonregular files, oversized or malformed JSON, pointer
replacements during the read, digest mismatches, incorrect snapshot/mission/
view hashes and nonliteral-false capabilities. It returns the original
AdaptedIncident as PublishedIncident.view with no hypothetical branches,
along with the pointer, publication, view, mission and snapshot identities.
It does not authenticate upstream providers, check current source freshness,
project WGS84 geometry or drive the UI.

The root current.json advanced after the prior 17:06Z publication to view
hash b8389c8667faf5fcd3e12e441ce8bb3af121fb74288a45f3dbfafb302f9fbefc.
The reader parsed it in a CPU structural smoke test, showing 14 hazards and
source-health fields marked alive at the 17:15Z sample. At this checkpoint no
independent source-review receipt for that refresh was found, so this newer
pointer is not adopted as verified live source evidence here. The earlier
15-hazard stale publication and its reviewed receipt remain immutable evidence
for that exact cutoff; they are not the current pointer.
