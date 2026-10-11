import { createCameraController } from './camera.js';

const BASE = new URL(".", import.meta.url);
const TOKEN = "intake-token";
const PENDING = "intake-pending-operation";
const CURRENT = "intake-current-arrival";
const RESULT_TEXT = {
  Yes: "Possible visible concern—get checked",
  No: "No visible concern detected in this photo",
  Unsure: "Unsure—get checked",
};
const $ = (id) => document.getElementById(id);
const state = { me: null, intakes: [], sid: null, session: null, aggregate: null,
  history: [], reviews: [], reviewId: null, coordinatorId: null,
  photoUrl: null, photoAbort: null, photoRenewAbort: null, photoContainer: null,
  photoLeaseTimer: null, photoRenewTimer: null, photoLeaseGeneration: 0,
  photoGeneration: 0, camera: null, busy: false };

function el(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined && text !== null) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}
function button(label, action, className = "") {
  const item = el("button", label, className);
  item.type = "button";
  item.disabled = state.busy;
  item.addEventListener("click", action);
  return item;
}
function field(form, labelText, name, type = "text", value = "") {
  const label = el("label", labelText);
  const input = document.createElement("input");
  input.name = name;
  input.type = type;
  input.value = value;
  input.required = true;
  label.append(input);
  form.append(label);
  return input;
}
function panel(title) {
  const section = el("section", null, "panel");
  section.append(el("h2", title));
  return section;
}
function text(parent, label, value) {
  const row = el("p");
  row.append(el("strong", label + " "), document.createTextNode(String(value ?? "—")));
  parent.append(row);
}
function notice(message, error = false) {
  $("notice").textContent = message || "";
  $("notice").classList.toggle("error", error);
}
function revokePhoto() {
  state.photoGeneration += 1;
  state.photoLeaseGeneration += 1;
  state.photoAbort?.abort();
  state.photoAbort = null;
  state.photoRenewAbort?.abort();
  state.photoRenewAbort = null;
  if (state.photoLeaseTimer !== null) clearTimeout(state.photoLeaseTimer);
  if (state.photoRenewTimer !== null) clearTimeout(state.photoRenewTimer);
  state.photoLeaseTimer = null;
  state.photoRenewTimer = null;
  if (state.photoUrl) URL.revokeObjectURL(state.photoUrl);
  state.photoUrl = null;
  state.photoContainer?.querySelector('.photo-preview')?.remove();
  state.photoContainer?.querySelector('.photo-region')?.remove();
  state.photoContainer = null;
}
function stopCamera() {
  state.camera?.dispose();
  state.camera = null;
}
function privateAccessLost() {
  stopCamera();
  revokePhoto();
  sessionStorage.removeItem(TOKEN);
  state.me = null;
  state.intakes = [];
  state.sid = null;
  state.session = null;
  state.aggregate = null;
  state.history = [];
  state.reviews = [];
  state.coordinatorId = null;
  $("content").replaceChildren();
  $("workspace").hidden = true;
  $("login-panel").hidden = false;
  $("logout").hidden = true;
  $("identity").textContent = "";
}
function target(path) {
  if (typeof path !== "string" || !path || path.startsWith("/") ||
      path.includes("..") || path.includes("?") || path.includes("#") ||
      /^[a-z][a-z\d+.-]*:/i.test(path)) throw new Error("Invalid intake path");
  const url = new URL(path, BASE);
  if (url.origin !== location.origin || !url.pathname.startsWith(BASE.pathname))
    throw new Error("Invalid intake path");
  return url;
}
async function checkedResponse(response) {
  if (response.status === 401 || response.status === 403) privateAccessLost();
  if (!response.ok) {
    let code;
    try { code = (await response.json())?.error?.code; } catch { /* status remains */ }
    const known = {
      unauthorized: "Access expired. Sign in again.",
      forbidden: "This role or assignment cannot perform that action.",
      not_found: "That assigned record is unavailable. Refresh the intake.",
      conflict: "Saved state changed. Refresh before trying again.",
      unavailable: "This service is unavailable. The action was not confirmed.",
      invalid_request: "The request was rejected. Check the fields and approved image.",
      method_not_allowed: "This action is unavailable.",
    };
    const error = new Error(known[code] || `Request failed (${response.status}).`);
    error.status = response.status;
    error.code = typeof code === "string" ? code : "http_error";
    throw error;
  }
  return response;
}
export async function api(path, options = {}) {
  const token = sessionStorage.getItem(TOKEN);
  if (!token) throw new Error("Enter your access token first.");
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", "Bearer " + token);
  const response = await fetch(target(path), { ...options, headers, cache: "no-store" });
  await checkedResponse(response);
  if (!response.headers.get("Content-Type")?.startsWith("application/json"))
    throw new Error("The server returned an unexpected response. Nothing is confirmed.");
  let body;
  try { body = await response.json(); }
  catch { throw new Error("The server returned invalid JSON. Nothing is confirmed."); }
  if (!body || typeof body !== "object" || Array.isArray(body))
    throw new Error("The server returned invalid JSON. Nothing is confirmed.");
  return body;
}
function post(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
}
function saved(key) {
  try { return JSON.parse(sessionStorage.getItem(key) || "null"); } catch { return null; }
}
function save(key, value) { sessionStorage.setItem(key, JSON.stringify(value)); }
function selected() { return state.intakes.find((item) => item.session_id === state.sid); }
function current() {
  const value = saved(CURRENT);
  return value && value.sid === state.sid ? value : null;
}
function pending() { return saved(PENDING); }
function sessionPath(suffix = "") { return `api/intakes/${encodeURIComponent(state.sid)}${suffix}`; }
function arrivalPath(aid, suffix = "") { return `api/arrivals/${encodeURIComponent(aid)}${suffix}`; }
function arrival(aid) { return state.session?.arrivals?.find((item) => item.arrival_id === aid); }
function stats(summary) {
  const wrapper = el("div", null, "stats");
  for (const [label, value] of [
    ["Expected", summary.expected_count], ["Confirmed", summary.confirmed_count],
    ["Difference", summary.difference], ["Awaiting review", summary.awaiting_reviews],
    ["Reviews complete", summary.completed_reviews],
  ]) {
    const cell = el("div", null, "stat");
    cell.append(el("strong", value ?? "—"), el("span", label));
    wrapper.append(cell);
  }
  return wrapper;
}
function context(summary) {
  const section = panel("Selected bus");
  text(section, "Bus:", summary.vehicle_id);
  text(section, "Destination:", summary.destination_node);
  text(section, "Case:", summary.case_id);
  text(section, "Status:", summary.intake_state);
  section.append(stats(summary));
  if (typeof summary.difference === "number" && summary.difference !== 0) {
    section.append(el("p", summary.difference > 0 ?
      `${summary.difference} fewer confirmed than expected.` :
      `${Math.abs(summary.difference)} more confirmed than expected.`, "caution"));
  }
  return section;
}
function operationLabel(item) { return `Arrival ${item.arrival_number} · anonymous reference ${item.arrival_id}`; }
async function run(action, rerender = true) {
  if (state.busy) return;
  state.busy = true;
  try { await action(); }
  catch (error) { notice(error.message || "Action was not confirmed.", true); }
  finally { state.busy = false; if (rerender) render(); }
}
async function refresh() {
  if (!state.me) return;
  const list = await api("api/intakes");
  state.intakes = Array.isArray(list.intakes) ? list.intakes : [];
  if (!state.sid) { render(); return; }
  if (!state.intakes.some((item) => item.session_id === state.sid)) {
    state.sid = null; state.session = null; render(); return;
  }
  state.session = await api(sessionPath());
  if (state.me.role === "coordinator") {
    state.aggregate = await api(sessionPath("/aggregate"));
    const result = await api(sessionPath("/history"));
    state.history = Array.isArray(result.history) ? result.history : [];
  }
  if (state.me.role === "care_reviewer") {
    const result = await api(sessionPath("/reviews"));
    state.reviews = Array.isArray(result.reviews) ? result.reviews : [];
  }
  render();
}
async function openSession(sid) {
  state.sid = sid;
  state.reviewId = null;
  state.coordinatorId = null;
  revokePhoto();
  await refresh();
}
async function confirmPending() {
  const operation = pending();
  if (!operation) return;
  state.sid = operation.sid;
  notice("Saving presence. Waiting for the server receipt…");
  const receipt = await post(sessionPath("/arrivals"), { operation_key: operation.key });
  if (!receipt.arrival_id || !receipt.arrival_number) throw new Error("Invalid receipt; presence remains unconfirmed.");
  save(CURRENT, { sid: operation.sid, aid: receipt.arrival_id, key: operation.key });
  sessionStorage.removeItem(PENDING);
  await refresh();
  notice("Presence confirmed by the server. Review the saved arrival below.");
}
async function startArrival() {
  if (pending()) throw new Error("Resolve or explicitly discard the pending operation first.");
  if (current()) throw new Error("Complete the current arrival before starting another.");
  if (!crypto.randomUUID) throw new Error("This browser cannot create a safe operation key.");
  save(PENDING, { sid: state.sid, key: crypto.randomUUID() });
  render();
  await confirmPending();
}
function clearCurrent() { sessionStorage.removeItem(CURRENT); stopCamera(); revokePhoto(); }
function pendingPanel(operation) {
  const section = panel("Presence still unconfirmed");
  section.append(el("p", "The last attempt has no receipt in this browser. Retry with the same operation key to resolve it against the server. It may already have counted this person. Do not start a second arrival for them; if retries cannot resolve it, ask a coordinator to reconcile the attendance before continuing.", "caution"));
  const actions = el("div", null, "actions");
  actions.append(button("Resolve saved attempt", () => run(confirmPending)));
  section.append(actions);
  if (operation.sid !== state.sid) section.append(el("p", "This pending operation belongs to another assigned bus."));
  return section;
}
function resultPanel(detail) {
  const assessment = detail.assessment;
  if (!assessment) return el("p", "No saved assessment for this capture. Choose an assessment or skip it to record Unsure.", "caution");
  const result = ["Yes", "No", "Unsure"].includes(assessment.result) ? assessment.result : "Unsure";
  const box = el("div", null, `result ${result.toLowerCase()}`);
  const origin = assessment.origin === "scripted_training" ? "Scripted exercise input" :
    assessment.origin === "evaluated_model" ? "Model result" : "Analysis unavailable";
  box.append(el("strong", RESULT_TEXT[result]), el("small", origin));
  box.append(el("p", "This suggestion does not clear a person for care. Record your own observation below."));
  return box;
}
function observationIsCurrent(detail) {
  const observation = detail.latest_volunteer_observation;
  const assessment = detail.assessment;
  return !!(observation && assessment && observation.arrival_revision > assessment.arrival_revision);
}
function observationForm(detail) {
  const section = panel("Your observation and concern decision");
  section.append(el("p", "Record what you observed after every result, including No. A concern creates a care handoff request; it does not prove care was completed."));
  const form = el("form");
  const yes = el("input"); yes.type = "radio"; yes.name = "concern"; yes.value = "yes"; yes.required = true;
  const yesLabel = el("label", "I have a concern to hand off", "choice"); yesLabel.prepend(yes);
  const no = el("input"); no.type = "radio"; no.name = "concern"; no.value = "no";
  const noLabel = el("label", "No additional concern observed", "choice"); noLabel.prepend(no);
  form.append(yesLabel, noLabel);
  const note = field(form, "Concern detail (required when you have a concern)", "text");
  note.required = false;
  const submit = el("button", "Save my observation"); submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(async () => {
      const concern = yes.checked;
      if (!yes.checked && !no.checked) throw new Error("Choose your observation decision.");
      if (concern && !note.value.trim()) throw new Error("Describe the concern before saving.");
      const response = await post(arrivalPath(detail.arrival_id, "/observation"), {
        expected_revision: detail.revision, concern, text: concern ? note.value.trim() : "",
      });
      if (!response.arrival) throw new Error("No observation receipt was returned.");
      await refresh();
      notice(concern ? "Concern handoff requested and saved. Care completion remains pending." : "Your observation was saved.");
    });
  });
  section.append(form);
  if (observationIsCurrent(detail)) {
    const observation = detail.latest_volunteer_observation;
    section.append(el("p", observation.concern ? "Saved: concern handed off." :
      "Saved: no additional concern observed.", "badge good"));
  }
  return section;
}
function cameraControl(detail) {
  const section = panel('Live camera');
  section.className += ' camera-panel';
  section.append(el('p', 'Start camera only after this adult has agreed to live framing and a selected photo for assessment. Framing feedback uses brief previews; only the frame you select is saved.', 'caution'));
  const stage = el('div', null, 'camera-stage');
  const video = el('video');
  video.autoplay = true;
  video.muted = true;
  video.playsInline = true;
  video.setAttribute('playsinline', '');
  video.setAttribute('aria-label', 'Live camera view');
  const overlay = el('canvas');
  overlay.setAttribute('aria-label', 'Most recently sampled framing feedback');
  stage.append(video, overlay);
  section.append(stage);
  const status = el('p', 'Camera is off.', 'camera-status');
  status.setAttribute('role', 'status');
  section.append(status);
  const actions = el('div', null, 'actions');
  const controller = createCameraController({ video, canvas: overlay, api,
    arrivalId: detail.arrival_id, expectedRevision: detail.revision,
    onPreview: result => {
      status.textContent = result.status === 'unavailable' ?
        'Live framing is unavailable. You may still select a clear frame.' :
        result.status === 'no_face' ? 'No face is in the sampled frame.' :
        result.status === 'multiple_faces' ? 'More than one face is in the sampled frame.' :
        'A face is in the sampled frame.';
    },
    onCaptured: () => { status.textContent = 'Selected photo saved. Requesting assessment…'; },
    onStatus: message => { status.textContent = String(message); } });
  state.camera = controller;
  const start = button('Start camera', () => run(async () => {
    await controller.start();
  }, false));
  const capture = button('Capture and assess', () => run(async () => {
    const saved = await controller.capture();
    if (!saved) {
      await refresh();
      notice('Saved state refreshed. Check the current photo before trying again.');
      return;
    }
    const response = await post(arrivalPath(detail.arrival_id, '/assessment'), {
      expected_revision: saved.arrival.revision, mode: 'real',
    });
    if (!response.arrival) throw new Error('No assessment receipt was returned.');
    await refresh();
    notice('Selected photo and assessment saved. Record your observation.');
  }));
  actions.append(start, capture);
  if (detail.current_photo) actions.append(button('Retake', () => run(async () => {
    await controller.start();
  }, false), 'quiet'));
  actions.append(button('Stop camera', () => {
    controller.stop();
    status.textContent = 'Camera stopped.';
  }, 'quiet'));
  section.append(actions);
  return section;
}
function photoControl(detail) {
  const section = panel("Use an approved file instead");
  section.append(el("p", "This separate fallback accepts an operator supplied illustration with its approved source reference. File selection does not grant permission.", "caution"));
  const form = el("form");
  const source = field(form, "Approved source reference", "source_reference");
  const fallbackLabel = el("label", "Choose approved image file");
  const fallback = el("input"); fallback.type = "file"; fallback.accept = "image/jpeg,image/png";
  fallbackLabel.append(fallback);
  form.append(fallbackLabel);
  const submit = el("button", detail.current_photo ? "Save retake" : "Save approved image"); submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(async () => {
      const file = fallback.files?.[0];
      if (!file) throw new Error("Select an approved exercise illustration, or skip capture.");
      if (!["image/jpeg", "image/png"].includes(file.type) || file.size > 5 * 1024 * 1024)
        throw new Error("Use a JPEG or PNG illustration no larger than 5 MiB.");
      if (!source.value.trim()) throw new Error("Enter the operator approved source reference.");
      const image_base64 = await fileBase64(file);
      const response = await post(arrivalPath(detail.arrival_id, "/photo"), {
        expected_revision: detail.revision, image_base64, media_type: file.type,
        permission: { source_kind: "operator_created_illustration",
          source_reference: source.value.trim(), capture_allowed: true,
          display_allowed: true, processing_allowed: true,
          verified_by: state.me.actor_id, verified_at: new Date().toISOString() },
      });
      if (!response.photo) throw new Error("No saved image receipt was returned.");
      await refresh();
      notice("Approved illustration saved. Request a new assessment for this capture.");
    });
  });
  section.append(form);
  if (detail.current_photo) section.append(button("View saved photo", () =>
    run(() => showPhoto(detail.arrival_id, section, detail.current_photo.image_id), false), "quiet"));
  return section;
}
function fileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the selected file."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.readAsDataURL(file);
  });
}
function displayLease(raw, started) {
  const { grant_id, version, expires_at, lease_ms } = raw;
  if ([grant_id, version, expires_at, lease_ms].every(value => value == null))
    return null; // Existing static illustrations.
  const serverExpiry = Date.parse(expires_at);
  const duration = Number(lease_ms);
  if (!grant_id || !Number.isInteger(Number(version)) ||
      !Number.isFinite(serverExpiry) || !Number.isFinite(duration) ||
      duration <= 0 || duration > 5000)
    throw new Error('Saved photo display authorization is invalid.');
  const remaining = serverExpiry - Date.now();
  const deadline = started + Math.min(duration, remaining);
  if (deadline <= performance.now()) throw new Error('Saved photo display permission expired.');
  return { grant_id, version: Number(version), expires_at, deadline };
}
function schedulePhotoLease(aid, container, lease, generation, imageId) {
  const authorizationGeneration = ++state.photoLeaseGeneration;
  const stillCurrent = () => generation === state.photoGeneration &&
    authorizationGeneration === state.photoLeaseGeneration &&
    container.isConnected && !!state.photoUrl;
  const remaining = lease.deadline - performance.now();
  state.photoLeaseTimer = setTimeout(() => {
    if (stillCurrent()) revokePhoto();
  }, Math.max(0, remaining));
  state.photoRenewTimer = setTimeout(() => {
    if (!stillCurrent()) return;
    const started = performance.now();
    const abort = new AbortController();
    state.photoRenewAbort = abort;
    void api(arrivalPath(aid), { signal: abort.signal }).then(response => {
      if (!stillCurrent()) return;
      const detail = response.arrival;
      const next = detail?.display_authorization;
      if (!next || next.grant_id !== lease.grant_id ||
          Number(next.version) !== lease.version ||
          (imageId && detail.current_photo?.image_id !== imageId)) {
        revokePhoto(); return;
      }
      const renewed = displayLease(next, started);
      if (!stillCurrent() || !renewed) return;
      clearTimeout(state.photoLeaseTimer);
      clearTimeout(state.photoRenewTimer);
      schedulePhotoLease(aid, container, renewed, generation, imageId);
    }).catch(() => { if (stillCurrent()) revokePhoto(); }).finally(() => {
      if (state.photoRenewAbort === abort) state.photoRenewAbort = null;
    });
  }, Math.max(0, remaining - 1000));
}
async function showPhoto(aid, container, imageId = null) {
  revokePhoto();
  const token = sessionStorage.getItem(TOKEN);
  if (!token) throw new Error("Access expired.");
  const generation = state.photoGeneration;
  const sid = state.sid;
  const actor = state.me?.actor_id;
  const controller = new AbortController();
  state.photoAbort = controller;
  try {
    const started = performance.now();
    const response = await fetch(target(arrivalPath(aid, "/photo")), {
      headers: { Authorization: "Bearer " + token }, cache: "no-store",
      signal: controller.signal,
    });
    await checkedResponse(response);
    const media = response.headers.get("Content-Type")?.split(";")[0];
    if (!["image/png", "image/jpeg"].includes(media)) throw new Error("Unexpected private image format.");
    const lease = displayLease({
      grant_id: response.headers.get('X-Display-Grant-Id') || undefined,
      version: response.headers.get('X-Display-Grant-Version'),
      expires_at: response.headers.get('X-Display-Expires-At'),
      lease_ms: response.headers.get('X-Display-Lease-Ms'),
    }, started);
    const blob = await response.blob();
    if (lease && performance.now() >= lease.deadline) return;
    if (controller.signal.aborted || generation !== state.photoGeneration ||
        sid !== state.sid || actor !== state.me?.actor_id || !container.isConnected) return;
    const url = URL.createObjectURL(blob);
    if (controller.signal.aborted || generation !== state.photoGeneration ||
        sid !== state.sid || actor !== state.me?.actor_id || !container.isConnected) {
      URL.revokeObjectURL(url);
      return;
    }
    state.photoUrl = url;
    state.photoContainer = container;
    const image = el("img", null, "photo-preview");
    image.alt = "Approved exercise illustration for this anonymous arrival";
    image.src = url;
    container.querySelector(".photo-preview")?.remove();
    container.append(image);
    if (lease) schedulePhotoLease(aid, container, lease, generation, imageId);
  } catch (error) {
    if (error.name !== "AbortError") throw error;
  } finally {
    if (state.photoAbort === controller) state.photoAbort = null;
  }
}
function assessmentActions(detail) {
  const section = panel("Photo suggestion");
  section.append(resultPanel(detail));
  const actions = el("div", null, "actions");
  for (const [mode, label] of [["scripted", "Use scripted exercise input"],
                               ["real", "Request genuine analysis"],
                               ["skipped", "Skip or decline capture · Unsure"]]) {
    actions.append(button(label, () => run(async () => {
      const response = await post(arrivalPath(detail.arrival_id, "/assessment"), {
        expected_revision: detail.revision, mode,
      });
      if (!response.arrival) throw new Error("No assessment receipt was returned.");
      await refresh();
      notice("Suggestion saved. Record your own observation before moving on.");
    }), mode === "skipped" ? "quiet" : ""));
  }
  section.append(actions);
  return section;
}
function renderCurrent(detail) {
  const wrapper = el("div");
  const head = panel("Current arrival");
  head.append(el("p", operationLabel(detail), "reference"));
  if (detail.state === "voided") {
    head.append(el("p", "Attendance was corrected: this arrival no longer counts as confirmed presence. The care handoff remains visible.", "caution"));
    text(head, "Care handoff:", detail.care_state?.replaceAll("_", " "));
    wrapper.append(head);
    const next = panel("Continue");
    next.append(button("Next arrival", () => { clearCurrent(); notice("Ready for the next arrival."); render(); }));
    wrapper.append(next);
    return wrapper;
  }
  head.append(el("p", "Presence is confirmed. Retakes and referrals keep this reference."));
  text(head, "Care handoff:", detail.care_state?.replaceAll("_", " "));
  wrapper.append(head, cameraControl(detail), photoControl(detail), assessmentActions(detail));
  if (detail.assessment) wrapper.append(observationForm(detail));
  const next = panel("Continue");
  if (!observationIsCurrent(detail)) next.append(el("p", "Save an assessment and your observation before moving to the next person.", "caution"));
  const nextButton = button("Next arrival", () => { clearCurrent(); notice("Ready for the next arrival."); render(); });
  nextButton.disabled ||= !observationIsCurrent(detail);
  next.append(nextButton);
  wrapper.append(next);
  return wrapper;
}
function renderVolunteer() {
  const content = $("content");
  content.append(context(state.session.session_summary));
  const operation = pending();
  if (operation) {
    content.append(pendingPanel(operation));
    return;
  }
  const active = current();
  if (active) {
    const detail = arrival(active.aid);
    if (detail) content.append(renderCurrent(detail));
    else content.append(el("p", "Current receipt could not be found. Refresh saved state before continuing.", "caution"));
    return;
  }
  const actions = panel("Confirm one person at a time");
  actions.append(el("p", "Confirm that a person is physically present at this bus. No name or face identity match is used."));
  const start = button("Start arrival · confirm presence", () => run(startArrival));
  start.disabled ||= state.session.session_summary.intake_state !== "open";
  actions.append(start);
  const finish = button("Finish intake", () => run(async () => {
    if (pending() || current()) throw new Error("Resolve the current arrival before finishing.");
    const summary = state.session.session_summary;
    const response = await post(sessionPath("/finish"), { expected_revision: summary.revision });
    if (!response.session_summary) throw new Error("No finish receipt was returned.");
    await refresh();
    notice("Intake finished. Any unfinished assessment was saved as Unsure; care reviews remain separate.");
  }), "quiet");
  finish.disabled ||= state.session.session_summary.intake_state !== "open";
  actions.append(finish);
  content.append(actions);
}
function correctionForm(title, changeFromForm) {
  const section = panel(title);
  const form = el("form");
  changeFromForm(form);
  const reason = field(form, "Reason for correction", "reason");
  const submit = el("button", "Save correction"); submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(async () => {
      const change = form._change();
      const response = await post(sessionPath("/corrections"), {
        expected_revision: state.session.session_summary.revision,
        reason: reason.value.trim(), change,
      });
      if (!response.session_summary) throw new Error("No correction receipt was returned.");
      await refresh();
      notice("Correction saved with actor, time and reason.");
    });
  });
  section.append(form);
  return section;
}
function renderCoordinator() {
  const content = $("content");
  const summary = state.session.session_summary;
  content.append(context(summary));
  if (state.coordinatorId) {
    const detail = state.session.arrivals.find(item => item.arrival_id === state.coordinatorId);
    const section = panel(detail ? `Arrival ${detail.arrival_number} · private detail` : "Arrival detail unavailable");
    section.append(button("Back to bus overview", () => {
      state.coordinatorId = null; render();
    }, "quiet"));
    if (!detail) {
      section.append(el("p", "This arrival is no longer in the saved bus view. Refresh to reconcile it.", "caution"));
    } else {
      section.append(el("p", operationLabel(detail), "reference"));
      text(section, "Attendance:", detail.state);
      text(section, "Care handoff:", detail.care_state?.replaceAll("_", " "));
      section.append(resultPanel(detail));
      for (const concern of detail.human_concerns || []) {
        const row = el("div", null, "row");
        text(row, "Volunteer concern:", concern.text);
        text(row, "Reported by:", concern.actor_id);
        text(row, "Time:", concern.created_at);
        section.append(row);
      }
      if (detail.current_photo) section.append(button("View saved photo", () =>
        run(() => showPhoto(detail.arrival_id, section, detail.current_photo.image_id), false), "quiet"));
    }
    content.append(section);
    return;
  }
  const aggregate = panel("Bus-level totals");
  aggregate.append(el("p", "This projection contains totals and trip context only."));
  aggregate.append(stats(state.aggregate || summary));
  content.append(aggregate);
  const arrivals = panel("Attendance and care queue");
  if (!state.session.arrivals.length) arrivals.append(el("p", "No confirmed arrivals yet."));
  for (const item of state.session.arrivals) {
    const row = el("div", null, "row");
    row.append(el("strong", `Arrival ${item.arrival_number}`));
    text(row, "Attendance:", item.state);
    text(row, "Care:", item.care_state?.replaceAll("_", " "));
    row.append(button("View private detail", () => {
      state.coordinatorId = item.arrival_id; render();
    }, "quiet"));
    arrivals.append(row);
  }
  content.append(arrivals);
  const forms = el("div", null, "two-column");
  forms.append(correctionForm("Correct expected count", (form) => {
    const count = field(form, "Revised expected count", "expected_count", "number", summary.expected_count);
    count.min = "0"; count.step = "1";
    form._change = () => ({ expected_count: Number(count.value) });
  }));
  forms.append(correctionForm("Correct an arrival", (form) => {
    const label = el("label", "Anonymous arrival");
    const select = el("select");
    for (const item of state.session.arrivals) {
      const option = el("option", `Arrival ${item.arrival_number} · ${item.state}`);
      option.value = item.arrival_id; select.append(option);
    }
    label.append(select); form.append(label);
    const counted = el("label", "Count as confirmed", "choice");
    const checkbox = el("input"); checkbox.type = "checkbox"; checkbox.checked = true;
    counted.prepend(checkbox); form.append(counted);
    form._change = () => ({ arrival_id: select.value, counted: checkbox.checked });
  }));
  content.append(forms);
  if (summary.intake_state === "finished") {
    const reopen = panel("Reopen intake");
    reopen.append(el("p", "Reopening allows the volunteer to continue. It does not reset care review."));
    reopen.append(button("Reopen with reason", () => {
      const reason = window.prompt("Reason for reopening this intake");
      if (!reason?.trim()) return;
      run(async () => {
        await post(sessionPath("/corrections"), { expected_revision: summary.revision,
          reason: reason.trim(), change: { intake_state: "open" } });
        await refresh(); notice("Intake reopened and recorded in correction history.");
      });
    }));
    content.append(reopen);
  }
  const history = panel("Correction history");
  if (!state.history.length) history.append(el("p", "No corrections recorded."));
  for (const entry of state.history) {
    const row = el("div", null, "row");
    row.append(el("strong", `${entry.change}: ${entry.before} → ${entry.after}`));
    text(row, "Reason:", entry.reason);
    text(row, "Recorded by:", entry.actor_id);
    text(row, "Time:", entry.occurred_at);
    if (entry.arrival_id) text(row, "Arrival reference:", entry.arrival_id);
    history.append(row);
  }
  content.append(history);
}
function renderReviewer() {
  const content = $("content");
  content.append(context(state.session.session_summary));
  const queue = panel("Care handoff queue");
  queue.append(el("p", "A referral is a request for review. Completion must be recorded by a care reviewer."));
  if (!state.reviews.length) queue.append(el("p", "No pending reviews."));
  for (const detail of state.reviews) {
    const row = el("div", null, "row");
    row.append(el("strong", `Arrival ${detail.arrival_number} · ${detail.care_state}`));
    row.append(button("Review details", () => { state.reviewId = detail.arrival_id; render(); }, "quiet"));
    queue.append(row);
  }
  content.append(queue);
  const detail = state.reviews.find((item) => item.arrival_id === state.reviewId);
  if (!detail) return;
  const section = panel(`Care review · arrival ${detail.arrival_number}`);
  section.append(resultPanel(detail));
  for (const concern of detail.human_concerns || []) {
    const row = el("div", null, "row");
    text(row, "Volunteer concern:", concern.text);
    text(row, "Reported by:", concern.actor_id);
    text(row, "Time:", concern.created_at);
    section.append(row);
  }
  if (detail.current_photo) section.append(button("View saved photo", () =>
    run(() => showPhoto(detail.arrival_id, section, detail.current_photo.image_id), false), "quiet"));
  const complete = button("Record care review complete", () => run(async () => {
    if (detail.review_revision === null) throw new Error("No current review revision. Refresh the queue.");
    const response = await post(arrivalPath(detail.arrival_id, "/review-complete"), {
      expected_revision: detail.review_revision,
    });
    if (!response.arrival) throw new Error("No completion receipt was returned.");
    state.reviewId = null;
    await refresh();
    notice("Review completion saved against the current handoff revision.");
  }));
  complete.disabled ||= detail.care_state !== "awaiting_review";
  section.append(complete);
  content.append(section);
}
function renderList() {
  const content = $("content");
  const intro = panel("Choose an assigned bus");
  intro.append(el("p", "Select the bus and destination shown in your exercise assignment."));
  content.append(intro);
  if (!state.intakes.length) content.append(el("p", "No intakes are assigned to this token."));
  const grid = el("div", null, "grid");
  for (const summary of state.intakes) {
    const card = panel(summary.vehicle_id);
    text(card, "Destination:", summary.destination_node);
    text(card, "Status:", summary.intake_state);
    card.append(stats(summary));
    card.append(button("Open this bus", () => run(() => openSession(summary.session_id))));
    grid.append(card);
  }
  content.append(grid);
}
function render() {
  stopCamera();
  revokePhoto();
  $("login-panel").hidden = !!state.me;
  $("workspace").hidden = !state.me;
  $("logout").hidden = !state.me;
  $("identity").textContent = state.me ? `${state.me.role.replaceAll("_", " ")} · ${state.me.actor_id}` : "";
  $("back").hidden = !state.sid;
  const content = $("content"); content.replaceChildren();
  if (!state.me) return;
  if (!state.sid || !state.session) { renderList(); return; }
  if (state.me.role === "volunteer") renderVolunteer();
  else if (state.me.role === "coordinator") renderCoordinator();
  else if (state.me.role === "care_reviewer") renderReviewer();
  else content.append(el("p", "This role has no intake view."));
}
async function signIn(token) {
  sessionStorage.setItem(TOKEN, token);
  try {
    const identity = await api("api/me");
    if (!identity.actor_id || !identity.role || !Array.isArray(identity.session_ids))
      throw new Error("Invalid identity response.");
    state.me = identity;
    await refresh();
    const operation = pending();
    if (operation && identity.session_ids.includes(operation.sid)) {
      state.sid = operation.sid;
      await confirmPending();
    } else {
      const active = saved(CURRENT);
      if (active && identity.session_ids.includes(active.sid)) await openSession(active.sid);
    }
    notice("");
  } catch (error) {
    if (!state.me) privateAccessLost();
    throw error;
  }
}
$("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const token = $("token").value.trim();
  $("token").value = "";
  run(() => signIn(token));
});
$("logout").addEventListener("click", () => {
  privateAccessLost();
  sessionStorage.removeItem(CURRENT);
  notice("Signed out. Private images and details have been cleared.");
  render();
});
$("back").addEventListener("click", () => {
  stopCamera();
  state.sid = null; state.session = null; state.reviewId = null; state.coordinatorId = null;
  revokePhoto(); notice(""); render();
});
$("refresh").addEventListener("click", () => run(async () => {
  await refresh();
  if (pending()) await confirmPending();
  notice("Saved state refreshed from the server.");
}));
if (sessionStorage.getItem(TOKEN)) run(() => signIn(sessionStorage.getItem(TOKEN)));
else render();
