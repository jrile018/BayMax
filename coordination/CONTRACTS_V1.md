# Coordination interfaces v1

Status: agreed design boundary for independent work; no generated JSON schemas or product API are implemented by this Markdown file. Root owns shared-schema changes. Units below are required; propose additions through your handoff rather than editing another worker's types.

## Common identifiers and units

Use `scenario_id`, `run_id`, `snapshot_version`, `route_id`, `route_version`, `vehicle_id`, `request_id`, `edge_id` and event IDs. Times are seconds from the scenario epoch; keep source issue/observation timestamps separately. Distances and road geometry use metres in a declared projected CRS/local metric origin. Geographic display coordinates use WGS84 and explicit longitude/latitude order. Unknown values remain unknown with their provenance.

## Known snapshot — root integration owns the envelope

Envelope: run/scenario/time/version; metric origin/CRS; source manifests; observed hazard/access and forecasts issued by that time; directed road graph; vehicles and active trips; needs; depot stocks; shelter/medical capacities. Hidden sampled future states are stored separately and never passed to controller policies.

Road edge: stable ID and directed endpoints; metric polyline; length; nonnegative travel-time estimate with source/assumption; vehicle access; observed availability plus received timestamp; optional forecast availability intervals with issue time/horizon and evidence. Origins/destinations resolve to valid nodes/access links rather than arbitrary cross-barrier snapping.

## Route, trip and ledger — routing worker owns execution

Routing input: known snapshot, vehicle, valid start/decision point, destination and departure time. Output: directed edge sequence, geometry, distance, edge entry/exit times, feasibility/search status, exclusions/evidence and information versions. Static shortest reference, time-varying feasible candidate, search limit and proven disconnected static graph are distinct statuses.

Trip: vehicle, request and committed route version; phase (idle/loading/traveling/waiting/servicing/completed/stranded); current edge/distance/direction; time; carried passengers/cargo; remaining path and actual completed trail. Reroute event preserves current position/load/time and records trigger, reason, previous/new paths and ETA change. Phase/position changes are authoritative server events; views do not calculate their own travel or routes.

Ledger: mutually exclusive person locations; vehicle availability/commitments; remaining needs and actual delivered stock; destination reservations and occupancy. Atomic dispatch commits validate resource/route/service constraints. Only actual safe arrival/delivery completes the applicable need.

## Hazard adapter — wildfire worker owns physical fields

Inputs: independently sourced AOI/grid/CRS, fuel/slope/wind/moisture assumptions and physical times. Outputs: documented model name/version/units, time-indexed burn/perimeter/arrival or access fields and metadata. Map hazard fields to stable road IDs through a documented spatial rule. Surface-fire reference and any empirical fixture/CA are labeled separately. Return unknown/unavailable where inputs fail; simulation field generation is not a confirmed current incident.

## Intake — HF worker proposes, human accepts

Output: report ID/source/received time; exact evidence span or reviewed transcript segment; explicit location mention, typed need/quantity/urgency or access claim; unknown/conflict markers; proposed mapped ID only with deterministic supported resolution; review status. Only accepted evidence changes known state or requests. Model confidence/similarity is not a calibrated real-world probability. The model never supplies route scores or outcome counts.

## Future comparison — Monte Carlo worker owns evaluation

Input: known snapshot and preserved trips/ledgers; policies/candidate first actions; coherent scenario seeds and explicit uncertainty assumptions. Each policy receives only the observations issued to it at each decision. Output: per-run actions/events and raw safe arrivals, on-time medical service, unmet goods, exposure/travel, route failures and constraint violations; aggregates with sample counts/failed-run counts and held-out results. Reuse common random scenarios for comparisons; do not provide an oracle baseline as deployable behavior.

## Views — map/dashboard and renderer workers consume shared records

Both consume the same run/time/hash, geometry, hazard, needs and trip/route/event records. Map/dashboard owns interaction and evidence panels; renderer owns elevated scene/FSR probe. Browser input requests a server action; it does not run solver/AI/routing. Where a product gate fails, label the unavailable component rather than invent its output. Live and prerecorded replay are separate modes.

The first integration checkpoint is one tiny graph, one tracked dispatch, one closure observation and one feasible reroute/failure, then a counted service outcome. Real AOI, physical fire, reviewed AI report and conditional futures attach to that working contract in parallel.
