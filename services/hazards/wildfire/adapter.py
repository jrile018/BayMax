"""Deterministic training fields with explicit physical-engine unavailability.

Coordinates: x east, y north, row index increases north; origin is lower-left.
All public times are seconds from epoch. No GPU, network or optional imports.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import heapq
import math

NONBURNABLE = frozenset({91, 92, 93, 98, 99})
# These two rate multipliers are training assumptions, not calibrated GR1/GR2 ROS.
FUEL_FACTOR = {101: 1.0, 102: 1.15}
MAX_CELLS = 65536
MAX_FRAMES = 1001
MAX_FRAME_CELL_PRODUCT = 1_000_000
MAX_HORIZON_S = 7 * 86400


def _number(value, name, lower=None, strict=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if lower is not None and (value < lower or (strict and value == lower)):
        raise ValueError(f'{name} is below its permitted bound')
    return float(value)


def _integer(value, name, lower=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < lower:
        raise ValueError(f'{name} must be an integer >= {lower}')
    return value


def _utc(value, name):
    if not isinstance(value, str):
        raise ValueError(f'{name} must be a dated timezone-aware ISO timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{name} must be an ISO timestamp') from exc
    if parsed.tzinfo is None:
        raise ValueError(f'{name} must include timezone')
    return parsed.astimezone(timezone.utc)


def wind_to_pyre(east_m_s, north_m_s):
    """Convert east/north TOWARD vectors to km/h and FROM clockwise-north."""
    east = _number(east_m_s, 'east_m_s')
    north = _number(north_m_s, 'north_m_s')
    speed = math.hypot(east, north) * 3.6
    if not math.isfinite(speed):
        raise ValueError('converted wind speed must remain finite')
    direction = math.degrees(math.atan2(-east, -north)) % 360 if speed else 0.0
    return speed, direction


def validate_config(config):
    """Fail closed on missing/unknown data; training does not establish incidents."""
    if not isinstance(config, dict):
        raise ValueError('config must be a dictionary')
    try:
        if not isinstance(config['scenario_id'], str) or not config['scenario_id']:
            raise ValueError('scenario_id is required')
        if config['scenario_kind'] != 'hypothetical':
            raise ValueError('this uncalibrated adapter accepts hypothetical exercises only')
        _utc(config['epoch_utc'], 'epoch_utc')
        _integer(config['seed'], 'seed')
        grid = config['grid']
        if not isinstance(grid['crs'], str) or not grid['crs'] or grid['crs'].upper() in ('EPSG:4326', 'WGS84'):
            raise ValueError('grid must declare a metric CRS or LOCAL_METRIC origin')
        if len(grid['origin_m']) != 2:
            raise ValueError('origin_m requires [east,north] metres')
        for value in grid['origin_m']:
            _number(value, 'origin_m')
        _number(grid['cell_size_m'], 'cell_size_m', 0, True)
        fuel = grid['fuel_model']
        if not isinstance(fuel, list) or not fuel or not isinstance(fuel[0], list) or not fuel[0]:
            raise ValueError('fuel_model must be a nonempty matrix')
        height, width = len(fuel), len(fuel[0])
        if height * width > MAX_CELLS:
            raise ValueError(f'training grid limit is {MAX_CELLS} cells')
        for name in ('fuel_model', 'slope_rise_run', 'aspect_deg'):
            matrix = grid[name]
            if not isinstance(matrix, list) or len(matrix) != height or any(not isinstance(row,list) or len(row)!=width for row in matrix):
                raise ValueError(f'{name} must match fuel grid shape')
            for row in matrix:
                for value in row:
                    if name == 'fuel_model':
                        _integer(value, name)
                        if value not in NONBURNABLE and value not in FUEL_FACTOR:
                            raise ValueError(f'fuel code {value} unavailable; no global calibrated fuel mapping')
                    elif name == 'slope_rise_run':
                        _number(value, name, 0)
                    else:
                        angle = _number(value, name, 0)
                        if angle >= 360:
                            raise ValueError('aspect is downslope azimuth [0,360) clockwise north')
        weather = config['weather']
        wind_to_pyre(weather['wind_east_m_s'], weather['wind_north_m_s'])
        for name in ('moisture_dead_1hr','moisture_dead_10hr','moisture_dead_100hr','moisture_live_herbaceous','moisture_live_woody'):
            _number(weather[name], name, 0)
        horizon = _number(config['horizon_s'], 'horizon_s', 0, True)
        step = _number(config['output_step_s'], 'output_step_s', 0, True)
        if horizon > MAX_HORIZON_S:
            raise ValueError(f'training horizon limit is {MAX_HORIZON_S} seconds')
        ratio = horizon / step
        if not math.isfinite(ratio) or ratio > MAX_FRAMES - 1:
            raise ValueError(f'output is bounded to {MAX_FRAMES} frames')
        frame_bound = math.ceil(ratio) + 1
        if frame_bound * height * width > MAX_FRAME_CELL_PRODUCT:
            raise ValueError(f'frame-cell output budget is {MAX_FRAME_CELL_PRODUCT}')
        if not isinstance(config['ignitions'],list) or not config['ignitions']:
            raise ValueError('at least one explicit ignition required')
        for ignition in config['ignitions']:
            y=_integer(ignition['row'],'ignition row'); x=_integer(ignition['col'],'ignition col')
            if not (y<height and x<width):
                raise ValueError('ignition outside domain')
            if fuel[y][x] in NONBURNABLE:
                raise ValueError('ignition on nonburnable fuel')
            when=_number(ignition['time_s'],'ignition time',0)
            if when>horizon:
                raise ValueError('ignition outside time horizon')
        ledger=config['source_ledger']
        if not isinstance(ledger,list) or not ledger:
            raise ValueError('dated source ledger required')
        ids=set()
        for source in ledger:
            if not isinstance(source['source_id'],str) or not source['source_id'] or source['source_id'] in ids:
                raise ValueError('source IDs must be unique and nonempty')
            ids.add(source['source_id'])
            if source['kind'] not in ('synthetic','observed','mapped','model_reference'):
                raise ValueError('unknown source kind')
            if not isinstance(source['license'],str) or not source['license']:
                raise ValueError('source license/rights label required')
            retrieved=_utc(source['retrieved_at_utc'],'retrieved_at_utc')
            if source['kind']=='observed' and source.get('observed_at_utc') is None:
                raise ValueError('observed input requires observed timestamp')
            if source.get('observed_at_utc') is not None and _utc(source['observed_at_utc'],'observed_at_utc')>retrieved:
                raise ValueError('observation timestamp cannot be after retrieval')
            if source['kind']!='synthetic' and not source.get('uri'):
                raise ValueError('nonsynthetic input requires source URI')
        engine=config.get('engine','pyretechnics')
        if engine not in ('pyretechnics','training-grid'):
            raise ValueError('unknown engine; no automatic fallback')
        if engine=='training-grid':
            assumptions=config['training_assumptions']
            for name in ('base_rate_m_s','moisture_extinction','residence_time_s'):
                _number(assumptions[name],name,0,True)
            for name in ('wind_gain_per_m_s','slope_gain'):
                _number(assumptions[name],name,0)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f'missing or malformed wildfire input: {exc}') from exc
    return height, width


def _training_arrivals(config,height,width):
    """Eight-neighbour first-arrival graph, not an ignition growth PDE solver."""
    grid=config['grid']; weather=config['weather']; assumptions=config['training_assumptions']
    fuel=grid['fuel_model']; cell=grid['cell_size_m']; horizon=config['horizon_s']
    dry=max(0.0,1-weather['moisture_dead_1hr']/assumptions['moisture_extinction'])
    # Additional moisture attenuation is empirical, explicitly recorded in manifest.
    moisture=math.exp(-.5*(weather['moisture_dead_10hr']+weather['moisture_dead_100hr'])
                      -.1*(weather['moisture_live_herbaceous']+weather['moisture_live_woody']))
    ratescale=assumptions['base_rate_m_s']*dry*moisture
    arrivals=[[math.inf]*width for _ in range(height)]; queue=[]
    for i in config['ignitions']:
        y,x,t=i['row'],i['col'],i['time_s']
        if t<arrivals[y][x]:
            arrivals[y][x]=float(t); heapq.heappush(queue,(float(t),y,x))
    if ratescale==0:
        return [[None if math.isinf(t) else t for t in row] for row in arrivals]
    def rate(y,x,ux,uy):
        if fuel[y][x] in NONBURNABLE:
            return 0.0
        aspect=math.radians(grid['aspect_deg'][y][x])
        uphill=-grid['slope_rise_run'][y][x]*(math.sin(aspect)*ux+math.cos(aspect)*uy)
        exponent=assumptions['wind_gain_per_m_s']*(weather['wind_east_m_s']*ux+weather['wind_north_m_s']*uy)+assumptions['slope_gain']*uphill
        factor=math.exp(max(-math.log(10),min(math.log(10),exponent)))
        return ratescale*FUEL_FACTOR[fuel[y][x]]*factor
    neighbours=[(dy,dx) for dy in (-1,0,1) for dx in (-1,0,1) if (dy,dx)!=(0,0)]
    while queue:
        t,y,x=heapq.heappop(queue)
        if t!=arrivals[y][x]:
            continue
        for dy,dx in neighbours:
            ny,nx=y+dy,x+dx
            if not(0<=ny<height and 0<=nx<width) or fuel[ny][nx] in NONBURNABLE:
                continue
            if dy and dx and (fuel[y][nx] in NONBURNABLE or fuel[ny][x] in NONBURNABLE):
                continue  # No diagonal corner jump over water/urban/bare barriers.
            norm=math.hypot(dx,dy); ux,uy=dx/norm,dy/norm
            r1=rate(y,x,ux,uy); r2=rate(ny,nx,ux,uy)
            if r1<=0 or r2<=0:
                continue
            if not math.isfinite(r1) or not math.isfinite(r2):
                raise ValueError('computed training rate must remain finite')
            candidate=t+cell*norm*.5*(1/r1+1/r2)
            if candidate<=horizon and candidate<arrivals[ny][nx]:
                arrivals[ny][nx]=candidate; heapq.heappush(queue,(candidate,ny,nx))
    return [[None if math.isinf(t) else math.floor(t*1e6)/1e6 for t in row] for row in arrivals]


def simulate(config):
    """Generate an explicit hypothetical training run or an unavailable engine record."""
    height,width=validate_config(config)
    if config.get('engine','pyretechnics')=='pyretechnics':
        return {'status':'unavailable','scenario_id':config['scenario_id'],
                'reason':'Pinned Pyretechnics 2026.8.10 build/import and physical validation are blocked by cloud dependency egress; no physical backend integrated.',
                'requested_engine':'pyretechnics','model_version':'2026.8.10',
                'physical_engine_implemented':False,'current_incident':False,
                'source_ledger':copy.deepcopy(config['source_ledger'])}
    arrivals=_training_arrivals(config,height,width)
    horizon=float(config['horizon_s']); step=float(config['output_step_s'])
    times=[i*step for i in range(math.ceil(horizon/step)) if i*step<horizon]+[horizon]
    cells=[(y,x,t) for y,row in enumerate(arrivals) for x,t in enumerate(row) if t is not None]
    residence=config['training_assumptions']['residence_time_s']
    frames=[{'time_s':t,'burned_cells':[[y,x] for y,x,a in cells if a<=t],
             'active_flame_cells':[[y,x] for y,x,a in cells if a<=t<min(horizon,a+residence)]} for t in times]
    return {'status':'ok','schema_version':'wildfire-output-v1','scenario_id':config['scenario_id'],
            'epoch_utc':config['epoch_utc'],'horizon_s':horizon,
            'units':{'time':'s from epoch','distance':'m','wind':'m/s toward east/north','slope':'rise/run','moisture':'kg/kg dry fuel'},
            'grid':{'crs':config['grid']['crs'],'origin_m':copy.deepcopy(config['grid']['origin_m']),
                    'cell_size_m':config['grid']['cell_size_m'],'height':height,'width':width,'row_axis':'north'},
            'arrivals_s':arrivals,'frames':frames,
            'burn_intervals':[{'row':y,'col':x,'start_s':a,'end_s':horizon} for y,x,a in cells],
            'active_flame_intervals':[{'row':y,'col':x,'start_s':a,'end_s':min(horizon,a+residence)} for y,x,a in cells],
            'provenance':{'model_name':'Simplified deterministic training grid','model_version':'1',
                'physical_engine_implemented':False,'scenario_kind':'hypothetical','current_incident':False,
                'seed':config['seed'],'seed_usage':'recorded; deterministic fields, no stochastic process',
                'source_ledger':copy.deepcopy(config['source_ledger']),
                'training_assumptions':copy.deepcopy(config['training_assumptions']),
                'fuel_rate_factors':dict(FUEL_FACTOR),
                'equation':'R=R0*fuel_factor*max(0,1-M1/Mext)*exp(-0.5*(M10+M100)-0.1*(Mlive_h+Mlive_w))*exp(clamp(kw*(wind dot direction)+ks*uphill,-ln(10),ln(10))); neighbour travel=distance/2*(1/Rsource+1/Rdestination)',
                'limitations':['Uncalibrated synthetic rates; not Rothermel, Pyretechnics or a physical wildfire solver.',
                    '8-neighbour graph has grid-direction and resolution bias; no spotting, crown fire, structures, suppression or atmospheric feedback.',
                    'Constant weather and explicit static fuel/slope/moisture assumptions; no current-incident evidence.',
                    'Null arrival means not reached within this modeled horizon; never safe forever.',
                    'Burn intervals persist to horizon conservatively; active flame residence is a separate assumed interval.']}}


def _segment_hits_box(p0,p1,xmin,ymin,xmax,ymax):
    """Closed-set Liang-Barsky clipping; tangent/boundary contacts count."""
    dx=p1[0]-p0[0]; dy=p1[1]-p0[1]; start,end=0.0,1.0
    for p,q in ((-dx,p0[0]-xmin),(dx,xmax-p0[0]),(-dy,p0[1]-ymin),(dy,ymax-p0[1])):
        if p==0:
            if q<0:return False
        else:
            r=q/p
            if p<0:start=max(start,r)
            else:end=min(end,r)
            if start>end:return False
    return True


def edge_access(hazard,edges,issued_time_s,safety_buffer_s=0):
    """Conservative any-cell polyline intersection; caller publishes as a forecast.

