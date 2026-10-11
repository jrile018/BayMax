"""Cloud-native resource sampler calculations."""
from pathlib import Path
import runpy


def derive(first, last, quota_cores):
    monitor = runpy.run_path(str(Path(__file__).parents[1] / "resource_monitor.py"))
    return monitor["derive"](first, last, quota_cores=quota_cores)


def test_derive_uses_sample_interval_and_preserves_unknown_io():
    first = {
        "monotonic_seconds": 10.0,
        "cpu": {"usage_usec": 1000000, "nr_throttled": 2, "throttled_usec": 100},
        "memory": {"current_bytes": 500, "max_bytes": 1000},
        "io": {"8:0": {"rbytes": 100, "wbytes": 200}, "259:1": {}},
    }
    last = {
        "monotonic_seconds": 12.0,
        "cpu": {"usage_usec": 3000000, "nr_throttled": 3, "throttled_usec": 150},
        "memory": {"current_bytes": 600, "max_bytes": 1000},
        "io": {"8:0": {"rbytes": 140, "wbytes": 260}, "259:1": {}},
    }
    actual = derive(first, last, quota_cores=4.0)
    assert actual["interval_seconds"] == 2.0
    assert actual["average_cpu_cores"] == 1.0
    assert actual["cpu_percent_of_quota"] == 25.0
    assert actual["throttled_usec_delta"] == 50
    assert actual["io"]["8:0"] == {"rbytes_delta": 40, "wbytes_delta": 60}
    assert actual["io"]["259:1"] == {}
    assert actual["memory_percent_of_limit_at_end"] == 60.0


def test_derive_does_not_invent_unavailable_quota_or_counters():
    first = {"monotonic_seconds": 0.0, "cpu": {}, "memory": {"current_bytes": 10, "max_bytes": None}, "io": {}}
    last = {"monotonic_seconds": 1.0, "cpu": {}, "memory": {"current_bytes": 20, "max_bytes": None}, "io": {}}
    actual = derive(first, last, quota_cores=None)
    assert actual["average_cpu_cores"] is None
    assert actual["cpu_percent_of_quota"] is None
    assert actual["memory_percent_of_limit_at_end"] is None
    assert actual["io"] == {}


def test_changed_or_missing_quota_is_not_used_for_cpu_percentage():
    monitor = runpy.run_path(str(Path(__file__).parents[1] / "resource_monitor.py"))
    stable_quota = monitor["stable_quota"]
    assert stable_quota([{"cpu_quota_cores": 4.0}, {"cpu_quota_cores": 4.0}]) == (4.0, None)
    assert stable_quota([{"cpu_quota_cores": 4.0}, {"cpu_quota_cores": 8.0}]) == (None, "quota changed during capture")
    assert stable_quota([{"cpu_quota_cores": 4.0}, {"cpu_quota_cores": None}]) == (None, "quota unavailable during capture")
