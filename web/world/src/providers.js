const dispose=value=>{if(value&&!value.isDestroyed?.())value.destroy?.();};
const aborted=()=>new DOMException('Provider request superseded','AbortError');
export async function installProvider(scene,config={},factories,signal,onState=()=>{}) {
 const publish=value=>{if(signal.aborted)throw aborted();onState(value);return value;};
 publish({mode:'ellipsoid',status:'loading',label:'Loading geographic surface',photographic:false});
 const attempts=[];
 if(typeof config.googleClientKey==='string'&&config.googleClientKey.trim())attempts.push(['Google Photorealistic 3D Tiles',()=>factories.google(config)]);
 if(typeof config.ionClientToken==='string'&&config.ionClientToken.trim()&&Number.isInteger(config.ionAssetId))attempts.push(['Cesium ion photographic asset',()=>factories.ion(config)]);
 for(const [label,create] of attempts){
  try {
   const tile=await create();
   if(signal.aborted){dispose(tile);throw aborted();}
   if(!tile)throw new Error('No photographic tileset');
   scene.primitives.add(tile);scene.globe.show=false;scene.requestRender?.();
   return publish({mode:'photographic',status:'ready',label,photographic:true});
  }catch(error){if(signal.aborted)throw aborted();}
 }
 scene.globe.show=true;
 if(!config.allowFallback)return publish({mode:'ellipsoid',status:'unavailable',label:'Photographic provider unavailable · limited ellipsoid reference',photographic:false});
 let terrain=false,imagery=false;
 try {const value=await factories.terrain();if(signal.aborted){dispose(value);throw aborted();}if(value){scene.terrainProvider=value;terrain=true;}}catch(error){if(signal.aborted)throw aborted();}
 try {const value=await factories.imagery();if(signal.aborted){dispose(value);throw aborted();}if(value){scene.imageryLayers.addImageryProvider(value);imagery=true;}}catch(error){if(signal.aborted)throw aborted();}
 scene.requestRender?.();
 return publish({mode:terrain?'terrain':'ellipsoid',status:terrain||imagery?'ready':'unavailable',photographic:false,
  label:'Limited '+(terrain?'terrain':'ellipsoid')+' view · '+(imagery?'Esri imagery':'imagery unavailable')+' · photographic tiles unavailable'});
}
