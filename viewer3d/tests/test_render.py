"""CPU-only native renderer preparation and fake context lifecycle tests."""
from dataclasses import replace
import importlib
import math
import sys
from types import SimpleNamespace

import pytest
from viewer3d import scene as s


def api():
    assert importlib.util.find_spec("viewer3d.render"), "native renderer preparation missing"
    return importlib.import_module("viewer3d.render")


def prepared():
    frame = s.FrameIdentity("run-render", "fixture", 7.5, "exact-hash")
    source = s.SourceMetadata("fixture", "independent fixture", "CC0-1.0", "fixture://render", True)
    p = s.MetricPoint
    ring = tuple(p(x, y, 2) for x, y in ((20, 20), (26, 20), (26, 26), (23, 23), (20, 26)))
    terrain = (p(0, 0, 0), p(10, 0, 1), p(10, 10, 2))
    return s.build_scene(s.SceneInput(
        frame, "LOCAL_METRIC:fixture", "fixture origin",
        s.SceneBounds(p(0, 0, 0), p(100, 100, 30)), "metres",
        terrain=(s.TerrainPatch("terrain", frame, source, terrain, ((0, 1, 2),)),),
        roads=(s.PolylineRecord("road", frame, source, terrain),),
        buildings=(s.BuildingRecord("known", frame, source, ring, 8),
                   s.BuildingRecord("unknown", frame, source, ring)),
        fires=(s.PolygonRecord("fire", frame, source, ring),),
        routes=(s.RouteRecord("route", frame, source, terrain, 11, "candidate"),),
        trails=(s.PolylineRecord("trail", frame, source, terrain),),
        units=(s.UnitRecord("unit", frame, source, "ambulance", p(4.25, 1.5, .75)),),
        aid=(s.AidRecord("aid", frame, source, "medical", p(70, 70, 3), "unmet"),),
    ))


def test_buffers_keep_frame_provenance_and_exact_supplied_geometry():
    r, scene = api(), prepared()
    result = r.build_render_buffers(scene)
    assert result.scene is scene
    assert result == r.build_render_buffers(scene)
    assert len(result.batches) == len(scene.primitives)
    for batch, primitive in zip(result.batches, scene.primitives):
        assert batch.primitive is primitive
        assert batch.vertices[:len(primitive.points)] == primitive.points
    batches = {b.primitive.record_id: b for b in result.batches}
    assert batches["terrain"].triangles == scene.primitives[0].triangles
    for name in ("road", "route", "trail"):
        assert batches[name].lines == ((0, 1), (1, 2))
        assert batches[name].vertices == batches[name].primitive.points
    assert batches["route"].primitive.route_version == 11
    assert batches["route"].primitive.line_style == "dashed"
    assert batches["unit"].vertices == (s.MetricPoint(4.25, 1.5, .75),)
    assert batches["aid"].vertices == (s.MetricPoint(70, 70, 3),)


def test_building_derives_only_explicit_height_and_missing_height_is_footprint():
    batches = {b.primitive.record_id: b for b in api().build_render_buffers(prepared()).batches}
    known, unknown = batches["known"], batches["unknown"]
    n = len(known.primitive.points)
    assert known.vertices[n:] == tuple(s.MetricPoint(p.x_m, p.y_m, p.z_m + 8) for p in known.primitive.points)
    assert len(known.triangles) == n - 2 + 2 * n
    assert unknown.vertices == unknown.primitive.points
    assert unknown.triangles == ()
    assert unknown.lines == tuple((i, (i + 1) % n) for i in range(n))


@pytest.mark.parametrize("reverse", [False, True])
def test_concave_fire_tessellation_preserves_polygon_area(reverse):
    scene = prepared()
    fire = next(p for p in scene.primitives if p.kind == "fire")
    if reverse:
        fire = replace(fire, points=fire.points[::-1])
    batch = api().build_render_buffers(replace(scene, primitives=(fire,))).batches[0]
    assert batch.vertices == fire.points
    def twice_area(a, b, c):
        return (b.x_m-a.x_m)*(c.y_m-a.y_m)-(b.y_m-a.y_m)*(c.x_m-a.x_m)
    expected = abs(sum(twice_area(fire.points[0], fire.points[i], fire.points[i+1])
                       for i in range(1, len(fire.points)-1)))
    actual = sum(abs(twice_area(*(batch.vertices[i] for i in tri))) for tri in batch.triangles)
    assert actual == expected
    assert len(batch.triangles) == len(fire.points)-2


