/* Read-only signed-in JupyterLab view of the root-owned accepted publication. */
(() => {
  "use strict";
  if (typeof window.__knightMapsLabStop === "function") window.__knightMapsLabStop();
  const previous = document.getElementById("knight-maps-live-lab");
  if (previous) previous.remove();

  const host = document.createElement("section");
  host.id = "knight-maps-live-lab";
  host.setAttribute("aria-label", "Knight26 accepted Situation dashboard");
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `
    :host{position:fixed;inset:38px 12px 12px;z-index:10000;display:block;overflow:auto;
      color:#eaf4f3;background:radial-gradient(circle at 10% 0%,#163d4e,#0a1721 55%,#08131a);
      border:1px solid #3b6c75;border-radius:14px;box-shadow:0 24px 70px #000b;
      font:15px/1.48 system-ui,-apple-system,Segoe UI,sans-serif}
    *{box-sizing:border-box} main{max-width:1200px;margin:auto;padding:28px 30px 40px}
    header{display:flex;justify-content:space-between;gap:20px;align-items:start;border-bottom:1px solid #33545b;padding-bottom:18px}
    .eyebrow{color:#87ced1;text-transform:uppercase;letter-spacing:.17em;font-size:11px;font-weight:750}
    h1{font-size:clamp(30px,3vw,48px);line-height:1.1;letter-spacing:-.03em;margin:7px 0 4px}
    p{margin:5px 0;color:#b7cdd0} .actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
    button{border:1px solid #537983;border-radius:7px;background:#15333d;color:#f3ffff;padding:9px 14px;cursor:pointer;font:inherit}
    button:hover,button:focus-visible{background:#285561;outline:2px solid #8be4e2;outline-offset:2px}
    .status{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0 24px;padding:13px 15px;border:1px solid #3d666d;border-radius:8px;background:#102c36}
    .status strong{color:#c3fbf5}.warn{color:#ffcc88!important}.error{color:#ff9791!important}
    .grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
    article{border:1px solid #355a62;background:#10242d;border-radius:10px;padding:19px;min-height:142px}
    article h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:#a6cbd0;margin:0 0 12px}
    article .value{font-size:31px;line-height:1.15;font-weight:730;color:#f7ffff}
    article .value.unknown{color:#ffcb8d} article small{display:block;margin-top:11px;color:#adc5ca}
    .source{margin-top:20px;border-top:1px solid #355a62;padding-top:18px;color:#a9c1c7;font-size:12px;overflow-wrap:anywhere}
    .source code{color:#d9eeee;font-size:12px} .empty{padding:24px;border:1px dashed #577078;border-radius:8px}
    @media(max-width:800px){:host{inset:32px 0 0;border-radius:0}main{padding:20px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}header{display:block}.actions{justify-content:flex-start;margin-top:16px}}
    @media(max-width:500px){.grid{grid-template-columns:1fr}}
  `;
  root.append(style);
  const main = document.createElement("main");
  root.append(main);
  const header = document.createElement("header");
  main.append(header);
  const heading = document.createElement("div");
  header.append(heading);
  const eyebrow = document.createElement("div");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "Knight26 · accepted source publication";
  heading.append(eyebrow);
  const title = document.createElement("h1");
  title.textContent = "Current Situation";
  heading.append(title);
  const subtitle = document.createElement("p");
  subtitle.textContent = "Read-only source evidence. No dispatch or forecast is enabled.";
  heading.append(subtitle);
  const actions = document.createElement("div");
  actions.className = "actions";
  header.append(actions);
  const refresh = document.createElement("button");
  refresh.type = "button";
  refresh.textContent = "Refresh now";
  actions.append(refresh);
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "Close panel";
  actions.append(close);
  const status = document.createElement("div");
  status.className = "status";
  status.setAttribute("role", "status");
  main.append(status);
  const grid = document.createElement("div");
  grid.className = "grid";
  main.append(grid);
  const source = document.createElement("div");
  source.className = "source";
  main.append(source);

  const base = window.location.pathname.split("/lab")[0];
  if (!/^\/instances\/[^/]+$/.test(base)) {
    status.textContent = "Jupyter instance base URL unavailable; no publication displayed.";
    return;
  }
  const contentsBase = base + "/api/contents/knight26/artifacts/coordinator/accepted-situation/";
  const hex64 = /^[a-f0-9]{64}$/;
  let stopped = false;
  let inFlight = false;
  let timer = null;
  let pending = null;

  function labelStatus(message, kind) {
    status.replaceChildren();
    const line = document.createElement("strong");
    if (kind) line.className = kind;
    line.textContent = message;
    status.append(line);
  }
  async function contentFile(name, signal) {
    const response = await fetch(contentsBase + name, {
      credentials: "same-origin", cache: "no-store", signal,
      headers: { Accept: "application/json" }
    });
    if (!response.ok) throw Error("Contents API HTTP " + response.status);
    const wrapper = await response.json();
    if (typeof wrapper.content !== "string") throw Error("Contents API returned no text content");
    return wrapper.content;
  }
  async function sha256(value) {
    const bytes = new TextEncoder().encode(value);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
  }
  const isRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const hasKeys = (value, keys) => isRecord(value) &&
    Object.keys(value).sort().join("\0") === [...keys].sort().join("\0");
  // SnapshotPublisher uses sorted, compact UTF-8 JSON. Fail closed if its
  // canonical form cannot be reproduced; two real publications were checked.
  function canonical(value) {
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (isRecord(value)) return "{" + Object.keys(value).sort().map(
      key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
    return JSON.stringify(value);
  }
  const digestObject = value => sha256(canonical(value));
  async function validatePublication(publication, pointer, raw) {
    const version = "knight26-snapshot-publication-v1";
    if (!isRecord(publication) || raw !== canonical(publication) + "\n" ||
        publication.publication_version !== version ||
        publication.view_hash !== pointer.view_hash ||
        !hasKeys(publication.capabilities,
          ["can_calculate_operational_outcomes", "can_dispatch"]) ||
        publication.capabilities.can_calculate_operational_outcomes !== false ||
        publication.capabilities.can_dispatch !== false) {
      throw Error("Invalid canonical publication or capabilities");
    }
    const snapshot = publication.snapshot;
    if (!isRecord(snapshot) || snapshot.schema_version !== "knight26-incident-v1" ||
        typeof snapshot.snapshot_hash !== "string" || !hex64.test(snapshot.snapshot_hash)) {
      throw Error("Invalid incident snapshot");
    }
    const plain = { ...snapshot };
    delete plain.snapshot_hash;
    if (await digestObject(plain) !== snapshot.snapshot_hash) throw Error("Snapshot hash mismatch");
    if (publication.incident_id !== snapshot.incident_id ||
        publication.cutoff_utc !== snapshot.cutoff_utc) {
      throw Error("Incident identity or cutoff mismatch");
    }
    const categories = snapshot.categories;
    if (!hasKeys(categories, ["hazard", "needs", "closures", "vehicles", "stock", "capacity"]) ||
        Object.values(categories).some(value => value !== null && !Array.isArray(value))) {
      throw Error("Invalid incident categories");
    }
    const required = ["incident_id", "bbox_lonlat", "cutoff_utc", "revision_history",
      "unconfirmed_leads", "accepted_source_refs", "ledger_watermark",
      "in_flight_commitments", "source_health"];
    if (required.some(key => !Object.hasOwn(snapshot, key))) throw Error("Missing incident fields");
    const projection = publication.projection_input ?? null;
    if (projection !== null &&
        (!isRecord(projection) || projection.initial_snapshot_hash !== snapshot.snapshot_hash ||
         typeof projection.projection_input_hash !== "string" ||
         !hex64.test(projection.projection_input_hash) ||
         projection.can_calculate_operational_outcomes !== false)) {
      throw Error("Invalid projection");
    }
    if (projection !== null) {
      const plainProjection = { ...projection };
      delete plainProjection.projection_input_hash;
      if (await digestObject(plainProjection) !== projection.projection_input_hash) {
        throw Error("Projection hash mismatch");
      }
    }
    const mission = {
      publication_version: version, incident_id: snapshot.incident_id,
      bbox_lonlat: snapshot.bbox_lonlat, cutoff_utc: snapshot.cutoff_utc,
      categories, revision_history: snapshot.revision_history,
      unconfirmed_leads: snapshot.unconfirmed_leads,
      accepted_source_refs: snapshot.accepted_source_refs,
      ledger_watermark: snapshot.ledger_watermark,
      in_flight_commitments: snapshot.in_flight_commitments,
      metadata_attestations: publication.metadata_attestations ?? null,
      geography_binding: publication.geography_binding ?? null
    };
    const missionHash = await digestObject(mission);
    if (publication.mission_hash !== missionHash) throw Error("Mission publication hash mismatch");
    const view = {
      publication_version: version, mission_hash: missionHash,
      snapshot_hash: snapshot.snapshot_hash, source_health: snapshot.source_health,
      synopsis: publication.synopsis ?? null,
      projection_input_hash: projection?.projection_input_hash ?? null
    };
    if (await digestObject(view) !== pointer.view_hash) throw Error("View publication hash mismatch");
    return snapshot;
  }
  function card(name, value, note, unknown) {
    const item = document.createElement("article");
    const h = document.createElement("h2");
    h.textContent = name;
    const v = document.createElement("div");
    v.className = "value" + (unknown ? " unknown" : "");
    v.textContent = value;
    const n = document.createElement("small");
    n.textContent = note;
    item.append(h, v, n);
    grid.append(item);
  }
  function render(publication, pointer, verifiedHash) {
    const snapshot = publication.snapshot;
    const ageMs = Date.now() - Date.parse(snapshot.cutoff_utc);
    const ageMinutes = Number.isFinite(ageMs) ? Math.max(0, Math.floor(ageMs / 60000)) : null;
    const freshness = ageMinutes === null ? "Cutoff unavailable" : ageMinutes < 60 ? ageMinutes + " min since cutoff" : Math.floor(ageMinutes / 60) + " h since cutoff";
    labelStatus("Verified accepted publication · " + freshness + " · Checked " + new Date().toLocaleTimeString(), ageMinutes === null || ageMinutes >= 60 ? "warn" : "");
    grid.replaceChildren();
    const categories = snapshot.categories;
    const hazard = categories.hazard;
    card("Hazard source records", Array.isArray(hazard) ? String(hazard.length) : "Unknown", "Accepted records; coverage does not imply local impact.", !Array.isArray(hazard));
    for (const name of ["capacity", "closures", "needs", "stock", "vehicles"]) {
      const value = categories[name];
      const unknown = value == null;
      const shown = unknown ? "Unknown" : Array.isArray(value) ? String(value.length) + " records" : typeof value === "object" ? "Source data present" : String(value);
      card(name[0].toUpperCase() + name.slice(1), shown, unknown ? "No accepted operational evidence" : "See accepted publication for details", unknown);
    }
    source.replaceChildren();
    const lines = [
      "Source cutoff: " + snapshot.cutoff_utc,
      "Snapshot SHA-256: " + snapshot.snapshot_hash,
      "Publication SHA-256: " + verifiedHash,
      "View hash: " + pointer.view_hash,
      "JupyterLab signed-in Contents API · automatic check every 30 seconds"
    ];
    for (const line of lines) {
      const p = document.createElement("div");
      p.textContent = line;
      source.append(p);
    }
  }
  async function poll() {
    if (stopped || inFlight) return;
    inFlight = true;
    refresh.disabled = true;
    const controller = new AbortController();
    pending = controller;
    const deadline = setTimeout(() => controller.abort(), 10000);
    try {
      const pointerRaw = await contentFile("current.json", controller.signal);
      if (new TextEncoder().encode(pointerRaw).byteLength > 4096) throw Error("Pointer exceeds limit");
      const pointer = JSON.parse(pointerRaw);
      if (!hasKeys(pointer, ["publication_version", "view_hash", "publication_file", "publication_sha256"]) ||
          pointer.publication_version !== "knight26-snapshot-publication-v1" ||
          typeof pointer.view_hash !== "string" || !hex64.test(pointer.view_hash) ||
          pointer.publication_file !== "publication-" + pointer.view_hash + ".json" ||
          typeof pointer.publication_sha256 !== "string" || !hex64.test(pointer.publication_sha256)) {
        throw Error("Accepted pointer has invalid shape");
      }
      const raw = await contentFile(pointer.publication_file, controller.signal);
      if (new TextEncoder().encode(raw).byteLength > 16777216) throw Error("Publication exceeds limit");
      const verifiedHash = await sha256(raw);
      if (verifiedHash !== pointer.publication_sha256) throw Error("Publication SHA-256 mismatch");
      const publication = JSON.parse(raw);
      await validatePublication(publication, pointer, raw);
      if (stopped) return;
      render(publication, pointer, verifiedHash);
    } catch (error) {
      if (stopped) return;
      grid.replaceChildren();
      source.replaceChildren();
      labelStatus("Accepted source unavailable: " +
        (error.name === "AbortError" ? "Request timed out" : error.message), "error");
    } finally {
      clearTimeout(deadline);
      if (pending === controller) pending = null;
      inFlight = false;
      refresh.disabled = false;
    }
  }
  refresh.addEventListener("click", poll);
  close.addEventListener("click", () => window.__knightMapsLabStop());
  window.__knightMapsLabStop = () => {
    stopped = true;
    if (timer) clearInterval(timer);
    pending?.abort();
    host.remove();
    delete window.__knightMapsLabStop;
  };
  document.body.append(host);
  labelStatus("Checking accepted source…");
  poll();
  timer = setInterval(poll, 30000);
})();
