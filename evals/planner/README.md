# Conditional futures C1 checkpoint

These are uncalibrated synthetic humanitarian training scenarios. MockWorld is a
**MOCK routing/ledger adapter** over hand-authored route catalogs, not the
production pathfinder or a physical fire engine. It supports vehicles already at
their request origin, active directed-edge progression, delivery/service,
destination reservations, stocks, and node-based continuation. It models neither
repositioning/pickup legs nor return-to-base, queues, retreat or turnaround.
Mid-edge closures strand in place with carried aid still reserved. Entry closures
preserve the reachable source junction and permit an observed continuation.

## Server commands

From the cloud worktree, using detached tmux and logged jobs with two CPU threads:

~~~
/opt/venv/bin/python -m pytest -q
/opt/venv/bin/python -m evals.planner.run_checkpoint --output /workspace/knight26/artifacts/monte_carlo/c1.json
~~~

Re-run the artifact command to another output path; deterministic raw JSON SHA256
must match. Default fixture: fixtures/recovery/synthetic_checkpoint.json.
It has one already-committed bus, one available ambulance, one supply truck and
two correlated uncertain road edges. Stable detours are explicitly fixture
assumptions. No current wildfire, current conflict or individual address data.

## Adapter and policy boundaries

services.planner.futures.conditional.build_ensemble(snapshot, seeds, horizon_s=300,
assumptions=None) preserves the full JSON snapshot. truth_events and latent
are evaluator-only; visible_observations(future,time_s) discloses received
history. condition_ensemble(futures,observation) rejects contradictory paths
and exposes the new fact, labeling compatible stress cases without a posterior.

Candidate contains action/vehicle/request/route IDs, kind, quantity,
arrival/deadline/travel seconds, forecast margin and feasibility.
PolicyView(time_s, observations, candidates) supplies no future seed/truth.
PriorityGreedy, AdaptiveDispatch, StaticDispatch are fresh per rollout.
All reject known-negative forecast margins and infeasible candidates.
Evacuation and medical share the first tier, ordered by earliest deadline;
supplies follow. Adaptive prefers larger known forecast margins within the same
vehicle/request; static freezes initial routes. Neither is a Monte Carlo
optimizer, calibrated risk estimator or global-optimal solver. This checkpoint
compares fixed transparent strategies across conditional Monte Carlo futures.

evals.planner.runner.WorldAdapter: policy_view()->PolicyView,
commit(Candidate)->None, advance_to(time_s)->None, outcome()->dict.
The world is trusted to enforce authoritative route and ledger constraints and
supply candidates based on observations only. evaluate(snapshot,futures,
policy_factories,world_factory,decision_step_s=5) passes a deep-copied restricted
view to each policy, not the evaluator world/future, and retains per-run decisions,
input hashes, events and final ledger. It limits each policy to one action per
decision tick with identical ticks/budgets. It never dispatches at the horizon.
compare_with_holdout enforces disjoint training/heldout seeds.

Each outcome has metrics, arrival_times_s, events, final_state. Required
metrics: safe_arrivals, medical_on_time, medical_completed, supplies_delivered,
unmet_goods, unmet_urgent_people, route_failures, constraint_violations, travel_s,
stranded_vehicle_s. Quantiles pool absolute scenario-time service completion
timestamps across completed requests (not persons), conditional on arrival;
route and evaluation failures are separately reported. Safe evacuation counts
arrivals, not boarding. Medical service completed late remains unmet urgent
demand and does not count on-time. Prior completed needs are not future demand.

Ranking's humanitarian tier uses equal weight per safely arrived evacuation
person and on-time medical patient, then actual supply units, then travel seconds.
All raw components remain visible. Policies with evaluation errors or constraint
violations are excluded from the ranking. Result: **best evaluated feasible
strategy**, only among the tested strategies under declared fixture assumptions.
No certificate or real-world probability claim.

## Integration boundary

mc-owned shapes are owned adapter/evaluation records, not a replacement for
root's V1 schema. Real routing/ledger/hazard integration remains C2. The production
adapter must map current edge/progress/load and commitment records exactly,
provide only issued forecasts/observed access, advance the authoritative engine
against evaluator-only future truth and return counted safe service outcomes.
Propose any shared-schema additions through the workstream HANDOFF.

## Benchmark gains and risk-adjusted evaluation

Direct human request adds paired_strategy_metrics(report, baselines=
("priority_greedy","static")) in strategy_metrics.py. Every comparison pairs
identical seeds; raw service/cost gains remain in their own units. Positive gains
mean more service or less cost. Total gain is the sum across tested scenarios,
not a claim that all hypothetical outcomes occurred in one real mission.
The humanitarian tier discloses equal weights for safe evacuation persons and
on-time medical patients; supplies and travel never enter that tier's scalar.

For each seed i, d_i=outcome_i(policy)-outcome_i(baseline).
Sharpe-style paired gain=mean(d_i)/sample_stddev(d_i), using ddof=1.
This is a dimensionless standardized benchmark improvement across synthetic
scenario draws, without financial annualization or calibrated real-world risk.
It follows the differential-return definition in [Sharpe's original account](
https://web.stanford.edu/~wfsharpe/art/sr/sr.htm).

Reports include relative improvement when the baseline is nonzero, downside RMS
sqrt(mean(min(d_i,0)^2)), a downside-adjusted gain, worst gain, p10 gain and the
fractionally weighted mean of the worst10% of tested outcomes. The latter is an
empirical lower-tail statistic; small samples do not establish rare-event safety.
Zero variance, zero downside, too few scenarios and incomplete evaluations yield
undefined ratios with reasons. Failed pairs and constraint violations remain
explicit, and incomplete comparisons are not rankable. Selection continues to
use the disclosed feasibility and humanitarian/supplies/travel order; a Sharpe
number alone never proves a deployment safe or a strategy globally optimal.
