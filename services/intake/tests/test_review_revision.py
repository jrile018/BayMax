import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from services.intake import Report, ReviewStore, ValidationError
from services.intake.providers import RuleBaseline
import services.intake.review as review_module

TEXT='At Pine School, 12 people need evacuation now. East Road is blocked.'
ALIASES={'Pine School':{'entity_id':'pine','entity_type':'node','source':'fictional graph v1'},
         'East Road':{'entity_id':'east','entity_type':'edge','source':'fictional graph v1'}}

def pending():
    store=ReviewStore(ALIASES); report=Report('revision:1','fictional',10,TEXT)
    raw=RuleBaseline().extract(report)
    return store,raw,store.submit(report,raw,'rule_baseline')

def test_acceptance_must_match_the_inspected_revision():
    store,raw,rec=pending()
    newraw=dict(raw); newraw['claims']=raw['claims'][:1]
    edited=store.edit(rec.proposal_id,newraw,'human:editor',expected_revision=1)
    assert edited.revision==2
    with pytest.raises(ValidationError,match='revision'):
        store.review(rec.proposal_id,'accepted','human:reviewer',expected_revision=1)
    assert store.get(rec.proposal_id).review_status=='pending'
    c=edited.proposal.claims[0]
    confirmation={'claim_id':c.claim_id,'kind':'need','mapped_entity_id':'pine',
                  'confirmed_values':{'category':c.label,'quantity':c.quantity.value,
                                      'unit':c.unit.value,'location':c.location.value,
                                      'urgency':c.urgency.value if c.urgency else None},
                  'semantic_override_reason':None}
    accepted=store.review(rec.proposal_id,'accepted','human:reviewer',expected_revision=2,
                          confirmations=(confirmation,))
    assert len(accepted.effects)==1 and accepted.effects[0]['revision']==2
    assert store.review(rec.proposal_id,'accepted','human:reviewer',expected_revision=2, confirmations=(confirmation,))==accepted

@pytest.mark.parametrize('revision',[True,0,-1,'1',3.0])
def test_invalid_edit_review_preconditions_fail_closed(revision):
    store,raw,rec=pending()
    with pytest.raises(ValidationError): store.edit(rec.proposal_id,raw,'human:editor',expected_revision=revision)
    with pytest.raises(ValidationError): store.review(rec.proposal_id,'accepted','human:reviewer',expected_revision=revision)
    assert store.get(rec.proposal_id).revision==1


def test_parallel_edit_and_accept_cannot_overwrite_a_terminal_decision(monkeypatch):
    store,raw,rec=pending(); entered=threading.Event(); release=threading.Event()
    original=review_module.parse_proposal
    def gated_parse(*args,**kwargs):
        if threading.current_thread().name.startswith('edit-worker'):
            entered.set()
            assert release.wait(3), 'test edit release timed out'
        return original(*args,**kwargs)
    monkeypatch.setattr(review_module,'parse_proposal',gated_parse)
    newraw=dict(raw); newraw['claims']=raw['claims'][:1]
    review_started=threading.Event(); review_finished=threading.Event()
    def accept():
        review_started.set()
        try:
            return store.review(rec.proposal_id,'accepted','human:reviewer',expected_revision=1)
        finally:
            review_finished.set()
    with ThreadPoolExecutor(1,thread_name_prefix='edit-worker') as edit_pool, ThreadPoolExecutor(1,thread_name_prefix='review-worker') as review_pool:
        editing=edit_pool.submit(store.edit,rec.proposal_id,newraw,'human:editor',expected_revision=1)
        try:
            assert entered.wait(2)
            reviewing=review_pool.submit(accept)
            assert review_started.wait(2)
            assert not review_finished.wait(.1), 'acceptance bypassed an active edit transaction'
        finally:
            release.set()
        assert editing.result(timeout=3).revision==2
        with pytest.raises(ValidationError,match='revision'): reviewing.result(timeout=3)
    assert store.get(rec.proposal_id).review_status=='pending'
    assert store.get(rec.proposal_id).revision==2


def test_simultaneous_duplicate_submissions_create_one_pending_proposal():
    store=ReviewStore(ALIASES)
    def submit(i):
        report=Report(f'repost:{i}','fictional',10,TEXT)
        return store.submit(report,RuleBaseline().extract(report),'rule_baseline')
    with ThreadPoolExecutor(2) as pool: records=list(pool.map(submit,range(20)))
    assert sum(r.review_status=='pending' for r in records)==1
    assert sum(r.review_status=='duplicate' for r in records)==19
