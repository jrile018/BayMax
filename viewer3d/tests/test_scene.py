"""Projection safety tests: no transport, renderer, or simulation dependency."""
from dataclasses import replace
import importlib
import importlib.util
import math
import pytest


def api():
    assert importlib.util.find_spec("viewer3d.scene") is not None, "CPU scene projection missing"
    return importlib.import_module("viewer3d.scene")


def fixture():
    s = api()
    frame = s.FrameIdentity("run-a", "scenario-a", 12.5, "snapshot-a")
    source = s.SourceMetadata("fixture", "independent fixture", "CC0-1.0",
                              "fixture://tiny", True, ("constructed training geometry",))
    p = s.MetricPoint
    bounds = s.SceneBounds(p(0, 0, 0), p(100, 100, 30))
    geometry = (p(0, 0, 0), p(10, 0, 1), p(10, 10, 2))
    footprint = (p(20, 20, 2), p(25, 20, 2), p(25, 25, 2), p(20, 25, 2))
    data = s.SceneInput(
        frame=frame, metric_crs="LOCAL_METRIC:fixture", metric_origin="fixture origin",
        bounds=bounds, horizontal_units="metres",
        terrain=(s.TerrainPatch("terrain-1", frame, source, geometry, ((0, 1, 2),)),),
        roads=(s.PolylineRecord("edge-1", frame, source, geometry),),
        buildings=(s.BuildingRecord("building-1", frame, source, footprint),),
        fires=(s.PolygonRecord("fire-1", frame, source,
                              (p(50, 50, 1), p(60, 50, 1), p(55, 60, 1))),),
        routes=(s.RouteRecord("route-1", frame, source, geometry, 7, "committed"),),
        trails=(s.PolylineRecord("vehicle-1-trail", frame, source, (p(1, 1, 0), p(2, 1, 0))),),
        units=(s.UnitRecord("vehicle-1", frame, source, "ambulance", p(4.25, 1.5, 0.75)),),
        aid=(s.AidRecord("request-1", frame, source, "medical", p(70, 70, 0), "unmet"),),
    )
    return s, data


def test_exact_authoritative_position_route_and_trail_are_retained():
    s, data = fixture()
    scene = s.build_scene(data)
    indexed = {p.record_id: p for p in scene.primitives}
    assert indexed["vehicle-1"].points == (s.MetricPoint(4.25, 1.5, 0.75),)
    assert indexed["route-1"].route_version == 7
    assert indexed["route-1"].role == "committed"
    assert indexed["route-1"].line_style == "solid"
    assert indexed["vehicle-1-trail"].points == (s.MetricPoint(1, 1, 0), s.MetricPoint(2, 1, 0))
    assert indexed["vehicle-1-trail"].line_style == "dotted"
    assert scene.frame == s.FrameIdentity("run-a", "scenario-a", 12.5, "snapshot-a")
    assert scene.metric_crs == "LOCAL_METRIC:fixture"
    assert scene.metric_origin == "fixture origin"


def test_terrain_mesh_and_source_manifest_survive_deterministic_projection():
    s, data = fixture()
    first = s.build_scene(data)
    assert first == s.build_scene(data)
    terrain = first.primitives[0]
    assert terrain.kind == "terrain"
    assert terrain.points == (s.MetricPoint(0, 0, 0), s.MetricPoint(10, 0, 1), s.MetricPoint(10, 10, 2))
    assert terrain.triangles == ((0, 1, 2),)
    assert terrain.source.license_id == "CC0-1.0"
    assert terrain.source.assumptions == ("constructed training geometry",)
    assert len(first.sources) == 1
    assert {p.kind for p in first.primitives} == {"terrain", "road", "building", "fire", "route", "trail", "unit", "aid"}
    assert all(p.frame == first.frame for p in first.primitives)


def test_missing_height_stays_unknown_and_explicit_assumption_is_labeled():
    s, data = fixture()
    building = next(p for p in s.build_scene(data).primitives if p.kind == "building")
    assert building.height_m is None
    assert building.height_status == "absent"
    assumed = replace(data.buildings[0], height_m=5.0, height_assumption="visual fixture height")
    projected = next(p for p in s.build_scene(replace(data, buildings=(assumed,))).primitives if p.kind == "building")
    assert projected.height_m == 5.0
    assert projected.height_status == "assumed"
    assert projected.height_assumption == "visual fixture height"


