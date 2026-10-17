import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import vapi
from app.config import Settings
from app.db import Call
from app.main import create_app

SECRET, KEY = 'x' * 32, 'k' * 32
AUTH = {'X-Vapi-Secret': SECRET}
READ = {'X-Api-Key': KEY}


def fixture(name):
    return json.loads(Path(f'fixtures/{name}').read_text(encoding='utf-8'))


@pytest.fixture
def make(tmp_path):
    def build(**extra):
        settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", webhook_secret=SECRET, api_key=KEY,
                            vapi_retry_delays='0,0', **extra)
        return TestClient(create_app(settings))
    return build


@pytest.fixture
def client(make):
    with make() as c:
        yield c


def test_webhook_auth(client):
    sample = fixture('carolina-end-of-call.json')
    assert client.post('/webhooks/vapi', json=sample).status_code == 401
    assert client.post('/webhooks/vapi', json=sample, headers={'X-Vapi-Secret': ''}).status_code == 401
    assert client.post('/webhooks/vapi', json=sample, headers={'Authorization': 'Bearer ' + SECRET}).status_code == 200


def test_unconfigured_secrets_fail_closed(tmp_path):
    with TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 't.db'}"))) as c:
        assert c.post('/webhooks/vapi', json=fixture('carolina-end-of-call.json'), headers=AUTH).status_code == 503
        assert c.get('/api/matches/x', headers=READ).status_code == 503


def test_non_end_of_call_events_ignored(client):
    r = client.post('/webhooks/vapi', json={'message': {'type': 'status-update', 'call': {'id': 'c9'}}}, headers=AUTH)
    assert r.json() == {'status': 'ignored'}
    assert client.get('/api/matches/c9', headers=READ).status_code == 404


def test_carolina_end_to_end(client):
    r = client.post('/webhooks/vapi', json=fixture('carolina-end-of-call.json'), headers=AUTH)
    assert r.json() == {'status': 'received', 'call_id': 'sim-carolina-0001'}
    body = client.get('/api/matches/sim-carolina-0001', headers=READ).json()
    assert body['status'] == 'completed'
    assert body['profile']['farmer_name'] == 'Carolina Martinez'
    assert [m['program_id'] for m in body['matches']] == ['eqip', 'fsa-operating-microloan']
    assert 'payload' not in body


def test_duplicate_is_idempotent(client):
    first = client.post('/webhooks/vapi', json=fixture('carolina-end-of-call.json'), headers=AUTH).json()
    second = client.post('/webhooks/vapi', json=fixture('carolina-end-of-call.json'), headers=AUTH).json()
    assert first['status'] == 'received'
    assert second == {'status': 'completed', 'call_id': 'sim-carolina-0001', 'duplicate': True}


def test_reads_require_api_key(client):
    client.post('/webhooks/vapi', json=fixture('carolina-end-of-call.json'), headers=AUTH)
    assert client.get('/api/matches/sim-carolina-0001').status_code == 401
    assert client.get('/api/matches/sim-carolina-0001', headers={'X-Api-Key': 'wrong'}).status_code == 401
    assert client.get('/api/calls/sim-carolina-0001').status_code == 401


def test_no_structured_outputs_and_no_vapi_key_needs_information(client):
    client.post('/webhooks/vapi', json=fixture('recorded-no-structured-outputs.json'), headers=AUTH)
    body = client.get('/api/matches/recorded-0f20', headers=READ).json()
    assert body['status'] == 'needs_information'
    assert {m['fit_status'] for m in body['matches']} == {'needs_information'}
    assert body['profile']['farmer_name'] is None  # nothing fabricated from the transcript
    calls = client.get('/api/calls/recorded-0f20', headers=READ).json()
    assert calls['transcript_chars'] > 0 and calls['structured_output'] == {}


def test_missing_structured_outputs_fetched_from_vapi(make, monkeypatch):
    so = fixture('carolina-end-of-call.json')['message']['artifact']['structuredOutputs']
    attempts = []

    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    def fake_get(url, headers, timeout):
        attempts.append(url)
        assert headers['Authorization'] == 'Bearer vapi-test'
        # Vapi is still analysing on the first attempt.
        return Response({'id': 'recorded-0f20', 'artifact': {'structuredOutputs': so if len(attempts) > 1 else {}}})

    monkeypatch.setattr(vapi.httpx, 'get', fake_get)
    with make(vapi_api_key='vapi-test') as c:
        c.post('/webhooks/vapi', json=fixture('recorded-no-structured-outputs.json'), headers=AUTH)
        body = c.get('/api/matches/recorded-0f20', headers=READ).json()
    assert len(attempts) == 2 and attempts[0].endswith('/call/recorded-0f20')
    assert body['status'] == 'completed' and body['profile']['farmer_name'] == 'Carolina Martinez'


def test_partial_information_call(client):
    posted = client.post('/webhooks/vapi', json=fixture('recorded-with-structured-outputs.json'), headers=AUTH).json()
    body = client.get(f"/api/matches/{posted['call_id']}", headers=READ).json()
    assert body['status'] == 'completed'
    microloan = next(m for m in body['matches'] if m['program_id'] == 'fsa-operating-microloan')
    assert any('How much money' in i['text'] for i in microloan['missing_requirements'])


def test_matches_before_processing_finishes(client):
    with client.app.state.db.transaction() as db:
        db.add(Call(call_id='in-flight', status='processing', payload={'message': {}}))
    body = client.get('/api/matches/in-flight', headers=READ).json()
    assert body['status'] == 'processing' and body['matches'] == [] and body['profile'] is None


@pytest.mark.parametrize('body', [b'not json', b'[]', b'{"message": {"type": "end-of-call-report", "call": {}}}'])
def test_bad_payload_422(client, body):
    r = client.post('/webhooks/vapi', content=body, headers={**AUTH, 'Content-Type': 'application/json'})
    assert r.status_code == 422
