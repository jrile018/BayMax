"""Build area/graph fixtures from bounded Overpass JSON or OSM XML/bz2 input."""
import argparse, bz2, hashlib, json, math, re, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from .importer import import_osm

PARADISE_BBOX=[-121.621,39.742,-121.591,39.765]
PARADISE_ORIGIN=[-121.607,39.754]
ENDPOINT="https://overpass-api.de/api/interpreter"
ATTRIBUTION="© OpenStreetMap contributors"
ODBL_URL="https://www.openstreetmap.org/copyright"
MAX_SOURCE_BYTES=8*1024*1024

def sha256_bytes(data): return hashlib.sha256(data).hexdigest()
def sha256(path): return sha256_bytes(Path(path).read_bytes())
def _bounded_decompress(data):
    dec=bz2.BZ2Decompressor()
    out=dec.decompress(data,max_length=MAX_SOURCE_BYTES+1)
    if len(out)>MAX_SOURCE_BYTES or not dec.eof: raise ValueError("bzip2 source exceeds 8 MiB decompressed limit or is truncated")
    return out

def parse_osm_xml(payload):
    if len(payload)>MAX_SOURCE_BYTES: raise ValueError("OSM XML exceeds 8 MiB limit")
    if re.search(br"<!\s*(DOCTYPE|ENTITY)",payload,re.I): raise ValueError("DTD/entity declarations are not accepted")
    try: root=ET.fromstring(payload)
    except ET.ParseError as exc: raise ValueError(f"malformed OSM XML: {exc}") from exc
    if root.tag!="osm": raise ValueError("expected <osm> root")
    nodes=[]; ways=[]; timestamps=[]; declared_bounds=None
    bounds_element=root.find("bounds")
    if bounds_element is not None:
        try:
            declared_bounds=[float(bounds_element.attrib[k]) for k in ("minlon","minlat","maxlon","maxlat")]
        except (KeyError,ValueError) as exc: raise ValueError("invalid declared source bbox") from exc
    for elem in root:
        if elem.tag=="node":
            if "id" not in elem.attrib or "lon" not in elem.attrib or "lat" not in elem.attrib: raise ValueError("OSM node missing id/lon/lat")
            try: ident=int(elem.attrib["id"]); lon=float(elem.attrib["lon"]); lat=float(elem.attrib["lat"])
            except ValueError as exc: raise ValueError("invalid OSM node id or coordinate") from exc
            if not math.isfinite(lon) or not math.isfinite(lat) or not -180<=lon<=180 or not -90<=lat<=90: raise ValueError("OSM node coordinate outside WGS84")
            nodes.append({"type":"node","id":ident,"lon":lon,"lat":lat})
            if elem.get("timestamp"): timestamps.append(elem.get("timestamp"))
        elif elem.tag=="way":
            if "id" not in elem.attrib: raise ValueError("OSM way missing id")
            try: ident=int(elem.attrib["id"])
            except ValueError as exc: raise ValueError("invalid OSM way id") from exc
            refs=[]; tags={}
            for child in elem:
                if child.tag=="nd":
                    if "ref" not in child.attrib: raise ValueError("OSM way node reference missing ref")
                    try: refs.append(int(child.attrib["ref"]))
                    except ValueError as exc: raise ValueError("invalid OSM way node reference") from exc
                elif child.tag=="tag" and "k" in child.attrib and "v" in child.attrib: tags[child.attrib["k"]]=child.attrib["v"]
            ways.append({"type":"way","id":ident,"nodes":refs,"tags":tags})
            if elem.get("timestamp"): timestamps.append(elem.get("timestamp"))
    if not nodes and not ways: raise ValueError("OSM XML contains no nodes or ways")
    node_ids={n["id"] for n in nodes}
    for way in ways:
        if any(ref not in node_ids for ref in way["nodes"]): raise ValueError(f"OSM way {way['id']} references a missing node")
    return {"elements":nodes+ways,"source_timestamps":timestamps,**({"bounds":declared_bounds} if declared_bounds is not None else {})}

def _feature_extent(roads,buildings,landuse):
    coords=[]
    for feature in roads+buildings+landuse:
        coords.extend(feature.get("geometry_lonlat",[]))
    if not coords: return None
    return [min(p[0] for p in coords),min(p[1] for p in coords),max(p[0] for p in coords),max(p[1] for p in coords)]

def _bbox_contains(outer,inner):
    return outer[0]<=inner[0] and outer[1]<=inner[1] and outer[2]>=inner[2] and outer[3]>=inner[3]

def _declared_bbox(data):
    declared=data.get("bounds",data.get("bbox"))
    if declared is None: return None
    try:
        if isinstance(declared,dict):
            bbox=[float(declared[k]) for k in ("minlon","minlat","maxlon","maxlat")]
        else: bbox=[float(v) for v in declared]
    except (TypeError,ValueError,KeyError) as exc: raise ValueError("invalid declared source bbox") from exc
    if len(bbox)!=4 or not all(math.isfinite(v) for v in bbox) or not -180<=bbox[0]<bbox[2]<=180 or not -90<=bbox[1]<bbox[3]<=90:
        raise ValueError("invalid declared source bbox")
    return bbox