@pytest.mark.parametrize("role,style", [("candidate", "dashed"), ("committed", "solid"), ("previous", "dash-dot")])
def test_route_roles_are_distinguishable_without_color(role, style):
    s, data = fixture()
    scene = s.build_scene(replace(data, routes=(replace(data.routes[0], role=role),)))
    route = next(p for p in scene.primitives if p.kind == "route")
    assert route.role == role
    assert route.line_style == style


@pytest.mark.parametrize("field", ["run_id", "scenario_id", "time_s", "snapshot_hash"])
def test_mixed_frame_identity_is_rejected(field):
    s, data = fixture()
    value = 99.0 if field == "time_s" else "different"
    road = replace(data.roads[0], frame=replace(data.frame, **{field: value}))
    with pytest.raises(ValueError, match="frame"):
        s.build_scene(replace(data, roads=(road,)))


@pytest.mark.parametrize("coordinate", [math.nan, math.inf, -math.inf, True, "2"])
def test_nonfinite_or_nonnumeric_positions_are_rejected(coordinate):
    s, data = fixture()
    unit = replace(data.units[0], position=s.MetricPoint(coordinate, 1, 0))
    with pytest.raises(ValueError, match="coordinate"):
        s.build_scene(replace(data, units=(unit,)))


@pytest.mark.parametrize("time", [math.nan, math.inf, -1, True])
def test_invalid_frame_time_is_rejected(time):
    s, data = fixture()
    with pytest.raises(ValueError, match="time"):
        s.build_scene(replace(data, frame=replace(data.frame, time_s=time)))


@pytest.mark.parametrize("source_change", [
    {"license_id": ""}, {"independently_sourced": False},
    {"provider": "Google Maps"}, {"reference": "https://maps.googleapis.com/geometry"},
    {"assumptions": ("Google-derived building footprint",)},
])
def test_unlicensed_or_google_derived_geography_is_rejected(source_change):
    s, data = fixture()
    road = replace(data.roads[0], source=replace(data.roads[0].source, **source_change))
    with pytest.raises(ValueError, match="source|license|Google|independent"):
        s.build_scene(replace(data, roads=(road,)))


@pytest.mark.parametrize("kind", ["tank", "infantry", "fighter", "combat", "unknown"])
def test_combat_or_unsupported_units_are_rejected(kind):
    s, data = fixture()
    with pytest.raises(ValueError, match="unit"):
        s.build_scene(replace(data, units=(replace(data.units[0], kind=kind),)))


@pytest.mark.parametrize("kind", ["ambulance", "bus", "supply_truck", "rescue_vehicle", "fire_engine"])
def test_civilian_rescue_logistics_units_have_exact_marker_positions(kind):
    s, data = fixture()
    scene = s.build_scene(replace(data, units=(replace(data.units[0], kind=kind),)))
    unit = next(p for p in scene.primitives if p.kind == "unit")
    assert unit.role == kind
    assert unit.points == (s.MetricPoint(4.25, 1.5, 0.75),)


def test_malformed_mesh_line_polygon_and_height_are_rejected():
    s, data = fixture()
    bad_inputs = (
        replace(data, terrain=(replace(data.terrain[0], triangles=((0, 1, 99),)),)),
        replace(data, terrain=(replace(data.terrain[0], triangles=((0, 1, 1),)),)),
        replace(data, roads=(replace(data.roads[0], points=(s.MetricPoint(0, 0, 0),)),)),
        replace(data, fires=(replace(data.fires[0], points=(s.MetricPoint(0, 0, 0), s.MetricPoint(2, 0, 0), s.MetricPoint(1, 0, 0))),)),
        replace(data, buildings=(replace(data.buildings[0], height_m=-2),)),
        replace(data, buildings=(replace(data.buildings[0], height_m=math.nan),)),
    )
    for bad in bad_inputs:
        with pytest.raises(ValueError):
            s.build_scene(bad)


def test_self_crossing_footprint_rejected():
    s, data = fixture()
    points = tuple(s.MetricPoint(x, y, 0) for x, y in [(0, 0), (10, 10), (0, 10), (10, 0)])
    with pytest.raises(ValueError, match="polygon"):
        s.build_scene(replace(data, buildings=(replace(data.buildings[0], footprint=points),)))


