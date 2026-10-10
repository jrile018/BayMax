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


def confirmation(record):
    c = record.proposal.claims[0]
    values = ({'category': c.label, 'quantity': c.quantity.value,
               'unit': c.unit.value, 'location': c.location.value,
               'urgency': c.urgency.value if c.urgency else None}
              if c.kind == 'need' else
              {'status': c.label, 'location': c.location.value,
               'scope': 'unqualified'})
    return {'claim_id': c.claim_id, 'kind': c.kind,
            'mapped_entity_id': 'pine' if c.kind == 'need' else 'highway-a',
            'confirmed_values': values, 'semantic_override_reason': None}


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
    assert store.review(rec.proposal_id, 'accepted', 'scripted-reviewer', expected_revision=1, confirmations=(confirmation(rec),)).effects[0]['status'] == 'open'


@pytest.mark.parametrize('text', [
    '10 bottles were delivered to Pine School, water is needed at Pine School.',
    'Water is needed at Pine School after 10 bottles were delivered.',
])
def test_completed_delivery_count_in_mixed_clause_cannot_become_current_need(text):
    report = Report('audit:borrowed-count:' + text, 'fictional', 10, text)
    raw = proposal(claim(text, kind='need', label='water', evidence=text,
                         location='Pine School', quantity=10, unit='bottles'))
    store = ReviewStore({'Pine School': {'entity_id': 'pine',
                                         'entity_type': 'node', 'source': 'fictional graph'}})
    with pytest.raises(ValidationError):
        store.submit(report, raw, 'scripted')


def test_explicit_current_request_count_survives_later_delivery_context():
    text = '10 bottles of water are needed at Pine School after 5 bottles were delivered.'
    report = Report('audit:current-count', 'fictional', 10, text)
    raw = proposal(claim(text, kind='need', label='water', evidence=text,
                         location='Pine School', quantity=10, unit='bottles'))
    store = ReviewStore({'Pine School': {'entity_id': 'pine',
                                         'entity_type': 'node', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    accepted = store.review(rec.proposal_id, 'accepted', 'scripted-reviewer',
                            expected_revision=1, confirmations=(confirmation(rec),))
    assert len(accepted.effects) == 1
    assert accepted.effects[0]['quantity'] == 10


@pytest.mark.parametrize('text', [
    'Highway A is open; bicycles only.',
    'Highway A is open. Only bicycles may cross there.',
])
def test_elliptic_same_road_restriction_blocks_unscoped_open(text):
    report = Report('audit:elliptic:' + text, 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence='Highway A is open', location='Highway A'))
    store = ReviewStore({'Highway A': {'entity_id': 'highway-a',
                                      'entity_type': 'edge', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    assert 'qualified_access' in rec.proposal.claims[0].flags
    accepted = store.review(rec.proposal_id, 'accepted', 'scripted-reviewer',
                            expected_revision=1)
    assert accepted.effects == ()


def test_other_road_semicolon_restriction_does_not_scope_first_road():
    text = 'Highway A is open; Highway B is open to bicycles only.'
    report = Report('audit:other-road-semicolon', 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence='Highway A is open', location='Highway A'))
    parsed = parse_proposal(report, raw, 'scripted')
    assert 'qualified_access' not in parsed.claims[0].flags


@pytest.mark.parametrize('text', [
    'Highway A is open. This road is open to bicycles only.',
    'Highway A is open. Only bicycles may cross.',
])
def test_unambiguous_following_road_restriction_blocks_open(text):
    report = Report('audit:continued-access:' + text, 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence='Highway A is open', location='Highway A'))
    store = ReviewStore({'Highway A': {'entity_id': 'highway-a',
                                      'entity_type': 'edge', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    assert 'qualified_access' in rec.proposal.claims[0].flags
    assert store.review(rec.proposal_id, 'accepted', 'scripted-reviewer',
                        expected_revision=1).effects == ()


@pytest.mark.parametrize('text', [
    "Water is needed at Pine School following yesterday's delivery of 10 bottles.",
    "Water is needed at Pine School despite yesterday's distribution of 10 bottles.",
    'Water is needed at Pine School following the arrival of 10 bottles.',
])
def test_prior_event_noun_count_does_not_size_current_request(text):
    report = Report('audit:past-noun:' + text, 'fictional', 10, text)
    raw = proposal(claim(text, kind='need', label='water', evidence=text,
                         location='Pine School', quantity=10, unit='bottles'))
    store = ReviewStore({'Pine School': {'entity_id': 'pine',
                                         'entity_type': 'node', 'source': 'fictional graph'}})
    with pytest.raises(ValidationError):
        store.submit(report, raw, 'scripted')


@pytest.mark.parametrize('text', [
    'Highway A is open. Only bicycles arriving from Highway B may cross it.',
    'Highway A is open. Trucks coming from Highway B may not use it.',
    'Highway A is open. Bicycles only.',
    'Highway A is open. Access is limited to bicycles.',
])
def test_adjacent_restriction_on_first_road_blocks_unscoped_open(text):
    report = Report('audit:restricted-a:' + text, 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence='Highway A is open', location='Highway A'))
    store = ReviewStore({'Highway A': {'entity_id': 'highway-a',
                                      'entity_type': 'edge', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    assert 'qualified_access' in rec.proposal.claims[0].flags
    assert store.review(rec.proposal_id, 'accepted', 'scripted-reviewer',
                        expected_revision=1).effects == ()


def test_semicolon_independent_vehicle_need_does_not_scope_open_road():
    text = 'Highway A is open; trucks need fuel.'
    report = Report('audit:independent-semicolon-need', 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence='Highway A is open', location='Highway A'))
    store = ReviewStore({'Highway A': {'entity_id': 'highway-a',
                                      'entity_type': 'edge', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    assert 'qualified_access' not in rec.proposal.claims[0].flags
    effects = store.review(rec.proposal_id, 'accepted', 'scripted-reviewer',
                           expected_revision=1, confirmations=(confirmation(rec),)).effects
    assert len(effects) == 1
    assert effects[0]['status'] == 'open'


def test_count_after_request_without_prior_event_remains_actionable():
    text = 'We need 10 bottles of water at Pine School.'
    report = Report('audit:need-count-after-verb', 'fictional', 10, text)
    raw = proposal(claim(text, kind='need', label='water', evidence=text,
                         location='Pine School', quantity=10, unit='bottles'))
    store = ReviewStore({'Pine School': {'entity_id': 'pine',
                                         'entity_type': 'node', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    effects = store.review(rec.proposal_id, 'accepted', 'scripted-reviewer',
                           expected_revision=1, confirmations=(confirmation(rec),)).effects
    assert len(effects) == 1 and effects[0]['quantity'] == 10


@pytest.mark.parametrize('separator', ['.', ';'])
def test_only_in_unrelated_fuel_need_does_not_restrict_road(separator):
    text = f'Highway A is open{separator} Only trucks need fuel for it.'
    report = Report('audit:only-fuel:' + separator, 'fictional', 10, text)
    raw = proposal(claim(text, kind='access', label='open',
                         evidence='Highway A is open', location='Highway A'))
    store = ReviewStore({'Highway A': {'entity_id': 'highway-a',
                                      'entity_type': 'edge', 'source': 'fictional graph'}})
    rec = store.submit(report, raw, 'scripted')
    assert 'qualified_access' not in rec.proposal.claims[0].flags
    effects = store.review(rec.proposal_id, 'accepted', 'scripted-reviewer',
                           expected_revision=1, confirmations=(confirmation(rec),)).effects
    assert len(effects) == 1 and effects[0]['status'] == 'open'
