"""Finite held-out TRAINING cohort: directed cycles and information rerouting.
New coverage only. No old acceptance suite, network, ledger mutation or dispatcher.
Execute solely via a separately reviewed launcher and fresh coordinator CPU grant.
"""
import argparse
import copy
import hashlib
import types
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINS = {
    'services/routing/training_time_search.py':
        '88f4f05f72b1be2448ce6312a9494c18af9b4bffb10520126efa75ccf4c451a0',
    'fixtures/routing/time_reference.py':
        '21ba3de4c489bfb528498ddb34212375b52063fb77ceace6c564e4999f62204c',
}
TOTAL_CASES = 768
PREFIX_BOUND = 9841  # sum(3**depth for depth in range(9)); at most two edges + WAIT


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf8')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def pinned_module(relative, name):
    path = ROOT / relative
    require(not path.is_symlink(), 'pinned source is a symlink')
    data = path.read_bytes()
    require(len(data) <= 1024**2, 'pinned source size bound')
    require(hashlib.sha256(data).hexdigest() == PINS[relative], 'pinned source changed')
    module = types.ModuleType(name)
    module.__file__ = str(path)
    # Execute precisely the verified source bytes during the authorized run;
    # no filename-loader reopen or timestamp-valid bytecode-cache substitution.
    exec(compile(data, str(path), 'exec'), module.__dict__)
    return module


def node(name, safe=None):
    return dict(id=name, known=[[0, 9]], safe=[[0, 9]] if safe is None else safe)


def edge(name, source, target, duration=1, reopening=0):
    return dict(id=name, source=source, target=target, duration=duration,
                access='ALLOWED', known=[[0, 9]],
                closed=[[0, reopening]] if reopening else [])


def request(case_id, nodes, edges, **updates):
    result = dict(schema='routing.training.time.v1', mode='TRAINING',
                  request_id=case_id, trip_id='heldout-trip', graph_version='authored-cycle-v1',
                  now=0, deadline=8, buffer=0, service_duration=0,
                  knowledge=dict(version='heldout-k1', valid_from=0, valid_until=9),
                  resources=dict(version='heldout-r1',
                    free_bus_seats_excluding_own_pickup_reservation=4,
                    free_destination_slots_excluding_own_reservation=7),
                  commitments=dict(reservation_id='heldout-res', onboard=3, pickup=4,
                                   destination_id='d', opaque={'reserved_pickup': 2}),
                  anchor=dict(kind='node', node='a'), destination='d',
                  alternatives=3, max_expansions=100000, nodes=nodes, edges=edges)
    result.update(updates)
    return result


def cases():
    ordinal = 0
    for mask in range(64):
        # Do not repeat configurations when a parameter's edge is absent.
        durations = (1, 2) if mask & (1 << 2) else (1,)
        reopenings = (0, 2, 4) if mask & (1 << 3) else (0,)
        for duration, reopening, gap, buffer in itertools.product(
                durations, reopenings, (False, True), (0, 1)):
            case_id = 'cycle-%04d' % ordinal
            catalog = [('ab', 'a', 'b', 1), ('bc', 'b', 'c', 1),
                       ('ca', 'c', 'a', duration), ('ad', 'a', 'd', 1),
                       ('bd', 'b', 'd', 1), ('cd', 'c', 'd', 1)]
            selected = [edge(name, start, end, cost, reopening if name == 'ad' else 0)
                        for bit, (name, start, end, cost) in enumerate(catalog)
                        if mask & (1 << bit)]
            nodes = [node('a', [[0, 1], [4, 9]] if gap else None),
                     node('b'), node('c'), node('d')]
            yield ordinal, request(case_id, nodes, selected, buffer=buffer)
            ordinal += 1


def compare(req, solver, oracle):
    before = encoded(req)
    reference = oracle.enumerate_reference(req, max_prefixes=PREFIX_BOUND)
    result = solver.search(req)
    require(encoded(req) == before, 'input mutated')
    require(result['status'] not in ('SEARCH_LIMIT', 'INVALID_INPUT',
                                     'INFORMATION_UNAVAILABLE', 'HORIZON_EXPIRED'),
            'unexpected status for fully known bounded cohort: ' + result['status'])
    routes, actual = reference['routes'], result['candidates']
    require(result['status'] == ('FEASIBLE' if routes else 'UNREACHABLE_UNDER_MODEL'),
            'feasibility disagrees with independent exhaustive oracle')
    require(result['alternatives_complete'] is True, 'incomplete alternatives')
    require(len(actual) == min(req['alternatives'], len(routes)), 'route count differs')
    ranked = sorted(route['completion'] for route in routes)
    require([c['completion'] for c in actual] == ranked[:req['alternatives']],
            'completion ranks differ; equal-completion cutoff routes are interchangeable')
    per_route = {tuple(r['edge_sequence']): r['completion'] for r in routes}
    seen = set()
    for candidate in actual:
        sequence = tuple(candidate['edge_sequence'])
        require(sequence not in seen, 'duplicate edge sequence')
        seen.add(sequence)
        require(sequence in per_route and candidate['completion'] == per_route[sequence],
                'route does not have its earliest completion')
        require(oracle.check_candidate(req, candidate), 'independent candidate check failed')
    return reference['prefixes'], result['expansions'], len(routes), result


