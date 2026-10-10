"""Build the Paradise display area and directed road graph from raw Overpass JSON."""
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from .importer import import_osm

BBOX=[-121.621,39.742,-121.591,39.765]
ORIGIN=[-121.607,39.754]
ENDPOINT="https://overpass-api.de/api/interpreter"
ATTRIBUTION="© OpenStreetMap contributors"
ODBL_URL="https://www.openstreetmap.org/copyright"

def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def ingest(input_path, output_dir, downloaded_at_utc=None, endpoint=ENDPOINT):
    raw_path=Path(input_path); out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    data=json.loads(raw_path.read_text(encoding="utf-8"))
    query_path=Path(__file__).resolve().parents[2]/"fixtures/geography/paradise/query.overpass"
    query_hash=sha256(query_path) if query_path.exists() else None
    roads,buildings,landuse,graph=import_osm(data,tuple(ORIGIN))
    osm3s=data.get("osm3s",{})
    source_time=osm3s.get("timestamp_osm_base") or osm3s.get("timestamp_areas_base")
    if downloaded_at_utc is None: downloaded_at_utc=datetime.now(timezone.utc).isoformat()
    road_status="available" if roads else "unavailable"
    coverage=[{"layer":"roads","status":road_status,"detail":f"{len(roads)} OSM highway ways" if roads else "No highway ways returned by source"},
      {"layer":"buildings","status":"available" if buildings else "unavailable","detail":f"{len(buildings)} OSM building ways" if buildings else "No building ways returned by source"},
      {"layer":"landuse","status":"available" if landuse else "unavailable","detail":f"{len(landuse)} OSM landuse/water ways" if landuse else "No landuse/water ways returned by source"},
      {"layer":"terrain","status":"unavailable","detail":"Not included in this OSM extract"},
      {"layer":"fuels","status":"unavailable","detail":"Not included in this OSM extract"},
      {"layer":"current_fire","status":"unavailable","detail":"No current fire source acquired"}]
    raw_hash=sha256(raw_path)
    manifest={"source":"OpenStreetMap","endpoint":endpoint,"downloaded_at_utc":downloaded_at_utc,"source_observed_at":source_time,"raw_file":str(raw_path),"raw_sha256":raw_hash,"query_file":str(query_path),"query_sha256":query_hash,"license":"ODbL 1.0","license_url":ODBL_URL,"attribution":ATTRIBUTION,"attribution_url":ODBL_URL}
    area={"area_id":"paradise-ca","label":"Paradise, California","bbox_lonlat":BBOX,"origin_lonlat":ORIGIN,"metric_crs":"local equirectangular metres; origin_lonlat is WGS84 longitude,latitude","coverage":coverage,"source_manifest":"source_manifest.json","roads":roads,"buildings":buildings,"landuse":landuse}
    graph.update({"area_id":"paradise-ca","origin_lonlat":ORIGIN,"metric_crs":"local equirectangular metres; origin_lonlat is WGS84 longitude,latitude","source_sha256":raw_hash})
    for name,obj in (("area.json",area),("graph.json",graph),("source_manifest.json",manifest)):
        (out/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return {"roads":len(roads),"buildings":len(buildings),"landuse":len(landuse),"nodes":len(graph["nodes"]),"edges":len(graph["edges"]),"source_sha256":raw_hash}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True); parser.add_argument("--output",required=True)
    parser.add_argument("--downloaded-at-utc"); parser.add_argument("--endpoint",default=ENDPOINT)
    args=parser.parse_args(); print(json.dumps(ingest(args.input,args.output,args.downloaded_at_utc,args.endpoint),sort_keys=True))
if __name__=="__main__": main()
