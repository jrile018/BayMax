"""Strict source-preserving intake types; validation is not fact verification."""
from dataclasses import dataclass
import math
import re

class ValidationError(ValueError):
    """Untrusted extraction or review input failed a structural/evidence gate."""

@dataclass(frozen=True)
class Report:
    report_id: str
    source: str
    received_time_s: float
    text: str

    def __post_init__(self):
        for name in ('report_id', 'source', 'text'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f'report.{name} must be nonempty text')
        if len(self.text) > 24000:
            raise ValidationError('report exceeds 24000 characters')
        if isinstance(self.received_time_s, bool) or not isinstance(self.received_time_s, (float,int)) or not math.isfinite(self.received_time_s) or self.received_time_s < 0:
            raise ValidationError('received_time_s must be finite nonnegative seconds')

@dataclass(frozen=True)
class Evidence:
    start: int
    end: int
    quote: str

@dataclass(frozen=True)
class Slot:
    value: str | int
    evidence: Evidence

@dataclass(frozen=True)
class Claim:
    claim_id: str
    kind: str
    label: str
    evidence: Evidence
    quantity: Slot | None
    unit: Slot | None
    urgency: Slot | None
    location: Slot | None
    flags: tuple[str, ...]

@dataclass(frozen=True)
class Proposal:
    report: Report
    language: str
    claims: tuple[Claim, ...]
    flags: tuple[str, ...]
    provider: str

FLAGS = frozenset({'conflict','unknown_access','missing_place','unknown_count','vague_count','negation','no_need','adversarial','qualified_access','multiple_requests','duplicate_repost'})
NEED_TERMS = {'medical':r'\b(medical|patient|patients|oxygen|medic[oa]|pacientes?)\b',
    'evacuation':r'\b(evacuat\w*|transport|evacua\w*|transporte)\b',
    'water':r'\b(water|agua)\b', 'food':r'\b(food|meal\w*|alimentos?|comida)\b',
    'shelter':r'\b(shelter|blankets?|refugio|mantas?)\b'}
ACCESS_TERMS = {'blocked':r'\b(blocked|closed|impassable|bloquead[oa]|cerrad[oa])\b',
    'open':r'\b(open|clear|abiert[oa]|despejad[oa])\b',
    'unknown':r'\b(unknown|not checked|nobody has checked|no access information|desconocid[oa])\b'}
