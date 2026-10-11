// Adapted from God's Eye View src/renderGovernor.js; MIT notice retained.
export function createGovernor(scene){
 const owners=new Set();let dead=false;
 const apply=()=>{if(dead)return;scene.requestRenderMode=owners.size===0;scene.maximumRenderTimeChange=Infinity;scene.requestRender();};
 apply();
 return {hold(id){if(!dead&&typeof id==='string'&&id){owners.add(id);apply();}},release(id){if(!dead){owners.delete(id);apply();}},request(){if(!dead)scene.requestRender();},destroy(){owners.clear();dead=true;}};
}
