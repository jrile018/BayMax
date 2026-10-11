// Run on the cloud executor with node --experimental-vm-modules --test.
// These controls load the actual camera module; they never request a device.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const CAMERA = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  '../../../web/intake/camera.js');
const EPOCH = Date.parse('2026-10-10T12:00:00Z');
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function session(id = 'session-1', expires = EPOCH + 120_000) {
  return { capture_session_id: id, expires_at: new Date(expires).toISOString(),
    arrival_revision: 2, purposes: ['preview', 'capture', 'display', 'assessment'] };
}
function stream() {
  const tracks = [0, 1].map(() => ({ stops: 0, stop() { this.stops++; } }));
  return { tracks, getTracks: () => tracks };
}
function harness({ requests = async () => { throw new Error('unexpected request'); }, permission,
                   sessionResponse = session() } = {}) {
  const calls = [], draws = [], statuses = [], previews = [], captures = [];
  const timers = new Map();
  let time = EPOCH, nextTimer = 0;
  const clock = {
    now: () => time, wallNow: () => time,
    setInterval(callback, interval) { assert.ok(interval >= 1000); const id = ++nextTimer;
      timers.set(id, { callback, kind: 'interval' }); return id; },
    clearInterval(id) { timers.delete(id); },
    setTimeout(callback, delay) { const id = ++nextTimer;
      timers.set(id, { callback, kind: 'timeout', at: time + Math.max(0, delay) });
      return id; },
    clearTimeout(id) { timers.delete(id); },
    advance(ms) { time += ms;
      for (const [id, timer] of [...timers]) if (timer.kind === 'timeout' && timer.at <= time) {
        timers.delete(id); timer.callback();
      }
    },
    async tick() { for (const timer of [...timers.values()])
      if (timer.kind === 'interval') timer.callback();
      await flush(); },
    get activeTimers() { return timers.size; },
  };
  const mediaDevices = { getUserMedia: permission || (async constraints => {
    assert.equal(constraints.audio, false);
    assert.ok(constraints.video);
    return stream();
  }) };
  const video = { videoWidth: 640, videoHeight: 480, srcObject: null,
    play: async () => {}, pause() {} };
  const canvas = { width: 0, height: 0, getContext: () => ({
    clearRect(...args) { draws.push(['clear', ...args]); },
    drawImage(...args) { draws.push(['image', ...args]); },
    strokeRect(...args) { draws.push(['box', ...args]); },
  }) };
  let rasterIndex = 0;
  const runtime = {
    ...clock, mediaDevices,
    createCanvas: () => ({ width: 0, height: 0,
      getContext: () => ({ drawImage() {} }),
      toDataURL: () => `data:image/png;base64,${Buffer.from(`raster-${++rasterIndex}`).toString('base64')}` }),
  };
  const api = async (route, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ route, method: options.method || 'GET', body });
    if (route.endsWith('/capture-session')) return sessionResponse;
    if (route.endsWith('/close')) return { state: 'closed' };
    return requests(route, body, options);
  };
  return { calls, draws, statuses, previews, captures, clock, runtime, api, video, canvas,
    options: { video, canvas, api, arrivalId: 'arrival-1', expectedRevision: 2,
      onPreview: value => previews.push(value), onCaptured: value => captures.push(value),
      onStatus: value => statuses.push(value), runtime } };
}
async function controller(h) {
  const source = await readFile(CAMERA, 'utf8');
  const context = vm.createContext({ console, AbortController, Date, URL, Uint8Array,
    setTimeout, clearTimeout, Buffer });
  const module = new vm.SourceTextModule(source, { context,
    initializeImportMeta(meta) { meta.url = 'https://exercise.example/intake/camera.js'; } });
  await module.link(() => { throw new Error('camera.js must be self-contained'); });
  await module.evaluate();
  return module.namespace.createCameraController(h.options);
}
const count = (h, suffix) => h.calls.filter(item => item.route.endsWith(suffix));
const frame = (id, number, width, height, status = 'ready') => ({
  capture_session_id: id, frame_id: number, image_sha256: 'server-normalized-digest',
  width, height, status,
  boxes: status === 'ready' ? [{ x: 10, y: 10, width: 50, height: 50 }] : [],
});

