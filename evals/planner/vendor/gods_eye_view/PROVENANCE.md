# Vendored God's Eye View UI modules

Source: [bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view), pinned commit `591f299d11f38a612629a274463196d57ae3862e`, MIT source-code license. The adjacent LICENSE is copied from that commit. The filtered source export provenance is in `UPSTREAM_SOURCE.json`. No bundled datasets, assets, provider keys, Cesium runtime, or upstream build scripts are included.

| Local file | Upstream file | Changes |
|---|---|---|
| `panelRailGeometry.js` | `src/ui/panelRailGeometry.js` | Exact source copy |
| `panelStackLayout.js` | `src/panelStackLayout.js` | Exact source copy |
| `railTimeline.js` | `src/ui/railTimeline.js` | Adapted UTC tick formatting and labels to simulated elapsed seconds and recorded decisions; accepts tick zero during drag |
| `practiceShell.js` | New adapter using the three modules above and the structural rail/center/dock pattern from `src/ui/applicationShell.js` and `src/ui/panelLayoutController.js` | Training-specific browser client; all mission data comes from current-node server responses |

The adapted timeline navigates only client-side snapshots already received in the current session. It cannot request or display future nodes. The central SVG depicts only initially published synthetic road geometry plus received closure facts. It is not a geographic base map or live hazard feed.
