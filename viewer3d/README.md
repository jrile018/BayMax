# CPU replay scene preparation

viewer3d prepares internal immutable scene descriptors from one authoritative replay frame. It does not define the shared JSON envelope. Root integration must map accepted shared records into these dataclasses once the envelope is frozen.

## API and coordinate contract

Call build_scene(SceneInput(...), limits=SceneLimits(...)) to get a PreparedScene. Validation failures raise ValueError. All collections and point/index arrays are tuples. No external packages or GPU/graphics imports are required.

- MetricPoint(x_m, y_m, z_m): supplied metric coordinates, z increasing upward. Declare metric_crs, metric_origin and horizontal_units="metres". Missing, unknown, feet or degree units are rejected; no geodetic conversion or coordinate inference occurs. CRS/units are declarations, not an audit: the root transport adapter must verify actual CRS units before constructing SceneInput.
- FrameIdentity(run_id, scenario_id, time_s, snapshot_hash): nonnegative seconds from scenario epoch. Every primitive must have exactly this identity.
- SourceMetadata(source_id, provider, license_id, reference, independently_sourced, assumptions=()): retained per primitive and as an ordered deduplicated source manifest. Missing/unknown/unlicensed permission, conflicting declarations for the same source ID, declared non-independent geometry and Google markers are rejected. Source declarations are caller evidence; this code cannot audit an actual license or detect concealed Google derivation.
- SceneBounds(minimum, maximum): explicit metric volume. Geometry and supplied building roof extent must fit; invalid input is rejected rather than clipped.
- TerrainPatch: supplied points and triangle indices, copied unchanged.
- PolylineRecord: supplied road edge or completed trail geometry.
- PolygonRecord: fire perimeter, as a simple open XY ring. No inferred spread, access or burn outcomes.
- BuildingRecord: simple open XY footprint and optional positive height_m. Missing height produces an unchanged footprint with height_status="absent" and no roof mesh. Supplied height is labeled supplied; adding height_assumption labels it assumed and retains that assumption.
- RouteRecord: exact polyline, nonnegative integer route_version, role candidate, committed or previous. Styles are respectively dashed, solid and dash-dot. Trails are dotted. IDs/roles remain available for text labels.
- UnitRecord: exact authoritative position, with civilian kind ambulance, bus, supply_truck, rescue_vehicle or fire_engine. Markers have no invented dimensions, orientation or travel.
- AidRecord: supplied location, kind and status; no resource allocation or completed-service count is calculated.

Primitive contains kind, record ID, frame, full source metadata and exact point tuple, plus relevant mesh indices/role/style/route version/height/status. Terrain is the only indexed mesh; building/fire polygons remain descriptors for a later renderer to tessellate. Output follows category order (terrain, roads, buildings, fires, routes, trails, units, aid), preserving order within each input category. Duplicate IDs are rejected within each primitive kind. Record classes must match the category exactly; RouteRecord is rejected under roads/trails to prevent dropping authoritative route metadata.

Limits default to 10,000 primitives, 100,000 point references, 100,000 triangles, 256 vertices per polygon and a 10,000m maximum extent on each axis. These bound CPU preparation; polygon validation is quadratic in the separately bounded polygon size. Empty categories remain empty. No terrain, roads or positions are synthesized for missing records.

    from viewer3d import (
        FrameIdentity, MetricPoint, SceneBounds, SceneInput,
        SourceMetadata, UnitRecord, build_scene,
    )

    frame = FrameIdentity("training-run", "fixture", 12.5, "authoritative-hash")
    source = SourceMetadata(
        "tiny-fixture", "independent fixture", "CC0-1.0", "fixture://tiny", True,
        ("constructed training geometry",),
    )
    prepared = build_scene(SceneInput(
        frame=frame,
        metric_crs="LOCAL_METRIC:fixture",
        metric_origin="fixture local origin",
        horizontal_units="metres",
        bounds=SceneBounds(MetricPoint(0, 0, 0), MetricPoint(100, 100, 30)),
        units=(UnitRecord("ambulance-1", frame, source, "ambulance",
                          MetricPoint(4.25, 1.5, 0.75)),),
    ))

## Server test evidence

All authoring and tests ran on the supplied cloud worktree /workspace/knight26/worktrees/amd using /opt/venv/bin/python. Tests run in detached tmux, pinned with taskset to the first two available CPUs, with OMP_NUM_THREADS=2, OPENBLAS_NUM_THREADS=2, MKL_NUM_THREADS=2.

- evidence/red.log: 38 failed in 0.30s, exit1, expected missing projection assertion before implementation.
- evidence/green.log: initial 38 passed in 0.05s, exit0.
- evidence/regression-red.log: 3 failed/41 passed in 0.09s, exit1; caught unknown license acceptance and malformed route role exception.
- evidence/review-red.log: 7 failed/44 passed in 0.11s, exit1; reproduced route-category metadata loss and missing explicit unit declaration.
- evidence/review-green.log: focused post-review regressions.
- evidence/final-green.log: final owned suite post-review command/results and exit code.

Reproduce the owned suite with:

    CPUS=$(/opt/venv/bin/python -c 'import os; print(",".join(map(str, sorted(os.sched_getaffinity(0))[:2])))')
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 \
      taskset -c "$CPUS" /opt/venv/bin/python -m pytest viewer3d/tests -q -p no:cacheprovider

This checkpoint prepares data only. No raster image, graphics context, FSR provider, GPU lease, renderer/shared-envelope integration, pathfinding, interpolation, physics or simulated outcome is established by these tests.