NUMBER_WORDS = {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'eleven':11,'twelve':12,'uno':1,'una':1,'dos':2,'tres':3,'cuatro':4,'cinco':5,'seis':6,'siete':7,'ocho':8,'nueve':9,'diez':10,'once':11,'doce':12}
APPROX = r'\b(about|roughly|around|approximately|some|several|dozen|aproximadamente|varios)\b'
NEGATION = r'\b(no one|nobody needs|no people|no food request|do not send|no need|nadie necesita|no necesitan)\b'
ADVERSARIAL = r'\b(ignore (all rules|previous instructions)|system override|dispatch all|invent a location|mark every road|report 200 patients)\b'
URGENT = r'\b(now|immediately|urgent\w*|ahora|inmediatamente)\b'
NEED_REQUEST = r'\b(need\w*|request\w*|pickup|necesit\w*|requiere\w*|solicita\w*)\b'
COUNT_UNCERTAINTY = APPROX + r'|\b(between|at least|at most|more than|less than|up to)\b|[0-9]+\s*[-–]\s*[0-9]+'
CLAUSE_NEGATION = r"\b(not|no|never|without|don't|doesn't|didn't|cannot|can't|sin|nadie)\b"
SOON = r'\b(soon|today|tomorrow|tonight|before|within|by|pronto|hoy|ma[ñn]ana)\b'
COMPLETED_EVENT = r'\b(?:delivered|distributed|supplied|provided|served|received|evacuated|completed|picked up|dropped off)\b'
PAST_EVENT_CONTEXT = r'\b(?:delivery|distribution|arrival|shipment|receipt|dropoff|delivered|distributed|arrived|supplied|provided|received|previously|earlier|prior|yesterday|already)\b'
REQUEST_SEGMENT_BOUNDARY = r'[,;.!?\n]|\b(?:and|but|however|yet|while|whereas|then|after|before|following|despite|since|because|although|though|once)\b'
REQUEST_CONJUNCTION = r'\b(?:but|and|however|yet|while|whereas|then)\b'
ACCESS_COREFERENCE = r'\b(?:it|there|this road|that road|the road|this route|that route|the route|this highway|that highway|the highway)\b'
ACCESS_RESTRICTION = r'\b(?:only|except|excluding|unless|until|before|after|between|during|limited|restricted|prohibited|cannot|not allowed)\b|\bmay\s+not\b'
ACCESS_ACTION = r'\b(?:cross|use|pass|travel|enter|drive|walk|access|open|closed|blocked|limited|restricted|prohibited)\b'
ACCESS_ELLIPSIS = r'^\s*(?:(?:only\s+)?(?:bicycles?|bikes?|cyclists?|pedestrians?|vehicles?|cars?|trucks?|buses?|motorcycles?|ambulances?)\s+(?:only\b|(?:may|can|must)\s+(?:cross|use|pass|travel)\b)|access\s+is\s+(?:limited|restricted)\s+to\b)'
OTHER_ROAD_SUBJECT = r'^\s*(?:the\s+)?(?:[Hh]ighway|[Rr]oad|[Rr]oute|[Ss]treet|[Bb]ridge|[Aa]venue)\s+(?:[A-Z][A-Za-z0-9-]*|\d+)\b'
ACCESS_QUALIFIER = (
    r'\b(?:only|except|excluding|unless|until|before|after|between|during|'
    r'bicycles?|bikes?|cyclists?|pedestrians?|peatones?|on foot|'
    r'vehicles?|cars?|trucks?|buses?|motorcycles?|ambulances?|'
    r'solo|solamente|excepto|hasta|antes|despu[eé]s|entre)\b'
    r'|\bfor\s+\d+\s+(?:minutes?|hours?|days?)\b'
)

def _object(raw, keys, path):
    if not isinstance(raw,dict) or set(raw)!=set(keys):
        raise ValidationError(f'{path}: expected keys {sorted(keys)}')

def _text(value, path):
    if not isinstance(value,str) or not value.strip(): raise ValidationError(f'{path}: expected nonempty text')
    return value

def _flags(raw, path):
    if not isinstance(raw,list) or len(raw)>len(FLAGS) or any(not isinstance(v,str) or v not in FLAGS for v in raw):
        raise ValidationError(f'{path}: unknown flag')
    return tuple(sorted(set(raw)))

def evidence(report, raw):
    _object(raw, ('start','end','quote'), 'evidence')
    start,end,quote = raw['start'],raw['end'],raw['quote']
    if type(start) is not int or type(end) is not int or not 0<=start<end<=len(report.text):
        raise ValidationError('evidence offsets must be Unicode character indices within report')
    if not isinstance(quote,str) or report.text[start:end]!=quote:
        raise ValidationError('evidence quote must exactly match source slice')
    return Evidence(start,end,quote)

def _slot(report, raw, name):
    if raw is None: return None
    _object(raw, ('value','evidence'), name)
    ev=evidence(report,raw['evidence']); value=raw['value']
    if name=='quantity':
        if type(value) is not int or not 0<value<=1000000:
            raise ValidationError('quantity must be a positive integer <=1000000')
        nums=[int(v) for v in re.findall(r'\b[0-9]+\b',ev.quote)]
        nums += [NUMBER_WORDS[w.lower()] for w in re.findall(r'\b\w+\b',ev.quote) if w.lower() in NUMBER_WORDS]
        if value not in nums or re.search(APPROX,ev.quote,re.I):
            raise ValidationError('quantity lacks explicit exact count evidence')
    else:
        _text(value,name)
        if name=='location' and value!=ev.quote:
            raise ValidationError('location must equal its exact literal source mention')
        if name=='unit' and value.casefold() not in ev.quote.casefold():
            raise ValidationError('quantity unit must be quoted')
        if name=='urgency':
            terms={'immediate':URGENT,'soon':SOON}
            if value not in terms or not re.search(terms[value],ev.quote,re.I):
                raise ValidationError('urgency lacks supported literal evidence')
    return Slot(value,ev)

