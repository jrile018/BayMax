from copy import deepcopy

from evals.intake.run import load_cases, score_case


def test_oversized_but_valid_claim_quote_fails_reference_span_alignment():
    text = 'At Pine School, 10 bottles of water are needed.'
    need_start = text.index('10 bottles')
    location_start = text.index('Pine School')
    quantity_start = text.index('10')
    unit_start = text.index('bottles')
    gold = {
        'language': 'en', 'flags': [],
        'claims': [{
            'claim_id': 'n1', 'kind': 'need', 'label': 'water',
            'evidence': {'start': need_start, 'end': len(text) - 1,
                         'quote': text[need_start:-1]},
            'quantity': {'value': 10, 'evidence': {'start': quantity_start,
                                                   'end': quantity_start + 2, 'quote': '10'}},
            'unit': {'value': 'bottles', 'evidence': {'start': unit_start,
                                                   'end': unit_start + 7, 'quote': 'bottles'}},
            'urgency': None,
            'location': {'value': 'Pine School',
                         'evidence': {'start': location_start,
                                      'end': location_start + 11, 'quote': 'Pine School'}},
            'flags': [],
        }],
    }
    case = {'report_id': 'alignment:1', 'domain': 'audit',
            'language': 'en', 'text': text, 'gold': gold}
    predicted = deepcopy(gold)
    predicted['claims'][0]['evidence'] = {
        'start': 0, 'end': len(text), 'quote': text,
    }
    result = score_case(case, predicted, 'scripted')
    assert result['metrics']['valid_schema'] == {'numerator': 1, 'denominator': 1}
    assert result['metrics']['evidence_quote_support'] == {'numerator': 4, 'denominator': 4}
    assert result['metrics']['exact_report'] == {'numerator': 1, 'denominator': 1}
    assert result['metrics']['evidence_span_alignment'] == {'numerator': 3, 'denominator': 4}
    assert result['metrics']['evidence_aligned_report'] == {'numerator': 0, 'denominator': 1}


def test_audited_wf01_whole_report_quote_loses_evidence_credit():
    case = next(item for item in load_cases() if item['report_id'] == 'WF01')
    predicted = deepcopy(case['gold'])
    predicted['claims'][0]['evidence'] = {
        'start': 0, 'end': len(case['text']), 'quote': case['text'],
    }
    result = score_case(case, predicted, 'scripted')
    assert result['metrics']['evidence_span_alignment']['numerator'] == 0
    assert result['metrics']['evidence_aligned_report']['numerator'] == 0
