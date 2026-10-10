"""Internal CPU projection of one authoritative metric replay frame.

No transport adapter, travel progression, solver, renderer or GPU imports.
x/y are projected metres; z is elevation in metres, increasing upward.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class MetricPoint:
    x_m: float
    y_m: float
    z_m: float


@dataclass(frozen=True)
class FrameIdentity:
    run_id: str
    scenario_id: str
    time_s: float
    snapshot_hash: str


@dataclass(frozen=True)
class SourceMetadata:
    source_id: str
    provider: str
    license_id: str
    reference: str
    independently_sourced: bool
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneBounds:
    minimum: MetricPoint
    maximum: MetricPoint


@dataclass(frozen=True)
class Record:
    record_id: str
    frame: FrameIdentity
    source: SourceMetadata


@dataclass(frozen=True)
class TerrainPatch(Record):
    points: tuple[MetricPoint, ...]
    triangles: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class PolylineRecord(Record):
    points: tuple[MetricPoint, ...]


@dataclass(frozen=True)
class PolygonRecord(Record):
    points: tuple[MetricPoint, ...]


@dataclass(frozen=True)
class BuildingRecord(Record):
    footprint: tuple[MetricPoint, ...]
    height_m: float | None = None
    height_assumption: str | None = None


@dataclass(frozen=True)
class RouteRecord(PolylineRecord):
    route_version: int
    role: str


@dataclass(frozen=True)
class UnitRecord(Record):
    kind: str
    position: MetricPoint


@dataclass(frozen=True)
class AidRecord(Record):
    kind: str
    position: MetricPoint
    status: str


@dataclass(frozen=True)
class SceneInput:
    frame: FrameIdentity
    metric_crs: str
    metric_origin: str
    bounds: SceneBounds
    horizontal_units: str | None = None
    terrain: tuple[TerrainPatch, ...] = ()
    roads: tuple[PolylineRecord, ...] = ()
    buildings: tuple[BuildingRecord, ...] = ()
    fires: tuple[PolygonRecord, ...] = ()
    routes: tuple[RouteRecord, ...] = ()
    trails: tuple[PolylineRecord, ...] = ()
    units: tuple[UnitRecord, ...] = ()
    aid: tuple[AidRecord, ...] = ()


@dataclass(frozen=True)
class SceneLimits:
    max_primitives: int = 10000
    max_points: int = 100000
    max_triangles: int = 100000
    max_extent_m: float = 10000
    max_polygon_points: int = 256


@dataclass(frozen=True)
class Primitive:
    kind: str
    record_id: str
    frame: FrameIdentity
    source: SourceMetadata
    points: tuple[MetricPoint, ...]
    triangles: tuple[tuple[int, int, int], ...] = ()
    role: str | None = None
    line_style: str | None = None
    route_version: int | None = None
    height_m: float | None = None
    height_status: str | None = None
    height_assumption: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class PreparedScene:
    frame: FrameIdentity
    metric_crs: str
    metric_origin: str
    horizontal_units: str
    bounds: SceneBounds
    primitives: tuple[Primitive, ...]
    sources: tuple[SourceMetadata, ...]


_UNIT_KINDS = frozenset({"ambulance", "bus", "supply_truck", "rescue_vehicle", "fire_engine"})
_ROUTE_STYLES = {"candidate": "dashed", "committed": "solid", "previous": "dash-dot"}
_GROUPS = (
    ("terrain", TerrainPatch), ("roads", PolylineRecord),
    ("buildings", BuildingRecord), ("fires", PolygonRecord),
    ("routes", RouteRecord), ("trails", PolylineRecord),
    ("units", UnitRecord), ("aid", AidRecord),
)
_KINDS = {"roads": "road", "buildings": "building", "fires": "fire",
          "routes": "route", "trails": "trail", "units": "unit"}


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


def _number(value, label):
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{label} must be finite")


def _point(point):
    if not isinstance(point, MetricPoint):
        raise ValueError("coordinate must be a MetricPoint")
    for coordinate in (point.x_m, point.y_m, point.z_m):
        _number(coordinate, "coordinate")


def _inside(point, bounds):
    _point(point)
    if not all(low <= value <= high for low, value, high in zip(
        (bounds.minimum.x_m, bounds.minimum.y_m, bounds.minimum.z_m),
        (point.x_m, point.y_m, point.z_m),
        (bounds.maximum.x_m, bounds.maximum.y_m, bounds.maximum.z_m),
    )):
        raise ValueError("coordinate outside scene bounds")


def _frame(frame):
    if not isinstance(frame, FrameIdentity):
        raise ValueError("frame identity missing")
    for name in ("run_id", "scenario_id", "snapshot_hash"):
        _text(getattr(frame, name), f"frame {name}")
    _number(frame.time_s, "frame time")
    if frame.time_s < 0:
        raise ValueError("frame time must be nonnegative")


def _source(source):
    if not isinstance(source, SourceMetadata):
        raise ValueError("source provenance missing")
    for name in ("source_id", "provider", "license_id", "reference"):
        _text(getattr(source, name), f"source {name}")
    if source.license_id.strip().casefold() in {"unknown", "unlicensed", "none", "unavailable", "not licensed"}:
        raise ValueError("source license permission is unknown or absent")
    if source.independently_sourced is not True:
        raise ValueError("source must declare independent geometry")
    if not isinstance(source.assumptions, tuple):
        raise ValueError("source assumptions must be an immutable tuple")
    for assumption in source.assumptions:
        _text(assumption, "source assumption")
    evidence = (source.source_id, source.provider, source.license_id,
                source.reference, *source.assumptions)
    if any("google" in value.casefold() for value in evidence):
        raise ValueError("Google-derived geography cannot be projected")


def _orient(a, b, c):
    return (b.x_m - a.x_m) * (c.y_m - a.y_m) - (b.y_m - a.y_m) * (c.x_m - a.x_m)


def _intersect(a, b, c, d):
    ab_c, ab_d, cd_a, cd_b = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    if ((ab_c > 0 > ab_d or ab_d > 0 > ab_c)
            and (cd_a > 0 > cd_b or cd_b > 0 > cd_a)):
        return True
    def on_segment(a, b, p):
        return (min(a.x_m, b.x_m) <= p.x_m <= max(a.x_m, b.x_m)
                and min(a.y_m, b.y_m) <= p.y_m <= max(a.y_m, b.y_m))
    return ((ab_c == 0 and on_segment(a, b, c))
            or (ab_d == 0 and on_segment(a, b, d))
            or (cd_a == 0 and on_segment(c, d, a))
            or (cd_b == 0 and on_segment(c, d, b)))


def _polygon(points, limits):
    if len(points) < 3:
        raise ValueError("polygon requires three vertices")
    if len(points) > limits.max_polygon_points:
        raise ValueError("polygon vertex limit exceeded")
    xy = tuple((p.x_m, p.y_m) for p in points)
    if len(set(xy)) != len(xy):
        raise ValueError("polygon ring must be open with distinct XY vertices")
    # Translate to the first vertex to avoid cancellation at large metric origins.
    area = sum(_orient(points[0], points[i], points[i + 1]) for i in range(1, len(points) - 1))
    if area == 0:
        raise ValueError("polygon must have nonzero XY area")
    count = len(points)
    for i in range(count):
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue
            if _intersect(points[i], points[(i + 1) % count], points[j], points[(j + 1) % count]):
                raise ValueError("polygon self-intersection")


def _terrain(record):
    if not record.triangles:
        raise ValueError("terrain requires triangle indices")
    for triangle in record.triangles:
        if (not isinstance(triangle, tuple) or len(triangle) != 3
                or any(type(index) is not int or not 0 <= index < len(record.points) for index in triangle)
                or len(set(triangle)) != 3):
            raise ValueError("malformed terrain triangle")
        a, b, c = (record.points[index] for index in triangle)
        u = (b.x_m - a.x_m, b.y_m - a.y_m, b.z_m - a.z_m)
        v = (c.x_m - a.x_m, c.y_m - a.y_m, c.z_m - a.z_m)
        if (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]) == (0, 0, 0):
            raise ValueError("degenerate terrain triangle")


def build_scene(data: SceneInput, *, limits: SceneLimits = SceneLimits()) -> PreparedScene:
    """Validate and project an exact frame; reject rather than clip or fill gaps.

    Output order follows fixed category order and input record order. Primitive
    points are the supplied immutable tuples. Building height is a descriptor,
    never an invented roof mesh. Source declarations are retained, not audited.
    """
    if not isinstance(data, SceneInput) or not isinstance(limits, SceneLimits):
        raise ValueError("typed scene input and limits required")
    for name in ("max_primitives", "max_points", "max_triangles", "max_polygon_points"):
        value = getattr(limits, name)
        if type(value) is not int or value < 0:
            raise ValueError("scene count limit must be a nonnegative integer")
    _number(limits.max_extent_m, "extent limit")
    if limits.max_extent_m <= 0:
        raise ValueError("extent limit must be positive")
    _frame(data.frame)
    _text(data.metric_crs, "metric CRS")
    _text(data.metric_origin, "metric origin")
    if data.horizontal_units != "metres":
        raise ValueError("horizontal units must explicitly be metres")
    if ("4326" in data.metric_crs or any(token in data.metric_crs.casefold()
        for token in ("wgs84", "wgs 84", "longlat", "lonlat", "degrees"))):
        raise ValueError("metric CRS required, not longitude/latitude")
    if not isinstance(data.bounds, SceneBounds):
        raise ValueError("scene bounds required")
    _point(data.bounds.minimum)
    _point(data.bounds.maximum)
    spans = tuple(high - low for low, high in zip(
        (data.bounds.minimum.x_m, data.bounds.minimum.y_m, data.bounds.minimum.z_m),
        (data.bounds.maximum.x_m, data.bounds.maximum.y_m, data.bounds.maximum.z_m),
    ))
    if any(span < 0 for span in spans):
        raise ValueError("scene bounds reversed")
    if any(span > limits.max_extent_m for span in spans):
        raise ValueError("scene bounds extent limit exceeded")

    # Budget geometry before polygon checks or descriptor construction.
    rows = []
    point_count = triangle_count = 0
    for group, record_type in _GROUPS:
        records = getattr(data, group)
        if not isinstance(records, tuple):
            raise ValueError("record collections must be immutable tuples")
        if len(rows) + len(records) > limits.max_primitives:
            raise ValueError("primitive limit exceeded")
        for record in records:
            if type(record) is not record_type:
                raise ValueError(f"malformed {group} record")
            if group in ("units", "aid"):
                points = (record.position,)
            elif group == "buildings":
                points = record.footprint
            else:
                points = record.points
            if not isinstance(points, tuple):
                raise ValueError("geometry must be an immutable tuple")
            point_count += len(points)
            if point_count > limits.max_points:
                raise ValueError("point limit exceeded")
            if group == "terrain":
                if not isinstance(record.triangles, tuple):
                    raise ValueError("triangle indices must be an immutable tuple")
                triangle_count += len(record.triangles)
                if triangle_count > limits.max_triangles:
                    raise ValueError("triangle limit exceeded")
            rows.append((group, record, points))

    result, sources, seen = [], {}, set()
    for group, record, points in rows:
        _text(record.record_id, "record ID")
        _frame(record.frame)
        if record.frame != data.frame:
            raise ValueError("mixed frame identity")
        kind = _KINDS.get(group, group)
        key = kind, record.record_id
        if key in seen:
            raise ValueError("duplicate record ID within primitive kind")
        seen.add(key)
        _source(record.source)
        existing = sources.get(record.source.source_id)
        if existing is not None and existing != record.source:
            raise ValueError("conflicting source provenance for source ID")
        sources[record.source.source_id] = record.source
        for point in points:
            _inside(point, data.bounds)
        extra = {}
        if group == "terrain":
            _terrain(record)
            extra["triangles"] = record.triangles
        elif group in ("roads", "routes", "trails"):
            if len(points) < 2 or any(a == b for a, b in zip(points, points[1:])):
                raise ValueError("polyline requires distinct consecutive vertices")
            extra["line_style"] = "solid" if group == "roads" else "dotted"
            if group == "routes":
                if type(record.route_version) is not int or record.route_version < 0:
                    raise ValueError("route version must be a nonnegative integer")
                _text(record.role, "route role")
                if record.role not in _ROUTE_STYLES:
                    raise ValueError("unsupported route role")
                extra.update(role=record.role, route_version=record.route_version,
                             line_style=_ROUTE_STYLES[record.role])
        elif group in ("buildings", "fires"):
            _polygon(points, limits)
            if group == "buildings":
                status = "absent"
                if record.height_assumption is not None:
                    _text(record.height_assumption, "building height assumption")
                if record.height_m is not None:
                    _number(record.height_m, "building height")
                    if record.height_m <= 0:
                        raise ValueError("building height must be positive")
                    for point in points:
                        _inside(MetricPoint(point.x_m, point.y_m, point.z_m + record.height_m), data.bounds)
                    status = "assumed" if record.height_assumption is not None else "supplied"
                extra.update(height_m=record.height_m, height_status=status,
                             height_assumption=record.height_assumption)
        elif group == "units":
            _text(record.kind, "unit kind")
            if record.kind not in _UNIT_KINDS:
                raise ValueError("unsupported civilian unit kind")
            extra["role"] = record.kind
        elif group == "aid":
            _text(record.kind, "aid kind")
            _text(record.status, "aid status")
            extra.update(role=record.kind, status=record.status)
        result.append(Primitive(kind, record.record_id, record.frame, record.source, points, **extra))
    return PreparedScene(frame=data.frame, metric_crs=data.metric_crs,
                         metric_origin=data.metric_origin, horizontal_units=data.horizontal_units,
                         bounds=data.bounds, primitives=tuple(result), sources=tuple(sources.values()))
