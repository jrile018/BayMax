# Web dashboard checkpoint

The browser client is served from `web/index.html`, `web/style.css`, and `web/app.js`. It has no package manager, CDN, tile, font, or JavaScript framework dependency. It uses the same-origin read-only endpoints `/api/bootstrap`, `/api/frame?index=N`, and `/api/coverage?lat=X&lon=Y`.

## Source and replay behavior

- The current source manifest reports OSM acquisition failure. With zero roads, the client displays “NO ROAD DATA LOADED · OVERLAYS ARE CONSTRUCTED ILLUSTRATIONS”, a map notice, and an unavailable road chip. It draws no substitute roads or buildings.
- Routes, old routes, completed trails, vehicle positions, fire overlays, closures, events, metrics, needs, stocks, and the snapshot hash come only from API frames. The old route uses `old_route_geometry_lonlat` when supplied; the client does not infer a route from previous frames.
- Playback and the slider request exact saved frame indices. The browser does not interpolate coordinates or advance vehicle physics. Coordinate lookup calls the coverage API and displays its returned unavailable message.
- Null remaining distance and ETA render as “Unknown”.

## Validation on the supplied server

- Static validation: 67 unique HTML IDs; all JavaScript-referenced IDs exist; balanced CSS/JS delimiters; no external asset links.
- Live HTTP: `/`, `/style.css`, and `/app.js` returned 200 from loopback port 8765.
- API contract: bootstrap and all six frame indices returned 200, with matching run/index, 64-character snapshot hashes, and vehicle position/route fields. Route versions were 1,1,1,2,2,2; event types included dispatch, closure, reroute, and arrival.
- Coverage: both a coordinate inside the loaded bbox with failed source acquisition and a coordinate outside the bbox returned `available: false`; an invalid frame returned a client error.
- Browser rendering remains unverified. The server has no installed browser or JavaScript runtime, and the SSH server blocks TCP forwarding.

Review follow-up: the initial footer says “CONSTRUCTED TRAINING REPLAY”; runtime mode also updates it. Mock route audit explicitly says “Constructed training path · route calculation unavailable,” even if map source data later becomes available. Static check passed again on 67 IDs / 20 JavaScript references. The live bootstrap still reported six frames at this check; fixture update is owned by another worker.

No code was committed.
