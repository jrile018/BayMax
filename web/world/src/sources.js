export function createLatestSource(fetchJSON,onValue){
 let sequence=0,controller=null,dead=false,last=null;
 const fail=reason=>onValue(last?{status:'stale',snapshot:last.snapshot,reason}:{status:'unavailable',reason});
 return {async refresh(){
  if(dead)return;const mine=++sequence;controller?.abort();controller=new AbortController();
  try{
   const value=await fetchJSON('/api/situation',{signal:controller.signal});
   if(dead||mine!==sequence)return;
   if(value?.status!=='available'){fail(value?.reason||'Accepted source unavailable');return;}
   const s=value.snapshot;
   if(s?.schema_version!=='knight26-incident-v1'||typeof s.snapshot_hash!=='string'||!s.snapshot_hash||!s.categories||typeof s.categories!=='object'||Array.isArray(s.categories)||!Number.isFinite(Date.parse(s.cutoff_utc)))throw Error('Accepted snapshot has invalid shape');
   if(last&&Date.parse(s.cutoff_utc)<Date.parse(last.snapshot.cutoff_utc))throw Error('Older cutoff rejected');
   last=value;onValue(value);
  }catch(error){if(!dead&&mine===sequence&&error?.name!=='AbortError')fail('Accepted source refresh failed or is older than displayed evidence');}
 },destroy(){dead=true;sequence++;controller?.abort();}};
}