@pytest.mark.parametrize("size", [(1280, 720), (320, 1000), (1, 1)])
@pytest.mark.parametrize("bounds", [
    s.SceneBounds(s.MetricPoint(0, 0, 0), s.MetricPoint(100, 100, 30)),
    s.SceneBounds(s.MetricPoint(1e6, -2e6, 0), s.MetricPoint(1e6+10, -2e6+100, 80)),
    s.SceneBounds(s.MetricPoint(5, 5, 5), s.MetricPoint(5, 5, 5)),
])
def test_camera_is_finite_deterministic_and_contains_every_bounds_corner(size, bounds):
    camera = api().camera_for_bounds(bounds, *size)
    assert camera == api().camera_for_bounds(bounds, *size)
    assert camera.aspect == size[0] / size[1]
    assert 0 < camera.near < camera.far
    assert camera.eye.z_m > camera.target.z_m
    assert all(math.isfinite(v) for row in camera.view_projection for v in row)
    for x in (bounds.minimum.x_m, bounds.maximum.x_m):
        for y in (bounds.minimum.y_m, bounds.maximum.y_m):
            for z in (bounds.minimum.z_m, bounds.maximum.z_m):
                ndc = camera.project(s.MetricPoint(x, y, z))
                assert all(-1 <= v <= 1 for v in ndc)


@pytest.mark.parametrize("size", [(0, 720), (-1, 2), (True, 2), (2.5, 3), (2, 0)])
def test_camera_rejects_invalid_dimensions(size):
    with pytest.raises(ValueError, match="dimensions"):
        api().camera_for_bounds(prepared().bounds, *size)


def test_cpu_path_does_not_import_graphics_or_torch(monkeypatch):
    original = __import__
    seen = []
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"moderngl", "glcontext", "torch", "PIL"}:
            seen.append(name)
            raise AssertionError("CPU preparation attempted graphics import")
        return original(name, *args, **kwargs)
    monkeypatch.setattr("builtins.__import__", guarded)
    r = importlib.reload(api())
    r.build_render_buffers(prepared())
    r.camera_for_bounds(prepared().bounds, 1280, 720)
    assert seen == []


class Resource:
    def __init__(self, ctx, kind):
        self.ctx, self.kind, self.released = ctx, kind, False
        ctx.resources.append(self)
        self.writes = {}
    def release(self):
        self.released = True
    def use(self):
        pass
    def clear(self, *args, **kwargs):
        pass
    def read(self, **kwargs):
        if self.ctx.fail_read:
            raise RuntimeError("read failed")
        return bytes((255, 0, 0) * 2 + (0, 0, 255) * 2)
    def render(self, **kwargs):
        self.ctx.draws.append(kwargs)
    def __getitem__(self, name):
        self.uniform_name = name
        return self
    def write(self, value):
        self.last_write = value
        self.writes[self.uniform_name] = value


class Context:
    def __init__(self, renderer="AMD test double", fail_read=False):
        self.info = {"GL_VENDOR": "test double", "GL_RENDERER": renderer, "GL_VERSION": "3.3 fake"}
        self.resources, self.draws, self.fail_read = [], [], fail_read
        self.uploads, self.vertex_formats = [], []
        self.released = False
    def release(self):
        self.released = True
    def enable(self, flags):
        self.enabled = flags
    def texture(self, *args, **kwargs):
        return Resource(self, "texture")
    def depth_renderbuffer(self, *args, **kwargs):
        return Resource(self, "depth")
    def framebuffer(self, *args, **kwargs):
        return Resource(self, "framebuffer")
    def program(self, **kwargs):
        return Resource(self, "program")
    def buffer(self, data):
        self.uploads.append(data)
        return Resource(self, "buffer")
    def vertex_array(self, *args, **kwargs):
        self.vertex_formats.append(args[1][0][1])
        return Resource(self, "vao")