def literals(solver, oracle):
    # At each intermediate arrival there is no safe one-tick wait. The only route
    # is the explicitly directed a->b->c->a cycle, returning when ad reopens.
    req = request('literal-required-cycle',
                  [node('a', [[0, 1], [4, 9]]), node('b', [[1, 2]]),
                   node('c', [[2, 3]]), node('d')],
                  [edge('ab', 'a', 'b'), edge('bc', 'b', 'c'),
                   edge('ca', 'c', 'a', 2), edge('ad', 'a', 'd', reopening=4)],
                  alternatives=1)
    _, _, _, result = compare(req, solver, oracle)
    candidate = result['candidates'][0]
    require(candidate['edge_sequence'] == ['ab', 'bc', 'ca', 'ad']
            and candidate['completion'] == 5, 'required-cycle literal failed')
    require(all(a['kind'] != 'WAIT' for a in candidate['actions']),
            'unsafe wait used instead of required directed cycle')

    req = request('literal-information-reroute',
                  [node('a'), node('b'), node('c'), node('d')],
                  [edge('ab', 'a', 'b', 5), edge('bd', 'b', 'd'),
                   edge('bc', 'b', 'c'), edge('cd', 'c', 'd')],
                  now=1, alternatives=1,
                  anchor=dict(kind='edge', edge='ab', entered_at=0,
                              duration_at_entry=3, source_at_entry='a', target_at_entry='b'))
    _, _, _, old = compare(req, solver, oracle)
    old_candidate = old['candidates'][0]
    require(old_candidate['edge_sequence'] == ['ab', 'bd']
            and old_candidate['completion'] == 4, 'original suffix literal failed')
    changed = copy.deepcopy(req)
    changed['knowledge']['version'] = 'heldout-k2'
    changed['edges'][1]['closed'] = [[0, 9]]
    _, _, _, new = compare(changed, solver, oracle)
    candidate = new['candidates'][0]
    require(candidate['edge_sequence'] == ['ab', 'bc', 'cd']
            and candidate['completion'] == 5, 'new feasible forward suffix failed')
    require(candidate['actions'][0] == old_candidate['actions'][0]
            and candidate['actions'][0]['end'] == 3, 'committed edge timing/progress changed')
    require(candidate['anchor'] == req['anchor']
            and candidate['commitments'] == req['commitments'],
            'anchor, onboard, pickup or reservation changed')
    require(solver.revalidate(old_candidate, changed)['status'] == 'REPLAN_REQUIRED',
            'stale knowledge proposal accepted')
    require(solver.revalidate(candidate, changed)['status'] == 'VALIDATED_PROPOSAL',
            'new pure proposal did not revalidate')
    return ['required-directed-cycle', 'underway-information-forward-reroute']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--shards', type=int, choices=(1, 2), required=True)
    parser.add_argument('--shard', type=int, required=True)
    args = parser.parse_args()
    parser.error('shard outside range') if not 0 <= args.shard < args.shards else None
    summary = dict(schema='routing.training.cyclic-cohort.v1', mode='TRAINING',
                   status='INCOMPLETE', shards=args.shards, shard=args.shard,
                   cohort_total=TOTAL_CASES, assigned_cases=TOTAL_CASES // args.shards,
                   completed_cases=0, reference_prefixes=0, solver_expansions=0,
                   max_reference_prefixes_per_case=0, routes_enumerated=0,
                   literal_checks=[], source_pins=PINS,
                   harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    request_digest = hashlib.sha256()
    case_id = 'source-pins'
    try:
        solver = pinned_module('services/routing/training_time_search.py', 'owned_cycle_solver')
        oracle = pinned_module('fixtures/routing/time_reference.py', 'owned_cycle_oracle')
        if args.shard == 0:
            case_id = 'literals'
            summary['literal_checks'] = literals(solver, oracle)
        for ordinal, req in cases():
            if ordinal % args.shards != args.shard:
                continue
            case_id = req['request_id']
            prefixes, expansions, routes, _ = compare(req, solver, oracle)
            request_digest.update(encoded(req) + b'\n')
            summary['completed_cases'] += 1
            summary['reference_prefixes'] += prefixes
            summary['solver_expansions'] += expansions
            summary['max_reference_prefixes_per_case'] = max(
                summary['max_reference_prefixes_per_case'], prefixes)
            summary['routes_enumerated'] += routes
        require(summary['completed_cases'] == summary['assigned_cases'], 'cohort count mismatch')
        summary['status'] = 'PASS'
    except Exception as error:
        summary['status'] = 'INCOMPLETE' if type(error).__name__ == 'ReferenceLimit' else 'FAIL'
        summary['first_unfinished_case'] = case_id
        summary['error_type'] = type(error).__name__
        summary['error'] = str(error)[:1000]
    summary['completed_requests_sha256'] = request_digest.hexdigest()
    print(json.dumps(summary, sort_keys=True, separators=(',', ':')))
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
