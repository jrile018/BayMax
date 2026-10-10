"""CPU geometry preparation and an explicitly invoked native EGL renderer.

Importing this module, preparing buffers, and computing cameras never import
graphics/ML packages or create a context. render_native requires an externally
obtained GPU lease. It neither obtains nor certifies that lease.
"""
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import importlib
import json
import math
from pathlib import Path
import struct

from .scene import MetricPoint, PreparedScene, Primitive, SceneBounds


@dataclass(frozen=True)
class DrawBatch:
    primitive: Primitive
    vertices: tuple[MetricPoint, ...]
    triangles: tuple[tuple[int, int, int], ...] = ()
    lines: tuple[tuple[int, int], ...] = ()
    points: tuple[int, ...] = ()


@dataclass(frozen=True)
class RenderBuffers:
    scene: PreparedScene
    batches: tuple[DrawBatch, ...]


def _orient(a, b, c):
    return (b.x_m-a.x_m)*(c.y_m-a.y_m)-(b.y_m-a.y_m)*(c.x_m-a.x_m)


def _triangulate(points):
    """Ear-clip a validated simple XY ring, without moving its vertices."""
    area = sum(_orient(points[0], points[i], points[i+1]) for i in range(1, len(points)-1))
    sign = 1 if area > 0 else -1
    remaining, result = list(range(len(points))), []
    while len(remaining) > 3:
        clipped = False
        for j, b in enumerate(remaining):
            a, c = remaining[j-1], remaining[(j+1) % len(remaining)]
            if sign * _orient(points[a], points[b], points[c]) <= 0:
                continue
            if any(
                all(sign * _orient(points[u], points[v], points[k]) >= 0
                    for u, v in ((a, b), (b, c), (c, a)))
                for k in remaining if k not in (a, b, c)
            ):
                continue
            result.append((a, b, c))
            del remaining[j]
            clipped = True
            break
        if not clipped:
            # Collinear boundary vertices have no area. Keep them in the buffer
            # and outline, removing only their redundant tessellation index.
            for j, b in enumerate(remaining):
                a, c = remaining[j-1], remaining[(j+1) % len(remaining)]
                if _orient(points[a], points[b], points[c]) == 0:
                    del remaining[j]
                    clipped = True
                    break
        if not clipped:
            raise ValueError("cannot tessellate prepared polygon")
    if len(remaining) == 3 and _orient(*(points[i] for i in remaining)) != 0:
        result.append(tuple(remaining))
    return tuple(result)


def build_render_buffers(scene: PreparedScene) -> RenderBuffers:
    """Retain source geometry and frame identity; derive only explicit roofs.

    PreparedScene from build_scene is the validation authority. No conversion,
    clipping, route recomputation, interpolation or inferred terrain occurs.
    """
    if not isinstance(scene, PreparedScene):
        raise ValueError("PreparedScene required")
    batches = []
    for primitive in scene.primitives:
        vertices = primitive.points
        triangles, lines, markers = (), (), ()
        n = len(vertices)
        if primitive.kind == "terrain":
            triangles = primitive.triangles
        elif primitive.kind in {"road", "route", "trail"}:
            lines = tuple((i, i+1) for i in range(n-1))
        elif primitive.kind in {"building", "fire"}:
            lines = tuple((i, (i+1) % n) for i in range(n))
            if primitive.kind == "fire":
                triangles = _triangulate(vertices)
            elif primitive.height_m is not None:
                roof = tuple(MetricPoint(p.x_m, p.y_m, p.z_m+primitive.height_m) for p in vertices)
                triangles = tuple(tuple(i+n for i in t) for t in _triangulate(vertices))
                walls = []
                for i in range(n):
                    j = (i+1) % n
                    walls.extend(((i, j, j+n), (i, j+n, i+n)))
                triangles += tuple(walls)
                vertices += roof
                lines += tuple((i+n, (i+1) % n+n) for i in range(n))
                lines += tuple((i, i+n) for i in range(n))
        elif primitive.kind in {"unit", "aid"}:
            markers = tuple(range(n))
        else:
            raise ValueError(f"unsupported prepared primitive kind: {primitive.kind}")
        batches.append(DrawBatch(primitive, vertices, triangles, lines, markers))
    return RenderBuffers(scene, tuple(batches))


