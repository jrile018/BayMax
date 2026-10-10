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
    confirmations: tuple[dict, ...] = ()
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
    def review(self, proposal_id, decision, reviewer_id, *, expected_revision=None, confirmations=()):
        if decision not in ('accepted', 'rejected') or not isinstance(reviewer_id, str) or not reviewer_id.strip():
            raise ValidationError('review requires accepted/rejected and a reviewer ID')
        if not isinstance(confirmations, (tuple, list)):
            raise ValidationError('confirmations must be a sequence')
        if confirmations and expected_revision is None:
            raise ValidationError('confirmed review requires an inspected revision')
        if decision == 'rejected' and confirmations:
            raise ValidationError('rejection cannot confirm a command')

        old = self.get(proposal_id)
        _check_revision(old, expected_revision)
        if old.review_status == 'duplicate':
            raise ValidationError('duplicate report cannot emit repeated effects')

        claims = {c.claim_id: c for c in old.proposal.claims}
        normalized = []
        seen = set()
        for item in confirmations:
            if not isinstance(item, dict) or set(item) != {'claim_id', 'kind', 'mapped_entity_id', 'confirmed_values', 'semantic_override_reason'}:
                raise ValidationError('confirmation has unsupported fields')
            claim_id, kind = item['claim_id'], item['kind']
            if not isinstance(claim_id, str) or not claim_id or claim_id in seen or claim_id not in claims:
                raise ValidationError('unknown or duplicate confirmed claim')
            seen.add(claim_id)
            claim = claims[claim_id]
            if kind != claim.kind or kind not in ('need', 'access'):
                raise ValidationError('confirmed claim kind mismatch')
            mapped_id = item['mapped_entity_id']
            if not isinstance(mapped_id, str) or not mapped_id.strip() or claim.location is None:
                raise ValidationError('confirmed mapped entity or place missing')
            mapped = self._aliases.get(claim.location.value)
            expected_type = 'node' if kind == 'need' else 'edge'
            if mapped is None or mapped['entity_type'] != expected_type or mapped['entity_id'] != mapped_id:
                raise ValidationError('confirmed mapped entity mismatch')
            reason = item['semantic_override_reason']
            if reason is not None and (not isinstance(reason, str) or not reason.strip() or len(reason) > 1000):
                raise ValidationError('semantic override reason must be nonempty bounded text or null')
            hard = {'adversarial', 'negation', 'conflict', 'missing_place', 'unknown_count', 'unknown_access', 'no_need'}
            all_flags = set(old.proposal.flags) | set(claim.flags)
            if all_flags & hard:
                raise ValidationError('claim has a hard-stop flag')
            caution = {'qualified_access', 'vague_count', 'multiple_requests'}
            if all_flags & caution and reason is None:
                raise ValidationError('caution claim requires semantic override reason')
            values = item['confirmed_values']
            if not isinstance(values, dict):
                raise ValidationError('confirmed values must be an exact object')
            if kind == 'need':
                if set(values) != {'category', 'quantity', 'unit', 'location', 'urgency'}:
                    raise ValidationError('need confirmation fields mismatch')
                if claim.quantity is None or claim.unit is None or type(values['quantity']) is not int or values['quantity'] <= 0:
                    raise ValidationError('need confirmation requires a positive requested amount')
                expected_values = {
                    'category': claim.label, 'quantity': claim.quantity.value,
                    'unit': claim.unit.value, 'location': claim.location.value,
                    'urgency': claim.urgency.value if claim.urgency else None,
                }
            else:
                if set(values) != {'status', 'location', 'scope'} or claim.label == 'unknown':
                    raise ValidationError('access confirmation fields mismatch')
                expected_values = {'status': claim.label, 'location': claim.location.value, 'scope': 'unqualified'}
            if values != expected_values or any(type(values[k]) is not type(expected_values[k]) for k in values):
                raise ValidationError('confirmed values do not match the current claim')
            normalized.append(deepcopy(item))
        claim_order = {claim.claim_id: index for index, claim in enumerate(old.proposal.claims)}
        normalized = tuple(sorted(normalized, key=lambda item: claim_order[item['claim_id']]))

        if old.review_status != 'pending':
            if old.review_status == decision and old.reviewer_id == reviewer_id and old.confirmations == normalized:
                return deepcopy(old)
            raise ValidationError('review is terminal; create a new reviewed report to revise')

        effects = []
        if decision == 'accepted':
            for item in normalized:
                claim = claims[item['claim_id']]
                mapped = self._aliases[claim.location.value]
                effect = {
                    'type': 'propose_need' if claim.kind == 'need' else 'propose_access_observation',
                    'idempotency_key': f'{old.proposal_id}:{claim.claim_id}',
                    'report_id': old.proposal.report.report_id,
                    'source': old.proposal.report.source,
                    'received_time_s': old.proposal.report.received_time_s,
                    'reviewer_id': reviewer_id, 'review_status': 'accepted',
                    'provider': old.proposal.provider, 'revision': old.revision,
                    'editors': list(old.editors), 'mapped_entity': deepcopy(mapped),
                    'claim': asdict(claim), 'confirmation': deepcopy(item),
                }
                if claim.kind == 'need':
                    effect.update(category=claim.label, quantity=claim.quantity.value,
                                  unit=claim.unit.value,
                                  urgency=claim.urgency.value if claim.urgency else None)
                else:
                    effect.update(status=claim.label)
                effects.append(effect)
        record = replace(old, review_status=decision, reviewer_id=reviewer_id,
                         effects=tuple(effects), confirmations=normalized)
        self._records[proposal_id] = record
        return deepcopy(record)
