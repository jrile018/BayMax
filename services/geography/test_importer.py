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
 def test_unrelated_source_cannot_claim_paradise_coverage(self):
  raw={"elements":[{"type":"node","id":1,"lon":0,"lat":0},{"type":"node","id":2,"lon":.001,"lat":0},{"type":"way","id":3,"nodes":[1,2],"tags":{"highway":"residential"}}]}
  with tempfile.TemporaryDirectory() as td:
   source=Path(td)/"raw.json"; source.write_text(json.dumps(raw))
   with self.assertRaisesRegex(ValueError,"acquisition bbox"):
    ingest(source,td)

 def test_crossing_way_retains_full_geometry(self):
  raw={"elements":[{"type":"node","id":1,"lon":-121.63,"lat":39.75},{"type":"node","id":2,"lon":-121.58,"lat":39.75},{"type":"way","id":3,"nodes":[1,2],"tags":{"highway":"residential"}}]}
  with tempfile.TemporaryDirectory() as td:
   source=Path(td)/"raw.json"; source.write_text(json.dumps(raw))
   ingest(source,td)
   area=json.loads((Path(td)/"area.json").read_text())
   self.assertEqual(area["roads"][0]["geometry_lonlat"],[[-121.63,39.75],[-121.58,39.75]])
   self.assertEqual(area["coverage"][0]["status"],"available")

 def test_declared_source_bbox_must_match_acquisition(self):
  raw={"bounds":{"minlon":0,"minlat":0,"maxlon":1,"maxlat":1},"elements":[{"type":"node","id":1,"lon":-121.607,"lat":39.754},{"type":"node","id":2,"lon":-121.606,"lat":39.754},{"type":"way","id":3,"nodes":[1,2],"tags":{"highway":"residential"}}]}
  with tempfile.TemporaryDirectory() as td:
   source=Path(td)/"raw.json"; source.write_text(json.dumps(raw))
   with self.assertRaisesRegex(ValueError,"declared source bbox"):
    ingest(source,td)

 def test_access_qualifications_and_mode_override(self):
  def edges(extra):
   raw={"elements":[{"type":"node","id":1,"lon":0,"lat":0},{"type":"node","id":2,"lon":.001,"lat":0},{"type":"way","id":3,"nodes":[1,2],"tags":{"highway":"service",**extra}}]}
   return import_osm(raw)[3]["edges"]
  self.assertEqual(edges({"access":"destination"}),[])
  self.assertEqual(edges({"access":"yes","motor_vehicle:conditional":"no @ (Mo-Fr 08:00-18:00)"}),[])
  bus=edges({"access":"no","bus":"yes"})
  self.assertEqual(len(bus),2)
  self.assertFalse(bus[0]["vehicle_access"]["motorcar"])
  self.assertFalse(bus[0]["vehicle_access"]["motor_vehicle"])
  self.assertTrue(bus[0]["vehicle_access"]["bus"])
  self.assertEqual(bus[0]["access_tags"]["access"],"no")
  self.assertEqual(bus[0]["access_tags"]["bus"],"yes")
  self.assertEqual(bus[0]["bus_access_assumption"],"OSM public-service bus")
  destination_bus=edges({"access":"destination","bus":"yes"})
  self.assertTrue(destination_bus[0]["vehicle_access"]["bus"])
  self.assertFalse(destination_bus[0]["vehicle_access"]["motorcar"])
  self.assertEqual(edges({"access":"no","bus":"destination"}),[])
  self.assertEqual(edges({"access":"no","bus:conditional":"yes @ (Mo-Fr)"}),[])
  self.assertTrue(edges({"motor_vehicle":"no","motorcar":"yes"})[0]["vehicle_access"]["motorcar"])
  specific_bus=edges({"access:conditional":"no @ (Mo-Fr 08:00-18:00)","bus":"yes"})
  self.assertTrue(specific_bus[0]["vehicle_access"]["bus"])
  self.assertFalse(specific_bus[0]["vehicle_access"]["motorcar"])
  psv_restricted=edges({"access":"no","motor_vehicle":"yes","psv":"no"})
  self.assertFalse(psv_restricted[0]["vehicle_access"]["bus"])
  self.assertTrue(psv_restricted[0]["vehicle_access"]["motorcar"])
  self.assertEqual(edges({"access":"no","psv":"no"}),[])

 def test_auto_bounds_accepts_declared_bounds_before_padding(self):
  raw={"bounds":[-122.3,37.8,-122.2,37.9],"elements":[
   {"type":"node","id":1,"lon":-122.3,"lat":37.8},
   {"type":"node","id":2,"lon":-122.2,"lat":37.9},
   {"type":"way","id":3,"nodes":[1,2],"tags":{"highway":"residential"}}]}
  with tempfile.TemporaryDirectory() as td:
   source=Path(td)/"raw.json"; source.write_text(json.dumps(raw))
   result=ingest(source,td,area_id="oakland",label="Oakland",auto_bounds=True)
   self.assertEqual(result["roads"],1)
   self.assertEqual(result["coverage_bbox_lonlat"],raw["bounds"])
   self.assertLess(result["bbox_lonlat"][0],raw["bounds"][0])
   xml=b"""<osm version='0.6'><bounds minlon='-122.3' minlat='37.8' maxlon='-122.2' maxlat='37.9'/><node id='1' lon='-122.3' lat='37.8'/><node id='2' lon='-122.2' lat='37.9'/><way id='3'><nd ref='1'/><nd ref='2'/><tag k='highway' v='residential'/></way></osm>"""
   xml_source=Path(td)/"raw.osm"; xml_source.write_bytes(xml)
   xml_result=ingest(xml_source,td,area_id="oakland",label="Oakland",auto_bounds=True)
   self.assertEqual(xml_result["roads"],1)
   self.assertEqual(xml_result["coverage_bbox_lonlat"],raw["bounds"])
   self.assertLess(xml_result["bbox_lonlat"][0],raw["bounds"][0])

 def test_layer_coverage_does_not_count_unrelated_roads(self):
  raw={"elements":[
   {"type":"node","id":1,"lon":0,"lat":0},
   {"type":"node","id":2,"lon":.001,"lat":0},
   {"type":"way","id":3,"nodes":[1,2],"tags":{"highway":"residential"}},
   {"type":"node","id":4,"lon":-121.608,"lat":39.754},
   {"type":"node","id":5,"lon":-121.607,"lat":39.754},
   {"type":"node","id":6,"lon":-121.607,"lat":39.755},
   {"type":"way","id":7,"nodes":[4,5,6,4],"tags":{"building":"yes"}}]}
  with tempfile.TemporaryDirectory() as td:
   source=Path(td)/"raw.json"; source.write_text(json.dumps(raw))
   ingest(source,td)
   area=json.loads((Path(td)/"area.json").read_text())
   coverage={entry["layer"]:entry["status"] for entry in area["coverage"]}
   self.assertEqual(coverage["roads"],"unavailable")
   self.assertEqual(coverage["buildings"],"available")
   self.assertEqual(area["roads"],[])
   self.assertLess(area["bbox_lonlat"][2],-121)
   graph=json.loads((Path(td)/"graph.json").read_text())
   self.assertEqual(graph["edges"],[])
   self.assertEqual(graph["nodes"],[])

 def test_closed_road_outside_bbox_is_not_a_filled_area(self):
  outer=[(-121.63,39.73),(-121.58,39.73),(-121.58,39.78),(-121.63,39.78)]
  nodes=[{"type":"node","id":i,"lon":lon,"lat":lat} for i,(lon,lat) in enumerate(outer,1)]
  ring={"type":"way","id":9,"nodes":[1,2,3,4,1],"tags":{"highway":"residential"}}
  local=[
   {"type":"node","id":5,"lon":-121.608,"lat":39.754},
   {"type":"node","id":6,"lon":-121.607,"lat":39.754},
   {"type":"node","id":7,"lon":-121.607,"lat":39.755},
   {"type":"way","id":10,"nodes":[5,6,7,5],"tags":{"building":"yes"}}]
  with tempfile.TemporaryDirectory() as td:
   source=Path(td)/"raw.json"
   source.write_text(json.dumps({"elements":nodes+[ring]+local}))
   ingest(source,td)
   area=json.loads((Path(td)/"area.json").read_text())
   graph=json.loads((Path(td)/"graph.json").read_text())
   coverage={entry["layer"]:entry["status"] for entry in area["coverage"]}
   self.assertEqual(coverage["roads"],"unavailable")
   self.assertEqual(coverage["buildings"],"available")
   self.assertEqual(area["roads"],[])
   self.assertGreaterEqual(area["bbox_lonlat"][0],-121.621)
   self.assertLessEqual(area["bbox_lonlat"][2],-121.591)
   self.assertEqual(graph["edges"],[])
   self.assertEqual(graph["nodes"],[])
   source.write_text(json.dumps({"elements":nodes+[ring]}))
   with self.assertRaisesRegex(ValueError,"acquisition bbox"):
    ingest(source,td)
   ring["tags"]={"waterway":"stream"}
   source.write_text(json.dumps({"elements":nodes+[ring]}))
   with self.assertRaisesRegex(ValueError,"acquisition bbox"):
    ingest(source,td)
   ring["tags"]={"landuse":"forest"}
   source.write_text(json.dumps({"elements":nodes+[ring]}))
   ingest(source,td)
   area=json.loads((Path(td)/"area.json").read_text())
   self.assertEqual(area["coverage"][2]["status"],"available")

 def test_committed_paradise_graph_uses_current_access_policy(self):
  root=Path(__file__).resolve().parents[2]
  source=root/"fixtures/geography/paradise/raw.osm"
  expected=json.loads((root/"fixtures/geography/paradise/graph.json").read_text())
  with tempfile.TemporaryDirectory() as td:
   ingest(source,td)
   actual=json.loads((Path(td)/"graph.json").read_text())
  self.assertEqual(actual["source_sha256"],expected["source_sha256"])
  self.assertEqual({e["id"] for e in actual["edges"]},{e["id"] for e in expected["edges"]})
  self.assertEqual({e["id"]:e["vehicle_access"] for e in actual["edges"]},{e["id"]:e["vehicle_access"] for e in expected["edges"]})
  self.assertEqual(actual,expected)

if __name__=="__main__": unittest.main()
