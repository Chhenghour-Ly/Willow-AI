import json
from datetime import date
from pathlib import Path

from app.matching import match_programs
from app.profile import FarmerProfile, extract_profile

PROGRAMS = json.loads(Path('fixtures/programs.json').read_text(encoding='utf-8'))
TODAY = date(2026, 10, 17)


def carolina():
    return extract_profile(json.loads(Path('fixtures/carolina-end-of-call.json').read_text(encoding='utf-8')))


def run(profile, today=TODAY):
    ranked = match_programs(profile, PROGRAMS, today)
    return {m['program_id']: m for m in ranked}, ranked


def texts(items):
    return ' | '.join(i['text'] for i in items)


def test_carolina_both_programs_investigated_with_citations():
    by_id, ranked = run(carolina())
    assert [m['program_id'] for m in ranked] == ['eqip', 'fsa-operating-microloan']  # prefers non-repayable
    for m in ranked:
        assert m['fit_status'] == 'potential_fit'  # never "eligible"
        assert m['reasons'] and m['missing_requirements'] and m['official_source_urls'] and m['evidence']
        assert all(i['source_url'].startswith('https://') for i in m['missing_requirements'] if i['source_url'])
    eqip = by_id['eqip']
    assert 'irrigated 4 of the last 5 years' in texts(eqip['reasons'])
    assert 'lease covering the full EQIP contract term' in texts(eqip['missing_requirements'])
    assert eqip['application_deadline']['date'] == '2026-11-06'
    assert 'Fresno County' in eqip['next_action']
    microloan = by_id['fsa-operating-microloan']
    assert '$20,000 you need is within the $50,000' in texts(microloan['reasons'])
    assert 'Willow does not assess it' in texts(microloan['missing_requirements'])


def test_missing_profile_means_needs_information_not_ineligible():
    by_id, _ = run(FarmerProfile(call_id='c'))
    assert {m['fit_status'] for m in by_id.values()} == {'needs_information'}
    assert all(not m['obstacles'] for m in by_id.values())


def test_partial_profile_asks_for_what_is_missing():
    by_id, _ = run(FarmerProfile(call_id='c', state='CA', needs=['irrigation_upgrade']))
    assert by_id['eqip']['fit_status'] == 'potential_fit'
    assert 'Do you own or lease the land' in texts(by_id['eqip']['missing_requirements'])
    assert 'Have you started the project' in texts(by_id['eqip']['missing_requirements'])
    assert 'How much money do you need' in texts(by_id['fsa-operating-microloan']['missing_requirements'])


def test_stated_conflicts_become_unlikely():
    p = carolina().model_copy(update={'funding_preference': 'nonrepayable_only', 'project_status': 'completed'})
    by_id, _ = run(p)
    assert by_id['fsa-operating-microloan']['fit_status'] == 'unlikely_fit'
    assert by_id['eqip']['fit_status'] == 'unlikely_fit'


def test_loan_amount_over_cap_is_an_obstacle():
    by_id, _ = run(carolina().model_copy(update={'assistance_needed_usd': 80000}))
    assert 'above the $50,000 microloan limit' in texts(by_id['fsa-operating-microloan']['obstacles'])


def test_deadline_hidden_after_cutoff_and_outside_state():
    by_id, _ = run(carolina(), today=date(2026, 12, 1))
    assert by_id['eqip']['application_deadline'] is None
    by_id, _ = run(carolina().model_copy(update={'state': 'IA'}))
    assert by_id['eqip']['application_deadline'] is None