def fake_module(monkeypatch, context):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return context
    monkeypatch.setitem(sys.modules, "moderngl", SimpleNamespace(
        create_standalone_context=create, DEPTH_TEST=1, PROGRAM_POINT_SIZE=2,
        TRIANGLES=4, LINES=1, POINTS=0))
    return calls


class DepthRasterContext(Context):
    """One-sample fake raster: equal metric depth and foreground occlusion."""
    def __init__(self):
        super().__init__()
        self.depth_func = "<"
        self.sample_depth = 1.0
        self.sample_color = (18, 23, 31)
        self.painted = []

    def framebuffer(self, *args, **kwargs):
        context = self
        class Framebuffer(Resource):
            def clear(self, *args, **kwargs):
                context.sample_depth = kwargs["depth"]
            def read(self, **kwargs):
                return bytes(context.sample_color * 4)
        return Framebuffer(self, "framebuffer")

    def program(self, **kwargs):
        class Uniform:
            def __init__(self):
                self.value = None
            def write(self, value):
                pass
        class Program(Resource):
            def __init__(self, ctx):
                super().__init__(ctx, "program")
                self.uniforms = {}
            def __getitem__(self, name):
                return self.uniforms.setdefault(name, Uniform())
        return Program(self)

    def vertex_array(self, program, bindings):
        import struct
        context = self
        vertices = tuple(struct.iter_unpack("<4f", bindings[0][0].last_data))
        color = program["color"].value
        class RasterVAO(Resource):
            def render(self, **kwargs):
                context.draws.append(kwargs)
                # Higher z is nearer for this one-sample orthographic model.
                depth = .5 - vertices[0][2] * .01
                passes = depth <= context.sample_depth if context.depth_func == "<=" else depth < context.sample_depth
                if passes:
                    context.sample_depth = depth
                    context.sample_color = tuple(round(channel * 255) for channel in color)
                    context.painted.append(context.sample_color)
        return RasterVAO(self, "vao")

    def buffer(self, data):
        resource = super().buffer(data)
        resource.last_data = data
        return resource


def test_equal_depth_trail_wins_over_road_and_nearer_road_still_occludes(tmp_path, monkeypatch):
    from PIL import Image
    scene = prepared()
    road = next(p for p in scene.primitives if p.kind == "road")
    route = next(p for p in scene.primitives if p.kind == "route")
    trail = next(p for p in scene.primitives if p.kind == "trail")
    for road_z, expected in ((0, (166, 178, 217)), (10, (191, 196, 204))):
        points = tuple(replace(p, z_m=road_z) for p in road.points)
        full = replace(route, record_id="full", role="committed")
        remaining = replace(route, record_id="remaining", role="committed")
        sample_scene = replace(scene, primitives=(replace(road, points=points), full, remaining, trail))
        ctx = DepthRasterContext()
        fake_module(monkeypatch, ctx)
        output = tmp_path / f"depth-{road_z}.png"
        api().render_native(sample_scene, output, width=2, height=2)
        with Image.open(output) as image:
            assert image.getpixel((0, 0)) == expected
        assert ctx.depth_func == "<="
        assert len(ctx.painted) == (4 if road_z == 0 else 1)


def test_fake_native_lifecycle_records_provider_flips_image_and_releases(tmp_path, monkeypatch):
    import json
    from PIL import Image
    r, ctx = api(), Context()
    calls = fake_module(monkeypatch, ctx)
    path = tmp_path / "fake.png"
    metadata = r.render_native(prepared(), path, width=2, height=2,
                               gl_library="/fixture/libGL.so", egl_library="/fixture/libEGL.so")
    assert calls == [{"require": 330, "backend": "egl", "libgl": "/fixture/libGL.so", "libegl": "/fixture/libEGL.so"}]
    assert metadata["provider"] == ctx.info
    assert metadata["frame"]["snapshot_hash"] == "exact-hash"
    assert metadata["status"] == "rendered"
    assert metadata["fsr"] == "not implemented"
    assert json.loads(path.with_suffix(".json").read_text()) == metadata
    with Image.open(path) as image:
        assert image.getpixel((0, 0)) == (0, 0, 255)
        assert image.getpixel((0, 1)) == (255, 0, 0)
    assert ctx.draws
    assert ctx.released and all(resource.released for resource in ctx.resources)
    assert ctx.enabled == 3


