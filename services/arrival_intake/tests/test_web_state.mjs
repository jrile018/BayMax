// Run with: node --experimental-vm-modules --test services/arrival_intake/tests/test_web_state.mjs
// Executes the real intake module in a controlled browser environment.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  '../../../web/intake/app.js');
const CAMERA = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  '../../../web/intake/camera.js');

class FakeElement {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.classList = { toggle() {} };
    this.isConnected = true;
    this.hidden = false;
    this.value = '';
    this._text = '';
    this.videoWidth = 640;
    this.videoHeight = 480;
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent || '').join(''); }
  append(...children) { this.children.push(...children); }
  prepend(...children) { this.children.unshift(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  setAttribute(name, value) { this[name] = value; }
  querySelector(selector) {
    const className = selector.replace(/^\./, '');
    return walk(this).find(item => item.className?.split(' ').includes(className));
  }
  remove() { this.removed = true; }
  async play() {}
  pause() {}
  getContext() { return { clearRect() {}, drawImage() {}, strokeRect() {} }; }
  toDataURL() { return 'data:image/png;base64,Y2FtZXJhLWZyYW1l'; }
}
function walk(root) {
  return [root, ...root.children.flatMap(child => child instanceof FakeElement ? walk(child) : [])];
}
function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
}
function json(body) {
  return { status: 200, ok: true, headers: { get: name =>
    name.toLowerCase() === 'content-type' ? 'application/json' : null },
    json: async () => body };
}
async function harness(fetch, { mediaDevices } = {}) {
  const storage = new Map();
  const elements = new Map();
  const urls = { created: [], revoked: [] };
  const timers = new Map();
  let time = 1000, nextTimer = 0;
  const clock = { advance(ms) { time += ms; this.fire(); },
    fire() { for (const [id, timer] of [...timers])
      if (timer.kind === 'timeout' && timer.at <= time) {
        timers.delete(id); timer.callback();
      } },
    get active() { return timers.size; } };
  const setTimer = (callback, delay) => { const id = ++nextTimer;
    timers.set(id, { callback, kind: 'timeout', at: time + Math.max(0, delay) });
    return id; };
  const setRepeatingTimer = callback => { const id = ++nextTimer;
    timers.set(id, { callback, kind: 'interval' }); return id; };
  const clearTimer = id => timers.delete(id);
  let nextUuid = 0;
  class FakeURL extends URL {
    static createObjectURL(blob) {
      const value = `blob:private-${urls.created.length + 1}`;
      urls.created.push({ value, blob });
      return value;
    }
    static revokeObjectURL(value) { urls.revoked.push(value); }
  }
  const document = {
    baseURI: 'https://exercise.example/intake/',
    createElement: tag => new FakeElement(tag),
    createTextNode: text => ({ textContent: String(text) }),
    createTextNode: text => ({ textContent: String(text) }),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new FakeElement());
      return elements.get(id);
    },
  };
  const sessionStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  };
  const context = vm.createContext({
    document, sessionStorage, Element: FakeElement, URL: FakeURL, Headers,
    AbortController, location: { origin: 'https://exercise.example' },
    crypto: { randomUUID: () => `operation-${++nextUuid}` },
    window: { confirm: () => true, prompt: () => '' }, fetch,
    navigator: { mediaDevices: mediaDevices || { getUserMedia: async () => {
      throw new Error('controlled camera unavailable'); } } },
    performance: { now: () => time }, setTimeout: setTimer, clearTimeout: clearTimer,
    setInterval: setRepeatingTimer, clearInterval: clearTimer,
    FileReader: class {}, Blob, console,
  });
  const source = await readFile(APP, 'utf8');
  const module = new vm.SourceTextModule(source + '\nexport { state, startArrival, confirmPending, pendingPanel, showPhoto, revokePhoto, privateAccessLost, render };', {
    context, initializeImportMeta(meta) { meta.url = 'https://exercise.example/intake/app.js'; },
  });
  await module.link(async specifier => {
    assert.equal(specifier, './camera.js');
    const camera = new vm.SourceTextModule(await readFile(CAMERA, 'utf8'), {
      context, initializeImportMeta(meta) { meta.url = 'https://exercise.example/intake/camera.js'; },
    });
    return camera;
  });
  await module.evaluate();
  sessionStorage.setItem('intake-token', 'test-token');
  return { app: module.namespace, document, sessionStorage, urls, FakeElement, clock };
}

