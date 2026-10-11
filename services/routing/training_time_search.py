"""Pure bounded, integer-second TRAINING proposals; never dispatch or book capacity."""
import copy
import hashlib
import heapq
import itertools
import json


SCHEMA = 'routing.training.time.v1'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def integer(value, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError('noninteger/out-of-bounds quantity')
    return value


def identifier(value):
    if type(value) is not str or not value or len(value) > 128:
        raise ValueError('invalid identifier')
    return value


def intervals(value):
    if type(value) is not list:
        raise ValueError('intervals must be lists')
    previous = -1
    for pair in value:
        if type(pair) is not list or len(pair) != 2:
            raise ValueError('invalid interval pair')
        lo, hi = integer(pair[0]), integer(pair[1])
        if lo >= hi or lo < previous:
            raise ValueError('empty/overlapping/unsorted intervals')
        previous = hi


def contains(periods, tick):
    return any(lo <= tick < hi for lo, hi in periods)


def covers(periods, start, end):
    if end == start:
        return contains(periods, start)
    cursor = start
    for lo, hi in periods:
        if hi <= cursor:
            continue
        if lo > cursor:
            return False
        cursor = hi
        if cursor >= end:
            return True
    return False


def validate(req):
    if type(req) is not dict or req['schema'] != SCHEMA or req['mode'] != 'TRAINING':
        raise ValueError('TRAINING schema required')
    if len(canonical(req)) > 1024**2:
        raise ValueError('request exceeds one MiB')
    for key in ('request_id', 'trip_id', 'graph_version', 'destination'):
        identifier(req[key])
    for key in ('now', 'deadline', 'buffer', 'service_duration'):
        integer(req[key])
    integer(req['alternatives'], 1, 3)
    integer(req['max_expansions'], 1, 100000)
    knowledge, resources, commitments = req['knowledge'], req['resources'], req['commitments']
    identifier(knowledge['version'])
    integer(knowledge['valid_from'])
    integer(knowledge['valid_until'])
    if knowledge['valid_from'] >= knowledge['valid_until']:
        raise ValueError('empty knowledge window')
    identifier(resources['version'])
    for key in ('free_bus_seats_excluding_own_pickup_reservation',
                'free_destination_slots_excluding_own_reservation'):
        integer(resources[key])
    for key in ('onboard', 'pickup'):
        integer(commitments[key])
    if commitments['reservation_id'] is not None:
        identifier(commitments['reservation_id'])
    commitments['opaque']  # required; canonical JSON already checked
    if commitments['destination_id'] != req['destination']:
        raise ValueError('destination commitment mismatch')
    if type(req['nodes']) is not list or type(req['edges']) is not list:
        raise ValueError('node/edge lists required')
    if not req['nodes'] or len(req['nodes']) > 64 or len(req['edges']) > 256:
        raise ValueError('bounded training graph exceeds64nodes/256edges')
    if knowledge['valid_until'] - knowledge['valid_from'] > 3600:
        raise ValueError('bounded training window exceeds3600ticks')
    nodes, edges = {}, {}
    for node in req['nodes']:
        name = identifier(node['id'])
        if name in nodes:
            raise ValueError('duplicate node')
        intervals(node['known'])
        intervals(node['safe'])
        nodes[name] = node
    if req['destination'] not in nodes:
        raise ValueError('missing destination')
    for edge in req['edges']:
        name = identifier(edge['id'])
        if name in edges:
            raise ValueError('duplicate edge')
        for key in ('source', 'target'):
            if identifier(edge[key]) not in nodes:
                raise ValueError('missing edge endpoint')
        integer(edge['duration'], 1)
        if edge['access'] not in ('ALLOWED', 'DENIED', 'UNKNOWN'):
            raise ValueError('unknown access tag')
        intervals(edge['known'])
        intervals(edge['closed'])
        edges[name] = edge
    anchor = req['anchor']
    if anchor['kind'] == 'node':
        if anchor['node'] not in nodes:
            raise ValueError('missing anchor node')
    elif anchor['kind'] == 'edge':
        if anchor['edge'] not in edges:
            raise ValueError('missing committed edge')
        integer(anchor['entered_at'])
        integer(anchor['duration_at_entry'], 1)
        identifier(anchor['source_at_entry'])
        identifier(anchor['target_at_entry'])
        if not anchor['entered_at'] <= req['now'] < anchor['entered_at'] + anchor['duration_at_entry']:
            raise ValueError('anchor progress inconsistent')
    else:
        raise ValueError('unknown anchor tag')
    return nodes, edges


def node_reason(node, tick):
    if not contains(node['known'], tick):
        return 'UNKNOWN_NODE'
    if not contains(node['safe'], tick):
        return 'UNSAFE_NODE'
    return None


def edge_reason(edge, start, end, buffer):
    if edge['access'] != 'ALLOWED':
        return 'UNKNOWN_ACCESS' if edge['access'] == 'UNKNOWN' else 'DENIED_ACCESS'
    if not covers(edge['known'], start, end + buffer):
        return 'UNKNOWN_EDGE'
    if any(lo < end + buffer and hi > start for lo, hi in edge['closed']):
        return 'CLOSED_EDGE'
    return None


def search(request):
    try:
        nodes, edges = validate(request)
        req = copy.deepcopy(request)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as error:
        return dict(schema=SCHEMA, mode='TRAINING', status='INVALID_INPUT',
                    reasons=[str(error)], candidates=[], expansions=0,
                    alternatives_complete=False, anchor=None, commitments=None,
                    continuation=[], model={})
    horizon, first = req['knowledge']['valid_until'], req['knowledge']['valid_from']
    result = dict(schema=SCHEMA, mode='TRAINING', status=None, reasons=[], candidates=[],
                  expansions=0, alternatives_complete=False, anchor=req['anchor'],
                  commitments=req['commitments'], continuation=[],
                  model=dict(tick_seconds=1, valid_from=first, valid_until=horizon,
                             deadline=req['deadline']))
    def finish(status, reason, complete=False):
        result['status'] = status
        result['reasons'] = [reason]
        result['alternatives_complete'] = complete
        return result
    now, buffer, service = req['now'], req['buffer'], req['service_duration']
    anchor = req['anchor']
    prefix, sequence = (), ()
    if anchor['kind'] == 'edge':
        edge = edges[anchor['edge']]
        if (edge['source'], edge['target']) != (anchor['source_at_entry'], anchor['target_at_entry']):
            return finish('STRANDED', 'EDGE_IDENTITY_CHANGED')
        arrival = anchor['entered_at'] + anchor['duration_at_entry']
        reason = ('HORIZON' if not first <= now < horizon or arrival >= horizon
                  or arrival + buffer > horizon else edge_reason(edge, now, arrival, buffer))
        if reason is None:
            reason = node_reason(nodes[edge['target']], arrival)
        if reason:
            return finish('STRANDED', reason)
        action = dict(kind='CONTINUE_EDGE', edge=edge['id'], source=edge['source'],
                      target=edge['target'], start=now, end=arrival,
                      entered_at=anchor['entered_at'], duration_at_entry=anchor['duration_at_entry'],
                      elapsed_at_start=now-anchor['entered_at'])
        prefix, sequence = (action,), (edge['id'],)
        result['continuation'] = [action]
        start_node, start_tick = edge['target'], arrival
    else:
        if not first <= now < horizon:
            return finish('HORIZON_EXPIRED', 'CURRENT_TIME_OUTSIDE_WINDOW')
        start_node, start_tick = anchor['node'], now
        reason = node_reason(nodes[start_node], now)
        if reason:
            return finish('INFORMATION_UNAVAILABLE' if reason.startswith('UNKNOWN') else
                          'UNREACHABLE_UNDER_MODEL', reason)
    resources, commitments = req['resources'], req['commitments']
    if (commitments['pickup'] > resources['free_bus_seats_excluding_own_pickup_reservation']
        or commitments['onboard'] + commitments['pickup'] >
            resources['free_destination_slots_excluding_own_reservation']):
        return finish('RESOURCE_UNAVAILABLE', 'AUTHORED_CAPACITY_SNAPSHOT')
    # Optimistic directed/access reverse distance screens irrelevant uncertainty.
    reverse = {node: [] for node in nodes}
    outgoing = {node: [] for node in nodes}
    for edge in sorted(edges.values(), key=lambda e: e['id']):
        outgoing[edge['source']].append(edge)
        if edge['access'] != 'DENIED':
            reverse[edge['target']].append((edge['source'], edge['duration']))
    distance, pending = {req['destination']: 0}, [(0, req['destination'])]
    while pending:
        cost, node = heapq.heappop(pending)
        if cost != distance[node]:
            continue
        for previous, duration in reverse[node]:
            candidate = cost + duration
            if candidate < distance.get(previous, float('inf')):
                distance[previous] = candidate
                heapq.heappush(pending, (candidate, previous))
    if start_node not in distance or start_tick + distance[start_node] + service > req['deadline']:
        return finish('UNREACHABLE_UNDER_MODEL', 'DIRECTED_ACCESS_DEADLINE_LOWER_BOUND', True)
    serial = itertools.count()
    queue = [(start_tick, next(serial), start_node, sequence, prefix)]
    seen = {(start_node, start_tick, sequence)}
    found, flags = set(), set()
    request_sha = digest(req)
    label_limit = False
    def note(reason):
        if reason and reason.startswith('UNKNOWN'):
            flags.add('UNKNOWN')
    def push(node, tick, path, actions):
        nonlocal label_limit
        label = (node, tick, path)
        if label in seen:
            return
        if len(seen) >= 100000:
            label_limit = True
            return
        seen.add(label)
        heapq.heappush(queue, (tick, next(serial), node, path, actions))
    while queue:
        if result['expansions'] >= req['max_expansions'] or label_limit:
            return finish('SEARCH_LIMIT', 'UNRESOLVED_BOUNDED_FRONTIER')
        tick, _, node, path, actions = heapq.heappop(queue)
        result['expansions'] += 1
        if node == req['destination']:
            completion = tick + service
            valid = False
            if completion <= req['deadline']:
                if completion >= horizon or completion + buffer > horizon:
                    flags.add('HORIZON')
                elif (not covers(nodes[node]['known'], tick, completion+buffer)
                      or not contains(nodes[node]['known'], completion)):
                    flags.add('UNKNOWN')
                elif (covers(nodes[node]['safe'], tick, completion+buffer)
                      and contains(nodes[node]['safe'], completion)):
                    valid = True
            if valid:
                if path not in found:
                    found.add(path)
                    result['candidates'].append(dict(
                        mode='TRAINING', request_id=req['request_id'], trip_id=req['trip_id'],
                        graph_version=req['graph_version'], knowledge_version=req['knowledge']['version'],
                        resource_version=resources['version'], request_sha256=request_sha,
                        anchor=copy.deepcopy(anchor), commitments=copy.deepcopy(commitments),
                        edge_sequence=list(path), arrival=tick, completion=completion,
                        actions=list(actions)+( [dict(kind='SERVICE',node=node,start=tick,end=completion)] )))
                    if len(found) == req['alternatives']:
                        return finish('FEASIBLE', 'REQUESTED_KNOWN_FEASIBLE_ROUTES', True)
                continue  # a journey terminates when destination service can complete
        for edge in outgoing[node]:
            target, arrival = edge['target'], tick + edge['duration']
            if edge['access'] == 'DENIED' or target not in distance:
                continue
            if arrival + distance[target] + service > req['deadline']:
                continue
            if arrival >= horizon or arrival + buffer > horizon:
                flags.add('HORIZON')
                continue
            reason = edge_reason(edge, tick, arrival, buffer)
            if reason is None:
                reason = node_reason(nodes[target], arrival)
            if reason:
                note(reason)
                continue
            action = dict(kind='TRAVERSE',edge=edge['id'],source=node,target=target,start=tick,end=arrival)
            push(target, arrival, path+(edge['id'],), actions+(action,))
        following = tick + 1
        if following < horizon and following + distance[node] + service <= req['deadline']:
            if not covers(nodes[node]['known'], tick, following) or not contains(nodes[node]['known'], following):
                flags.add('UNKNOWN')
            elif covers(nodes[node]['safe'], tick, following) and contains(nodes[node]['safe'], following):
                push(node, following, path, actions+(dict(kind='WAIT',node=node,start=tick,end=following),))
    if label_limit:
        return finish('SEARCH_LIMIT', 'LABEL_CAP')
    if found:
        return finish('FEASIBLE', 'BOUNDED_KNOWN_FRONTIER_EXHAUSTED', True)
    if 'UNKNOWN' in flags:
        return finish('INFORMATION_UNAVAILABLE', 'RELEVANT_UNKNOWN_FRONTIER', True)
    if 'HORIZON' in flags:
        return finish('HORIZON_EXPIRED', 'RELEVANT_HORIZON_FRONTIER', True)
    return finish('UNREACHABLE_UNDER_MODEL', 'BOUNDED_FRONTIER_EXHAUSTED', True)


def revalidate(candidate, current_request):
    try:
        validate(current_request)
        if (type(candidate) is not dict or type(candidate.get('request_sha256')) is not str
            or len(candidate['request_sha256']) != 64
            or any(c not in '0123456789abcdef' for c in candidate['request_sha256'])):
            return dict(status='REJECTED', reasons=['MALFORMED_CANDIDATE'])
        encoded = canonical(candidate)
        if candidate['request_sha256'] != digest(current_request):
            return dict(status='REPLAN_REQUIRED', reasons=['REQUEST_IDENTITY_CHANGED'])
        regenerated = search(current_request)
        if any(encoded == canonical(proposal) for proposal in regenerated['candidates']):
            return dict(status='VALIDATED_PROPOSAL', reasons=['PURE_PROPOSAL_ONLY_OWNER_COMMIT_REQUIRED'])
        return dict(status='REJECTED', reasons=['CANDIDATE_NOT_REPRODUCIBLE'])
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as error:
        return dict(status='REJECTED', reasons=[str(error)])