@pytest.mark.parametrize("renderer", ["llvmpipe (LLVM)", "softpipe", "Software Rasterizer", "SwiftShader"])
def test_software_provider_rejected_with_failed_sidecar_and_context_cleanup(renderer, tmp_path, monkeypatch):
    import json
    ctx = Context(renderer)
    fake_module(monkeypatch, ctx)
    path = tmp_path / "rejected.png"
    with pytest.raises(RuntimeError, match="software"):
        api().render_native(prepared(), path, width=2, height=2)
    metadata = json.loads(path.with_suffix(".failed.json").read_text())
    assert metadata["status"] == "failed"
    assert metadata["provider"]["GL_RENDERER"] == renderer
    assert not path.exists()
    assert ctx.released and ctx.resources == []


def test_read_failure_releases_all_resources_and_does_not_claim_success(tmp_path, monkeypatch):
    import json
    ctx = Context(fail_read=True)
    fake_module(monkeypatch, ctx)
    path = tmp_path / "failed.png"
    with pytest.raises(RuntimeError, match="read failed"):
        api().render_native(prepared(), path, width=2, height=2)
    assert ctx.released and all(resource.released for resource in ctx.resources)
    assert json.loads(path.with_suffix(".failed.json").read_text())["status"] == "failed"
    assert not path.exists()


def test_collinear_boundary_vertices_remain_exact_while_surface_area_is_valid():
    scene = prepared()
    fire = next(p for p in scene.primitives if p.kind == "fire")
    p = s.MetricPoint
    ring = (p(0, 0, 1), p(5, 0, 1), p(10, 0, 1), p(10, 10, 1), p(0, 10, 1))
    batch = api().build_render_buffers(replace(scene, primitives=(replace(fire, points=ring),))).batches[0]
    assert batch.vertices == ring
    assert batch.lines == ((0, 1), (1, 2), (2, 3), (3, 4), (4, 0))
    area = sum(abs((ring[b].x_m-ring[a].x_m)*(ring[c].y_m-ring[a].y_m) -
                   (ring[b].y_m-ring[a].y_m)*(ring[c].x_m-ring[a].x_m))/2
               for a, b, c in batch.triangles)
    assert area == 100


def test_camera_looks_at_target_and_handles_z_up_without_swapping_metric_axes():
    r, bounds = api(), prepared().bounds
    camera = r.camera_for_bounds(bounds, 1280, 720)
    center = camera.project(camera.target)
    assert center[0] == pytest.approx(0, abs=1e-15)
    assert center[1] == pytest.approx(0, abs=1e-15)
    above = s.MetricPoint(camera.target.x_m, camera.target.y_m, camera.target.z_m+1)
    assert camera.project(above)[1] > center[1]
    assert camera.view_projection[0][0] == pytest.approx(camera.view_projection[0][1])


@pytest.mark.parametrize("size", [(16385, 1), (4097, 4096)])
def test_oversized_image_rejected_before_native_context(size, monkeypatch, tmp_path):
    r = api()
    def forbidden(*args, **kwargs):
        raise AssertionError("oversized image attempted graphics import")
    monkeypatch.setattr(r.importlib, "import_module", forbidden)
    with pytest.raises(ValueError, match="budget"):
        r.render_native(prepared(), tmp_path / "large.png", width=size[0], height=size[1])


def test_explicit_assumed_height_stays_labeled_in_buffers_and_sidecar(tmp_path, monkeypatch):
    scene = prepared()
    known = next(p for p in scene.primitives if p.record_id == "known")
    assumed = replace(known, height_status="assumed", height_assumption="fixture supplied estimate")
    scene = replace(scene, primitives=(assumed,))
    assert api().build_render_buffers(scene).batches[0].primitive is assumed
    fake_module(monkeypatch, Context())
    metadata = api().render_native(scene, tmp_path / "assumed.png", width=2, height=2)
    assert metadata["primitives"][0]["height_status"] == "assumed"
    assert metadata["primitives"][0]["height_assumption"] == "fixture supplied estimate"


