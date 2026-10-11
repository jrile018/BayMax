import test from 'node:test';import assert from 'node:assert/strict';
const {fitDistance,validPick}=await import('../src/camera.js').catch(()=>({}));
test('portrait uses tighter field of view and real sky picks fail closed',()=>{
 assert.equal(typeof fitDistance,'function','fitDistance missing');assert.equal(typeof validPick,'function');
 assert.ok(fitDistance(1000,Math.PI/3,.45,.2)>fitDistance(1000,Math.PI/3,1.8,.2));
 assert.equal(validPick(undefined),null);assert.equal(validPick({longitude:NaN,latitude:0}),null);
 assert.equal(validPick({longitude:4,latitude:0}),null);
 const p=validPick({longitude:-121.6*Math.PI/180,latitude:39.75*Math.PI/180});
 assert.ok(Math.abs(p[0]+121.6)<1e-8&&Math.abs(p[1]-39.75)<1e-8);
});