def detect_flags(text):
    flags=set()
    if re.search(NEGATION,text,re.I): flags.add('negation')
    if re.search(ADVERSARIAL,text,re.I): flags.add('adversarial')
    if re.search(r'\b(pedestrians?|on foot|peatones?)\b',text,re.I): flags.add('qualified_access')
    return flags

def _source_clause(report, ev, kind):
    # Inspect full source context, not just the model-selected shortened quote.
    starts=[m.end() for m in re.finditer(r'[.;!?\n]',report.text[:ev.start])]
    lo=starts[-1] if starts else 0
    end=re.search(r'[.;!?\n]',report.text[ev.start:])
    hi=ev.start+end.start() if end else len(report.text)
    if kind=='need':
        clause=report.text[lo:hi]
        for join in re.finditer(REQUEST_CONJUNCTION,clause,re.I):
            if (re.search(COMPLETED_EVENT,clause[:join.start()],re.I)
                    and re.search(NEED_REQUEST,clause[join.end():],re.I)):
                boundary_start, boundary_end=lo+join.start(),lo+join.end()
                if ev.start>=boundary_end:
                    lo=boundary_end
                else:
                    hi=boundary_start
                break
    if kind=='access' and ev.end>hi+1:
        # Some access evidence includes a semicolon and its explanation.
        # Keep that explanation, but do not borrow a following sentence.
        if re.search(r'[.;!?\n]$', ev.quote):
            hi=ev.end-1
        else:
            next_end=re.search(r'[.;!?\n]',report.text[ev.end:])
            hi=ev.end+next_end.start() if next_end else len(report.text)
    return lo,hi,report.text[lo:hi]

def _count_in_request_segment(report, context_start, context_end, quantity, unit):
    # Only an atomic request phrase can size a new need. Mixed past-event
    # phrases or distant modifiers abstain instead of lending their count.
    context=report.text[context_start:context_end]
    cuts=[context_start]
    for boundary in re.finditer(REQUEST_SEGMENT_BOUNDARY,context,re.I):
        cuts.extend((context_start+boundary.start(),context_start+boundary.end()))
    cuts.append(context_end)
    for lo,hi in zip(cuts[::2],cuts[1::2]):
        q,u=quantity.evidence,unit.evidence
        if not (lo<=q.start<q.end<=hi and lo<=u.start<u.end<=hi):
            continue
        segment=report.text[lo:hi]
        if re.search(COMPLETED_EVENT,segment,re.I) or re.search(PAST_EVENT_CONTEXT,segment,re.I):
            return False
        count_start,count_end=min(q.start,u.start),max(q.end,u.end)
        for request in re.finditer(NEED_REQUEST,segment,re.I):
            request_start,request_end=lo+request.start(),lo+request.end()
            bridge=(report.text[request_end:count_start] if request_end<=count_start
                    else report.text[count_end:request_start] if count_end<=request_start else '')
            if (len(re.findall(r'\b\w+\b',bridge))<=8
                    and not re.search(PAST_EVENT_CONTEXT,bridge,re.I)):
                return True
        return False
    return False


def _following_access_restriction(report, context_end, location):
    # A short follow-on sentence may scope an otherwise unqualified 'open'.
    tail=report.text[context_end+1:]
    if not tail.strip():
        return False
    end=re.search(r'[.;!?\n]',tail)
    following=tail[:end.start()] if end else tail
    if not re.search(ACCESS_RESTRICTION,following,re.I):
        return False
    ellipsis=bool(re.search(ACCESS_ELLIPSIS,following,re.I))
    if not ellipsis and not re.search(ACCESS_ACTION,following,re.I):
        return False
    subject=re.match(OTHER_ROAD_SUBJECT,following)
    if subject and subject.group().strip().casefold()!=location.casefold():
        return False
    return bool(re.search(ACCESS_COREFERENCE,following,re.I)
                or re.search(re.escape(location),following,re.I)
                or ellipsis)


