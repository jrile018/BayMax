"""CPU-only internal scene projection. Transport integration remains root-owned."""
from .scene import (
    AidRecord, BuildingRecord, FrameIdentity, MetricPoint, PolygonRecord,
    PolylineRecord, PreparedScene, Primitive, RouteRecord, SceneBounds,
    SceneInput, SceneLimits, SourceMetadata, TerrainPatch, UnitRecord, build_scene,
)

__all__ = [
    "AidRecord", "BuildingRecord", "FrameIdentity", "MetricPoint", "PolygonRecord",
    "PolylineRecord", "PreparedScene", "Primitive", "RouteRecord", "SceneBounds",
    "SceneInput", "SceneLimits", "SourceMetadata", "TerrainPatch", "UnitRecord", "build_scene",
]
