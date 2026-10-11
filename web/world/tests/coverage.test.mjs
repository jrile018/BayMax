import test from 'node:test';import assert from 'node:assert/strict';
const {coverageAt}=await import('../src/coverage.js').catch(()=>({}));
const area=()=>({coverage_bbox_lonlat:[-122,39,-121,40],bbox_lonlat:[-123,38,-120,41],coverage:[{layer:'roads',status:'available'},{layer:'buildings',status:'available'}],roads:[null,{}, {geometry_lonlat:[[1,2],[1,2]]}],buildings:[{}]});
test('padding, invalid roads and unavailable layers cannot enable training',()=>{
 assert.equal(typeof coverageAt,'function','coverageAt missing');const a=area();
 assert.equal(coverageAt(a,[-121.5,39.5],true).training,false);
 a.roads=[{geometry_lonlat:[[-121.7,39.4],[-121.6,39.5]]}];
 assert.equal(coverageAt(a,[-122.5,39.5],true).training,false);
 assert.equal(coverageAt(a,[-121.5,39.5],false).training,false);
 assert.equal(coverageAt(a,[-121.5,39.5],true).training,true);
 a.coverage[0].status='unavailable';assert.equal(coverageAt(a,[-121.5,39.5],true).training,false);
});
test('mixed geometry preserves only meaningful closed building rings',()=>{
 assert.equal(typeof coverageAt,'function');const a=area();
 const good={geometry_lonlat:[[-121.7,39.4],[-121.6,39.4],[-121.6,39.5],[-121.7,39.4]]};
 a.buildings=[null,{}, {geometry_lonlat:[[0,0],[1,1],[2,2],[0,0]]},good];
 const result=coverageAt(a,[-121.5,39.5],true);
 assert.equal(result.buildings,true);assert.deepEqual(result.buildingFeatures,[good]);assert.equal(result.training,false);
 assert.equal(coverageAt(a,[190,39.5],true).acquired,false);
});
