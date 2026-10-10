"use strict";
// Esri World Imagery follows the keyless satellite path in the pinned God’s Eye View source.
// Tiles are viewed transiently in the browser; this module does not crawl or cache imagery.
window.KnightSatellite=(()=>{
 const NS="http://www.w3.org/2000/svg", ENDPOINT="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/";
 const lon=x=>x*360-180, lat=y=>Math.atan(Math.sinh(Math.PI*(1-2*y)))*180/Math.PI;
 const tx=(longitude,n)=>Math.floor((longitude+180)/360*n);
 const ty=(latitude,n)=>Math.floor((1-Math.asinh(Math.tan(latitude*Math.PI/180))/Math.PI)/2*n);
 let current="",generation=0;
 function render(state,project,unproject){
  const layer=document.getElementById("layer-satellite"),status=document.getElementById("imagery-status");
  if(!layer||!state.projection)return;
  if(state.basemap!=="satellite"){if(current){layer.replaceChildren();current=""}status.textContent="Vector geometry view";return}
  const v=state.view,rect=document.getElementById("map").getBoundingClientRect(),q=state.projection;
  if(!rect.width)return;
  const screenLonScale=q.cos*q.scale*rect.width/v.w;
  let z=Math.max(9,Math.min(18,Math.round(Math.log2(screenLonScale*360/256))));
  const a=unproject({x:v.x,y:v.y}),b=unproject({x:v.x+v.w,y:v.y+v.h});
  const west=Math.max(-180,Math.min(a[0],b[0])),east=Math.min(180,Math.max(a[0],b[0]));
  const north=Math.min(85,Math.max(a[1],b[1])),south=Math.max(-85,Math.min(a[1],b[1]));
  let x0,x1,y0,y1,n;
  do{n=2**z;x0=Math.max(0,tx(west,n)-1);x1=Math.min(n-1,tx(east,n)+1);y0=Math.max(0,ty(north,n)-1);y1=Math.min(n-1,ty(south,n)+1);if((x1-x0+1)*(y1-y0+1)<=80)break;z--}while(z>=9);
  const key=[z,x0,x1,y0,y1].join("/");if(key===current)return;current=key;
  const fragment=document.createDocumentFragment(),token=++generation;let loaded=0,failed=0;
  for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
   const p=project([lon(x/n),lat(y/n)]),r=project([lon((x+1)/n),lat((y+1)/n)]);
   const img=document.createElementNS(NS,"image");
   img.setAttribute("x",p[0]);img.setAttribute("y",p[1]);img.setAttribute("width",r[0]-p[0]);img.setAttribute("height",r[1]-p[1]);
   img.setAttribute("preserveAspectRatio","none");img.setAttribute("href",ENDPOINT+z+"/"+y+"/"+x);
   img.setAttribute("pointer-events","none");img.addEventListener("load",()=>{if(token===generation){loaded++;status.textContent="Esri World Imagery · "+loaded+" tiles loaded"}});
   img.addEventListener("error",()=>{if(token===generation){failed++;status.textContent="Imagery unavailable · "+failed+" tiles failed"}});
   fragment.append(img)
  }
  layer.replaceChildren(fragment);status.textContent="Loading Esri satellite imagery…";
 }
 return{render};
})();
