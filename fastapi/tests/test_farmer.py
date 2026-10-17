import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app import results_email
from app.config import Settings
from app.db import Farmer
from app.main import create_app


SECRET = 'x' * 32
CONSENT = {'deep_matching_requested': True, 'email_delivery_consent': True, 'results_email': 'carolina@example.com'}


def carolina(call_id, phone='+15555550123'):
    payload = json.loads(Path('fixtures/carolina-end-of-call.json').read_text(encoding='utf-8'))
    payload['message']['call']['id'] = call_id
    payload['message']['call']['customer']['number'] = phone
    next(iter(payload['message']['artifact']['structuredOutputs'].values()))['result'].update(CONSENT)
    return payload


def test_origins_list_puts_email_link_first():
    settings = Settings(frontend_origin='https://willow-ai.vercel.app/, http://localhost:5173')
    assert settings.origins() == ['https://willow-ai.vercel.app', 'http://localhost:5173']


def test_farmer_code_opens_only_their_profile_and_saves_approvals(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(results_email.httpx, 'post', lambda url, json, headers, timeout: sent.append(json) or
                        httpx.Response(200, json={'id': 're_1'}, request=httpx.Request('POST', url)))
    settings = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", webhook_secret=SECRET,
                        email_delivery_enabled='true', resend_api_key='re', farmbridge_from_email='a@b.test',
                        frontend_origin='https://app.test')
    with TestClient(create_app(settings)) as client:
        for call_id, phone in (('call-a', '+15555550123'), ('call-b', '+15555550999')):
            assert client.post('/webhooks/vapi', json=carolina(call_id, phone), headers={'X-Vapi-Secret': SECRET}).status_code == 200
        with client.app.state.db.transaction() as db:
            code_a, code_b = (db.get(Farmer, p).login_code for p in ('+15555550123', '+15555550999'))
        assert code_a != code_b and len(code_a) == 6 and code_a.isdigit()
        assert f'Your Willow login code: {code_a}' in sent[0]['text'] and 'https://app.test/app' in sent[0]['text']

        me = client.get('/api/me', headers={'X-Farmer-Code': code_a}).json()
        assert me['call']['call_id'] == 'call-a' and [c['call_id'] for c in me['calls']] == ['call-a']
        assert 'email_consent_statement' not in me['call']['profile']

        program = me['call']['matches'][0]['program_id']
        a = {'X-Farmer-Code': code_a}
        assert client.post('/api/me/approvals', json={'call_id': 'call-a', 'program_id': program}, headers=a).json()['approved'] == [program]
        client.post('/api/me/details', json={'call_id': 'call-a', 'edits': {'county': 'Wake'}, 'confirmed': True}, headers=a)
        assert client.get('/api/me', headers=a).json()['state'] == {'approved': [program], 'edits': {'county': 'Wake'}, 'confirmed': True}

        # Another farmer's call, unknown fields and wrong codes are refused.
        assert client.post('/api/me/approvals', json={'call_id': 'call-b', 'program_id': program}, headers=a).status_code == 404
        assert client.post('/api/me/details', json={'call_id': 'call-a', 'edits': {'phone': 'x'}}, headers=a).status_code == 422
        wrong = f'{(int(code_a) + 1) % 10**6:06d}'
        wrong = wrong if wrong != code_b else f'{(int(code_a) + 2) % 10**6:06d}'
        assert client.get('/api/me', headers={'X-Farmer-Code': wrong}).status_code == 401
        assert client.get('/api/me').status_code == 401
        for _ in range(30):
            client.get('/api/me', headers={'X-Farmer-Code': 'nope'})
        assert client.get('/api/me', headers=a).status_code == 429
