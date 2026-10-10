"""Finite, truth-isolated first-responder practice export."""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping


_FORBIDDEN = {
    "truth_events", "observation_events", "future", "future_seed", "seed",
    "latent", "latent_outcomes", "outcome", "outcomes", "final_state",
    "arrival_times_s", "hidden", "hidden_state", "metrics",
}


def _visible(value, path="visible"):
    """Copy a known-state payload and reject hidden/evaluator fields."""
    if isinstance(value, Mapping):
        clean = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            if key.lower() in _FORBIDDEN or key.lower().startswith("hidden_"):
                raise ValueError(f"{path}.{key} is not trainee-visible")
            clean[key] = _visible(item, f"{path}.{key}")
        return clean
    if isinstance(value, (tuple, list)):
        return [_visible(item, f"{path}[]") for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"{path} contains a non-JSON value")


def select_practice_actions(actions, branch_limit):
    legal = []
    ids = set()
    for action in actions:
        if not isinstance(action, Mapping):
            raise TypeError("world actions must be mappings")
        action = _visible(action, "action")
        action_id = action.get("id")
        if not isinstance(action_id, str) or not action_id:
            raise ValueError("action id must be a nonempty string")
        if action_id in ids:
            raise ValueError("duplicate action id")
        ids.add(action_id)
        if action.get("feasible", True) and action.get("supported", True):
            legal.append(action)
    waits = [a for a in legal if a.get("kind") == "wait"]
    moves = [a for a in legal if a.get("kind") != "wait"]
    moves.sort(key=lambda a: (
        -float(a.get("expected_urgent") or 0),
        -float(a.get("expected_supply") or 0),
        str(a.get("kind", "")), str(a["id"]),
    ))
    selected = waits[:1]
    seen_resources = set()
    for action in moves:
        resource = action.get("vehicle_id")
        distinct = (resource, action.get("request_id"), action.get("destination_id"))
        if resource in seen_resources:
            continue
        if distinct in {(x.get("vehicle_id"), x.get("request_id"), x.get("destination_id")) for x in selected}:
            continue
        selected.append(action)
        seen_resources.add(resource)
        if len(selected) >= branch_limit:
            return selected[:branch_limit]
    for action in moves:
        if action not in selected:
            selected.append(action)
        if len(selected) >= branch_limit:
            break
    return selected[:branch_limit]


def _critique(metrics):
    prompts = ["Which received facts supported your choice, and which needs were still unknown?"]
    if metrics.get("unmet_urgent_people", 0):
        prompts.append("What earlier dispatch or coverage choice might have reduced unmet urgent need?")
    if metrics.get("route_failures", 0):
        prompts.append("What road information was available before the failed route choice?")
    if metrics.get("stranded_vehicle_s", 0):
        prompts.append("How did stranded capacity affect later choices?")
    prompts.append("Compare service gained with travel time, route failures, and remaining unmet needs.")
    return prompts


def _debrief(world, comparison):
    world.advance_to(world.horizon_end_s)
    result = world.outcome()
    metrics = copy.deepcopy(result["metrics"])
    return {
        "metrics": metrics,
        "comparison": copy.deepcopy(comparison),
        "critique_prompts": _critique(metrics),
        "scope": "Synthetic scenario outcome; this exercise does not establish real-world performance improvement.",
    }


def build_practice_pack(
    episodes,
    *,
    world_factory=None,
    branch_limit=3,
    depth_limit=3,
):
    """Precompute a bounded choice tree; the browser never receives future inputs."""
    if world_factory is None:
        from evals.planner.training_world import TrainingWorld
        world_factory = TrainingWorld
    if isinstance(branch_limit, bool) or not isinstance(branch_limit, int) or not 2 <= branch_limit <= 3:
        raise ValueError("branch_limit must be 2 or 3")
    if isinstance(depth_limit, bool) or not isinstance(depth_limit, int) or not 1 <= depth_limit <= 4:
        raise ValueError("depth_limit must be 1 through 4")
    if not episodes:
        raise ValueError("at least one episode is required")

    def build_node(world, depth, comparison):
        knowledge = _visible(world.knowledge(), "knowledge")
        node = {"depth": depth, "time_s": world.time_s, "knowledge": knowledge, "actions": []}
        if depth == depth_limit or world.time_s >= world.horizon_end_s:
            node["debrief"] = _debrief(world, comparison)
            return node
        choices = select_practice_actions(world.actions(), branch_limit)
        if not choices:
            node["debrief"] = _debrief(world, comparison)
            return node
        node["actions"] = choices
        node["children"] = {}
        for action in choices:
            child_world = copy.deepcopy(world)
            child_world.step(action["id"])
            if child_world.time_s <= world.time_s and child_world.time_s < child_world.horizon_end_s:
                raise ValueError("world.step must advance time")
            node["children"][action["id"]] = build_node(child_world, depth + 1, comparison)
        return node

    packed = []
    for index, episode in enumerate(episodes):
        world = world_factory(copy.deepcopy(episode["situation"]), copy.deepcopy(episode["future"]))
        packed.append({
            "name": str(episode.get("name", f"Episode {index + 1}")),
            "root": build_node(world, 0, episode.get("comparison", {})),
        })
    from services.planner.futures.training import severity_profile
    return {
        "schema": "synthetic-first-responder-practice-v1",
        "severity_scale": [{"level": i, "description": severity_profile(i)["description"]}
                           for i in range(1, 11)],
        "limits": {"branch_limit": branch_limit, "depth_limit": depth_limit},
        "episodes": packed,
    }