test('active start samples a bounded preview and selected capture uses the exact server body', async () => {
  const h = harness({ requests: async route => route.endsWith('/preview') ?
    { capture_session_id: 'session-1', frame_id: 1, image_sha256: 'digest',
      width: 640, height: 480, status: 'unavailable', boxes: [] } :
    { photo: { image_id: 'photo-1' }, arrival: { revision: 3, current_image_id: 'photo-1' },
      is_current: true } });
  const c = await controller(h);
  await c.start();
  assert.ok(h.video.srcObject, 'an active controller displays the acquired stream');
  await h.clock.tick();
  assert.equal(count(h, '/preview').length, 1, 'positive preview control');
  assert.deepEqual(Object.keys(count(h, '/preview')[0].body).sort(),
    ['frame_id', 'image_base64', 'media_type']);
  assert.equal(count(h, '/preview')[0].body.frame_id, 1);
  assert.ok(h.previews.some(item => item.status === 'unavailable'),
    'missing detector must be explained as unavailable');
  await c.capture();
  assert.equal(count(h, '/capture').length, 1, 'positive selected-save control');
  assert.deepEqual(Object.keys(count(h, '/capture')[0].body).sort(),
    ['expected_revision', 'image_base64', 'media_type']);
  assert.equal(count(h, '/capture')[0].body.expected_revision, 2);
  assert.equal(h.captures.length, 1);
  assert.equal(h.captures[0].photo.image_id, 'photo-1');
  assert.equal(h.calls.some(item => /arrivals$|confirm|attendance/.test(item.route)), false);
  c.dispose();
});

for (const action of ['stop', 'dispose']) {
  test(`${action} during delayed permission stops every late track and starts no preview`, async () => {
    const gate = deferred(), late = stream();
    const h = harness({ permission: () => gate.promise });
    const c = await controller(h);
    const starting = c.start();
    await flush();
    assert.equal(count(h, '/capture-session').length, 1);
    c[action]();
    gate.resolve(late);
    await starting;
    assert.ok(late.tracks.every(track => track.stops === 1));
    assert.equal(h.clock.activeTimers, 0);
    assert.equal(h.video.srcObject, null);
    assert.equal(count(h, '/preview').length, 0);
    assert.equal(count(h, '/close').length, 1);
  });
}

test('Stop during session creation closes its late handle without requesting permission', async () => {
  const gate = deferred(); let permissionCalls = 0;
  const h = harness({ sessionResponse: gate.promise,
    permission: async () => { permissionCalls++; return stream(); } });
  const c = await controller(h);
  const starting = c.start();
  await flush(); c.stop();
  gate.resolve(session('late-handle'));
  await starting;
  assert.equal(permissionCalls, 0);
  assert.equal(count(h, 'late-handle/close').length, 1);
  assert.equal(h.clock.activeTimers, 0);
});

test('permission granted after session expiry cannot activate video', async () => {
  const gate = deferred(), late = stream();
  const h = harness({ sessionResponse: session('short', EPOCH + 500),
    permission: () => gate.promise });
  const c = await controller(h);
  const starting = c.start();
  await flush(); h.clock.advance(501); gate.resolve(late);
  await starting;
  assert.ok(late.tracks.every(track => track.stops === 1));
  assert.equal(h.video.srcObject, null);
  assert.equal(count(h, '/preview').length, 0);
});

test('Start–Stop–Start rejects the first permission completion and shares concurrent Start', async () => {
  const first = deferred(), old = stream(), fresh = stream();
  let permissions = 0, sessions = 0;
  const h = harness({ sessionResponse: session(), permission: () => {
    permissions++; return permissions === 1 ? first.promise : Promise.resolve(fresh);
  } });
  h.api = async (route, options = {}) => {
    h.calls.push({ route, method: options.method || 'GET', body: options.body && JSON.parse(options.body) });
    if (route.endsWith('/capture-session')) return session(`session-${++sessions}`);
    return { state: 'closed' };
  };
  h.options.api = h.api;
  const c = await controller(h);
  const a = c.start(), shared = c.start();
  assert.equal(a, shared, 'concurrent callers share one pending promise');
  await flush(); c.stop();
  const b = c.start();
  await b;
  first.resolve(old);
  await a;
  assert.ok(old.tracks.every(track => track.stops === 1));
  assert.equal(h.video.srcObject, fresh);
  assert.equal(permissions, 2);
  assert.equal(count(h, '/capture-session').length, 2);
  c.dispose();
});

test('camera denial reports a useful status and closes the created session', async () => {
  const h = harness({ permission: async () => { throw new Error('Permission denied'); } });
  const c = await controller(h);
  await c.start();
  assert.match(h.statuses.map(String).join(' '), /denied|permission|unavailable/i);
  assert.equal(count(h, '/close').length, 1);
  assert.equal(h.video.srcObject, null);
});