test('lost confirmation receipt keeps one operation and cannot create a second arrival', async () => {
  const operations = new Map();
  let loseFirstResponse = true;
  const { app, sessionStorage } = await harness(async (url, options = {}) => {
    const route = new URL(url).pathname;
    if (route.endsWith('/api/intakes/sid/arrivals') && options.method === 'POST') {
      const key = JSON.parse(options.body).operation_key;
      if (!operations.has(key)) operations.set(key, {
        arrival_id: `arrival-${operations.size + 1}`, arrival_number: operations.size + 1,
      });
      if (loseFirstResponse) { loseFirstResponse = false; throw new Error('response lost after commit'); }
      return json(operations.get(key));
    }
    if (route.endsWith('/api/intakes')) return json({ intakes: [{ session_id: 'sid' }] });
    if (route.endsWith('/api/intakes/sid')) return json({
      session_summary: { session_id: 'sid', vehicle_id: 'bus', destination_node: 'shelter',
        case_id: 'case', intake_state: 'open', expected_count: 2,
        confirmed_count: operations.size, difference: 2 - operations.size,
        awaiting_reviews: 0, completed_reviews: 0 },
      arrivals: [...operations.values()].map(entry => ({ ...entry, state: 'confirmed',
        revision: 0, care_state: 'not_referred', current_photo: null, assessment: null })),
    });
    throw new Error(`unexpected fetch ${route}`);
  });
  app.state.me = { actor_id: 'volunteer', role: 'volunteer', session_ids: ['sid'] };
  app.state.sid = 'sid';
  app.state.intakes = [{ session_id: 'sid' }];
  app.state.session = { session_summary: { vehicle_id: 'bus', destination_node: 'shelter',
    case_id: 'case', intake_state: 'open', expected_count: 2, confirmed_count: 0,
    difference: 2, awaiting_reviews: 0, completed_reviews: 0 }, arrivals: [] };
  await assert.rejects(app.startArrival(), /response lost/);
  const pending = JSON.parse(sessionStorage.getItem('intake-pending-operation'));
  assert.equal(pending.key, 'operation-1');
  assert.equal(operations.size, 1, 'the server committed the first POST');
  const view = app.pendingPanel(pending);
  const discard = walk(view).find(item => item.tagName === 'BUTTON' &&
    item.textContent.includes('Discard'));
  assert.equal(discard, undefined, 'a committed-but-unacknowledged operation cannot be discarded');
  await assert.rejects(app.startArrival(), /Resolve or explicitly discard|Resolve the pending|pending operation/);
  await app.confirmPending();
  assert.equal(operations.size, 1);
  assert.equal(sessionStorage.getItem('intake-pending-operation'), null);
  assert.equal(JSON.parse(sessionStorage.getItem('intake-current-arrival')).aid, 'arrival-1');
});

