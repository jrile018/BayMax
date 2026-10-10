import pytest

from services.intake.review import ReviewStore
from services.intake.schema import Report, ValidationError, parse_proposal


def span(text, quote):
    start = text.index(quote)
    return {'start': start, 'end': start + len(quote), 'quote': quote}


def claim(text, *, kind, label, evidence, location, quantity=None, unit=None):
    return {
        'claim_id': 'audit', 'kind': kind, 'label': label,
        'evidence': span(text, evidence),
        'quantity': {'value': quantity, 'evidence': span(text, str(quantity))} if quantity is not None else None,
        'unit': {'value': unit, 'evidence': span(text, unit)} if unit is not None else None,
        'urgency': None,
        'location': {'value': location, 'evidence': span(text, location)},
        'flags': [],
    }


def proposal(raw_claim):
    return {'language': 'en', 'flags': [], 'claims': [raw_claim]}


def test_completed_delivery_count_cannot_be_borrowed_by_later_need():
    text = '10 bottles were delivered to Pine School. Water is needed at Pine School.'
    report = Report('audit:delivery', 'fictional', 10, text)
    raw = proposal(claim(text, kind='need', label='water', evidence=text,
                         location='Pine School', quantity=10, unit='bottles'))
    with pytest.raises(ValidationError, match='clause'):
        parse_proposal(report, raw, 'scripted')


def test_completed_water_delivery_cannot_borrow_following_request_verb():
    text = '10 water bottles were delivered to Pine School. Water is needed at Pine School.'
    report = Report('audit:delivery-context', 'fictional', 10, text)
    delivered = '10 water bottles were delivered to Pine School.'
    raw = proposal(claim(text, kind='need', label='water', evidence=delivered,
                         location='Pine School', quantity=10, unit='bottles'))
    with pytest.raises(ValidationError, match='positive stated request'):
        parse_proposal(report, raw, 'scripted')


@pytest.mark.parametrize('joining', [', but', ' and'])
def test_completed_delivery_count_cannot_cross_request_conjunction(joining):
    text = f'10 water bottles were delivered to Pine School{joining} water is needed now at Pine School.'
    report = Report('audit:delivery-' + joining, 'fictional', 10, text)
    raw = proposal(claim(text, kind='need', label='water', evidence=text,
                         location='Pine School', quantity=10, unit='bottles'))
    with pytest.raises(ValidationError, match='clause'):
        parse_proposal(report, raw, 'scripted')


def test_exact_count_in_same_request_clause_remains_valid():
    text = 'At Pine School, 10 bottles of water are needed.'
    report = Report('audit:need', 'fictional', 10, text)
    raw = proposal(claim(text, kind='need', label='water',
                         evidence='10 bottles of water are needed',
                         location='Pine School', quantity=10, unit='bottles'))
    parsed = parse_proposal(report, raw, 'scripted')
    assert parsed.claims[0].quantity.value == 10


@pytest.mark.parametrize('text', [
    'Highway A is open to bicycles only.',
    'Highway A is open except for trucks.',
    'Highway A is open for cars until noon.',
    'Highway A is open to ambulances.',
])
def test_qualified_open_cannot_emit_unscoped_access(text):
    report = Report('audit:' + text, 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence=text, location='Highway A'))
    store = ReviewStore({'Highway A': {'entity_id': 'highway-a',
                                      'entity_type': 'edge', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    assert 'qualified_access' in rec.proposal.claims[0].flags
    accepted = store.review(rec.proposal_id, 'accepted', 'scripted-reviewer')
    assert accepted.effects == ()


def test_unqualified_open_is_not_restricted_by_next_sentence_vehicle():
    text = 'Highway A is open. Trucks need fuel.'
    report = Report('audit:independent-vehicle', 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence='Highway A is open.', location='Highway A'))
    parsed = parse_proposal(report, raw, 'scripted')
    assert 'qualified_access' not in parsed.claims[0].flags


def test_following_coreferent_restriction_blocks_unscoped_open():
    text = 'Highway A is open. Only bicycles may use it.'
    report = Report('audit:coreference', 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence='Highway A is open', location='Highway A'))
    store = ReviewStore({'Highway A': {'entity_id': 'highway-a',
                                      'entity_type': 'edge', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    assert 'qualified_access' in rec.proposal.claims[0].flags
    assert store.review(rec.proposal_id, 'accepted', 'scripted-reviewer').effects == ()


def test_following_restriction_for_other_road_does_not_scope_open():
    text = 'Highway A is open. Highway B is open to bicycles only.'
    report = Report('audit:other-road', 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence='Highway A is open', location='Highway A'))
    parsed = parse_proposal(report, raw, 'scripted')
    assert 'qualified_access' not in parsed.claims[0].flags


def test_unqualified_open_remains_reviewable():
    text = 'Highway A is open.'
    report = Report('audit:open', 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence=text, location='Highway A'))
    store = ReviewStore({'Highway A': {'entity_id': 'highway-a',
                                      'entity_type': 'edge', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    assert 'qualified_access' not in rec.proposal.claims[0].flags
    assert store.review(rec.proposal_id, 'accepted', 'scripted-reviewer').effects[0]['status'] == 'open'