def _xyz(point):
    return point.x_m, point.y_m, point.z_m


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]


def _unit(v):
    length = math.hypot(*v)
    return tuple(x / length for x in v)


def _multiply(a, b):
    return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)) for i in range(4))


def _dimensions(width, height):
    if any(type(v) is not int or v <= 0 for v in (width, height)):
        raise ValueError("image dimensions must be positive integers")
    # Bound standalone readback/allocation work before creating a GPU context.
    if width > 16384 or height > 16384 or width*height > 16777216:
        raise ValueError("image dimensions exceed render budget")


@dataclass(frozen=True)
class Camera:
    eye: MetricPoint
    target: MetricPoint
    aspect: float
    near: float
    far: float
    view_projection: tuple[tuple[float, ...], ...]

    def project(self, point: MetricPoint) -> tuple[float, float, float]:
        """Project world metres to NDC; matrix acts on target-relative metres."""
        value = tuple(a-b for a, b in zip(_xyz(point), _xyz(self.target))) + (1,)
        clip = tuple(_dot(row, value) for row in self.view_projection)
        return tuple(v / clip[3] for v in clip[:3])


def camera_for_bounds(bounds: SceneBounds, width=1280, height=720) -> Camera:
    """Deterministic elevated, z-up perspective covering the full bounds."""
    _dimensions(width, height)
    if not isinstance(bounds, SceneBounds):
        raise ValueError("SceneBounds required")
    low, high = _xyz(bounds.minimum), _xyz(bounds.maximum)
    if any(not math.isfinite(v) for v in low+high) or any(a > b for a, b in zip(low, high)):
        raise ValueError("finite ordered bounds required")
    spans = tuple(b-a for a, b in zip(low, high))
    if any(not math.isfinite(v) for v in spans):
        raise ValueError("bounds cannot produce finite camera extent")
    center = tuple(a+span/2 for a, span in zip(low, spans))
    radius = max(.5, math.hypot(*(b-a for a, b in zip(low, high)))/2)
    aspect = width / height
    half_vertical = math.radians(22.5)
    half_horizontal = math.atan(math.tan(half_vertical)*aspect)
    distance = 1.15 * radius / math.sin(min(half_vertical, half_horizontal))
    direction = _unit((1, -1, 1.2))
    local_eye = tuple(v*distance for v in direction)
    eye = MetricPoint(*(c+v for c, v in zip(center, local_eye)))
    forward = tuple(-v for v in direction)
    right = _unit(_cross(forward, (0, 0, 1)))
    up = _cross(right, forward)
    view = (
        right + (-_dot(right, local_eye),),
        up + (-_dot(up, local_eye),),
        tuple(-v for v in forward) + (_dot(forward, local_eye),),
        (0, 0, 0, 1),
    )
    near, far = max(.01, distance-radius*1.5), distance+radius*1.5
    f = 1 / math.tan(half_vertical)
    projection = (
        (f/aspect, 0, 0, 0), (0, f, 0, 0),
        (0, 0, (far+near)/(near-far), 2*far*near/(near-far)),
        (0, 0, -1, 0),
    )
    matrix = _multiply(projection, view)
    if any(not math.isfinite(v) for v in _xyz(eye)+center+(near, far)+tuple(v for row in matrix for v in row)):
        raise ValueError("bounds cannot produce finite camera projection")
    return Camera(eye, MetricPoint(*center), aspect, near, far, matrix)