test('late private photo responses after navigation or logout allocate no object URL', async () => {
  const fetchGate = deferred();
  const bodyGate = deferred();
  const bodyCalled = deferred();
  let calls = 0;
  const { app, urls, FakeElement, document, sessionStorage } = await harness(async () => {
    calls += 1;
    if (calls === 1) return fetchGate.promise;
    if (calls === 2) return { status: 200, ok: true,
      headers: { get: name => name.toLowerCase() === 'content-type' ? 'image/png' : null },
      blob: () => { bodyCalled.resolve(); return bodyGate.promise; } };
    return { status: 200, ok: true, headers: { get: name =>
      name.toLowerCase() === 'content-type' ? 'image/png' : null },
      blob: async () => new Blob(['approved illustration']) };
  });
  app.state.me = { actor_id: 'reviewer', role: 'care_reviewer' };
  app.state.sid = 'sid';
  const firstView = new FakeElement();
  const first = app.showPhoto('arrival-1', firstView);
  app.state.sid = null;
  firstView.isConnected = false;
  app.revokePhoto();
  fetchGate.resolve({ status: 200, ok: true, headers: { get: name =>
    name.toLowerCase() === 'content-type' ? 'image/png' : null },
    blob: async () => new Blob(['image']) });
  await first;
  assert.equal(urls.created.length, 0, 'navigation before fetch must not allocate a URL');
  assert.equal(firstView.querySelector('.photo-preview'), undefined);

  app.state.me = { actor_id: 'reviewer', role: 'care_reviewer' };
  app.state.sid = 'sid';
  const secondView = new FakeElement();
  const second = app.showPhoto('arrival-1', secondView);
  await bodyCalled.promise;
  app.privateAccessLost();
  secondView.isConnected = false;
  bodyGate.resolve(new Blob(['image']));
  await second;
  assert.equal(urls.created.length, 0, 'logout during blob read must not allocate a URL');
  assert.equal(secondView.querySelector('.photo-preview'), undefined);

  // Positive control: a still-authorized, connected view must show the image.
  sessionStorage.setItem('intake-token', 'test-token');
  app.state.me = { actor_id: 'reviewer', role: 'care_reviewer' };
  app.state.sid = 'sid';
  const activeView = new FakeElement();
  document.getElementById('content').append(activeView);
  await app.showPhoto('arrival-1', activeView);
  assert.equal(urls.created.length, 1);
  assert.ok(activeView.querySelector('.photo-preview'));
  app.revokePhoto();
  assert.deepEqual(urls.revoked, [urls.created[0].value]);
  app.privateAccessLost();
  assert.equal(document.getElementById('content').querySelector('.photo-preview'), undefined);
});

test('voided current arrival is labeled corrected and can advance without an impossible write', async () => {
  let writes = 0;
  const { app, document, sessionStorage } = await harness(async (_url, options = {}) => {
    if (options.method) writes++;
    throw new Error('unexpected network request');
  });
  app.state.me = { actor_id: 'volunteer', role: 'volunteer', session_ids: ['sid'] };
  app.state.sid = 'sid';
  app.state.session = { session_summary: { case_id: 'case', vehicle_id: 'bus',
    destination_node: 'shelter', intake_state: 'open', expected_count: 1,
    confirmed_count: 0, difference: 1, awaiting_reviews: 1, completed_reviews: 0 },
    arrivals: [{ arrival_id: 'arrival-1', arrival_number: 1, state: 'voided',
      confirmed_by: 'volunteer', confirmed_at: '2026-10-10T12:00:00Z', revision: 2,
      care_state: 'awaiting_review', assessment: null, current_photo: null,
      latest_volunteer_observation: null }] };
  sessionStorage.setItem('intake-current-arrival', JSON.stringify({ sid: 'sid', aid: 'arrival-1' }));
  app.render();
  const content = document.getElementById('content');
  assert.match(content.textContent, /corrected|voided/i);
  assert.doesNotMatch(content.textContent, /Presence is confirmed/);
  const next = walk(content).find(item => item.tagName === 'BUTTON' && item.textContent === 'Next arrival');
  assert.ok(next);
  assert.equal(next.disabled, false);
  next.listeners.click();
  assert.equal(sessionStorage.getItem('intake-current-arrival'), null);
  assert.equal(writes, 0);
  assert.equal(app.state.session.session_summary.confirmed_count, 0);
});

