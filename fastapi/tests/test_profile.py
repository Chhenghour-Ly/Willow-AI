import json
from datetime import date
from pathlib import Path

import pytest

from app.profile import extract_profile

SAMPLE = json.loads(Path('fixtures/sample-end-of-call.json').read_text())


def with_data(data, call_id='c1'):
    return {'message': {'type': 'end-of-call-report', 'call': {'id': call_id}, 'analysis': {'structuredData': data}}}


def test_sample_payload_is_cleaned():
    p = extract_profile(SAMPLE)
    assert p.call_id == 'sample-call-0001'
    assert p.phone == '+15555550100'
    assert p.farmer_name == 'Dale Hansen'
    assert p.state == 'IA'
    assert p.crops == ['corn', 'soybeans']
    assert p.damage_type == 'hail'
    assert (p.acres_damaged, p.total_acres, p.loss_percent) == (120, 300, 60)
    assert p.annual_income == 180000
    assert p.has_crop_insurance is True
    assert p.is_organic is False
    assert p.years_farming == 22
    assert p.loss_date == date(2026, 10, 3)
    assert 'hail' in p.story.lower()


@pytest.mark.parametrize('raw,expected', [('ia', 'IA'), ('Nebraska', 'NE'), ('south dakota', 'SD'),
                                          ('somewhere', None), ('', None)])
def test_state(raw, expected):
    assert extract_profile(with_data({'state': raw})).state == expected


@pytest.mark.parametrize('raw,expected', [('180k', 180000), ('$1.2 million', 1200000), ('about 95', 95),
                                          ('a lot', None), (250000, 250000)])
def test_income(raw, expected):
    assert extract_profile(with_data({'annual_income': raw})).annual_income == expected


@pytest.mark.parametrize('raw,expected', [('yes', True), ('No', False), (True, True), ('not sure', None)])
def test_yes_no(raw, expected):
    assert extract_profile(with_data({'has_crop_insurance': raw})).has_crop_insurance is expected


@pytest.mark.parametrize('raw,expected', [('tornado', 'wind'), ('it flooded bad', 'flood'), ('late frost', 'freeze'),
                                          ('wildfire', 'fire'), ('too much rain', 'excess_moisture'), ('aliens', None)])
def test_damage_type(raw, expected):
    assert extract_profile(with_data({'damage_type': raw})).damage_type == expected


def test_crops_from_list_use_aliases():
    assert extract_profile(with_data({'crops': ['Soybean', 'Apple', 'cows']})).crops == ['soybeans', 'apples', 'cattle']


def test_bad_date_becomes_unknown():
    assert extract_profile(with_data({'loss_date': 'last Tuesday'})).loss_date is None


def test_missing_structured_data_gives_empty_profile():
    p = extract_profile({'message': {'type': 'end-of-call-report', 'call': {'id': 'c2'}}})
    assert p.call_id == 'c2' and p.state is None and p.crops == []


@pytest.mark.parametrize('payload', [{}, {'message': {'call': {}}}, {'message': {'call': {'id': ''}}}])
def test_missing_call_id_rejected(payload):
    with pytest.raises(ValueError):
        extract_profile(payload)
