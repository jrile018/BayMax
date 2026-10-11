// Run with: node --experimental-vm-modules --test services/arrival_intake/tests/test_web_integration.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../web');
class Element {
  constructor(tag = 'div') { this.tagName = tag.toUpperCase(); this.children = []; this.hidden = false; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
}

test('configured and unconfigured legacy map callback executes using actual dashboard state', async () => {
  const source = await readFile(path.join(web, 'app.js'), 'utf8');
  const marker = 'init().then(async () => {';
  const start = source.lastIndexOf(marker);
  assert.ok(start >= 0);
  // Execute the actual final callback, replacing only module loading with a
  // deterministic loader. The S/s state lookup and guard remain untouched.
  const callback = source.slice(start).replace('import("./arrival-summary.js")', 'importSummary()');
  for (const configured of [false, true]) {
    const container = new Element();
    let mounts = 0;
    const context = vm.createContext({
      S: { boot: configured ? { arrival_intake_url: '/intake/',
        arrival_intake_summary: { mode: 'exercise', confirmed_count: 2 } } : {} },
      document: { getElementById: () => container },
      init: async () => {},
      importSummary: async () => ({ mountConfiguredArrivalIntake: (_target, config) => {
        mounts++;
        assert.equal(config.entry_url, '/intake/');
      } }),
      console: { warn: () => {} },
    });
    await vm.runInContext(callback.replace(marker, 'globalThis.done = init().then(async () => {'), context);
    await context.done;
    assert.equal(mounts, configured ? 1 : 0);
  }
});

test('summary visibly labels exercise provenance and workflow completion without private extras', async () => {
  const source = await readFile(path.join(web, 'arrival-summary.js'), 'utf8');
  const context = vm.createContext({ document: { createElement: tag => new Element(tag) }, Element });
  const module = new vm.SourceTextModule(source, { context });
  await module.link(() => { throw new Error('unexpected import'); });
  await module.evaluate();
  const container = new Element();
  module.namespace.mountArrivalSummary(container, {
    mode: 'exercise', vehicle_id: 'bus-3', expected_count: 30, confirmed_count: 29,
    completed_reviews: 2, awaiting_reviews: 0,
    image_sha256: 'PRIVATE_HASH', human_concerns: 'PRIVATE_CONCERN',
  });
  assert.equal(container.hidden, false);
  assert.match(container.textContent, /exercise|simulated/i);
  assert.match(container.textContent, /2/);
  assert.match(container.textContent, /reviews? completed|completed reviews?|review actions/i);
  assert.doesNotMatch(container.textContent, /PRIVATE_HASH|PRIVATE_CONCERN/);
  const unknown = new Element();
  module.namespace.mountArrivalSummary(unknown, { mode: 'unexpected', confirmed_count: 29 });
  assert.ok(unknown.hidden || /unverified|unknown|unavailable/i.test(unknown.textContent));
  const absent = new Element();
  module.namespace.mountArrivalSummary(absent, { confirmed_count: 29 });
  assert.ok(absent.hidden || /unverified|unknown|unavailable/i.test(absent.textContent));
});
