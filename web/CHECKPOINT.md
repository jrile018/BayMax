# Map dashboard checkpoint

Dependency-free `web/index.html`, `style.css`, `app.js`; no CDN/tile/font/runtime install. Read-only same-origin bootstrap/frame/coverage API. Client draws exact recorded positions, trails, remaining paths/ETA, closures/fire, metrics and events without independent movement or physics.

Real Paradise OSM map: 444 roads, 199 buildings, 40 landuse/water features. Attribution is visible. Acquisition bounds are a distinct dashed boundary; full way context extends beyond it. Viewport fits loaded geometry. The source panel distinguishes the two extents and marks terrain/fuels/current fire unavailable.

Seven-frame mock route/fire replay remains labeled constructed even with real map geometry. Route audit states calculated routing is unavailable; mock metrics are labeled. Null ETA/distance remains unknown. Pan/zoom, play/step/scrub and fleet selection are supported.

Server static validation passed: 70 unique IDs, all22JSreferencespresent; no external assets. Actual service refresh serves the real geometry and seven exact snapshots. Current real-map preview browser inspection is pending authenticated notebook access. Earlier saved mock preview first/closure/final frames were verified in Chrome with matching hashes; latest reload returned nginx403. This does not prove live API browser access. No network/security changes or public exposure.

Server saved artifact `/workspace/knight26/artifacts/maps/c1/preview.html`, API trace and publication manifest in same directory. Detailed test/commit record in services/dashboard_api/CHECKPOINT.md and publication manifest. Own draft PR10 and Discussion1 remain the review destination.
