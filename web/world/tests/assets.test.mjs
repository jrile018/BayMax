import test from 'node:test';
import assert from 'node:assert/strict';
const {assetUrl}=await import('../src/assets.js').catch(()=>({}));
test('same-origin assets retain proxy prefix and reject escapes',()=>{
 assert.equal(typeof assetUrl,'function','assetUrl missing');
 const base='https://example.test/instances/id/proxy/8765/world/dist/';
 assert.equal(assetUrl(base,'cesium/Workers/createGeometry.js'),base+'cesium/Workers/createGeometry.js');
 for(const p of ['../secret','https://evil.test/a','/root','a?token=x','%2e%2e/secret'])assert.throws(()=>assetUrl(base,p),/asset/i);
});
