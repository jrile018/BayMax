# Wildfire C1: explicit training adapter and blocked physical reference

This checkpoint produces deterministic synthetic hazard fields for routing integration. **Physical wildfire simulation is unimplemented.** Default Pyretechnics requests return unavailable. The explicit `engine="training-grid"` path is an uncalibrated hypothetical exercise. No current incident, real fuel raster, measured weather or mapped terrain is ingested. See `REFERENCE_GATE.json` for the failed cloud dependency gate and researched pin. The pinned source archive and EPL notice were researched previously, but not downloaded/verified on this server; no Pyretechnics code is copied or distributed here.

## Run on the authorized Radeon Cloud

From `/workspace/knight26/worktrees/wildfire`, with two-thread environment caps:

```sh
/opt/venv/bin/python -m unittest discover -s services/hazards/wildfire/tests -v
/opt/venv/bin/python -m services.hazards.wildfire --fixture fixtures/fire/synthetic_fuel_gap_v1.json --output-dir /workspace/knight26/artifacts/wildfire/checkpoint-c1/run-a
```

Long jobs run in detached tmux; the coordinator owns shared contracts/integration. Pure standard-library implementation, no image/Torch edits or GPU allocation. Keep all product runs on cloud. Output JSON includes `hazard.json`, `edge-access.json`, and SHA256 `manifest.json`; identical fixture bytes produce identical output bytes.

## API proposal for coordinator review

`simulate(config: dict) -> dict`: hypothetical-only configuration with explicit metric grid/CRS, fuel codes, slope/aspect, fixed wind/moisture, ignition cells/times, horizon, output spacing, seed and dated source ledger. Output `status`, `scenario_id`, `epoch_utc`, `grid`, `arrivals_s`, `frames`, `burn_intervals`, `active_flame_intervals`, `horizon_s`, `units`, `provenance`. This is an owned module payload; root must wrap it in the shared snapshot with run/version/forecast issue time. Hidden sampled future truth must never be published to controllers as an observation.

`edge_access(hazard, edges, issued_time_s, safety_buffer_s=0) -> list`: edges use stable `edge_id` and `geometry_m` east/north polylines in the same CRS. Any segment touching a closed grid-cell rectangle uses the earliest arrival minus buffer. Intervals are `[start_s,end_s)`, capped to the model horizon; closures persist conservatively. Partial/outside grid coverage returns `status="unknown"` while preserving any computed inside closure. Null cell arrivals mean not reached within this modeled horizon, not safe beyond it. Empty closures are a model forecast, never an observed road-safety certification. Every row carries source IDs, issue time, coverage horizon and spatial rule. The routing owner must test full-edge traversal against these intervals and reject/handle unknown coverage.

`current_incident_eligibility(evidence, as_of_utc, location_lonlat, max_age_hours=24)` checks metadata on separately human-accepted incident records (ID, active wildfire status, HTTPS source, timestamp and matching bbox). The 24-hour freshness window is an explicit training gate assumption. Empty, stale, future, unreviewed or mismatched records abstain. Passing metadata is not independent verification and never relabels hypothetical fields as a current fire. No live feed is implemented.

## Training equation and fidelity

Let `d` be unit neighbour direction, `u` wind toward east/north in m/s, and `g=-slope*(sin(aspect)*d_x+cos(aspect)*d_y)` positive uphill. The assumed local rate is:

```
R = R0 * f_fuel * max(0,1-M1/Mext)
    * exp(-0.5*(M10+M100)-0.1*(Mlive_h+Mlive_w))
    * exp(clamp(kw*(u dot d)+ks*g,-ln(10),ln(10)))
travel_time = neighbour_distance/2 * (1/Rsource + 1/Rdestination)
```

An eight-neighbour first-arrival graph computes arrivals. Every coefficient is disclosed in the fixture/output. Fuel factors101=1 and102=1.15 are assumed; codes91/92/93/98/99 are categorical nonburnable masks. Unknown codes and NoData are rejected, never inferred. Diagonal corner jumps past barriers are blocked. Moisture at extinction stops propagation while retaining explicit ignition. There is no regeneration. `burn_intervals` describe cumulative burned/hazard state to horizon; separate assumed active-flame residence is120s. `seed` is a provenance identifier; this deterministic backend has no RNG. Output sampling changes frames but not arrivals. There is grid-direction/resolution bias, no spotting/crown/building fire, suppression, atmosphere feedback or validated rates. Rothermel's published physical equations are a foundation for a future engine, not the equations implemented here.

Coordinates: metres in caller-declared projected CRS or local metric system, origin lower-left, x/east and y/north, array row increases north. Times seconds from the declared epoch. Slope rise/run; aspect downslope clockwise north; fuel moisture kg water/kg dry fuel. `wind_to_pyre` converts east/north m/s toward vectors into10m wind km/h and meteorological FROM clockwise north, tested for all four cardinal directions. No geographic resampling/fuel calibration is implemented.

References reviewed2026-10-10: [Rothermel1972](https://research.fs.usda.gov/treesearch/32533), [LANDFIRE fuel products](https://landfire.gov/fuel), [published Pyretechnics2026.8.10](https://pypi.org/project/pyretechnics/2026.8.10/). Fixtures are authored synthetic data (CC0-1.0); dependency/source and real-data rights remain separate.
