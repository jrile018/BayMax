const valid=r=>r&&[r.x,r.y,r.width,r.height].every(Number.isFinite)&&r.width>0&&r.height>0;
const overlaps=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
export function layoutLabels(candidates,viewport,reserved=[],cap=150){
 if(!valid(viewport))return [];
 const limit=Number.isFinite(cap)?Math.max(0,Math.min(150,Math.floor(cap))):150;
 const blocked=reserved.filter(valid),chosen=[];
 const sorted=[...candidates].sort((a,b)=>(b.priority||0)-(a.priority||0));
 for(const c of sorted){
  if(chosen.length>=limit)break;
  if(!valid(c)||c.x<viewport.x||c.y<viewport.y||c.x+c.width>viewport.x+viewport.width||c.y+c.height>viewport.y+viewport.height)continue;
  if(blocked.some(r=>overlaps(c,r))||chosen.some(r=>overlaps(c,r)))continue;
  chosen.push(c);
 }
 return chosen;
}
