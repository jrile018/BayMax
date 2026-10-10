"""Hand-calculated, fictional graph acceptance checks; no external road data."""
import unittest
from services.routing.models import Edge, Graph
from services.routing.safety import Closure, SafetySnapshot
from services.routing.search import static_reference, candidate_routes

def graph():
    return Graph({"A":(0,0),"B":(100,0),"C":(100,100),"D":(200,0),"X":(300,0)},[
        Edge("ab","A","B",100,10,("bus","ambulance")),
        Edge("bd","B","D",100,10,("bus","ambulance")),
        Edge("ac","A","C",141.421356,15),
        Edge("cd","C","D",141.421356,15),
        Edge("bc","B","C",100,10),
    ], version="tiny-v1")

def known(closures=(), now=0, horizon=1000, covered_edges=None):
    return SafetySnapshot("k1", now, 0, horizon, tuple(closures),
                          covered_edges=covered_edges, provenance="fictional interval fixture")

class SearchTests(unittest.TestCase):
    def test_static_directed_nonnegative_reference(self):
        r = static_reference(graph(),"A","D","bus",0,known())
        self.assertEqual(r.edge_ids,("ab","bd"))
        self.assertEqual(r.arrival_s,20)
        self.assertFalse(r.safety_validated)
        self.assertEqual(static_reference(graph(),"D","A","bus",0,known()).status,"unreachable_static")
    def test_vehicle_access_is_not_silently_ignored(self):
        r = static_reference(graph(),"A","D","truck",0,known())
        self.assertEqual(r.edge_ids,("ac","cd"))
        self.assertEqual(r.arrival_s,30)
    def test_entire_traversal_closure_rejects_shortest_and_yields_alternative(self):
        s = known((Closure("bd",15,100,0,0,"forecast fire"),))
        result = candidate_routes(graph(),"A","D","bus",0,s)
        self.assertEqual(result.status,"feasible")
        self.assertEqual(result.routes[0].edge_ids,("ac","cd"))
        self.assertEqual(result.routes[0].arrival_s,30)
        self.assertTrue(result.routes[0].safety_validated)
        self.assertTrue(any(x.edge_id=="bd" and x.reason=="closed_during_traversal" for x in result.exclusions))
    def test_static_open_at_departure_does_not_certify_forecast(self):
        s = known((Closure("bd",15,100,0,0,"future closure"),))
        self.assertEqual(static_reference(graph(),"A","D","bus",0,s).edge_ids,("ab","bd"))
    def test_candidate_alternatives_keep_edge_identity(self):
        r = candidate_routes(graph(),"A","D","bus",0,known(),max_candidates=3)
        self.assertEqual([x.edge_ids for x in r.routes],[("ab","bd"),("ac","cd"),("ab","bc","cd")])
    def test_future_unreceived_information_cannot_change_initial_action(self):
        s = known((Closure("bd",0,100,8,8,"hidden until 8"),))
        r = candidate_routes(graph(),"A","D","bus",0,s)
        self.assertEqual(r.routes[0].edge_ids,("ab","bd"))
        seen = known(s.closures,now=8)
        self.assertEqual(candidate_routes(graph(),"A","D","bus",8,seen).routes[0].edge_ids,("ac","cd"))
    def test_unknown_forecast_coverage_is_not_certified_safe(self):
        r = candidate_routes(graph(),"A","D","bus",0,known(horizon=12))
        self.assertEqual(r.status,"no_feasible_candidate")
        self.assertTrue(any(x.reason=="unknown_coverage" for x in r.exclusions))
    def test_search_bound_is_not_unreachable(self):
        r = candidate_routes(graph(),"A","D","bus",0,known(),max_expansions=1)
        self.assertEqual(r.status,"search_limit")
        self.assertTrue(r.search_limited)
        self.assertEqual(candidate_routes(graph(),"A","X","bus",0,known()).status,"unreachable_static")
    def test_parallel_roads_and_zero_cost_edges(self):
        g = Graph({"A":(0,0),"B":(1,0),"D":(2,0)},[
            Edge("ab-fast","A","B",1,1),Edge("ab-slow","A","B",1,2),
            Edge("bd","B","D",1,1),Edge("loop","B","B",0,0)])
        r = candidate_routes(g,"A","D","bus",0,known(),max_candidates=3)
        self.assertEqual([x.edge_ids for x in r.routes],[("ab-fast","bd"),("ab-slow","bd")])
    def test_safety_buffer_and_boundary(self):
        s = known((Closure("bd",20,100,0,0,"at exit"),))
        self.assertEqual(candidate_routes(graph(),"A","D","bus",0,s).routes[0].edge_ids,("ab","bd"))
        buffered = SafetySnapshot("k2",0,0,1000,s.closures,safety_buffer_s=1,provenance="fictional")
        self.assertEqual(candidate_routes(graph(),"A","D","bus",0,buffered).routes[0].edge_ids,("ac","cd"))
    def test_invalid_weights_and_duplicate_ids_rejected_before_search(self):
        for length, seconds in [(1,-1),(1,float("nan")),(1,None),(-1,1),(1,0)]:
            with self.subTest(length=length,seconds=seconds),self.assertRaises(ValueError):
                Graph({"A":(0,0),"B":(1,0)},[Edge("e","A","B",length,seconds)])
        with self.assertRaises(ValueError):
            Graph({"A":(0,0),"B":(1,0)},[Edge("e","A","B",1,1),Edge("e","A","B",1,1)])
    def test_zero_length_cannot_bridge_distinct_positions(self):
        with self.assertRaises(ValueError):
            Graph({"A":(0,0),"B":(1000,0)},[Edge("teleport","A","B",0,0)])
    def test_accumulated_nonfinite_times_rejected(self):
        g=Graph({"A":(0,0),"B":(1,0),"D":(2,0)},[
            Edge("ab","A","B",1,1e308),Edge("bd","B","D",1,1e308)])
        with self.assertRaises(ValueError):
            static_reference(g,"A","D","bus",0)
        g2=Graph({"A":(0,0),"B":(1,0)},[Edge("ab","A","B",1,1e308)])
        with self.assertRaises(ValueError):
            static_reference(g2,"A","B","bus",1e308)
    def test_same_node_candidate_requires_forecast_temporal_coverage(self):
        g = Graph({"A": (0, 0)}, [])
        safety = SafetySnapshot("forecast", 0, 0, 10,
                                safe_nodes=frozenset({"A"}),
                                provenance="authored example")
        for departure, expected_status in (
            (9, "feasible"),
            (10, "feasible"),
            (11, "no_feasible_candidate"),
        ):
            with self.subTest(departure=departure):
                result = candidate_routes(g, "A", "A", "bus", departure, safety)
                self.assertEqual(result.status, expected_status)
                if expected_status == "feasible":
                    self.assertEqual(result.routes[0].arrival_s, departure)
                    self.assertEqual(result.routes[0].edge_ids, ())
                    self.assertTrue(result.routes[0].safety_validated)
                else:
                    self.assertEqual(result.routes, ())

    def test_departure_before_available_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            candidate_routes(graph(),"A","D","bus",0,known(now=5))

if __name__=="__main__":
    unittest.main()
