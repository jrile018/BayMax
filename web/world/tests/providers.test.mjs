import test from 'node:test';
import assert from 'node:assert/strict';
const {installProvider}=await import('../src/providers.js').catch(()=>({}));
function scene(){return {globe:{show:true},primitives:{added:[],add(x){this.added.push(x);return x;}},imageryLayers:{addImageryProvider:x=>x}};}
function fallback(){return {google:async()=>{throw Error('must not call')},ion:async()=>{throw Error('must not call')},terrain:async()=>{throw Error('offline')},imagery:async()=>null};}
test('no photographic config and offline terrain remain explicitly limited',async()=>{
 assert.equal(typeof installProvider,'function','installProvider missing');
 const states=[],s=scene();const value=await installProvider(s,{allowFallback:true},fallback(),new AbortController().signal,v=>states.push(v));
 assert.equal(value.mode,'ellipsoid');assert.equal(value.photographic,false);assert.match(value.label,/limited/i);assert.equal(s.globe.show,true);
});
test('successful tiles own visible ground and advertise their provider',async()=>{
 assert.equal(typeof installProvider,'function');const s=scene(),tile={};
 const value=await installProvider(s,{googleClientKey:'test-client-key',allowFallback:true},{...fallback(),google:async()=>tile},new AbortController().signal,()=>{});
 assert.equal(value.photographic,true);assert.equal(s.globe.show,false);assert.equal(s.primitives.added[0],tile);
});
test('failed tiles restore geographic fallback without claiming coverage',async()=>{
 assert.equal(typeof installProvider,'function');const s=scene();
 const value=await installProvider(s,{googleClientKey:'test',allowFallback:true},{...fallback(),google:async()=>{throw Error('provider failed')}},new AbortController().signal,()=>{});
 assert.equal(value.photographic,false);assert.equal(s.globe.show,true);
});
test('cancelled late tiles are destroyed and never installed',async()=>{
 assert.equal(typeof installProvider,'function');const s=scene(),c=new AbortController();let resolve,destroyed=0;
 const result=installProvider(s,{googleClientKey:'test',allowFallback:true},{...fallback(),google:()=>new Promise(r=>resolve=r)},c.signal,()=>{});
 c.abort();resolve({destroy(){destroyed++;}});await assert.rejects(result,{name:'AbortError'});
 assert.equal(destroyed,1);assert.equal(s.primitives.added.length,0);
});
