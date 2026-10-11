import test from 'node:test';import assert from 'node:assert/strict';
const {layoutLabels}=await import('../src/labels.js').catch(()=>({}));
test('phone labels cannot cover controls, credits or the viewport edge',()=>{
 assert.equal(typeof layoutLabels,'function','layoutLabels missing');
 const viewport={x:0,y:0,width:360,height:800},reserved=[{x:0,y:700,width:360,height:100}];
 const candidates=Array.from({length:400},(_,i)=>({id:String(i),x:10,y:710,width:80,height:18,priority:0}));
 assert.deepEqual(layoutLabels(candidates,viewport,reserved,60),[]);
 assert.deepEqual(layoutLabels([{id:'outside',x:-5,y:0,width:80,height:18}],viewport,[],60),[]);
});
test('selected label wins collisions and label budget is hard bounded',()=>{
 assert.equal(typeof layoutLabels,'function');const viewport={x:0,y:0,width:1000,height:1000};
 const overlapping=[{id:'low',x:10,y:10,width:40,height:18,priority:0},{id:'selected',x:10,y:10,width:40,height:18,priority:10}];
 assert.deepEqual(layoutLabels(overlapping,viewport,[],60).map(v=>v.id),['selected']);
 const many=Array.from({length:200},(_,i)=>({id:String(i),x:i%20*45,y:Math.floor(i/20)*30,width:40,height:18,priority:0}));
 assert.equal(layoutLabels(many,viewport,[],60).length,60);
});
