"""Wildfire edge-access to interval-safe routing integration."""
import copy
import importlib.util
import math
import unittest

from services.hazards.wildfire.adapter import edge_access

ROUTING_AVAILABLE = importlib.util.find_spec("services.routing") is not None


EPOCH = "2026-10-10T00:00:00Z"
SOURCE = {"source_id": "synthetic-ignition", "kind": "synthetic",
          "retrieved_at_utc": EPOCH, "observed_at_utc": None, "license": "CC0-1.0"}


def availability():
    return {"status": "available", "epoch_utc": EPOCH, "checked_at_s": 0,
            "available_from_s": 0, "source_ids": ["synthetic-ignition"],
            "source_ledger": [copy.deepcopy(SOURCE)]}


def row(edge_id="direct", status="forecast", start=0, end=100, closed=()):
    return {"edge_id": edge_id, "status": status, "issued_time_s": 0,
            "coverage_start_s": start, "coverage_end_s": end,
            "closed_intervals": [{"start_s": a, "end_s": b} for a, b in closed],
            "source_ids": ["synthetic-ignition"], "source_availability": availability(),
            "spatial_rule": "Any intersecting cell", "reason": "Training wildfire forecast"}


@unittest.skipUnless(ROUTING_AVAILABLE, "routing package absent; run with wildfire and routing worktrees on PYTHONPATH")
class RoutingBridgeTests(unittest.TestCase):
    def snapshot(self, rows, known=0, expected=None):
        from services.hazards.wildfire.routing_bridge import safety_snapshot_from_access
        return safety_snapshot_from_access(rows, known_at_s=known, version="fire-v1",
                                           safe_nodes=("D",), expected_edge_ids=expected)

    def test_real_route_avoids_wildfire_closure(self):
        from services.routing.models import Edge, Graph
        from services.routing.search import candidate_routes
        graph = Graph({"S": (0, 0), "A": (20, 0), "B": (0, 20), "D": (20, 20)}, [
            Edge("direct", "S", "A", 20, 5), Edge("finish", "A", "D", 20, 5),
            Edge("detour", "S", "B", 20, 8), Edge("detour_finish", "B", "D", 20, 8)])
        hazard = {"grid": {"width": 2, "height": 2, "cell_size_m": 10, "origin_m": [0, 0]},
                  "epoch_utc": EPOCH, "horizon_s": 100,
                  "arrivals_s": [[None, 0], [None, None]],
                  "provenance": {"source_ledger": [copy.deepcopy(SOURCE)]}}
        edges = [{"edge_id": e.edge_id, "geometry_m": [list(p) for p in e.geometry]}
                 for e in graph.edges.values()]
        rows = edge_access(hazard, edges, issued_time_s=0)
        safety = self.snapshot(rows, expected=tuple(graph.edges))
        result = candidate_routes(graph, "S", "D", "ambulance", 0, safety)
        self.assertEqual("feasible", result.status)
        self.assertEqual(("detour", "detour_finish"), result.routes[0].edge_ids)
        self.assertTrue(any(x.edge_id == "direct" and x.reason == "closed_during_traversal"
                            for x in result.exclusions))
        self.assertIn("synthetic-ignition", result.exclusions[0].evidence)
        self.assertEqual(0, safety.safety_buffer_s)

    def test_unknown_and_missing_edges_abstain_even_with_partial_closure(self):
        safety = self.snapshot([row("known"), row("partial", status="unknown", closed=((2, 8),))],
                               expected=("known", "partial", "missing"))
        self.assertEqual(frozenset({"known"}), safety.covered_edges)
        for edge in ("partial", "missing"):
            self.assertEqual("unknown_coverage", safety.traversal(edge, 3, 4)[1])

    def test_common_horizon_is_shortest_coverage(self):
        safety = self.snapshot([row("a", end=80), row("b", end=40)])
        self.assertEqual(40, safety.horizon_s)
        self.assertEqual("unknown_coverage", safety.traversal("a", 39, 41)[1])

    def test_future_issue_or_coverage_start_rejected(self):
        future_issue = row()
        future_issue["issued_time_s"] = 11
        future_start = row(start=11)
        for bad in (future_issue, future_start):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.snapshot([bad], known=10)

    def test_closure_uses_half_open_exact_endpoints(self):
        safety = self.snapshot([row(closed=((10, 20),))])
        self.assertTrue(safety.traversal("direct", 5, 10)[0])
        self.assertEqual("closed_during_traversal", safety.traversal("direct", 10, 11)[1])
        self.assertTrue(safety.traversal("direct", 20, 21)[0])

    def test_malformed_duplicate_and_out_of_coverage_rows_rejected(self):
        cases = [[row(), row()], [row(end=math.inf)], [row(closed=((10, 101),))],
                 [row(closed=((20, 20),))], [row(start=20, closed=((10, 30),))],
                 [dict(row(), source_ids=[])], [dict(row(), status="safe")],
                 [dict(row(), edge_id="outside")]]
        for rows in cases:
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    self.snapshot(rows, expected=("direct",))

    def test_received_time_equals_known_at_and_provenance_survives(self):
        safety = self.snapshot([row(closed=((15, 50),))], known=10)
        closure = safety.closures[0]
        self.assertEqual(10, closure.received_s)
        self.assertEqual(0, closure.issued_s)
        self.assertIn("synthetic-ignition", closure.evidence)
        self.assertIn("Any intersecting cell", closure.evidence)
        self.assertIn("synthetic-ignition", safety.provenance)
        self.assertIn("Training wildfire forecast", safety.provenance)


    def test_selector_collections_reject_strings_and_malformed_values(self):
        from services.hazards.wildfire.routing_bridge import safety_snapshot_from_access
        for nodes in ("Dest", b"Dest", {"Dest": 1}, 42, [[]]):
            with self.subTest(safe_nodes=nodes):
                with self.assertRaises(ValueError):
                    safety_snapshot_from_access([row()], 0, "fire-v1", safe_nodes=nodes)
        for edges in ("direct", b"direct", {"direct": 1}, 42, [[]]):
            with self.subTest(expected_edge_ids=edges):
                with self.assertRaises(ValueError):
                    safety_snapshot_from_access([row()], 0, "fire-v1", expected_edge_ids=edges)



    def test_missing_forged_or_mismatched_availability_rejected(self):
        missing = row()
        del missing["source_availability"]
        mismatched_ids = row()
        mismatched_ids["source_ids"] = ["other"]
        forged = row()
        forged["source_availability"]["available_from_s"] = 99
        forged_issue = row()
        forged_issue["source_availability"]["checked_at_s"] = 1
        boolean_issue = row()
        boolean_issue["source_availability"]["checked_at_s"] = False
        boolean_available = row()
        boolean_available["source_availability"]["available_from_s"] = False
        future = row()
        future["source_availability"]["source_ledger"][0]["retrieved_at_utc"] = "2026-10-10T00:00:20Z"
        for bad in (missing, mismatched_ids, forged, forged_issue, boolean_issue, boolean_available, future):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.snapshot([bad])

    def test_mixed_epoch_rows_rejected(self):
        other = row("other")
        other["source_availability"]["epoch_utc"] = "2026-10-11T00:00:00Z"
        with self.assertRaises(ValueError):
            self.snapshot([row(), other])


    def test_handbuilt_nonsynthetic_row_requires_license_and_http_uri(self):
        valid = row()
        valid["source_availability"]["source_ledger"][0].update(
            kind="mapped", uri="https://example.test/mapping", license="CC-BY-4.0")
        self.assertEqual(frozenset({"direct"}), self.snapshot([valid]).covered_edges)
        for change in ({"license": ""}, {"uri": None}, {"uri": "ftp://example.test/mapping"}):
            bad = copy.deepcopy(valid)
            bad["source_availability"]["source_ledger"][0].update(change)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.snapshot([bad])


if __name__ == "__main__":
    unittest.main()
