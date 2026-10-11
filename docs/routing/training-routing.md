# Authored TRAINING routing and fleet fixtures

This change supplies a pure integer-time route proposer and independently checked
training fixtures. It does not execute trips or commit resource reservations.
Maps, TripExecutor and ledger adapter adoption remain pending.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `services/routing/training_time_search.py` | `search(request)` and pure `revalidate(candidate, current_request)` |
| `fixtures/routing/time_reference.py` | Independent exhaustive tiny-time reference and action feasibility checker; no solver imports/helpers |
| `fixtures/routing/test_training_time_search.py` | Literal boundaries and 32 authored acyclic-grid comparisons |
| `fixtures/routing/validate_cyclic_time_cohort.py` | New held-out 768-configuration cohort and two literal behaviors; source accepted, not executed |
| `fixtures/routing/training_multibus.py` | Deterministic graph-pinned three-bus display fixture, validation, interpolation and schema |
| `fixtures/routing/test_training_multibus.py` | Fixture identity, timing, interpolation and malformed/oversized numeric checks |

The fleet fixture and time search are separate contracts. The time-search module
does not accept the full Paradise graph or turn the display fixture into a fleet
optimizer.

## Integer-time route contract

Requests use `schema="routing.training.time.v1"` and `mode="TRAINING"`.
Times, durations, capacity counts, bounds and interval endpoints are exact
nonnegative integers; travel durations are positive. Floats and booleans are
rejected rather than rounded. Identifiers are nonempty strings.

A request declares request/trip/graph identities; `now`, `deadline`, `buffer`,
`service_duration`; a versioned global knowledge window; resources; commitments;
a node or underway-edge anchor; destination; one to three alternatives; maximum
expansions; and directed nodes/edges. Known/safe/closed intervals are sorted,
disjoint, nonempty half-open intervals; adjacent intervals form a continuous
union. Empty known coverage is unknown. Missing coverage/access does not become
open or safe.

Node records carry `id`, `known`, `safe`. Edge records carry `id`, `source`,
`target`, `duration`, `access` (ALLOWED/DENIED/UNKNOWN), `known` and `closed`.
A wait must remain continuously known and safe, including its arrival endpoint.
Traversal requires explicit ALLOWED access, full edge coverage and no closure
over `[departure, arrival + buffer)`, plus known/safe arrival-node membership.
Waiting on an edge or reversing without an explicit directed edge is unsupported.

Service completes at `arrival + service_duration`. Destination coverage/safety
must span service plus buffer and include completion itself. Completion is at
or before the deadline, strictly before the global exclusive horizon, and
completion plus buffer may equal that horizon. A zero-buffer closure starting
exactly at edge arrival does not overlap traversal.

A node anchor is `{kind:"node",node}`. An underway anchor is
`{kind:"edge",edge,entered_at,duration_at_entry,source_at_entry,target_at_entry}`.
It preserves original arrival from committed entry time/duration even if the
current graph duration differs. The remaining edge and arrival are checked under
the current snapshot. Changed endpoints or uncertifiable continuation produce
STRANDED while preserving commitments. A feasible prefix with no feasible suffix
is retained without executing it.

Resources carry a version and
`free_bus_seats_excluding_own_pickup_reservation` /
`free_destination_slots_excluding_own_reservation`. Commitments preserve
`reservation_id`, `onboard`, `pickup`, `destination_id` and `opaque`.
Own reservations are already excluded once from the free counts and are not
added back. Destination must match the commitment. This snapshot check is not
atomic booking.

Candidates include explicit CONTINUE_EDGE/TRAVERSE/WAIT/SERVICE actions, edge
sequence, arrival/completion, anchor/commitments, identities/versions and a
canonical full-request SHA256. Routes rank among known feasible sequences;
different wait schedules do not make duplicate route alternatives. Tied cutoff
routes may be interchangeable.

`revalidate` regenerates proposals for an identical request and requires
type-sensitive canonical candidate equality. Request drift or a changed valid
candidate request pin gives REPLAN_REQUIRED; malformed proposals are REJECTED.
Corrupt proposals carrying the current request pin are REJECTED. VALIDATED_PROPOSAL
requires a separate authoritative owner recheck/commit before any movement.

Results distinguish FEASIBLE, SEARCH_LIMIT, INFORMATION_UNAVAILABLE,
HORIZON_EXPIRED, UNREACHABLE_UNDER_MODEL, STRANDED, RESOURCE_UNAVAILABLE and
INVALID_INPUT. SEARCH_LIMIT may contain partial candidates with
`alternatives_complete=false`; it is not an impossibility proof. Unknown/horizon
failure explanations are conservative.

