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

## Native EGL renderer preparation

Import CPU functions directly from viewer3d.render:

    from viewer3d.render import build_render_buffers, camera_for_bounds, render_native
    buffers = build_render_buffers(prepared)
    camera = camera_for_bounds(prepared.bounds, 1280, 720)

DrawBatch retains its original Primitive reference, frame identity, source, roles, statuses and authoritative point tuple. Terrain indices remain exact; roads, routes and trails join supplied vertices. Concave fire rings are tessellated without moving vertices. Supplied or explicitly assumed positive building heights produce roof/wall vertices by adding only height_m to z. Absent heights produce only the original footprint outline. Unit and aid glyph centers remain the exact supplied positions. This is display preparation: no route computation, interpolation, physics, inferred height or terrain is performed.

Camera projection uses x/y ground metres and z-up elevation, fits all bounds corners with an elevated perspective, rejects invalid image dimensions and nonfinite derived camera arithmetic, and recenters GPU float uploads around the bounds center while keeping original CPU coordinates unchanged. Matrix upload is column-major. Route/trail dash styles use cumulative projected display distance, independent of line angle; line glyphs and point sizes are visual symbols, not inferred metric dimensions. Polygon depth offset adjusts raster depth only.

Only an explicit render_native call imports ModernGL and Pillow and creates a standalone EGL context requesting OpenGL 3.3. The caller must acquire the allocated GPU lease before calling it. Supply the isolated ModernGL/glcontext package directory on PYTHONPATH; do not install or import Torch for this renderer. Optional gl_library and egl_library arguments map to glcontext libgl/libegl hints; glcontext also honors GLCONTEXT_LINUX_LIBGL, GLCONTEXT_LINUX_LIBEGL and device-selection environment variables. Driver prerequisites must be staged externally. Future isolated runtime pins are ModernGL 5.13.0 and glcontext 3.1.0 (see platform/native-runtime-requirements.txt); neither pinned runtime has been downloaded, installed or exercised here. CPU tests supply a fake ModernGL module and establish no compatibility proof for those native package versions.

After prerequisites and a GPU lease are available:

    # This operation creates an actual native context; it was not run at this checkpoint.
    metadata = render_native(
        prepared, "/path/to/native.png", width=1280, height=720,
        require_hardware=True,
        gl_library="/path/to/libGL.so", egl_library="/path/to/libEGL.so",
    )

Rendering draws depth-tested colored terrain/buildings/fire surfaces, exact road/route/trail outlines and unit/aid glyphs. PNG readback flips bottom-up OpenGL rows. The adjacent .json sidecar retains the original snapshot_hash, metric reference/bounds, exact authoritative primitive geometry and source IDs, source manifest, camera, dimensions, actual GL_VENDOR/GL_RENDERER/GL_VERSION, and success/failure state. No hash is substituted for the authoritative snapshot hash or asserted to validate it. Software provider names (including llvmpipe, softpipe and SwiftShader) are rejected by default; provider strings do not certify physical GPU allocation. FSR is explicitly marked not implemented. PNG publication occurs only after all native resources are released; failure sidecars do not claim rendering success. A preexisting PNG is not replaced on a failed call.

All tests and source authoring for this renderer ran on the cloud worktree using /opt/venv/bin/python, detached tmux, taskset CPU0/1 and thread limits of two. Native-preparation tests use a fake ModernGL context and Pillow for synthetic 2x2 row-flip verification. They do not create EGL/OpenGL/Vulkan contexts, enumerate GPUs, import Torch or exercise native graphics drivers. Real native rendering remains unexecuted because graphics runtime prerequisites are unavailable; no allocated-GPU image or FSR proof exists.

Evidence files are native-prep-red.log (missing module), native-prep-initial-green.log (serialization regression), native-prep-line-red.log (line distance upload), native-prep-review-red.log (camera overflow/source association), native-prep-authority-red.log (authority geometry), and native-prep-final-green.log (final CPU suite). Reproduce with bash viewer3d/evidence/native-prep-final-green.sh.

Native API references: [ModernGL context creation](https://moderngl.readthedocs.io/en/latest/topics/context.html), [glcontext EGL backend and library hints](https://github.com/moderngl/glcontext), [ModernGL framebuffer readback](https://moderngl.readthedocs.io/en/latest/reference/framebuffer.html).
