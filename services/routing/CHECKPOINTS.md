# Versioned routing continuation checkpoints

Implemented boundary for independent continuations of actual trips and resources. Shared coordinator contracts remain proposed; sourced wildfire/map integration and Monte Carlo rollout policy are outside this change.

```python
import json
from services.planner.ledger import Ledger
from services.routing.trip import TripExecutor

saved = json.loads(json.dumps(engine.checkpoint()))
branch_a = TripExecutor.from_checkpoint(graph, saved)
branch_b = TripExecutor.from_checkpoint(graph, saved)
branch_a.advance(later_time_s, known_safety)
# branch_b and engine retain their own state.

saved_ledger = ledger.checkpoint()
new_ledger = Ledger.from_checkpoint(saved_ledger)
```

TripExecutor.snapshot() is a display record. checkpoint() is the complete continuation boundary: schema knight26.trip-executor version1, canonical JSON SHA256 checksum, exact graph content fingerprint, ledger checkpoint, trip internals, clock, snapshot version, known-information history, ordered events, original dispatch signatures and reroute trigger receipts.

Ledger.checkpoint() uses schema knight26.ledger version1. It includes immutable initial configuration and initial resource totals, current assignments, reservations, actual person locations, stocks/deliveries/outcomes, idempotency fingerprints and ordered audit. Restore creates fresh objects and replays validated ledger actions. It checks reconstructed canonical JSON, capacities, chronology and conservation.

Restore supports loading, partial edge travel, servicing, completed and stranded trips, including positive-duration collapsed connectors and a failed suffix search while the safe current edge is still finishing. It preserves actual edge entry time, distance, trail, completed/pending paths, passengers/cargo, service duration, exposure, initial dispatch identity and trigger idempotency. A rerouted Route may start at the future junction while the current edge remains active.

Validation rejects unknown schemas, checksum corruption, changed graph content even under the same version string, impossible resource state, inconsistent ordered history, missing/extra trigger receipts, route/path replacement and altered movement geometry. Later actions still enforce received information and supplied safety coverage; restoring does not certify future safety. The checksum detects accidental alteration and semantic consistency is checked separately.

## Cloud evidence

```text
/opt/venv/bin/python -m unittest discover -s fixtures/ledger -p 'test_*.py' -v
/opt/venv/bin/python -m unittest discover -s fixtures/routing -p 'test_*.py' -v
/opt/venv/bin/python -m services.routing.checkpoint_demo --output-dir /workspace/knight26/artifacts/routing/checkpoint-v1
```

Current reviewed suites:20 ledger +54 routing tests,74 total. All new checkpoint tests and checkpoint_demo use the actual Ledger. The four historical test_trip_faults tests retain their labeled StubLedger.

Mixed actual replay saves at21.5s: bus and ambulance are servicing, truck is traveling, all three people remain in transit and five water units are carried. Independent safe continuation evacuates2, serves1 medical person on time and delivers5 water; remaining need3. Unknown destination safety instead strands all three vehicles, serves nobody and retains3 people and5 carried water. Every branch conserves initial water10 and original state remains unchanged. Duplicate completion/replan/dispatch checks add no outcomes or events.

checkpoint-verified-head.json/.log pin the committed head, exact commands/exits and artifact hashes. checkpoint-mixed-state.json is the actual restorable payload; checkpoint-mixed-replay.json contains original and branch snapshots with conservation and explicit fictional assumptions. Historical red/green logs record the review counterexamples and corrections.

These are fictional tiny-road continuations, not a probability estimate or integrated physical-fire mission. Restore cost includes audit replay and no large-scenario performance claim is made. Maps Paradise and the current synthetic wildfire grid have different coordinate declarations; they remain unjoined.