test('coordinator can drill into anonymous private detail and return without reviewer authority', async () => {
  const requests = [];
  const detail = { arrival_id: 'arrival-1', arrival_number: 1, state: 'confirmed',
    care_state: 'awaiting_review', revision: 3, current_photo: { image_id: 'private-capture' },
    assessment: { result: 'Yes', origin: 'scripted_training', reason: 'Exercise cue', arrival_revision: 2 },
    human_concerns: [{ actor_id: 'volunteer', text: 'Reported dizziness', created_at: 'time' }] };
  const { app, document } = await harness(async (url, options = {}) => {
    requests.push({ path: new URL(url).pathname, method: options.method || 'GET' });
    if (new URL(url).pathname.endsWith('/api/arrivals/arrival-1')) return json({ arrival: detail });
    throw new Error('unexpected request');
  });
  app.state.me = { actor_id: 'coordinator', role: 'coordinator', session_ids: ['sid'] };
  app.state.sid = 'sid';
  app.state.session = { session_summary: { case_id: 'case', vehicle_id: 'bus',
    destination_node: 'shelter', intake_state: 'open', expected_count: 1,
    confirmed_count: 1, difference: 0, awaiting_reviews: 1, completed_reviews: 0 },
    arrivals: [detail] };
  app.render();
  let content = document.getElementById('content');
  const open = walk(content).find(item => item.tagName === 'BUTTON' && /detail/i.test(item.textContent));
  assert.ok(open, 'coordinator arrival row needs an actual detail action');
  await open.listeners.click();
  await new Promise(resolve => setImmediate(resolve));
  content = document.getElementById('content');
  assert.match(content.textContent, /anonymous reference.*arrival-1/i);
  assert.match(content.textContent, /Scripted exercise input/);
  assert.match(content.textContent, /Reported dizziness/);
  assert.ok(walk(content).some(item => item.tagName === 'BUTTON' && /illustration|photo/i.test(item.textContent)));
  assert.equal(walk(content).some(item => item.tagName === 'BUTTON' && /Record care review complete/.test(item.textContent)), false);
  assert.equal(requests.some(item => item.method === 'POST'), false);
  const back = walk(content).find(item => item.tagName === 'BUTTON' && /back|return/i.test(item.textContent));
  assert.ok(back);
  await back.listeners.click();
  assert.doesNotMatch(document.getElementById('content').textContent, /Reported dizziness/);
});

test('volunteer camera controls perform selected save then exact real assessment without a second attendance write', async () => {
  const requests = [];
  const tracks = [{ stopped: 0, stop() { this.stopped++; } }];
  let sessions = 0;
  let detail = { arrival_id: 'arrival-1', arrival_number: 1, state: 'confirmed',
    revision: 2, care_state: 'not_referred', current_photo: null, assessment: null };
  const summary = { session_id: 'sid', vehicle_id: 'bus', destination_node: 'shelter',
    case_id: 'case', intake_state: 'open', expected_count: 1, confirmed_count: 1,
    difference: 0, awaiting_reviews: 0, completed_reviews: 0 };
  const { app, document, sessionStorage, urls } = await harness(async (url, options = {}) => {
    const route = new URL(url).pathname;
    const body = options.body && JSON.parse(options.body);
    requests.push({ route, method: options.method || 'GET', body });
    if (route.endsWith('/api/arrivals/arrival-1/capture-session')) return json({
      capture_session_id: `capture-${++sessions}`, expires_at: '2099-01-01T00:00:00Z',
      arrival_revision: detail.revision, purposes: ['preview', 'capture', 'display', 'assessment'] });
    if (route.endsWith('/api/capture-sessions/capture-1/capture')) {
      detail = { ...detail, revision: 3, current_photo: { image_id: 'photo-1' } };
      return json({ photo: detail.current_photo, arrival: detail, is_current: true });
    }
    if (route.endsWith('/api/arrivals/arrival-1/assessment')) {
      detail = { ...detail, revision: 4, assessment: { result: 'Unsure',
        origin: 'real_unavailable', reason: 'Analysis unavailable', arrival_revision: 3 } };
      return json({ arrival: detail });
    }
    if (route.endsWith('/api/intakes')) return json({ intakes: [summary] });
    if (route.endsWith('/api/intakes/sid')) return json({ session_summary: summary, arrivals: [detail] });
    if (route.endsWith('/photo')) return { status: 200, ok: true,
      headers: { get: name => name.toLowerCase() === 'content-type' ? 'image/png' : null },
      blob: async () => new Blob(['selected photo']) };
    if (route.endsWith('/close')) return json({ state: 'closed' });
    throw new Error(`unexpected request ${route}`);
  }, { mediaDevices: { getUserMedia: async constraints => {
    assert.equal(constraints.audio, false);
    return { getTracks: () => tracks };
  } } });
  app.state.me = { actor_id: 'volunteer', role: 'volunteer', session_ids: ['sid'] };
  app.state.sid = 'sid';
  app.state.intakes = [summary];
  app.state.session = { session_summary: summary, arrivals: [detail] };
  sessionStorage.setItem('intake-current-arrival', JSON.stringify({ sid: 'sid', aid: 'arrival-1' }));
  app.render();
  const findButton = label => walk(document.getElementById('content'))
    .find(item => item.tagName === 'BUTTON' && item.textContent === label);
  assert.ok(findButton('Start camera'));
  await findButton('Start camera').listeners.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(findButton('Capture and assess'));
  await findButton('Capture and assess').listeners.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests.find(item => item.route.endsWith('/assessment')).body,
    { expected_revision: 3, mode: 'real' });
  assert.deepEqual(Object.keys(requests.find(item => item.route.endsWith('/capture')).body).sort(),
    ['expected_revision', 'image_base64', 'media_type']);
  assert.equal(requests.some(item => item.route.endsWith('/api/intakes/sid/arrivals') &&
    item.method === 'POST'), false);
  assert.match(document.getElementById('content').textContent, /unable|unavailable|unsure/i);
  assert.equal(findButton('View saved photo').disabled, false,
    'refresh after capture must leave the saved-photo control enabled');
  assert.equal(findButton('Retake').disabled, false);
  await findButton('View saved photo').listeners.click();
  assert.equal(urls.created.length, 1, 'saved-photo control remains operable');
  await findButton('Retake').listeners.click();
  assert.equal(sessions, 2, 'retake starts a new session for the same arrival');
  assert.deepEqual(requests.filter(item => item.route.endsWith('/capture-session')).map(item =>
    item.body.expected_revision), [2, 4]);
  app.privateAccessLost();
  assert.ok(tracks[0].stopped >= 1, 'logout stops the acquired track');
});

