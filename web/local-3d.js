"use strict";
// A bounded 3D training visualization of the existing Paradise OSM footprints.
// Building extrusion heights and the ground plane are illustrative, not survey data.
window.KnightLocal3D=(()=>{
 const $=id=>document.getElementById(id);
 const colors=[0x4fd3df,0xf3b86d,0xcf9bf4,0x91d989,0xff8b8b,0x8fb6f5];
 let Three,renderer,scene,camera,frame=0,open=false,setupPromise=null,context=null,place=null,area=null,origin=null,span=5000;
 let fleetGroup=null,selected=undefined,cockpit=false,angle=.18,elevation=.62,distance=9000,target=null,drag=null,lastFrame=null,speeds=new Map(),lastTick=0,lastPaint=0,speedMultiplier=1;
 let controls=null,vehicleMeshes=[],coverage=null;
 const finite=n=>typeof n==="number"&&Number.isFinite(n);
 const point=p=>Array.isArray(p)&&p.length===2&&finite(p[0])&&finite(p[1]);
 const route=g=>Array.isArray(g)&&g.every(point)?g:[];
 const samePoint=(a,b)=>a[0]===b[0]&&a[1]===b[1];
 const usableRoad=item=>{const points=route(item?.geometry_lonlat).slice(0,512);return points.length>=2&&points.some(p=>!samePoint(p,points[0]))};
 const usableBuilding=item=>{const ring=route(item?.geometry_lonlat);if(ring.length<4||ring.length>256||!samePoint(ring[0],ring[ring.length-1]))return false;
  const vertices=ring.slice(0,-1);if(new Set(vertices.map(p=>p[0]+","+p[1])).size<3)return false;
  const anchor=vertices[0];let twiceArea=0;for(let i=0;i<vertices.length;i++){const a=vertices[i],b=vertices[(i+1)%vertices.length];twiceArea+=(a[0]-anchor[0])*(b[1]-anchor[1])-(b[0]-anchor[0])*(a[1]-anchor[1])}
  return Number.isFinite(twiceArea)&&twiceArea!==0};
 const usableFeatures=name=>(Array.isArray(area?.[name])?area[name]:[]).filter(name==="roads"?usableRoad:usableBuilding);
 const formatTime=seconds=>finite(seconds)?String(Math.floor(seconds/3600)).padStart(2,"0")+":"+String(Math.floor(seconds%3600/60)).padStart(2,"0")+":"+String(Math.floor(seconds%60)).padStart(2,"0"):"Unknown";
 const bounds=b=>Array.isArray(b)&&b.length===4&&b.every(finite)&&b[0]<b[2]&&b[1]<b[3];
 const within=(p,b)=>point(p)&&bounds(b)&&p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3];
 function localCoverage(){
  const acquired=within([place.lon,place.lat],area?.coverage_bbox_lonlat);
  const layers=Array.isArray(area?.coverage)?area.coverage:[];
  const layerAvailable=name=>layers.some(layer=>layer?.layer===name&&layer.status==="available");
  const roadFeatures=acquired&&layerAvailable("roads")?usableFeatures("roads"):[];
  const buildingFeatures=acquired&&layerAvailable("buildings")?usableFeatures("buildings"):[];
  const roads=roadFeatures.length>0,buildings=buildingFeatures.length>0;
  return{roads,buildings,roadFeatures,buildingFeatures,available:roads||buildings,training:roads&&training()?.valid===true};
 }
 const colorFor=index=>colors[index%colors.length];
 const colorHex=index=>"#"+colorFor(index).toString(16).padStart(6,"0");
 const training=()=>window.KnightTrainingBuses;
 const currentFrame=()=>training()?.valid?training().snapshot():null;
 function xyz(lonlat,y=0){return new Three.Vector3((lonlat[0]-origin[0])*111320*Math.cos(origin[1]*Math.PI/180),y,-(lonlat[1]-origin[1])*111320)}
 function dispose(object){object.traverse(item=>{item.geometry?.dispose();if(Array.isArray(item.material))item.material.forEach(m=>m.dispose());else item.material?.dispose()})}
 function clearScene(){if(!scene)return;for(const child of [...scene.children]){scene.remove(child);dispose(child)}vehicleMeshes=[];fleetGroup=null}
 function line(points,color,opacity=1,height=2){const coords=route(points);if(coords.length<2)return null;
  return new Three.Line(new Three.BufferGeometry().setFromPoints(coords.slice(0,512).map(p=>xyz(p,height))),new Three.LineBasicMaterial({color,transparent:opacity<1,opacity}));}
 function addGround(){
  scene.background=new Three.Color(0x071827);
  const ground=new Three.Mesh(new Three.PlaneGeometry(span*2.5,span*2.5),new Three.MeshStandardMaterial({color:0x153344,roughness:1}));
  ground.rotation.x=-Math.PI/2;ground.position.y=-4;scene.add(ground);
  const grid=new Three.GridHelper(span*2.4,24,0x467183,0x2b5263);grid.position.y=-2;scene.add(grid);
  scene.add(new Three.HemisphereLight(0xc9f1ff,0x173344,2.1));
  const sun=new Three.DirectionalLight(0xffd7a4,2.2);sun.position.set(span*.4,span,span*.25);scene.add(sun);
 }
 function buildParadise(){
  const roads=new Three.Group(),buildings=new Three.Group();scene.add(roads,buildings);
  for(const item of coverage.roadFeatures.slice(0,500)){
   const geometry=route(item.geometry_lonlat);const road=line(geometry,/primary|secondary|tertiary/.test(item.highway||"")?0x9bb9b9:0x5d8892,1,1);
   if(road)roads.add(road);
  }
  for(const [index,item] of coverage.buildingFeatures.slice(0,250).entries()){
   const ring=item.geometry_lonlat;
   const shape=new Three.Shape();for(const [i,p] of ring.entries()){const local=xyz(p);if(i===0)shape.moveTo(local.x,-local.z);else shape.lineTo(local.x,-local.z)}
   const height=12+(index*37)%46,geometry=new Three.ExtrudeGeometry(shape,{depth:height,bevelEnabled:false});geometry.rotateX(-Math.PI/2);
   const mesh=new Three.Mesh(geometry,new Three.MeshStandardMaterial({color:index%4===0?0x457589:0x315b6e,roughness:.86,metalness:.08}));
   buildings.add(mesh);
  }
  $("local3d-coverage").textContent="Paradise OSM "+[coverage.roads?"road lines":null,coverage.buildings?"building footprints":null].filter(Boolean).join(" and ")+
   (coverage.buildings?" · illustrative extrusion heights":"")+" · flat ground, no surveyed terrain"+
   (coverage.roads?"":" · roads unavailable; no vehicle coverage")+(coverage.buildings?"":" · buildings unavailable");
 }
 function buildFallback(){
  const pin=new Three.Mesh(new Three.ConeGeometry(span*.022,span*.1,6),new Three.MeshStandardMaterial({color:0xf0ba72,emissive:0x71411b}));
  pin.position.y=span*.055;scene.add(pin);
  $("local3d-coverage").textContent="No verified local OSM geometry or terrain tiles for this coordinate. Flat reference grid only; no vehicle coverage.";
 }
 function rebuild(){if(!Three||!place)return;clearScene();
  coverage=localCoverage();const paradise=coverage.available,bbox=bounds(area?.bbox_lonlat)?area.bbox_lonlat:area?.coverage_bbox_lonlat;
  origin=paradise?[(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2]:[place.lon,place.lat];
  span=paradise?Math.max((bbox[2]-bbox[0])*111320*Math.cos(origin[1]*Math.PI/180),(bbox[3]-bbox[1])*111320):5000;
  target=paradise?xyz([place.lon,place.lat]):new Three.Vector3();distance=paradise&&training()?.valid?Math.max(300,Math.min(span*.72,500)):span*.72;angle=.18;elevation=.62;selected=coverage.training?training()?.selectedBusId:undefined;cockpit=false;lastFrame=null;speeds.clear();
  addGround();if(paradise)buildParadise();else buildFallback();
  fleetGroup=new Three.Group();scene.add(fleetGroup);
  $("local3d-training").hidden=!coverage.training;
  $("local3d-title").textContent=place.name||"Selected coordinate";
  $("local3d-coordinate").textContent=Number(place.lat).toFixed(4)+"°, "+Number(place.lon).toFixed(4)+"° · "+(paradise?(coverage.training?"PARADISE TRAINING AREA":"LOCAL OSM COVERAGE"):"COVERAGE UNAVAILABLE");
  if(coverage.roads&&!training()?.valid)$("local3d-coverage").textContent+=" · training fixture rejected: "+(training()?.error||"Missing data")+"; no bus markers shown";
  update(currentFrame());cameraPose();
 }
 function selectedVehicle(vehicles){return vehicles.find(v=>v.vehicle_id===selected)||null}
 function speedFor(vehicle,time){const previous=lastFrame?.vehicles?.find(v=>v.vehicle_id===vehicle.vehicle_id);
  if(!previous||!point(previous.position_lonlat)||!point(vehicle.position_lonlat)||!finite(time)||!finite(lastFrame.time_s)||time<=lastFrame.time_s)return speeds.get(vehicle.vehicle_id)||null;
  const a=previous.position_lonlat,b=vehicle.position_lonlat,lat=(a[1]+b[1])*Math.PI/360;
  const metres=Math.hypot((b[0]-a[0])*111320*Math.cos(lat),(b[1]-a[1])*111320);
  const kmh=metres/(time-lastFrame.time_s)*3.6;
  if(Number.isFinite(kmh)){speeds.set(vehicle.vehicle_id,kmh);return kmh}
  return null;
 }
 function headingFor(vehicle){const path=route(vehicle.remaining_path_lonlat).length>1?route(vehicle.remaining_path_lonlat):route(vehicle.route_geometry_lonlat);
  if(finite(vehicle.heading_deg)){const radians=vehicle.heading_deg*Math.PI/180;return new Three.Vector3(Math.sin(radians),0,-Math.cos(radians))}
  const p=vehicle.position_lonlat;if(!point(p)||path.length<2)return new Three.Vector3(0,0,-1);
  let nearest=0,best=Infinity;for(let i=0;i<path.length-1;i++){const d=Math.hypot(path[i][0]-p[0],path[i][1]-p[1]);if(d<best){best=d;nearest=i}}
  const from=xyz(path[nearest]),to=xyz(path[nearest+1]),direction=to.sub(from);direction.y=0;return direction.lengthSq()>0?direction.normalize():new Three.Vector3(0,0,-1);
 }
 function renderFleet(frameData){if(!fleetGroup||!context)return;frameData=currentFrame();
  for(const child of [...fleetGroup.children]){fleetGroup.remove(child);dispose(child)}vehicleMeshes=[];
  const vehicles=Array.isArray(frameData?.vehicles)?frameData.vehicles:[];
  const candidates=coverage?.training?vehicles.filter(v=>point(v.position_lonlat)):[];
  if(selected&&!candidates.some(v=>v.vehicle_id===selected)){selected=undefined;cockpit=false}
  if(selected===undefined&&candidates.length)selected=candidates.find(v=>v.kind==="bus")?.vehicle_id||candidates[0].vehicle_id;
  const list=$("local3d-fleet-list"),ids=["__all__",...candidates.map(v=>v.vehicle_id)];
  if(list.children.length!==ids.length||ids.some((id,index)=>list.children[index]?.dataset.vehicleId!==id)){
   const buttons=ids.map(id=>{const button=document.createElement("button");button.type="button";button.dataset.vehicleId=id;
    button.onclick=()=>{selected=id==="__all__"?null:id;if(selected)training()?.select(selected);else{cockpit=false;frameFleet()}renderFleet(currentFrame());cameraPose()};return button});
   list.replaceChildren(...buttons);
  }
  const all=list.children[0];all.textContent="Whole fleet · "+candidates.length;all.setAttribute("aria-pressed",String(!selected));
  for(const [index,v] of candidates.entries()){
   const color=colorFor(index),colorText=colorHex(index),position=xyz(v.position_lonlat,16);
   const marker=new Three.Mesh(new Three.CylinderGeometry(Math.min(15,span*.009),Math.min(18,span*.011),Math.min(40,span*.025),8),new Three.MeshStandardMaterial({color,emissive:color,emissiveIntensity:.25}));
   marker.position.copy(position);marker.userData.vehicleId=v.vehicle_id;marker.visible=!cockpit;fleetGroup.add(marker);vehicleMeshes.push(marker);
   const track=line(v.route_geometry_lonlat,color,.34,5);if(track)fleetGroup.add(track);
   const trail=line(v.completed_trail_lonlat,color,.95,8);if(trail)fleetGroup.add(trail);
   const button=list.children[index+1];button.style.setProperty("--vehicle-color",colorText);button.setAttribute("aria-pressed",String(v.vehicle_id===selected));
   button.textContent=(v.label||v.vehicle_id)+" · "+(v.phase||"Unknown")+" · "+formatTime(frameData.time_s);
  }
  const current=selectedVehicle(candidates),speed=current?(finite(current.simulated_speed_kmh)?current.simulated_speed_kmh:speedFor(current,frameData?.time_s)):null;
  $("local3d-frame").textContent="TRAINING FRAME "+(Number(frameData?.index)+1||1)+" · "+formatTime(frameData?.time_s);
  $("local3d-hud").textContent=current?
   (current.label||current.vehicle_id)+" · "+(current.phase||"Unknown")+" · simulated speed "+(speed===null?"Unknown":speed.toFixed(1)+" km/h along training route")+
   " · simulated heading "+(finite(current.heading_deg)?current.heading_deg.toFixed(0)+"°":"Unknown")+" · route "+(current.route_id||"Unknown")+
   " · source: separate graph-bound training fixture "+(training()?.sourceHash?.slice(0,12)||"Unknown"):
   "Whole training fleet · select a unit for details and follow camera";
  $("local3d-cockpit").disabled=!current||current.kind!=="bus";
  $("local3d-cockpit").textContent=cockpit?"EXIT COCKPIT":"ENTER COCKPIT / FOLLOW";
  const buses=candidates.filter(v=>v.kind==="bus");$("local3d-prev").disabled=$("local3d-next").disabled=buses.length<2;
  $("local3d-play").textContent=training()?.paused?"PLAY":"PAUSE";
  $("local3d-step-back").disabled=!frameData||frameData.index<=0;
  $("local3d-step-forward").disabled=!frameData||frameData.time_s>=120;
  if(cockpit&&!current){cockpit=false;cameraPose()}
  lastFrame=frameData||null;
 }
 function frameFleet(){
  if(!camera||!origin||!coverage?.training)return;
  const points=(currentFrame()?.vehicles||[]).flatMap(v=>[...route(v.route_geometry_lonlat),...(point(v.position_lonlat)?[v.position_lonlat]:[])]).map(p=>xyz(p));
  if(!points.length)return;
  let minX=Infinity,maxX=-Infinity,minZ=Infinity,maxZ=-Infinity;
  for(const p of points){minX=Math.min(minX,p.x);maxX=Math.max(maxX,p.x);minZ=Math.min(minZ,p.z);maxZ=Math.max(maxZ,p.z)}
  target=new Three.Vector3((minX+maxX)/2,20,(minZ+maxZ)/2);
  const vertical=camera.fov*Math.PI/360,horizontal=Math.atan(Math.tan(vertical)*camera.aspect);
  // A padded bounding sphere fits at any orbit angle; portrait uses tighter FOV.
  const radius=Math.max(40,Math.hypot((maxX-minX)/2,(maxZ-minZ)/2,40));
  distance=Math.max(200,radius/Math.sin(Math.min(vertical,horizontal))*1.15);
 }
 function cameraPose(){if(!camera||!target)return;
  const vehicle=selectedVehicle(currentFrame()?.vehicles||[]);
  if(cockpit&&vehicle&&point(vehicle.position_lonlat)){
   const p=xyz(vehicle.position_lonlat),heading=headingFor(vehicle);
   camera.position.copy(p).addScaledVector(heading,-Math.max(18,span*.005));camera.position.y=14;
   camera.lookAt(p.clone().addScaledVector(heading,Math.max(60,span*.02)).add(new Three.Vector3(0,7,0)));
   $("local3d-camera").textContent="LOW FOLLOW CAMERA · SIMULATED BUS";
  }else{
   const focus=vehicle&&point(vehicle.position_lonlat)?xyz(vehicle.position_lonlat):target;
   const horizontal=Math.cos(elevation)*distance;
   camera.position.set(focus.x+Math.sin(angle)*horizontal,focus.y+Math.sin(elevation)*distance,focus.z+Math.cos(angle)*horizontal);
   camera.lookAt(focus);$("local3d-camera").textContent="TILTED 3D OVERVIEW · FLAT GROUND";
  }
 }
 function resize(){if(!renderer)return;const canvas=$("local3d-canvas"),w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();if(open&&selected===null){frameFleet();cameraPose()}}
 function animate(now=0){if(!open){frame=0;return}frame=requestAnimationFrame(animate);if(lastTick&&!training()?.paused){training()?.advance(Math.min(.1,(now-lastTick)/1000)*10*speedMultiplier);if(now-lastPaint>50){renderFleet(currentFrame());lastPaint=now}}lastTick=now;cameraPose();renderer.render(scene,camera)}
 async function setup(){if(renderer)return;if(setupPromise)return setupPromise;setupPromise=(async()=>{
  Three=window.KnightThree;if(!Three)throw new Error("Bundled 3D dependency unavailable");scene=new Three.Scene();camera=new Three.PerspectiveCamera(52,1,.5,100000);
  renderer=new Three.WebGLRenderer({antialias:true,powerPreference:"low-power"});renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.5));
  renderer.outputColorSpace=Three.SRGBColorSpace;$("local3d-canvas").append(renderer.domElement);
  new ResizeObserver(resize).observe($("local3d-canvas"));resize();
  const canvas=renderer.domElement;canvas.style.touchAction="none";let moved=false;
  canvas.addEventListener("pointerdown",e=>{drag={x:e.clientX,y:e.clientY};moved=false;canvas.setPointerCapture(e.pointerId)});
  canvas.addEventListener("pointermove",e=>{if(!drag||cockpit)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>2)moved=true;angle+=dx*.006;elevation=Math.max(.16,Math.min(1.35,elevation+dy*.004));drag={x:e.clientX,y:e.clientY}});
  canvas.addEventListener("pointerup",e=>{drag=null;if(moved||cockpit)return;const rect=canvas.getBoundingClientRect(),ray=new Three.Raycaster();ray.setFromCamera(new Three.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1),camera);
   const hit=ray.intersectObjects(vehicleMeshes)[0];if(hit?.object?.userData?.vehicleId){selected=hit.object.userData.vehicleId;training()?.select(selected);renderFleet(currentFrame());cameraPose()}});
  canvas.addEventListener("wheel",e=>{e.preventDefault();distance=Math.max(span*.18,Math.min(span*4,distance*(e.deltaY>0?1.12:.88)))},{passive:false});
 })();try{await setupPromise}catch(error){setupPromise=null;throw error}}
 async function show(nextPlace){if(!nextPlace||!finite(nextPlace.lon)||!finite(nextPlace.lat))return;
  window.KnightEarth?.close();place=nextPlace;area=context?.getBoot?.()?.area||null;open=true;$("local3d-panel").hidden=false;document.body.classList.add("local3d-mode");
  $("local3d-coverage").textContent="Loading local geometry…";
  try{await setup();if(!open)return;rebuild();resize();lastTick=0;if(!frame)animate()}catch(error){$("local3d-coverage").textContent="3D renderer unavailable: "+error.message+" · use the 2D map"}
 }
 function hide(toEarth=false){open=false;cockpit=false;training()?.pause();if(frame){cancelAnimationFrame(frame);frame=0}$("local3d-panel").hidden=true;document.body.classList.remove("local3d-mode");if(toEarth)window.KnightEarth?.open()}
 function switchBus(delta){const buses=(currentFrame()?.vehicles||[]).filter(v=>v.kind==="bus");if(buses.length<2)return;const index=Math.max(0,buses.findIndex(v=>v.vehicle_id===selected));selected=buses[(index+delta+buses.length)%buses.length].vehicle_id;training()?.select(selected);renderFleet(currentFrame());cameraPose()}
 function update(){if(!open||!renderer||!place)return;renderFleet(currentFrame());cameraPose()}
 function bind(options){controls=options;context=options;
  $("local3d-earth").onclick=()=>hide(true);$("local3d-2d").onclick=()=>hide(false);
  $("local3d-cockpit").onclick=()=>{cockpit=!cockpit;renderFleet(currentFrame());cameraPose()};
  $("local3d-prev").onclick=()=>switchBus(-1);$("local3d-next").onclick=()=>switchBus(1);
  $("local3d-play").onclick=()=>{training()?.toggle();lastTick=0;renderFleet(currentFrame())};
  $("local3d-step-back").onclick=()=>{training()?.pause();training()?.setElapsed(Math.floor((training()?.elapsed||0)/10-1)*10);renderFleet(currentFrame())};
  $("local3d-step-forward").onclick=()=>{training()?.pause();training()?.setElapsed(Math.floor((training()?.elapsed||0)/10+1)*10);renderFleet(currentFrame())};
  $("local3d-speed").onchange=e=>{speedMultiplier=Number(e.target.value)||1};
 }
 return{bind,open:show,close:hide,update};
})();
