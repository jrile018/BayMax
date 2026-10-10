import assert from 'node:assert/strict';
import test from 'node:test';
import { createChoiceRecovery, mountPracticeShell } from './vendor/gods_eye_view/practiceShell.js';

test('lost step response and first recovery retain the original choice and block a different retry', async () => {
  const firstNode = { decision_nonce: 'n0', depth: 0 };
  const advancedNode = { decision_nonce: 'n1', depth: 1 };
  const calls = [];
  let recoveryAttempts = 0;
  const request = async (path, body) => {
    calls.push({ path, body });
    if (path === '/step') {
      assert.equal(body.action_id, 'move-amb');
      throw new Error('step response lost after apply');
    }
    assert.equal(path, '/current');
    recoveryAttempts += 1;
    if (recoveryAttempts === 1) throw new Error('first recovery lost');
    return { node: advancedNode };
  };
  const choice = createChoiceRecovery(request);
  const first = await choice.submit({
    session: 's', nonce: firstNode.decision_nonce,
    actionId: 'move-amb', choiceDuration: 2.5,
  });
  assert.equal(first.kind, 'unresolved');
  assert.equal(choice.hasUnresolved(), true);
  const second = await choice.submit({
    session: 's', nonce: firstNode.decision_nonce,
    actionId: 'wait', choiceDuration: 0.3,
  });
  assert.equal(second.kind, 'blocked');
  assert.equal(calls.filter((call) => call.path === '/step').length, 1);
  const recovered = await choice.reconcile();
  assert.deepEqual({
    kind: recovered.kind, node: recovered.node,
    actionId: recovered.actionId, choiceDuration: recovered.choiceDuration,
  }, { kind: 'applied', node: advancedNode, actionId: 'move-amb', choiceDuration: 2.5 });
  assert.equal(choice.hasUnresolved(), false);
  assert.equal((await choice.reconcile()).kind, 'blocked');
  assert.equal(calls.filter((call) => call.path === '/step').length, 1);
});

test('same nonce after recovery releases the choice without recording it', async () => {
  const node = { decision_nonce: 'n0', depth: 0 };
  const choice = createChoiceRecovery(async (path) => {
    if (path === '/step') throw new Error('step failed');
    return { node };
  });
  const result = await choice.submit({
    session: 's', nonce: 'n0', actionId: 'wait', choiceDuration: 1,
  });
  assert.equal(result.kind, 'not_applied');
  assert.equal(choice.hasUnresolved(), false);
});


test('malformed current response keeps the original action pending for another recovery', async () => {
  let reads = 0;
  const choice = createChoiceRecovery(async (path) => {
    if (path === '/step') throw new Error('response lost');
    reads += 1;
    return reads === 1 ? { node: {} } : { node: { decision_nonce: 'n1' } };
  });
  const first = await choice.submit({
    session: 's', nonce: 'n0', actionId: 'move-amb', choiceDuration: 4,
  });
  assert.equal(first.kind, 'unresolved');
  assert.equal(choice.hasUnresolved(), true);
  const recovered = await choice.reconcile();
  assert.equal(recovered.kind, 'applied');
  assert.equal(recovered.actionId, 'move-amb');
  assert.equal(recovered.choiceDuration, 4);
});