test('one in-flight preview, at most one Hz, and stale frame or session response draws no boxes', async () => {
  const gate = deferred();
  const h = harness({ requests: async route => route.endsWith('/preview') ? gate.promise : {} });
  const c = await controller(h);
  await c.start();
  await h.clock.tick();
  assert.equal(count(h, '/preview').length, 1);
  await h.clock.tick();
  assert.equal(count(h, '/preview').length, 1);
  h.clock.advance(1000);
  await h.clock.tick();
  assert.equal(count(h, '/preview').length, 1, 'never start a second preview while first is pending');
  gate.resolve({ capture_session_id: 'wrong', frame_id: 1, image_sha256: 'digest',
    width: 640, height: 480, status: 'ready', boxes: [{ x: 1, y: 1, width: 10, height: 10 }] });
  await flush();
  assert.equal(h.draws.filter(item => item[0] === 'box').length, 0);
  h.clock.advance(1000);
  await h.clock.tick();
  assert.equal(count(h, '/preview').length, 2);
  assert.ok(count(h, '/preview')[1].body.frame_id > 1);
  c.dispose();
});

test('uncertain selected save recovers only the original handle and rejects retired media', async () => {
  let saves = 0, status = 0;
  const h = harness({ requests: async route => {
    if (route.endsWith('/capture')) { saves++; throw new Error('receipt lost'); }
    if (route.endsWith('/session-1')) { status++; return {
      capture_session_id: 'session-1', state: 'consumed', is_current: false,
      photo: { image_id: 'old-photo' }, arrival: { revision: 4,
        current_image_id: 'new-photo' } }; }
    throw new Error('unexpected request');
  } });
  const c = await controller(h);
  await c.start();
  await c.capture();
  assert.equal(saves, 1);
  assert.equal(status, 1, 'status resolves the same possibly consumed handle');
  assert.equal(h.captures.length, 0, 'historical receipt never becomes selected evidence');
  assert.ok(h.statuses.some(value => /stale|retired|refresh|saved/i.test(String(value))));
  assert.equal(h.calls.some(item => /arrivals$|confirm|attendance/.test(item.route)), false);
  c.dispose();
});

test('lost selected-save response recovers the current receipt from the same handle and fresh detail', async () => {
  const h = harness({ requests: async route => {
    if (route.endsWith('/capture')) throw new Error('response lost after commit');
    if (route.endsWith('/session-1')) return { state: 'consumed', is_current: true,
      photo: { image_id: 'photo-1' }, arrival: { revision: 2,
        current_photo: { image_id: 'photo-1' } } };
    if (route.endsWith('api/arrivals/arrival-1')) return { arrival: {
      revision: 3, current_photo: { image_id: 'photo-1' } } };
    throw new Error(`unexpected route ${route}`);
  } });
  const c = await controller(h);
  await c.start();
  const saved = await c.capture();
  assert.equal(saved.photo.image_id, 'photo-1');
  assert.equal(saved.arrival.revision, 3, 'recovered arrival comes from fresh assigned detail');
  assert.equal(saved.is_current, true);
  assert.equal(h.captures.length, 1);
  assert.equal(count(h, '/capture').length, 1);
  assert.equal(count(h, '/session-1').length, 1);
  assert.equal(count(h, 'api/arrivals/arrival-1').length, 1);
  assert.equal(h.calls.some(item => /arrivals$|confirm|attendance/.test(item.route)), false);
  c.dispose();
});

test('wide and portrait camera previews match 1280-long-edge server normalization', async () => {
  for (const [width, height, expectedWidth, expectedHeight, status] of [
    [1920, 1080, 1280, 720, 'ready'],
    [1080, 1920, 720, 1280, 'unavailable'],
  ]) {
    const h = harness({ requests: async route => {
      assert.ok(route.endsWith('/preview'));
      return frame('session-1', 1, expectedWidth, expectedHeight, status);
    } });
    h.video.videoWidth = width;
    h.video.videoHeight = height;
    const c = await controller(h);
    await c.start();
    await h.clock.tick();
    assert.equal(h.canvas.width, expectedWidth);
    assert.equal(h.canvas.height, expectedHeight);
    assert.equal(h.previews.length, 1, `${width}x${height} response must be delivered`);
    assert.equal(h.previews[0].status, status);
    assert.equal(h.draws.filter(item => item[0] === 'box').length,
      status === 'ready' ? 1 : 0);
    c.dispose();
  }
});

test('wrong normalized dimensions draw nothing even when session and frame match', async () => {
  const h = harness({ requests: async () => frame('session-1', 1, 1279, 720) });
  h.video.videoWidth = 1920; h.video.videoHeight = 1080;
  const c = await controller(h);
  await c.start(); await h.clock.tick();
  assert.equal(h.previews.length, 0);
  assert.equal(h.draws.filter(item => item[0] === 'image' || item[0] === 'box').length, 0);
  c.dispose();
});

