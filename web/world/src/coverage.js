const finite=n=>typeof n==='number'&&Number.isFinite(n);
export const lonlat=p=>Array.isArray(p)&&p.length===2&&p.every(finite)&&Math.abs(p[0])<=180&&Math.abs(p[1])<=90;
const bounds=b=>Array.isArray(b)&&b.length===4&&b.every(finite)&&b[0]>=-180&&b[2]<=180&&b[1]>=-90&&b[3]<=90&&b[0]<b[2]&&b[1]<b[3];
const same=(a,b)=>a[0]===b[0]&&a[1]===b[1];
const route=g=>Array.isArray(g)&&g.every(lonlat)?g:[];
export function usableRoad(item){const points=route(item?.geometry_lonlat).slice(0,512);return points.length>=2&&points.some(p=>!same(p,points[0]));}
export function usableBuilding(item){const ring=route(item?.geometry_lonlat);if(ring.length<4||ring.length>256||!same(ring[0],ring.at(-1)))return false;
 const vertices=ring.slice(0,-1);if(new Set(vertices.map(p=>p.join(','))).size<3)return false;
 const anchor=vertices[0];let area=0;for(let i=0;i<vertices.length;i++){const a=vertices[i],b=vertices[(i+1)%vertices.length];area+=(a[0]-anchor[0])*(b[1]-anchor[1])-(b[0]-anchor[0])*(a[1]-anchor[1]);}
 return Number.isFinite(area)&&area!==0;
}
export function coverageAt(area,p,trainingValid){
 const b=area?.coverage_bbox_lonlat;const acquired=lonlat(p)&&bounds(b)&&p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3];
 const layers=Array.isArray(area?.coverage)?area.coverage:[];
 const available=name=>acquired&&layers.some(v=>v?.layer===name&&v.status==='available');
 const roadFeatures=available('roads')&&Array.isArray(area?.roads)?area.roads.filter(usableRoad):[];
 const buildingFeatures=available('buildings')&&Array.isArray(area?.buildings)?area.buildings.filter(usableBuilding):[];
 return {acquired,roads:roadFeatures.length>0,buildings:buildingFeatures.length>0,roadFeatures,buildingFeatures,training:roadFeatures.length>0&&trainingValid===true};
}
