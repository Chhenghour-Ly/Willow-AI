import json
from pathlib import Path

import pytest

from app.profile import extract_profile, structured_data, transcript_of


def load(name):
    return json.loads(Path(f'fixtures/{name}').read_text(encoding='utf-8'))


def test_carolina_profile_is_normalized():
    p = extract_profile(load('carolina-end-of-call.json'))
    assert (p.farmer_name, p.state, p.county) == ('Carolina Martinez', 'CA', 'Fresno County')
    assert p.crops == ['tomatoes', 'squash']
    assert p.needs == ['irrigation_upgrade', 'water_conservation', 'financing']
    assert (p.project_acres, p.total_farm_acres) == (15, 20)
    assert (p.total_project_cost_usd, p.assistance_needed_usd) == (24000, 20000)
    assert (p.land_control, p.project_status) == ('leased', 'not_started')
    assert p.funding_preference == 'prefer_nonrepayable_open_to_loan'
    assert p.irrigated_years_of_last_5 == 4
    assert p.source == 'structured_output' and p.missing_core() == []


def test_recorded_vapi_payload():
    """Sanitized real end-of-call-report: strings instead of arrays, 0 and 'unknown' for unheard values."""
    p = extract_profile(load('recorded-with-structured-outputs.json'))
    assert (p.farmer_name, p.state, p.county) == ('Brandon', 'CA', 'Fresno County')
    assert p.crops == ['tomatoes', 'squash'] and p.needs == ['irrigation_upgrade', 'financing']
    assert p.land_control == 'leased' and p.project_status == 'not_started'
    assert p.total_farm_acres is None and p.assistance_needed_usd is None  # Vapi sent 0
    assert p.phone == '+15555550199'


def test_recorded_call_without_structured_outputs_stays_empty():
    payload = load('recorded-no-structured-outputs.json')
    p = extract_profile(payload)
    assert p.source == 'none' and p.farmer_name is None and p.needs == []
    assert p.missing_core() == ['state', 'needs']
    assert 'tomatoes' in transcript_of(payload['message'])  # transcript kept, nothing guessed from it


def test_structured_output_on_call_object_from_vapi_api():
    so = load('carolina-end-of-call.json')['message']['artifact']['structuredOutputs']
    assert structured_data({'call': {'artifact': {'structuredOutputs': so}}})['state'] == 'California'


@pytest.mark.parametrize('field,raw,expected', [
    ('land_control', 'Owned', 'owned'), ('land_control', 'rent', None),
    ('project_status', 'in progress', 'in_progress'), ('funding_preference', 'unknown', None),
    ('needs', 'irrigation_upgrade, hot_tub', ['irrigation_upgrade']), ('total_farm_acres', 'about 40 acres', 40),
    ('assistance_needed_usd', '$1.2 million', 1_200_000), ('state', 'somewhere', None),
])
def test_field_cleanup(field, raw, expected):
    payload = {'message': {'call': {'id': 'c1'}, 'artifact': {'structuredOutputs': {'x': {'result': {field: raw}}}}}}
    assert getattr(extract_profile(payload), field) == expected


@pytest.mark.parametrize('payload', [{}, {'message': {'call': {}}}, {'message': {'call': {'id': ''}}}])
def test_missing_call_id_rejected(payload):
    with pytest.raises((ValueError, KeyError)):
        extract_profile(payload)