def render_practice_html():
    """Render a same-origin client with no scenario or future data embedded."""
    return """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>First responder practice</title>
<style>
:root{font-family:system-ui,Segoe UI,sans-serif;color:#17332e;background:#edf4ef}
body{margin:0}header{background:#153f38;color:white;padding:1.2rem max(1rem,calc((100vw - 1050px)/2))}
main{max-width:1050px;margin:1.5rem auto;padding:0 1rem 3rem}
h1{margin:.1rem 0;font-size:1.7rem}h2{margin:.2rem 0 1rem}
p{line-height:1.5}.muted{color:#546b63}.card{background:white;border:1px solid #cadbd2;border-radius:12px;padding:1rem;margin:1rem 0;box-shadow:0 2px 8px #163b3211}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:.8rem}
button{font:inherit;text-align:left;border:1px solid #9ebcaf;background:#f7fcf9;color:#17332e;border-radius:9px;padding:.85rem;cursor:pointer}
button:hover,button:focus{outline:2px solid #187b61;background:#e8f6ee}
button:disabled{opacity:.45;cursor:not-allowed}.action{display:block;width:100%;margin:.6rem 0}
strong{display:block}.small{font-size:.9rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f7f4;padding:.8rem;border-radius:8px}
.metric{display:flex;justify-content:space-between;border-bottom:1px solid #e0ebe4;padding:.35rem 0}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{text-align:left;border-bottom:1px solid #dbe9df;padding:.4rem}th{background:#edf4ef}td:not(:first-child){font-variant-numeric:tabular-nums}
</style>
<header><h1>First responder practice</h1><div>Synthetic situation exercise · decisions use only received information</div></header>
<main><div id="app"></div></main>
<script>
let META=null,sessionToken=null;
const app=document.getElementById("app");
let episodeIndex=0,node=null,choiceTimes=[],startedAt=0,clockEl=null,pending=false;
function el(tag,txt,cls){const x=document.createElement(tag);if(txt!==undefined)x.textContent=String(txt);if(cls)x.className=cls;return x}
function add(parent,tag,txt,cls){const x=el(tag,txt,cls);parent.appendChild(x);return x}
function card(parent,title){const x=add(parent,"section",undefined,"card");add(x,"h2",title);return x}
function human(s){return String(s).replaceAll("_"," ")}
async function api(path,body){const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const data=await response.json();if(!response.ok){const error=new Error(data.error||"Request failed");error.status=response.status;throw error}return data}
function fail(error){app.replaceChildren();add(app,"p",String(error),"card");const retry=add(app,"button","Restart this episode");retry.onclick=()=>restart(episodeIndex)}
async function restart(i){pending=false;try{const data=await api("/start",{episode_index:i});episodeIndex=i;sessionToken=data.session;node=data.node;choiceTimes=[];startedAt=performance.now();render()}catch(error){fail(error)}}
function facts(container,knowledge){
  const keys=["severity","assumptions","observations","requests","roads","facilities","resources","vehicles","stocks","coverage_by_vehicle","idle_resources","camp_coverage","goals"];
  const shown=new Set();
  for(const key of keys){if(!(key in knowledge))continue;shown.add(key);
    const v=knowledge[key], block=add(container,"div",undefined,"card");
    add(block,"strong",human(key));
    add(block,"pre",JSON.stringify(v,null,2));
  }
  const rest=Object.keys(knowledge).filter(k=>!shown.has(k)&&k!=="time_s");
  if(rest.length){const block=add(container,"div",undefined,"card");add(block,"strong","Other received facts");
    const r={};for(const k of rest)r[k]=knowledge[k];add(block,"pre",JSON.stringify(r,null,2))}
}
function metricList(parent,metrics){for(const [key,val] of Object.entries(metrics)){
  const row=add(parent,"div",undefined,"metric");add(row,"span",human(key));add(row,"strong",val)
}}
function render(){
  app.replaceChildren();
  const top=card(app,"Exercise");
  add(top,"p","Choose an episode, review facts received by command, then select one available action. The simulation advances 15 seconds per choice.");
  const scale=add(top,"details");add(scale,"summary","Instructor severity scale (1–10)");
  add(scale,"p","Descriptions and rates are editable synthetic defaults, not empirically estimated probabilities or a physical fire-intensity scale.","muted");
  const scaleList=add(scale,"ol");META.severity_scale.forEach(x=>add(scaleList,"li",`Level ${x.level}: ${x.description}`));
  const scope=META.mode==="live_full_mission"?"Full mission":"Finite demonstration";
  add(top,"p",`${scope}: up to ${META.limits.branch_limit} choices per step and ${META.limits.decision_limit} decisions, 15 simulated seconds apart, before debrief.`,"muted");
  const tabs=add(top,"div",undefined,"grid");
  META.episodes.forEach((ep,i)=>{const b=add(tabs,"button",ep.name);b.setAttribute("aria-current",i===episodeIndex?"true":"false");b.onclick=()=>restart(i)});
  const reset=add(top,"button","Restart this episode");reset.onclick=()=>restart(episodeIndex);
  const state=card(app,node.debrief?`Mission complete · simulation time ${node.time_s} s`:`Decision ${node.depth+1} · simulation time ${node.time_s} s`);
  add(state,"p","Displayed facts are the command team's current received knowledge. Future events remain hidden.","muted");
  facts(app,node.knowledge);
  if(node.debrief){
    const d=card(app,"Debrief");
    add(d,"p",node.debrief.scope);
    metricList(d,node.debrief.metrics);
    add(d,"h3","Your decision time");
    choiceTimes.forEach((t,i)=>{const row=add(d,"div",undefined,"metric");add(row,"span",`Choice ${i+1}: ${t.action}`);add(row,"strong",`${t.seconds.toFixed(1)} s`)});
    const total=choiceTimes.reduce((sum,t)=>sum+t.seconds,0);
    const timing=add(d,"div",undefined,"metric");add(timing,"span","Total thinking time");add(timing,"strong",`${total.toFixed(1)} s`);
    add(d,"p","Browser thinking time is personal practice feedback; it does not change simulation outcomes.","muted");
    clockEl=null;
    if(Object.keys(node.debrief.comparison||{}).length){
      add(d,"h3","Same-scenario comparison with equal decision budget");
      const c=node.debrief.comparison;
      add(d,"p",`The planner and greedy comparator each made up to ${c.decision_budget} choices, 15 simulated seconds apart, before the world ran to the same horizon.`,"muted");
      const table=add(d,"table"),head=add(table,"thead"),heads=add(head,"tr");
      ["Metric","Your outcome","Situational planner","Greedy comparator"].forEach(x=>add(heads,"th",x));
      const body=add(table,"tbody");
      for(const [key,val] of Object.entries(node.debrief.metrics)){const row=add(body,"tr");
        [human(key),val,c.situational?.[key]??"—",c.priority_greedy?.[key]??"—"].forEach(x=>add(row,"td",x))}
    }
    add(d,"h3","Discuss");
    const list=add(d,"ul");
    node.debrief.critique_prompts.forEach(p=>add(list,"li",p));
    return;
  }
  const choices=card(app,"Available choices");
  clockEl=add(choices,"p","Thinking time on this choice: 0.0 s","muted");
  startedAt=performance.now();
  for(const action of node.actions){
    const b=add(choices,"button",undefined,"action");
    const label=[action.kind,action.vehicle_id,action.request_id,action.destination_id].filter(Boolean).join(" · ");
    add(b,"strong",label||action.id);
    const why=action.explanation||action.explanation_data||"Advance the scenario with this action.";
    add(b,"span",typeof why==="string"?why:JSON.stringify(why));
    b.onclick=async()=>{if(pending)return;pending=true;
      app.querySelectorAll("button").forEach(button=>button.disabled=true);
      const seconds=(performance.now()-startedAt)/1000,previousDepth=node.depth;
      try{const data=await api("/step",{session:sessionToken,decision_nonce:node.decision_nonce,action_id:action.id});
        choiceTimes.push({action:label||action.id,seconds});node=data.node;render()}
      catch(error){try{const current=await api("/current",{session:sessionToken});if(current.node.depth>previousDepth)choiceTimes.push({action:label||action.id,seconds});node=current.node;render()}
        catch(recoveryError){fail(recoveryError)}}
      finally{pending=false}};

  }
}
setInterval(()=>{if(clockEl)clockEl.textContent=`Thinking time on this choice: ${((performance.now()-startedAt)/1000).toFixed(1)} s`},100);
fetch("/meta").then(r=>{if(!r.ok)throw new Error("Metadata unavailable");return r.json()}).then(meta=>{META=meta;restart(0)}).catch(fail);
</script></html>
"""


__all__ = ["build_practice_pack", "render_practice_html", "select_practice_actions"]
