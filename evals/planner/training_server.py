"""Localhost practice delivery: current known state only, with live missions by default."""
from __future__ import annotations

import argparse
import copy
import json
import math
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from evals.planner.practice import _debrief, _visible, render_practice_html, select_practice_actions


class StaleDecision(Exception):
    pass


def _public_finite(node, nonce):
    public = {
        "depth": node["depth"], "time_s": node["time_s"],
        "knowledge": node["knowledge"], "actions": node["actions"],
        "decision_nonce": nonce,
    }
    if "debrief" in node:
        public["debrief"] = node["debrief"]
    return public


def _public_live(world, depth, nonce, comparison, branch_limit):
    public = {
        "depth": depth, "time_s": world.time_s,
        "knowledge": _visible(world.knowledge(), "knowledge"),
        "actions": [], "decision_nonce": nonce,
    }
    if world.time_s >= world.horizon_end_s:
        public["debrief"] = _debrief(world, comparison)
    else:
        public["actions"] = select_practice_actions(world.actions(), branch_limit)
    return public


def make_server(pack, host="127.0.0.1", port=8766, *,
                live_episodes=None, world_factory=None, planner=None):
    """Serve finite fallback or live worlds, never raw pack/future files."""
    if not isinstance(pack, dict) or not pack.get("episodes"):
        raise ValueError("practice pack requires episodes")
    live = live_episodes is not None
    branch_limit = pack["limits"]["branch_limit"]
    comparisons = []
    decision_limits = []
    if live:
        if len(live_episodes) != len(pack["episodes"]):
            raise ValueError("live episode count must match pack")
        if world_factory is None:
            from evals.planner.training_world import TrainingWorld
            world_factory = TrainingWorld
        if planner is None:
            from services.planner.policies.situational import plan_situation
            planner = plan_situation
        from evals.planner.run_training import evaluate_episode
        for episode in live_episodes:
            situation, future = episode["situation"], episode["future"]
            sample = world_factory(copy.deepcopy(situation), copy.deepcopy(future))
            decision_limit = math.ceil((sample.horizon_end_s - sample.time_s) / 15)
            if decision_limit < 1:
                raise ValueError("live episode must have a future decision")
            situational = evaluate_episode(situation, future, "situational",
                world_factory=world_factory, planner=planner,
                decision_limit=decision_limit, branch_limit=branch_limit)
            greedy = evaluate_episode(situation, future, "priority_greedy",
                world_factory=world_factory, planner=planner,
                decision_limit=decision_limit, branch_limit=branch_limit)
            comparisons.append({
                "decision_budget": decision_limit, "decision_step_s": 15,
                "situational": situational["metrics"],
                "priority_greedy": greedy["metrics"],
            })
            decision_limits.append(decision_limit)

    sessions = {}
    lock = threading.Lock()
    meta = {
        "schema": pack["schema"],
        "mode": "live_full_mission" if live else "finite_demonstration",
        "limits": {
            "branch_limit": branch_limit,
            "decision_limit": max(decision_limits) if live else pack["limits"]["depth_limit"],
            "decision_step_s": 15,
        },
        "severity_scale": pack["severity_scale"],
        "episodes": [{"name": episode["name"]} for episode in pack["episodes"]],
    }
    html = render_practice_html().encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send(self, status, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json_body(self):
            length = self.headers.get("Content-Length")
            if length is None or not length.isdigit() or not 0 < int(length) <= 8192:
                raise ValueError("request body must be 1-8192 bytes")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ValueError("Content-Type must be application/json")
            value = json.loads(self.rfile.read(int(length)))
            if not isinstance(value, dict):
                raise ValueError("request JSON must be an object")
            return value

        def do_GET(self):
            route = urlsplit(self.path).path
            if route == "/":
                self._send(200, html, "text/html; charset=utf-8")
            elif route == "/meta":
                self._send(200, meta)
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self):
            route = urlsplit(self.path).path
            if route not in ("/start", "/step", "/current"):
                self._send(404, {"error": "not_found"})
                return
            try:
                data = self._json_body()
                if route == "/start":
                    index = data.get("episode_index")
                    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(pack["episodes"]):
                        raise ValueError("invalid episode")
                    token = secrets.token_urlsafe(32)
                    nonce = secrets.token_urlsafe(16)
                    if live:
                        episode = live_episodes[index]
                        world = world_factory(copy.deepcopy(episode["situation"]),
                                              copy.deepcopy(episode["future"]))
                        session = {"world": world, "depth": 0, "index": index, "nonce": nonce}
                        public = _public_live(world, 0, nonce, comparisons[index], branch_limit)
                    else:
                        node = pack["episodes"][index]["root"]
                        session = {"node": node, "nonce": nonce}
                        public = _public_finite(node, nonce)
                    with lock:
                        sessions[token] = session
                    self._send(200, {"session": token, "node": public})
                    return
                if route == "/current":
                    token = data.get("session")
                    if not isinstance(token, str):
                        raise ValueError("invalid session")
                    with lock:
                        session = sessions.get(token)
                        if session is None:
                            raise ValueError("unknown session")
                        nonce = session["nonce"]
                        if live:
                            public = _public_live(session["world"], session["depth"], nonce,
                                                  comparisons[session["index"]], branch_limit)
                        else:
                            public = _public_finite(session["node"], nonce)
                    self._send(200, {"node": public})
                    return
                token = data.get("session")
                action_id = data.get("action_id")
                submitted_nonce = data.get("decision_nonce")
                if not isinstance(token, str) or not isinstance(action_id, str) or not isinstance(submitted_nonce, str):
                    raise ValueError("invalid session or action")
                with lock:
                    session = sessions.get(token)
                    if session is None:
                        raise ValueError("unknown session")
                    if not secrets.compare_digest(submitted_nonce, session["nonce"]):
                        raise StaleDecision()
                    if live:
                        world = session["world"]
                        if world.time_s >= world.horizon_end_s:
                            raise ValueError("exercise complete")
                        choices = select_practice_actions(world.actions(), branch_limit)
                        if action_id not in {a["id"] for a in choices}:
                            raise ValueError("unavailable action")
                        world.step(action_id)
                        session["depth"] += 1
                        session["nonce"] = secrets.token_urlsafe(16)
                        public = _public_live(world, session["depth"], session["nonce"],
                                              comparisons[session["index"]], branch_limit)
                    else:
                        node = session["node"]
                        choices = {a["id"] for a in node["actions"]}
                        if action_id not in choices or action_id not in node.get("children", {}):
                            raise ValueError("unavailable action")
                        node = node["children"][action_id]
                        session["node"] = node
                        session["nonce"] = secrets.token_urlsafe(16)
                        public = _public_finite(node, session["nonce"])
                self._send(200, {"node": public})
            except StaleDecision:
                self._send(409, {"error": "stale_decision"})
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def _adjacent_live_episodes(pack_path):
    folder = pack_path.parent
    situation_path = folder / "situations.json"
    future_path = folder / "instructor_futures.json"
    if not situation_path.exists() or not future_path.exists():
        return None
    situations = json.loads(situation_path.read_text(encoding="utf-8"))
    futures = json.loads(future_path.read_text(encoding="utf-8"))
    if len(situations) != len(futures):
        raise ValueError("situation/future episode counts differ")
    episodes = []
    for left, right in zip(situations, futures):
        if left["episode"] != right["episode"]:
            raise ValueError("situation/future episode ordering differs")
        episodes.append({"situation": left["situation"], "future": right["future"]})
    return episodes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve received knowledge one decision at a time")
    parser.add_argument("--pack", type=Path, required=True,
                        help="instructor-only practice.json generated by run_training")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--finite", action="store_true",
                        help="use the precomputed finite demonstration instead of live full mission")
    args = parser.parse_args(argv)
    pack = json.loads(args.pack.read_text(encoding="utf-8"))
    live_episodes = None if args.finite else _adjacent_live_episodes(args.pack)
    server = make_server(pack, args.host, args.port, live_episodes=live_episodes)
    print(f"Practice server listening on http://{args.host}:{server.server_port}/ "
          f"mode={'live_full_mission' if live_episodes is not None else 'finite_demonstration'}",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
