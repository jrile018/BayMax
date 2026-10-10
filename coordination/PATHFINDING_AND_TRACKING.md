# Pathfinding and route tracking: flagship training feature

Date: 2026-10-10. Status: required feature contract; implementation and product tests have not run. This refines the user's explicit pathfinding requirement and latest request to give path tracking major emphasis for the serious-game track. It defines both route calculation and tracking of simulated trips. It does not claim live GPS integration.

## The feature in one sentence

Dispatch an aid vehicle, watch it follow a calculated road route, respond when new information changes access, and compare whether another strategy would deliver urgent help more reliably across the tested futures.

This is a central training interaction for an aid coordinator practicing wildfire evacuation or civilian recovery. The learning objective is to identify a feasible route, recognize a changing access constraint, and explain a revised dispatch using urgency, capacity, travel time and uncertainty. Route search and trip tracking remain required when optional vision, aircraft, extra regions or richer animation are cut. Google composition and genuine server FSR4 remain separately required, unresolved gates.

## What the coordinator sees and controls

| Interaction | Visible result | Consequence in the exercise |
|---|---|---|
| Select an ambulance, bus or supply truck and an eligible request | Origin, destination, calculated road path, distance, estimated travel/service times, resource compatibility and source status | A dispatch can use only a feasible path and an available compatible vehicle; the aid ledger reserves its load/assignment. |
| Compare route candidates before dispatch | Candidate paths, arrival estimates, known exclusions and outcomes across the tested futures | The learner weighs urgent deadlines and access reliability; a shorter route need not be the selected response. |
| Advance or pause simulation time | Vehicle marker, completed trail, remaining path, current segment, ETA and loading/travel/service status | Actual trip events advance on the selected edges; the view follows those events. Picking people up does not yet count as evacuation. |
| Inspect a closure or a reviewed field report | Affected mapped segments, source or scenario assumption, observation time and reason | Accepted information updates the known road state. The system cannot treat AI text or an unreviewed report as a verified closure. |
| Replan after access, forecast, delay, destination or assignment changes | Old route, revised remaining route, change in ETA and explicit explanation | The vehicle keeps its actual progress, passengers, cargo, elapsed time and commitments. A new path starts at a physically reachable decision point. |
| Find no feasible continuation | Explicit unreachable, waiting, access-unknown or stranded status, with the reason | The request stays unmet; a vehicle cannot jump to the destination or travel along a fabricated straight line. |
| Review the exercise | Timeline of dispatches, traversed paths, reports, reroutes, arrivals and service outcomes | The learner can identify the observation and decision that changed the result. |

Both views consume the authoritative server state for the same run, simulation time and snapshot hash. Distinguish path candidates, committed routes and completed trails by line style and labels as well as color. Use a text vehicle list and route explanation so the task remains understandable without reading the map alone. Vehicle positions are **simulated**, not observed live locations.

## Routing rules that make this consequential

