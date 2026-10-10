"""Export a saved replay on the server for authenticated notebook-file viewing."""
import argparse
import json
from pathlib import Path
from .replay import ReplayStore
from .server import ROOT


def render_preview(store, web_root):
    web_root=Path(web_root)
    bootstrap=store.bootstrap()
    saved={'bootstrap':bootstrap,'frames':[store.frame(i) for i in range(bootstrap['replay']['frame_count'])]}
    encoded=json.dumps(saved,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('<',r'\u003c')
    bridge=r"""
const savedReplay = SAVED;
window.fetch = async function(input) {
  const url = new URL(String(input), window.location.href);
  let data, status = 200;
  if (url.pathname === '/api/bootstrap') data = savedReplay.bootstrap;
  else if (url.pathname === '/api/frame') {
    const indices = url.searchParams.getAll('index');
    const raw = indices.length === 1 ? indices[0] : '';
    const index = /^-?[0-9]+$/.test(raw) ? Number(raw) : NaN;
    if (!Number.isInteger(index) || index < 0 || index >= savedReplay.frames.length) {status=400;data={error:'Saved frame index out of range'};}
    else data = savedReplay.frames[index];
  } else if (url.pathname === '/api/coverage') {
    data={available:false,area_id:null,label:'Saved replay',coverage:[],message:'Live coverage query unavailable in this saved replay. The recorded area/source panel remains authoritative.'};
  } else {status=404;data={error:'Saved replay has no live service endpoint'};}
  return new Response(JSON.stringify(data), {status,headers:{'Content-Type':'application/json'}});
};
""".replace('SAVED',encoded)
    html=(web_root/'index.html').read_text()
    html=html.replace('<link rel="stylesheet" href="./style.css">','<style>'+(web_root/'style.css').read_text()+'</style>')
    html=html.replace('<script src="./app.js" defer></script>','')
    mode_label='Saved mock replay' if bootstrap.get('mode') == 'mock-replay' else 'Saved recorded replay'
    banner='<div style="padding:10px 24px;background:#f7dfc5;color:#633a1f;font:600 13px system-ui">'+mode_label+' · generated on Radeon Cloud · exact recorded frames · live actions and coverage queries unavailable</div>'
    html=html.replace('<body>','<body>'+banner)
    return html.replace('</body>','<script>'+bridge+'</script><script>'+(web_root/'app.js').read_text()+'</script></body>')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area',type=Path,default=ROOT/'fixtures/geography/paradise/area.json')
    parser.add_argument('--replay',type=Path,default=ROOT/'fixtures/replay_ui/paradise_mock.json')
    parser.add_argument('--web',type=Path,default=ROOT/'web')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();store=ReplayStore(args.area,args.replay)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render_preview(store,args.web))
    print(f'Saved recorded preview: {args.output}')

if __name__=='__main__':main()
