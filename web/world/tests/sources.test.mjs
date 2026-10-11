import test from 'node:test';import assert from 'node:assert/strict';
const {createLatestSource}=await import('../src/sources.js').catch(()=>({}));
const value=(hash,cutoff='2026-10-10T23:00:00Z')=>({status:'available',snapshot:{schema_version:'knight26-incident-v1',snapshot_hash:hash,cutoff_utc:cutoff,categories:{hazard:[]}}});
test('late requests and disposal cannot overwrite accepted state',async()=>{
 assert.equal(typeof createLatestSource,'function','createLatestSource missing');const pending=[],delivered=[];
 const source=createLatestSource(()=>new Promise(resolve=>pending.push(resolve)),v=>delivered.push(v));
 const old=source.refresh(),fresh=source.refresh();pending[1](value('new'));await fresh;pending[0](value('old'));await old;
 assert.deepEqual(delivered.map(v=>v.snapshot.snapshot_hash),['new']);
 const late=source.refresh();source.destroy();pending[2](value('disposed'));await late;assert.equal(delivered.length,1);
});
test('cutoff regression and provider errors preserve last accepted evidence with stale label',async()=>{
 assert.equal(typeof createLatestSource,'function');let reply=value('new'),events=[];
 const source=createLatestSource(async()=>{if(reply instanceof Error)throw reply;return reply;},v=>events.push(v));
 await source.refresh();reply=value('old','2026-10-09T23:00:00Z');await source.refresh();
 assert.equal(events.at(-1).status,'stale');assert.equal(events.at(-1).snapshot.snapshot_hash,'new');
 reply=new Error('offline');await source.refresh();assert.equal(events.at(-1).status,'stale');
 reply={status:'available',snapshot:{schema_version:'wrong'}};await source.refresh();assert.equal(events.at(-1).status,'stale');
 source.destroy();
});
test('unconnected source remains Unknown rather than empty operational facts',async()=>{
 assert.equal(typeof createLatestSource,'function');const events=[];
 const source=createLatestSource(async()=>({status:'unavailable',reason:'No accepted publication'}),v=>events.push(v));
 await source.refresh();assert.equal(events.at(-1).status,'unavailable');assert.equal(events.at(-1).snapshot,undefined);source.destroy();
});
