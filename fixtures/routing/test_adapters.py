"""Sourced road metadata and conservative access/coverage conversion."""
import copy
import unittest
from services.routing.adapters import graph_from_geography,safety_from_access
from services.routing import candidate_routes
from services.routing.trip import TripExecutor
from services.planner.ledger import Ledger,Vehicle,Request,Destination

CRS="local equirectangular metres; origin_lonlat is WGS84 longitude,latitude"
ORIGIN=[-121.607,39.754]
BBOX=[-121.621,39.742,-121.591,39.765]
SHA="a"*64

def fixture():
    xy={"A":[0,0],"B":[10,0],"C":[10,10],"D":[20,0],"OUT":[10000,0]}
    geo={"A":ORIGIN,"B":[-121.606883,39.754],
         "C":[-121.606883,39.75409],"D":[-121.606766,39.754],
         "OUT":[-121.49002241778886,39.754]}
    nodes=[dict(id=name,lonlat=geo[name],geometry_m=point) for name,point in xy.items()]
    def edge(eid,a,b,length,duration,access=None):
        return dict(id=eid,way_id=eid.split("/")[0],segment_index=0,
            from_node=a,to_node=b,geometry_m=[xy[a],xy[b]],length_m=length,
            travel_time_s=duration,speed_mps=length/duration,
            speed_assumption="assumed test speed",vehicle_access=access or
            dict(motor_vehicle=True,motorcar=True,bus=True,hgv=True))
    edges=[edge("ab/0/fwd","A","B",10,1),
           edge("bd/0/fwd","B","D",10,1),
           edge("bc/0/fwd","B","C",10,1),
           edge("cd/0/fwd","C","D",14.142135623730951,1.4142135623730951),
           edge("bo/0/fwd","B","OUT",9990,999)]
    payload=dict(nodes=nodes,edges=edges,area_id="paradise-ca",
        coverage_bbox_lonlat=list(BBOX),
        source_geometry_bbox_lonlat=[-121.63,39.72,-121.48,39.80],
        geometry_coverage_note="OSM API bbox is requested coverage; full way may extend outside.",
        origin_lonlat=list(ORIGIN),metric_crs=CRS,source_sha256=SHA)
    manifest=dict(source="OpenStreetMap",downloaded_at_utc="2026-10-10T07:00:45Z",
        raw_sha256=SHA,coverage_bbox_lonlat=list(BBOX),
        source_geometry_bbox_lonlat=payload["source_geometry_bbox_lonlat"],
        license="ODbL 1.0",attribution="© OpenStreetMap contributors")
    return payload,manifest

def alignment(graph):
    return dict(graph_version=graph.version,area_id=graph.area_id,
        metric_crs=graph.metric_crs,origin_lonlat=list(graph.origin_lonlat),
        graph_source_sha256=graph.source_sha256,source_kind="authored_simulated",
        source_id="routing-adapter-test")

def record(eid,*,issued=0,received=0,status="forecast",closed=()):
    return dict(edge_id=eid,status=status,issued_time_s=issued,received_time_s=received,
        coverage_start_s=0,coverage_end_s=100,
        closed_intervals=[dict(start_s=a,end_s=b) for a,b in closed],
        source_ids=["routing-adapter-test"],spatial_rule="authored edge interval",
        reason="authored exercise status")

