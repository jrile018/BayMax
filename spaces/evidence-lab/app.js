'use strict';
const titles={taxonomy:'Historical report classification',retrieval:'Multilingual source search',transcription:'Permitted audio transcription'};
const tabs=Array.from(document.querySelectorAll('[data-component]'));
let saved=null;
function text(id,value){document.getElementById(id).textContent=value;}
function selectComponent(name){
  tabs.forEach(tab=>{const selected=tab.dataset.component===name;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;});
  document.getElementById('capability').setAttribute('aria-labelledby','tab-'+name);
  text('capability-title',titles[name]);
  const metrics=document.getElementById('metrics');metrics.replaceChildren();
  const refs=document.getElementById('refs');refs.replaceChildren();
  if(!saved){text('status','Saved results unavailable');text('reason','Reload to retry. No model or live service is connected.');text('method','');return;}
  const item=saved.components[name];
  const statuses={pending:'Pilot pending',failed:'Pilot failed',measured:'Measured and reviewed'};
  text('status',statuses[item.status]);text('reason',item.reason||'Results are recorded, not live.');
  text('method',item.methodology);
  if(item.status==='measured'){
    Object.entries(item.metrics).forEach(([name,value])=>{const term=document.createElement('dt');term.textContent=name.replaceAll('_',' ');const result=document.createElement('dd');result.textContent=String(value);metrics.append(term,result);});
    const count=document.createElement('p');count.textContent='Denominators: '+Object.entries(item.denominators).map(([key,value])=>key.replaceAll('_',' ')+': '+value).join(', ');metrics.append(count);
  }
  item.sources.forEach((url,index)=>{const link=document.createElement('a');link.href=url;link.textContent='Source '+(index+1);link.rel='noopener noreferrer';refs.append(link,document.createTextNode(' '));});
}
function showExample(){
  const replay=saved&&saved.replays.find(item=>item.id===document.getElementById('example').value);
  text('excerpt',replay?replay.text:'Recorded examples unavailable.');
  text('proposal',replay?replay.proposal:'No interpretation has been loaded.');
}
tabs.forEach((tab,index)=>{
  tab.addEventListener('click',()=>selectComponent(tab.dataset.component));
  tab.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
    tabs[next].focus();selectComponent(tabs[next].dataset.component);
  });
});
document.getElementById('example').addEventListener('change',showExample);
fetch('results.json',{credentials:'omit',cache:'no-store'}).then(response=>{
  if(!response.ok)throw new Error('unavailable');return response.json();
}).then(data=>{
  if(data.schema!=='baymax.evidence.v1'||!data.components||!Array.isArray(data.replays))throw new Error('invalid saved results');
  for(const name of Object.keys(titles)){
    const item=data.components[name];
    if(!item||!['pending','failed','measured'].includes(item.status)||typeof item.methodology!=='string'||!Array.isArray(item.sources))throw new Error('invalid component');
    if(item.sources.some(url=>{const u=new URL(url);return u.protocol!=='https:'||u.hostname!=='huggingface.co'||u.username||u.password;}))throw new Error('invalid source');
    if(item.status==='measured'&&(!item.metrics||!item.denominators||!item.receipt_sha))throw new Error('unreviewed result');
  }
  saved=data;
  const select=document.getElementById('example');
  data.replays.forEach(item=>{const option=document.createElement('option');option.value=item.id;option.textContent=item.label+': '+item.id.replaceAll('-',' ');select.append(option);});
  showExample();selectComponent('taxonomy');
}).catch(()=>{saved=null;showExample();selectComponent('taxonomy');});