def parse_proposal(report, payload, provider):
    if not isinstance(report,Report): raise ValidationError('expected Report')
    _text(provider,'provider')
    _object(payload, ('language','flags','claims'), 'proposal')
    if payload['language'] not in ('en','es','unknown'): raise ValidationError('unsupported declared language')
    flags=set(_flags(payload['flags'],'proposal.flags')) | detect_flags(report.text)
    if not isinstance(payload['claims'],list) or len(payload['claims'])>20: raise ValidationError('claims must be list <=20')
    claims=[]; identifiers=set()
    for raw in payload['claims']:
        _object(raw, ('claim_id','kind','label','evidence','quantity','unit','urgency','location','flags'), 'claim')
        cid=_text(raw['claim_id'],'claim_id')
        if cid in identifiers: raise ValidationError('duplicate claim ID')
        identifiers.add(cid)
        kind,label=raw['kind'],raw['label']
        _text(kind,'kind'); _text(label,'label')
        terms=NEED_TERMS if kind=='need' else ACCESS_TERMS if kind=='access' else {}
        ev=evidence(report,raw['evidence'])
        if kind=='need' and re.search(r'[.;!?\n]', ev.quote[:-1]):
            raise ValidationError('claim evidence must stay within one source clause')
        if label not in terms or not re.search(terms[label],ev.quote,re.I):
            raise ValidationError('claim label lacks category/status evidence')
        context_start,context_end,context=_source_clause(report,ev,kind)
        if kind=='need' and ev.end > context_end + 1:
            raise ValidationError('claim evidence must stay within one source clause')
        if kind=='need' and not re.search(NEED_REQUEST,context,re.I):
            raise ValidationError('need claim must cite a positive stated request, not a completed event')
        slots={k:_slot(report,raw[k],k) for k in ('quantity','unit','urgency','location')}
        for name in ('quantity','unit','urgency'):
            sl=slots[name]
            if sl and not ev.start<=sl.evidence.start<sl.evidence.end<=ev.end:
                raise ValidationError(f'{name} evidence must belong to the same claim clause')
        if kind=='access' and any(slots[k] is not None for k in ('quantity','unit','urgency')):
            raise ValidationError('access claims cannot carry need count/unit/urgency')
        if bool(slots['quantity'])!=bool(slots['unit']): raise ValidationError('exact quantity requires an explicit quantity unit')
        if slots['quantity'] and re.search(COUNT_UNCERTAINTY,context,re.I):
            raise ValidationError('approximate or range count must remain unknown')
        if kind=='need' and slots['quantity'] and not _count_in_request_segment(
                report,context_start,context_end,slots['quantity'],slots['unit']):
            raise ValidationError('quantity and unit must belong to the current request segment')
        loc=slots['location']
        if loc and not context_start<=loc.evidence.start<loc.evidence.end<=context_end:
            prefix=report.text[:loc.evidence.start]
            inherited=bool(re.search(r'\b(?:at|in)\s*$',prefix,re.I))
            between=report.text[loc.evidence.end:context_start]
            if not inherited or loc.evidence.end>context_start or re.search(r'[.!?\n]|\b(?:at|in)\s',between,re.I):
                raise ValidationError('location must belong to this clause or its inherited preceding place context')
        cflags=set(_flags(raw['flags'],'claim.flags'))
        if kind=='access' and (re.search(ACCESS_QUALIFIER,context + ' ' + ev.quote,re.I)
                               or (loc and _following_access_restriction(report,context_end,loc.value))):
            cflags.add('qualified_access')
        if re.search(CLAUSE_NEGATION,context,re.I) and label!='unknown': cflags.add('negation')
        if slots['location'] is None: cflags.add('missing_place')
        if kind=='need' and slots['quantity'] is None: cflags.add('unknown_count')
        if kind=='access' and label=='unknown': cflags.add('unknown_access')
        claims.append(Claim(cid,kind,label,ev,**slots,flags=tuple(sorted(cflags))))
    by_location={}
    for c in claims:
        if c.kind=='access' and c.location:
            k=c.location.value.casefold(); by_location.setdefault(k,set()).add(c.label)
    if any(len(v)>1 for v in by_location.values()): flags.add('conflict')
    return Proposal(report,payload['language'],tuple(claims),tuple(sorted(flags)),provider)
