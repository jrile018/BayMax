"""Time-respecting, directed propagation of synthetic training facts."""
from __future__ import annotations

import copy
import hashlib
import heapq
import math
from collections.abc import Mapping, Sequence
from typing import Any


def _number(value: Any, name: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return result


def _delivered(seed: int, fact_id: str, link_key: str, contact: int, chance: float) -> bool:
    if chance == 1:
        return True
    if chance == 0:
        return False
    key = f"{seed}:{fact_id}:{link_key}:{contact}".encode()
    draw = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / 2**64
    return draw < chance


def _next_arrival(
    now: float, link: dict, link_key: str, fact_id: str, horizon: float, seed: int
) -> float | None:
    interval = link["contact_interval_s"]
    delay = link["delay_s"]
    chance = link["success_probability"]
    if chance == 0:
        return None
    if interval == 0:
        return now + delay if now + delay <= horizon and _delivered(seed, fact_id, link_key, 0, chance) else None
    contact = max(0, math.ceil(now / interval - 1e-12))
    # Limit work for pathological subsecond intervals. Generated links are slower.
    for step in range(10001):
        tick = contact + step
        arrival = tick * interval + delay
        if arrival > horizon:
            return None
        if _delivered(seed, fact_id, link_key, tick, chance):
            return arrival
    return None


def diffuse_information(
    facts: Sequence[Mapping[str, Any]],
    communications: Mapping[str, Any],
    horizon_s: float,
    seed: int,
) -> list[dict[str, Any]]:
    """Return one received copy per reachable agent and fact, within the horizon.

    Each link is directed. Periodic links transmit at multiples of
    contact_interval_s; a zero interval is an immediate radio attempt.
    Losses are keyed by fact/link/contact, so list order does not alter draws.
    """
    horizon = _number(horizon_s, "horizon_s")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if not isinstance(communications, Mapping):
        raise TypeError("communications must be a mapping")
    agents = list(communications["agents"])
    if len(agents) != len(set(agents)):
        raise ValueError("communications agents must be unique")
    agent_set = set(agents)
    links_by_source: dict[str, list[tuple[str, dict]]] = {a: [] for a in agents}
    seen_links = set()
    for raw in communications.get("links", []):
        if raw["source"] not in agent_set or raw["target"] not in agent_set:
            raise ValueError("communication link endpoints must be agents")
        link = {
            "target": raw["target"],
            "delay_s": _number(raw["delay_s"], "delay_s"),
            "contact_interval_s": _number(raw["contact_interval_s"], "contact_interval_s"),
            "success_probability": _number(raw["success_probability"], "success_probability"),
        }
        if link["success_probability"] > 1:
            raise ValueError("success_probability must be <= 1")
        identity = (
            str(raw["source"]), str(raw["target"]), link["delay_s"],
            link["contact_interval_s"], link["success_probability"],
        )
        if identity in seen_links:
            raise ValueError("duplicate identical communication link")
        seen_links.add(identity)
        link_key = "|".join(str(part) for part in identity)
        links_by_source[raw["source"]].append((link_key, link))
    received = []
    seen_ids = set()
    for raw in facts:
        fact = copy.deepcopy(dict(raw))
        fact_id = str(fact["id"])
        if fact_id in seen_ids:
            raise ValueError(f"duplicate fact id: {fact_id}")
        seen_ids.add(fact_id)
        source = fact["source_id"]
        if source not in agent_set:
            raise ValueError(f"fact source is not an agent: {source}")
        event_time = _number(fact["time_s"], "fact.time_s")
        issued = _number(fact.get("issued_at_s", event_time), "fact.issued_at_s")
        if issued < event_time:
            raise ValueError("a fact cannot be issued before its event")
        if issued > horizon:
            continue
        payload = copy.deepcopy(dict(fact.get("payload", {})))
        earliest = {source: issued}
        queue = [(issued, str(source), source)]
        while queue:
            now, _, agent = heapq.heappop(queue)
            if now != earliest[agent]:
                continue
            for link_key, link in links_by_source[agent]:
                arrival = _next_arrival(now, link, link_key, fact_id, horizon, seed)
                target = link["target"]
                if arrival is not None and arrival < earliest.get(target, math.inf):
                    earliest[target] = arrival
                    heapq.heappush(queue, (arrival, str(target), target))
        for agent, at in earliest.items():
            observation = {
                "id": fact_id,
                "event_id": fact_id,
                "kind": fact["kind"],
                "time_s": event_time,
                "issued_at_s": issued,
                "received_at_s": at,
                "recipient_id": agent,
                "source_id": source,
                "payload": copy.deepcopy(payload),
            }
            for key in ("edge_id", "request", "facility_id"):
                if key in payload:
                    observation[key] = copy.deepcopy(payload[key])
            received.append(observation)
    received.sort(key=lambda event: (event["received_at_s"], event["id"], str(event["recipient_id"])))
    return received
