"""Stdlib OSM Overpass importer with local equirectangular metric coordinates."""
import math
import re
R=6371008.8
POLAR_EPSILON=1e-12

def _validate_origin(origin):
    try: lon0,lat0=origin
    except (TypeError,ValueError): raise ValueError("origin must be WGS84 (longitude, latitude)")
    if not all(math.isfinite(v) for v in (lon0,lat0)) or not -180<=lon0<=180 or not -90<lat0<90 or abs(math.cos(math.radians(lat0)))<POLAR_EPSILON:
        raise ValueError("invalid WGS84 projection origin")
    return lon0,lat0

def project(lon,lat,origin):
    lon0,lat0=_validate_origin(origin)
    if not all(math.isfinite(v) for v in (lon,lat)) or not -180<=lon<=180 or not -90<=lat<=90:
        raise ValueError("invalid WGS84 longitude/latitude")
    return [math.radians(lon-lon0)*R*math.cos(math.radians(lat0)),math.radians(lat-lat0)*R]

def unproject(x,y,origin):
    lon0,lat0=_validate_origin(origin)
    if not all(math.isfinite(v) for v in (x,y)): raise ValueError("projected coordinates must be finite")
    lat=lat0+math.degrees(y/R); lon=lon0+math.degrees(x/(R*math.cos(math.radians(lat0))))
    if not math.isfinite(lon) or not math.isfinite(lat) or not -180<=lon<=180 or not -90<=lat<=90: raise ValueError("projection outside WGS84")
    return [lon,lat]

def _speed(tags,highway):
    """Return positive m/s and a source/assumption string; OSM maxspeed defaults to km/h."""
    fallback={"motorway":27.8,"trunk":22.2,"primary":16.7,"secondary":13.9,"tertiary":11.1,"residential":8.3,"unclassified":8.3,"service":5.6,"track":4.2}.get(highway,8.3)
    raw=tags.get("maxspeed")
    if raw is not None:
        match=re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(mph|km/?h|kph)?",str(raw),re.I)
        if match:
            n=float(match.group(1)); unit=(match.group(2) or "km/h").lower()
            value=n*(0.44704 if unit=="mph" else 1/3.6)
            if math.isfinite(value) and value>0: return value,f"OSM maxspeed {raw} ({value:g} m/s)"
    # Compatibility with nonstandard feeds that supply maxspeed_kph.
    raw_kph=tags.get("maxspeed_kph")
    if raw_kph is not None:
        try:
            value=float(raw_kph)/3.6
            if math.isfinite(value) and value>0: return value,f"source maxspeed_kph {raw_kph} ({value:g} m/s)"
        except (TypeError,ValueError): pass
    return fallback,f"assumed highway-class speed {fallback:g} m/s" + (f"; invalid maxspeed {raw!r}" if raw is not None else "")

def _yes(value): return str(value).strip().lower() in ("yes","designated","permissive","official","1","true")
def _no(value): return str(value).strip().lower() in ("no","private","0","false")

ACCESS_ORDER={
    "motor_vehicle":("motor_vehicle","vehicle","access"),
    "motorcar":("motorcar","motor_vehicle","vehicle","access"),
    "bus":("bus","psv","motor_vehicle","vehicle","access"),
    "hgv":("hgv","motor_vehicle","vehicle","access"),
}
ACCESS_KEYS={key for order in ACCESS_ORDER.values() for key in order}
ACCESS_KEYS.update(key+":conditional" for key in tuple(ACCESS_KEYS))

def _vehicle_access(tags,highway):
    default=highway not in {"footway","path","cycleway","steps","pedestrian"}
    result={}
    for mode,order in ACCESS_ORDER.items():
        # Resolve the most specific tagged class first. A conditional value
        # at that class cannot establish unrestricted access; broader tags do
        # not override an explicit mode-specific permission.
        result[mode]=default
        for key in order:
            if key+":conditional" in tags:
                result[mode]=False
                break
            if key in tags:
                result[mode]=_yes(tags[key])
                break
    return result

def import_osm(data,origin=(-121.607,39.754)):
    _validate_origin(origin)
    elements=data.get("elements",[])
    nodes={e["id"]:(e["lon"],e["lat"]) for e in elements if e.get("type")=="node" and "lon" in e}
    roads=[]; buildings=[]; landuse=[]; edges=[]; graph_nodes={}
    for w in (e for e in elements if e.get("type")=="way"):
        tags=w.get("tags",{}); ids=w.get("nodes",[])
        complete=bool(ids) and all(n in nodes for n in ids)
        coords=[nodes[n] for n in ids] if complete else []
        if len(coords)<2: continue
        ident=str(w["id"]); metric=[project(lon,lat,origin) for lon,lat in coords]
        if "highway" in tags:
            roads.append({"id":ident,"name":tags.get("name"),"highway":tags["highway"],"geometry_lonlat":coords,"geometry_m":metric})
            vehicle_access=_vehicle_access(tags,tags["highway"])
            access_tags={key:tags[key] for key in ACCESS_KEYS if key in tags}
            access_metadata={"access_tags":access_tags} if access_tags else {}
            if _yes(tags.get("bus")):
                access_metadata["bus_access_assumption"]="OSM public-service bus"
            oneway=str(tags.get("oneway","")).lower() in ("yes","1","true") or tags.get("junction")=="roundabout"
            reverse=str(tags.get("oneway","")).lower() in ("-1","reverse")
            speed,speed_source=_speed(tags,tags["highway"])
            for i,(a,b) in enumerate(zip(coords,coords[1:])):
                na,nb=str(ids[i]),str(ids[i+1])
                graph_nodes[na]={"id":na,"lonlat":a,"geometry_m":project(*a,origin)}
                graph_nodes[nb]={"id":nb,"lonlat":b,"geometry_m":project(*b,origin)}
                ma,mb=project(*a,origin),project(*b,origin); length=math.dist(ma,mb)
                directions=[] if not any(vehicle_access.values()) else ([(nb,na,"rev")] if reverse else [(na,nb,"fwd")]+([] if oneway else [(nb,na,"rev")]))
                for u,v,direction in directions:
                    geom=[mb,ma] if direction=="rev" else [ma,mb]
                    edges.append({"id":f"{ident}/{i}/{direction}","way_id":ident,"segment_index":i,"from_node":u,"to_node":v,"geometry_m":geom,"length_m":length,"travel_time_s":length/speed,"speed_mps":speed,"speed_assumption":speed_source,"vehicle_access":vehicle_access,**access_metadata})
        if str(tags.get("building","")).strip().lower() not in ("","no","0","false"):
            buildings.append({"id":ident,"geometry_lonlat":coords,"geometry_m":metric})
        kind=tags.get("landuse") or ("water" if tags.get("natural")=="water" or "waterway" in tags else None)
        if kind: landuse.append({"id":ident,"kind":kind,"geometry_lonlat":coords})
    return roads,buildings,landuse,{"nodes":list(graph_nodes.values()),"edges":edges}
