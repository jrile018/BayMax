# Routing and atomic aid ledger evidence

C1 source is implemented for the declared fictional tiny graph. C2 sourced mission integration and C3 judging acceptance remain pending coordinator integration. Independent review corrected material search, movement, resource timing and unsafe service issues before final checks.

## Reproduce on the authorized cloud worktree
Use repository root, Python /opt/venv/bin/python, CPU thread cap2, and a detached tmux runner with a log:

```text
/opt/venv/bin/python -m unittest discover -s fixtures/ledger -p 'test_*.py' -v
/opt/venv/bin/python -m unittest discover -s fixtures/routing -p 'test_*.py' -v
/opt/venv/bin/python -m services.routing.demo --output-dir /workspace/knight26/artifacts/routing --samples 100
```

Final source suite: 11 ledger +41 routing tests, 52 total. The four historical test_trip_faults checks use a labeled StubLedger; test_trip and test_integration exercise the actual Ledger, including a fault raised after resource transfer and complete rollback.

## Actual replay artifacts
/workspace/knight26/artifacts/routing/c1-replay.json contains the exact fictional input graph, real engine frames, events, immutable snapshot hashes, explicit safety assumptions, raw ledger state and aid outcomes.
/workspace/knight26/artifacts/routing/c1-summary.json records source Git SHA, source-input hash, resource conservation and measured p50/p95.
/workspace/knight26/artifacts/routing/c1-timing.json records all100 actual timing samples per operation; no performance threshold or real-world calibration claim.
/workspace/knight26/artifacts/routing/c1-verified-head.json and c1-verified-head.log record exact committed SHA, commands, integer exit codes and artifact hashes.

Expected literal proof:
- Bus at5s is(50,0) on A-B. B-D closure preserves that state, finishes A-B at10, takes B-C-D, arrives35, completes service37; two people count only then.
- A-B closure at5 strands at(50,0), retains two passengers, counts no aid, accumulates20s exposure by25.
- Mixed aid replay serves2 evacuation +1 on-time medical person and delivers5 water units. Initial water10 = stock5 +carried0 +delivered5; residual need3. Duplicate time/service cannot add outcomes.
- Shelter and medical occupancy never exceed capacities; stranded resources remain committed rather than disappearing.

## Restricted claim
Hand-authored fictional metric roads and hazard intervals, simulated authority, explicit safe destination declarations. Directed Dijkstra is a static reference; dispatch requires bounded full-edge interval validation. Simple paths have no waiting or retreat. No live GPS, real-world wildfire safety certificate, Monte Carlo probability, or arbitrary time-dependent global optimality claim.

Historical red/green logs are retained in the same artifact directory. Earlier partial-reviewed-head and all-owned-current records belong to the earlier incomplete d763eb6 head and must not be mistaken for final C1 evidence.

## Actual continuation boundary
Versioned Ledger and TripExecutor checkpoint/restore are implemented; see CHECKPOINTS.md. Updated reviewed source suite:20 ledger +54 routing,74 total. New actual mixed-resource continuation evidence is separate from the preserved C1 bundle in artifacts/routing/checkpoint-v1; checkpoint-verified-head.json/.log pin its committed source. This does not complete sourced C2 integration or C3 acceptance.
