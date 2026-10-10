# Routing search checkpoint

Current status: reviewed search is testable; authoritative trip and ledger core are still in progress.

Public Python exports: Edge, Graph, Route, SearchResult, Closure, SafetySnapshot, static_reference and candidate_routes from services.routing. static_reference is directed nonnegative Dijkstra on compatible roads open at dispatch and returns safety_validated=false. candidate_routes validates whole traversal intervals using only received information, preserves road identity and reports bounded-search status.

The source is standard-library Python, authored and tested on the supplied Radeon Cloud server (/opt/venv/bin/python3.14.4; cgroup16 CPUs; test threads capped2; no GPU/dependency additions). Inputs and known-access intervals are explicitly fictional tiny exercise data.

Command:
```
/opt/venv/bin/python -m unittest discover -s fixtures/routing -p test_search.py -v
```
14 acceptance tests passed in /workspace/knight26/artifacts/routing/search-review-green.log, exit0. Expected initial missing-feature red and independent reviewer regression red logs are preserved. Fixed reviewed defects: zero-length teleport connector and cumulative ETA overflow.

No waiting/retreat model or arbitrary time-dependent global optimality certificate. A structural compatible directed disconnection is unreachable_static; finite simple-path candidate failure is no_feasible_candidate; bounds report search_limit. Explicit safe destination declarations are proposed for the trip dependency, not inferred from road coverage.

TripExecutor is now in the draft: actual metric edge progress, polyline trail/remaining geometry, reachable-junction replanning, in-place stranding, loading/arrival/service phases, deterministic snapshot hash and route events. It requires the proposed Ledger.transaction API; real ledger implementation/integration is pending at an automatic-approval boundary.

Four focused trip-only fault tests use a clearly labeled test StubLedger. They do not prove any real ledger capacity/service outcomes. Command:
```
/opt/venv/bin/python -m unittest discover -s fixtures/routing -p test_trip_faults.py -v
```
trip-review-red.log recorded four failures (positive-duration collapsed connector, partial clock/state advance, ETA update split state and stranded ledger split state). trip-review-green.log records four passed, exit0. Independent follow-up review found no further material issue. Corrected trips use duration independent of distance and atomic executor+ledger rollback.

The real trip/ledger acceptance files remain pending until the ledger dependency is unblocked. C1 movement/reroute/exactly-once service is not yet complete.