_VERTEX_SHADER = """
#version 330
in vec3 in_position;
in float in_distance;
noperspective out float line_distance;
uniform mat4 view_projection;
uniform float point_size;
void main() {
    gl_Position = view_projection * vec4(in_position, 1.0);
    gl_PointSize = point_size;
    line_distance = in_distance;
}
"""
_FRAGMENT_SHADER = """
#version 330
noperspective in float line_distance;
uniform vec3 color;
uniform int line_style;
uniform int marker;
out vec4 frag_color;
void main() {
    float phase = mod(line_distance, 18.0);
    if (line_style == 1 && phase > 10.0) discard;
    if (line_style == 2 && phase > 2.0) discard;
    if (line_style == 3 && phase > 9.0 && (phase < 13.0 || phase > 15.0)) discard;
    if (marker == 1 && length(gl_PointCoord - vec2(0.5)) > 0.5) discard;
    if (marker == 2 && abs(gl_PointCoord.x - 0.5) + abs(gl_PointCoord.y - 0.5) > 0.5) discard;
    frag_color = vec4(color, 1.0);
}
"""
_COLORS = {
    "terrain": (.25, .40, .30), "road": (.75, .77, .80),
    "building": (.60, .64, .70), "fire": (.95, .25, .08),
    "trail": (.65, .70, .85), "unit": (.10, .75, .95), "aid": (1., .80, .1),
}
_ROUTE_COLORS = {"candidate": (.75, .50, 1.), "committed": (.1, .95, .6), "previous": (.75, .7, .5)}
_STYLES = {"solid": 0, "dashed": 1, "dotted": 2, "dash-dot": 3}
_SOFTWARE = ("llvmpipe", "softpipe", "software", "swiftshader", "swrast", "lavapipe")


