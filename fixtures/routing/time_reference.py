"""Independent exhaustive tiny-grid TRAINING oracle; no solver imports/helpers."""
import copy
import hashlib
import json


class ReferenceLimit(ValueError):
    pass



def encoding(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),
                      ensure_ascii=False,allow_nan=False).encode('utf8')


def require(condition,message):
    if not condition:
        raise ValueError(message)


def quantity(value,minimum=0,maximum=None):
    require(type(value) is int and value>=minimum
            and (maximum is None or value<=maximum),'exact nonnegative bounded integer required')


def name(value):
    require(type(value) is str and 0<len(value)<=128,'nonempty bounded identifier required')


def periods(value):
    require(type(value) is list,'interval list required')
    last=-1
    for pair in value:
        require(type(pair) is list and len(pair)==2,'interval pair required')
        for endpoint in pair:
            quantity(endpoint)
        require(pair[0]<pair[1] and pair[0]>=last,'nonempty sorted disjoint intervals required')
        last=pair[1]


def reference_validate(req):
    # Independently written schema guard, never calls the implementation.
    try:
        require(type(req) is dict and req['schema']=='routing.training.time.v1'
                and req['mode']=='TRAINING','TRAINING schema required')
        require(len(encoding(req))<=1024**2,'request bound')
        for field in ('request_id','trip_id','graph_version','destination'):
            name(req[field])
        for field in ('now','deadline','buffer','service_duration'):
            quantity(req[field])
        quantity(req['alternatives'],1,3)
        quantity(req['max_expansions'],1,100000)
        k,r,c,a=req['knowledge'],req['resources'],req['commitments'],req['anchor']
        for obj in (k,r,c,a):
            require(type(obj) is dict,'object required')
        name(k['version'])
        quantity(k['valid_from'])
        quantity(k['valid_until'])
        require(0<k['valid_until']-k['valid_from']<=3600,'knowledge window bound')
        name(r['version'])
        for field in ('free_bus_seats_excluding_own_pickup_reservation',
                      'free_destination_slots_excluding_own_reservation'):
            quantity(r[field])
        for field in ('onboard','pickup'):
            quantity(c[field])
        if c['reservation_id'] is not None:
            name(c['reservation_id'])
        c['opaque']
        require(c['destination_id']==req['destination'],'destination commitment mismatch')
        require(type(req['nodes']) is list and type(req['edges']) is list,'graph lists required')
        require(1<=len(req['nodes'])<=64 and len(req['edges'])<=256,'training graph bound')
        nodes,edges={},{}
        for node in req['nodes']:
            name(node['id'])
            require(node['id'] not in nodes,'duplicate node')
            periods(node['known'])
            periods(node['safe'])
            nodes[node['id']]=node
        require(req['destination'] in nodes,'destination node required')
        for edge in req['edges']:
            name(edge['id'])
            require(edge['id'] not in edges,'duplicate edge')
            for field in ('source','target'):
                name(edge[field])
                require(edge[field] in nodes,'edge endpoint required')
            quantity(edge['duration'],1)
            require(edge['access'] in ('ALLOWED','DENIED','UNKNOWN'),'access tag required')
            periods(edge['known'])
            periods(edge['closed'])
            edges[edge['id']]=edge
        if a['kind']=='node':
            require(a['node'] in nodes,'anchor node required')
        elif a['kind']=='edge':
            require(a['edge'] in edges,'anchor edge required')
            quantity(a['entered_at'])
            quantity(a['duration_at_entry'],1)
            name(a['source_at_entry'])
            name(a['target_at_entry'])
            require(a['entered_at']<=req['now']<a['entered_at']+a['duration_at_entry'],
                    'committed progress inconsistent')
        else:
            raise ValueError('anchor tag required')
    except (KeyError,TypeError,OverflowError,RecursionError) as error:
        raise ValueError('malformed reference request') from error


def at(periods, tick):
    for start, stop in periods:
        if start <= tick < stop:
            return True
    return False