Closure is [first arrival-buffer,horizon). Unknown partial coverage stays unknown;
no arrival generates no closure only within coverage, not an observed safety claim.
"""
    try:
        g=hazard['grid']; width=_integer(g['width'],'width',1); height=_integer(g['height'],'height',1)
        cell=_number(g['cell_size_m'],'cell_size_m',0,True)
        ox,oy=g['origin_m']; ox=_number(ox,'origin east'); oy=_number(oy,'origin north')
        horizon=_number(hazard['horizon_s'],'horizon',0,True)
        issued=_number(issued_time_s,'issued_time_s',0)
        buffer=_number(safety_buffer_s,'safety_buffer_s',0)
        if issued>=horizon:raise ValueError('forecast issue time outside modeled horizon')
        arrivals=hazard['arrivals_s']
        if len(arrivals)!=height or any(len(row)!=width for row in arrivals):raise ValueError('arrival shape differs from grid')
        for row in arrivals:
            for arrival in row:
                if arrival is not None:
                    t=_number(arrival,'arrival',0)
                    if t>horizon:raise ValueError('arrival outside horizon')
        source_ids=[s['source_id'] for s in hazard['provenance']['source_ledger']]
        result=[]; ids=set()
        for edge in edges:
            eid=edge['edge_id']
            if not isinstance(eid,str) or not eid or eid in ids:raise ValueError('edge IDs must be unique nonempty strings')
            ids.add(eid)
            points=edge['geometry_m']
            if not isinstance(points,list) or len(points)<2:raise ValueError('edge requires a metric polyline')
            for point in points:
                if not isinstance(point,(list,tuple)) or len(point)!=2:raise ValueError('polyline point requires east,north')
                for coordinate in point:_number(coordinate,'polyline coordinate')
            outside=any(not(ox<=p[0]<=ox+width*cell and oy<=p[1]<=oy+height*cell) for p in points)
            first=None
            for p0,p1 in zip(points,points[1:]):
                # Include both cells when a segment coincides with a boundary.
                x0=max(0,math.floor((min(p0[0],p1[0])-ox)/cell)-1)
                x1=min(width-1,math.floor((max(p0[0],p1[0])-ox)/cell))
                y0=max(0,math.floor((min(p0[1],p1[1])-oy)/cell)-1)
                y1=min(height-1,math.floor((max(p0[1],p1[1])-oy)/cell))
                for y in range(y0,y1+1):
                    for x in range(x0,x1+1):
                        arrival=arrivals[y][x]
                        if arrival is not None and _segment_hits_box(p0,p1,ox+x*cell,oy+y*cell,ox+(x+1)*cell,oy+(y+1)*cell):
                            first=arrival if first is None else min(first,arrival)
            intervals=[]
            if first is not None and first-buffer<horizon:
                intervals=[{'start_s':max(issued,first-buffer),'end_s':horizon}]
            result.append({'edge_id':eid,'status':'unknown' if outside else 'forecast',
                'issued_time_s':issued,'coverage_start_s':issued,'coverage_end_s':horizon,
                'closed_intervals':intervals,'source_ids':list(source_ids),
                'spatial_rule':'Any closed cell rectangle intersecting any polyline segment; touches included.',
                'reason':'Outside or partially outside modeled grid' if outside else 'Modeled training forecast; no observed road safety certification'})
        return result
    except (KeyError,TypeError,IndexError) as exc:
        raise ValueError(f'missing or malformed hazard/edge input: {exc}') from exc


def current_incident_eligibility(evidence,as_of_utc,location_lonlat,max_age_hours=24):
    """Metadata gate for separately reviewed evidence, not automatic verification.

