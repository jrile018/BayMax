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
    """Serve a source-isolated DOM shell; mission facts arrive from current-node HTTP responses."""
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>First responder practice · synthetic mission</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#040b11;color:#d9eef2}
*{box-sizing:border-box}body{margin:0;min-width:320px;overflow-x:hidden}
button,input{font:inherit}button{cursor:pointer}
.practice-shell{position:relative;width:100%;min-height:100vh;overflow:hidden;background:radial-gradient(circle at 52% 43%,#103343 0,#071722 42%,#03080e 85%)}
.practice-shell:before{content:"";pointer-events:none;position:absolute;inset:0;z-index:1;background:linear-gradient(#60bdd00b 1px,transparent 1px),linear-gradient(90deg,#60bdd00b 1px,transparent 1px);background-size:42px 42px}
.title-bar{position:absolute;inset:0 0 auto 0;min-height:72px;z-index:8;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:1rem;padding:.8rem 1.2rem;background:linear-gradient(#041019ed,#071925ba);border-bottom:1px solid #75d7e144}
.brand{display:flex;align-items:center;gap:.75rem;min-width:0}.brand-mark{width:29px;height:29px;border:2px solid #6ce4ef;transform:rotate(45deg);box-shadow:0 0 16px #49dae877}
.brand h1{margin:0;color:#e9fbff;font-size:.92rem;letter-spacing:.16em;text-transform:uppercase;white-space:nowrap}.brand small{display:block;color:#78aeb8;font-size:.64rem;letter-spacing:.11em;text-transform:uppercase}
.mode-switch{display:flex;gap:.3rem;border:1px solid #5296a777;background:#071a24cc;padding:.25rem;border-radius:7px}
.mode-switch button,.toolbar-btn{border:0;border-radius:4px;background:transparent;color:#8ab5bd;padding:.45rem .8rem;text-transform:uppercase;letter-spacing:.12em;font-size:.68rem;font-weight:700}
.mode-switch button[aria-selected=true],.toolbar-btn.active{background:#1a6470;color:#e7fcff;box-shadow:0 0 12px #36cddd44}
.status{text-align:right;color:#91c9d0;text-transform:uppercase;letter-spacing:.12em;font-size:.65rem}
.stage{position:absolute;inset:0;z-index:0}.stage svg{width:100%;height:100%;display:block}
.stage-title{position:absolute;top:95px;left:50%;transform:translateX(-50%);z-index:2;color:#c9edf1;background:#071a24c9;border:1px solid #63cbd255;border-radius:4px;padding:.45rem .7rem;font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;text-align:center}
.stage-key{position:absolute;left:50%;bottom:156px;max-width:calc(100% - 1rem);width:max-content;transform:translateX(-50%);z-index:2;display:flex;gap:1rem;flex-wrap:wrap;background:#04131bd9;border:1px solid #4b8b9366;border-radius:4px;padding:.45rem .7rem;color:#afd7da;font-size:.7rem}
.key-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:.35rem;background:#63dae5}.key-dot.facility{background:#f8b86b}.key-dot.resource{background:#f9f6de}.key-dot.closed{background:#fa7372}
.panel-rail{position:absolute;z-index:5;top:91px;bottom:150px;width:min(300px,27vw);display:flex;flex-direction:column;gap:.55rem;pointer-events:none}
.panel-rail.left{left:1rem}.panel-rail.right{right:1rem}
.panel{pointer-events:auto;min-height:42px;display:flex;flex-direction:column;overflow:hidden;border:1px solid #4a9eaa77;border-radius:6px;background:#071b27dc;box-shadow:0 8px 30px #0007, inset 0 1px #b9faff19;backdrop-filter:blur(12px)}
.panel-heading{flex:none;width:100%;border:0;border-bottom:1px solid #4f98a566;background:#0c2b38b5;color:#d9faff;text-align:left;padding:.65rem .75rem;letter-spacing:.13em;text-transform:uppercase;font-size:.67rem;font-weight:800}
.panel-heading:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid #7ef4f9;outline-offset:2px}
.panel-heading .marker{color:#56e5eb;margin-right:.6rem}.panel-body{min-height:0;overflow:auto;padding:.6rem .75rem;font-size:.75rem;line-height:1.45}
.panel.collapsed .panel-body{display:none}.panel.collapsed .panel-heading{border-bottom:0}
.fact{border-bottom:1px solid #52909a44;padding:.45rem 0}.fact:last-child{border:0}.fact strong{display:block;color:#c3edf1;font-size:.69rem;text-transform:uppercase;letter-spacing:.06em}
.fact span{color:#9bbcc2;overflow-wrap:anywhere}.muted{color:#83a9b1}.accent{color:#6be4e9}
.small-list{margin:.3rem 0;padding-left:1.1rem}.small-list li{margin:.25rem 0;overflow-wrap:anywhere}
.episode-btn,.action-btn,.minor-btn{border:1px solid #68c5cd77;background:#0b2a35bd;color:#d7faff;border-radius:4px;padding:.55rem .65rem;text-align:left}
.episode-btn,.action-btn{display:block;width:100%;margin:.34rem 0}.episode-btn[aria-current=true]{border-color:#75edf2;background:#1a5864}.minor-btn{font-size:.69rem;text-transform:uppercase;letter-spacing:.08em}
.action-btn strong{display:block;color:#f0ffff;font-size:.72rem}.action-btn span{display:block;color:#9abcc4;font-size:.68rem;margin-top:.25rem;overflow-wrap:anywhere}
.action-btn:hover,.episode-btn:hover,.minor-btn:hover{background:#195568}.action-btn:disabled{opacity:.5;cursor:not-allowed}
.mission-dock{position:absolute;z-index:9;left:1rem;right:1rem;bottom:1rem;min-height:111px;display:grid;grid-template-columns:115px minmax(180px,1fr) minmax(190px,330px);gap:.8rem;align-items:center;padding:.65rem .9rem;border:1px solid #69bfc799;background:#061924e8;box-shadow:0 0 30px #0009;backdrop-filter:blur(14px)}
.dock-clock{font-variant-numeric:tabular-nums;color:#dffcff;font-size:1.5rem;font-weight:700}.dock-clock small{display:block;font-size:.59rem;letter-spacing:.14em;color:#77b7c0;text-transform:uppercase}
#mission-timeline{min-width:0}.rail-timeline{width:100%}.rail-timeline-track,.rail-timeline-controls{display:flex;align-items:center;gap:.45rem}.rail-timeline-track input{flex:1;min-width:35px;accent-color:#75e9ec}.rail-timeline-controls{margin-top:.3rem}.rail-timeline-endpoints{display:none}
.rail-timeline .panel-title{font-size:.6rem;color:#7eacb5;text-transform:uppercase;letter-spacing:.12em}.rail-timeline-readout{color:#c9ebee;font-size:.72rem}
.data-toggle-chip{border:1px solid #5bafba88;background:#0e3845;color:#dcfaff;border-radius:3px;padding:.28rem .47rem;font-size:.67rem}.data-toggle-chip.active{background:#217987}.data-toggle-chip:disabled{opacity:.45}
.dock-decision{border-left:1px solid #58a4ad55;padding-left:.7rem;min-width:0}.dock-decision strong{display:block;color:#e2faff;font-size:.75rem}.dock-decision small{display:block;color:#91bfc6;font-size:.66rem;margin-top:.2rem}
#debrief-panel[hidden]{display:none}#debrief-panel{position:absolute;z-index:12;top:89px;left:50%;transform:translateX(-50%);width:min(620px,calc(100vw - 2rem));max-height:calc(100vh - 240px);overflow:auto;background:#071b27f2;border:1px solid #6bd1d9;border-radius:7px;box-shadow:0 15px 50px #000c;padding:1rem}
#debrief-panel h2{margin:.1rem 0 .7rem;font-size:1rem;text-transform:uppercase;letter-spacing:.1em}#debrief-panel table{width:100%;border-collapse:collapse;font-size:.7rem}
#debrief-panel th,#debrief-panel td{padding:.35rem;border-bottom:1px solid #4d8a9355;text-align:left}#debrief-panel th{color:#8acbd3}
#debrief-panel p,#debrief-panel li{font-size:.75rem;line-height:1.4}
#notice{position:absolute;z-index:14;top:78px;left:50%;transform:translateX(-50%);max-width:min(500px,90vw);background:#2b1820;color:#ffe2e6;border:1px solid #f28696;padding:.6rem .9rem;border-radius:5px;font-size:.75rem}#notice[hidden]{display:none}
@media(max-width:900px){.practice-shell{min-height:100vh;overflow:visible}.title-bar{position:relative;grid-template-columns:1fr auto}.mode-switch{grid-column:1/-1;justify-self:center}.status{grid-column:2;grid-row:1}.stage{position:relative;height:48vh}.stage-title{top:.8rem}.stage-key{bottom:.6rem}.panel-rail{position:relative;inset:auto!important;width:auto!important;max-height:none!important;margin:.6rem 1rem}.panel-rail.right{right:auto}.panel{max-height:240px!important}.mission-dock{position:relative;left:auto;right:auto;bottom:auto;margin:1rem;grid-template-columns:minmax(75px,95px) minmax(0,1fr);max-width:calc(100% - 2rem);overflow:hidden}.rail-timeline-controls{flex-wrap:wrap}.dock-decision{grid-column:1/-1;border-left:0;border-top:1px solid #58a4ad55;padding:.5rem 0 0}#debrief-panel{position:relative;top:auto;left:auto;transform:none;margin:1rem auto;max-height:none}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
</style>
</head>
<body><div id="practice-root" class="practice-shell">
<header id="title-bar" class="title-bar">
  <div class="brand"><span class="brand-mark" aria-hidden="true"></span><div><h1>Response practice</h1><small>Synthetic command exercise</small></div></div>
  <nav id="top-center-actions" class="mode-switch" role="tablist" aria-label="Exercise mode">
    <button id="practice-mode" type="button" role="tab" aria-selected="true">Practice</button>
    <button id="review-mode" type="button" role="tab" aria-selected="false">Review</button>
  </nav><div id="connection-status" class="status" role="status">Connecting</div>
</header>
<main id="mission-stage" class="stage" aria-label="Synthetic known road network">
  <svg id="mission-network" viewBox="0 0 1000 700" role="img" aria-label="Current known synthetic road graph"></svg>
  <div id="stage-title" class="stage-title">Received network view</div>
  <div id="stage-key" class="stage-key"><span><i class="key-dot"></i>Camp / road</span><span><i class="key-dot facility"></i>Facility</span><span><i class="key-dot resource"></i>Resource</span><span><i class="key-dot closed"></i>Received closure</span></div>
</main>
<aside id="left-panel-stack" class="panel-rail left" aria-label="Scenario and layers">
  <section id="scenario-panel" class="panel" data-panel-id="scenario"><button type="button" class="panel-heading" aria-expanded="true" aria-controls="scenario-content"><span class="marker">◇</span>Scenario</button><div id="scenario-content" class="panel-body"></div></section>
  <section id="layers-panel" class="panel" data-panel-id="layers"><button type="button" class="panel-heading" aria-expanded="true" aria-controls="layers-content"><span class="marker">◇</span>Layers &amp; received facts</button><div id="layers-content" class="panel-body"></div></section>
</aside>
<aside id="right-context-rail" class="panel-rail right" aria-label="Display and controls">
  <section id="display-panel" class="panel" data-panel-id="display"><button type="button" class="panel-heading" aria-expanded="true" aria-controls="display-content"><span class="marker">◇</span>Display</button><div id="display-content" class="panel-body"></div></section>
  <section id="controls-panel" class="panel" data-panel-id="controls"><button type="button" class="panel-heading" aria-expanded="true" aria-controls="controls-content"><span class="marker">◇</span>Controls</button><div id="controls-content" class="panel-body"></div></section>
</aside>
<section id="debrief-panel" hidden aria-label="Exercise debrief"></section>
<div id="notice" role="alert" hidden></div>
<footer id="mission-dock" class="mission-dock">
  <div id="mission-clock" class="dock-clock"><small>Mission clock</small>0:00</div>
  <div id="mission-timeline" aria-label="Recorded decision history"></div>
  <div id="thinking-time" class="dock-decision"><strong>Decision time 0.0 s</strong><small>Browser timer only · no effect on simulation</small></div>
</footer>
</div><script type="module" src="/vendor/gods_eye_view/practiceShell.js"></script></body></html>
"""


def render_current_preview_html(episode_name, severity_scale, current_node, *, decision_limit=40):
    """Bundle a read-only saved decision for sandboxed visual inspection."""
    from pathlib import Path

    known_node = {
        key: _visible(current_node[key], f"current_node.{key}")
        for key in ("depth", "time_s", "knowledge", "actions")
    }
    known_node["decision_nonce"] = "preview-only"
    meta = {
        "mode": "live_full_mission",
        "limits": {"decision_limit": decision_limit, "branch_limit": 3, "decision_step_s": 15},
        "severity_scale": _visible(severity_scale, "severity_scale"),
        "episodes": [{"name": str(episode_name)}],
    }

    def script_json(value):
        return (json.dumps(value, ensure_ascii=False, allow_nan=False)
                .replace("&", r"\u0026").replace("<", r"\u003c")
                .replace(">", r"\u003e").replace("\u2028", r"\u2028")
                .replace("\u2029", r"\u2029"))

    folder = Path(__file__).resolve().parent / "vendor" / "gods_eye_view"
    modules = (
        ("panelRailGeometry.js", "resolveHudRailLayout"),
        ("panelStackLayout.js", "allocatePanelStackHeights"),
        ("railTimeline.js", "createRailTimeline"),
        ("practiceShell.js", "mountPracticeShell"),
    )
    wrapped = []
    for filename, symbol in modules:
        code = (folder / filename).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in code.splitlines()
            if not line.startswith("import ")
        ).replace("export function ", "function ")
        if "</script" in code.lower():
            raise ValueError("module cannot be safely embedded")
        wrapped.append(f"const {{{symbol}}} = (() => {{\n{code}\nreturn {{{symbol}}};\n}})();")

    loader = (
        "const payloads = {'/meta': " + script_json(meta) +
        ", '/start': {session: 'preview-only', node: " + script_json(known_node) + "}};\n"
        "const fetcher = async (path) => ({\n"
        "  ok: Object.prototype.hasOwnProperty.call(payloads, path),\n"
        "  status: Object.prototype.hasOwnProperty.call(payloads, path) ? 200 : 404,\n"
        "  json: async () => payloads[path] || {error: 'read_only_preview'}\n"
        "});\n"
        "mountPracticeShell({fetcher, readOnly: true});"
    )
    html = render_practice_html()
    html = html.replace('<html lang="en">', '<html lang="en" data-practice-preview>')
    html = html.replace("</style>", """
#preview-banner{position:absolute;z-index:20;left:50%;top:75px;transform:translateX(-50%);width:min(650px,94vw);padding:.5rem .7rem;border:1px solid #75d7e1;background:#102f3bf2;color:#effdff;text-align:center;font-size:.7rem}
#stage-title{top:130px}
@media(max-width:900px){#preview-banner{position:relative;top:auto;left:auto;transform:none;width:auto;margin:.4rem 1rem}#stage-title{top:.8rem}}
</style>""")
    html = html.replace(
        '<header id="title-bar"',
        '<div id="preview-banner">Saved current decision preview · choices are disabled · live mission requires the practice server</div><header id="title-bar"',
    )
    license_text = (folder / "LICENSE").read_text(encoding="utf-8")
    if "</script" in license_text.lower():
        raise ValueError("license cannot be safely embedded")
    license_block = '<script type="text/plain" id="gods-eye-view-mit-license">\n' + license_text + '</script>\n'
    script_tag = '<script type="module" src="/vendor/gods_eye_view/practiceShell.js"></script>'
    return html.replace(script_tag, license_block + "<script>\n" + "\n".join(wrapped) +
                        "\n" + loader + "\n</script>")


__all__ = ["build_practice_pack", "render_practice_html", "render_current_preview_html", "select_practice_actions"]
