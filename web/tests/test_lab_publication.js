const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

const sourcePath = process.env.KNIGHT_LAB_SCRIPT || path.resolve(__dirname, '../lab-live.js');
const fixturePath = process.env.KNIGHT_NUMERIC_FIXTURE || path.resolve(__dirname, 'fixtures/numeric-publication.json');
const source = fs.readFileSync(sourcePath, 'utf8');
const marker = '  refresh.addEventListener("click", poll);';
assert.equal(source.split(marker).length, 2, 'test seam must be unique');
const script = source.replace(marker,
  '  window.__labVerifier = { canonical, parseLossless, validatePublication }; return;\n' + marker);

function element() {
  return {
    append() {}, replaceChildren() {}, setAttribute() {}, remove() {},
    addEventListener() {}, attachShadow() { return element(); },
  };
}
const window = { location: { pathname: '/instances/test/lab/tree/notebook.ipynb' } };
const document = {
  body: element(), createElement: element, getElementById() { return null; },
};
vm.runInNewContext(script, { window, document, crypto: webcrypto, TextEncoder,
  fetch() { throw Error('test must not fetch'); }, setTimeout, clearTimeout,
  setInterval, clearInterval, console });

const { canonical, parseLossless, validatePublication } = window.__labVerifier;
const numeric = '{"float":2.0,"large":1e+20,"long":123456789.12345679,"negative":-0.0,"small":1e-07,"tiny":1.234e-13}';
assert.equal(canonical(parseLossless(numeric)), numeric);
if (process.env.KNIGHT_PYTHON_NUMBER_CORPUS) {
  const randomPythonNumbers = fs.readFileSync(process.env.KNIGHT_PYTHON_NUMBER_CORPUS, 'utf8').trim();
  assert.equal(canonical(parseLossless(randomPythonNumbers)), randomPythonNumbers);
}
for (const bad of ['{"x":2.00}', '{"x":1e-7}', '{"x":-0}', '{"x":1e+0}',
  '{"x":0.00001}', '{"x":1e309}']) {
  assert.throws(() => parseLossless(bad), /Noncanonical|Non-finite/);
}

(async () => {
  for (const file of [fixturePath, process.env.KNIGHT_CURRENT_PUBLICATION_FIXTURE].filter(Boolean)) {
    const fixture = JSON.parse(fs.readFileSync(file, 'utf8'));
    const publication = JSON.parse(fixture.raw);
    const accepted = await validatePublication(publication, fixture.pointer, fixture.raw);
    assert.equal(accepted.snapshot_hash, publication.snapshot.snapshot_hash);
  }
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const tampered = fixture.raw.replace('"integral_float":2.0', '"integral_float":3.0');
  assert.notEqual(tampered, fixture.raw);
  await assert.rejects(validatePublication(JSON.parse(tampered), fixture.pointer, tampered),
    /Snapshot hash mismatch|Projection hash mismatch|View publication hash mismatch/);
  console.log('Lab publication Python numeric fixture and hashes: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