A passing gate cannot turn hypothetical simulation fields into a current incident.
No feed is ingested by this function. Reviewed evidence must match place and date.
"""
    now=_utc(as_of_utc,'as_of_utc'); max_age=_number(max_age_hours,'max_age_hours',0,True)
    if len(location_lonlat)!=2:raise ValueError('location must be longitude,latitude')
    lon=_number(location_lonlat[0],'longitude'); lat=_number(location_lonlat[1],'latitude')
    if not(-180<=lon<=180 and -90<=lat<=90):raise ValueError('invalid geographic location')
    eligible=[]; reasons=[]
    for record in evidence:
        try:
            observed=_utc(record['observed_at_utc'],'observed_at_utc')
            age=(now-observed).total_seconds()/3600
            bbox=record['bbox_lonlat']
            if len(bbox)!=4:raise ValueError('bbox must have west,south,east,north')
            west,south,east,north=[_number(v,'bbox') for v in bbox]
            valid_bounds=-180<=west<=east<=180 and -90<=south<=north<=90
            qualifies=(record.get('review_status')=='accepted' and record.get('incident_status')=='confirmed_active_wildfire'
                and isinstance(record.get('incident_id'),str) and bool(record['incident_id'])
                and isinstance(record.get('source_uri'),str) and record['source_uri'].startswith('https://')
                and 0<=age<=max_age and valid_bounds and west<=lon<=east and south<=lat<=north)
            if qualifies:eligible.append(copy.deepcopy(record))
            else:reasons.append('Evidence lacks accepted active-wildfire status, matching bounds, source URI or valid freshness')
        except (KeyError,TypeError,ValueError):reasons.append('Malformed or undated incident evidence')
    return {'status':'eligible_reviewed_evidence' if eligible else 'unavailable',
            'as_of_utc':as_of_utc,'evidence':eligible,'max_age_hours_assumption':max_age,
            'reasons':reasons or ([] if eligible else ['No dated accepted incident evidence']),
            'simulation_confirms_current_incident':False}
