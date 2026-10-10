import unittest
import hashlib, json, tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from services.geography.ingest import ingest
from services.geography.importer import project,unproject,import_osm
class ImportTests(unittest.TestCase):
 def test_projection_roundtrip_and_invalid(self):
  p=[-121.608,39.755]; o=(-121.607,39.754)
  q=unproject(*project(*p,o),o); self.assertAlmostEqual(q[0],p[0],places=8); self.assertAlmostEqual(q[1],p[1],places=8)
  with self.assertRaises(ValueError): project(181,0,o)
 def test_directed_oneway_and_speed_assumption(self):
  d={"elements":[{"type":"node","id":1,"lon":-121.607,"lat":39.754},{"type":"node","id":2,"lon":-121.606,"lat":39.754},{"type":"way","id":9,"nodes":[1,2],"tags":{"highway":"residential"}},{"type":"way","id":10,"nodes":[1,2],"tags":{"highway":"primary","oneway":"yes"}}]}
  e=import_osm(d)[3]["edges"]
  self.assertEqual({x["id"] for x in e if x["way_id"]=="9"},{"9/0/fwd","9/0/rev"})
  self.assertEqual({x["id"] for x in e if x["way_id"]=="10"},{"10/0/fwd"})
  self.assertTrue(all(x["length_m"]>0 and x["travel_time_s"]>0 for x in e))
  self.assertIn("assumed",next(x for x in e if x["way_id"]=="9")["speed_assumption"])
 def test_speed_units_and_bad_speed_fallback(self):
  def edge(tags):
   d={"elements":[{"type":"node","id":1,"lon":0,"lat":0},{"type":"node","id":2,"lon":.001,"lat":0},{"type":"way","id":5,"nodes":[1,2],"tags":{"highway":"residential",**tags}}]}
   return import_osm(d)[3]["edges"][0]
  self.assertAlmostEqual(edge({"maxspeed":"36 km/h"})["speed_mps"],10)
  self.assertAlmostEqual(edge({"maxspeed":"25 mph"})["speed_mps"],11.176)
  self.assertAlmostEqual(edge({"highway":"residential"})["speed_mps"],8.3)
  self.assertAlmostEqual(edge({"maxspeed":"0 mph"})["speed_mps"],8.3)
 def test_missing_way_node_is_not_bridged(self):
  d={"elements":[{"type":"node","id":1,"lon":0,"lat":0},{"type":"node","id":3,"lon":.002,"lat":0},{"type":"way","id":6,"nodes":[1,2,3],"tags":{"highway":"residential"}}]}
  self.assertEqual(import_osm(d)[3]["edges"],[])
 def test_footways_and_per_vehicle_access(self):
  def edges(tags):
   d={"elements":[{"type":"node","id":1,"lon":0,"lat":0},{"type":"node","id":2,"lon":.001,"lat":0},{"type":"way","id":7,"nodes":[1,2],"tags":tags}]}
   return import_osm(d)[3]["edges"]
  self.assertEqual(edges({"highway":"footway"}),[])
  e=edges({"highway":"service","motor_vehicle":"yes","bus":"no","hgv":"yes"})
  self.assertTrue(e[0]["vehicle_access"]["motor_vehicle"])
  self.assertFalse(e[0]["vehicle_access"]["bus"])
  self.assertTrue(e[0]["vehicle_access"]["hgv"])
 def test_projection_rejects_invalid_origin_and_nonfinite(self):
  for origin in [(0,90),(181,0),(0,float("nan"))]:
   with self.assertRaises(ValueError): project(0,0,origin)
  with self.assertRaises(ValueError): unproject(float("inf"),0,(0,0))
 def test_ingest_writes_source_provenance_and_shapes(self):
  raw={"osm3s":{"timestamp_osm_base":"2026-10-10T06:00:00Z"},"elements":[
   {"type":"node","id":1,"lon":-121.607,"lat":39.754},
   {"type":"node","id":2,"lon":-121.606,"lat":39.754},
   {"type":"way","id":11,"nodes":[1,2],"tags":{"highway":"residential","maxspeed":"36 km/h"}},
   {"type":"way","id":12,"nodes":[1,2,1],"tags":{"building":"yes"}}]}
  with tempfile.TemporaryDirectory() as td:
   source=Path(td)/"raw.json"; source.write_text(json.dumps(raw))
   result=ingest(source,td,downloaded_at_utc="2026-10-10T07:00:00Z")
   area=json.loads((Path(td)/"area.json").read_text()); graph=json.loads((Path(td)/"graph.json").read_text()); manifest=json.loads((Path(td)/"source_manifest.json").read_text())
   self.assertEqual((result["roads"],result["buildings"],result["edges"]),(1,1,2))
   self.assertEqual(area["coverage"][0]["status"],"available")
   self.assertEqual(area["roads"][0]["geometry_lonlat"][0],[-121.607,39.754])
   self.assertIn("metric_crs",graph); self.assertEqual(manifest["raw_sha256"],hashlib.sha256(source.read_bytes()).hexdigest())
   self.assertEqual(manifest["source_observed_at"],"2026-10-10T06:00:00Z"); self.assertTrue(manifest["query_sha256"]); self.assertIn("ODbL",manifest["license"])
 def test_vehicle_restriction(self):
  d={"elements":[{"type":"node","id":1,"lon":0,"lat":0},{"type":"node","id":2,"lon":.001,"lat":0},{"type":"way","id":4,"nodes":[1,2],"tags":{"highway":"service","access":"no"}}]}
  self.assertEqual(import_osm(d)[3]["edges"],[])
if __name__=="__main__": unittest.main()
