"use strict";
// NASA Blue Marble is a historic Earth composite, not incident imagery.
// Uses a worker-free WebGL sphere so the authenticated cloud file preview can display Earth.
window.KnightEarth=(()=>{
 const THREE_URL="https://unpkg.com/three@0.180.0/build/three.module.js";
 const TEXTURE_URL="./assets/nasa-blue-marble-2009.jpg";
 const API_ROOT=new URL(".",document.currentScript?.src||document.baseURI);
 let initialized=false,setupPromise=null,visible=false,dragging=false,renderer,scene,camera,globe,Three,frame=0,oldBanner="",setPanel=null,restoreMapLabels=null,openLocal=null,panelState=null;
 let places=[],selected=null,picked=null,markers=[],regionMeshes=[],activeFilter="all",sourceTimer=null,sourceEpoch=0,sourcePending=null,situation=null;
 const $=id=>document.getElementById(id);
 const data=()=>window.KnightEarthPlaces;
 const safeUrl=value=>data()?.safeUrl(value)||null;
 const svgNS="http://www.w3.org/2000/svg",fleetColors=["#4fd3df","#f3b86d","#cf9bf4"];
 function renderTrainingFleet(){
  const model=window.KnightTrainingBuses,host=$("earth-fleet-map");if(!host)return;
  host.replaceChildren();
  if(!model?.valid){$("earth-fleet-title").textContent="Training fixture unavailable";$("earth-fleet-clock").textContent=model?.error||"Missing fixture";return}
  const routes=model.fixture.buses.map(bus=>bus.route.geometry_lonlat),vehicles=model.snapshot().vehicles;
  const coords=routes.flat(),lons=coords.map(p=>p[0]),lats=coords.map(p=>p[1]);
  const minLon=Math.min(...lons),maxLon=Math.max(...lons),minLat=Math.min(...lats),maxLat=Math.max(...lats);
  const dx=Math.max(1e-7,maxLon-minLon),dy=Math.max(1e-7,maxLat-minLat);
  const plot=p=>[24+(p[0]-minLon)/dx*272,130-(p[1]-minLat)/dy*110];
  const line=points=>points.map((p,i)=>{const [x,y]=plot(p);return(i?"L":"M")+x.toFixed(1)+" "+y.toFixed(1)}).join(" ");
  for(const [index,vehicle] of vehicles.entries()){
   for(const [points,opacity,width] of [[routes[index],"0.42","2"],[vehicle.completed_trail_lonlat,"1","3.5"]]){
    const path=document.createElementNS(svgNS,"path");path.setAttribute("d",line(points));path.setAttribute("stroke",fleetColors[index]);path.setAttribute("opacity",opacity);path.setAttribute("stroke-width",width);host.append(path);
   }
   const [x,y]=plot(vehicle.position_lonlat),dot=document.createElementNS(svgNS,"circle");dot.setAttribute("cx",x);dot.setAttribute("cy",y);dot.setAttribute("r","6");dot.setAttribute("fill",fleetColors[index]);host.append(dot);
   const label=document.createElementNS(svgNS,"text");label.setAttribute("x",x+8);label.setAttribute("y",y-8);label.textContent=String(index+1);host.append(label);
  }
  $("earth-fleet-title").textContent="3 simulated buses · "+(model.paused?"PAUSED":"PLAYING");
  $("earth-fleet-clock").textContent="Training "+String(Math.floor(model.elapsed/60)).padStart(2,"0")+":"+String(Math.floor(model.elapsed%60)).padStart(2,"0")+" / 02:00";
 }
 function sourceLabel(){
  const health=situation?.snapshot?.source_health;
  const stale=health&&typeof health==="object"&&Object.values(health).some(item=>item?.status==="stale"||item?.status==="failure");
  const cutoff=situation?.snapshot?.cutoff_utc,age=Date.now()-Date.parse(cutoff);
  const ageLabel=Number.isFinite(age)&&age>=0?" · view age "+(age<3600000?Math.floor(age/60000)+" min":Math.floor(age/3600000)+" h"):"";
  if(document.querySelector(".saved-preview-banner"))return situation?.status==="available"?
   "Saved accepted snapshot as-of "+(cutoff||"Unknown")+ageLabel+(stale?" · source health STALE":"")+" · not live":
   "Saved replay preview · no live accepted feed";
  if(!situation||situation.status!=="available")return"No accepted current source snapshot connected";
  const freshness=Number.isFinite(age)&&age>=0?(age<3600000?Math.floor(age/60000)+" min":"STALE · "+Math.floor(age/3600000)+" h"):"cutoff unknown";
  return"Accepted source cutoff "+(cutoff||"Unknown")+" · "+freshness+(stale?" · source health STALE":"");
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
  $("earth-detail-news").textContent=place.kind==="UNCONFIRMED NEWS LEAD"?
   "UNCONFIRMED · original headline only; no operational claim":data()?.fromSituation(situation).news||"No reviewed place-linked news feed connected";
  $("earth-detail-evidence").textContent=place.reviewStatus?
   place.reviewStatus+" · published "+(place.publishedAt||"Unknown")+" · observed "+(place.observedAt||"Unknown")+
   " · accepted cutoff "+(situation?.snapshot?.cutoff_utc||"Unknown")+" · snapshot "+(situation?.snapshot?.snapshot_hash||"Unknown")+
   " · operational needs, closures, vehicles, stock and capacity remain Unknown unless separately accepted":
   "Curated historical context or selected coordinate · no current local incident claim";
  $("earth-detail-map").textContent=place.id==="paradise"?"Open Paradise training 3D map ↗":"Open local 3D coverage view ↗";
  hover(null);
  if(recenter&&globe&&Three&&Number.isFinite(place.lon)&&Number.isFinite(place.lat)){const p=localPoint(place,1.54);globe.rotation.y=Math.atan2(-p.x,p.z);globe.rotation.x=Math.max(-1.25,Math.min(1.25,place.lat*Math.PI/180));positionMarkers()}
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
  const shown=places.filter(place=>activeFilter==="all"||
   (activeFilter==="quake"&&place.kind==="ACCEPTED USGS OBSERVATION")||
   (activeFilter==="alert"&&place.kind==="ACCEPTED NWS REGIONAL ALERT")||
   (activeFilter==="news"&&place.kind==="UNCONFIRMED NEWS LEAD")||
   (activeFilter==="history"&&!place.reviewStatus));
  if(!shown.length){const empty=document.createElement("p");empty.textContent="No records in this category at the accepted cutoff.";list.append(empty)}
  for(const place of shown){
   const row=document.createElement("button");row.type="button";row.dataset.placeId=place.id;row.className="earth-row "+(place.kind==="ACCEPTED NWS REGIONAL ALERT"?"regional":place.kind==="UNCONFIRMED NEWS LEAD"?"unconfirmed":place.kind==="ACCEPTED USGS OBSERVATION"?"quake":"context");
   const label=document.createElement("span");label.textContent=place.name;
   const kind=document.createElement("small");kind.textContent=place.kind;label.append(kind);
   const arrow=document.createElement("b");arrow.textContent="↗";row.append(label,arrow);
   row.setAttribute("aria-pressed",String(selected?.id===place.id));row.onclick=()=>detail(place);
   row.onpointerenter=()=>hover(place,row);row.onpointerleave=()=>hover(null);
   row.onfocus=()=>hover(place,row);row.onblur=()=>hover(null);
   list.append(row);
   if(!Number.isFinite(place.lon)||!Number.isFinite(place.lat))continue;
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
  const counts=parsed?.counts||{quakes:0,alerts:0,news:0};
  $("earth-counts").textContent=counts.quakes+" observed quakes · "+counts.alerts+" regional alerts · "+counts.news+" unconfirmed news";
  if(oldStatus===response?.status&&oldHash===response?.snapshot?.snapshot_hash)return;
  places=[...(data()?.curated||[]),...(parsed?.places||[]),...(picked?[picked]:[])];
  renderPlaces();
  renderRegions(parsed?.regions||[]);
 }
 function renderRegions(regions){
  if(!globe||!Three)return;
  for(const line of regionMeshes){globe.remove(line);line.geometry.dispose();line.material.dispose()}
  regionMeshes=[];
  for(const region of regions.slice(0,40))for(const ring of region.rings||[]){
   const points=ring.slice(0,257).map(([lon,lat])=>localPoint({lon,lat},1.547));
   if(points.length<4)continue;
   const line=new Three.Line(new Three.BufferGeometry().setFromPoints(points),new Three.LineBasicMaterial({color:0xf7b15d,transparent:true,opacity:.85}));
   globe.add(line);regionMeshes.push(line);
  }
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
  globe.rotation.y=-.15;initialized=true;renderRegions(data()?.fromSituation(situation).regions||[]);
  const canvas=renderer.domElement;canvas.style.touchAction="none";canvas.tabIndex=0;canvas.setAttribute("role","img");canvas.setAttribute("aria-label","Interactive Earth globe. Arrow keys rotate; plus and minus zoom.");canvas.addEventListener("keydown",e=>{if(handleKey(e))e.stopPropagation()});
  let lastX=0,lastY=0,downX=0,downY=0;
  canvas.addEventListener("pointerdown",e=>{dragging=true;lastX=downX=e.clientX;lastY=downY=e.clientY;canvas.setPointerCapture(e.pointerId)});
  canvas.addEventListener("pointermove",e=>{if(!dragging)return;globe.rotation.y+=(e.clientX-lastX)*.006;globe.rotation.x=Math.max(-.8,Math.min(.8,globe.rotation.x+(e.clientY-lastY)*.004));lastX=e.clientX;lastY=e.clientY});
  canvas.addEventListener("pointerup",e=>{dragging=false;if(Math.abs(e.clientX-downX)+Math.abs(e.clientY-downY)>8)return;
   const rect=canvas.getBoundingClientRect(),cursor=new Three.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);
   const ray=new Three.Raycaster();ray.setFromCamera(cursor,camera);const hit=ray.intersectObject(globe.children[0])[0];if(!hit)return;
   const local=globe.worldToLocal(hit.point.clone()).normalize(),lat=Math.asin(local.y)*180/Math.PI;
   let lon=Math.atan2(local.z,-local.x)*180/Math.PI-180;if(lon<-180)lon+=360;
   picked={id:"picked-coordinate",name:Math.abs(lat).toFixed(2)+"°"+(lat>=0?"N":"S")+" · "+Math.abs(lon).toFixed(2)+"°"+(lon>=0?"E":"W"),kind:"SELECTED COORDINATES",lon,lat,
    history:"Selected globe coordinate. No local source evidence or 3D terrain coverage is implied.",current:"No accepted incident record is tied to this exact point.",localMap:false};
   places=places.filter(place=>place.id!==picked.id).concat(picked);renderPlaces();detail(picked,false);
  });canvas.addEventListener("pointercancel",()=>dragging=false);
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
  setSituation({status:"unavailable"});renderTrainingFleet();beginSituation();
  try{await setup();if(visible)window.KnightEarth.resume()}catch(error){$("earth-state").textContent="Earth view unavailable online: "+error.message;console.error(error)}
 }
 function close(){visible=false;endSituation();hover(null);detail(null);if(frame){cancelAnimationFrame(frame);frame=0}$("earth-panel").hidden=true;document.body.classList.remove("earth-mode");
  $("earth-toggle").textContent="EARTH";$("earth-toggle").setAttribute("aria-pressed","false");$("earth-toggle").setAttribute("aria-label","Open interactive Earth globe");
  $("view-chip").textContent=document.body.classList.contains("satellite")?"REAL-WORLD SATELLITE MAP":"OSM VECTOR MAP";$("source-chip").textContent=document.body.classList.contains("satellite")?"Esri satellite + OSM vectors":"OSM vector geometry";
  $("source-banner").textContent=oldBanner;
  restoreMapLabels?.();
  if(setPanel&&panelState){setPanel("left",innerWidth>760&&panelState.left);setPanel("right",innerWidth>760&&panelState.right)}
 }
 function bind(options={}){setPanel=options.setPanel||null;restoreMapLabels=options.restoreMapLabels||null;openLocal=options.openLocal||null;const b=$("earth-toggle");b.onclick=()=>visible?close():open();$("earth-local-button").onclick=()=>openLocal?openLocal(data().curated[0]):close();$("earth-fleet-open").onclick=()=>openLocal?openLocal(data().curated[0]):close();$("earth-detail-close").onclick=()=>detail(null);$("earth-detail-map").onclick=()=>openLocal?openLocal(selected):close();for(const button of document.querySelectorAll("#earth-filters button"))button.onclick=()=>{activeFilter=button.dataset.filter;for(const item of document.querySelectorAll("#earth-filters button"))item.setAttribute("aria-pressed",String(item===button));renderPlaces()};document.addEventListener("keydown",e=>{if(visible&&e.key==="Escape"&&!$("earth-detail").hidden){detail(null);e.stopImmediatePropagation()}},true)}
 return{bind,open,close,handleKey};
})();
