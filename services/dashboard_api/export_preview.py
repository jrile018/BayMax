"""Export a saved replay on the server for authenticated notebook-file viewing."""
import argparse
import json
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
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
    mode_label='Saved mock replay' if bootstrap.get('mode') == 'mock-replay' else 'Saved recorded replay'
    banner='<div class="saved-preview-banner" role="note">'+mode_label+' · generated on Radeon Cloud · exact recorded frames · live actions and coverage queries unavailable</div>'
    document=_PreviewDocument(web_root,bridge,banner)
    document.feed((web_root/'index.html').read_text(encoding='utf-8'))
    document.close()
    if not document.body_closed:
        raise ValueError('Preview HTML must contain a complete body element')
    return ''.join(document.parts)


def _safe_raw_element(source, tag):
    # A trusted local asset may contain this delimiter as a JavaScript string.
    return re.sub(r'</('+tag+r')',lambda match: '<\\/'+match[1],source,flags=re.I)


class _PreviewDocument(HTMLParser):
    """Inline local classic assets, then run deferred scripts after the saved API."""
    def __init__(self,web_root,bridge,banner):
        super().__init__(convert_charrefs=False)
        self.web_root=Path(web_root).resolve()
        self.bridge=bridge
        self.banner=banner
        self.parts=[]
        self.scripts=[]
        self.skip_script=False
        self.body_closed=False

    def _asset(self,reference,suffix):
        parsed=urlsplit(reference)
        name=unquote(parsed.path)
        if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or
                not name or name.startswith(('/', '\\')) or '\\' in name):
            raise ValueError('Preview assets must use local relative file paths')
        path=(self.web_root/name).resolve()
        if not path.is_relative_to(self.web_root) or path.suffix.lower()!=suffix:
            raise ValueError('Preview asset escapes its web root or has an unsupported type')
        return path.read_text(encoding='utf-8')

    def handle_starttag(self,tag,attrs):
        if self.skip_script:
            return
        values=dict(attrs)
        if tag=='link' and 'stylesheet' in values.get('rel','').lower().split():
            css=self._asset(values.get('href',''),'.css')
            self.parts.append('<style>'+_safe_raw_element(css,'style')+'</style>')
            return
        if tag=='script' and 'src' in values:
            if 'async' in values or values.get('type','').lower() not in ('','text/javascript','application/javascript'):
                raise ValueError('Saved preview supports ordered classic scripts only')
            self.scripts.append(self._asset(values['src'],'.js'))
            self.skip_script=True
            return
        self.parts.append(self.get_starttag_text())
        if tag=='body':
            self.parts.append(self.banner)

    def handle_startendtag(self,tag,attrs):
        if tag in ('link','script'):
            self.handle_starttag(tag,attrs)
            if tag=='script':
                self.handle_endtag(tag)
        elif not self.skip_script:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self,tag):
        if self.skip_script:
            if tag=='script':
                self.skip_script=False
            return
        if tag=='body':
            self.parts.append('<script>'+self.bridge+'</script>')
            self.parts.extend('<script>'+_safe_raw_element(source,'script')+'</script>' for source in self.scripts)
            self.body_closed=True
        self.parts.append('</'+tag+'>')

    def handle_data(self,data):
        if not self.skip_script:
            self.parts.append(data)

    def handle_entityref(self,name):
        self.handle_data('&'+name+';')

    def handle_charref(self,name):
        self.handle_data('&#'+name+';')

    def handle_comment(self,data):
        self.handle_data('<!--'+data+'-->')

    def handle_decl(self,decl):
        self.handle_data('<!'+decl+'>')

    def handle_pi(self,data):
        self.handle_data('<?'+data+'>')


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
