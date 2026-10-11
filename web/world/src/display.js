import {lonlat} from './coverage.js';
const finite=n=>typeof n==='number'&&Number.isFinite(n);
function wgs84(lon,lat,height){const a=6378137,e2=0.0066943799901413165,p=lat*Math.PI/180,l=lon*Math.PI/180,n=a/Math.sqrt(1-e2*Math.sin(p)**2);return {x:(n+height)*Math.cos(p)*Math.cos(l),y:(n+height)*Math.cos(p)*Math.sin(l),z:(n*(1-e2)+height)*Math.sin(p)};}
export function createDisplay(training,initialCoverage,{groundHeight=()=>undefined,toCartesian=wgs84}={}){
 let coverage=initialCoverage;
 return {setCoverage(value){coverage=value;},select(id){training?.select(id);},tick(dtSeconds){
  const dt=finite(dtSeconds)?Math.min(.1,Math.max(0,dtSeconds)):0;
  const eligible=coverage?.training===true&&training?.valid===true;
  if(eligible&&!training.paused)training.advance(dt);
  const snapshot=eligible?training.snapshot():null;
  const timeSeconds=finite(training?.elapsed)?training.elapsed:0;
  const contacts=(snapshot?.vehicles||[]).filter(v=>v.kind==='bus'&&lonlat(v.position_lonlat)).map(v=>{
   const point=[...v.position_lonlat],height=groundHeight(point),heightM=finite(height)?height:null;
   return {id:v.vehicle_id,label:v.label||v.vehicle_id,kind:'bus',simulated:true,lonlat:point,
    headingDeg:finite(v.heading_deg)?v.heading_deg:null,speedKmh:finite(v.simulated_speed_kmh)?v.simulated_speed_kmh:null,
    route:(v.route_geometry_lonlat||[]).filter(lonlat).slice(0,512),trail:(v.completed_trail_lonlat||[]).filter(lonlat).slice(-512),
    sourceHash:training.sourceHash,scenarioSeconds:timeSeconds,heightM,heightSource:heightM===null?'Unknown · ellipsoid reference':'Sampled displayed surface · simulated vehicle',
    position:toCartesian(point[0],point[1],(heightM??0)+1.5)};
  });
  return {timeSeconds,dtSeconds:dt,paused:training?.paused!==false,selectedId:eligible?training.selectedBusId:null,contacts,byId:new Map(contacts.map(c=>[c.id,c]))};
 }};
}