def test_partial_attachment_creation_failure_releases_previously_created_resources(tmp_path, monkeypatch):
    import json
    ctx = Context()
    def fail(*args, **kwargs):
        raise RuntimeError("depth allocation failed")
    ctx.depth_renderbuffer = fail
    fake_module(monkeypatch, ctx)
    path = tmp_path / "partial.png"
    with pytest.raises(RuntimeError, match="depth allocation"):
        api().render_native(prepared(), path, width=2, height=2)
    assert ctx.released and all(resource.released for resource in ctx.resources)
    assert json.loads(path.with_suffix(".failed.json").read_text())["output_written"] is False
    assert not path.exists()


def test_cleanup_failure_still_releases_context_and_prevents_image_publication(tmp_path, monkeypatch):
    import json
    ctx = Context()
    original_buffer = ctx.buffer
    def buffer_with_failing_release(*args, **kwargs):
        resource = original_buffer(*args, **kwargs)
        def fail():
            resource.released = True
            raise RuntimeError("buffer release failed")
        resource.release = fail
        return resource
    ctx.buffer = buffer_with_failing_release
    fake_module(monkeypatch, ctx)
    path = tmp_path / "cleanup.png"
    with pytest.raises(RuntimeError, match="release failed"):
        api().render_native(prepared(), path, width=2, height=2)
    assert ctx.released and all(resource.released for resource in ctx.resources)
    assert json.loads(path.with_suffix(".failed.json").read_text())["status"] == "failed"
    assert not path.exists()
    assert not path.with_name("cleanup.png.tmp").exists()


def test_missing_provider_metadata_fails_before_resource_allocation(tmp_path, monkeypatch):
    ctx = Context()
    del ctx.info["GL_RENDERER"]
    fake_module(monkeypatch, ctx)
    with pytest.raises(RuntimeError, match="metadata missing"):
        api().render_native(prepared(), tmp_path / "unknown.png", width=2, height=2)
    assert ctx.released and ctx.resources == []


def test_native_context_failure_writes_failed_sidecar_without_success_claim(tmp_path, monkeypatch):
    import json
    def fail(**kwargs):
        raise RuntimeError("EGL unavailable")
    monkeypatch.setitem(sys.modules, "moderngl", SimpleNamespace(create_standalone_context=fail))
    path = tmp_path / "no-context.png"
    with pytest.raises(RuntimeError, match="EGL unavailable"):
        api().render_native(prepared(), path, width=2, height=2)
    metadata = json.loads(path.with_suffix(".failed.json").read_text())
    assert metadata["provider"] == {}
    assert metadata["output_written"] is False
    assert metadata["status"] == "failed"
    assert not path.exists()


def test_native_line_upload_retains_exact_centers_and_has_progressive_screen_distance(tmp_path, monkeypatch):
    """A diagonal must have positive dash progression rather than x+y phase."""
    import struct
    scene = prepared()
    route = next(p for p in scene.primitives if p.kind == "route")
    scene = replace(scene, primitives=(route,))
    r, ctx = api(), Context()
    fake_module(monkeypatch, ctx)
    r.render_native(scene, tmp_path / "line.png", width=2, height=2)
    assert ctx.vertex_formats == ["3f 1f"]
    camera = r.camera_for_bounds(scene.bounds, 2, 2)
    expected_matrix = struct.pack("<16f", *(camera.view_projection[i][j] for j in range(4) for i in range(4)))
    program = next(resource for resource in ctx.resources if resource.kind == "program")
    assert program.writes["view_projection"] == expected_matrix
    vertices = tuple(struct.iter_unpack("<4f", ctx.uploads[0]))
    camera = r.camera_for_bounds(scene.bounds, 2, 2)
    expected_indices = (0, 1, 1, 2)
    for uploaded, index in zip(vertices, expected_indices):
        assert uploaded[:3] == pytest.approx(tuple(a-b for a, b in zip(
            (route.points[index].x_m, route.points[index].y_m, route.points[index].z_m),
            (camera.target.x_m, camera.target.y_m, camera.target.z_m))))
    assert vertices[0][3] == 0
    assert vertices[1][3] > vertices[0][3]
    assert vertices[2][3] == vertices[1][3]
    assert vertices[3][3] > vertices[2][3]


