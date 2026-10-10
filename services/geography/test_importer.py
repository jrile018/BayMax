import unittest
import hashlib, json, tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from services.geography.ingest import ingest, parse_osm_xml, _read_data, _bounded_decompress
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
   result=ingest(source,td,downloaded_at_utc="2026-10-10T07:00:00Z",query_file=Path(__file__).resolve().parents[2]/"fixtures/geography/paradise/query.overpass")
   area=json.loads((Path(td)/"area.json").read_text()); graph=json.loads((Path(td)/"graph.json").read_text()); manifest=json.loads((Path(td)/"source_manifest.json").read_text())
   self.assertEqual((result["roads"],result["buildings"],result["edges"]),(1,1,2))
   self.assertEqual(area["coverage"][0]["status"],"available")
   self.assertEqual(area["roads"][0]["geometry_lonlat"][0],[-121.607,39.754])
   self.assertIn("metric_crs",graph); self.assertEqual(manifest["raw_sha256"],hashlib.sha256(source.read_bytes()).hexdigest())
   self.assertEqual(manifest["source_observed_at"],"2026-10-10T06:00:00Z"); self.assertTrue(manifest["query_sha256"]); self.assertIn("ODbL",manifest["license"])
 def test_osm_xml_parse_and_auto_bounds_ingest(self):
  import bz2
  xml=b"""<osm version='0.6'><node id='1' lon='-122.3' lat='37.8' timestamp='2017-10-14T00:00:00Z'/><node id='2' lon='-122.2' lat='37.9' timestamp='2017-10-14T00:01:00Z'/><way id='3' timestamp='2017-10-14T00:02:00Z'><nd ref='1'/><nd ref='2'/><tag k='highway' v='residential'/></way></osm>"""
  parsed=parse_osm_xml(xml); self.assertEqual(len(parsed["elements"]),3)
  with tempfile.TemporaryDirectory() as td:
   source=Path(td)/"raw.osm.bz2"; source.write_bytes(bz2.compress(xml))
   result=ingest(source,td,area_id="west-oakland",label="West Oakland (historical fixture)",auto_bounds=True,endpoint=None,upstream_url="https://example.test/osm.bz2",upstream_commit="abc123",upstream_date="2017-10-14")
   area=json.loads((Path(td)/"area.json").read_text()); graph=json.loads((Path(td)/"graph.json").read_text()); manifest=json.loads((Path(td)/"source_manifest.json").read_text())
   self.assertEqual(area["area_id"],"west-oakland"); self.assertNotEqual(area["bbox_lonlat"],[-121.621,39.742,-121.591,39.765])
   self.assertEqual(area["origin_lonlat"],[(area["bbox_lonlat"][0]+area["bbox_lonlat"][2])/2,(area["bbox_lonlat"][1]+area["bbox_lonlat"][3])/2])
   self.assertEqual(manifest["source_observed_at"],{"min":"2017-10-14T00:00:00Z","max":"2017-10-14T00:02:00Z"})
   self.assertEqual(manifest["raw_sha256"],hashlib.sha256(source.read_bytes()).hexdigest()); self.assertEqual(manifest["decompressed_sha256"],hashlib.sha256(xml).hexdigest()); self.assertIsNone(manifest["query_file"])
   self.assertEqual(graph["area_id"],"west-oakland"); self.assertEqual(result["edges"],2)
 def test_osm_xml_rejects_empty_malformed_entities_and_missing_refs(self):
  for xml in (b"<osm/>",b"<osm",b"<!DOCTYPE osm [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><osm>&x;</osm>",b"<osm><way id='4'><nd ref='99'/></way></osm>"):
   with self.assertRaises(ValueError): parse_osm_xml(xml)

 def test_osm_bz2_decompression_limit(self):
  import bz2
  with self.assertRaises(ValueError): _bounded_decompress(bz2.compress(b"x"*(8*1024*1024+1)))
 def test_request_coverage_and_full_way_context_bounds_are_distinct(self):
  bbox=[-121.621,39.742,-121.591,39.765]
  raw={"elements":[{"type":"node","id":1,"lon":-121.63,"lat":39.74},{"type":"node","id":2,"lon":-121.60,"lat":39.75},{"type":"way","id":77,"nodes":[1,2],"tags":{"highway":"residential"}}]}
  with tempfile.TemporaryDirectory() as td:
   source=Path(td)/"raw.json"; source.write_text(json.dumps(raw))
   ingest(source,td)
   area=json.loads((Path(td)/"area.json").read_text()); graph=json.loads((Path(td)/"graph.json").read_text()); manifest=json.loads((Path(td)/"source_manifest.json").read_text())
   extent=[-121.63,39.74,-121.60,39.75]
   self.assertEqual(area["coverage_bbox_lonlat"],bbox)
   self.assertEqual(area["source_geometry_bbox_lonlat"],extent)
   self.assertEqual(area["bbox_lonlat"],[-121.63,39.74,bbox[2],bbox[3]])
   self.assertEqual(graph["coverage_bbox_lonlat"],bbox); self.assertEqual(graph["source_geometry_bbox_lonlat"],extent)
   self.assertEqual(manifest["coverage_bbox_lonlat"],bbox); self.assertEqual(manifest["source_geometry_bbox_lonlat"],extent)
   self.assertIn("partial way context",area["geometry_coverage_note"])

 def test_vehicle_restriction(self):
  d={"elements":[{"type":"node","id":1,"lon":0,"lat":0},{"type":"node","id":2,"lon":.001,"lat":0},{"type":"way","id":4,"nodes":[1,2],"tags":{"highway":"service","access":"no"}}]}
  self.assertEqual(import_osm(d)[3]["edges"],[])
if __name__=="__main__": unittest.main()