def render_native(scene: PreparedScene, output_png, *, width=1280, height=720,
                  require_hardware=True, gl_library=None, egl_library=None):
    """Execute native EGL rendering only after caller acquires a GPU lease.

    Isolated ModernGL/glcontext packages must be available through the caller's
    Python runtime/PYTHONPATH. Optional libgl/libegl hints and glcontext's
    GLCONTEXT_* environment variables configure native driver discovery.
    Real GL provider strings are recorded, but do not certify physical allocation.
    Software providers are rejected by default. FSR is not implemented.
    """
    _dimensions(width, height)
    buffers = build_render_buffers(scene)
    camera = camera_for_bounds(scene.bounds, width, height)
    output = Path(output_png)
    if output.suffix.casefold() != ".png":
        raise ValueError("output must use .png extension")
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "status": "failed", "backend": "egl", "required_opengl": "3.3",
        "provider": {}, "frame": asdict(scene.frame),
        "metric_crs": scene.metric_crs, "metric_origin": scene.metric_origin,
        "horizontal_units": scene.horizontal_units, "bounds": asdict(scene.bounds),
        "sources": [asdict(source) for source in scene.sources],
        "primitives": [dict(source_id=b.primitive.source.source_id,
                            points=[asdict(p) for p in b.primitive.points],
                            triangles=b.primitive.triangles, **{
            name: getattr(b.primitive, name) for name in
            ("kind", "record_id", "role", "line_style", "route_version",
             "height_m", "height_status", "height_assumption", "status")})
            for b in buffers.batches],
        "camera": asdict(camera), "width": width, "height": height,
        "hardware_required": bool(require_hardware), "output_written": False,
        "fsr": "not implemented",
        "lease": "caller-managed; not certified by renderer",
        "line_patterns": "projected cumulative display distance; original vertices retained",
    }
    temporary = output.with_name(output.name + ".tmp")
    try:
        # These are the only graphics imports in this module.
        moderngl = importlib.import_module("moderngl")
        image_api = importlib.import_module("PIL.Image")
        kwargs = {"require": 330, "backend": "egl"}
        if gl_library is not None:
            kwargs["libgl"] = gl_library
        if egl_library is not None:
            kwargs["libegl"] = egl_library
        with ExitStack() as stack:
            def track(resource):
                stack.callback(resource.release)
                return resource
            ctx = track(moderngl.create_standalone_context(**kwargs))
            metadata["provider"] = {key: ctx.info.get(key) for key in ("GL_VENDOR", "GL_RENDERER", "GL_VERSION")}
            if any(not isinstance(v, str) or not v.strip() for v in metadata["provider"].values()):
                raise RuntimeError("native context provider metadata missing")
            description = " ".join(metadata["provider"].values()).casefold()
            metadata["software_detected"] = any(token in description for token in _SOFTWARE)
            if require_hardware and metadata["software_detected"]:
                raise RuntimeError("software OpenGL provider cannot prove allocated GPU rendering")
            color = track(ctx.texture((width, height), 3))
            depth = track(ctx.depth_renderbuffer((width, height)))
            framebuffer = track(ctx.framebuffer(color_attachments=[color], depth_attachment=depth))
            framebuffer.use()
            ctx.viewport = (0, 0, width, height)
            ctx.enable(moderngl.DEPTH_TEST | moderngl.PROGRAM_POINT_SIZE)
            framebuffer.clear(.07, .09, .12, 1., depth=1.)
            program = track(ctx.program(vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER))
            matrix = tuple(camera.view_projection[i][j] for j in range(4) for i in range(4))
            program["view_projection"].write(struct.pack("<16f", *matrix))
            program["point_size"].value = 10.
            origin = _xyz(camera.target)
            # Draw filled surfaces, then their exact outlines, then exact glyph
            # centers. Raster depth offset avoids shifting metric geometry.
            for topology, mode in (("triangles", moderngl.TRIANGLES), ("lines", moderngl.LINES), ("points", moderngl.POINTS)):
                ctx.polygon_offset = (1., 1.) if topology == "triangles" else (0., 0.)
                for batch in buffers.batches:
                    indices = getattr(batch, topology)
                    if not indices:
                        continue
                    primitive = batch.primitive
                    rgb = _ROUTE_COLORS[primitive.role] if primitive.kind == "route" else _COLORS[primitive.kind]
                    program["color"].value = rgb
                    program["line_style"].value = _STYLES.get(primitive.line_style, 0) if topology == "lines" else 0
                    program["marker"].value = (2 if primitive.kind == "aid" else 1) if topology == "points" else 0
                    flat_indices = indices if topology == "points" else tuple(i for group in indices for i in group)
                    distances = [0.] * len(batch.vertices)
                    if topology == "lines" and primitive.line_style != "solid":
                        projected = [camera.project(p) for p in batch.vertices]
                        for i, (a, b) in enumerate(zip(projected, projected[1:]), 1):
                            distances[i] = distances[i-1] + math.hypot((b[0]-a[0])*width/2, (b[1]-a[1])*height/2)
                    values = tuple(value for i in flat_indices
                                   for value in tuple(a-b for a, b in zip(_xyz(batch.vertices[i]), origin))+(distances[i],))
                    vbo = track(ctx.buffer(struct.pack(f"<{len(values)}f", *values)))
                    vao = track(ctx.vertex_array(program, [(vbo, "3f 1f", "in_position", "in_distance")]))
                    vao.render(mode=mode)
            pixels = framebuffer.read(components=3, alignment=1)
            image = image_api.frombytes("RGB", (width, height), pixels)
            flipped = image.transpose(image_api.Transpose.FLIP_TOP_BOTTOM)
            try:
                flipped.save(temporary, format="PNG")
            finally:
                flipped.close()
                image.close()
        # Context and all attachments have been released before publishing.
        temporary.replace(output)
        metadata.update(status="rendered", output_written=True)
    except Exception as error:
        metadata.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        if temporary.exists():
            temporary.unlink()
        output.with_suffix(".json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    return json.loads(json.dumps(metadata))