test('uncertain null capture refresh leaves saved-photo and retake controls enabled and usable', async () => {
  let sessions = 0, saves = 0;
  const detail = { arrival_id: 'arrival-1', arrival_number: 1, state: 'confirmed',
    revision: 2, care_state: 'not_referred', current_photo: { image_id: 'older-photo' },
    assessment: null };
  const summary = { session_id: 'sid', vehicle_id: 'bus', destination_node: 'shelter',
    case_id: 'case', intake_state: 'open', expected_count: 1, confirmed_count: 1,
    difference: 0, awaiting_reviews: 0, completed_reviews: 0 };
  const { app, document, sessionStorage, urls } = await harness(async (url, options = {}) => {
    const route = new URL(url).pathname;
    if (route.endsWith('/capture-session')) return json({ capture_session_id: `capture-${++sessions}`,
      expires_at: '2099-01-01T00:00:00Z', arrival_revision: 2,
      purposes: ['preview', 'capture', 'display', 'assessment'] });
    if (route.endsWith('/capture')) { saves++; throw new Error('save reply lost'); }
    if (route.endsWith('/capture-1') && !options.method) return json({ state: 'active',
      is_current: false });
    if (route.endsWith('/close')) return json({ state: 'closed' });
    if (route.endsWith('/api/intakes')) return json({ intakes: [summary] });
    if (route.endsWith('/api/intakes/sid')) return json({ session_summary: summary,
      arrivals: [detail] });
    if (route.endsWith('/photo')) return { status: 200, ok: true,
      headers: { get: name => name.toLowerCase() === 'content-type' ? 'image/png' : null },
      blob: async () => new Blob(['older photo']) };
    throw new Error(`unexpected request ${route}`);
  }, { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } });
  app.state.me = { actor_id: 'volunteer', role: 'volunteer', session_ids: ['sid'] };
  app.state.sid = 'sid'; app.state.intakes = [summary];
  app.state.session = { session_summary: summary, arrivals: [detail] };
  sessionStorage.setItem('intake-current-arrival', JSON.stringify({ sid: 'sid', aid: 'arrival-1' }));
  app.render();
  const findButton = label => walk(document.getElementById('content'))
    .find(item => item.tagName === 'BUTTON' && item.textContent === label);
  await findButton('Start camera').listeners.click();
  await findButton('Capture and assess').listeners.click();
  assert.equal(saves, 1);
  assert.equal(findButton('View saved photo').disabled, false);
  assert.equal(findButton('Retake').disabled, false);
  await findButton('View saved photo').listeners.click();
  assert.equal(urls.created.length, 1);
  await findButton('Retake').listeners.click();
  assert.equal(sessions, 2);
  app.privateAccessLost();
});

