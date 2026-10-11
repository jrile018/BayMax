import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
const {createDisplay}=await import('../src/display.js').catch(()=>({}));
function model(){const box={window:{}};vm.createContext(box);for(const name of ['training-buses-data.js','training-buses-core.js'])vm.runInContext(fs.readFileSync(new URL('../../'+name,import.meta.url),'utf8'),box);return box.window.KnightTrainingBuses;}
test('paused contact switching preserves time and one cached anchor',()=>{
 assert.equal(typeof createDisplay,'function','createDisplay missing');const training=model();assert.equal(training.valid,true);training.pause();training.setElapsed(40);
 let samples=0;const display=createDisplay(training,{training:true},{groundHeight:()=>{samples++;return 100;}});
 const first=display.tick(0);display.select('TRAINING-BUS-002');const next=display.tick(0);
 assert.equal(next.timeSeconds,first.timeSeconds);assert.equal(next.paused,true);assert.equal(next.selectedId,'TRAINING-BUS-002');
 assert.equal(samples,6);for(const c of next.contacts){assert.equal(next.byId.get(c.id),c);assert.equal(c.heightM,100);assert.ok(Number.isFinite(c.position.x));}
 display.setCoverage({training:false});assert.equal(display.tick(1).contacts.length,0);assert.equal(training.elapsed,40);
});
test('one tick advances once and clamps visibility recovery',()=>{
 assert.equal(typeof createDisplay,'function');const training=model();training.toggle();const display=createDisplay(training,{training:true});
 const frame=display.tick(60);assert.equal(training.elapsed,.1);assert.equal(frame.dtSeconds,.1);
 for(const c of frame.contacts){assert.equal(c.heightM,null);assert.match(c.heightSource,/Unknown|ellipsoid/);assert.equal(c.simulated,true);}
});
