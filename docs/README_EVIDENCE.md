# README evidence notes

The README summarizes project evidence reviewed on October 10, 2026, including saved map/browser artifacts and workstream checkpoints. It does not establish current deployment availability or rerun the product. BayMax was previously labeled Knight26 in the interface and source.

## Situation and geography

- Reviewed NWS weather alerts and USGS earthquake records were accepted into immutable publications with source IDs, hashes, times, unknowns, and snapshot identities.
- A signed-in JupyterLab Situation panel followed accepted publication-pointer changes. Polling a stored publication does not refresh its original source observations.
- A separately browser-checked Earth export embedded a fixed snapshot with cutoff `2026-10-10T20:53:39.996667Z`. It included three curated context places and two accepted USGS points. Regional NWS alerts were not converted to city pins.
- The Paradise road/building geometry comes from a bounded OSM acquisition. Geographic context is not proof of current road safety or historical disaster damage.
- The two README screenshots are earlier development previews with authored replay routes, vehicle positions, and fire overlays. NASA Blue Marble is historical imagery; Esri imagery acquisition dates are not established by these previews.

The published [Situation contract](../services/dashboard_api/SITUATION.md), [incident-artifact documentation](../integration/INCIDENT_ARTIFACTS.md), [map checkpoint](../web/CHECKPOINT.md), and [map references](../web/REFERENCES.md) describe the relevant source interfaces and provenance.

## Response planning

Tested routing components cover directed-road access, simulated trip progress, underway commitments, changed access, and rerouting. Authored training cases exercise requests, stocks, capacities, closures, alternative policies, and debrief metrics. Their separate evidence does not establish a complete accepted-incident-to-executor-to-map connection.

Operational needs, road closures, fleet positions, stocks, and destination capacities remain Unknown in the accepted situation described by the review. Exercises supply declared fictional values. Simulated requests served and resource use are not measured lives saved or demonstrated community benefit.

Authored stress cases have no probability weights. Sampled training futures describe a declared model and do not establish calibrated real-world probabilities.

See [routing artifacts](../services/routing/ARTIFACTS.md), [training documentation](../evals/planner/TRAINING.md), and the [routing/planner review](reviews/routing_mc.md).

## Models and graphics

The reviewed intake work included a reported layer and a pinned Qwen3-4B runner. Verified GPU inference, evaluated OCR, and a complete document-to-map workflow remained separate gates in that evidence. Wildfire dependency work did not establish a validated physical forecast connected to the mission.

ROCm tensor smoke evidence and native W7900 mock-scene renders were recorded. They do not establish genuine FSR4 dispatch or product performance. See the [intake/wildfire review](reviews/hf_fire.md) and [Maps/AMD review](reviews/maps_amd.md) for their recorded scopes.

## Origins and source boundaries

God's Eye View inspired the map-first interaction and this README's presentation. Documented code reuse concerns MIT panel-layout helpers pinned at `591f299d11f38a612629a274463196d57ae3862e`; the Earth view uses a project-authored Three.js integration. Upstream provider catalogs do not establish connected BayMax feeds.

OSM supplies geographic geometry; NASA/Esri supply visual context; NWS/USGS supply accepted hazard observations. Exercise authors supply fictional operational conditions where verified inputs are absent. Additional providers and models retain their own adoption, access, and licensing requirements.

See the [map references](../web/REFERENCES.md), [upstream notice](../web/UPSTREAM_LICENSE.txt), and [training-helper provenance](../evals/planner/vendor/gods_eye_view/PROVENANCE.md). The [review index](reviews/README.md) provides the repository's independent review records.