def test_camera_rejects_finite_bounds_that_overflow_derived_projection():
    p = s.MetricPoint
    with pytest.raises(ValueError, match="finite"):
        api().camera_for_bounds(s.SceneBounds(p(-1e308, 0, 0), p(1e308, 1, 1)), 1280, 720)


def test_sidecar_associates_each_primitive_with_its_exact_source(tmp_path, monkeypatch):
    scene = prepared()
    distinct = replace(scene.sources[0], source_id="other-source", provider="second independent fixture")
    first, second = scene.primitives[0], replace(scene.primitives[1], source=distinct)
    scene = replace(scene, primitives=(first, second), sources=(first.source, distinct))
    fake_module(monkeypatch, Context())
    metadata = api().render_native(scene, tmp_path / "sources.png", width=2, height=2)
    assert [p["source_id"] for p in metadata["primitives"]] == [first.source.source_id, distinct.source_id]
    assert metadata["bounds"] == {
        "minimum": {"x_m": 0, "y_m": 0, "z_m": 0},
        "maximum": {"x_m": 100, "y_m": 100, "z_m": 30},
    }


def test_sidecar_keeps_original_authoritative_geometry_and_snapshot_hash(tmp_path, monkeypatch):
    scene = prepared()
    fake_module(monkeypatch, Context())
    metadata = api().render_native(scene, tmp_path / "geometry.png", width=2, height=2)
    assert metadata["frame"]["snapshot_hash"] == scene.frame.snapshot_hash
    for record, primitive in zip(metadata["primitives"], scene.primitives):
        assert record["points"] == [dict(x_m=p.x_m, y_m=p.y_m, z_m=p.z_m) for p in primitive.points]
        assert record["triangles"] == [list(triangle) for triangle in primitive.triangles]
        assert record["source_id"] == primitive.source.source_id


def test_replay_sidecar_hook_retains_mock_labels_without_overriding_native_fields(tmp_path, monkeypatch):
    from dataclasses import asdict
    scene=prepared()
    original={"identity":asdict(scene.frame),"mode":"mock-replay","label":"project-authored mock",
              "attribution":"© OpenStreetMap contributors","elevation_assumption":"flat-ground visual assumption",
              "provider":{"GL_RENDERER":"untrusted nested description"},"fsr":"untrusted nested description"}
    before=__import__("copy").deepcopy(original)
    ctx=Context()
    fake_module(monkeypatch,ctx)
    metadata=api().render_native(scene,tmp_path/"replay.png",width=2,height=2,replay_metadata=original)
    assert metadata["replay"]==original
    assert metadata["provider"]==ctx.info and metadata["fsr"]=="not implemented"
    assert metadata["frame"]["snapshot_hash"]==scene.frame.snapshot_hash
    assert original==before
    metadata["replay"]["label"]="changed returned copy"
    assert original==before


@pytest.mark.parametrize("field",["run_id","scenario_id","time_s","snapshot_hash"])
def test_replay_sidecar_identity_mismatch_rejected_before_context(field,tmp_path,monkeypatch):
    from dataclasses import asdict
    scene=prepared()
    identity=asdict(scene.frame)
    identity[field]=123 if field=="time_s" else "wrong"
    ctx=Context()
    calls=fake_module(monkeypatch,ctx)
    with pytest.raises(ValueError,match="replay.*identity"):
        api().render_native(scene,tmp_path/"bad-replay.png",width=2,height=2,replay_metadata={"identity":identity})
    assert calls==[] and not ctx.released


def test_replay_metadata_bool_time_is_not_numeric_identity(tmp_path,monkeypatch):
    from dataclasses import asdict,replace
    scene=prepared()
    frame=replace(scene.frame,time_s=0)
    scene=replace(scene,frame=frame,primitives=tuple(replace(p,frame=frame) for p in scene.primitives))
    identity=asdict(frame)
    identity["time_s"]=False
    calls=fake_module(monkeypatch,Context())
    with pytest.raises(ValueError,match="replay.*identity"):
        api().render_native(scene,tmp_path/"bool-replay.png",width=2,height=2,replay_metadata={"identity":identity})
    assert calls==[]



