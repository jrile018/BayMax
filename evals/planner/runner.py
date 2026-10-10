"""Fair common-scenario evaluation through an injected routing/ledger world.

The runner never gives a future descriptor to a policy. World adapters are trusted
to produce observation-only route candidates; the synthetic adapter is NOT the
production router. No claim of a globally optimal policy is made here.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from dataclasses import asdict
from typing import Callable, Mapping, Protocol
from services.planner.futures.conditional import build_ensemble
from services.planner.policies.dispatch import Candidate, PolicyView

METRICS=("safe_arrivals","medical_on_time","medical_completed","supplies_delivered",
         "unmet_goods","unmet_urgent_people","route_failures","constraint_violations",
         "travel_s","stranded_vehicle_s")

class WorldAdapter(Protocol):
    """Adapter enforces routing, atomic ledger commits and physical progression."""
    def policy_view(self) -> PolicyView: ...
    def commit(self, candidate: Candidate) -> None: ...
    def advance_to(self, time_s: float) -> None: ...
    def outcome(self) -> dict: ...

def _canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                                     ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def _quantile(values, q):
    if not values:
        return None
    vals=sorted(values)
    pos=(len(vals)-1)*q
    lo=math.floor(pos); hi=math.ceil(pos)
    return vals[lo]+(vals[hi]-vals[lo])*(pos-lo)

def _view_record(view):
    if not isinstance(view,PolicyView):
        raise TypeError("adapter must supply PolicyView")
    record=asdict(view)
    for observation in view.observations:
        if observation.get("received_at_s",float("inf"))>view.time_s:
            raise ValueError("policy observation was not received yet")
        if observation.get("issued_at_s",float("inf"))>view.time_s:
            raise ValueError("policy observation was not issued yet")
    return record

def evaluate(snapshot: Mapping, futures: list[dict],
             policy_factories: Mapping[str,Callable], world_factory: Callable,
             decision_step_s: float=5) -> dict:
    """Each policy receives a fresh world for every common future.

    Factory/world errors remain failed rows and in all sample-count denominators.
    Quantiles pool actual completed request arrivals, conditional on arrival;
    route failures, unmet requests and evaluation failures remain beside them.
    """
    if not math.isfinite(decision_step_s) or decision_step_s<=0:
        raise ValueError("decision_step_s must be finite and positive")
    seeds=[f["seed"] for f in futures]
    if len(set(seeds))!=len(seeds):
        raise ValueError("duplicate scenario seeds")
    digest=_canonical_hash(snapshot)
    for f in futures:
        if f["initial_snapshot"]!=snapshot or f["snapshot_hash"]!=digest:
            raise ValueError("future does not preserve the supplied known snapshot")
        if f["start_time_s"]!=snapshot["time_s"] or not math.isfinite(f["horizon_end_s"]) or f["horizon_end_s"]<f["start_time_s"]:
            raise ValueError("invalid future horizon")
    runs=[]
    for label,make_policy in policy_factories.items():
        for f in futures:
            row={"policy":label,"seed":f["seed"],"snapshot_hash":digest,
                 "actions":[],"evaluation_failed":False}
            try:
                policy=make_policy()
                world=world_factory(copy.deepcopy(snapshot),copy.deepcopy(f))
                t=f["start_time_s"]
                while t<f["horizon_end_s"]:
                    view=world.policy_view()
                    if view.time_s!=t:
                        raise ValueError("adapter clock disagrees with evaluation clock")
                    before=_view_record(view)
                    action=policy.choose(copy.deepcopy(view))
                    if action is not None:
                        if action not in view.candidates or not action.feasible:
                            raise ValueError("policy selected an unavailable candidate")
                        world.commit(action)
                        row["actions"].append({"time_s":t,"view":before,
                                               "view_hash":_canonical_hash(before),
                                               "action":asdict(action)})
                    t=min(t+decision_step_s,f["horizon_end_s"])
                    world.advance_to(t)
                result=world.outcome()
                for metric in METRICS:
                    value=result["metrics"][metric]
                    if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                        raise ValueError("invalid nonnegative raw outcome "+metric)
                if any(not math.isfinite(x) for x in result["arrival_times_s"]):
                    raise ValueError("invalid arrival times")
                row.update(result)
            except Exception as exc:
                row.update(evaluation_failed=True,error=f"{type(exc).__name__}: {exc}",
                           metrics=None,arrival_times_s=[])
            runs.append(row)
    aggregates={}
    for label in policy_factories:
        rows=[r for r in runs if r["policy"]==label]
        measured=[r for r in rows if not r["evaluation_failed"]]
        arrivals=[t for r in measured for t in r["arrival_times_s"]]
        totals={k:sum(r["metrics"][k] for r in measured) for k in METRICS}
        successes=sum(r["metrics"]["route_failures"]==0 and
                      r["metrics"]["constraint_violations"]==0 and
                      r["metrics"]["unmet_urgent_people"]==0 for r in measured)
        aggregates[label]={"sample_count":len(rows),"measured_run_count":len(measured),
            "evaluation_failed_count":len(rows)-len(measured),"raw_totals":totals,
            "tested_scenario_success_fraction":successes/len(rows) if rows else None,
            "arrival_quantiles_s":{"sample_count":len(arrivals),
                "conditioning":"actual completed request arrivals only; failures reported separately",
                "p50":_quantile(arrivals,.5),"p90":_quantile(arrivals,.9),
                "p95":_quantile(arrivals,.95)},
            "per_run":[{"seed":r["seed"],"evaluation_failed":r["evaluation_failed"],
                        "metrics":r["metrics"]} for r in rows]}
    feasible=[name for name,a in aggregates.items() if a["sample_count"] and
              not a["evaluation_failed_count"] and not a["raw_totals"]["constraint_violations"]]
    ranking=sorted(feasible,key=lambda name:(
        -(aggregates[name]["raw_totals"]["safe_arrivals"]+
          aggregates[name]["raw_totals"]["medical_on_time"]),
        -aggregates[name]["raw_totals"]["supplies_delivered"],
        aggregates[name]["raw_totals"]["travel_s"],name))
    return {"schema":"mc-owned-evaluation-v1","snapshot_hash":digest,
        "calibration":"uncalibrated tested-scenario fractions",
        "result_label":"best evaluated feasible strategy",
        "within_humanitarian_tier_rule":"equal weight per safely arrived evacuation person and on-time medical patient",
        "ranking":ranking,"runs":runs,"aggregates":aggregates,
        "adapter":getattr(world_factory,"label","injected adapter; capability supplied by caller")}

def compare_with_holdout(snapshot, training_seeds, heldout_seeds, policy_factories,
                         world_factory, horizon_s=100, decision_step_s=5, assumptions=None):
    if set(training_seeds)&set(heldout_seeds):
        raise ValueError("training and heldout seeds must be disjoint")
    training=build_ensemble(snapshot,training_seeds,horizon_s,assumptions)
    heldout=build_ensemble(snapshot,heldout_seeds,horizon_s,assumptions)
    return {"training":evaluate(snapshot,training,policy_factories,world_factory,decision_step_s),
            "heldout":evaluate(snapshot,heldout,policy_factories,world_factory,decision_step_s),
            "selection":"policies fixed before heldout evaluation; no heldout tuning"}
