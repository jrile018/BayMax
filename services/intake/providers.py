"""No learned model is executed by these explicitly labeled CPU providers."""
from copy import deepcopy
import re
from .schema import ValidationError, NEED_TERMS, ACCESS_TERMS, NUMBER_WORDS, APPROX, NEGATION, URGENT, SOON, detect_flags

def span(text, quote, start=0):
    i=text.index(quote,start)
    return {'start':i,'end':i+len(quote),'quote':quote}

def slot(text, value, quote): return {'value':value,'evidence':span(text,quote)}

class FixtureProvider:
    name='mocked_model_fixture'
    def __init__(self,cases): self._cases={c['report_id']:deepcopy(c) for c in cases}
    def extract(self,report):
        case=self._cases.get(report.report_id)
        if case is None or case['text']!=report.text: raise ValidationError('mock fixture requires matching report ID and exact source text')
        return deepcopy(case['gold'])

class RuleBaseline:
    """Frozen limited English pattern baseline, no geocoder or semantic model."""
    name='rule_baseline'
    def extract(self,report):
        text=report.text; flags=detect_flags(text)
        result={'language':'en','flags':sorted(flags),'claims':[]}
        if re.search(NEGATION,text,re.I):
            result['flags']=sorted(flags|{'no_need'}); return result
        place=re.search(r'\b(?:[Aa]t|[Ii]n) ([A-Z][\w -]*?)(?=,|:|\.|\s+(?:need|requests?|has)\b|\s+we\b|$)',text)
        loc=slot(text,place.group(1),place.group(1)) if place else None
        words='|'.join(NUMBER_WORDS)
        count_pattern=rf'\b(?P<n>[0-9]+|{words})\s+(?P<u>people|patients?|residents?|families|bottles?|liters?|blankets?|boxes|meal kits|meal packs|packs)\b'
        for sentence in re.findall(r'[^.!?]+(?:[.!?]|$)',text):
            sentence=sentence.strip()
            if not sentence or 'adversarial' in detect_flags(sentence): continue
            for label,pattern in NEED_TERMS.items():
                if not re.search(pattern,sentence,re.I) or not re.search(r'\b(need\w*|request\w*|medical pickup)\b',sentence,re.I): continue
                ev=span(text,sentence); q=None; unit=None; cf=[]
                match=re.search(count_pattern,sentence,re.I)
                if match and not re.search(APPROX,sentence,re.I):
                    word=match.group('n'); n=int(word) if word.isdigit() else NUMBER_WORDS[word.lower()]
                    q=slot(text,n,match.group(0)); unit=slot(text,match.group('u'),match.group('u'))
                elif match or re.search(APPROX,sentence,re.I): cf.append('vague_count')
                urgency=None
                um=re.search(URGENT,sentence,re.I) or re.search(SOON,sentence,re.I)
                if um: urgency=slot(text,'immediate' if re.search(URGENT,um.group(),re.I) else 'soon',um.group())
                c={'claim_id':f'claim{len(result["claims"])+1}','kind':'need','label':label,'evidence':ev,
                   'quantity':q,'unit':unit,'urgency':urgency,'location':loc,'flags':cf}
                result['claims'].append(c)
            for am in re.finditer(r'(?P<location>(?:[A-Za-z0-9]+[ -]){0,5}[A-Za-z0-9]+)\s+is\s+(?P<status>blocked|closed|open|clear|unknown)\b',sentence,re.I):
                rawloc=am.group('location'); clean=re.sub(r'^(?:The|the)\s+','',rawloc)
                status=am.group('status').lower(); label='blocked' if status in ('blocked','closed') else 'open' if status in ('open','clear') else 'unknown'
                result['claims'].append({'claim_id':f'claim{len(result["claims"])+1}','kind':'access','label':label,
                    'evidence':span(text,am.group()),'quantity':None,'unit':None,'urgency':None,
                    'location':slot(text,clean,clean),'flags':[]})
        return result
