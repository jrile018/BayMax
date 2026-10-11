"""Read-only cgroup v2 resource samples for matched cloud workloads."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import time

CGROUP = Path("/sys/fs/cgroup")
WORKSPACE = Path(__file__).resolve().parents[2]


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value is not None and value != "max" else None
    except (ValueError, TypeError):
        return None


def _kv(raw: str | None) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in (raw or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            number = _integer(parts[1])
            if number is not None:
                values[parts[0]] = number
    return values


def _io(raw: str | None) -> dict[str, dict[str, int]]:
    devices: dict[str, dict[str, int]] = {}
    for line in (raw or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        counters: dict[str, int] = {}
        for entry in parts[1:]:
            key, separator, value = entry.partition("=")
            number = _integer(value) if separator else None
            if number is not None:
                counters[key] = number
        devices[parts[0]] = counters
    return devices


def _read(root: Path, name: str, errors: dict[str, str]) -> str | None:
    try:
        return (root / name).read_text(encoding="utf-8").strip()
    except OSError as exc:
        errors[name] = f"{type(exc).__name__}: {exc}"
        return None


def _quota(raw: str | None) -> float | None:
    parts = (raw or "").split()
    if len(parts) != 2:
        return None
    numerator, denominator = _integer(parts[0]), _integer(parts[1])
    return numerator / denominator if numerator is not None and denominator and denominator > 0 else None


def sample(root: Path = CGROUP, workspace: Path = WORKSPACE) -> dict:
    errors: dict[str, str] = {}
    cpu = _kv(_read(root, "cpu.stat", errors))
    current = _integer(_read(root, "memory.current", errors))
    maximum = _integer(_read(root, "memory.max", errors))
    io = _io(_read(root, "io.stat", errors))
    quota = _quota(_read(root, "cpu.max", errors))
    pressure = {name: _read(root, f"{name}.pressure", errors) for name in ("cpu", "memory", "io")}
    memory_events = _kv(_read(root, "memory.events", errors))
    try:
        fs = os.statvfs(workspace)
        disk = {"bytes_total": fs.f_frsize * fs.f_blocks,
                "bytes_available": fs.f_frsize * fs.f_bavail}
    except OSError as exc:
        errors["workspace_statvfs"] = f"{type(exc).__name__}: {exc}"
        disk = {"bytes_total": None, "bytes_available": None}
    return {
        "utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_seconds": time.monotonic(),
        "cpu": cpu,
        "cpu_quota_cores": quota,
        "memory": {"current_bytes": current, "max_bytes": maximum,
                   "events": memory_events},
        "io": io,
        "pressure_raw": pressure,
        "workspace": disk,
        "errors": errors,
    }


def _delta(first: dict, last: dict, key: str) -> int | None:
    before, after = first.get(key), last.get(key)
    if isinstance(before, int) and isinstance(after, int) and after >= before:
        return after - before
    return None


def derive(first: dict, last: dict, quota_cores: float | None) -> dict:
    interval = last["monotonic_seconds"] - first["monotonic_seconds"]
    if interval <= 0:
        raise ValueError("sample interval must be positive")
    usage = _delta(first.get("cpu", {}), last.get("cpu", {}), "usage_usec")
    cores = usage / 1_000_000 / interval if usage is not None else None
    memory = last.get("memory", {})
    current, maximum = memory.get("current_bytes"), memory.get("max_bytes")
    memory_percent = (100 * current / maximum
                      if isinstance(current, int) and isinstance(maximum, int) and maximum > 0 else None)
    io_delta: dict[str, dict[str, int]] = {}
    for device, counters in last.get("io", {}).items():
        previous = first.get("io", {}).get(device)
        if previous is None:
            continue
        io_delta[device] = {}
        for key in ("rbytes", "wbytes", "rios", "wios"):
            value = _delta(previous, counters, key)
            if value is not None:
                io_delta[device][key + "_delta"] = value
    return {
        "interval_seconds": interval,
        "average_cpu_cores": cores,
        "cpu_percent_of_quota": 100 * cores / quota_cores if cores is not None and quota_cores and quota_cores > 0 else None,
        "throttled_usec_delta": _delta(first.get("cpu", {}), last.get("cpu", {}), "throttled_usec"),
        "nr_throttled_delta": _delta(first.get("cpu", {}), last.get("cpu", {}), "nr_throttled"),
        "memory_percent_of_limit_at_end": memory_percent,
        "memory_oom_delta": _delta(first.get("memory", {}).get("events", {}),
                                    memory.get("events", {}), "oom"),
        "io": io_delta,
    }



def stable_quota(samples: list[dict]) -> tuple[float | None, str | None]:
    quotas = [item.get("cpu_quota_cores") for item in samples]
    if any(value is None for value in quotas):
        return None, "quota unavailable during capture"
    if len(set(quotas)) != 1:
        return None, "quota changed during capture"
    return quotas[0], None


def capture(duration: int, interval: int, workload_id: str) -> dict:
    if not 1 <= duration <= 300 or not 1 <= interval <= duration:
        raise ValueError("duration must be 1-300 seconds and interval 1-duration")
    start = time.monotonic()
    samples = []
    for offset in range(0, duration + 1, interval):
        time.sleep(max(0.0, start + offset - time.monotonic()))
        samples.append(sample())
    if (duration % interval) != 0:
        time.sleep(max(0.0, start + duration - time.monotonic()))
        samples.append(sample())
    quota_cores, quota_note = stable_quota(samples)
    return {
        "schema": "amd-resource-monitor/v1",
        "cpu_quota_note": quota_note,
        "scope": "cloud cgroup v2 namespace root and AMD workspace; no host-wide or GPU claim",
        "workload_id": workload_id,
        "hostname": socket.gethostname(),
        "cgroup_root": str(CGROUP),
        "workspace_path": str(WORKSPACE),
        "requested_duration_seconds": duration,
        "requested_interval_seconds": interval,
        "samples": samples,
        "derived": derive(samples[0], samples[-1], quota_cores),
        "gpu": {"utilization": None, "vram_bytes": None, "temperature_c": None,
                "reason": "requires a separate exclusive GPU lease and measurement"},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--interval", type=int, default=1)
    parser.add_argument("--workload-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = capture(args.duration, args.interval, args.workload_id)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
