import test from 'node:test';import assert from 'node:assert/strict';
const {createGovernor}=await import('../src/governor.js').catch(()=>({}));
test('identity keyed holds release idle without leaks or late mutations',()=>{
 assert.equal(typeof createGovernor,'function','createGovernor missing');let requests=0;
 const scene={requestRenderMode:true,requestRender(){requests++;}},g=createGovernor(scene);
 g.hold('training');g.hold('training');assert.equal(scene.requestRenderMode,false);
 g.release('training');assert.equal(scene.requestRenderMode,true);g.release('training');assert.equal(scene.requestRenderMode,true);
 g.hold('follow');g.hold('training');g.release('follow');assert.equal(scene.requestRenderMode,false);g.release('training');assert.equal(scene.requestRenderMode,true);
 const before=requests;g.destroy();g.hold('late');g.request();assert.equal(requests,before);assert.equal(scene.maximumRenderTimeChange,Infinity);
});
