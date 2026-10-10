import copy
import hashlib
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from training_multibus import build_training_fixture, validate_training_fixture


def document():
    nodes = []
    edges = []
    for index, prefix in enumerate("ABC"):
        y = 30.0 * index
        points = [(0.0, y), (10.0, y + 5.0), (20.0, y + 5.0)]
        for step, (x, yy) in enumerate(points):
            nodes.append({"id": f"{prefix}{step}", "geometry_m": [x, yy],
                          "lonlat": [x / 1000.0, yy / 2000.0]})
        edges.extend([
            {"id": f"{prefix}-0", "from_node": f"{prefix}0",
             "to_node": f"{prefix}1",
             "geometry_m": [[0.0, y], [0.0, y + 5.0], [10.0, y + 5.0]],
             "length_m": 15.0},
            {"id": f"{prefix}-1", "from_node": f"{prefix}1",
             "to_node": f"{prefix}2",
             "geometry_m": [[10.0, y + 5.0], [20.0, y + 5.0]],
             "length_m": 10.0},
        ])
    graph = {
        "area_id": "paradise-ca",
        "metric_crs": "local equirectangular metres; origin_lonlat is WGS84 longitude,latitude",
        "origin_lonlat": [0.0, 0.0],
        "coverage_bbox_lonlat": [-1.0, -1.0, 1.0, 1.0],
        "source_sha256": "a" * 64,
        "nodes": nodes, "edges": edges,
    }
    manifest = {"coverage_bbox_lonlat": [-1.0, -1.0, 1.0, 1.0],
                "raw_sha256": "a" * 64, "decompressed_sha256": "a" * 64}
    gb = json.dumps(graph, allow_nan=False).encode()
    mb = json.dumps(manifest, allow_nan=False).encode()
    return graph, manifest, gb, mb


def build(gb=None, mb=None):
    _, _, default_gb, default_mb = document()
    gb = default_gb if gb is None else gb
    mb = default_mb if mb is None else mb
    return build_training_fixture(
        gb, mb, expected_graph_sha256=hashlib.sha256(gb).hexdigest(),
        expected_manifest_sha256=hashlib.sha256(mb).hexdigest())


