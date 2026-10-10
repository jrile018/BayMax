"""HTTP boundary for one-decision-at-a-time practice delivery."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from evals.planner.training_server import make_server


@pytest.fixture
def live_server():
    leaf = {
        "depth": 2, "time_s": 30,
        "knowledge": {"time_s": 30, "observations": [{"id": "secret-closure"}]},
        "actions": [],
        "debrief": {"metrics": {"safe_arrivals": 1}, "critique_prompts": ["Discuss"]},
    }
    middle = {
        "depth": 1, "time_s": 15,
        "knowledge": {"time_s": 15, "observations": []},
        "actions": [{"id": "wait", "kind": "wait", "explanation": "Wait for radio"}],
        "children": {"wait": leaf},
    }
    pack = {
        "schema": "synthetic-first-responder-practice-v1",
        "limits": {"branch_limit": 3, "depth_limit": 2},
        "severity_scale": [{"level": i, "description": f"Level {i}"} for i in range(1, 11)],
        "episodes": [{
            "name": "Episode 1",
            "root": {
                "depth": 0, "time_s": 0,
                "knowledge": {"time_s": 0, "observations": [{"note": "</script><img src=x>"}]},
                "actions": [{"id": "wait", "kind": "wait", "explanation": "Wait for radio"}],
                "children": {"wait": middle},
            },
        }],
    }
    server = make_server(pack, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def get(base, path):
    try:
        with urlopen(base + path, timeout=2) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8")


def post(base, path, value):
    data = json.dumps(value).encode("utf-8")
    request = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_initial_html_and_metadata_expose_no_future(live_server):
    status, html = get(live_server, "/")
    assert status == 200
    assert "secret-closure" not in html
    assert "<img src=x>" not in html
    assert '"truth_events"' not in html
    assert "node.children" not in html
    assert "if(pending)return" in html
    assert "app.querySelectorAll" in html
    status, metadata = get(live_server, "/meta")
    assert status == 200
    assert json.loads(metadata)["episodes"] == [{"name": "Episode 1"}]
    assert "secret-closure" not in metadata
    for path in ("/practice.json", "/instructor_futures.json", "/episodes/0", "/node/1"):
        assert get(live_server, path)[0] == 404


def test_step_requires_current_nonce_and_reveals_only_current_node(live_server):
    status, started = post(live_server, "/start", {"episode_index": 0})
    assert status == 200
    token = started["session"]
    assert "secret-closure" not in json.dumps(started)
    assert "children" not in started["node"]
    assert "debrief" not in started["node"]
    first = {"session": token, "decision_nonce": started["node"]["decision_nonce"],
             "action_id": "wait"}
    assert post(live_server, "/step", {**first, "action_id": "guess"})[0] == 400
    assert post(live_server, "/step", {**first, "session": "wrong"})[0] == 400
    status, advanced = post(live_server, "/step", first)
    assert status == 200
    assert "secret-closure" not in json.dumps(advanced)
    assert "debrief" not in advanced["node"]
    assert "children" not in advanced["node"]
    assert advanced["node"]["decision_nonce"] != first["decision_nonce"]
    assert post(live_server, "/step", first) == (409, {"error": "stale_decision"})
    status, current = post(live_server, "/current", {"session": token})
    assert status == 200
    assert current["node"] == advanced["node"]
    second = {"session": token, "decision_nonce": advanced["node"]["decision_nonce"],
              "action_id": "wait"}
    status, ended = post(live_server, "/step", second)
    assert status == 200
    assert "secret-closure" in json.dumps(ended)
    assert ended["node"]["debrief"]["metrics"]["safe_arrivals"] == 1
    assert "children" not in ended["node"]


def test_live_mission_receives_later_request_and_debriefs_at_horizon():
    class LiveWorld:
        def __init__(self, situation, future):
            self.time_s = 0
            self.horizon_end_s = 45
            self.served = 0
            self.future = future

        def knowledge(self, recipient_id=None):
            observations = []
            if self.time_s >= 15:
                observations.append({"kind": "request_created", "id": "new-request",
                                     "received_at_s": 15})
            return {"time_s": self.time_s, "observations": observations,
                    "goals": {"priority_order": ["urgent_service", "supply", "coverage", "protection", "time"]},
                    "requests": [{"id": "new-request", "remaining": 1}] if observations else []}

        def actions(self):
            actions = [{"id": "wait", "kind": "wait", "expected_urgent": 0,
                        "travel_s": 0, "explanation": "Wait"}]
            if self.time_s >= 15 and not self.served:
                actions.append({"id": "move", "kind": "dispatch", "vehicle_id": "ambulance",
                                "request_id": "new-request", "expected_urgent": 1,
                                "travel_s": 5, "explanation": "Serve newly received request"})
            return actions

        def step(self, action_id):
            if action_id == "move":
                self.served = 1
            self.time_s = min(self.time_s + 15, self.horizon_end_s)
            return {}

        def advance_to(self, time_s):
            self.time_s = time_s

        def outcome(self):
            return {"metrics": {
                "safe_arrivals": self.served, "medical_on_time": self.served,
                "medical_completed": self.served, "supplies_delivered": 0,
                "unmet_urgent_people": 1 - self.served, "unmet_goods": 0,
                "travel_s": 5 if self.served else 0, "stranded_vehicle_s": 0,
                "route_failures": 0, "constraint_violations": 0,
            }, "events": [], "final_state": {}, "arrival_times_s": []}

    def planner(knowledge, actions):
        return {"chosen_action": next((a for a in actions if a["id"] == "move"), actions[0]),
                "reasons": [], "score_components": {}}

    pack = {"schema": "synthetic-first-responder-practice-v1",
            "limits": {"branch_limit": 3, "depth_limit": 2},
            "severity_scale": [{"level": i, "description": str(i)} for i in range(1, 11)],
            "episodes": [{"name": "Episode 1", "root": {}}]}
    server = make_server(pack, "127.0.0.1", 0,
                         live_episodes=[{"situation": {"time_s": 0, "horizon_s": 45},
                                         "future": {"secret": "future-request"}}],
                         world_factory=LiveWorld, planner=planner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, metadata = get(base, "/meta")
        assert status == 200
        assert json.loads(metadata)["mode"] == "live_full_mission"
        assert json.loads(metadata)["limits"]["decision_limit"] == 3
        assert "future-request" not in metadata
        assert "future-request" not in get(base, "/")[1]
        status, started = post(base, "/start", {"episode_index": 0})
        assert status == 200
        token = started["session"]
        node = started["node"]
        assert node["knowledge"]["observations"] == []
        assert {a["id"] for a in node["actions"]} == {"wait"}
        first = {"session": token, "decision_nonce": node["decision_nonce"], "action_id": "wait"}
        status, response = post(base, "/step", first)
        assert status == 200
        node = response["node"]
        assert node["time_s"] == 15
        assert node["knowledge"]["observations"][0]["id"] == "new-request"
        assert {a["id"] for a in node["actions"]} == {"wait", "move"}
        assert "debrief" not in node
        assert post(base, "/step", first)[0] == 409
        status, response = post(base, "/step", {
            "session": token, "decision_nonce": node["decision_nonce"], "action_id": "move"})
        assert status == 200
        node = response["node"]
        assert node["time_s"] == 30
        assert "debrief" not in node
        status, response = post(base, "/step", {
            "session": token, "decision_nonce": node["decision_nonce"], "action_id": "wait"})
        assert status == 200
        node = response["node"]
        assert node["time_s"] == 45
        assert node["debrief"]["metrics"]["medical_completed"] == 1
        assert node["debrief"]["comparison"]["decision_budget"] == 3
        assert node["debrief"]["comparison"]["situational"]["medical_completed"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
