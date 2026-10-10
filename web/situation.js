"use strict";
// Renders a server-published accepted snapshot. Browser content cannot create acceptance.
window.KnightSituation=(()=>{
 const NS="http://www.w3.org/2000/svg";
 const categories=["hazard","needs","closures","vehicles","stock","capacity"];
 const names={hazard:"Hazards",needs:"Needs",closures:"Closures",vehicles:"Vehicles",stock:"Stock",capacity:"Capacity"};
 const el=(tag,cls="",value)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=String(value);return n};
 const validPoint=p=>Array.isArray(p)&&p.length===2&&p.every(v=>typeof v==="number"&&Number.isFinite(v))&&p[0]>=-180&&p[0]<=180&&p[1]>=-90&&p[1]<=90;
 const when=v=>v?String(v):"Unknown";
 function text(container,tag,cls,value){const n=el(tag,cls,value);container.append(n);return n}
 function safeLink(value){try{const u=new URL(value);return u.protocol==="https:"?u.href:null}catch{return null}}
 function outsideLoaded(geo,bbox){
  if(!geo||!Array.isArray(bbox)||bbox.length!==4)return false;
  if(geo.type==="Point"&&validPoint(geo.coordinates)){
   const [lon,lat]=geo.coordinates;return lon<bbox[0]||lon>bbox[2]||lat<bbox[1]||lat>bbox[3];
  }
  if(geo.type==="Polygon"&&Array.isArray(geo.coordinates)){
   const points=geo.coordinates.flat().filter(validPoint);if(!points.length)return false;
   const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
   return Math.max(...xs)<bbox[0]||Math.min(...xs)>bbox[2]||Math.max(...ys)<bbox[1]||Math.min(...ys)>bbox[3];
  }
  return false;
 }
 function recordCard(item,kind,bbox){
  const card=el("article","situation-card");
  const payload=item.payload&&typeof item.payload==="object"?item.payload:{};
  const title=item.area_label||payload.title||payload.name||payload.headline||payload.event||item.item_id||kind;
  text(card,"strong","",title);
  text(card,"small","","Provider: "+(item.provider||"Unknown")+" · "+(item.source_kind||"Unknown kind")+" · "+(item.precision||"Unknown precision"));
  text(card,"small","","Published "+when(item.published_at)+" · observed "+when(item.observed_at)+" · accepted "+when(item.accepted_at));
  if(item.valid_from||item.valid_through)text(card,"small","","Valid "+when(item.valid_from)+" to "+when(item.valid_through));
  if(item.message_expires_at)text(card,"small","","Source message expires "+when(item.message_expires_at)+" (not hazard end)");
  if(item.source_uncertainty)text(card,"small","","Uncertainty: "+item.source_uncertainty);
  if(!item.geometry)text(card,"small","","Area-level or unspecified geometry; no point plotted");
  else if(item.geometry.type==="Point"&&validPoint(item.geometry.coordinates))text(card,"small","","Source point: "+item.geometry.coordinates[1].toFixed(5)+", "+item.geometry.coordinates[0].toFixed(5));
  if(outsideLoaded(item.geometry,bbox))text(card,"small","situation-warning","Outside loaded Paradise base map; source location not relocated");
  const href=safeLink(item.source_url);
  if(href){const link=el("a","","Open source ↗");link.href=href;link.target="_blank";link.rel="noopener noreferrer";card.append(link)}
  return card;
 }
 function mapItem(group,item,kind,project){
  const geo=item.geometry;if(!geo||!project)return;
  const title=(item.area_label||item.item_id||kind)+" · accepted "+kind+" · "+(item.provider||"source");
  if(geo.type==="Point"&&validPoint(geo.coordinates)){
   const [x,y]=project(geo.coordinates);if(!Number.isFinite(x)||!Number.isFinite(y))return;
   const mark=document.createElementNS(NS,"circle");mark.setAttribute("cx",x);mark.setAttribute("cy",y);mark.setAttribute("r","7");mark.setAttribute("class","situation-point");mark.setAttribute("data-radius","7");
   const hint=document.createElementNS(NS,"title");hint.textContent=title;mark.append(hint);group.append(mark);
  }else if(geo.type==="Polygon"&&Array.isArray(geo.coordinates)){
   const rings=geo.coordinates.filter(r=>Array.isArray(r)&&r.length>=4&&r.every(validPoint));
   if(!rings.length)return;
   const d=rings.map(r=>r.map((p,i)=>{const[x,y]=project(p);return(i?"L":"M")+x.toFixed(2)+" "+y.toFixed(2)}).join(" ")+" Z").join(" ");
   const mark=document.createElementNS(NS,"path");mark.setAttribute("d",d);mark.setAttribute("class","situation-poly");mark.setAttribute("fill-rule","evenodd");
   const hint=document.createElementNS(NS,"title");hint.textContent=title;mark.append(hint);group.append(mark);
  }
 }
 function render(host,group,response,project,bbox){
  host.replaceChildren();group.replaceChildren();
  if(response?.status!=="available"||!response.snapshot){
   const section=el("div","situation-status");text(section,"strong","","No accepted snapshot connected");
   text(section,"p","",response?.reason||"The trusted incident publisher has not supplied a snapshot.");
   host.append(section);return;
  }
  const snapshot=response.snapshot;
  if(snapshot.schema_version!=="knight26-incident-v1"||!snapshot.categories||typeof snapshot.categories!=="object"){
   const section=el("div","situation-status");text(section,"strong","","Invalid incident snapshot");host.append(section);return;
  }
  const header=el("div","situation-status");
  text(header,"strong","","Incident "+(snapshot.incident_id||"Unknown"));
  text(header,"p","","Accepted evidence cutoff: "+when(snapshot.cutoff_utc));
  text(header,"p","situation-warning","Operational outcomes remain unavailable under incident contract v1.");
  text(header,"p","","Snapshot "+(snapshot.snapshot_hash||"Unknown")+" · source references "+(snapshot.accepted_source_refs?.length??0));
  host.append(header);
  const health=snapshot.source_health;
  const healthSection=el("section","situation-section");text(healthSection,"h3","","Source health");
  if(!health||!Object.keys(health).length)text(healthSection,"p","situation-unknown","Unknown — no source health published");
  else for(const [sourceId,state] of Object.entries(health)){
   const row=el("div","situation-card");
   text(row,"strong","",sourceId+" · "+(state?.status||"unknown"));
   if(state?.source_time)text(row,"small","","Last source time: "+when(state.source_time));
   if(state?.reason)text(row,"small","","Refresh status: "+state.reason);
   healthSection.append(row);
  }
  host.append(healthSection);
  for(const kind of categories){
   const section=el("section","situation-section");text(section,"h3","",names[kind]);
   const items=snapshot.categories[kind];
   if(items==null)text(section,"p","situation-unknown","Unknown — no accepted current evidence");
   else if(!Array.isArray(items))text(section,"p","situation-unknown","Unknown — invalid category data");
   else if(!items.length)text(section,"p","situation-empty","No accepted current records at cutoff");
   else for(const item of items){if(!item||typeof item!=="object")continue;section.append(recordCard(item,kind,bbox));if(!outsideLoaded(item.geometry,bbox))mapItem(group,item,kind,project)}
   host.append(section);
  }
  const leads=snapshot.unconfirmed_leads;
  const section=el("section","situation-section");text(section,"h3","","Unconfirmed leads");
  if(!Array.isArray(leads)||!leads.length)text(section,"p","situation-empty","None listed");
  else for(const lead of leads){const card=recordCard(lead,"Unconfirmed lead",bbox);card.prepend(el("small","situation-warning","Unconfirmed · excluded from operational constraints"));section.append(card)}
  host.append(section);
 }
 return{render};
})();
