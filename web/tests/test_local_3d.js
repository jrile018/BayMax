"use strict";
// Real renderer/control logic and real Three camera maths; only WebGL and DOM
// are replaced because these cloud CPU regressions do not have a browser context.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../..');
let Three;
const vendor=path.join(root,'web/vendor/three/three.js');
if(fs.existsSync(vendor)){const box={window:{},console,AbortController};vm.runInNewContext(fs.readFileSync(vendor,'utf8'),box);Three=box.window.KnightThree;}
else Three=require(process.env.THREE_CJS);
const area=JSON.parse(fs.readFileSync(path.join(root,'fixtures/geography/paradise/area.json'),'utf8'));
const failures=[];
function element(){return{hidden:false,textContent:'',children:[],dataset:{},style:{setProperty(){}},classList:{add(){},remove(){}},clientWidth:1200,clientHeight:800,append(child){this.children.push(child)},replaceChildren(...children){this.children=children},setAttribute(){},addEventListener(){},setPointerCapture(){}}}
async function app(data=area,width=1200,height=800){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id)};
 get('local3d-canvas').clientWidth=width;get('local3d-canvas').clientHeight=height;
 let rendered;
 class WebGLRenderer{constructor(){this.domElement=element()}setPixelRatio(){}setSize(){}render(scene,camera){rendered={scene,camera};camera.updateMatrixWorld()}}
 const namespace={...Three,WebGLRenderer};
 const window={KnightThree:namespace},box={window,console,document:{getElementById:get,createElement:element,body:element()},ResizeObserver:class{observe(){}},requestAnimationFrame:()=>1,cancelAnimationFrame(){},devicePixelRatio:1};
 const context=vm.createContext(box);
 for(const file of ['training-buses-data.js','training-buses-core.js'])vm.runInContext(fs.readFileSync(path.join(root,'web',file),'utf8'),context);
 const module=new vm.SyntheticModule(Object.keys(namespace),function(){for(const key of Object.keys(namespace))this.setExport(key,namespace[key])},{context});
 await module.link(()=>{});await module.evaluate();
 const source=fs.readFileSync(path.join(root,'web/local-3d.js'),'utf8');
 new vm.Script(source,{importModuleDynamically:()=>module}).runInContext(context);
 window.KnightLocal3D.bind({getBoot:()=>({area:data})});
 return{window,get,async open(lon=-121.608,lat=39.75){await window.KnightLocal3D.open({lon,lat,name:'Regression coordinate'});assert.ok(rendered,'renderer must initialize');return rendered},rendered:()=>rendered};
}
function objects(scene,predicate){const out=[];scene.traverse(x=>{if(predicate(x))out.push(x)});return out}
async function test(name,run){try{await run();console.log('PASS '+name)}catch(error){failures.push(name);console.error('FAIL '+name+': '+error.message)}}
(async()=>{
 await test('display-padding coordinate must be unavailable',async()=>{
  const a=await app(),r=await a.open(-121.625,39.75);
  assert.match(a.get('local3d-coordinate').textContent,/COVERAGE UNAVAILABLE/);
  assert.equal(a.get('local3d-training').hidden,true);
  assert.equal(objects(r.scene,x=>x.userData.vehicleId).length,0);
 });
 await test('missing acquired bounds fail closed',async()=>{
  const data=structuredClone(area);delete data.coverage_bbox_lonlat;
  const a=await app(data);await a.open();assert.match(a.get('local3d-coordinate').textContent,/COVERAGE UNAVAILABLE/);
 });
 await test('unavailable roads suppress road lines and fleet independently',async()=>{
  const data=structuredClone(area);data.coverage.find(x=>x.layer==='roads').status='unavailable';
  const a=await app(data),r=await a.open();
  assert.equal(objects(r.scene,x=>x.type==='Line').length,0);
  assert.equal(objects(r.scene,x=>x.userData.vehicleId).length,0);
  assert.ok(objects(r.scene,x=>x.geometry?.type==='ExtrudeGeometry').length>0,'available buildings remain');
  assert.equal(a.get('local3d-training').hidden,true);
 });
 await test('unavailable buildings suppress extrusions independently',async()=>{
  const data=structuredClone(area);data.coverage.find(x=>x.layer==='buildings').status='unavailable';
  const a=await app(data),r=await a.open();
  assert.equal(objects(r.scene,x=>x.geometry?.type==='ExtrudeGeometry').length,0);
  assert.equal(objects(r.scene,x=>x.userData.vehicleId).length,3);
 });
 await test('all unavailable or unknown layers use honest fallback',async()=>{
  const data=structuredClone(area);for(const layer of data.coverage)layer.status='unknown';
  const a=await app(data),r=await a.open();assert.match(a.get('local3d-coordinate').textContent,/COVERAGE UNAVAILABLE/);
  assert.equal(objects(r.scene,x=>x.userData.vehicleId).length,0);
 });
 for(const [width,height] of [[1200,800],[360,800]])await test(`Whole fleet frames all buses and route points at ${width}x${height}`,async()=>{
  const a=await app(area,width,height),r=await a.open(-121.62,39.763);
  a.get('local3d-fleet-list').children[0].onclick();
  const camera=r.camera;camera.updateMatrixWorld();
  const fleet=r.scene.children.find(g=>g.children.some(child=>child.userData.vehicleId));
  assert.ok(fleet,'fleet group exists');assert.equal(fleet.children.filter(x=>x.userData.vehicleId).length,3);
  const points=[];
  for(const child of fleet.children){if(child.userData.vehicleId)points.push(child.position.clone());else if(child.type==='Line'){const p=child.geometry.attributes.position;for(let i=0;i<p.count;i++)points.push(new Three.Vector3(p.getX(i),p.getY(i),p.getZ(i)))}}
  assert.ok(points.length>6,'real bus routes included');
  for(const p of points){const view=p.clone().applyMatrix4(camera.matrixWorldInverse),screen=p.clone().project(camera);
   assert.ok(view.z<0,`point behind camera: depth ${view.z}`);
   assert.ok(Math.abs(screen.x)<=.96&&Math.abs(screen.y)<=.96&&screen.z>=-1&&screen.z<=1,`point clipped: ${screen.toArray()}`)}
  a.window.KnightTrainingBuses.toggle();a.window.KnightTrainingBuses.advance(60);a.window.KnightLocal3D.update();
  assert.match(a.get('local3d-hud').textContent,/Whole training fleet/,'updates preserve whole-fleet mode');
 });
 await test('whole-fleet selection exits follow and survives pause',async()=>{
  const a=await app();await a.open();a.get('local3d-cockpit').onclick();
  a.get('local3d-fleet-list').children[0].onclick();assert.match(a.get('local3d-camera').textContent,/OVERVIEW/);
  a.window.KnightTrainingBuses.pause();a.window.KnightLocal3D.update();assert.match(a.get('local3d-hud').textContent,/Whole training fleet/);
 });
 if(failures.length){console.error(`${failures.length} renderer regressions failed`);process.exitCode=1}else console.log('8 local renderer regressions passed');
})();
