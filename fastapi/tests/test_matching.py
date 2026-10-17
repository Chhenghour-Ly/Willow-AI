import json
from datetime import date
from pathlib import Path

from app.matching import match_programs
from app.profile import FarmerProfile, extract_profile

PROGRAMS = json.loads(Path('fixtures/programs.json').read_text())
TODAY = date(2026, 10, 17)
RANK = {'likely': 0, 'possible': 1, 'not_eligible': 2}


def run(profile):
    ranked = match_programs(profile, PROGRAMS, TODAY)
    return {m.program_id: m for m in ranked}, ranked


def iowa_hail():
    return extract_profile(json.loads(Path('fixtures/sample-end-of-call.json').read_text()))


def test_iowa_hail_corn_top_matches():
    by_id, ranked = run(iowa_hail())
    assert ranked[0].status == 'likely'
    assert {'syn-iowa-recovery', 'syn-ecap'} <= {m.program_id for m in ranked[:3]}
    assert by_id['syn-crop-insurance-claim'].status == 'likely'
    assert by_id['syn-nebraska-drought'].status == 'not_eligible'


def test_results_ordered_by_status():
    _, ranked = run(iowa_hail())
    assert [RANK[m.status] for m in ranked] == sorted(RANK[m.status] for m in ranked)


def test_passed_deadline_blocks():
    by_id, _ = run(iowa_hail())
    m = by_id['syn-hail-replant']
    assert m.status == 'not_eligible'
    assert any('Deadline passed' in reason for reason in m.blocked)


def test_income_over_limit_blocks_with_reason():
    profile = iowa_hail().model_copy(update={'annual_income': 2_000_000})
    by_id, _ = run(profile)
    assert by_id['syn-ecap'].status == 'not_eligible'
    assert 'Income over the $900,000 limit' in by_id['syn-ecap'].blocked


def test_missing_facts_become_questions():
    by_id, _ = run(FarmerProfile(call_id='c', damage_type='hail'))
    m = by_id['syn-ecap']
    assert m.status == 'possible'
    assert 'About what percent of the crop was lost?' in m.unknown
    assert 'What is your yearly farm income?' in m.unknown
    assert m.explanation.startswith('Could fit')


def test_no_insurance_blocks_claim():
    by_id, _ = run(iowa_hail().model_copy(update={'has_crop_insurance': False}))
    assert 'Requires a crop insurance policy' in by_id['syn-crop-insurance-claim'].blocked


def test_crop_groups_match_specific_crops():
    profile = FarmerProfile(call_id='c', state='CA', crops=['apples'], damage_type='freeze', loss_percent=40,
                            annual_income=100000, total_acres=40)
    by_id, _ = run(profile)
    assert by_id['syn-freeze-fruit'].status == 'likely'
    assert by_id['syn-ecap'].status != 'not_eligible'


def test_every_match_marked_synthetic():
    _, ranked = run(iowa_hail())
    assert len(ranked) == len(PROGRAMS)
    assert all(m.synthetic for m in ranked)
