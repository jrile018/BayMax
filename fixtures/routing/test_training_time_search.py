"""Literal TRAINING routing contracts and independent tiny-grid comparisons."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module_at(relative, name):
    path = ROOT / relative
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOLVER = module_at('services/routing/training_time_search.py', 'owned_time_solver')
ORACLE = module_at('fixtures/routing/time_reference.py', 'owned_time_reference')


def node(name, safe=None, known=None):
    return dict(id=name, known=[[0, 8]] if known is None else known,
                safe=[[0, 8]] if safe is None else safe)


def edge(name, source, target, duration=2, closed=None, access='ALLOWED', known=None):
    return dict(id=name, source=source, target=target, duration=duration, access=access,
                known=[[0, 8]] if known is None else known, closed=[] if closed is None else closed)


def request(nodes=None, edges=None, **updates):
    result = dict(schema='routing.training.time.v1', mode='TRAINING',
                  request_id='request-1', trip_id='trip-1', graph_version='authored-1',
                  now=0, deadline=7, buffer=0, service_duration=0,
                  knowledge=dict(version='k1', valid_from=0, valid_until=8),
                  resources=dict(version='r1',
                    free_bus_seats_excluding_own_pickup_reservation=4,
                    free_destination_slots_excluding_own_reservation=7),
                  commitments=dict(reservation_id='res-1', onboard=3, pickup=4,
                                   destination_id='d', opaque={'reserved_pickup': 2}),
                  anchor=dict(kind='node', node='a'), destination='d',
                  alternatives=1, max_expansions=10000,
                  nodes=nodes if nodes is not None else [node('a'), node('d')],
                  edges=edges if edges is not None else [edge('ad', 'a', 'd')])
    result.update(updates)
    return result


class TimeContracts(unittest.TestCase):
    def search(self, req):
        self.assertIsNotNone(SOLVER, 'waiting-aware TRAINING solver is absent')
        return SOLVER.search(req)

    def candidate(self, req):
        result = self.search(req)
        self.assertEqual(result['status'], 'FEASIBLE', result)
        return result['candidates'][0]

    def underway(self):
        return request(nodes=[node('a'), node('b'), node('d')],
                       edges=[edge('ab', 'a', 'b', 5), edge('bd', 'b', 'd', 1)],
                       now=1, anchor=dict(kind='edge', edge='ab', entered_at=0,
                         duration_at_entry=3, source_at_entry='a', target_at_entry='b'))

    def test_directed_and_bus_access(self):
        self.assertEqual(self.candidate(request())['completion'], 2)
        reverse = request(anchor=dict(kind='node', node='d'), destination='a')
        reverse['commitments']['destination_id'] = 'a'
        self.assertEqual(self.search(reverse)['status'], 'UNREACHABLE_UNDER_MODEL')
        req = request(nodes=[node('a'), node('b'), node('d')],
                      edges=[edge('shortcut', 'a', 'd', 1, access='DENIED'),
                             edge('ab', 'a', 'b'), edge('bd', 'b', 'd')])
        self.assertEqual(self.candidate(req)['edge_sequence'], ['ab', 'bd'])

    def test_reopening_requires_explicit_safe_wait(self):
        req = request(edges=[edge('ad', 'a', 'd', closed=[[0, 3]])])
        candidate = self.candidate(req)
        self.assertEqual(candidate['arrival'], 5)
        self.assertEqual([a['kind'] for a in candidate['actions']], ['WAIT']*3+['TRAVERSE','SERVICE'])
        req['nodes'][0]['safe'] = [[0, 2], [3, 8]]
        self.assertEqual(self.search(req)['status'], 'UNREACHABLE_UNDER_MODEL')

    def test_full_edge_closure_and_zero_buffer_endpoint(self):
        req = request(nodes=[node('a', safe=[[0, 1]]), node('d')],
                      edges=[edge('ad', 'a', 'd', closed=[[2, 8]])])
        self.assertEqual(self.candidate(req)['arrival'], 2)
        req['buffer'] = 1
        self.assertEqual(self.search(req)['status'], 'UNREACHABLE_UNDER_MODEL')
        req['buffer'] = 0
        req['edges'][0]['closed'] = [[1, 8]]
        self.assertEqual(self.search(req)['status'], 'UNREACHABLE_UNDER_MODEL')

    def test_service_deadline_safe_endpoint_and_horizon(self):
        req = request(service_duration=2, deadline=4)
        self.assertEqual(self.candidate(req)['completion'], 4)
        req['deadline'] = 3
        self.assertEqual(self.search(req)['status'], 'UNREACHABLE_UNDER_MODEL')
        req = request(nodes=[node('a', safe=[[0, 1]]), node('d', safe=[[0, 4]])],
                      service_duration=2)
        self.assertEqual(self.search(req)['status'], 'UNREACHABLE_UNDER_MODEL')
        req = request(nodes=[node('a'), node('d')], edges=[edge('ad','a','d',4)],
                      buffer=2, knowledge=dict(version='k1',valid_from=0,valid_until=6))
        req['nodes'][1]['safe'] = [[0,6]]
        req['nodes'][1]['known'] = [[0,6]]
        req['edges'][0]['known'] = [[0,6]]
        self.assertEqual(self.candidate(req)['completion'], 4)
        req['service_duration'] = 2
        req['buffer'] = 0
        self.assertEqual(self.search(req)['status'], 'HORIZON_EXPIRED')

    def test_adjacent_interval_union(self):
        req = request(edges=[edge('ad','a','d',known=[[0,1],[1,8]])])
        req['nodes'][1]['known'] = [[0,2],[2,8]]
        self.assertEqual(self.candidate(req)['arrival'], 2)

    def test_unknown_is_not_open_and_dead_end_does_not_taint(self):
        for field, value in [('known', []), ('access','UNKNOWN')]:
            req = request()
            req['edges'][0][field] = value
            self.assertEqual(self.search(req)['status'], 'INFORMATION_UNAVAILABLE')
        req = request(nodes=[node('a'),node('x'),node('d')],
                      edges=[edge('ax','a','x',access='UNKNOWN')],deadline=20)
        self.assertEqual(self.search(req)['status'], 'UNREACHABLE_UNDER_MODEL')
        req = request(edges=[edge('ad','a','d',access='UNKNOWN')], service_duration=3, deadline=4)
        self.assertEqual(self.search(req)['status'], 'UNREACHABLE_UNDER_MODEL')

    def test_start_unknown_unsafe_expired(self):
        req = request()
        req['nodes'][0]['known'] = []
        self.assertEqual(self.search(req)['status'], 'INFORMATION_UNAVAILABLE')
        req = request()
        req['nodes'][0]['safe'] = []
        self.assertEqual(self.search(req)['status'], 'UNREACHABLE_UNDER_MODEL')
        req = request(now=8,deadline=10)
        self.assertEqual(self.search(req)['status'], 'HORIZON_EXPIRED')

    def test_underway_preserves_original_time_and_commitments(self):
        req = self.underway()
        req['edges'][0]['closed'] = [[0,1]]
        candidate = self.candidate(req)
        continuation = candidate['actions'][0]
        self.assertEqual(continuation['kind'], 'CONTINUE_EDGE')
        self.assertEqual((continuation['start'], continuation['end'], continuation['elapsed_at_start']), (1,3,1))
        self.assertEqual(candidate['arrival'],4)
        self.assertEqual(candidate['edge_sequence'],['ab','bd'])
        self.assertEqual(candidate['commitments'],req['commitments'])
        self.assertEqual(candidate['anchor'],req['anchor'])

    def test_underway_stranding_and_identity_do_not_teleport(self):
        for change in ['closure','coverage','horizon','access','identity']:
            req = self.underway()
            if change == 'closure': req['edges'][0]['closed'] = [[2,3]]
            if change == 'coverage': req['edges'][0]['known'] = []
            if change == 'horizon': req['knowledge']['valid_until'] = 3
            if change == 'access': req['edges'][0]['access'] = 'UNKNOWN'
            if change == 'identity': req['edges'][0]['target'] = 'd'
            result = self.search(req)
            self.assertEqual(result['status'],'STRANDED', (change,result))
            self.assertEqual(result['anchor'],req['anchor'])
            self.assertEqual(result['commitments'],req['commitments'])
            self.assertEqual(result['candidates'],[])
        req = self.underway()
        req['edges'][0]['closed'] = [[2,3]]
        req['resources']['free_destination_slots_excluding_own_reservation'] = 0
        self.assertEqual(self.search(req)['status'],'STRANDED')

    def test_suffix_failure_retains_certified_continuation(self):
        req = self.underway()
        req['edges'][1]['access'] = 'DENIED'
        result = self.search(req)
        self.assertEqual(result['status'],'UNREACHABLE_UNDER_MODEL')
        self.assertEqual(result['continuation'][0]['end'],3)

    def test_search_limit_and_exact_cap_precedence(self):
        self.assertEqual(self.search(request(max_expansions=1))['status'],'SEARCH_LIMIT')
        req = request(nodes=[node('a',safe=[[0,1]]),node('d')],
                      edges=[edge('ad','a','d',1)],max_expansions=2)
        self.assertEqual(self.search(req)['status'],'FEASIBLE')
        req['edges'][0]['closed'] = [[0,8]]
        req['max_expansions'] = 1
        self.assertEqual(self.search(req)['status'],'UNREACHABLE_UNDER_MODEL')
        req = request(nodes=[node('a',safe=[[0,1]]),node('b'),node('d')],
                      edges=[edge('ad','a','d',1),edge('ab','a','b',2),edge('bd','b','d',1)],
                      alternatives=3,max_expansions=2)
        result = self.search(req)
        self.assertEqual(result['status'],'SEARCH_LIMIT')
        self.assertEqual(len(result['candidates']),1)
        self.assertFalse(result['alternatives_complete'])

    def test_three_real_alternatives_and_wait_dedup(self):
        req = request(nodes=[node('a'),node('b'),node('c'),node('d')],
                      edges=[edge('ad','a','d',2),edge('ab','a','b',1),edge('bd','b','d',2),
                             edge('ac','a','c',2),edge('cd','c','d',2)],alternatives=3)
        result = self.search(req)
        self.assertEqual(result['status'],'FEASIBLE')
        self.assertEqual([c['completion'] for c in result['candidates']],[2,3,4])
        self.assertEqual(len({tuple(c['edge_sequence']) for c in result['candidates']}),3)
        req = request(alternatives=3,deadline=3)
        result = self.search(req)
        self.assertEqual(len(result['candidates']),1)
        self.assertTrue(result['alternatives_complete'])

    def test_empty_sequence_at_destination(self):
        req = request(anchor=dict(kind='node',node='d'),service_duration=1)
        candidate = self.candidate(req)
        self.assertEqual(candidate['edge_sequence'],[])
        self.assertEqual(candidate['completion'],1)

    def test_capacity_is_pure_and_own_reservation_not_added_twice(self):
        req = request()
        before = copy.deepcopy(req)
        first = self.search(req)
        self.assertEqual(first['status'],'FEASIBLE')
        self.assertEqual(first,self.search(req))
        self.assertEqual(req,before)
        for key in ['free_bus_seats_excluding_own_pickup_reservation',
                    'free_destination_slots_excluding_own_reservation']:
            bad = copy.deepcopy(req)
            bad['resources'][key] -= 1
            result = self.search(bad)
            self.assertEqual(result['status'],'RESOURCE_UNAVAILABLE')
            self.assertEqual(result['commitments'],bad['commitments'])

    def test_stale_and_corrupt_dispatch_revalidation(self):
        req = request()
        candidate = self.candidate(req)
        self.assertEqual(SOLVER.revalidate(candidate,req)['status'],'VALIDATED_PROPOSAL')
        for field in ['now','deadline','buffer','destination','graph_version','max_expansions']:
            current = copy.deepcopy(req)
            if field == 'destination':
                current['destination']='a'
                current['commitments']['destination_id']='a'
            elif field == 'graph_version': current[field]='different'
            else: current[field]+=1
            self.assertEqual(SOLVER.revalidate(candidate,current)['status'],'REPLAN_REQUIRED')
        for section,key,value in [('knowledge','version','k2'),('resources','version','r2'),
                                  ('resources','free_bus_seats_excluding_own_pickup_reservation',5),
                                  ('commitments','onboard',2),('anchor','node','d')]:
            current = copy.deepcopy(req)
            current[section][key]=value
            self.assertEqual(SOLVER.revalidate(candidate,current)['status'],'REPLAN_REQUIRED')
        current = copy.deepcopy(req)
        current['edges'][0]['duration']=3
        self.assertEqual(SOLVER.revalidate(candidate,current)['status'],'REPLAN_REQUIRED')
        corrupt = copy.deepcopy(candidate)
        corrupt['actions'][0]['end']+=1
        self.assertEqual(SOLVER.revalidate(corrupt,req)['status'],'REJECTED')

    def test_reject_fractional_bool_malformed_and_destination_mismatch(self):
        for field,value in [('now',True),('buffer',0.5),('max_expansions',0),('alternatives',4)]:
            self.assertEqual(self.search(request(**{field:value}))['status'],'INVALID_INPUT')
        for edit in ['duration','interval','duplicate','destination','missing']:
            req = request()
            if edit=='duration': req['edges'][0]['duration']=0
            if edit=='interval': req['nodes'][0]['safe']=[[1,1]]
            if edit=='duplicate': req['nodes'].append(node('a'))
            if edit=='destination': req['commitments']['destination_id']='a'
            if edit=='missing': del req['edges'][0]['known']
            self.assertEqual(self.search(req)['status'],'INVALID_INPUT')

    def test_independent_exhaustive_grid_and_reference_bounds(self):
        self.assertIsNotNone(ORACLE,'independent tiny-time reference is absent')
        comparisons = 0
        for closed_end in range(4):
            for duration in [1,2]:
                for gap in [False,True]:
                    for buffer in [0,1]:
                        req = request(nodes=[node('a',safe=[[0,1],[2,8]] if gap else None),
                                              node('b'),node('d')],
                            edges=[edge('ab','a','b',duration,closed=[[0,closed_end]] if closed_end else []),
                                   edge('bd','b','d',1),edge('ad','a','d',3)],
                            alternatives=3,buffer=buffer,deadline=6)
                        expected = ORACLE.enumerate_reference(req)
                        result = self.search(req)
                        self.assertEqual(result['status'],'FEASIBLE')
                        routes = expected['routes']
                        actual = result['candidates']
                        self.assertEqual(len(actual),min(3,len(routes)))
                        ranked = sorted(r['completion'] for r in routes)
                        self.assertEqual([c['completion'] for c in actual],ranked[:3])
                        per_route={tuple(r['edge_sequence']):r['completion'] for r in routes}
                        for candidate in actual:
                            self.assertEqual(candidate['completion'],per_route[tuple(candidate['edge_sequence'])])
                            self.assertTrue(ORACLE.check_candidate(req,candidate))
                        comparisons+=1
        self.assertEqual(comparisons,32)
        req=request()
        req['knowledge']['valid_until']=14
        with self.assertRaises(ORACLE.ReferenceLimit):
            ORACLE.enumerate_reference(req)
        with self.assertRaises(ORACLE.ReferenceLimit):
            ORACLE.enumerate_reference(request(),max_prefixes=1)
        print('Independent authored grid comparisons:',comparisons)

    def test_revalidation_strict_numeric_types_and_malformed_candidate(self):
        req = request()
        candidate = self.candidate(req)
        for key in ['action_end_float', 'completion_float', 'malformed_none', 'one_tick_bool']:
            with self.subTest(key=key):
                bad = copy.deepcopy(candidate)
                current = req
                if key == 'action_end_float':
                    bad['actions'][0]['end'] = float(bad['actions'][0]['end'])
                if key == 'completion_float':
                    bad['completion'] = float(bad['completion'])
                if key == 'malformed_none':
                    bad = None
                if key == 'one_tick_bool':
                    current = request(edges=[edge('ad','a','d',1)])
                    bad = self.candidate(current)
                    bad['actions'][0]['end'] = True
                    bad['completion'] = True
                self.assertEqual(SOLVER.revalidate(bad,current)['status'],'REJECTED')

    def test_reference_rejects_unsupported_inputs_independently(self):
        self.assertIsNotNone(ORACLE)
        for case in ['negative_buffer','negative_service','bool_horizon','float_known','float_capacity']:
            with self.subTest(case=case):
                req=request(anchor=dict(kind='node',node='d'))
                if case=='negative_buffer': req['buffer']=-1
                if case=='negative_service': req['service_duration']=-1
                if case=='bool_horizon': req['knowledge']['valid_from']=True
                if case=='float_known': req['nodes'][1]['known']=[[0,8.0]]
                if case=='float_capacity': req['resources']['free_destination_slots_excluding_own_reservation']=7.0
                with self.assertRaises(ValueError):
                    ORACLE.enumerate_reference(req)

    def test_independent_checker_rejects_delayed_service_pin_and_numeric_corruption(self):
        req=request(anchor=dict(kind='node',node='d'),
                    edges=[edge('ad','a','d',2),edge('da','d','a',1)])
        candidate=self.candidate(req)
        self.assertTrue(ORACLE.check_candidate(req,candidate))
        for case in ['delayed_wait','leave_return','wrong_pin','float_completion']:
            with self.subTest(case=case):
                bad=copy.deepcopy(candidate)
                if case=='delayed_wait':
                    bad['actions']=[dict(kind='WAIT',node='d',start=0,end=1),
                                    dict(kind='SERVICE',node='d',start=1,end=1)]
                    bad['arrival']=bad['completion']=1
                if case=='leave_return':
                    bad['actions']=[dict(kind='TRAVERSE',edge='da',source='d',target='a',start=0,end=1),
                                    dict(kind='TRAVERSE',edge='ad',source='a',target='d',start=1,end=3),
                                    dict(kind='SERVICE',node='d',start=3,end=3)]
                    bad['edge_sequence']=['da','ad']
                    bad['arrival']=bad['completion']=3
                if case=='wrong_pin': bad['request_sha256']='0'*64
                if case=='float_completion': bad['completion']=float(bad['completion'])
                self.assertFalse(ORACLE.check_candidate(req,bad))

    def test_independent_continuation_metadata_rejects_float_and_bool(self):
        req=self.underway()
        candidate=self.candidate(req)
        self.assertTrue(ORACLE.check_candidate(req,candidate))
        for field,value in [('entered_at',False),('duration_at_entry',3.0),('elapsed_at_start',True)]:
            with self.subTest(field=field):
                bad=copy.deepcopy(candidate)
                bad['actions'][0][field]=value
                self.assertFalse(ORACLE.check_candidate(req,bad))


if __name__=='__main__':
    unittest.main(verbosity=2)