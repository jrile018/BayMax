"""Fail-closed incident-v1 evidence context for a restored routing checkpoint.

This bridge does not interpret incident payloads or authorize operational work.
All trusted identity, manifest bytes, checkpoint, and expected snapshot hash are
explicit caller inputs; no runtime path or import from the frozen contract exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from json import dumps, loads
from re import compile as re_compile

from .checkpoint import graph_fingerprint
from .safety import SafetySnapshot
from .trip import TripExecutor


VERSION = 'knight26-incident-v1'
CATEGORIES = ('hazard', 'needs', 'closures', 'vehicles', 'stock', 'capacity')
OPERATIONAL = CATEGORIES[1:]
UTC_RE = re_compile(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$')
SHA_RE = re_compile(r'^[0-9a-f]{64}$')
FROZEN_HASHES = {
    'contracts/incident.py': 'e456253dfee508171ceb45a818560d002f47b58ef8d79968dc041c245489fc1f',
    'contracts/INCIDENT_V1.md': '74131b06f62e069ddf2337bb8bccef40f371efd71b7779e0aedcd8db7267ed3c',
    'contracts/tests/test_incident.py': '7c6ddac9730bc84f371e91254ade5ad45bbad706ff3488386dce7763dd976e39',
}
FROZEN_RECEIPT_HASH = '6d29687d73fff3ebdac7c02a1b7e95e289297ac67b5a9a4b543ac0037e42dab0'
FROZEN_MANIFEST_HASH = 'f7d8fbd0613ba34f188e77e43a96219703914ccfe8e1e3e49b929585858d8ede'
REVIEWED_COMMIT = 'a294c868e75d8f8de3f3f9fb3ed7e52bee225ae6'
SNAPSHOT_KEYS = frozenset(('schema_version', 'incident_id', 'bbox_lonlat', 'cutoff_utc',
    'categories', 'revision_history', 'unconfirmed_leads', 'accepted_source_refs',
    'ledger_watermark', 'in_flight_commitments', 'source_health', 'snapshot_hash'))
RECORD_KEYS = frozenset(('source_id', 'item_id', 'revision', 'source_url', 'raw_sha256',
    'provider', 'license', 'source_type', 'category', 'source_kind', 'published_at',
    'observed_at', 'valid_from', 'valid_through', 'message_expires_at', 'first_seen_at',
    'fetched_at', 'accepted_at', 'correction_available_at', 'superseded_at',
    'supersedes', 'retracted', 'source_reference', 'geometry', 'precision',
    'area_label', 'source_uncertainty', 'payload', 'acceptance'))
REF_KEYS = ('source_id', 'item_id', 'revision', 'raw_sha256')
IDENTITY_KEYS = frozenset(('graph_fingerprint', 'graph_version', 'metric_crs',
                           'origin_lonlat', 'source_metadata'))
BINDING_KEYS = frozenset((*REF_KEYS, 'edge_ids', 'issued_at', 'received_at'))


def _require(condition, message):
    if not condition:
        raise ValueError('incident v1 bridge: ' + message)


def _canonical(value):
    try:
        return dumps(value, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError('incident v1 bridge: finite JSON required') from exc


def _copy(value):
    return loads(_canonical(value))


def _same(left, right):
    return _canonical(left) == _canonical(right)


def _utc(value, name):
    _require(isinstance(value, str) and UTC_RE.fullmatch(value), name + ' needs strict UTC Z')
    try:
        return datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as exc:
        raise ValueError('incident v1 bridge: invalid ' + name) from exc


def _optional_utc(value, name):
    return None if value is None else _utc(value, name)


def _utc_string(value):
    fraction = ('.' + f'{value.microsecond:06d}'.rstrip('0')) if value.microsecond else ''
    return value.strftime('%Y-%m-%dT%H:%M:%S') + fraction + 'Z'


def _sha(value, name):
    _require(isinstance(value, str) and SHA_RE.fullmatch(value), name + ' needs lowercase SHA-256')


def verify_frozen_contract(manifest, contract_bytes, receipt_bytes):
    """Verify caller-provided immutable contract and independent review bytes."""
    _require(type(manifest) is bytes and sha256(manifest).hexdigest() == FROZEN_MANIFEST_HASH,
             'frozen manifest bytes differ')
    try:
        m = loads(manifest)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('incident v1 bridge: invalid frozen manifest JSON') from exc
    _require(isinstance(m, dict) and m.get('version') == VERSION
             and m.get('reviewed_commit') == REVIEWED_COMMIT
             and m.get('immutable_dependency') is True
             and m.get('operational_outcome_capability') is False
             and m.get('file_sha256') == FROZEN_HASHES
             and m.get('independent_receipt_sha256') == FROZEN_RECEIPT_HASH,
             'frozen manifest identity/capability differs')
    _require(isinstance(contract_bytes, dict) and set(contract_bytes) == set(FROZEN_HASHES),
             'exact frozen contract bytes required')
    for name, digest in FROZEN_HASHES.items():
        raw = contract_bytes[name]
        _require(type(raw) is bytes and sha256(raw).hexdigest() == digest,
                 'frozen contract bytes differ: ' + name)
    _require(type(receipt_bytes) is bytes and sha256(receipt_bytes).hexdigest() == FROZEN_RECEIPT_HASH,
             'independent receipt bytes differ')
    return True


def _graph_identity(graph):
    return dict(graph_fingerprint=graph_fingerprint(graph), graph_version=graph.version,
                metric_crs=getattr(graph, 'metric_crs', 'declared local metric x/y metres'),
                origin_lonlat=getattr(graph, 'origin_lonlat', None),
                source_metadata=getattr(graph, 'source_metadata', None))


def _time_from_checkpoint(epoch_utc, now_s):
    epoch = _utc(epoch_utc, 'epoch_utc')
    _require(type(now_s) in (int, float) and now_s >= 0, 'checkpoint now_s')
    try:
        micros = Decimal(str(now_s)) * 1_000_000
        _require(micros == micros.to_integral_value(), 'checkpoint time needs exact microseconds')
        cutoff = epoch + timedelta(microseconds=int(micros))
    except (OverflowError, ValueError) as exc:
        raise ValueError('incident v1 bridge: checkpoint cutoff overflow') from exc
    return cutoff


def bind_checkpoint(graph, checkpoint, epoch_utc, graph_identity):
    """Bind complete validated actual state; no dispatch or simulation occurs.

    Fractional checkpoint seconds must resolve to whole microseconds. A finer
    value is rejected instead of silently rounding the evidence cutoff.
    """
    expected = _copy(graph_identity)
    _require(isinstance(expected, dict) and set(expected) == IDENTITY_KEYS
             and _same(expected, _graph_identity(graph)), 'explicit graph identity differs')
    saved = _copy(checkpoint)
    restored = TripExecutor.from_checkpoint(graph, saved)
    checked = restored.checkpoint()
    _require(_same(saved, checked), 'checkpoint changed during validated restoration')
    cutoff = _time_from_checkpoint(epoch_utc, restored.now_s)
    commitments = []
    for dispatch_id in sorted(checked['trips']):
        trip = checked['trips'][dispatch_id]
        assignment = checked['ledger']['state']['assignments'][dispatch_id]
        if trip['phase'] != 'completed':
            commitments.append(dict(dispatch_id=dispatch_id,
                                    assignment=_copy(assignment), trip=_copy(trip)))
    watermark = dict(executor_checksum=checked['checksum'],
                     ledger_checksum=checked['ledger']['checksum'],
                     executor_audit_count=len(checked['events']),
                     ledger_audit_count=len(checked['ledger']['state']['events']),
                     now_s=restored.now_s, epoch_utc=epoch_utc,
                     graph_fingerprint=expected['graph_fingerprint'],
                     graph_version=expected['graph_version'],
                     metric_crs=expected['metric_crs'],
                     origin_lonlat=expected['origin_lonlat'],
                     source_metadata=expected['source_metadata'])
    return _copy(dict(cutoff_utc=_utc_string(cutoff), ledger_watermark=watermark,
                      in_flight_commitments=commitments))


def _record_ref(record):
    return {key: record[key] for key in REF_KEYS}


def _validate_record(record, cutoff):
    _require(isinstance(record, dict) and set(record) == RECORD_KEYS, 'record fields')
    for name in ('source_id', 'item_id', 'provider', 'source_url'):
        _require(isinstance(record[name], str) and bool(record[name]), 'record ' + name)
    _sha(record['raw_sha256'], 'record raw_sha256')
    _require(type(record['revision']) is int and record['revision'] > 0, 'record revision')
    _require(record['category'] in CATEGORIES, 'record category')
    _require(type(record['retracted']) is bool, 'record retracted')
    for name in ('first_seen_at', 'fetched_at', 'accepted_at'):
        _require(_utc(record[name], name) <= cutoff, 'future known ' + name)
    accepted = _utc(record['accepted_at'], 'accepted_at')
    _require(_utc(record['first_seen_at'], 'first_seen_at') <=
             _utc(record['fetched_at'], 'fetched_at') <= accepted, 'record acquisition order')
    known_times = {}
    for name in ('published_at', 'observed_at', 'correction_available_at'):
        when = _optional_utc(record[name], name)
        _require(when is None or when <= accepted, name + ' after acceptance')
        known_times[name] = when
    superseded = _optional_utc(record['superseded_at'], 'superseded_at')
    _require(superseded is None or superseded <= cutoff, 'future known superseded_at')
    valid_from = _optional_utc(record['valid_from'], 'valid_from')
    valid_through = _optional_utc(record['valid_through'], 'valid_through')
    _optional_utc(record['message_expires_at'], 'message_expires_at')
    _require(valid_from is None or valid_through is None or valid_from <= valid_through,
             'valid_from after valid_through')
    _require(record['source_kind'] != 'observed' or known_times['observed_at'] is not None,
             'observed claim needs observed_at')
    acceptance = record['acceptance']
    _require(isinstance(acceptance, dict) and acceptance.get('method') in
             ('official_policy', 'human_review'), 'record acceptance')
    if acceptance['method'] == 'human_review':
        reviewed = _utc(acceptance.get('reviewed_at'), 'reviewed_at')
        _require(_utc(record['fetched_at'], 'fetched_at') <= reviewed <= accepted,
                 'review outside acquisition/acceptance')
    _require(record['supersedes'] is None or
             (isinstance(record['supersedes'], list) and len(record['supersedes']) == 3
              and record['supersedes'][:2] == [record['source_id'], record['item_id']]
              and type(record['supersedes'][2]) is int
              and record['correction_available_at'] is not None), 'record correction link')
    _require(not record['retracted'] or record['supersedes'] is not None,
             'retraction without prior revision')


def _validate_snapshot(snapshot, trusted_expected_hash, cutoff):
    s = _copy(snapshot)
    _sha(trusted_expected_hash, 'trusted expected snapshot hash')
    _require(isinstance(s, dict) and set(s) == SNAPSHOT_KEYS
             and s['schema_version'] == VERSION, 'snapshot v1 fields')
    recorded = s.pop('snapshot_hash')
    _require(recorded == sha256(_canonical(s)).hexdigest()
             and recorded == trusted_expected_hash, 'snapshot checksum/trusted hash differs')
    s['snapshot_hash'] = recorded
    _require(_utc(s['cutoff_utc'], 'cutoff_utc') == cutoff, 'snapshot cutoff differs from checkpoint')
    _require(isinstance(s['incident_id'], str) and bool(s['incident_id']), 'incident ID')
    bbox = s['bbox_lonlat']
    _require(isinstance(bbox, list) and len(bbox) == 4 and all(
        type(x) in (int, float) and -180 <= x <= 180 for x in bbox)
        and bbox[0] < bbox[2] and bbox[1] < bbox[3]
        and -90 <= bbox[1] <= 90 and -90 <= bbox[3] <= 90, 'incident bbox')
    _require(isinstance(s['categories'], dict) and set(s['categories']) == set(CATEGORIES)
             and isinstance(s['revision_history'], list)
             and isinstance(s['unconfirmed_leads'], list)
             and isinstance(s['accepted_source_refs'], list), 'snapshot collections')
    by_item = {}
    for record in s['revision_history']:
        _validate_record(record, cutoff)
        key = record['source_id'], record['item_id']
        by_item.setdefault(key, []).append(record)
    latest = []
    for key, versions in by_item.items():
        versions.sort(key=lambda r: r['revision'])
        for index, record in enumerate(versions):
            prior = versions[index - 1] if index else None
            following = versions[index + 1] if index + 1 < len(versions) else None
            _require(prior is None or
                     (record['revision'] > prior['revision'] and
                      record['supersedes'] == [*key, prior['revision']] and
                      _utc(prior['accepted_at'], 'accepted_at') <=
                      _utc(record['accepted_at'], 'accepted_at')),
                     'revision chain differs')
            _require((prior is not None or record['supersedes'] is None)
                     and record['superseded_at'] ==
                     (following['accepted_at'] if following else None),
                     'derived superseded time differs')
        if not versions[-1]['retracted']:
            latest.append(versions[-1])
    latest.sort(key=lambda r: (r['category'], r['source_id'], r['item_id'], r['revision']))
    leads = [r for r in latest if r['category'] == 'hazard' and r['source_type'] == 'news']
    _require(_same(s['unconfirmed_leads'], leads), 'unconfirmed leads differ from history')
    for category in CATEGORIES:
        matching = [r for r in latest if r['category'] == category and r not in leads]
        _require(_same(s['categories'][category], matching or None),
                 'current category differs from history: ' + category)
    _require(_same(s['accepted_source_refs'], [_record_ref(r) for r in latest]),
             'accepted refs differ from current records')
    health = s['source_health']
    _require(health is None or isinstance(health, dict), 'source health')
    if health:
        for item in health.values():
            _require(isinstance(item, dict) and item.get('status') in
                     ('alive', 'stale', 'failure'), 'source health status')
            when = _optional_utc(item.get('source_time'), 'source_time')
            _require(when is None or when <= cutoff, 'future source health')
    return s


@dataclass(frozen=True)
class EdgeEvidenceBinding:
    source_id: str
    item_id: str
    revision: int
    raw_sha256: str
    edge_ids: tuple[str, ...]
    issued_at: str
    received_at: str


@dataclass(frozen=True)
class IncidentBridgeResult:
    snapshot_hash: str
    cutoff_utc: str
    horizon_utc: str
    graph_fingerprint: str
    edge_bindings: tuple[EdgeEvidenceBinding, ...]
    missing_operational_categories: tuple[str, ...]
    unknown_operational_categories: tuple[str, ...]
    unverified_operational_categories: tuple[str, ...]
    operational_completeness: str
    can_calculate_operational_outcomes: bool
    safety: SafetySnapshot


def bridge_incident_v1(*, graph, checkpoint, epoch_utc, graph_identity, snapshot,
                       trusted_expected_snapshot_hash, edge_bindings, manifest,
                       contract_bytes, receipt_bytes, horizon_minutes):
    """Verify evidence and return an inert routing context with a closed gate."""
    verify_frozen_contract(manifest, contract_bytes, receipt_bytes)
    bound = bind_checkpoint(graph, checkpoint, epoch_utc, graph_identity)
    cutoff = _utc(bound['cutoff_utc'], 'bound cutoff')
    s = _validate_snapshot(snapshot, trusted_expected_snapshot_hash, cutoff)
    _require(s['ledger_watermark'] is not None and s['in_flight_commitments'] is not None
             and _same(s['ledger_watermark'], bound['ledger_watermark'])
             and _same(s['in_flight_commitments'], bound['in_flight_commitments']),
             'stale or missing checkpoint binding')
    _require(type(horizon_minutes) is int and 1 <= horizon_minutes <= 10080,
             'horizon_minutes must be 1..10080')
    horizon = cutoff + timedelta(minutes=horizon_minutes)
    _require(horizon >= cutoff, 'horizon before cutoff')
    _require(isinstance(edge_bindings, (tuple, list)), 'typed edge bindings required')
    current = {(r['source_id'], r['item_id'], r['revision'], r['raw_sha256']): r
               for r in (s['categories']['closures'] or [])}
    bound_edges = []
    seen = set()
    for value in edge_bindings:
        b = _copy(value)
        _require(isinstance(b, dict) and set(b) == BINDING_KEYS, 'typed edge binding fields')
        _require(all(isinstance(b[name], str) and bool(b[name])
                     for name in ('source_id', 'item_id'))
                 and type(b['revision']) is int and b['revision'] > 0,
                 'typed source/item/revision identity')
        _sha(b['raw_sha256'], 'binding raw_sha256')
        ref = tuple(b[key] for key in REF_KEYS)
        _require(ref in current and ref not in seen, 'edge binding lacks current accepted closure')
        seen.add(ref)
        edges = b['edge_ids']
        _require(isinstance(edges, list) and bool(edges) and
                 all(isinstance(eid, str) and bool(eid) and eid in graph.edges for eid in edges)
                 and len(edges) == len(set(edges)), 'unknown or duplicate directed edge ID')
        record = current[ref]
        issued = _utc(b['issued_at'], 'issued_at')
        received = _utc(b['received_at'], 'received_at')
        published = _optional_utc(record['published_at'], 'published_at')
        _require(issued <= received <= cutoff
                 and received >= _utc(record['accepted_at'], 'accepted_at')
                 and received >= _utc(record['fetched_at'], 'fetched_at')
                 and (published is None or issued >= published),
                 'edge evidence arrived after cutoff or before issue')
        bound_edges.append(EdgeEvidenceBinding(*ref, tuple(edges),
                                               b['issued_at'], b['received_at']))
    now_s = bound['ledger_watermark']['now_s']
    safety = SafetySnapshot(version='incident-v1-disabled:' + s['snapshot_hash'][:16],
                            known_at_s=now_s, issued_s=now_s,
                            horizon_s=now_s + horizon_minutes * 60,
                            closures=(), covered_edges=frozenset(),
                            safe_nodes=frozenset(),
                            operational_enabled=False,
                            provenance='incident v1 disabled: operational safety unverified')
    return IncidentBridgeResult(s['snapshot_hash'], s['cutoff_utc'],
                                _utc_string(horizon), bound['ledger_watermark']['graph_fingerprint'],
                                tuple(bound_edges),
                                tuple(name for name in OPERATIONAL if s['categories'][name] is None),
                                OPERATIONAL, OPERATIONAL, 'not_validated', False, safety)
