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

TripExecutor and ledger tests are not in this first reviewed-search commit. They will be added to the same draft PR after end-to-end checks. C1 movement/reroute/exactly-once service is not yet complete.
