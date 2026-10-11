"use strict";
// Separate, static Paradise TRAINING fixture. Nothing here is live telemetry.
window.KnightTrainingBuses=(()=>{
 const fixture=window.KNIGHT_TRAINING_BUS_FIXTURE;
 const finite=n=>typeof n==="number"&&Number.isFinite(n);
 const point=p=>Array.isArray(p)&&p.length===2&&p.every(finite);
 const lerp=(a,b,t)=>a+(b-a)*t;
 function prepare(){
  if(!fixture||fixture.schema_version!=="1.0"||fixture.training_only!==true||fixture.gps_feed!==false||fixture.real_dispatch!==false||fixture.real_eta!==false||fixture.local_hazard_binding!==null||fixture.mock_duration_s!==120||!Array.isArray(fixture.buses)||fixture.buses.length!==3)throw Error("Invalid training fixture header");
  const ids=new Set(),routes=new Set(),trails=new Set();
  return fixture.buses.map((bus,index)=>{
   if(!/^TRAINING-BUS-00[1-3]$/.test(bus.bus_id)||ids.has(bus.bus_id)||routes.has(bus.route_id)||trails.has(bus.trail_id))throw Error("Invalid or duplicate training bus identity");
   ids.add(bus.bus_id);routes.add(bus.route_id);trails.add(bus.trail_id);
   const metric=bus.route?.geometry_m,geo=bus.route?.geometry_lonlat;
   if(!Array.isArray(metric)||metric.length<3||metric.length!==geo?.length||!metric.every(point)||!geo.every(point)||!Array.isArray(bus.route.edge_ids)||bus.route.edge_ids.length<2)throw Error("Invalid training bus route");
   if(!Array.isArray(bus.positions)||bus.positions.length!==13)throw Error("Invalid training bus timeline");
   const cumulative=[0];for(let i=1;i<metric.length;i++){const length=Math.hypot(metric[i][0]-metric[i-1][0],metric[i][1]-metric[i-1][1]);if(length<=0)throw Error("Degenerate training route");cumulative.push(cumulative.at(-1)+length)}
   const length=cumulative.at(-1),epoch=Date.parse(fixture.simulation_epoch_utc);
   if(!Number.isFinite(epoch))throw Error("Invalid training epoch");
   for(const [i,sample] of bus.positions.entries()){
    if(sample.sequence!==i||sample.elapsed_s!==i*10||Date.parse(sample.timestamp_utc)!==epoch+i*10000||!point(sample.position_m)||!point(sample.position_lonlat)||!finite(sample.route_distance_m)||Math.abs(sample.route_distance_m-length*i/12)>1e-5)throw Error("Invalid training position timeline");
   }
   return{bus,index,metric,geo,cumulative,length};
  });
 }
 let prepared,error=null;
 try{prepared=prepare()}catch(cause){error=cause.message;prepared=[]}
 let elapsed=0,paused=true,selectedBusId="TRAINING-BUS-001";
 function resolve(item,time=elapsed){
  const d=Math.max(0,Math.min(120,time))/120*item.length,dist=item.cumulative;
  let segment=dist.length-2;for(let i=0;i<dist.length-1;i++){if(d<dist[i+1]-1e-8){segment=i;break}}
  const fraction=Math.max(0,Math.min(1,(d-dist[segment])/(dist[segment+1]-dist[segment])));
  const pair=(a,b)=>[lerp(a[0],b[0],fraction),lerp(a[1],b[1],fraction)];
  const position=pair(item.geo[segment],item.geo[segment+1]);
  const dx=item.metric[segment+1][0]-item.metric[segment][0],dy=item.metric[segment+1][1]-item.metric[segment][1];
  const heading=(Math.atan2(dx,dy)*180/Math.PI+360)%360;
  return{vehicle_id:item.bus.bus_id,kind:"bus",label:"Training bus "+(item.index+1),phase:time>=120?"TRAINING COMPLETE":paused?"TRAINING PAUSED":"TRAINING MOVING",position_lonlat:position,route_geometry_lonlat:item.geo,completed_trail_lonlat:[...item.geo.slice(0,segment+1),position],trail_id:item.bus.trail_id,route_id:item.bus.route_id,heading_deg:heading,simulated_speed_kmh:paused||time>=120?0:item.length/120*3.6,route_distance_m:d};
 }
 function snapshot(){return{index:Math.floor(elapsed/10),time_s:elapsed,vehicles:prepared.map(item=>resolve(item))}}
 function setElapsed(value){if(finite(value))elapsed=Math.max(0,Math.min(120,value));if(elapsed>=120)paused=true;return snapshot()}
 function advance(seconds){if(!paused&&finite(seconds))setElapsed(elapsed+seconds);return snapshot()}
 function select(id){if(prepared.some(item=>item.bus.bus_id===id))selectedBusId=id;return selectedBusId}
 function toggle(){if(elapsed>=120)elapsed=0;paused=!paused;return paused}
 return{sourceHash:"ccd9c4145e60fbcee7bb1637bef3a528b38273d5dd9365685a135d564fd4b68f",error,get valid(){return !error},get elapsed(){return elapsed},get paused(){return paused},get selectedBusId(){return selectedBusId},get fixture(){return fixture},snapshot,setElapsed,advance,select,toggle,pause(){paused=true},prepare};
})();