for (const status of [409, 404]) {
  test(`${status} preview terminal response stops all tracks, clears pixels and sends no later frame`, async () => {
    const acquired = stream();
    const h = harness({ permission: async () => acquired,
      requests: async () => { const error = new Error('arrival no longer available');
        error.status = status; throw error; } });
    const c = await controller(h);
    await c.start();
    await h.clock.tick();
    assert.equal(count(h, '/preview').length, 1);
    assert.ok(acquired.tracks.every(track => track.stops === 1));
    assert.equal(h.video.srcObject, null);
    assert.equal(h.canvas.width, 0);
    assert.equal(h.canvas.height, 0);
    h.clock.advance(1000);
    await h.clock.tick();
    assert.equal(count(h, '/preview').length, 1);
    assert.match(h.statuses.map(String).join(' '), /refresh|changed|unavailable|ended/i);
    c.dispose();
  });
}

test('200 unavailable preview leaves the active camera available for later samples', async () => {
  const acquired = stream();
  const h = harness({ permission: async () => acquired,
    requests: async (_route, body) => frame('session-1', body.frame_id, 640, 480, 'unavailable') });
  const c = await controller(h);
  await c.start(); await h.clock.tick();
  h.clock.advance(1000); await h.clock.tick();
  assert.equal(count(h, '/preview').length, 2);
  assert.equal(h.previews.length, 2);
  assert.ok(acquired.tracks.every(track => track.stops === 0));
  c.dispose();
});

test('acquisition expires and stops tracks while video.play is still pending', async () => {
  const gate = deferred(), acquired = stream();
  const h = harness({ permission: async () => acquired,
    sessionResponse: session('short-play', EPOCH + 1000) });
  h.video.play = () => gate.promise;
  const c = await controller(h);
  const starting = c.start();
  await flush();
  assert.equal(h.video.srcObject, acquired);
  h.clock.advance(1001);
  assert.ok(acquired.tracks.every(track => track.stops === 1),
    'expiry watchdog must not await video.play');
  assert.equal(h.video.srcObject, null);
  assert.equal(h.canvas.width, 0);
  gate.resolve();
  await starting;
  assert.equal(h.clock.activeTimers, 0);
  c.dispose();
});

test('timely video.play activates preview and Stop–Start rejects old late play completion', async () => {
  const first = deferred(), old = stream(), fresh = stream();
  const h = harness();
  let sessions = 0, permissions = 0, plays = 0;
  h.api = async (route, options = {}) => {
    h.calls.push({ route, method: options.method || 'GET',
      body: options.body && JSON.parse(options.body) });
    if (route.endsWith('/capture-session')) return session(`session-${++sessions}`);
    if (route.endsWith('/preview')) return frame('session-2', 1, 640, 480, 'unavailable');
    return { state: 'closed' };
  };
  h.options.api = h.api;
  h.runtime.mediaDevices.getUserMedia = async () => ++permissions === 1 ? old : fresh;
  h.video.play = () => ++plays === 1 ? first.promise : Promise.resolve();
  const c = await controller(h);
  const initial = c.start();
  await flush(); c.stop();
  await c.start();
  first.resolve(); await initial;
  assert.ok(old.tracks.every(track => track.stops >= 1),
    'every old track is physically stopped regardless of repeated idempotent stop calls');
  assert.equal(h.video.srcObject, fresh);
  await h.clock.tick();
  assert.equal(count(h, '/preview').length, 1, 'timely second play permits preview');
  c.dispose();
});

test('a preview response after two seconds draws nothing and timed-out old work cannot alter a newer frame', async () => {
  const first = deferred();
  const h = harness({ requests: async (_route, body) =>
    body.frame_id === 1 ? first.promise : frame('session-1', body.frame_id, 640, 480) });
  const c = await controller(h);
  await c.start(); await h.clock.tick();
  assert.equal(count(h, '/preview').length, 1);
  h.clock.advance(2001);
  await h.clock.tick();
  assert.equal(count(h, '/preview').length, 2,
    'timed-out request must be abortable without blocking newer work');
  assert.equal(h.previews.length, 1);
  assert.equal(h.previews[0].frame_id, 2);
  const imagesBefore = h.draws.filter(item => item[0] === 'image').length;
  first.resolve(frame('session-1', 1, 640, 480));
  await flush();
  assert.equal(h.previews.length, 1);
  assert.equal(h.draws.filter(item => item[0] === 'image').length, imagesBefore);
  h.clock.advance(2001);
  assert.equal(h.canvas.width, 0, 'displayed sampled pixels expire after two seconds');
  assert.equal(h.canvas.height, 0);
  c.dispose();
});

test('a timely matching preview is visible only until its two-second display deadline', async () => {
  const h = harness({ requests: async () => frame('session-1', 1, 640, 480) });
  const c = await controller(h);
  await c.start(); await h.clock.tick();
  assert.equal(h.previews.length, 1);
  assert.equal(h.draws.filter(item => item[0] === 'box').length, 1);
  h.clock.advance(1999);
  assert.equal(h.canvas.width, 640);
  h.clock.advance(2);
  assert.equal(h.canvas.width, 0);
  c.dispose();
});
