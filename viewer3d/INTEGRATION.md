# Replay integration boundary

Scanned 2026-10-10. Root coordination seed is fe83b4b. Maps source is 82ce6bbd348718dad95f787281e185bc2ddb8500 and routing source is d763eb61bed8276a24cce769684f58501e68b581. These are inspected upstream revisions, not merged dependencies.

The current maps API exposes `/api/bootstrap` and `/api/frame?index=N`. Bootstrap carries area bbox/origin in WGS84 longitude/latitude, source manifest and feature collections, plus replay run/scenario/frame times. Frames carry run/scenario/snapshot version/index/time/hash, vehicle positions, route versions/geometry, remaining paths and completed trails, hazards, closures, events, needs and stocks. The snapshot hash is the SHA256 of canonical frame JSON excluding the hash itself.

Its existing replay is explicitly constructed `mock-replay`. Acquired geography is empty with `unavailable_source`/`acquisition_failed` source status. Those labels must survive any renderer adapter. This API is a display contract; it currently has no authoritative bridge from routing/ledger/fire. It must not be relabeled as a sourced integrated mission.

Routing owns calculated graph routes and trip progress. Its `Route` records preserve metric geometry, graph and known versions, safety provenance, and entry/exit leg times. `TripExecutor.snapshot()` is the intended authoritative position/trail source, but current routing evidence uses a stub ledger; real ledger integration is pending. The maps importer defines local equirectangular metres around an explicit WGS84 origin. A routing metric point without that CRS/origin is insufficient to map to the dashboard.

The coordinator/maps replay layer should own the authoritative serializer and CRS declaration. The renderer then consumes its frame without computing routes, interpolating positions, advancing trips, simulating fire or deriving aid outcomes. `viewer3d.SceneInput` remains an internal immutable projection. No replacement shared JSON schema is introduced here.

The adapter needs one audited frame identity (run, scenario, time, hash), metric CRS/units/origin, source/license declarations, terrain/feature geometry where actually available, exact unit/aid positions, route IDs/versions and completed trails, and hazard source status. Missing geography or elevations stay absent. A fixture or flat demonstration must be explicitly labeled synthetic. Shared contract and actual integrated frame are still pending.