def test_bounds_and_total_geometry_limits_are_enforced_before_projection():
    s, data = fixture()
    with pytest.raises(ValueError, match="bounds"):
        s.build_scene(replace(data, units=(replace(data.units[0], position=s.MetricPoint(101, 0, 0)),)))
    with pytest.raises(ValueError, match="bounds"):
        s.build_scene(replace(data, buildings=(replace(data.buildings[0], height_m=29),)))
    for limits in (s.SceneLimits(max_primitives=1), s.SceneLimits(max_points=3), s.SceneLimits(max_triangles=0), s.SceneLimits(max_extent_m=10)):
        with pytest.raises(ValueError, match="limit|extent"):
            s.build_scene(data, limits=limits)


def test_declared_metric_reference_duplicate_ids_and_route_version_validation():
    s, data = fixture()
    bad_inputs = (
        replace(data, metric_crs="EPSG:4326"),
        replace(data, metric_origin=""),
        replace(data, roads=data.roads + data.roads),
        replace(data, routes=(replace(data.routes[0], route_version=-1),)),
        replace(data, routes=(replace(data.routes[0], route_version=True),)),
        replace(data, routes=(replace(data.routes[0], role="invented"),)),
    )
    for bad in bad_inputs:
        with pytest.raises(ValueError):
            s.build_scene(bad)


@pytest.mark.parametrize("field,value", [
    ("license_id", "unlicensed"), ("license_id", "unknown"),
])
def test_unknown_license_is_not_permission_to_project(field, value):
    s, data = fixture()
    road = replace(data.roads[0], source=replace(data.roads[0].source, **{field: value}))
    with pytest.raises(ValueError, match="license"):
        s.build_scene(replace(data, roads=(road,)))


def test_unhashable_route_and_unit_kinds_rejected_as_malformed_records():
    s, data = fixture()
    for bad in (
        replace(data, routes=(replace(data.routes[0], role=[]),)),
        replace(data, units=(replace(data.units[0], kind=[]),)),
    ):
        with pytest.raises(ValueError):
            s.build_scene(bad)


def test_backtracking_polygon_boundary_is_rejected():
    s, data = fixture()
    points = tuple(s.MetricPoint(x, y, 0) for x, y in [(0, 0), (10, 0), (5, 0), (5, 5), (0, 5)])
    with pytest.raises(ValueError, match="polygon"):
        s.build_scene(replace(data, buildings=(replace(data.buildings[0], footprint=points),)))


def test_conflicting_provenance_cannot_collapse_into_one_source_manifest():
    s, data = fixture()
    road = replace(data.roads[0], source=replace(data.roads[0].source, license_id="CC-BY-4.0"))
    with pytest.raises(ValueError, match="source"):
        s.build_scene(replace(data, roads=(road,)))


def test_immutable_scene_inputs_and_polygon_budget_are_required():
    s, data = fixture()
    for bad in (
        replace(data, roads=list(data.roads)),
        replace(data, roads=(replace(data.roads[0], points=list(data.roads[0].points)),)),
        replace(data, bounds=replace(data.bounds, maximum=s.MetricPoint(-1, 100, 30))),
    ):
        with pytest.raises(ValueError):
            s.build_scene(bad)
    with pytest.raises(ValueError, match="limit"):
        s.build_scene(data, limits=s.SceneLimits(max_polygon_points=3))


@pytest.mark.parametrize("category", ["roads", "trails"])
def test_route_record_in_plain_line_category_cannot_drop_version_or_role(category):
    s, data = fixture()
    with pytest.raises(ValueError, match="record"):
        s.build_scene(replace(data, **{category: (data.routes[0],)}))


def test_scene_requires_explicit_horizontal_metres_and_preserves_declaration():
    s, data = fixture()
    assert "horizontal_units" in data.__dataclass_fields__, "explicit horizontal unit declaration missing"
    scene = s.build_scene(replace(data, horizontal_units="metres"))
    assert scene.horizontal_units == "metres"


@pytest.mark.parametrize("crs,units", [
    ("EPSG:4269", "degrees"), ("EPSG:2263", "ft"),
    ("LOCAL_METRIC:fixture", None), ("LOCAL_METRIC:fixture", "unknown"),
])
def test_missing_or_nonmetre_horizontal_units_rejected(crs, units):
    s, data = fixture()
    assert "horizontal_units" in data.__dataclass_fields__, "explicit horizontal unit declaration missing"
    with pytest.raises(ValueError, match="units"):
        s.build_scene(replace(data, metric_crs=crs, horizontal_units=units))
