"""Incident v1 is evidence context only, bound to a real trip checkpoint."""
import base64
import hashlib
import json
import sys
import types
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from services.routing import Graph, candidate_routes
from services.routing.checkpoint import graph_fingerprint
from services.routing.incident import (
    bind_checkpoint, bridge_incident_v1, verify_frozen_contract,
)
from services.routing.trip import TripExecutor
from test_trip import setup


FROZEN_FIXTURE = Path(__file__).resolve().parent / 'frozen_incident_v1' / 'input.json'
FROZEN_MANIFEST_SHA256 = 'f7d8fbd0613ba34f188e77e43a96219703914ccfe8e1e3e49b929585858d8ede'
CATEGORIES = ('hazard', 'needs', 'closures', 'vehicles', 'stock', 'capacity')
OPERATIONAL = CATEGORIES[1:]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def seal(snapshot):
    snapshot['snapshot_hash'] = hashlib.sha256(canonical(snapshot)).hexdigest()
    return snapshot


def frozen_bytes():
    fixture = json.loads(FROZEN_FIXTURE.read_text(encoding='utf-8'))
    assert fixture['manifest_sha256'] == FROZEN_MANIFEST_SHA256
    manifest_bytes = base64.b64decode(fixture['manifest_bytes_b64'], validate=True)
    assert hashlib.sha256(manifest_bytes).hexdigest() == FROZEN_MANIFEST_SHA256
    assert json.loads(manifest_bytes) == fixture['manifest']
    files = {name: base64.b64decode(raw, validate=True)
             for name, raw in fixture['contract_bytes_b64'].items()}
    receipt = base64.b64decode(fixture['receipt_bytes_b64'], validate=True)
    return manifest_bytes, files, receipt


def identity(graph):
    return dict(graph_fingerprint=graph_fingerprint(graph), graph_version=graph.version,
                metric_crs=getattr(graph, 'metric_crs', 'declared local metric x/y metres'),
                origin_lonlat=getattr(graph, 'origin_lonlat', None),
                source_metadata=getattr(graph, 'source_metadata', None))


def closure_record(*, accepted='2026-10-10T09:00:05Z', revision=1,
                   retracted=False, supersedes=None, source_id='county', item_id='notice'):
    return dict(source_id=source_id, item_id=item_id, revision=revision,
                source_url='https://example.gov/notice', raw_sha256='a' * 64,
                provider='county', license='public', source_type='agency_notice',
                category='closures', source_kind='reported', published_at=accepted,
                observed_at=None, valid_from=None, valid_through=None,
                message_expires_at=None, first_seen_at=accepted, fetched_at=accepted,
                accepted_at=accepted, correction_available_at=accepted if supersedes else None,
                superseded_at=None, supersedes=supersedes, retracted=retracted,
                source_reference={'quote': 'road closed'}, geometry=None,
                precision='unknown', area_label=None, source_uncertainty=None,
                payload={'open': True, 'safe': True, 'edge_ids': ['ab'], 'stock': 1000},
                acceptance={'method': 'human_review', 'reviewed_at': accepted})


def snapshot(bound, records=(), *, cutoff=None):
    current = [r for r in records if not r['retracted']]
    categories = {name: None for name in CATEGORIES}
    if current:
        categories['closures'] = current
    refs = [{key: r[key] for key in ('source_id', 'item_id', 'revision', 'raw_sha256')}
            for r in current]
    return seal(dict(schema_version='knight26-incident-v1', incident_id='exercise',
                     bbox_lonlat=[-121, 39, -120, 40],
                     cutoff_utc=cutoff or bound['cutoff_utc'], categories=categories,
                     revision_history=list(records), unconfirmed_leads=[],
                     accepted_source_refs=refs,
                     ledger_watermark=deepcopy(bound['ledger_watermark']),
                     in_flight_commitments=deepcopy(bound['in_flight_commitments']),
                     source_health=None))


class IncidentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.graph, self.old_safety, self.ledger, self.engine = setup(service=2)
        self.engine.advance(5, self.old_safety)
        self.checkpoint = self.engine.checkpoint()
        self.epoch = '2026-10-10T09:00:00Z'
        self.graph_identity = identity(self.graph)
        self.bound = bind_checkpoint(self.graph, self.checkpoint, self.epoch,
                                     self.graph_identity)
        self.manifest, self.files, self.receipt = frozen_bytes()
        self.record = closure_record()
        self.evidence = snapshot(self.bound, [self.record])

    def run_bridge(self, **overrides):
        options = dict(graph=self.graph, checkpoint=self.checkpoint, epoch_utc=self.epoch,
                       graph_identity=self.graph_identity, snapshot=self.evidence,
                       trusted_expected_snapshot_hash=self.evidence['snapshot_hash'],
                       edge_bindings=[dict(source_id='county', item_id='notice', revision=1,
                                           raw_sha256='a' * 64, edge_ids=['ab'],
                                           issued_at='2026-10-10T09:00:05Z',
                                           received_at='2026-10-10T09:00:05Z')],
                       manifest=self.manifest, contract_bytes=self.files,
                       receipt_bytes=self.receipt, horizon_minutes=60)
        options.update(overrides)
        return bridge_incident_v1(**options)

    def test_bound_gate_is_closed_and_freeform_open_safe_stock_is_inert(self):
        before = self.engine.snapshot()
        result = self.run_bridge()
        self.assertFalse(result.can_calculate_operational_outcomes)
        self.assertEqual(result.unknown_operational_categories, OPERATIONAL)
        self.assertEqual(result.unverified_operational_categories, OPERATIONAL)
        self.assertEqual(result.safety.covered_edges, frozenset())
        self.assertEqual(result.safety.safe_nodes, frozenset())
        self.assertEqual(result.safety.closures, ())
        self.assertFalse(result.safety.traversal('ab', 5, 10)[0])
        self.assertFalse(result.safety.destination_safe('D', 20))
        search = candidate_routes(self.graph, 'A', 'D', 'bus', 5, result.safety)
        self.assertEqual(search.routes, ())
        self.assertNotEqual(search.status, 'feasible')
        self.assertEqual(self.engine.snapshot(), before)
        self.assertEqual(self.engine.ledger.export_state()['outcome_totals']['safe_evacuated_people'], 0)

    def test_frozen_contract_tamper_and_manifest_gate_rejected(self):
        verify_frozen_contract(self.manifest, self.files, self.receipt)
        files = dict(self.files)
        files['contracts/incident.py'] += b'\n'
        with self.assertRaises(ValueError): self.run_bridge(contract_bytes=files)
        manifest = json.loads(self.manifest)
        manifest['operational_outcome_capability'] = True
        with self.assertRaises(ValueError): self.run_bridge(manifest=canonical(manifest))
        manifest = json.loads(self.manifest)
        manifest['scope'] = 'changed unrelated manifest field'
        with self.assertRaises(ValueError): self.run_bridge(manifest=canonical(manifest))
        with self.assertRaises(ValueError): self.run_bridge(receipt_bytes=self.receipt + b'\n')

    def test_snapshot_hash_and_trusted_expected_hash_both_required(self):
        altered = deepcopy(self.evidence); altered['categories']['closures'][0]['payload']['safe'] = False
        with self.assertRaises(ValueError): self.run_bridge(snapshot=altered)
        with self.assertRaises(ValueError): self.run_bridge(trusted_expected_snapshot_hash='0' * 64)

    def test_exact_cutoff_and_strict_utc(self):
        self.assertEqual(self.bound['cutoff_utc'], '2026-10-10T09:00:05Z')
        with self.assertRaises(ValueError): bind_checkpoint(self.graph, self.checkpoint,
                                                             '2026-10-10T09:00:00+00:00', self.graph_identity)
        with self.assertRaises(ValueError): self.run_bridge(snapshot=snapshot(self.bound, [self.record],
                                                                               cutoff='2026-10-10T09:00:04Z'))
        future = deepcopy(self.evidence)
        future['categories']['closures'][0]['accepted_at'] = '2026-10-10T09:00:05.000001Z'
        future['revision_history'][0]['accepted_at'] = '2026-10-10T09:00:05.000001Z'
        seal(future)
        with self.assertRaises(ValueError): self.run_bridge(snapshot=future,
            trusted_expected_snapshot_hash=future['snapshot_hash'])
        just_before = closure_record(accepted='2026-10-10T09:00:04.999999Z')
        accepted = snapshot(self.bound, [just_before])
        result = self.run_bridge(snapshot=accepted,
            trusted_expected_snapshot_hash=accepted['snapshot_hash'], edge_bindings=[])
        self.assertFalse(result.can_calculate_operational_outcomes)
        fractional = bind_checkpoint(self.graph, self.checkpoint,
            '2026-10-10T09:00:00.123456Z', self.graph_identity)
        self.assertEqual(fractional['cutoff_utc'], '2026-10-10T09:00:05.123456Z')

    def test_future_fetch_review_and_envelope_receipt_rejected(self):
        for field in ('fetched_at', 'acceptance'):
            altered = deepcopy(self.evidence)
            for record in (altered['categories']['closures'][0],
                           altered['revision_history'][0]):
                if field == 'acceptance':
                    record['acceptance']['reviewed_at'] = '2026-10-10T09:00:05.000001Z'
                else:
                    record[field] = '2026-10-10T09:00:05.000001Z'
            seal(altered)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_bridge(snapshot=altered,
                    trusted_expected_snapshot_hash=altered['snapshot_hash'])
        binding = dict(source_id='county', item_id='notice', revision=1,
                       raw_sha256='a' * 64, edge_ids=['ab'],
                       issued_at='2026-10-10T09:00:05.000001Z',
                       received_at='2026-10-10T09:00:05.000001Z')
        with self.assertRaises(ValueError): self.run_bridge(edge_bindings=[binding])

    def test_actual_frozen_evidence_log_snapshot_compatibility(self):
        verify_frozen_contract(self.manifest, self.files, self.receipt)
        module = types.ModuleType('frozen_incident_v1_fixture')
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        source = self.files['contracts/incident.py'].decode('utf-8')
        exec(compile(source, module.__name__, 'exec'), module.__dict__)
        log = module.EvidenceLog('exercise', [-121, 39, -120, 40])
        raw = b'fictional county notice for integration fixture'
        record = closure_record()
        record.pop('acceptance')
        record['raw_sha256'] = hashlib.sha256(raw).hexdigest()
        digest = module.record_fingerprint(record)
        log.append(record, verification=module.VerifiedSource(
            'county', record['source_url'], record['raw_sha256'], True, digest),
            review=module.HumanReview(('county', 'notice', 1),
                record['raw_sha256'], 'reviewer', tuple(record['payload']),
                record['accepted_at'], True, digest))
        actual = log.snapshot(self.bound['cutoff_utc'],
            ledger_watermark=self.bound['ledger_watermark'],
            in_flight_commitments=self.bound['in_flight_commitments'])
        result = self.run_bridge(snapshot=actual,
            trusted_expected_snapshot_hash=actual['snapshot_hash'],
            edge_bindings=[dict(source_id='county', item_id='notice', revision=1,
                raw_sha256=record['raw_sha256'], edge_ids=['ab'],
                issued_at='2026-10-10T09:00:05Z',
                received_at='2026-10-10T09:00:05Z')])
        self.assertEqual(result.snapshot_hash, actual['snapshot_hash'])
        self.assertFalse(result.can_calculate_operational_outcomes)
        self.assertIn('v1 disabled', result.safety.provenance)

    def test_checkpoint_change_and_graph_identity_rejected(self):
        changed = deepcopy(self.checkpoint); changed['checksum'] = '0' * 64
        with self.assertRaises(ValueError): self.run_bridge(checkpoint=changed)
        changed_graph = Graph(self.graph.nodes,
            [replace(edge, travel_s=edge.travel_s + 1) for edge in self.graph.edges.values()],
            version=self.graph.version)
        with self.assertRaises(ValueError): self.run_bridge(graph=changed_graph)
        wrong = deepcopy(self.graph_identity); wrong['source_metadata'] = {'source': 'other'}
        with self.assertRaises(ValueError): self.run_bridge(graph_identity=wrong)
        double = deepcopy(self.evidence)
        double['in_flight_commitments'].append(deepcopy(double['in_flight_commitments'][0]))
        seal(double)
        with self.assertRaises(ValueError): self.run_bridge(snapshot=double,
            trusted_expected_snapshot_hash=double['snapshot_hash'])

    def test_valid_later_actual_checkpoint_cannot_reuse_old_snapshot(self):
        old = deepcopy(self.evidence)
        self.engine.advance(6, self.old_safety)
        newer = self.engine.checkpoint()
        later = bind_checkpoint(self.graph, newer, self.epoch, self.graph_identity)
        self.assertEqual(later['cutoff_utc'], '2026-10-10T09:00:06Z')
        self.assertNotEqual(later['ledger_watermark'], old['ledger_watermark'])
        self.assertNotEqual(later['in_flight_commitments'], old['in_flight_commitments'])
        with self.assertRaises(ValueError): self.run_bridge(checkpoint=newer)

    def test_null_binding_and_foreign_or_unknown_edges_rejected(self):
        for field in ('ledger_watermark', 'in_flight_commitments'):
            altered = deepcopy(self.evidence); altered[field] = None; seal(altered)
            with self.subTest(field=field), self.assertRaises(ValueError): self.run_bridge(
                snapshot=altered, trusted_expected_snapshot_hash=altered['snapshot_hash'])
        for mutation in ({'edge_ids': ['missing']}, {'source_id': 'foreign'},
                         {'issued_at': '2026-10-10T09:00:06Z'},
                         {'received_at': '2026-10-10T09:00:06Z'},
                         {'revision': True}, {'revision': 1.0},
                         {'source_id': ''}, {'raw_sha256': 'A' * 64},
                         {'issued_at': '2026-10-10T09:00:04Z'},
                         {'received_at': '2026-10-10T09:00:04Z'}):
            binding = dict(source_id='county', item_id='notice', revision=1,
                           raw_sha256='a' * 64, edge_ids=['ab'],
                           issued_at='2026-10-10T09:00:05Z', received_at='2026-10-10T09:00:05Z')
            binding.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.run_bridge(edge_bindings=[binding])

    def test_retracted_and_historical_references_rejected(self):
        first = closure_record(accepted='2026-10-10T09:00:03Z')
        first['superseded_at'] = '2026-10-10T09:00:04Z'
        later = closure_record(accepted='2026-10-10T09:00:04Z', revision=2,
                               supersedes=['county', 'notice', 1], retracted=True)
        evidence = snapshot(self.bound, [first, later])
        evidence['categories']['closures'] = None
        evidence['accepted_source_refs'] = []
        seal(evidence)
        with self.assertRaises(ValueError): self.run_bridge(snapshot=evidence,
            trusted_expected_snapshot_hash=evidence['snapshot_hash'])

    def test_restoration_preserves_actual_mid_edge_commitments_and_no_alias(self):
        restored = TripExecutor.from_checkpoint(self.graph, deepcopy(self.checkpoint))
        same = bind_checkpoint(self.graph, restored.checkpoint(), self.epoch,
                               self.graph_identity)
        self.assertEqual(same, self.bound)
        commitment = self.bound['in_flight_commitments'][0]
        self.assertEqual(commitment['trip']['current_edge_id'], 'ab')
        self.assertEqual(commitment['assignment']['person_ids'], ['p1', 'p2'])
        before = self.engine.snapshot()
        result = self.run_bridge()
        self.evidence['categories']['closures'][0]['payload']['open'] = False
        self.checkpoint['trips']['dispatch1']['pending'].clear()
        self.assertEqual(self.engine.snapshot(), before)
        self.assertEqual(result.safety.covered_edges, frozenset())
        self.assertEqual(result.edge_bindings[0].edge_ids, ('ab',))


if __name__ == '__main__': unittest.main()