1. Use an independently sourced directed road graph with stable segment IDs, metric geometry, valid nonnegative travel-time weights, one-way restrictions and declared vehicle access. Origins and destinations must resolve to mapped road nodes or explicit valid access links; preserve any assumed snapping distance and reject connections across barriers. Missing speed/access data requires a visible assumption or an unknown result, not silent certainty. Parallel roads must retain their distinct edge identity.
2. Establish a static shortest-path reference using Dijkstra on the compatible, observed-open graph. A* is optional and must agree with that reference under a documented admissible heuristic. Missing travel-time attributes must be rejected or explicitly filled before search: an implicit default weight is not a valid travel-time estimate. The source documents directed weighted search and nonnegative Dijkstra weights: [NetworkX shortest paths](https://networkx.org/documentation/stable/reference/algorithms/shortest_paths.html).
3. Forecast-aware feasibility is a separate required check. For each candidate edge, compute entry and exit times from departure, previous travel and any permitted wait. Check the full traversal interval against the forecast/access schedule and the declared training safety buffer. A road that is open at dispatch can still be rejected because it is expected to close before the vehicle exits. Preserve the forecast issue time, valid horizon and assumptions; unknown coverage is not a safety guarantee.
4. If time-varying access is handled by bounded candidate generation and interval validation, report a feasible candidate or search limit. Rejection of a finite candidate set cannot prove that every route is impossible. Use a bounded time-expanded graph with explicit safe waiting states if needed for the chosen closure/reopening model. Ordinary static Dijkstra plus one validation pass must not be presented as an exact solution of arbitrary time-dependent routing.
5. If an observation arrives while a vehicle is partway along an edge, preserve its segment, direction and traveled distance. Validate the remaining traversal before continuing. Reroute at a reachable junction or an explicitly modeled permitted turnaround/retreat with its own travel cost. If neither continuation nor retreat is feasible, record the in-place stranded state and exposure; never teleport, assume an instant U-turn, or automatically finish an unsafe edge. Waiting requires a location and duration that pass the exercise's access/hazard rules.
6. The controller uses only observations and forecasts available at that decision time. Hidden sampled fire/closure truth belongs to the evaluator, not route search. Routes that pass the model's predicted checks may still fail in a sampled future; preserve those failures in the results.
7. Commit a dispatch only after one authoritative ledger transaction checks and reserves vehicle availability, seats/cargo, stock, remaining need, destination capacity and assignment against duplicate service. Include loading/unloading, deadlines and the vehicle's subsequent availability/return commitment. Route calculation finds a path; allocation chooses which vehicle serves which request and when. A capacity/time-window library supports those constraints but does not automatically model this project's changing hazards: [OR-Tools capacities](https://developers.google.com/optimization/routing/cvrp), [time windows](https://developers.google.com/optimization/routing/vrptw).

Example explanation, **constructed training case**: “The original road is forecast to close before the ambulance exits. Route B adds travel time and remains feasible under this forecast. The ambulance is already between two junctions, so the change applies from the next reachable decision point.” A second example must show an unreachable request and its remaining unmet need rather than invent a successful rescue.

## Tracking and event contract

Proposed fields extend the root-owned contracts in the [parallel build plan](PARALLEL_BUILD_PLAN.md); these schemas are not implemented yet.

- **Route record:** route/version ID; request and vehicle IDs; source/destination; ordered directed edge IDs and geometry; departure and per-edge entry/exit times; distance and travel/service estimates; graph and known-state versions; forecast issue time/horizon; exclusions and their evidence; search/feasibility status; measured calculation duration.
- **Trip record:** assigned route version; phase; current edge and distance along it; current simulation time; physically reached decision point; load/passengers; outstanding destination commitment; completed trail; remaining path; point ETA and separately labeled ensemble arrival estimates where available.
- **Reroute event:** triggering observation/forecast/delay event; decision timestamp and information set; previous/current vehicle state; old and new remaining paths; reason; feasibility result and ETA change. Failed replanning is an event too.
- **Replay frame:** run/time/hash and those same authoritative trip records. 2D and 3D only display the recorded geometry and position; they cannot independently invent routes or interpolate through closures. Display interpolation is bounded by consecutive authoritative frames and follows the recorded metric polyline.

Travel advances elapsed time and distance along the selected route. Load, travel, pickup, drop-off and service remain distinct events. People are at origin, in transit or at the safe destination, never in two places at once. Aid is counted once at actual delivery. Replaying a saved run reproduces the same sequence of route versions and outcomes.

## How Monte Carlo strengthens the feature

At a known decision step, branch plausible correlated hazard/weather/access and delay conditions while preserving current positions and commitments. Compare the player's response, a priority-greedy baseline and a risk-aware policy on the same seeded futures; then evaluate selected policies on held-out seeds. Each policy replans only when its simulated observation history allows it. This follows the [conditional aid-planning design](research/conditional-aid-planning.md).

Show arrival-time quantiles, on-time medical service, people reaching shelter, unmet supply needs, exposure, failed traversals and infeasible requests. A policy with unreachable cases must report their count alongside conditional arrival quantiles; do not drop failed runs or conceal them in a mean ETA. Fractions are fractions of the tested scenarios unless the inputs have an independently justified calibration. “Best evaluated feasible strategy” is the result label; global optimality requires a separate certificate.

## Definition of done and evidence for judges

Every row below requires actual server execution and a saved artifact before claiming completion. These are planned acceptance checks, not passing test results.

| Required check | Proof artifact |
|---|---|
| Known shortest path and cost | Hand-checkable graph and expected directed edge sequence/cost; actual route matches. |
| One-way and vehicle access | An incompatible truck or wrong-way route is rejected; the compatible alternative is traversed. |
| Closure and traversal timing | A known alternate path appears after a closure; a forecast closure halfway through an edge invalidates that candidate. |
| Reachability versus search limit | Disconnected static graph reports unreachable; bounded dynamic search exhaustion reports search limit, not proven unreachable. |
| Trip tracking and underway reroute | A partway-edge fixture preserves position/load/elapsed time; subsequent movement follows the revised remaining route without teleporting. Unsafe continuation has an explicit failed/stranded result. |
| Capacity, deadlines and conservation | Bus/ambulance/truck cases enforce their separate service capacities; arrival and delivery count once, with unmet demand retained. |
| Information timing | With identical known histories but different hidden futures, initial actions match. A later observed closure can cause different replanning. |
| View agreement and replay | Route versions, simulated positions and event times match across enabled views and a saved replay. Product-level dual-view completion still requires the graphics/composition gates. |
| Comparison and honest performance | Common/held-out seeds, raw outcomes including failures, sample counts and measured route/replan p50/p95 runtime; no invented performance threshold or real-world probability claim. |
| Training decision | Learner states a route/dispatch reason before revealing changed access and explains their adaptation in the debrief. Actual learning claims require recorded learner evidence. |

The Full Sail demonstration must devote approximately 90–120 seconds of the main six-minute presentation to this chain: **request → calculated path → moving vehicle/trail → new closure/report → physically feasible reroute or failure → revised ETA → actual arrival/service and comparison**. Show the computed path/algorithm evidence beside its consequence. Use a small, source-checked wildfire exercise first; repeat one closure case in the clearly labeled civilian-recovery preset. Scenario time may be accelerated for presentation, but physical elapsed time and route costs remain visible.

Minimum judge packet: one saved replay, reference/pathfinding fixture results, a route-change event with reason and information timestamp, raw same-seed comparison outcomes, and a source/model manifest. A prerecorded replay must be labeled prerecorded. The track's quoted “pathfinding or face detection” requirement is addressed by demonstrable pathfinding in the training interaction; route tracking makes its effect visible but does not replace the search algorithm. Official event evidence is recorded in [event rules](research/official-event-rules.md) and the [competition blueprint](COMPETITION_BLUEPRINT.md).

## Build priority and ownership

Promote routing, trip tracking and the conserved ledger into the first implementation wave, in parallel with geography and the fire adapter. Begin with a tiny hand-known road fixture so routing does not wait on satellite ingestion, detailed graphics or physical fire-package installation. Root freezes route/trip/event contracts; the routing worker owns search, travel progression and reroute events; the map/3D workers display those records; the uncertainty worker evaluates policies; the AI worker proposes evidence-linked reports for human acceptance.

All product code, builds, tests, simulation, comparison and rendering run on the supplied Radeon server through detached logged jobs. Local planning documents remain reviewable working drafts. This document does not assert that those jobs, a GitHub branch/issue/PR, or a product route exist yet.
