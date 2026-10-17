import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SECRET = 'x' * 32
SAMPLE = json.loads(Path('fixtures/sample-end-of-call.json').read_text())
AUTH = {'Authorization': 'Bearer ' + SECRET}


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", webhook_secret=SECRET))
    with TestClient(app) as c:
        yield c


def test_unconfigured_secret_fails_closed(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 't.db'}"))
    with TestClient(app) as c:
        assert c.post('/webhooks/vapi', json=SAMPLE, headers=AUTH).status_code == 503


def test_wrong_secret_rejected(client):
    assert client.post('/webhooks/vapi', json=SAMPLE, headers={'Authorization': 'Bearer nope'}).status_code == 401
    assert client.post('/webhooks/vapi', json=SAMPLE).status_code == 401


def test_x_vapi_secret_header_accepted(client):
    assert client.post('/webhooks/vapi', json=SAMPLE, headers={'X-Vapi-Secret': SECRET}).status_code == 200


def test_other_events_ignored(client):
    r = client.post('/webhooks/vapi', json={'message': {'type': 'status-update', 'call': {'id': 'c9'}}}, headers=AUTH)
    assert r.json() == {'status': 'ignored'}
    assert client.get('/api/matches/c9').status_code == 404


def test_end_of_call_saves_profile_and_matches(client):
    r = client.post('/webhooks/vapi', json=SAMPLE, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()['call_id'] == 'sample-call-0001'
    body = client.get('/api/matches/sample-call-0001').json()
    assert body['profile']['state'] == 'IA'
    assert body['matches'][0]['status'] == 'likely'
    assert body['matches'][0]['synthetic'] is True
    assert 'payload' not in body


def test_replay_is_idempotent(client):
    first = client.post('/webhooks/vapi', json=SAMPLE, headers=AUTH).json()
    second = client.post('/webhooks/vapi', json=SAMPLE, headers=AUTH).json()
    assert first == second


def test_unknown_call_404(client):
    assert client.get('/api/matches/nope').status_code == 404


@pytest.mark.parametrize('body', [b'not json', b'[]', b'{"message": {"type": "end-of-call-report", "call": {}}}'])
def test_bad_payload_422(client, body):
    r = client.post('/webhooks/vapi', content=body, headers={**AUTH, 'Content-Type': 'application/json'})
    assert r.status_code == 422