class TrainingFixtureTests(unittest.TestCase):
    def setUp(self):
        self.graph, self.manifest, self.gb, self.mb = document()
        self.kw = {"expected_graph_sha256": hashlib.sha256(self.gb).hexdigest(),
                   "expected_manifest_sha256": hashlib.sha256(self.mb).hexdigest()}

    def valid(self, payload):
        validate_training_fixture(payload, self.gb, self.mb, **self.kw)

    def test_literal_polyline_midpoint_and_timeline(self):
        payload = build(self.gb, self.mb)
        self.valid(payload)
        self.assertEqual([b["bus_id"] for b in payload["buses"]],
                         ["TRAINING-BUS-001", "TRAINING-BUS-002", "TRAINING-BUS-003"])
        self.assertEqual(len({b["route_id"] for b in payload["buses"]}), 3)
        self.assertEqual(len({b["trail_id"] for b in payload["buses"]}), 3)
        self.assertEqual([len(b["positions"]) for b in payload["buses"]], [13] * 3)
        first = payload["buses"][0]
        self.assertEqual(first["route"]["edge_ids"], ["A-0", "A-1"])
        self.assertEqual(first["route"]["geometry_m"],
                         [[0.0, 0.0], [0.0, 5.0], [10.0, 5.0], [20.0, 5.0]])
        halfway = first["positions"][6]
        self.assertEqual(halfway["elapsed_s"], 60)
        self.assertEqual(halfway["timestamp_utc"], "2026-01-01T00:01:00Z")
        self.assertEqual(halfway["edge_id"], "A-0")
        self.assertAlmostEqual(halfway["offset_m"], 12.5)
        self.assertAlmostEqual(halfway["route_distance_m"], 12.5)
        self.assertEqual(halfway["position_m"], [7.5, 5.0])
        self.assertEqual(halfway["position_lonlat"], [0.0075, 0.0025])
        self.assertEqual(first["positions"][-1]["status"], "TRAINING_COMPLETE")
        self.assertTrue(payload["training_only"])
        self.assertFalse(payload["gps_feed"])
        self.assertFalse(payload["real_dispatch"])
        self.assertFalse(payload["real_eta"])
        self.assertIsNone(payload["local_hazard_binding"])

    def test_wrong_byte_hash_and_manifest_identity_rejected(self):
        with self.assertRaises(ValueError):
            build_training_fixture(self.gb, self.mb,
                                   expected_graph_sha256="0" * 64,
                                   expected_manifest_sha256=self.kw["expected_manifest_sha256"])
        altered = dict(self.manifest, raw_sha256="b" * 64)
        mb = json.dumps(altered).encode()
        with self.assertRaises(ValueError):
            build(self.gb, mb)

    def test_bad_anchor_and_nonfinite_rejected(self):
        for altered in (
            lambda g: g["nodes"][0].update(geometry_m=[True, 0.0]),
            lambda g: g["nodes"][0].update(lonlat=[float("nan"), 0.0]),
            lambda g: g["nodes"][0].update(lonlat=[0.25, 0.25]),
            lambda g: g["edges"][0].update(geometry_m=[[0.0, 0.0], [1.0]]),
        ):
            graph = copy.deepcopy(self.graph)
            altered(graph)
            gb = json.dumps(graph, allow_nan=True).encode()
            with self.subTest(graph=graph["nodes"][0], edge=graph["edges"][0]):
                with self.assertRaises(ValueError):
                    build(gb, self.mb)

    def test_tampered_identity_time_edge_position_and_operations_rejected(self):
        original = build(self.gb, self.mb)
        changes = [
            lambda p: p["buses"][1].update(bus_id=p["buses"][0]["bus_id"]),
            lambda p: p["buses"][1].update(route_id=p["buses"][0]["route_id"]),
            lambda p: p["buses"][1].update(trail_id=p["buses"][0]["trail_id"]),
            lambda p: p["buses"][0]["positions"][1].update(timestamp_utc=p["buses"][0]["positions"][0]["timestamp_utc"]),
            lambda p: p["buses"][0]["positions"][1].update(elapsed_s=0),
            lambda p: p["buses"][0]["positions"][6].update(edge_id="B-0"),
            lambda p: p["buses"][0]["positions"][6].update(offset_m=9.0),
            lambda p: p["buses"][0]["positions"][6].update(route_distance_m=13.0),
            lambda p: p["buses"][0]["positions"][6].update(position_m=[7.6, 5.0]),
            lambda p: p["buses"][0]["positions"][6].update(position_lonlat=[0.0076, 0.0025]),
            lambda p: p["buses"][0]["positions"][6].update(offset_m=True),
            lambda p: p["buses"][0]["positions"][6].update(route_distance_m=float("nan")),
            lambda p: p.update(dispatch_id="actual-incident"),
            lambda p: p["buses"][0]["positions"][0].update(gps=True),
        ]
        for i, change in enumerate(changes):
            payload = copy.deepcopy(original)
            change(payload)
            with self.subTest(i=i):
                with self.assertRaises(ValueError):
                    self.valid(payload)


    def test_oversized_integer_is_public_validation_error(self):
        huge = 10 ** 400
        graph_cases = (
            ("node_geometry_m", lambda g: g["nodes"][0]["geometry_m"].__setitem__(0, huge)),
            ("node_lonlat", lambda g: g["nodes"][0]["lonlat"].__setitem__(0, huge)),
            ("edge_geometry_m", lambda g: g["edges"][0]["geometry_m"][1].__setitem__(0, huge)),
        )
        for field, change in graph_cases:
            graph = copy.deepcopy(self.graph)
            change(graph)
            gb = json.dumps(graph).encode()
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    build(gb, self.mb)
        original = build(self.gb, self.mb)
        for field, value in (
            ("offset_m", huge),
            ("route_distance_m", huge),
            ("position_m", [huge, 5.0]),
            ("position_lonlat", [huge, 0.0025]),
        ):
            payload = copy.deepcopy(original)
            payload["buses"][0]["positions"][6][field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.valid(payload)


if __name__ == "__main__":
    unittest.main()