def span(periods, start, stop):
    # Integer endpoint contract makes checking each occupied tick exact.
    return all(at(periods, tick) for tick in range(start, stop))


def node_ok(node, tick):
    return at(node['known'],tick) and at(node['safe'],tick)


def travel_ok(req, edge, start, stop, nodes):
    return (req['knowledge']['valid_from'] <= start < stop < req['knowledge']['valid_until']
            and stop+req['buffer'] <= req['knowledge']['valid_until']
            and edge['access']=='ALLOWED'
            and span(edge['known'],start,stop+req['buffer'])
            and not any(at(edge['closed'],tick) for tick in range(start,stop+req['buffer']))
            and node_ok(nodes[edge['target']],stop))


def service_ok(req,node,tick):
    completion=tick+req['service_duration']
    stop=completion+req['buffer']
    return (completion<=req['deadline'] and completion<req['knowledge']['valid_until']
            and stop<=req['knowledge']['valid_until']
            and span(node['known'],tick,stop) and span(node['safe'],tick,stop)
            and node_ok(node,completion))


def capacity_ok(req):
    c,r=req['commitments'],req['resources']
    return (c['destination_id']==req['destination']
            and c['pickup']<=r['free_bus_seats_excluding_own_pickup_reservation']
            and c['onboard']+c['pickup']<=r['free_destination_slots_excluding_own_reservation'])


def enumerate_reference(request,max_prefixes=100000):
    reference_validate(request)
    req=copy.deepcopy(request)
    if (type(max_prefixes) is not int or not 1<=max_prefixes<=100000
        or len(req['nodes'])>6 or len(req['edges'])>8
        or req['knowledge']['valid_until']-req['now']>12
        or req['knowledge']['valid_until']<=req['now']):
        raise ReferenceLimit('reference graph/time/prefix bound')
    for key in ('now','deadline','buffer','service_duration'):
        if type(req[key]) is not int:
            raise ValueError('exact integer model required')
    nodes={n['id']:n for n in req['nodes']}
    edges={e['id']:e for e in req['edges']}
    if any(type(e['duration']) is not int or e['duration']<=0 for e in edges.values()):
        raise ValueError('positive integer durations required')
    routes={}
    prefixes=0
    if not capacity_ok(req):
        return dict(routes=[],prefixes=0)
    anchor=req['anchor']
    if anchor['kind']=='edge':
        edge=edges[anchor['edge']]
        tick=anchor['entered_at']+anchor['duration_at_entry']
        if (edge['source'],edge['target'])!=(anchor['source_at_entry'],anchor['target_at_entry']):
            return dict(routes=[],prefixes=0)
        if not travel_ok(req,edge,req['now'],tick,nodes):
            return dict(routes=[],prefixes=0)
        start_node,path=edge['target'],(edge['id'],)
    else:
        start_node,tick,path=anchor['node'],req['now'],()
        if not req['knowledge']['valid_from']<=tick<req['knowledge']['valid_until'] or not node_ok(nodes[start_node],tick):
            return dict(routes=[],prefixes=0)
    def visit(node,tick,path):
        nonlocal prefixes
        prefixes+=1
        if prefixes>max_prefixes:
            raise ReferenceLimit('exhaustive prefix bound; no partial proof')
        if node==req['destination'] and service_ok(req,nodes[node],tick):
            completion=tick+req['service_duration']
            if path not in routes or completion<routes[path]['completion']:
                routes[path]=dict(edge_sequence=list(path),arrival=tick,completion=completion)
            return  # terminal first feasible destination service
        for edge in req['edges']:  # input order, intentionally no priority/label dedupe
            arrival=tick+edge['duration']
            if (edge['source']==node and arrival+req['service_duration']<=req['deadline']
                and travel_ok(req,edge,tick,arrival,nodes)):
                visit(edge['target'],arrival,path+(edge['id'],))
        following=tick+1
        if (following<req['knowledge']['valid_until'] and following+req['service_duration']<=req['deadline']
            and span(nodes[node]['known'],tick,following) and span(nodes[node]['safe'],tick,following)
            and node_ok(nodes[node],following)):
            visit(node,following,path)
    visit(start_node,tick,path)
    return dict(routes=sorted(routes.values(),key=lambda r:(r['completion'],r['edge_sequence'])),
                prefixes=prefixes)


