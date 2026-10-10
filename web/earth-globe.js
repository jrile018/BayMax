"use strict";
// NASA Blue Marble is a historic Earth composite, not incident imagery.
// Uses a worker-free WebGL sphere so the authenticated cloud file preview can display Earth.
window.KnightEarth=(()=>{
 const THREE_URL="https://unpkg.com/three@0.180.0/build/three.module.js";
 const TEXTURE_URL="./assets/nasa-blue-marble-2009.jpg";
 const API_ROOT=new URL(".",document.currentScript?.src||document.baseURI);
 let initialized=false,setupPromise=null,visible=false,dragging=false,renderer,scene,camera,globe,Three,frame=0,oldBanner="",setPanel=null,restoreMapLabels=null,panelState=null;
 let places=[],selected=null,markers=[],sourceTimer=null,sourceEpoch=0,sourcePending=null,situation=null;
 const $=id=>document.getElementById(id);
 const data=()=>window.KnightEarthPlaces;
 const safeUrl=value=>data()?.safeUrl(value)||null;
 function sourceLabel(){
  if(document.querySelector(".saved-preview-banner"))return situation?.status==="available"?
   "Saved accepted snapshot as-of "+(situation.snapshot?.cutoff_utc||"Unknown")+" · not live":
   "Saved replay preview · no live accepted feed";
  if(!situation||situation.status!=="available")return"No accepted current source snapshot connected";
  const cutoff=situation.snapshot?.cutoff_utc,age=Date.now()-Date.parse(cutoff);
  const freshness=Number.isFinite(age)&&age>=0?(age<3600000?Math.floor(age/60000)+" min":"STALE · "+Math.floor(age/3600000)+" h"):"cutoff unknown";
  return"Accepted source cutoff "+(cutoff||"Unknown")+" · "+freshness;
 }
 function setLink(id,url){const a=$(id),safe=safeUrl(url);a.hidden=!safe;if(safe)a.href=safe;else a.removeAttribute("href")}
 function detail(place,recenter=true){
  selected=place||null;$("earth-detail").hidden=!place;
  for(const button of document.querySelectorAll(".earth-place-list button,.earth-pin"))button.setAttribute("aria-pressed",String(!!place&&button.dataset.placeId===place.id));
  if(!place)return;
  $("earth-detail-kind").textContent=place.kind;
  $("earth-detail-title").textContent=place.name;
  $("earth-detail-context-heading").textContent=place.kind==="ACCEPTED USGS OBSERVATION"?"Observation context":"Historical context";
  $("earth-detail-history").textContent=place.history;
  $("earth-detail-stat").textContent=place.historyStat||"";
  $("earth-detail-stat").hidden=!place.historyStat;
  setLink("earth-detail-history-link",place.historySource);
  $("earth-detail-current").textContent=place.current;
  setLink("earth-detail-current-link",place.currentSource);
  $("earth-detail-news").textContent=data()?.fromSituation(situation).news||"No reviewed place-linked news feed connected";
  $("earth-detail-evidence").textContent=place.kind==="ACCEPTED USGS OBSERVATION"?
   "Accepted snapshot "+(situation?.snapshot?.snapshot_hash||"Unknown")+" · cutoff "+(situation?.snapshot?.cutoff_utc||"Unknown"):
   "Curated historical context · not a current local incident claim";
  $("earth-detail-map").hidden=!place.localMap;
  hover(null);
  if(recenter&&globe&&Three){const p=localPoint(place,1.54);globe.rotation.y=Math.atan2(-p.x,p.z);globe.rotation.x=Math.max(-1.25,Math.min(1.25,place.lat*Math.PI/180));positionMarkers()}
 }
 function hover(place,button){
  const box=$("earth-hover");if(!place||selected?.id===place.id){box.hidden=true;return}
  $("earth-hover-title").textContent=place.name;
  $("earth-hover-summary").textContent=place.current||place.history;
  const host=$("earth-panel").getBoundingClientRect(),rect=button.getBoundingClientRect();
  box.style.left=Math.max(12,Math.min(host.width-280,rect.left-host.left+24))+"px";
  box.style.top=Math.max(65,Math.min(host.height-120,rect.top-host.top-12))+"px";
  box.hidden=false;
 }
 function localPoint(place,r){const phi=(place.lon+180)*Math.PI/180,theta=(90-place.lat)*Math.PI/180;return new Three.Vector3(-r*Math.cos(phi)*Math.sin(theta),r*Math.cos(theta),r*Math.sin(phi)*Math.sin(theta))}
 function positionMarkers(){
  if(!Three||!globe||!camera||!renderer)return;
  globe.updateMatrixWorld(true);camera.updateMatrixWorld(true);
  const bounds=$("earth-panel").getBoundingClientRect(),center=globe.getWorldPosition(new Three.Vector3());
  for(const {place,button} of markers){
   const world=globe.localToWorld(localPoint(place,1.555));
   const facing=world.clone().sub(center).normalize().dot(camera.position.clone().sub(world).normalize());
   const ndc=world.clone().project(camera),show=facing>.04&&ndc.z<1&&ndc.z>-1&&visible;
   button.hidden=!show;if(!show)continue;
   button.style.left=((ndc.x+1)*bounds.width/2)+"px";
   button.style.top=((1-ndc.y)*bounds.height/2)+"px";
  }
 }
 function renderPlaces(){
  const list=$("earth-place-list"),pins=$("earth-pin-layer");
  const focused=document.activeElement,focusId=focused?.dataset?.placeId;
  const focusLayer=focused?.classList?.contains("earth-pin")?pins:list;
  list.replaceChildren();pins.replaceChildren();markers=[];
  const current=selected&&places.find(place=>place.id===selected.id);
  if(!current)detail(null);else selected=current;
  for(const place of places){
   const row=document.createElement("button");row.type="button";row.dataset.placeId=place.id;
   const label=document.createElement("span");label.textContent=place.name;
   const kind=document.createElement("small");kind.textContent=place.kind;label.append(kind);
   const arrow=document.createElement("b");arrow.textContent="↗";row.append(label,arrow);
   row.setAttribute("aria-pressed",String(selected?.id===place.id));row.onclick=()=>detail(place);
   row.onpointerenter=()=>hover(place,row);row.onpointerleave=()=>hover(null);
   row.onfocus=()=>hover(place,row);row.onblur=()=>hover(null);
   list.append(row);
   const pin=document.createElement("button");pin.type="button";pin.className="earth-pin"+(place.kind==="ACCEPTED USGS OBSERVATION"?" accepted":"");
   pin.dataset.placeId=place.id;pin.setAttribute("aria-label","Explore "+place.name);pin.title=place.name;
   pin.setAttribute("aria-pressed",String(selected?.id===place.id));pin.onclick=()=>detail(place);
   pin.onpointerenter=()=>hover(place,pin);pin.onpointerleave=()=>hover(null);
   pin.onfocus=()=>hover(place,pin);pin.onblur=()=>hover(null);
   pins.append(pin);markers.push({place,button:pin});
  }
  if(current)detail(current,false);
  if(focusId)Array.from(focusLayer.querySelectorAll("button")).find(button=>button.dataset.placeId===focusId)?.focus({preventScroll:true});
  positionMarkers();
 }
 function setSituation(response){
  const oldStatus=situation?.status,oldHash=situation?.snapshot?.snapshot_hash;
  situation=response;const parsed=data()?.fromSituation(response);
  $("earth-source-state").textContent=sourceLabel();
  $("earth-provenance").textContent=parsed?.summary||"Accepted source unavailable · history only";
  if(oldStatus===response?.status&&oldHash===response?.snapshot?.snapshot_hash)return;
  places=[...(data()?.curated||[]),...(parsed?.places||[])];
  renderPlaces();
 }
 async function pollSituation(epoch){
  if(!visible||epoch!==sourceEpoch||sourcePending)return;
  const controller=new AbortController();sourcePending=controller;
  const deadline=setTimeout(()=>controller.abort(),10000);
  try{const r=await fetch(new URL("api/situation",API_ROOT),{cache:"no-store",signal:controller.signal,headers:{Accept:"application/json"}});
   if(!r.ok)throw Error("Situation HTTP "+r.status);
   const response=await r.json();if(visible&&epoch===sourceEpoch)setSituation(response);
  }catch(error){if(visible&&epoch===sourceEpoch){setSituation({status:"unavailable"});$("earth-source-state").textContent="Accepted feed unavailable · historical places only"}}
  finally{clearTimeout(deadline);if(sourcePending===controller)sourcePending=null}
 }
 function beginSituation(){const epoch=++sourceEpoch;pollSituation(epoch);clearInterval(sourceTimer);sourceTimer=document.querySelector(".saved-preview-banner")?null:setInterval(()=>pollSituation(epoch),30000)}
 function endSituation(){sourceEpoch++;clearInterval(sourceTimer);sourceTimer=null;sourcePending?.abort();sourcePending=null}
 function size(){if(!renderer)return;const host=$("earth-panel"),w=host.clientWidth,h=host.clientHeight;if(w&&h){renderer.setSize(w,h,false);const aspect=w/h;camera.aspect=aspect;camera.position.z=aspect<.9?Math.max(5.7,1.65/(Math.tan(16*Math.PI/180)*aspect)):5.7;if(globe)globe.position.x=aspect<.9?0:.95;camera.updateProjectionMatrix();positionMarkers()}}
 async function setup(){if(initialized)return;if(setupPromise)return setupPromise;setupPromise=build();try{await setupPromise}catch(error){setupPromise=null;if(renderer){renderer.dispose();renderer.domElement.remove();renderer=null}throw error}}
 async function build(){
  $("earth-state").textContent="Loading NASA Earth globe…";
  const T=await import(THREE_URL),host=$("earth-canvas");Three=T;
  scene=new T.Scene();camera=new T.PerspectiveCamera(32,1,.1,100);camera.position.z=5.7;
  renderer=new T.WebGLRenderer({antialias:true,alpha:true,powerPreference:"low-power"});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));renderer.outputColorSpace=T.SRGBColorSpace;
  host.append(renderer.domElement);size();
  scene.add(new T.AmbientLight(0xffffff,1.15));
  const sunlight=new T.DirectionalLight(0xffffff,2.0);sunlight.position.set(-3,4,7);scene.add(sunlight);
  const rim=new T.DirectionalLight(0x77c7ff,.7);rim.position.set(4,-1,-5);scene.add(rim);
  const texture=await new Promise((resolve,reject)=>new T.TextureLoader().load(window.KNIGHT_EARTH_TEXTURE||TEXTURE_URL,resolve,undefined,reject));
  texture.colorSpace=T.SRGBColorSpace;
  globe=new T.Group();scene.add(globe);size();
  globe.add(new T.Mesh(new T.SphereGeometry(1.5,64,48),new T.MeshStandardMaterial({map:texture,roughness:1})));
  const atmosphere=new T.Mesh(new T.SphereGeometry(1.535,64,48),new T.MeshBasicMaterial({color:0x75d9fc,transparent:true,opacity:.095,side:T.BackSide}));globe.add(atmosphere);
  globe.rotation.y=-.15;initialized=true;
  const canvas=renderer.domElement;canvas.style.touchAction="none";canvas.tabIndex=0;canvas.setAttribute("role","img");canvas.setAttribute("aria-label","Interactive Earth globe. Arrow keys rotate; plus and minus zoom.");canvas.addEventListener("keydown",e=>{if(handleKey(e))e.stopPropagation()});
  let lastX=0,lastY=0;
  canvas.addEventListener("pointerdown",e=>{dragging=true;lastX=e.clientX;lastY=e.clientY;canvas.setPointerCapture(e.pointerId)});
  canvas.addEventListener("pointermove",e=>{if(!dragging)return;globe.rotation.y+=(e.clientX-lastX)*.006;globe.rotation.x=Math.max(-.8,Math.min(.8,globe.rotation.x+(e.clientY-lastY)*.004));lastX=e.clientX;lastY=e.clientY});
  canvas.addEventListener("pointerup",()=>dragging=false);canvas.addEventListener("pointercancel",()=>dragging=false);
  canvas.addEventListener("wheel",e=>{e.preventDefault();camera.position.z=Math.max(3.8,Math.min(12,camera.position.z+(e.deltaY>0?.35:-.35)))},{passive:false});
  if(window.ResizeObserver)new ResizeObserver(size).observe($("earth-panel"));else window.addEventListener("resize",size);
  $("earth-state").textContent="Earth ready · drag to rotate · scroll to zoom";
  function animate(){if(!visible){frame=0;return}frame=requestAnimationFrame(animate);if(!dragging&&!selected)globe.rotation.y+=.00045;positionMarkers();renderer.render(scene,camera)}
  window.KnightEarth.resume=()=>{if(!frame){size();animate()}};
 }
 function handleKey(e){if(!visible||!globe||!camera)return false;const k=e.key;if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","+","=","-"].includes(k))return false;e.preventDefault();if(k==="ArrowLeft")globe.rotation.y-=.13;else if(k==="ArrowRight")globe.rotation.y+=.13;else if(k==="ArrowUp")globe.rotation.x=Math.max(-.8,globe.rotation.x-.1);else if(k==="ArrowDown")globe.rotation.x=Math.min(.8,globe.rotation.x+.1);else camera.position.z=Math.max(3.8,Math.min(12,camera.position.z+(k==="-"?.35:-.35)));return true}
 async function open(){
  if(visible)return;visible=true;oldBanner=$("source-banner").textContent;
  panelState={left:!$("left-panel").classList.contains("collapsed"),right:!$("right-panel").classList.contains("collapsed")};
  if(setPanel){setPanel("left",false);setPanel("right",false)}
  $("earth-panel").hidden=false;document.body.classList.add("earth-mode");
  $("earth-toggle").textContent="MAP";$("earth-toggle").setAttribute("aria-pressed","true");$("earth-toggle").setAttribute("aria-label","Return to Paradise satellite map");
  $("view-chip").textContent="3D EARTH OVERVIEW";$("source-chip").textContent="NASA Blue Marble composite";
  $("source-banner").textContent="NASA EARTH COMPOSITE · PARADISE REPLAY IS CONSTRUCTED TRAINING DATA";
  setSituation({status:"unavailable"});beginSituation();
  try{await setup();if(visible)window.KnightEarth.resume()}catch(error){$("earth-state").textContent="Earth view unavailable online: "+error.message;console.error(error)}
 }
 function close(){visible=false;endSituation();hover(null);detail(null);if(frame){cancelAnimationFrame(frame);frame=0}$("earth-panel").hidden=true;document.body.classList.remove("earth-mode");
  $("earth-toggle").textContent="EARTH";$("earth-toggle").setAttribute("aria-pressed","false");$("earth-toggle").setAttribute("aria-label","Open interactive Earth globe");
  $("view-chip").textContent=document.body.classList.contains("satellite")?"REAL-WORLD SATELLITE MAP":"OSM VECTOR MAP";$("source-chip").textContent=document.body.classList.contains("satellite")?"Esri satellite + OSM vectors":"OSM vector geometry";
  $("source-banner").textContent=oldBanner;
  restoreMapLabels?.();
  if(setPanel&&panelState){setPanel("left",innerWidth>760&&panelState.left);setPanel("right",innerWidth>760&&panelState.right)}
 }
 function bind(options={}){setPanel=options.setPanel||null;restoreMapLabels=options.restoreMapLabels||null;const b=$("earth-toggle");b.onclick=()=>visible?close():open();$("earth-local-button").onclick=close;$("earth-detail-close").onclick=()=>detail(null);$("earth-detail-map").onclick=close;document.addEventListener("keydown",e=>{if(visible&&e.key==="Escape"&&!$("earth-detail").hidden){detail(null);e.stopImmediatePropagation()}},true)}
 return{bind,open,close,handleKey};
})();
