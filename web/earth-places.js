"use strict";
// Curated historical context and strictly typed accepted source points.
window.KnightEarthPlaces=(()=>{
 const curated=[
  {id:"paradise",name:"Paradise, California",kind:"EXERCISE AREA",lon:-121.606,lat:39.754,history:"The 2018 Camp Fire spread through Paradise and nearby Butte County communities. The local map here is a constructed training replay of that geography.",historyStat:"2018 Camp Fire · 153,336 acres · 85 civilian fatalities",historySource:"https://www.nist.gov/programs-projects/wildland-urban-interface-wui-fire-data-collection-parcel-vulnerabilities/nist",current:"No verified current Paradise incident update in the accepted snapshot.",localMap:true},
  {id:"yosemite",name:"Yosemite region, California",kind:"RESEARCH CONTEXT",lon:-119.61617975318511,lat:37.56620512778412,history:"Indigenous cultural burning and natural fire shaped Yosemite for millennia. The Dome Fire point is a separate research candidate, not an accepted incident perimeter or Paradise event.",historyStat:"Historic landscape · not a current fire statistic",historySource:"https://www.nps.gov/yose/learn/nature/firehistory.htm",current:"No accepted Dome Fire record or verified current local update.",localMap:false},
  {id:"san-francisco",name:"San Francisco, California",kind:"HISTORICAL CONTEXT",lon:-122.4194,lat:37.7749,history:"The 1906 northern California earthquake caused severe shaking and fires in San Francisco. Regional weather alerts are not treated as a city point on this globe.",historyStat:"1906 earthquake · magnitude 7.9",historySource:"https://earthquake.usgs.gov/earthquakes/events/1906calif/",current:"No verified city-specific current update in the accepted snapshot.",localMap:false}
 ];
 const finite=n=>typeof n==="number"&&Number.isFinite(n);
 const lonlat=p=>Array.isArray(p)&&p.length===2&&finite(p[0])&&finite(p[1])&&Math.abs(p[0])<=180&&Math.abs(p[1])<=90;
 const point=g=>g?.type==="Point"&&Array.isArray(g.coordinates)&&g.coordinates.length===2&&finite(g.coordinates[0])&&finite(g.coordinates[1])&&Math.abs(g.coordinates[0])<=180&&Math.abs(g.coordinates[1])<=90;
 const safeUrl=value=>{try{const u=new URL(value);return u.protocol==="https:"?u.href:null}catch{return null}};
 const date=value=>typeof value==="string"&&Number.isFinite(Date.parse(value))?value:null;
 const clean=value=>typeof value==="string"?value.trim():"";
 const polygon=g=>g?.type==="Polygon"&&Array.isArray(g.coordinates)?g.coordinates.filter(ring=>Array.isArray(ring)&&ring.length>=4&&ring.every(lonlat)):[];
 function fromSituation(response){
  const snapshot=response?.status==="available"&&response.snapshot?.schema_version==="knight26-incident-v1"?response.snapshot:null;
  if(!snapshot)return{cutoff:null,hash:null,summary:"No accepted source snapshot connected",places:[],regions:[],news:"No reviewed place-linked news feed connected",counts:{quakes:0,alerts:0,news:0}};
  const hazards=Array.isArray(snapshot.categories?.hazard)?snapshot.categories.hazard:[];
  const earthquakes=hazards.filter(item=>item?.provider==="US Geological Survey"&&item.source_kind==="observed"&&item.payload?.event_type==="earthquake"&&point(item.geometry)&&clean(item.payload.place)&&finite(item.payload.magnitude)&&safeUrl(item.source_url));
  const places=earthquakes.slice(0,12).map(item=>({
   id:"usgs-"+String(item.item_id),name:item.payload.place.trim(),kind:"ACCEPTED USGS OBSERVATION",lon:item.geometry.coordinates[0],lat:item.geometry.coordinates[1],
   history:"USGS location text identifies the reported event area. This point is an observation, not a city-wide impact or forecast.",
   historyStat:null,historySource:null,
   current:"Magnitude "+item.payload.magnitude.toFixed(1)+" · depth "+(finite(item.payload.depth_km)?item.payload.depth_km.toFixed(1)+" km":"Unknown")+" · observed "+(item.observed_at||"Unknown"),
   currentSource:safeUrl(item.source_url),observedAt:date(item.observed_at),publishedAt:date(item.published_at),reviewStatus:"Accepted official source",localMap:false
  }));
  const alerts=hazards.filter(item=>item?.provider==="National Weather Service"&&item.source_kind==="official_forecast"&&clean(item.payload?.event)&&safeUrl(item.source_url));
  const regions=alerts.map(item=>({
   id:"nws-"+String(item.item_id),name:item.payload.event,kind:"ACCEPTED NWS REGIONAL ALERT",lon:null,lat:null,
   history:"National Weather Service regional alert. Its area text and source geometry do not establish conditions at a selected city or street.",
   historyStat:null,historySource:null,current:clean(item.payload.area_desc)||"Alert area unavailable",
   currentSource:safeUrl(item.source_url),observedAt:date(item.observed_at),publishedAt:date(item.published_at),
   reviewStatus:"Accepted official source · regional coverage",localMap:false,regional:true,
   rings:polygon(item.geometry)
  }));
  const leads=(Array.isArray(snapshot.unconfirmed_leads)?snapshot.unconfirmed_leads:[]).filter(item=>item?.source_type==="news"&&safeUrl(item.source_url));
  const newsPlaces=leads.map(item=>({
   id:"news-"+String(item.item_id),name:clean(item.payload?.headline)||clean(item.payload?.title)||String(item.item_id),
   kind:"UNCONFIRMED NEWS LEAD",lon:null,lat:null,history:"Original-source headline. This lead has not been promoted into accepted incident evidence.",
   historyStat:null,historySource:null,current:clean(item.payload?.summary)||"Details require source review",
   currentSource:safeUrl(item.source_url),observedAt:date(item.observed_at),publishedAt:date(item.published_at),
   reviewStatus:"UNCONFIRMED · not operational evidence",localMap:false
  }));
  return{cutoff:snapshot.cutoff_utc||null,hash:snapshot.snapshot_hash||null,
   summary:alerts.length+" accepted NWS regional alerts · "+earthquakes.length+" accepted USGS points · "+leads.length+" unconfirmed news leads at cutoff",
   places:[...places,...regions,...newsPlaces],regions,
   news:leads.length+" unconfirmed source-linked news leads · no incident claim until reviewed",
   counts:{quakes:earthquakes.length,alerts:alerts.length,news:leads.length}};
 }
 return{curated,fromSituation,safeUrl};
})();
