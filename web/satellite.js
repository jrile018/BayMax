"use strict";
// Esri World Imagery follows the keyless satellite path in the pinned God’s Eye View source.
// Tiles are viewed transiently in the browser; this module does not crawl or cache imagery.
window.KnightSatellite=(()=>{
 const NS="http://www.w3.org/2000/svg", ENDPOINT="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/";
 const lon=x=>x*360-180, lat=y=>Math.atan(Math.sinh(Math.PI*(1-2*y)))*180/Math.PI;
 const tx=(longitude,n)=>Math.floor((longitude+180)/360*n);
 const ty=(latitude,n)=>Math.floor((1-Math.asinh(Math.tan(latitude*Math.PI/180))/Math.PI)/2*n);
 let current="",generation=0,failedForCurrent=0,retryCount=0;
 function render(state,project,unproject){
  const layer=document.getElementById("layer-satellite"),status=document.getElementById("imagery-status");
  if(!layer||!state.projection)return;
  if(state.basemap!=="satellite"){if(current){layer.replaceChildren();current="";generation++}failedForCurrent=0;retryCount=0;status.textContent="Vector geometry view";return}
  const svg=document.getElementById("map"),rect=svg.getBoundingClientRect(),ctm=svg.getScreenCTM(),q=state.projection;
  if(!rect.width||!ctm)return;
  const inverse=ctm.inverse();
  const corners=[[rect.left,rect.top],[rect.right,rect.top],[rect.left,rect.bottom],[rect.right,rect.bottom]].map(([x,y])=>{const p=new DOMPoint(x,y).matrixTransform(inverse);return unproject({x:p.x,y:p.y})});
  const screenLonScale=q.cos*q.scale*Math.hypot(ctm.a,ctm.b);
  let z=Math.max(4,Math.min(18,Math.round(Math.log2(screenLonScale*360/256))));
  const west=Math.max(-180,Math.min(...corners.map(p=>p[0]))),east=Math.min(180,Math.max(...corners.map(p=>p[0])));
  const north=Math.min(85,Math.max(...corners.map(p=>p[1]))),south=Math.max(-85,Math.min(...corners.map(p=>p[1])));
  let x0,x1,y0,y1,n;
  do{n=2**z;x0=Math.max(0,tx(west,n)-1);x1=Math.min(n-1,tx(east,n)+1);y0=Math.max(0,ty(north,n)-1);y1=Math.min(n-1,ty(south,n)+1);if((x1-x0+1)*(y1-y0+1)<=80||z===4)break;z--}while(true);
  const key=[z,x0,x1,y0,y1].join("/");if(key===current){if(!failedForCurrent||retryCount>=1)return;retryCount++}else retryCount=0;current=key;failedForCurrent=0;
  const fragment=document.createDocumentFragment(),token=++generation,total=(x1-x0+1)*(y1-y0+1);let loaded=0,failed=0;const update=()=>{status.textContent=failed?"Imagery degraded · "+failed+" of "+total+" tiles failed":loaded===total?"Esri World Imagery · "+loaded+" tiles loaded":"Loading Esri satellite imagery · "+loaded+"/"+total+" tiles"};
  for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
   const p=project([lon(x/n),lat(y/n)]),r=project([lon((x+1)/n),lat((y+1)/n)]);
   const img=document.createElementNS(NS,"image");
   img.setAttribute("x",p[0]);img.setAttribute("y",p[1]);img.setAttribute("width",r[0]-p[0]);img.setAttribute("height",r[1]-p[1]);
   img.setAttribute("preserveAspectRatio","none");img.setAttribute("href",ENDPOINT+z+"/"+y+"/"+x);
   img.setAttribute("pointer-events","none");img.addEventListener("load",()=>{if(token===generation){loaded++;update()}});
   img.addEventListener("error",()=>{if(token===generation){failed++;failedForCurrent++;update()}});
   fragment.append(img)
  }
  layer.replaceChildren(fragment);update();
 }
 return{render};
})();