class FakeElement {
  constructor(tag = 'div') {
    this.tag = tag;
    this.children = [];
    this.attributes = new Map();
    this.handlers = new Map();
    this.style = {};
    this.hidden = false;
    this._text = '';
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent || '').join(''); }
  append(...children) { for (const child of children) this.appendChild(child); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  setAttribute(key, value) { this.attributes.set(key, String(value)); }
  getAttribute(key) { return this.attributes.get(key) ?? null; }
  addEventListener(key, handler) { this.handlers.set(key, handler); }
  removeEventListener(key) { this.handlers.delete(key); }
  click() { return this.handlers.get('click')?.(); }
  querySelectorAll(selector) {
    if (!['button', 'strong', 'small'].includes(selector)) return [];
    return this.children.flatMap((child) => [
      ...(child.tag === selector ? [child] : []),
      ...(child.querySelectorAll?.(selector) || []),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function fakeDocument() {
  const ids = [
    'practice-root', 'mission-timeline', 'connection-status', 'mission-network',
    'stage-title', 'scenario-content', 'layers-content', 'display-content',
    'controls-content', 'mission-clock', 'thinking-time', 'debrief-panel',
    'notice', 'practice-mode', 'review-mode', 'left-panel-stack',
    'right-context-rail', 'title-bar', 'mission-dock',
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement()]));
  const document = {
    getElementById: (id) => elements.get(id) || null,
    createElement: (tag) => new FakeElement(tag),
    createTextNode: (text) => { const node = new FakeElement('#text'); node.textContent = text; return node; },
    defaultView: { innerWidth: 800, innerHeight: 600, addEventListener() {} },
  };
  return { document, elements };
}

test('mounted shell blocks stale B and restart through double loss, then records A once', async () => {
  const { document, elements } = fakeDocument();
  const firstNode = {
    decision_nonce: 'n0', depth: 0, time_s: 0, knowledge: {},
    actions: [
      { id: 'move-amb', kind: 'dispatch', explanation: 'Move ambulance' },
      { id: 'wait', kind: 'wait', explanation: 'Wait' },
    ],
  };
  const advancedNode = {
    decision_nonce: 'n1', depth: 1, time_s: 15, knowledge: {}, actions: [],
    debrief: { metrics: {}, comparison: {}, critique_prompts: [] },
  };
  const stepActions = [];
  let currentReads = 0;
  let starts = 0;
  const reply = (value) => ({ ok: true, json: async () => value });
  const fetcher = async (path, options) => {
    if (path === '/meta') return reply({
      mode: 'live_full_mission', limits: { decision_limit: 2 },
      episodes: [{ name: 'Test incident' }], severity_scale: [],
    });
    if (path === '/start') { starts += 1; return reply({ session: 's', node: firstNode }); }
    if (path === '/step') {
      stepActions.push(JSON.parse(options.body).action_id);
      throw new Error('step response lost after apply');
    }
    if (path === '/current') {
      currentReads += 1;
      if (currentReads === 1) throw new Error('first current response lost');
      return reply({ node: advancedNode });
    }
    throw new Error('unexpected path ' + path);
  };
  const oldPerformance = globalThis.performance;
  const oldSetInterval = globalThis.setInterval;
  let timeMs = 0;
  globalThis.performance = { now: () => timeMs };
  globalThis.setInterval = () => 1;
  try {
    const shell = mountPracticeShell({ document, fetcher });
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    const controls = elements.get('controls-content');
    const button = (text) => controls.querySelectorAll('button')
      .find((item) => item.textContent.includes(text));
    const staleWait = button('Wait');
    assert.ok(staleWait);
    timeMs = 2500;
    await button('Move ambulance').click();
    assert.equal(shell.getHistory().length, 1);
    assert.equal(button('Wait'), undefined);
    assert.ok(button('Retry current decision'));
    await staleWait.click();
    await shell.restart();
    assert.deepEqual(stepActions, ['move-amb']);
    assert.equal(starts, 1);
    timeMs = 9000;
    elements.get('review-mode').click();
    elements.get('practice-mode').click();
    assert.equal(elements.get('thinking-time').querySelector('strong').textContent,
      'Decision 1 · 2.5 s');
    const retry = button('Retry current decision');
    await retry.click();
    assert.deepEqual(stepActions, ['move-amb']);
    assert.equal(currentReads, 2);
    assert.deepEqual(shell.getHistory(), [firstNode, advancedNode]);
    assert.match(elements.get('thinking-time').querySelector('small').textContent,
      /Total 2\.5 s · last choice 2\.5 s/);
    const debrief = elements.get('debrief-panel').textContent;
    assert.equal(debrief.split('move-amb · 2.5 s').length - 1, 1);
    assert.equal(debrief.includes('wait ·'), false);
    await retry.click();
    assert.equal(shell.getHistory().length, 2);
  } finally {
    globalThis.performance = oldPerformance;
    globalThis.setInterval = oldSetInterval;
  }
});


test('recovery controller blocks concurrent current requests while first recovery is in flight', async () => {
  let releaseCurrent;
  let reads = 0;
  const choice = createChoiceRecovery(async (path) => {
    if (path === '/step') throw new Error('step response lost');
    reads += 1;
    if (reads === 1) return new Promise((resolve) => { releaseCurrent = resolve; });
    return { node: { decision_nonce: 'n1' } };
  });
  const submitted = choice.submit({
    session: 's', nonce: 'n0', actionId: 'move-amb', choiceDuration: 2,
  });
  await new Promise((resolve) => setImmediate(resolve));
  const concurrent = await choice.reconcile();
  assert.equal(concurrent.kind, 'blocked');
  assert.equal(reads, 1);
  releaseCurrent({ node: { decision_nonce: 'n1' } });
  assert.equal((await submitted).actionId, 'move-amb');
});
