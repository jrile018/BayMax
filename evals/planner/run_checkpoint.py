"""Write deterministic raw C1 artifacts; all simulation runs on the supplied cloud."""
from pathlib import Path
import argparse
import hashlib
import json
from evals.planner.mock_world import MockWorld
from evals.planner.runner import compare_with_holdout
from evals.planner.strategy_metrics import paired_strategy_metrics
from services.planner.policies.dispatch import AdaptiveDispatch,PriorityGreedy,StaticDispatch

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--fixture",default="fixtures/recovery/synthetic_checkpoint.json")
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    snapshot=json.loads(Path(args.fixture).read_text())
    report=compare_with_holdout(snapshot,list(range(32)),list(range(1000,1016)),
        {"adaptive":AdaptiveDispatch,"priority_greedy":PriorityGreedy,"static":StaticDispatch},
        MockWorld,horizon_s=100,decision_step_s=5)
    for split in ("training","heldout"):
        report[split]["paired_strategy_metrics"]=paired_strategy_metrics(report[split])
    report["fixture_version"]=snapshot["fixture_version"]
    report["fixture_label"]=snapshot["label"]
    report["fixture_sha256"]=hashlib.sha256(Path(args.fixture).read_bytes()).hexdigest()
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)+"\n")
    summary={split:report[split]["aggregates"] for split in ("training","heldout")}
    for split in summary.values():
        for policy in split.values():
            policy.pop("per_run")
    summary["paired_strategy_metrics"]={}
    for split in ("training","heldout"):
        paired=report[split]["paired_strategy_metrics"]
        reduced={}
        for policy,benchmarks in paired["comparisons"].items():
            reduced[policy]={}
            for benchmark,comparison in benchmarks.items():
                reduced[policy][benchmark]={"complete_evaluation":comparison["complete_evaluation"],
                    "simulated_feasibility":comparison["simulated_feasibility"],
                    "measures":{name:{k:v for k,v in measure.items() if k!="paired_deltas"}
                                for name,measure in comparison["measures"].items()}}
        summary["paired_strategy_metrics"][split]=reduced
    summary.update(fixture_label=report["fixture_label"],fixture_version=report["fixture_version"],
                   calibration=report["training"]["calibration"],result_label=report["training"]["result_label"],
                   training_seeds=list(range(32)),heldout_seeds=list(range(1000,1016)),
                   raw_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    output.with_suffix(".summary.json").write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n")
    print(json.dumps(summary,sort_keys=True,indent=2))

if __name__=="__main__":
    main()
