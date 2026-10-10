"""Human review produces pending integration commands, never simulator mutations."""
from dataclasses import asdict, dataclass, replace
from copy import deepcopy
from hashlib import sha256
import re
from functools import wraps
from threading import RLock
from .schema import Proposal, ValidationError, parse_proposal

@dataclass(frozen=True)
class ReviewRecord:
    proposal_id: str
    proposal: Proposal
    review_status: str = 'pending'
    reviewer_id: str | None = None
    duplicate_of: str | None = None
    effects: tuple[dict, ...] = ()
    revision: int = 1
    editors: tuple[str, ...] = ()

def _content_key(text):
    # Exact normalized repost detection, not similarity or verified identity.
    text=re.sub(r'^\s*repost:\s*','',text,flags=re.I)
    return sha256(' '.join(text.split()).casefold().encode()).hexdigest()

def _serialized(method):
    @wraps(method)
    def guarded(self,*args,**kwargs):
        with self._lock:
            return method(self,*args,**kwargs)
    return guarded

def _check_revision(record,expected_revision):
    if expected_revision is not None:
        if type(expected_revision) is not int or expected_revision<1 or expected_revision!=record.revision:
            raise ValidationError('review revision precondition failed; inspect the current proposal')

class ReviewStore:
    """In-memory exercise store. Service adapter must authenticate the human reviewer."""
    def __init__(self, aliases):
        self._lock=RLock()
        self._aliases=deepcopy(aliases)
        self._records={}; self._by_report={}; self._by_content={}
        for alias,record in self._aliases.items():
            if not isinstance(alias,str) or not alias or not isinstance(record,dict) or set(record)!={'entity_id','entity_type','source'} or record['entity_type'] not in ('node','edge') or not all(isinstance(v,str) and v.strip() for v in record.values()):
                raise ValidationError('aliases require literal mention, entity_id/type and independent source')

    @_serialized
    def submit(self, report, payload, provider):
        p=parse_proposal(report,payload,provider)
        if report.report_id in self._by_report:
            old=self._records[self._by_report[report.report_id]]
            if old.proposal != p: raise ValidationError('report ID reused with altered source/extraction')
            return deepcopy(old)
        content_key=_content_key(report.text)
        key=f'{content_key}:{report.source}:{report.received_time_s}'
        pid='intake:'+sha256(report.report_id.encode()).hexdigest()[:24]
        duplicate=self._by_content.get(key)
        rec=ReviewRecord(pid,p,'duplicate' if duplicate else 'pending',duplicate_of=duplicate)
        self._records[pid]=rec; self._by_report[report.report_id]=pid
        if not duplicate: self._by_content[key]=pid
        return deepcopy(rec)

    @_serialized
    def get(self, proposal_id):
        if proposal_id not in self._records: raise ValidationError('unknown proposal')
        return deepcopy(self._records[proposal_id])

    @_serialized
    def edit(self, proposal_id, payload, editor_id, *, expected_revision=None):
        if not isinstance(editor_id,str) or not editor_id.strip():
            raise ValidationError('edit requires authenticated human editor ID')
        old=self.get(proposal_id)
        _check_revision(old,expected_revision)
        if old.review_status!='pending': raise ValidationError('only pending proposals can be corrected')
        proposal=parse_proposal(old.proposal.report,payload,old.proposal.provider)
        rec=replace(old,proposal=proposal,revision=old.revision+1,editors=old.editors+(editor_id,))
        self._records[proposal_id]=rec
        return deepcopy(rec)

    @_serialized
    def review(self, proposal_id, decision, reviewer_id, *, expected_revision=None):
        if decision not in ('accepted','rejected') or not isinstance(reviewer_id,str) or not reviewer_id.strip():
            raise ValidationError('review requires accepted/rejected and authenticated human reviewer ID')
        old=self.get(proposal_id)
        _check_revision(old,expected_revision)
        if old.review_status=='duplicate': raise ValidationError('duplicate report cannot emit repeated effects')
        if old.review_status!='pending':
            if old.review_status==decision and old.reviewer_id==reviewer_id: return old
            raise ValidationError('review is terminal; create a new reviewed report to revise')
        effects=[]
        blocked={'adversarial','conflict','negation','qualified_access'}
        if decision=='accepted' and not blocked.intersection(old.proposal.flags):
            for c in old.proposal.claims:
                if blocked.intersection(c.flags) or not c.location: continue
                mapped=self._aliases.get(c.location.value)
                if mapped is None: continue
                if c.kind=='need' and (mapped['entity_type']!='node' or not c.quantity or not c.unit): continue
                if c.kind=='access' and (mapped['entity_type']!='edge' or c.label=='unknown'): continue
                e={'type':'propose_need' if c.kind=='need' else 'propose_access_observation',
                   'idempotency_key':f'{old.proposal_id}:{c.claim_id}', 'report_id':old.proposal.report.report_id,
                   'source':old.proposal.report.source,'received_time_s':old.proposal.report.received_time_s,
                   'reviewer_id':reviewer_id,'review_status':'accepted','provider':old.proposal.provider,
                   'revision':old.revision,'editors':list(old.editors),
                   'mapped_entity':deepcopy(mapped),'claim':asdict(c)}
                if c.kind=='need': e.update(category=c.label,quantity=c.quantity.value,unit=c.unit.value,urgency=c.urgency.value if c.urgency else None)
                else: e.update(status=c.label)
                effects.append(e)
        rec=replace(old,review_status=decision,reviewer_id=reviewer_id,effects=tuple(effects))
        self._records[proposal_id]=rec
        return deepcopy(rec)