def seed_render_pair(path):
    """An earlier valid image and its hand-authored success receipt."""
    from PIL import Image
    with Image.new("RGB", (2, 2), (12, 34, 56)) as image:
        image.save(path)
    sidecar = path.with_suffix(".json")
    sidecar.write_bytes(b'{"status":"rendered","frame":{"snapshot_hash":"earlier-frame"}}\n')
    return path.read_bytes(), sidecar.read_bytes()


def assert_render_pair_failure(path, previous, error):
    import json
    assert (path.read_bytes(), path.with_suffix(".json").read_bytes()) == previous
    diagnostic = json.loads(path.with_suffix(".failed.json").read_text())
    assert diagnostic["status"] == "failed" and diagnostic["output_written"] is False
    assert diagnostic["frame"]["snapshot_hash"] == "exact-hash"
    assert str(error) in diagnostic["error"]
    assert set(p.name for p in path.parent.iterdir()) == {path.name, path.with_suffix(".json").name,
                                                        path.with_suffix(".failed.json").name}


def test_render_pair_context_failure_preserves_earlier_image_and_metadata(tmp_path, monkeypatch):
    r, path = api(), tmp_path / "earlier.png"
    previous = seed_render_pair(path)
    failure = RuntimeError("new context unavailable")
    def fail(**kwargs):
        raise failure
    monkeypatch.setitem(sys.modules, "moderngl", SimpleNamespace(create_standalone_context=fail))
    with pytest.raises(RuntimeError) as caught:
        r.render_native(prepared(), path, width=2, height=2)
    assert caught.value is failure
    assert_render_pair_failure(path, previous, failure)


def test_render_pair_encode_failure_cleans_partial_stage_and_preserves_earlier_pair(tmp_path, monkeypatch):
    from PIL import Image
    r, path, ctx = api(), tmp_path / "earlier.png", Context()
    previous = seed_render_pair(path)
    failure = OSError("PNG encoding failed")
    def fail(self, filename, *args, **kwargs):
        from pathlib import Path
        Path(filename).write_bytes(b"partial new PNG")
        raise failure
    monkeypatch.setattr(Image.Image, "save", fail)
    fake_module(monkeypatch, ctx)
    with pytest.raises(OSError) as caught:
        r.render_native(prepared(), path, width=2, height=2)
    assert caught.value is failure
    assert ctx.released and all(resource.released for resource in ctx.resources)
    assert_render_pair_failure(path, previous, failure)


@pytest.mark.parametrize("phase", ["metadata-write", "png-publish", "metadata-publish"])
def test_render_pair_filesystem_failure_restores_earlier_pair(tmp_path, monkeypatch, phase):
    from pathlib import Path
    r, path, ctx = api(), tmp_path / "earlier.png", Context()
    previous = seed_render_pair(path)
    failure = OSError(phase + " failed")
    original_write, original_replace = Path.write_text, Path.replace
    fired = []
    def write(self, data, *args, **kwargs):
        if phase == "metadata-write" and self.name == path.with_suffix(".json").name:
            fired.append(True)
            raise failure
        return original_write(self, data, *args, **kwargs)
    def replace(self, target):
        target = Path(target)
        expected = path if phase == "png-publish" else path.with_suffix(".json")
        if phase in {"png-publish", "metadata-publish"} and target == expected and not fired:
            fired.append(True)
            raise failure
        return original_replace(self, target)
    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(Path, "replace", replace)
    fake_module(monkeypatch, ctx)
    with pytest.raises(OSError) as caught:
        r.render_native(prepared(), path, width=2, height=2)
    assert caught.value is failure
    assert fired
    assert_render_pair_failure(path, previous, failure)


