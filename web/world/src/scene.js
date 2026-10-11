import {assetUrl} from './assets.js';
export function createWorldScene({canvas,creditContainer,assetBase,engine,SceneCtor=engine?.Scene}) {
 if(!SceneCtor||!canvas)throw new Error('Scene constructor and canvas required');
 if(engine)engine.buildModuleUrl.setBaseUrl(assetUrl(assetBase,'cesium/'));
 const scene=new SceneCtor({canvas,creditContainer,requestRenderMode:true,maximumRenderTimeChange:Infinity});
 if(engine){scene.globe=new engine.Globe(engine.Ellipsoid.WGS84);scene.skyAtmosphere=new engine.SkyAtmosphere();}
 let dead=false;
 return {scene,
  resize(width,height,dpr=1){
   if(dead||!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)return;
   const ratio=Math.min(2,Math.max(1,Number.isFinite(dpr)?dpr:1));
   canvas.width=Math.max(1,Math.round(width*ratio));canvas.height=Math.max(1,Math.round(height*ratio));
   scene.camera.frustum.aspectRatio=width/height;scene.requestRender?.();
  },
  render(time){if(dead)return;scene.initializeFrame();scene.render(time??engine?.JulianDate.now());},
  destroy(){if(dead)return;dead=true;scene.destroy();}
 };
}
