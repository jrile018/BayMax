"use strict";
// Curated historical context and strictly typed accepted source points.
window.KnightEarthPlaces=(()=>{
 const curated=[
  {id:"paradise",name:"Paradise, California",kind:"EXERCISE AREA",lon:-121.606,lat:39.754,history:"The 2018 Camp Fire spread through Paradise and nearby Butte County communities. The local map here is a constructed training replay of that geography.",historyStat:"2018 Camp Fire · 153,336 acres · 85 civilian fatalities",historySource:"https://www.nist.gov/programs-projects/wildland-urban-interface-wui-fire-data-collection-parcel-vulnerabilities/nist",current:"No verified current Paradise incident update in the accepted snapshot.",localMap:true},
  {id:"yosemite",name:"Yosemite region, California",kind:"RESEARCH CONTEXT",lon:-119.61617975318511,lat:37.56620512778412,history:"Indigenous cultural burning and natural fire shaped Yosemite for millennia. The Dome Fire point is a separate research candidate, not an accepted incident perimeter or Paradise event.",historyStat:"Historic landscape · not a current fire statistic",historySource:"https://www.nps.gov/yose/learn/nature/firehistory.htm",current:"No accepted Dome Fire record or verified current local update.",localMap:false},
  {id:"san-francisco",name:"San Francisco, California",kind:"HISTORICAL CONTEXT",lon:-122.4194,lat:37.7749,history:"The 1906 northern California earthquake caused severe shaking and fires in San Francisco. Regional weather alerts are not treated as a city point on this globe.",historyStat:"1906 earthquake · magnitude 7.9",historySource:"https://earthquake.usgs.gov/earthquakes/events/1906calif/",current:"No verified city-specific current update in the accepted snapshot.",localMap:false}
 ];
 const finite=n=>typeof n==="number"&&Number.isFinite(n);
 const point=g=>g?.type==="Point"&&Array.isArray(g.coordinates)&&g.coordinates.length===2&&finite(g.coordinates[0])&&finite(g.coordinates[1])&&Math.abs(g.coordinates[0])<=180&&Math.abs(g.coordinates[1])<=90;
 const safeUrl=value=>{try{const u=new URL(value);return u.protocol==="https:"?u.href:null}catch{return null}};
 function fromSituation(response){
  const snapshot=response?.status==="available"&&response.snapshot?.schema_version==="knight26-incident-v1"?response.snapshot:null;
  if(!snapshot)return{cutoff:null,hash:null,summary:"No accepted source snapshot connected",places:[],news:"No verified current news feed connected"};
  const hazards=Array.isArray(snapshot.categories?.hazard)?snapshot.categories.hazard:[];
  const earthquakes=hazards.filter(item=>item?.provider==="US Geological Survey"&&item.source_kind==="observed"&&item.payload?.event_type==="earthquake"&&point(item.geometry)&&typeof item.payload.place==="string"&&item.payload.place.trim()&&finite(item.payload.magnitude)&&safeUrl(item.source_url));
  const places=earthquakes.slice(0,12).map(item=>({
   id:"usgs-"+String(item.item_id),name:item.payload.place.trim(),kind:"ACCEPTED USGS OBSERVATION",lon:item.geometry.coordinates[0],lat:item.geometry.coordinates[1],
   history:"USGS location text identifies the reported event area. This point is an observation, not a city-wide impact or forecast.",
   historyStat:null,historySource:null,
   current:"Magnitude "+item.payload.magnitude.toFixed(1)+" · depth "+(finite(item.payload.depth_km)?item.payload.depth_km.toFixed(1)+" km":"Unknown")+" · observed "+(item.observed_at||"Unknown"),
   currentSource:safeUrl(item.source_url),observedAt:item.observed_at||null,localMap:false
  }));
  const regional=hazards.filter(item=>item?.provider==="National Weather Service"&&!point(item.geometry)).length;
  return{cutoff:snapshot.cutoff_utc||null,hash:snapshot.snapshot_hash||null,summary:regional+" regional weather alerts · "+earthquakes.length+" mapped USGS earthquakes at accepted cutoff",places,news:"No reviewed place-linked news feed connected"};
 }
 return{curated,fromSituation,safeUrl};
})();