def test_render_pair_first_failure_only_writes_distinct_failed_diagnostic(tmp_path, monkeypatch):
    import json
    r, path = api(), tmp_path / "first.png"
    failure = RuntimeError("first context unavailable")
    def fail(**kwargs):
        raise failure
    monkeypatch.setitem(sys.modules, "moderngl", SimpleNamespace(create_standalone_context=fail))
    with pytest.raises(RuntimeError) as caught:
        r.render_native(prepared(), path, width=2, height=2)
    assert caught.value is failure
    assert not path.exists() and not path.with_suffix(".json").exists()
    diagnostic = json.loads(path.with_suffix(".failed.json").read_text())
    assert diagnostic["status"] == "failed" and diagnostic["output_written"] is False
    assert diagnostic["frame"]["snapshot_hash"] == "exact-hash"
    assert set(p.name for p in tmp_path.iterdir()) == {"first.failed.json"}


def test_render_pair_diagnostic_failure_does_not_mask_original_context_exception(tmp_path, monkeypatch):
    from pathlib import Path
    r, path = api(), tmp_path / "earlier.png"
    previous = seed_render_pair(path)
    failure = RuntimeError("original context unavailable")
    def fail(**kwargs):
        raise failure
    monkeypatch.setitem(sys.modules, "moderngl", SimpleNamespace(create_standalone_context=fail))
    original_write = Path.write_text
    def write(self, *args, **kwargs):
        if self.name.endswith(".json"):
            raise OSError("diagnostic storage unavailable")
        return original_write(self, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", write)
    with pytest.raises(RuntimeError) as caught:
        r.render_native(prepared(), path, width=2, height=2)
    assert caught.value is failure
    assert (path.read_bytes(), path.with_suffix(".json").read_bytes()) == previous
    assert set(p.name for p in tmp_path.iterdir()) == {"earlier.png", "earlier.json"}



def test_render_pair_first_metadata_publication_failure_removes_new_image(tmp_path, monkeypatch):
    from pathlib import Path
    r, path = api(), tmp_path / "first.png"
    failure = OSError("first metadata publication failed")
    original_replace = Path.replace
    def replace(self, target):
        if Path(target) == path.with_suffix(".json"):
            raise failure
        return original_replace(self, target)
    monkeypatch.setattr(Path, "replace", replace)
    fake_module(monkeypatch, Context())
    with pytest.raises(OSError) as caught:
        r.render_native(prepared(), path, width=2, height=2)
    assert caught.value is failure
    assert not path.exists() and not path.with_suffix(".json").exists()
    assert set(p.name for p in tmp_path.iterdir()) == {"first.failed.json"}


def test_render_pair_failure_does_not_delete_caller_owned_temporary_file(tmp_path, monkeypatch):
    r, path = api(), tmp_path / "earlier.png"
    previous = seed_render_pair(path)
    unrelated = path.with_name(path.name + ".tmp")
    unrelated.write_bytes(b"caller-owned scratch bytes")
    failure = RuntimeError("new context unavailable")
    def fail(**kwargs):
        raise failure
    monkeypatch.setitem(sys.modules, "moderngl", SimpleNamespace(create_standalone_context=fail))
    with pytest.raises(RuntimeError):
        r.render_native(prepared(), path, width=2, height=2)
    assert unrelated.read_bytes() == b"caller-owned scratch bytes"
    assert (path.read_bytes(), path.with_suffix(".json").read_bytes()) == previous
    assert set(p.name for p in tmp_path.iterdir()) == {"earlier.png", "earlier.json", "earlier.png.tmp", "earlier.failed.json"}



@pytest.mark.parametrize("phase", ["png", "metadata"])
def test_render_pair_publication_error_after_replacement_restores_both_old_files(tmp_path, monkeypatch, phase):
    from pathlib import Path
    r, path = api(), tmp_path / "earlier.png"
    previous = seed_render_pair(path)
    failure = OSError(phase + " publication result unavailable")
    original_replace = Path.replace
    target_to_fail = path if phase == "png" else path.with_suffix(".json")
    fired = []
    def replace(self, target):
        result = original_replace(self, target)
        if Path(target) == target_to_fail and not fired:
            fired.append(True)
            raise failure
        return result
    monkeypatch.setattr(Path, "replace", replace)
    fake_module(monkeypatch, Context())
    with pytest.raises(OSError) as caught:
        r.render_native(prepared(), path, width=2, height=2)
    assert caught.value is failure
    assert_render_pair_failure(path, previous, failure)
