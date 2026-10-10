"use strict";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const state = {
  bootstrap: null, frame: null, selectedId: null, index: 0, playing: false,
  timer: null, requestSerial: 0, projection: null, view: {x:0,y:0,w:1000,h:700},
  pointer: null
};

function setText(id, value) { $(id).textContent = value == null ? "--" : String(value); }
function el(tag, className, textValue) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (textValue !== undefined) node.textContent = textValue;
  return node;
}
function svg(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}
function clear(id) { $(id).replaceChildren(); }
function error(message) { const box = $("global-error"); box.textContent = message; box.hidden = !message; }
function fmtTime(seconds) {
  if (seconds === null || seconds === undefined || seconds === "" || !Number.isFinite(Number(seconds))) return "--:--";
  const s = Math.max(0, Math.round(Number(seconds)));
  return String(Math.floor(s / 3600)).padStart(2,"0") + ":" +
    String(Math.floor((s % 3600) / 60)).padStart(2,"0") + ":" +
    String(s % 60).padStart(2,"0");
}
function fmtDistance(metres) {
  if (metres === null || metres === undefined || metres === "" || !Number.isFinite(Number(metres))) return "Unknown";
  return Number(metres) >= 1000 ? (Number(metres)/1000).toFixed(1) + " km" : Math.round(Number(metres)) + " m";
}
function fmtEta(seconds) {
  if (seconds === null || seconds === undefined || seconds === "" || !Number.isFinite(Number(seconds))) return "Unknown";
  const minutes = Math.ceil(Number(seconds) / 60);
  return minutes < 60 ? minutes + " min" : Math.floor(minutes / 60) + " h " + String(minutes % 60).padStart(2,"0") + " m";
}
function asPair(point) {
  return Array.isArray(point) && point.length >= 2 && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])) &&
    !Array.isArray(point[0]) ? [Number(point[0]),Number(point[1])] : null;
}
function lineGroups(geometry) {
  if (!Array.isArray(geometry)) return [];
  if (geometry.length && asPair(geometry[0])) return [geometry.map(asPair).filter(Boolean)];
  return geometry.flatMap(lineGroups);
}
function project(pair) {
  if (!state.projection) return [0,0];
  const p = state.projection;
  return [(pair[0] - p.lon0) * p.cos * p.scale + p.offsetX, (p.lat1 - pair[1]) * p.scale + p.offsetY];
}
function pathData(geometry, close = false) {
  return lineGroups(geometry).filter(g => g.length > (close ? 2 : 1)).map(group =>
    group.map((point,i) => { const [x,y] = project(point); return (i ? "L" : "M") + x.toFixed(2) + " " + y.toFixed(2); }).join(" ") + (close ? " Z" : "")
  ).join(" ");
}
function addPath(layer, geometry, className, close = false, extra = {}) {
  const d = pathData(geometry, close);
  if (!d) return null;
  const node = svg("path", {d, class:className, ...extra});
  $(layer).append(node);
  return node;
}
function projectionFromBbox(bbox) {
  if (!Array.isArray(bbox) || bbox.length < 4) throw new Error("Area bounds are missing.");
  const [lon0,lat0,lon1,lat1] = bbox.map(Number);
  if (![lon0,lat0,lon1,lat1].every(Number.isFinite) || lon1 <= lon0 || lat1 <= lat0) throw new Error("Area bounds are invalid.");
  const cos = Math.cos((lat0 + lat1) * Math.PI / 360);
  const width = (lon1 - lon0) * cos, height = lat1 - lat0;
  const scale = Math.min(920 / width, 620 / height);
  return {lon0,lat1,cos,scale,offsetX:(1000-width*scale)/2,offsetY:(700-height*scale)/2};
}
function drawBase(area) {
  state.projection = projectionFromBbox(area.bbox_lonlat);
  clear("layer-land"); clear("layer-buildings"); clear("layer-roads"); clear("layer-boundary");
  const colors = {forest:"#b7c8ad",wood:"#b7c8ad",grass:"#cbd7b7",meadow:"#d3dec1",residential:"#e4e9dc",industrial:"#d7dcca",park:"#c6d3b6"};
  for (const land of area.landuse || []) {
    const kind = String(land.kind || "").toLowerCase();
    addPath("layer-land",land.geometry_lonlat,"landuse",true,{fill:colors[kind] || (kind.includes("forest") ? colors.forest : "#d2ddc5")});
  }
  for (const building of area.buildings || []) addPath("layer-buildings",building.geometry_lonlat,"building",true);
  const roads = (area.roads || []).slice().sort((a,b) => roadWidth(a.highway)-roadWidth(b.highway));
  for (const road of roads) {
    const width = roadWidth(road.highway);
    addPath("layer-roads",road.geometry_lonlat,"road-casing",false,{"stroke-width":width+1.8});
    const item = addPath("layer-roads",road.geometry_lonlat,"road",false,{"stroke-width":width});
    if (item) item.appendChild(svg("title")).textContent = road.name || road.highway || "Road";
  }
  const [lon0,lat0,lon1,lat1] = area.bbox_lonlat.map(Number);
  addPath("layer-boundary",[[lon0,lat0],[lon1,lat0],[lon1,lat1],[lon0,lat1],[lon0,lat0]],"area-boundary");
  const hasRoads = (area.roads || []).length > 0;
  setText("source-chip",hasRoads ? "OSM road geometry" : "Road data unavailable");
  $("map-notice").hidden = hasRoads;
  setText("map-area-label",area.label || "Loaded area");
  setText("map-title",area.label || "Area map");
  setText("map-subtitle",(area.roads || []).length.toLocaleString() + " road geometries · " + (area.buildings || []).length.toLocaleString() + " buildings");
  resetMap();
}
function roadWidth(highway) {
  const h = String(highway || "").toLowerCase();
  if (["motorway","trunk","primary"].some(x => h.includes(x))) return 7;
  if (["secondary","tertiary"].some(x => h.includes(x))) return 5;
  return 2.7;
}
function setView(view) {
  const w = Math.max(120,Math.min(1500,view.w)), h = w*.7;
  const x = Math.max(-250,Math.min(1250-w,view.x));
  const y = Math.max(-175,Math.min(875-h,view.y));
  state.view = {x,y,w,h};
  $("map").setAttribute("viewBox",[x,y,w,h].map(n => n.toFixed(2)).join(" "));
}
function resetMap() { setView({x:0,y:0,w:1000,h:700}); }
function zoom(factor) {
  const v = state.view, w = v.w * factor, h = w * .7;
  setView({x:v.x + (v.w-w)/2,y:v.y + (v.h-h)/2,w,h});
}
function wireMap() {
  $("reset-map").addEventListener("click",resetMap);
  $("zoom-in").addEventListener("click",() => zoom(.78));
  $("zoom-out").addEventListener("click",() => zoom(1/.78));
  const map = $("map");
  map.addEventListener("wheel",event => { event.preventDefault(); zoom(event.deltaY < 0 ? .9 : 1/.9); },{passive:false});
  map.addEventListener("pointerdown",event => {
    if (event.button !== 0) return;
    state.pointer = {id:event.pointerId,x:event.clientX,y:event.clientY,view:{...state.view}};
    map.setPointerCapture(event.pointerId); map.classList.add("dragging");
  });
  map.addEventListener("pointermove",event => {
    const drag = state.pointer;
    if (!drag || drag.id !== event.pointerId) return;
    const bounds = map.getBoundingClientRect();
    setView({x:drag.view.x-(event.clientX-drag.x)*drag.view.w/bounds.width,
      y:drag.view.y-(event.clientY-drag.y)*drag.view.h/bounds.height,w:drag.view.w});
  });
  const end = () => { state.pointer = null; map.classList.remove("dragging"); };
  map.addEventListener("pointerup",end); map.addEventListener("pointercancel",end);
}
async function getJSON(path) {
  const response = await fetch(path,{headers:{"Accept":"application/json"}});
  if (!response.ok) {
    let detail = "";
    try { const body = await response.json(); detail = body.message || body.error || ""; } catch (_) {}
    throw new Error("API " + response.status + " " + response.statusText + (detail ? ": " + detail : ""));
  }
  return response.json();
}
function markMode(mode) {
  const mock = String(mode || "").startsWith("mock");
  setText("mode-label",mock ? "Open map · training replay" : "Open map · recorded replay");
  setText("footer-mode",mock ? "CONSTRUCTED TRAINING REPLAY" : "RECORDED SIMULATION");
  const roadsLoaded = !!(state.bootstrap && state.bootstrap.area && (state.bootstrap.area.roads || []).length);
  setText("source-banner",roadsLoaded ? (mock ? "MOCK SCENARIO · OSM MAP GEOMETRY" : "RECORDED SIMULATION · CHECK SOURCE STATUS") : "NO ROAD DATA LOADED · OVERLAYS ARE CONSTRUCTED ILLUSTRATIONS");
  document.querySelectorAll(".metric-foot").forEach(node => {
    if (!node.dataset.original) node.dataset.original = node.textContent;
    node.textContent = mock ? node.dataset.original + " · mock scenario" : node.dataset.original;
  });
}
function renderCoverage(entries) {
  clear("coverage-list");
  if (!entries || !entries.length) {
    $("coverage-list").append(el("p","empty-state","No coverage manifest returned."));
    return;
  }
  for (const entry of entries) {
    const row = el("div","coverage-row");
    const label = el("div"); label.append(el("strong","",entry.layer || "Layer"));
    if (entry.detail) label.append(el("small","coverage-detail",entry.detail));
    row.append(label,el("span",String(entry.status || "unknown").toLowerCase(),entry.status || "unknown"));
    $("coverage-list").append(row);
  }
}
function vehicleIcon(kind) {
  const wrapper = el("span","fleet-icon " + String(kind || "").toLowerCase());
  const symbol = svg("svg",{viewBox:"0 0 24 24","aria-hidden":"true"});
  const paths = {
    ambulance:"M3 6h12v10H3z M15 9h3l3 3v4h-6z M7 11h5 M9.5 8.5v5 M6 18a1.5 1.5 0 1 0 0-3 M18 18a1.5 1.5 0 1 0 0-3",
    bus:"M4 5h16v11H4z M7 8h3 M13 8h4 M7 11h3 M13 11h4 M7 18v-2 M17 18v-2",
    truck:"M3 6h11v10H3z M14 9h4l3 3v4h-7z M6 18a1.5 1.5 0 1 0 0-3 M18 18a1.5 1.5 0 1 0 0-3"
  };
  symbol.append(svg("path",{d:paths[String(kind || "").toLowerCase()] || paths.truck,fill:"none",stroke:"currentColor","stroke-width":"1.5","stroke-linejoin":"round","stroke-linecap":"round"}));
  wrapper.append(symbol); return wrapper;
}
function renderFleet(frame) {
  clear("fleet-list");
  const vehicles = frame.vehicles || [];
  setText("fleet-count",vehicles.length);
  if (!vehicles.length) { $("fleet-list").append(el("p","empty-state","No vehicles in this snapshot.")); return; }
  if (!vehicles.some(v => v.vehicle_id === state.selectedId)) state.selectedId = vehicles[0].vehicle_id;
  for (const v of vehicles) {
    const selected = v.vehicle_id === state.selectedId;
    const button = el("button","fleet-item" + (selected ? " selected" : ""));
    button.type = "button"; button.setAttribute("aria-pressed",String(selected));
    button.setAttribute("aria-label","Inspect " + (v.label || v.vehicle_id));
    const main = el("span","fleet-main");
    main.append(el("strong","",v.label || v.vehicle_id),el("small","",String(v.kind || "unit") + " · " + String(v.phase || "unknown")));
    button.append(vehicleIcon(v.kind),main,el("span","fleet-chevron","›"));
    button.addEventListener("click",() => { state.selectedId = v.vehicle_id; renderFleet(frame); renderRouteAudit(frame); drawFrameMap(frame); });
    $("fleet-list").append(button);
  }
}
function auditStat(label,value) {
  const node = el("div","route-stat");
  node.append(el("small","",label),el("strong","",value));
  return node;
}
function renderLedger(frame) {
  clear("needs-list"); clear("stock-list");
  const needs = frame.needs || [];
  if (!needs.length) $("needs-list").append(el("p","empty-state","No need records in this frame."));
  for (const need of needs) {
    const row = el("div","ledger-row");
    const name = el("div"); name.append(el("strong","",need.label || need.request_id || "Request"));
    name.append(el("small","",String(need.kind || "need").replaceAll("_"," ") + " · " + String(need.status || "unknown")));
    row.append(name,el("span","",String(need.remaining ?? "—") + " / " + String(need.quantity ?? "—") + " " + String(need.unit || "")));
    $("needs-list").append(row);
  }
  const stocks = frame.stocks || [];
  if (stocks.length) $("stock-list").append(el("div","ledger-caption","DEPOT STOCK"));
  for (const stock of stocks) {
    const row = el("div","ledger-row"); row.append(el("strong","",stock.label || stock.depot_id || "Depot"),el("span","",String(stock.supply_units ?? "—") + " units"));
    $("stock-list").append(row);
  }
}
function renderRouteAudit(frame) {
  clear("route-audit");
  const v = (frame.vehicles || []).find(item => item.vehicle_id === state.selectedId);
  if (!v) { $("route-audit").append(el("p","empty-state","No vehicle selected.")); return; }
  const heading = el("div","route-name");
  heading.append(el("strong","",v.label || v.vehicle_id),el("span","route-tag",v.phase || "unknown"));
  $("route-audit").append(heading);
  if (String(state.bootstrap.mode || "").startsWith("mock")) $("route-audit").append(el("p","route-caveat","Constructed training path · route calculation unavailable."));
  else if (!(state.bootstrap.area.roads || []).length) $("route-audit").append(el("p","route-caveat","Road graph unavailable · route calculation status unknown."));
  $("route-audit").append(el("p","route-reason",v.reason || "No route change reason recorded for this frame."));
  const grid = el("div","route-grid");
  grid.append(
    auditStat("Remaining",fmtDistance(v.remaining_distance_m)),
    auditStat("Arrival ETA",fmtEta(v.eta_s)),
    auditStat("People aboard",Number(v.load && v.load.people || 0).toLocaleString()),
    auditStat("Supply units",Number(v.load && v.load.supply_units || 0).toLocaleString())
  );
  $("route-audit").append(grid,el("p","route-version","Route " + (v.route_id || "unassigned") + " · version " + (v.route_version ?? "--")));
}
function drawFrameMap(frame) {
  ["layer-hazards","layer-old-route","layer-route","layer-closures","layer-vehicles"].forEach(clear);
  for (const hazard of frame.hazards || []) {
    const path = addPath("layer-hazards",hazard.geometry_lonlat,"hazard",true);
    if (path) path.appendChild(svg("title")).textContent = (hazard.label || "Fire perimeter") + " · " + (hazard.source_status || "source unknown");
  }
  const selected = (frame.vehicles || []).find(v => v.vehicle_id === state.selectedId);
  if (selected) {
    addPath("layer-old-route",selected.old_route_geometry_lonlat,"old-route");
    addPath("layer-route",selected.route_geometry_lonlat,"remaining-route");
    addPath("layer-route",selected.remaining_path_lonlat,"remaining-route");
    addPath("layer-route",selected.completed_trail_lonlat,"completed-trail");
  }
  for (const closure of frame.closures || []) {
    const line = addPath("layer-closures",closure.geometry_lonlat,"closure");
    if (line) line.appendChild(svg("title")).textContent = (closure.reason || "Closed road") + " · observed at " + fmtTime(closure.observed_at_s);
  }
  for (const v of frame.vehicles || []) {
    const point = asPair(v.position_lonlat);
    if (!point) continue;
    const [x,y] = project(point), selectedMarker = v.vehicle_id === state.selectedId;
    const group = svg("g",{tabindex:"0",role:"button","aria-label":"Select " + (v.label || v.vehicle_id)});
    group.append(svg("circle",{cx:x,cy:y,r:selectedMarker ? 11 : 9,class:"vehicle-marker" + (selectedMarker ? " selected" : "")}));
    group.append(svg("circle",{cx:x,cy:y,r:3,class:"vehicle-center" + (selectedMarker ? " selected" : "")}));
    const label = svg("text",{x:x+15,y:y+4,class:"marker-label" + (selectedMarker ? " selected" : "")}); label.textContent = v.label || v.vehicle_id; group.append(label);
    const select = () => { state.selectedId = v.vehicle_id; renderFleet(frame); renderRouteAudit(frame); drawFrameMap(frame); };
    group.addEventListener("click",select);
    group.addEventListener("keydown",event => { if (event.key === "Enter" || event.key === " ") {event.preventDefault();select();} });
    $("layer-vehicles").append(group);
  }
}
function renderEvents(frame) {
  clear("event-list");
  const events = (frame.events || []).filter(e => Number(e.time_s) <= Number(frame.time_s)).slice().sort((a,b) => Number(b.time_s)-Number(a.time_s));
  setText("event-count",events.length + (events.length === 1 ? " EVENT" : " EVENTS"));
  if (!events.length) { $("event-list").append(el("li","empty-state","No recorded events at this frame.")); return; }
  for (const event of events) {
    const kind = String(event.type || "").toLowerCase();
    const item = el("li",kind.includes("clos") || kind.includes("rerout") ? "event-closure" : "");
    item.append(el("span","event-time",fmtTime(event.time_s) + " · " + String(event.type || "event").replaceAll("_"," ").toUpperCase()));
    item.append(el("span","",event.message || "Recorded event"));
    $("event-list").append(item);
  }
}
function renderFrame(frame) {
  state.frame = frame; state.index = Number(frame.index);
  setText("frame-index",state.index + 1);
  setText("map-frame-label","FRAME " + (state.index + 1) + " / " + state.bootstrap.replay.frame_count);
  setText("metric-clock",fmtTime(frame.time_s)); setText("playback-clock",fmtTime(frame.time_s));
  setText("metric-safe",Number(frame.metrics && frame.metrics.safely_evacuated || 0).toLocaleString());
  setText("metric-supply",Number(frame.metrics && frame.metrics.delivered_supply_units || 0).toLocaleString());
  setText("metric-medical",Number(frame.metrics && frame.metrics.medical_served || 0).toLocaleString());
  setText("footer-hash","SNAPSHOT " + String(frame.snapshot_hash || "--").slice(0,12));
  $("frame-slider").value = state.index;
  $("step-back").disabled = state.index <= 0;
  $("step-forward").disabled = state.index >= state.bootstrap.replay.frame_count - 1;
  renderFleet(frame); renderRouteAudit(frame); renderLedger(frame); drawFrameMap(frame); renderEvents(frame);
}
async function loadFrame(index) {
  if (!state.bootstrap) return;
  const clamped = Math.max(0,Math.min(state.bootstrap.replay.frame_count-1,Number(index)));
  const serial = ++state.requestSerial;
  try {
    const frame = await getJSON("/api/frame?index=" + encodeURIComponent(clamped));
    if (serial !== state.requestSerial) return;
    if (frame.run_id !== state.bootstrap.replay.run_id || Number(frame.index) !== clamped) throw new Error("Frame identity did not match the requested replay.");
    error(""); renderFrame(frame);
  } catch (err) {
    if (serial !== state.requestSerial) return;
    stopPlayback(); error("Could not load replay frame: " + err.message);
  }
}
function stopPlayback() {
  state.playing = false;
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
  setText("play-glyph","▶"); setText("play-text","Play"); $("play-button").setAttribute("aria-label","Play replay");
}
async function playbackTick() {
  if (!state.playing || !state.bootstrap) return;
  if (state.index >= state.bootstrap.replay.frame_count - 1) { stopPlayback(); return; }
  await loadFrame(state.index + 1);
  if (state.playing) state.timer = setTimeout(playbackTick,900);
}
function wirePlayback() {
  $("play-button").addEventListener("click",async () => {
    if (state.playing) { stopPlayback(); return; }
    if (state.index >= state.bootstrap.replay.frame_count - 1) await loadFrame(0);
    if (!state.frame) return;
    state.playing = true; setText("play-glyph","Ⅱ"); setText("play-text","Pause"); $("play-button").setAttribute("aria-label","Pause replay");
    state.timer = setTimeout(playbackTick,900);
  });
  $("step-back").addEventListener("click",() => { stopPlayback(); loadFrame(state.index - 1); });
  $("step-forward").addEventListener("click",() => { stopPlayback(); loadFrame(state.index + 1); });
  $("frame-slider").addEventListener("input",event => { stopPlayback(); loadFrame(Number(event.target.value)); });
}
function wireCoverage() {
  $("coord-form").addEventListener("submit",async event => {
    event.preventDefault();
    const result = $("coord-result"); result.className = "coord-result";
    const text = $("coord-input").value.trim();
    const match = text.match(/^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$/);
    if (!match) { result.textContent = "Enter latitude, longitude as decimal numbers."; result.classList.add("unavailable"); return; }
    const lat = Number(match[1]), lon = Number(match[2]);
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) { result.textContent = "Latitude or longitude is out of range."; result.classList.add("unavailable"); return; }
    result.textContent = "Checking API coverage...";
    try {
      const coverage = await getJSON("/api/coverage?lat=" + encodeURIComponent(lat) + "&lon=" + encodeURIComponent(lon));
      result.textContent = coverage.message || (coverage.available ? "Location is inside the loaded exercise area." : "Unavailable outside loaded exercise area.");
      result.classList.toggle("unavailable",!coverage.available);
    } catch (err) {
      result.textContent = "Coverage check failed: " + err.message; result.classList.add("unavailable");
    }
  });
}
async function init() {
  wireMap(); wirePlayback(); wireCoverage();
  try {
    const data = await getJSON("/api/bootstrap");
    if (!data.area || !data.replay || !Number.isInteger(Number(data.replay.frame_count)) || Number(data.replay.frame_count) < 1) throw new Error("Bootstrap response is missing the area or replay.");
    state.bootstrap = data;
    drawBase(data.area); renderCoverage(data.area.coverage);
    markMode(data.mode);
    setText("run-id","RUN " + String(data.replay.run_id || "--").slice(0,15).toUpperCase());
    setText("scenario-description",data.replay.description || data.label || "Recorded response exercise.");
    setText("top-status",data.area.label || "Replay ready");
    $("frame-slider").max = Number(data.replay.frame_count)-1;
    $("frame-slider").disabled = false; $("play-button").disabled = false;
    const times = data.replay.frame_times_s || [];
    setText("start-time",fmtTime(times[0])); setText("end-time",fmtTime(times[times.length-1]));
    await loadFrame(0);
  } catch (err) {
    setText("top-status","Replay unavailable");
    error("Could not open the exercise: " + err.message);
  }
}
init();
