import test from 'node:test';
import assert from 'node:assert/strict';
const {createWorldScene}=await import('../src/scene.js').catch(()=>({}));
test('one Scene owns an idempotent render lifetime and bounded pixel resize',()=>{
 assert.equal(typeof createWorldScene,'function','createWorldScene missing');
 let renders=0,destroys=0;
 class FakeScene{constructor(){this.camera={frustum:{aspectRatio:1}};}initializeFrame(){}render(){renders++;}destroy(){destroys++;}}
 const canvas={width:1,height:1};
 const world=createWorldScene({canvas,creditContainer:{},assetBase:'https://example.test/world/dist/',SceneCtor:FakeScene});
 world.resize(360,800,4);assert.equal(canvas.width,720);assert.equal(canvas.height,1600);
 assert.equal(world.scene.camera.frustum.aspectRatio,.45);
 world.render();world.destroy();world.destroy();world.render();
 assert.equal(renders,1);assert.equal(destroys,1);
});
