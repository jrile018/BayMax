# Wildfire: pinned surface reference and explicit training fields

The module implements an optional Pyretechnics 2026.8.10 surface-fire backend and a separately selected deterministic training graph. All scenarios are hypothetical. No current incident, measured weather, mapped terrain or real fuel raster is ingested. The pinned compiled extension has imported on the supplied cloud; actual solver verification is still pending the detached test-runner approval. `REFERENCE_GATE.json` records exact evidence. Missing or wrong physical runtimes return unavailable and never silently choose training.

## Cloud execution and runtime boundary

Keep product authoring, install, build, tests, simulation and rendering on the supplied Radeon Cloud. Ordinary CPU jobs cap OMP/OPENBLAS/MKL/NUMEXPR threads at two and run detached when nontrivial. The isolated reference interpreter is `/workspace/knight26/artifacts/wildfire/runtime/venv/bin/python` (CPython 3.11.13), with NumPy 1.26.4, SciPy 1.12.0, rasterio 1.4.3, sortedcontainers 2.4.0 and Cython 3.0.11. The image Python 3.14/Torch/ROCm environment stays separate; API integration should invoke the isolated CLI or worker rather than switching the whole API interpreter. No GPU is needed by this module.

From `/workspace/knight26/worktrees/wildfire`:

```sh
/workspace/knight26/artifacts/wildfire/runtime/venv/bin/python -m unittest discover -s services/hazards/wildfire/tests -v
/workspace/knight26/artifacts/wildfire/runtime/venv/bin/python -m services.hazards.wildfire --fixture fixtures/fire/synthetic_surface_reference_v1.json --output-dir /workspace/knight26/artifacts/wildfire/checkpoint-c2/reference-a
/opt/venv/bin/python -m services.hazards.wildfire --fixture fixtures/fire/synthetic_fuel_gap_v1.json --output-dir /workspace/knight26/artifacts/wildfire/checkpoint-c2/training-a
```

The CLI exports `hazard.json`, `edge-access.json` and a SHA256 `manifest.json`. Determinism must be checked in a fixed pinned runtime; manifests bind fixture/output bytes. Do not claim physical results from skipped optional-runtime tests. The training path uses only the standard library.

## API and source availability

`simulate(config)` requires a hypothetical metric grid/CRS, supported fuel codes, slope/aspect, fixed wind/moisture, explicit ignitions, horizon/output spacing, seed and a dated source ledger. It produces arrivals, frames, cumulative burn intervals, separate assumed active-flame intervals and provenance. Public times are seconds from `epoch_utc`; x/east and y/north are metres, origin is lower-left and rows increase north. Slope is rise/run, aspect is downslope clockwise from north, moisture is kg water/kg dry fuel, and public wind is toward east/north in m/s. Physical conversion supplies 10 m wind km/h and meteorological FROM degrees.

`edge_access(hazard, edges, issued_time_s, safety_buffer_s=0)` consumes stable edge IDs and same-CRS metric polylines. Any segment touching a closed cell rectangle closes the whole edge at the earliest arrival minus buffer, clamped to issue, through the model horizon. Intervals are half-open `[start,end)`. Partial/outside coverage remains unknown while retaining any inside closure. Empty closures/null arrivals do not certify observed road safety or safety outside the horizon.

Every row carries issue/coverage times, source IDs, spatial rule/reason and `source_availability`: scenario epoch, full dated ledger, checked issue seconds and latest available seconds. Retrieval and any observation must precede issuance; an observed source requires an observation date. Missing/future dates, invalid rights labels or required source URI, duplicated IDs and unsupported kinds fail closed. This is metadata validation, not authentication or independent source fact checking. Synthetic fixture epochs follow their source retrieval dates.

`safety_snapshot_from_access(rows, known_at_s, version, safe_nodes=(), expected_edge_ids=None)` in `routing_bridge.py` imports the routing package lazily. It rederives availability from each full ledger, rejects missing/forged fields, future issue/coverage, source-ID mismatch and mixed epochs, and takes the shortest coverage end. Only explicit forecast rows cover edges; unknown/missing edges abstain. Use `expected_edge_ids=graph.edges.keys()` or `tuple(graph.edges)`. Wildfire closures are already buffered, so no additional routing buffer is added. Full traversal/horizon checks remain routing responsibilities. Root wraps this owned payload in the shared run/version/mission contract and keeps sampled hidden future truth separate.

`current_incident_eligibility` checks separately human-reviewed active-wildfire metadata, HTTPS URI, place/date and explicit 24-hour freshness. Passing metadata never relabels a hypothetical field as a current fire. No live feed is implemented.

## Physical reference limits

`engine="pyretechnics"` is the default physical request. The exact compiled pinned extension is required. `physical_assumptions` must contain exactly `surface_only=True`, `wind_height_m=10`, nonnegative `foliar_moisture` and positive assumed `residence_time_s`. Supported surface fuels are 101/102 and categorical nonburnable 91/92/93/98/99. Ignitions must be explicit cells at time zero. Unknown fuels and NoData are rejected.

Static cubes feed the surface Rothermel level-set solver; canopy values are zero, spotting is disabled, wind limit is enabled, maximum cells per step is 0.4 and buffer width is 3. Solver minutes are converted to seconds; float32 inputs are range checked and arrival times lowered by one ULP conservatively. Provenance distinguishes the expected source-archive SHA from the actual loaded extension SHA and records version/settings/stop condition/boundary contact. Seed is recorded only; this path has no stochastic spotting process.

This is an uncalibrated surface-only reference with assumed fuels/weather/terrain and residence time. It excludes crown/structure fire, suppression and atmosphere feedback. Domain boundaries clip the field; spatial resolution, numerical errors and incomplete inputs limit road forecasts. No physical accuracy or real-incident fitness is established by compilation or synthetic behaviour tests. See [Pyretechnics 2026.8.10](https://pypi.org/project/pyretechnics/2026.8.10/), [Rothermel 1972](https://research.fs.usda.gov/treesearch/32533) and [LANDFIRE](https://landfire.gov/fuel).

## Explicit training graph

`engine="training-grid"` requires disclosed `training_assumptions`. An eight-neighbour first-arrival graph uses:

```
R = R0 * f_fuel * max(0,1-M1/Mext)
    * exp(-0.5*(M10+M100)-0.1*(Mlive_h+Mlive_w))
    * exp(clamp(kw*(u dot d)+ks*g,-ln(10),ln(10)))
travel_time = neighbour_distance/2 * (1/Rsource + 1/Rdestination)
g = -slope*(sin(aspect)*d_x + cos(aspect)*d_y)
```

Fuel factors 101=1 and 102=1.15 are assumptions. Diagonal barrier corner jumps are blocked, moisture extinction stops propagation while retaining ignition, burned state is monotonic, and output spacing changes sampling rather than arrivals. The assumed active-flame residence is separate from cumulative hazard. Grid direction/resolution bias and empirical rates preclude physical accuracy claims. This graph does not implement Rothermel.

Both paths bound 65,536 cells, 1,001 frames, 1,000,000 cell-frame samples and a seven-day horizon before allocation. These are compute/representation limits. Fixtures are authored CC0 synthetic data; dependencies and original data rights are separate. Official runtime/package bytes were registry-hash verified on cloud, exact source LICENSE confirmed EPL-2.0 and retained in the isolated runtime. No Pyretechnics source is vendored in this repository. [DATA_FIT.md](DATA_FIT.md) records the bounded Hugging Face card audit; no candidate was adopted because required fit gates were missing.