test('live photo lease expiry clears pixels and late detail renewal cannot restore them', async () => {
  const renewal = deferred();
  let renewalRequests = 0;
  const { app, document, urls, clock, FakeElement } = await harness(async url => {
    const route = new URL(url).pathname;
    if (route.endsWith('/photo')) return { status: 200, ok: true,
      headers: { get: name => ({ 'content-type': 'image/png',
        'x-display-grant-id': 'grant-a', 'x-display-grant-version': '1',
        'x-display-expires-at': '2099-01-01T00:00:00Z',
        'x-display-lease-ms': '5000' })[name.toLowerCase()] || null },
      blob: async () => new Blob(['live-photo']) };
    if (route.endsWith('/api/arrivals/arrival-1')) {
      renewalRequests++; return renewal.promise;
    }
    throw new Error(`unexpected request ${route}`);
  });
  app.state.me = { actor_id: 'volunteer', role: 'volunteer', session_ids: ['sid'] };
  app.state.sid = 'sid';
  const view = new FakeElement();
  document.getElementById('content').append(view);
  await app.showPhoto('arrival-1', view);
  assert.equal(urls.created.length, 1, 'positive live-photo display control');
  assert.ok(view.querySelector('.photo-preview'));
  clock.advance(4000);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(renewalRequests, 1, 'detail renewal must actually launch before expiry');
  clock.advance(1001);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(urls.revoked, [urls.created[0].value]);
  assert.ok(!view.querySelector('.photo-preview') || view.querySelector('.photo-preview').removed);
  renewal.resolve(json({ arrival: { arrival_id: 'arrival-1',
    display_authorization: { grant_id: 'grant-a', version: 1,
      expires_at: '2099-01-01T00:00:00Z', lease_ms: 5000 } } }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(urls.created.length, 1, 'late renewal must not revive an expired image');
});

test('denied live-photo lease renewal clears visible pixels and object URL', async () => {
  let renewalRequests = 0;
  const { app, document, urls, clock, FakeElement } = await harness(async url => {
    const route = new URL(url).pathname;
    if (route.endsWith('/photo')) return { status: 200, ok: true,
      headers: { get: name => ({ 'content-type': 'image/png',
        'x-display-grant-id': 'grant-a', 'x-display-grant-version': '1',
        'x-display-expires-at': '2099-01-01T00:00:00Z',
        'x-display-lease-ms': '5000' })[name.toLowerCase()] || null },
      blob: async () => new Blob(['live-photo']) };
    if (route.endsWith('/api/arrivals/arrival-1')) {
      renewalRequests++;
      return { status: 403, ok: false, headers: { get: () => 'application/json' },
        json: async () => ({ error: { code: 'forbidden' } }) };
    }
    throw new Error(`unexpected request ${route}`);
  });
  app.state.me = { actor_id: 'volunteer', role: 'volunteer', session_ids: ['sid'] };
  app.state.sid = 'sid';
  const view = new FakeElement();
  document.getElementById('content').append(view);
  await app.showPhoto('arrival-1', view);
  assert.equal(urls.created.length, 1);
  clock.advance(4000);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(renewalRequests, 1);
  assert.deepEqual(urls.revoked, [urls.created[0].value]);
  assert.ok(view.querySelector('.photo-preview').removed);
  assert.equal(app.state.me, null, 'access loss clears private app state');
});