class AdapterTests(unittest.TestCase):
    def test_graph_preserves_directed_source_and_access_proxy_provenance(self):
        payload,manifest=fixture()
        graph=graph_from_geography(payload,manifest)
        self.assertEqual(set(graph.edges),{e["id"] for e in payload["edges"]})
        self.assertEqual(graph.edges["ab/0/fwd"].source,"A")
        self.assertEqual(graph.edges["ab/0/fwd"].target,"B")
        self.assertEqual(graph.edges["ab/0/fwd"].travel_s,1)
        self.assertEqual(graph.edges["ab/0/fwd"].access,("bus","ambulance","truck"))
        self.assertIn("assumed test speed",graph.edges["ab/0/fwd"].weight_source)
        self.assertEqual(graph.source_metadata["license"],"ODbL 1.0")
        self.assertIn("motorcar",graph.source_metadata["vehicle_access_proxy"]["ambulance"])
        self.assertEqual(graph.origin_lonlat,tuple(ORIGIN))
        self.assertEqual(graph.metric_crs,CRS)
        self.assertEqual(graph.edge_provenance["ab/0/fwd"]["way_id"],"ab")
        plain=TripExecutor(graph,Ledger([],[],[],{})).snapshot()
        self.assertEqual(plain["metric_crs"],CRS)
        self.assertEqual(plain["origin_lonlat"],ORIGIN)
        self.assertEqual(plain["source_metadata"]["raw_sha256"],SHA)
        state=TripExecutor(graph,Ledger([],[],[],{})).checkpoint()
        graph.source_metadata["license"]="changed after save"
        with self.assertRaises(ValueError):
            TripExecutor.from_checkpoint(graph,state)
    def test_existing_version_one_checkpoints_keep_their_graph_identity(self):
        from services.routing.checkpoint import graph_fingerprint
        from services.routing.demo import exercise_graph
        self.assertEqual(graph_fingerprint(exercise_graph()),
            "78542f1adac8d330b0c8e19102ef246ec54fbb3dd20fb758ed340cc9900b8205")
    def test_invalid_ids_units_access_and_source_identity_reject(self):
        for mutation in ("duplicate","duration","geometry","access","crs","source","bbox"):
            payload,manifest=fixture()
            if mutation=="duplicate": payload["edges"][1]["id"]=payload["edges"][0]["id"]
            elif mutation=="duration": payload["edges"][0]["travel_time_s"]=-1
            elif mutation=="geometry": payload["edges"][0]["geometry_m"][1]=[99,0]
            elif mutation=="access": payload["edges"][0]["vehicle_access"]["bus"]=1
            elif mutation=="crs": payload["metric_crs"]="WGS84 longitude latitude"
            elif mutation=="source": manifest["raw_sha256"]="b"*64
            else: manifest["coverage_bbox_lonlat"][0]-=0.01
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                graph_from_geography(payload,manifest)
    def test_metric_origin_and_whole_edge_coverage_are_checked(self):
        payload,manifest=fixture()
        shifted=copy.deepcopy(payload)
        seen_points=set()
        for point in ([node["geometry_m"] for node in shifted["nodes"]]
                      +[point for edge in shifted["edges"] for point in edge["geometry_m"]]):
            if id(point) not in seen_points:
                point[0]+=100000
                seen_points.add(id(point))
        with self.assertRaisesRegex(ValueError,"projection"):
            graph_from_geography(shifted,manifest)

        payload,manifest=fixture()
        bent=payload["edges"][0]
        bent["geometry_m"].insert(1,[0,10000])
        from math import hypot
        bent["length_m"]=10000+hypot(10,10000)
        bent["travel_time_s"]=bent["length_m"]/bent["speed_mps"]
        graph=graph_from_geography(payload,manifest)
        safe=safety_from_access([record("ab/0/fwd")],graph,alignment=alignment(graph),
            known_at_s=0,horizon_s=100,version="bent",safe_nodes=["D"])
        self.assertNotIn("ab/0/fwd",safe.covered_edges)
        self.assertEqual(safe.traversal("ab/0/fwd",1,2)[1],"unknown_coverage")

    def test_unknown_outside_future_and_incompatible_alignment_reject(self):
        payload,manifest=fixture(); graph=graph_from_geography(payload,manifest)
        records=[record(e) for e in graph.edges]
        a=alignment(graph)
        for field,value in (("metric_crs","LOCAL_METRIC"),
                            ("origin_lonlat",[0,0]),
                            ("graph_version","another-graph"),
                            ("graph_source_sha256","b"*64)):
            bad=copy.deepcopy(a); bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                safety_from_access(records,graph,alignment=bad,known_at_s=0,
                    horizon_s=100,version="k0",safe_nodes=["D"])
        safe=safety_from_access(records,graph,alignment=a,known_at_s=0,
            horizon_s=100,version="k0",safe_nodes=["D"])
        self.assertNotIn("bo/0/fwd",safe.covered_edges)
        self.assertEqual(safe.traversal("bo/0/fwd",1,2)[1],"unknown_coverage")
        with self.assertRaises(ValueError):
            safety_from_access(records,graph,alignment=a,known_at_s=0,
                horizon_s=100,version="k0",safe_nodes=["OUT"])
        unknown=safety_from_access([r for r in records if r["edge_id"]!="bc/0/fwd"],graph,alignment=a,known_at_s=0,
            horizon_s=100,version="k0",safe_nodes=["D"])
        self.assertNotIn("bc/0/fwd",unknown.covered_edges)
        future=[record("ab/0/fwd",issued=5,received=5)]
        hidden=safety_from_access(future,graph,alignment=a,known_at_s=0,
            horizon_s=100,version="early",safe_nodes=["D"])
        self.assertEqual(hidden.covered_edges,frozenset())
        partial=record("ab/0/fwd"); partial["coverage_end_s"]=2
        incomplete=safety_from_access([partial],graph,alignment=a,known_at_s=0,
            horizon_s=100,version="partial",safe_nodes=["D"])
        self.assertEqual(incomplete.covered_edges,frozenset())
        unknown_row=record("ab/0/fwd",status="unknown")
        unknown_status=safety_from_access([unknown_row],graph,alignment=a,known_at_s=0,
            horizon_s=100,version="unknown",safe_nodes=["D"])
        self.assertEqual(unknown_status.covered_edges,frozenset())
        observed_open=record("ab/0/fwd",status="observed")
        observed=safety_from_access([observed_open],graph,alignment=a,known_at_s=0,
            horizon_s=100,version="observed-open",safe_nodes=["D"])
        self.assertEqual(observed.covered_edges,frozenset(),
            "an instantaneous observation cannot certify future open road travel")
        reports=[record(e) for e in graph.edges]
        reports += [record("bd/0/fwd",issued=.5,received=1,closed=((1,100),))]
        unseen=safety_from_access(reports,graph,alignment=a,known_at_s=.5,
            horizon_s=100,version="unreceived",safe_nodes=["D"])
        self.assertTrue(unseen.traversal("bd/0/fwd",1,2)[0])
    def test_injected_closure_is_half_open_and_restored_trip_detours(self):
        payload,manifest=fixture(); graph=graph_from_geography(payload,manifest)
        a=alignment(graph); base=[record(e) for e in graph.edges]
        initial=safety_from_access(base,graph,alignment=a,known_at_s=0,horizon_s=100,
            version="k0",safe_nodes=["D"])
        route=candidate_routes(graph,"A","D","bus",0,initial).routes[0]
        self.assertEqual(route.edge_ids,("ab/0/fwd","bd/0/fwd"))
        ledger=Ledger([Vehicle("v","bus","A",1,0)],
            [Request("r","evacuation","A","D",("person",))],
            [Destination("shelter","D","shelter",1)],{})
        engine=TripExecutor(graph,ledger)
        engine.dispatch("dispatch","v","r",route,initial,service_s=1)
        engine.advance(.5,initial)
        restored=TripExecutor.from_checkpoint(graph,engine.checkpoint())
        later=base+[record("bd/0/fwd",issued=.5,received=.5,closed=((1,100),))]
        known=safety_from_access(later,graph,alignment=a,known_at_s=.5,horizon_s=100,
            version="k1",safe_nodes=["D"])
        self.assertTrue(known.traversal("ab/0/fwd",.5,1)[0])
        edge_exit=base+[record("ab/0/fwd",issued=.5,received=.5,closed=((1,100),))]
        exact=safety_from_access(edge_exit,graph,alignment=a,known_at_s=.5,
            horizon_s=100,version="exact",safe_nodes=["D"])
        self.assertTrue(exact.traversal("ab/0/fwd",.5,1)[0])
        self.assertFalse(exact.traversal("ab/0/fwd",1,1.5)[0])
        self.assertFalse(known.traversal("bd/0/fwd",1,2)[0])
        result=restored.replan("dispatch",known,"report","authored closure")
        self.assertEqual(result.status,"feasible")
        self.assertEqual(restored.snapshot()["trips"][0]["position_m"],[5,0])
        self.assertEqual(restored.snapshot()["trips"][0]["remaining_path"],
                         ["ab/0/fwd","bc/0/fwd","cd/0/fwd"])
        restored.advance(5,known)
        self.assertEqual(restored.ledger.export_state()["outcome_totals"]["safe_evacuated_people"],1)
        self.assertEqual(engine.ledger.export_state()["outcome_totals"]["safe_evacuated_people"],0)

    def test_report_corrections_are_visible_only_after_receipt(self):
        payload, manifest = fixture()
        graph = graph_from_geography(payload, manifest)
        rows = [record('ab/0/fwd'),
                record('ab/0/fwd', issued=2, received=3, status='unknown'),
                record('ab/0/fwd', issued=4, received=5, status='forecast')]
        expected = [(1, True), (2.5, True), (3, False), (4.5, False), (5, True)]
        for cutoff, covered in expected:
            with self.subTest(cutoff=cutoff):
                snapshot = safety_from_access(
                    rows, graph, alignment=alignment(graph), known_at_s=cutoff,
                    horizon_s=10, version=f'correction-{cutoff}', safe_nodes=['D'])
                self.assertEqual('ab/0/fwd' in snapshot.covered_edges, covered)
        same_issue_unknown = rows + [record('ab/0/fwd', issued=4, received=5, status='unknown')]
        conflicting = safety_from_access(
            same_issue_unknown, graph, alignment=alignment(graph), known_at_s=5,
            horizon_s=10, version='same-issue-conflict', safe_nodes=['D'])
        self.assertNotIn('ab/0/fwd', conflicting.covered_edges)