def check_candidate(req,candidate):
    try:
        reference_validate(req)
        if (type(candidate) is not dict or type(candidate.get('arrival')) is not int
            or type(candidate.get('completion')) is not int
            or candidate.get('request_sha256')!=hashlib.sha256(encoding(req)).hexdigest()
            or type(candidate.get('actions')) is not list
            or encoding(candidate.get('anchor'))!=encoding(req['anchor'])
            or encoding(candidate.get('commitments'))!=encoding(req['commitments'])
            or not req['knowledge']['valid_from']<=req['now']<req['knowledge']['valid_until']):
            return False
        if (candidate['mode']!='TRAINING' or candidate['request_id']!=req['request_id']
            or candidate['trip_id']!=req['trip_id'] or candidate['graph_version']!=req['graph_version']
            or candidate['knowledge_version']!=req['knowledge']['version']
            or candidate['resource_version']!=req['resources']['version']
            or candidate['anchor']!=req['anchor'] or candidate['commitments']!=req['commitments']
            or not capacity_ok(req)):
            return False
        nodes={n['id']:n for n in req['nodes']}
        edges={e['id']:e for e in req['edges']}
        anchor=req['anchor']
        tick=req['now']
        node=anchor.get('node')
        path=[]
        serviced=False
        for position,action in enumerate(candidate['actions']):
            if serviced or type(action['start']) is not int or type(action['end']) is not int or action['start']!=tick:
                return False
            kind,stop=action['kind'],action['end']
            if kind=='CONTINUE_EDGE':
                if position!=0 or anchor['kind']!='edge':
                    return False
                if any(type(action.get(field)) is not int for field in
                       ('entered_at','duration_at_entry','elapsed_at_start')):
                    return False
                edge=edges[anchor['edge']]
                if (action['edge']!=anchor['edge'] or action['source']!=anchor['source_at_entry']
                    or action['target']!=anchor['target_at_entry']
                    or edge['source']!=anchor['source_at_entry'] or edge['target']!=anchor['target_at_entry']
                    or stop!=anchor['entered_at']+anchor['duration_at_entry']
                    or action['entered_at']!=anchor['entered_at']
                    or action['duration_at_entry']!=anchor['duration_at_entry']
                    or action['elapsed_at_start']!=req['now']-anchor['entered_at']
                    or not travel_ok(req,edge,tick,stop,nodes)):
                    return False
                node=edge['target']
                path.append(edge['id'])
            else:
                if position==0 and anchor['kind']=='edge':
                    return False
                if node not in nodes or not node_ok(nodes[node],tick):
                    return False
                if node==req['destination'] and service_ok(req,nodes[node],tick) and kind!='SERVICE':
                    return False
                if kind=='WAIT':
                    if (action['node']!=node or stop!=tick+1 or stop>=req['knowledge']['valid_until']
                        or not span(nodes[node]['known'],tick,stop)
                        or not span(nodes[node]['safe'],tick,stop) or not node_ok(nodes[node],stop)):
                        return False
                elif kind=='TRAVERSE':
                    edge=edges[action['edge']]
                    if (edge['source']!=node or action['source']!=node or action['target']!=edge['target']
                        or stop!=tick+edge['duration'] or not travel_ok(req,edge,tick,stop,nodes)):
                        return False
                    node=edge['target']
                    path.append(edge['id'])
                elif kind=='SERVICE':
                    if (node!=req['destination'] or action['node']!=node
                        or stop!=tick+req['service_duration'] or not service_ok(req,nodes[node],tick)
                        or candidate['arrival']!=tick):
                        return False
                    serviced=True
                else:
                    return False
            tick=stop
        return (serviced and candidate['completion']==tick and candidate['edge_sequence']==path
                and tick<=req['deadline'])
    except (KeyError,TypeError,ValueError,OverflowError):
        return False
