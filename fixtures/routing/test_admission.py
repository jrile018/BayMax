"""Admission guards preserve real ledger reservations and restorable checkpoints."""
import unittest
from dataclasses import replace

from services.routing import Edge, Graph, SafetySnapshot, candidate_routes
from services.routing.trip import TripExecutor
from services.planner.ledger import Ledger, Vehicle, Request, Destination


def build(*, same_node=False, start_s=0, horizon_s=1000):
    destination = 'A' if same_node else 'D'
    graph = Graph({'A': (0, 0)} if same_node else
                  {'A': (0, 0), 'B': (100, 0), 'D': (200, 0)},
                  [] if same_node else [Edge('ab', 'A', 'B', 100, 10),
                                        Edge('bd', 'B', 'D', 100, 10)],
                  version='admission-fixture')
    safety = SafetySnapshot('k0', 0, 0, horizon_s,
                            provenance='explicit fictional admission fixture')
    ledger = Ledger([Vehicle('bus1', 'bus', 'A', 1, 0)],
                    [Request('evac1', 'evacuation', 'A', destination, ('p1',))],
                    [Destination('shelter1', destination, 'shelter', 1)], {})
    return graph, safety, ledger, TripExecutor(graph, ledger, start_s=start_s)


class AdmissionTests(unittest.TestCase):
    def assert_unchanged_and_restorable(self, graph, ledger, engine, before, before_ledger):
        self.assertEqual(engine.checkpoint(), before)
        self.assertEqual(ledger.export_state(), before_ledger)
        restored = TripExecutor.from_checkpoint(graph, engine.checkpoint())
        self.assertEqual(restored.checkpoint(), before)
        self.assertEqual(restored.ledger.export_state(), before_ledger)

    def test_malformed_routes_reject_before_real_resource_reservation(self):
        graph, safety, ledger, engine = build()
        route = candidate_routes(graph, 'A', 'D', 'bus', 0, safety).routes[0]
        mutations = (
            ('negative distance', replace(route, distance_m=-1)),
            ('wrong total distance', replace(route, distance_m=1)),
            ('empty route ID', replace(route, route_id='')),
            ('zero route version', replace(route, route_version=0)),
            ('boolean route version', replace(route, route_version=True)),
            ('string route version', replace(route, route_version='1')),
            ('wrong leg length', replace(route, legs=(replace(route.legs[0], length_m=1),
                                                       *route.legs[1:]))),
            ('negative leg length', replace(route, legs=(replace(route.legs[0], length_m=-1),
                                                          *route.legs[1:]))),
            ('wrong geometry', replace(route, geometry=())),
            ('negative forecast issue', replace(route, forecast_issued_s=-1)),
            ('boolean forecast horizon', replace(route, forecast_horizon_s=True)),
        )
        for label, altered in mutations:
            with self.subTest(mutation=label):
                graph, safety, ledger, engine = build()
                before, before_ledger = engine.checkpoint(), ledger.export_state()
                with self.assertRaises(ValueError):
                    engine.dispatch('dispatch1', 'bus1', 'evac1', altered, safety)
                self.assert_unchanged_and_restorable(graph, ledger, engine, before, before_ledger)

    def test_invalid_reroute_metadata_rejects_without_state_mutation(self):
        invalid = (1, True, [], ['nonempty'], {}, {'nonempty': 'value'}, None, '')
        for field in ('trigger', 'reason'):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    graph, safety, ledger, engine = build()
                    route = candidate_routes(graph, 'A', 'D', 'bus', 0, safety).routes[0]
                    engine.dispatch('dispatch1', 'bus1', 'evac1', route, safety)
                    engine.advance(5, safety)
                    before, before_ledger = engine.checkpoint(), ledger.export_state()
                    trigger = value if field == 'trigger' else 'report1'
                    reason = value if field == 'reason' else 'new observation'
                    with self.assertRaises(ValueError):
                        engine.replan('dispatch1', safety, trigger, reason)
                    self.assert_unchanged_and_restorable(graph, ledger, engine, before, before_ledger)

    def test_valid_dispatch_remains_idempotent_and_restorable(self):
        graph, safety, ledger, engine = build()
        route = candidate_routes(graph, 'A', 'D', 'bus', 0, safety).routes[0]
        committed = engine.dispatch('dispatch1', 'bus1', 'evac1', route, safety)
        before, before_ledger = engine.checkpoint(), ledger.export_state()
        self.assertEqual(ledger.requests['evac1']['reserved_people'], ['p1'])
        self.assertEqual(engine.dispatch('dispatch1', 'bus1', 'evac1', route, safety), committed)
        self.assert_unchanged_and_restorable(graph, ledger, engine, before, before_ledger)

    def test_valid_reroute_receipt_remains_idempotent_and_restorable(self):
        graph, safety, ledger, engine = build()
        route = candidate_routes(graph, 'A', 'D', 'bus', 0, safety).routes[0]
        engine.dispatch('dispatch1', 'bus1', 'evac1', route, safety)
        engine.advance(5, safety)
        result = engine.replan('dispatch1', safety, 'report1', 'new observation')
        self.assertEqual(result.status, 'feasible')
        self.assertEqual(result.routes[0].route_version, 2)
        before, before_ledger = engine.checkpoint(), ledger.export_state()
        repeated = engine.replan('dispatch1', safety, 'report1', 'new observation')
        self.assertEqual(repeated.to_dict(), result.to_dict())
        self.assert_unchanged_and_restorable(graph, ledger, engine, before, before_ledger)
        restored = TripExecutor.from_checkpoint(graph, engine.checkpoint())
        restored.replan('dispatch1', safety, 'report1', 'new observation')
        self.assertEqual(restored.checkpoint(), before)


    def test_invalid_safety_versions_reject_without_state_mutation(self):
        for version in (1, True, ''):
            with self.subTest(version=version):
                graph, safety, ledger, engine = build()
                route = candidate_routes(graph, 'A', 'D', 'bus', 0, safety).routes[0]
                engine.dispatch('dispatch1', 'bus1', 'evac1', route, safety)
                engine.advance(5, safety)
                before = engine.checkpoint()
                before_ledger = ledger.export_state()
                before_ledger_checkpoint = ledger.checkpoint()
                invalid = replace(safety, version=version)
                with self.assertRaises(ValueError):
                    engine.replan('dispatch1', invalid, 'report1', 'new observation')
                self.assert_unchanged_and_restorable(
                    graph, ledger, engine, before, before_ledger)
                self.assertEqual(ledger.checkpoint(), before_ledger_checkpoint)
                restored = TripExecutor.from_checkpoint(graph, engine.checkpoint())
                self.assertEqual(restored.ledger.checkpoint(), before_ledger_checkpoint)

    def test_valid_safety_version_reroute_remains_idempotent_and_restorable(self):
        graph, safety, ledger, engine = build()
        route = candidate_routes(graph, 'A', 'D', 'bus', 0, safety).routes[0]
        engine.dispatch('dispatch1', 'bus1', 'evac1', route, safety)
        engine.advance(5, safety)
        before_ledger = ledger.export_state()
        before_ledger_checkpoint = ledger.checkpoint()
        initial = engine.checkpoint()
        current = replace(safety, version='k-valid')
        result = engine.replan('dispatch1', current, 'report1', 'new observation')
        self.assertEqual(result.status, 'feasible')
        self.assertEqual(result.routes[0].known_version, 'k-valid')
        self.assertEqual(result.routes[0].route_version, 2)
        before = engine.checkpoint()
        self.assertNotEqual(before, initial)
        repeated = engine.replan('dispatch1', current, 'report1', 'new observation')
        self.assertEqual(repeated.to_dict(), result.to_dict())
        self.assert_unchanged_and_restorable(
            graph, ledger, engine, before, before_ledger)
        self.assertEqual(ledger.checkpoint(), before_ledger_checkpoint)
        restored = TripExecutor.from_checkpoint(graph, engine.checkpoint())
        self.assertEqual(restored.ledger.checkpoint(), before_ledger_checkpoint)
        restored.replan('dispatch1', current, 'report1', 'new observation')
        self.assertEqual(restored.checkpoint(), before)

    def test_zero_edge_dispatch_rejects_departure_after_actual_forecast_horizon(self):
        graph, safety, ledger, engine = build(same_node=True, start_s=11, horizon_s=10)
        route = candidate_routes(graph, 'A', 'A', 'bus', 10, safety).routes[0]
        route = replace(route, departure_s=11, arrival_s=11, forecast_horizon_s=1000)
        before, before_ledger = engine.checkpoint(), ledger.export_state()
        with self.assertRaises(ValueError):
            engine.dispatch('dispatch1', 'bus1', 'evac1', route, safety)
        self.assert_unchanged_and_restorable(graph, ledger, engine, before, before_ledger)

    def test_zero_edge_dispatch_allows_exact_horizon_without_authorizing_destination(self):
        graph, safety, ledger, engine = build(same_node=True, start_s=10, horizon_s=10)
        route = candidate_routes(graph, 'A', 'A', 'bus', 10, safety).routes[0]
        self.assertFalse(safety.destination_safe('A', 10))
        engine.dispatch('dispatch1', 'bus1', 'evac1', route, safety)
        self.assertEqual(ledger.requests['evac1']['reserved_people'], ['p1'])
        restored = TripExecutor.from_checkpoint(graph, engine.checkpoint())
        self.assertEqual(restored.checkpoint(), engine.checkpoint())


if __name__ == '__main__':
    unittest.main()
