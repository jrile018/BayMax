"use strict";
// NASA Blue Marble is a historic Earth composite, not incident imagery.
// Uses a worker-free WebGL sphere so the authenticated cloud file preview can display Earth.
window.KnightEarth=(()=>{
 const THREE_URL="https://unpkg.com/three@0.180.0/build/three.module.js";
 const TEXTURE_URL="./assets/nasa-blue-marble-2009.jpg";
 let initialized=false,visible=false,dragging=false,renderer,scene,camera,globe,frame=0,oldBanner="",setPanel=null,panelState=null;
 const $=id=>document.getElementById(id);
 function size(){if(!renderer)return;const host=$("earth-panel"),w=host.clientWidth,h=host.clientHeight;if(w&&h){renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}}
 async function setup(){
  if(initialized)return;
  $("earth-state").textContent="Loading NASA Earth globe…";
  const T=await import(THREE_URL),host=$("earth-canvas");
  scene=new T.Scene();camera=new T.PerspectiveCamera(32,1,.1,100);camera.position.z=5.7;
  renderer=new T.WebGLRenderer({antialias:true,alpha:true,powerPreference:"low-power"});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));renderer.outputColorSpace=T.SRGBColorSpace;
  host.append(renderer.domElement);size();
  scene.add(new T.AmbientLight(0xffffff,1.15));
  const sunlight=new T.DirectionalLight(0xffffff,2.0);sunlight.position.set(-3,4,7);scene.add(sunlight);
  const rim=new T.DirectionalLight(0x77c7ff,.7);rim.position.set(4,-1,-5);scene.add(rim);
  const texture=await new Promise((resolve,reject)=>new T.TextureLoader().load(window.KNIGHT_EARTH_TEXTURE||TEXTURE_URL,resolve,undefined,reject));
  texture.colorSpace=T.SRGBColorSpace;
  globe=new T.Group();globe.position.x=.95;scene.add(globe);
  globe.add(new T.Mesh(new T.SphereGeometry(1.5,64,48),new T.MeshStandardMaterial({map:texture,roughness:1})));
  const atmosphere=new T.Mesh(new T.SphereGeometry(1.535,64,48),new T.MeshBasicMaterial({color:0x75d9fc,transparent:true,opacity:.095,side:T.BackSide}));globe.add(atmosphere);
  const lon=-121.606,lat=39.754,r=1.535,phi=(lon+180)*Math.PI/180,theta=(90-lat)*Math.PI/180;
  const pin=new T.Group();pin.position.set(-r*Math.cos(phi)*Math.sin(theta),r*Math.cos(theta),r*Math.sin(phi)*Math.sin(theta));
  const core=new T.Mesh(new T.SphereGeometry(.055,12,12),new T.MeshBasicMaterial({color:0xffcb83}));pin.add(core);
  const halo=new T.Mesh(new T.SphereGeometry(.09,12,12),new T.MeshBasicMaterial({color:0xffad5e,transparent:true,opacity:.4}));pin.add(halo);globe.add(pin);
  globe.rotation.y=-.15;initialized=true;
  const canvas=renderer.domElement;canvas.style.touchAction="none";
  let lastX=0,lastY=0;
  canvas.addEventListener("pointerdown",e=>{dragging=true;lastX=e.clientX;lastY=e.clientY;canvas.setPointerCapture(e.pointerId)});
  canvas.addEventListener("pointermove",e=>{if(!dragging)return;globe.rotation.y+=(e.clientX-lastX)*.006;globe.rotation.x=Math.max(-.8,Math.min(.8,globe.rotation.x+(e.clientY-lastY)*.004));lastX=e.clientX;lastY=e.clientY});
  canvas.addEventListener("pointerup",()=>dragging=false);canvas.addEventListener("pointercancel",()=>dragging=false);
  canvas.addEventListener("wheel",e=>{e.preventDefault();camera.position.z=Math.max(3.8,Math.min(9,camera.position.z+(e.deltaY>0?.35:-.35)))},{passive:false});
  if(window.ResizeObserver)new ResizeObserver(size).observe($("earth-panel"));else window.addEventListener("resize",size);
  $("earth-state").textContent="Earth ready · drag to rotate · scroll to zoom";
  function animate(){if(!visible){frame=0;return}frame=requestAnimationFrame(animate);if(!dragging)globe.rotation.y+=.00045;renderer.render(scene,camera)}
  window.KnightEarth.resume=()=>{if(!frame){size();animate()}};
 }
 async function open(){
  if(visible)return;visible=true;oldBanner=$("source-banner").textContent;
  panelState={left:!$("left-panel").classList.contains("collapsed"),right:!$("right-panel").classList.contains("collapsed")};
  if(setPanel){setPanel("left",false);setPanel("right",false)}
  $("earth-panel").hidden=false;document.body.classList.add("earth-mode");
  $("earth-toggle").textContent="MAP";$("earth-toggle").setAttribute("aria-pressed","true");$("earth-toggle").setAttribute("aria-label","Return to Paradise satellite map");
  $("view-chip").textContent="3D EARTH OVERVIEW";$("source-chip").textContent="NASA Blue Marble composite";
  $("source-banner").textContent="NASA EARTH COMPOSITE · PARADISE REPLAY IS CONSTRUCTED TRAINING DATA";
  try{await setup();if(visible)window.KnightEarth.resume()}catch(error){$("earth-state").textContent="Earth view unavailable online: "+error.message;console.error(error)}
 }
 function close(){visible=false;if(frame){cancelAnimationFrame(frame);frame=0}$("earth-panel").hidden=true;document.body.classList.remove("earth-mode");
  $("earth-toggle").textContent="EARTH";$("earth-toggle").setAttribute("aria-pressed","false");$("earth-toggle").setAttribute("aria-label","Open interactive Earth globe");
  $("view-chip").textContent="REAL-WORLD SATELLITE MAP";$("source-chip").textContent=document.body.classList.contains("satellite")?"Esri satellite + OSM vectors":"OSM vector geometry";
  $("source-banner").textContent=oldBanner;
  if(setPanel&&panelState){setPanel("left",innerWidth>760&&panelState.left);setPanel("right",innerWidth>760&&panelState.right)}
 }
 function bind(options={}){setPanel=options.setPanel||null;const b=$("earth-toggle");b.onclick=()=>visible?close():open();$("earth-local-button").onclick=close}
 return{bind,open,close};
})();