Declared solver bounds: 64 nodes, 256 edges, a 3600-tick global window, 1 MiB
canonical request, and 100000 expansions/labels. These bounds are not measured
large-graph performance or an aggregate RAM guarantee. The independent reference
is limited to six nodes, eight edges, twelve ticks and 100000 recursive prefixes;
limit exhaustion cannot supply partial successful oracle evidence.

## Recorded validation

These are prior observed results, not new runs during publication.

- Fleet fixture at commit `86786dff65cf77bb2994725ea4d1906509f04675`: independent
  review ACCEPT; five focused methods / 25 subcases passed, 36 oversized-number
  probes rejected as ValueError, and 39 interpolated positions checked across
  three buses. Graph/source identity, schema and fresh fixture rebuild matched.
- Waiting-aware final source: 21 tests passed plus 32 independent authored-grid
  comparisons. Initial feature-absence and later numeric/candidate/terminal
  service corruption failures were observed before their fixes. Final independent
  source verdict ACCEPT_OWNED_TRAINING_SOURCE.
- Held-out cohort: independent ACCEPT_SOURCE_ONLY, with no remaining Critical or
  Important findings. **Zero cohort invocations.** The accepted source has 768
  unique graph/time configurations over all 64 subsets of six directed edges;
  128 configurations include the full a->b->c->a topology cycle. Parameters only
  vary when their corresponding edge is present. Two separate literal checks
  require a safe directed cycle and an information-triggered forward suffix while
  preserving underway timing/progress/commitments.
- One worker owns all 768 generated cases, or two admitted workers use disjoint
  ordinal-modulo shards of 384 each; only worker zero runs literals. At most two
  outgoing edges plus WAIT and eight advancing steps give a structural reference
  visit bound of 9841 per case. This is not a measured duration/memory result.
  Receipt counters/request digest cover generated cases only; literals are
  recorded separately. A two-shard aggregate must verify both distinct complete
  receipts and matching pins, with worker-zero literal coverage.
- Remaining minor cohort review recommendations: direct before/after snapshots
  around both revalidation arguments and an explicit generated-only counter-scope
  field in receipts. A reviewed launcher and new runtime admission are still
  required. No launcher or aggregate has been executed or accepted by this source
  review.

Exact source pins:

| Source | SHA256 |
| --- | --- |
| training_multibus.py | a42bdb70c984c42cb02934b91ba8a68aca754f0a78316e3e481285f0ba9ef9c7 |
| test_training_multibus.py | c7d2ca6ddf6da44e80eefc9a37bc0bd7155e7646ad834c4232626d0ce46ea690 |
| training_time_search.py | 88f4f05f72b1be2448ce6312a9494c18af9b4bffb10520126efa75ccf4c451a0 |
| time_reference.py | 21ba3de4c489bfb528498ddb34212375b52063fb77ceace6c564e4999f62204c |
| test_training_time_search.py | 0410f839431912527f123fe831b4c65f25e07121866cfd2c7d33ea07f9a0b2db |
| validate_cyclic_time_cohort.py | 78f05b33f9f09ad46a034d2f8c2e79462d82e2c0e3ba8043d2074ef6b525b196 |

Review evidence digests: fleet final report
`4bafc1bd7632cb9bfe356d588c405a7415058e237239556c4a404e8c51e15abb`;
waiting-aware final source report
`ea753b48c98f3151c7fac3c5d1eb992a23349ee6294bc149c10aa7484d9ca7b3`;
cohort final source report
`d9f2db4d1489b1732b9c8be2e470642d0ccb023b2c768d3f8f4bcb11759c1353`;
waiting-aware final observed run receipt
`38fa70cec70eb0378c3f4a7904349dfeb8894904fec8ae674c5dfe5e7163718b`.

## Integration still required

Maps must accept directed stable IDs, positive authored integer travel ticks,
explicit access/knowledge/closure/safety intervals and a separate geometry mapping.
Its display must label TRAINING assumptions and partial/unknown/expired outcomes.

TripExecutor must supply authoritative clock/progress/committed current-edge data
and preserve reservation/load state through replan and restore. Ledger adoption
must recheck versions and atomically commit resources; two-bus contention,
idempotent booking and rollback isolation are not supplied by this pure module.
Actual UI/debrief, refresh/restore, changed accepted inputs and execution events
need owner-reviewed integration evidence.

The graph-pinned display fixture uses public road geometry with authored
timestamps and interpolated positions. The separate time-search requests author
access, safety and capacity snapshots. Neither contract establishes real vehicle
positions or road suitability. No incident closures, physical hazard-to-road join, forecast
calibration, fleet optimality, operational dispatch or safety are established.