def _point_in_bbox(point,bbox):
    return bbox[0]<=point[0]<=bbox[2] and bbox[1]<=point[1]<=bbox[3]

def _segment_intersects_bbox(a,b,bbox):
    dx=b[0]-a[0]; dy=b[1]-a[1]; low=0.0; high=1.0
    for p,q in ((-dx,a[0]-bbox[0]),(dx,bbox[2]-a[0]),(-dy,a[1]-bbox[1]),(dy,bbox[3]-a[1])):
        if p==0:
            if q<0: return False
            continue
        ratio=q/p
        if p<0: low=max(low,ratio)
        else: high=min(high,ratio)
        if low>high: return False
    return True

def _polygon_contains(point,ring):
    inside=False; x,y=point
    for (x1,y1),(x2,y2) in zip(ring,ring[1:]):
        if (y1>y)!=(y2>y) and x<(x2-x1)*(y-y1)/(y2-y1)+x1: inside=not inside
    return inside

def _feature_intersects_bbox(feature,bbox):
    coords=feature.get("geometry_lonlat",[])
    if any(_point_in_bbox(p,bbox) for p in coords): return True
    if any(_segment_intersects_bbox(a,b,bbox) for a,b in zip(coords,coords[1:])): return True
    return len(coords)>=4 and coords[0]==coords[-1] and _polygon_contains(((bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2),coords)

def _union_bounds(a,b):
    if b is None: return list(a)
    return [min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]

def _auto_bounds(data,pad_degrees=0.001):
    if not 0<=pad_degrees<=0.1: raise ValueError("auto-bounds padding must be between 0 and 0.1 degrees")
    coords=[(e["lon"],e["lat"]) for e in data["elements"] if e.get("type")=="node"]
    if not coords: raise ValueError("cannot derive bounds without valid OSM nodes")
    minlon=min(p[0] for p in coords); maxlon=max(p[0] for p in coords); minlat=min(p[1] for p in coords); maxlat=max(p[1] for p in coords)
    west=max(-180,minlon-pad_degrees); east=min(180,maxlon+pad_degrees); south=max(-90,minlat-pad_degrees); north=min(90,maxlat+pad_degrees)
    if west==east: west=max(-180,west-pad_degrees or 1e-6); east=min(180,east+pad_degrees or 1e-6)
    if south==north: south=max(-90,south-pad_degrees or 1e-6); north=min(90,north+pad_degrees or 1e-6)
    return [west,south,east,north],[(west+east)/2,(south+north)/2]

def _read_data(input_path):
    path=Path(input_path); raw=path.read_bytes()
    if len(raw)>MAX_SOURCE_BYTES: raise ValueError("source file exceeds 8 MiB compressed/raw input limit")
    if path.suffix==".bz2":
        payload=_bounded_decompress(raw); data=parse_osm_xml(payload)
    elif path.suffix==".osm" or path.suffix==".xml":
        payload=raw; data=parse_osm_xml(payload)
    else:
        payload=raw; data=json.loads(raw.decode("utf-8"))
    return data,raw,payload

def ingest(input_path,output_dir,downloaded_at_utc=None,endpoint=ENDPOINT,area_id="paradise-ca",label="Paradise, California",auto_bounds=False,query_file=None,upstream_url=None,upstream_commit=None,upstream_date=None,pad_degrees=0.001):
    raw_path=Path(input_path); out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    data,raw_bytes,payload=_read_data(raw_path)
    if auto_bounds: bbox,origin=_auto_bounds(data,pad_degrees)
    elif area_id=="paradise-ca": bbox,origin=PARADISE_BBOX,PARADISE_ORIGIN
    else: raise ValueError("non-Paradise inputs require --auto-bounds")
    declared_bbox=_declared_bbox(data)
    if declared_bbox is not None and not auto_bounds and not _bbox_contains(declared_bbox,bbox):
        raise ValueError("declared source bbox does not contain acquisition bbox")
    query_hash=sha256(query_file) if query_file else None
    roads,buildings,landuse,graph=import_osm(data,tuple(origin))
    roads=[feature for feature in roads if _feature_intersects_bbox(feature,bbox)]
    buildings=[feature for feature in buildings if _feature_intersects_bbox(feature,bbox)]
    landuse=[feature for feature in landuse if _feature_intersects_bbox(feature,bbox)]
    if not auto_bounds and not (roads or buildings or landuse):
        raise ValueError("source contains no supported geometry intersecting acquisition bbox")
    road_ids={feature["id"] for feature in roads}
    graph["edges"]=[edge for edge in graph["edges"] if edge["way_id"] in road_ids]
    node_ids={str(node_id) for way in data.get("elements",[])
              if way.get("type")=="way" and str(way.get("id")) in road_ids
              for node_id in way.get("nodes",[])}
    graph["nodes"]=[node for node in graph["nodes"] if node["id"] in node_ids]
    osm3s=data.get("osm3s",{}); source_time=osm3s.get("timestamp_osm_base") or osm3s.get("timestamp_areas_base")
    timestamps=data.get("source_timestamps",[])
    if timestamps: source_time={"min":min(timestamps),"max":max(timestamps)}
    if downloaded_at_utc is None: downloaded_at_utc=datetime.now(timezone.utc).isoformat()
    coverage=[{"layer":"roads","status":"available" if roads else "unavailable","detail":f"{len(roads)} OSM highway ways" if roads else "No highway ways returned by source"},
      {"layer":"buildings","status":"available" if buildings else "unavailable","detail":f"{len(buildings)} OSM building ways" if buildings else "No building ways returned by source"},
      {"layer":"landuse","status":"available" if landuse else "unavailable","detail":f"{len(landuse)} OSM landuse/water ways" if landuse else "No landuse/water ways returned by source"},
      {"layer":"terrain","status":"unavailable","detail":"Not included in this OSM extract"},{"layer":"fuels","status":"unavailable","detail":"Not included in this OSM extract"},{"layer":"current_fire","status":"unavailable","detail":"No current fire source acquired"}]
    geometry_bbox=_feature_extent(roads,buildings,landuse)
    viewport_bbox=_union_bounds(bbox,geometry_bbox)
    context_note="OSM API bbox is the requested coverage; ways intersecting that bbox may include full node geometry outside it, which is partial way context rather than complete outside coverage."
    raw_hash=sha256_bytes(raw_bytes); decompressed_hash=sha256_bytes(payload)
    manifest={"source":"OpenStreetMap","endpoint":endpoint,"upstream_fixture_url":upstream_url,"upstream_commit":upstream_commit,"upstream_file_date":upstream_date,"historical_fixture":bool(upstream_date),"downloaded_at_utc":downloaded_at_utc,"source_observed_at":source_time,"raw_file":str(raw_path),"raw_sha256":raw_hash,"decompressed_sha256":decompressed_hash,"query_file":str(query_file) if query_file else None,"query_sha256":query_hash,"coverage_bbox_lonlat":bbox,"source_geometry_bbox_lonlat":geometry_bbox,"geometry_coverage_note":context_note,"license":"ODbL 1.0","license_url":ODBL_URL,"attribution":ATTRIBUTION,"attribution_url":ODBL_URL,"note":"Fixture-derived OSM data is historical and does not represent current mapping." if upstream_url else None}
    if not upstream_url:
        for key in ("upstream_fixture_url","upstream_commit","upstream_file_date","historical_fixture","note"): manifest.pop(key,None)
    area={"area_id":area_id,"label":label,"bbox_lonlat":viewport_bbox,"coverage_bbox_lonlat":bbox,"source_geometry_bbox_lonlat":geometry_bbox,"geometry_coverage_note":context_note,"origin_lonlat":origin,"metric_crs":"local equirectangular metres; origin_lonlat is WGS84 longitude,latitude","coverage":coverage,"source_manifest":"source_manifest.json","roads":roads,"buildings":buildings,"landuse":landuse}
    graph.update({"area_id":area_id,"coverage_bbox_lonlat":bbox,"source_geometry_bbox_lonlat":geometry_bbox,"geometry_coverage_note":context_note,"origin_lonlat":origin,"metric_crs":"local equirectangular metres; origin_lonlat is WGS84 longitude,latitude","source_sha256":raw_hash})
    for name,obj in (("area.json",area),("graph.json",graph),("source_manifest.json",manifest)):
        (out/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return {"roads":len(roads),"buildings":len(buildings),"landuse":len(landuse),"nodes":len(graph["nodes"]),"edges":len(graph["edges"]),"source_sha256":raw_hash,"decompressed_sha256":decompressed_hash,"bbox_lonlat":viewport_bbox,"coverage_bbox_lonlat":bbox,"source_geometry_bbox_lonlat":geometry_bbox}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True); parser.add_argument("--output",required=True); parser.add_argument("--downloaded-at-utc"); parser.add_argument("--endpoint",default=ENDPOINT)
    parser.add_argument("--area-id",default="paradise-ca"); parser.add_argument("--label",default="Paradise, California"); parser.add_argument("--auto-bounds",action="store_true"); parser.add_argument("--pad-degrees",type=float,default=0.001)
    parser.add_argument("--query-file"); parser.add_argument("--upstream-url"); parser.add_argument("--upstream-commit"); parser.add_argument("--upstream-date")
    args=parser.parse_args(); print(json.dumps(ingest(args.input,args.output,args.downloaded_at_utc,args.endpoint,args.area_id,args.label,args.auto_bounds,args.query_file,args.upstream_url,args.upstream_commit,args.upstream_date,args.pad_degrees),sort_keys=True))
if __name__=="__main__": main()
