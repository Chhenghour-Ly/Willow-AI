import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import results_email
from app.config import Settings
from app.db import EmailDelivery
from app.main import create_app
from app.results_email import render, resume_interrupted


SECRET, KEY = 'x' * 32, 'k' * 32
CONSENT = {'deep_matching_requested': True, 'email_delivery_consent': True,
           'results_email': 'Carolina@Example.com',
           'email_consent_statement': 'Yes, please email me the results at carolina@example.com.'}


class Resend:
    """Stands in for Resend's POST /emails."""
    def __init__(self, status=200, error=None):
        self.status, self.error, self.sent = status, error, []

    def __call__(self, url, json, headers, timeout):
        self.sent.append({'url': url, 'body': json, 'headers': headers, 'timeout': timeout})
        if self.error:
            raise self.error
        body = {'id': 're_test_123'} if self.status < 400 else {'name': 'validation_error', 'message': 'domain not verified'}
        return httpx.Response(self.status, json=body, request=httpx.Request('POST', url))


def carolina(call_id='sim-carolina-0001', **result):
    payload = json.loads(Path('fixtures/carolina-end-of-call.json').read_text(encoding='utf-8'))
    payload['message']['call']['id'] = call_id
    next(iter(payload['message']['artifact']['structuredOutputs'].values()))['result'].update(result)
    return payload


@pytest.fixture
def make(tmp_path, monkeypatch):
    def build(resend=None, **extra):
        fake = resend if resend is not None else Resend()
        monkeypatch.setattr(results_email.httpx, 'post', fake)
        base = dict(database_url=f"sqlite:///{tmp_path / 'test.db'}", webhook_secret=SECRET,
                    api_key=KEY, email_delivery_enabled='true', resend_api_key='re_test',
                    farmbridge_from_email='results@farmbridge.test',
                    farmbridge_reply_to='help@farmbridge.test')
        return TestClient(create_app(Settings(**{**base, **extra})))
    return build


def deliver(client, payload):
    response = client.post('/webhooks/vapi', json=payload, headers={'X-Vapi-Secret': SECRET})
    assert response.status_code == 200, response.text
    response = client.get(f"/api/matches/{payload['message']['call']['id']}", headers={'X-Api-Key': KEY})
    assert response.status_code == 200, response.text
    return response.json()


def test_consented_results_send_one_personalized_email(make):
    resend = Resend()
    with make(resend) as client:
        body = deliver(client, carolina(**CONSENT))
        with client.app.state.db.transaction() as db:
            delivery = db.query(EmailDelivery).one()
            assert delivery.status == 'sent'
            assert delivery.consent_statement == CONSENT['email_consent_statement']
            assert delivery.provider_message_id == 're_test_123'
            assert delivery.provider_response == 'HTTP 200'
            assert delivery.sent_at is not None
    assert body['email_delivery']['status'] == 'sent'
    assert len(resend.sent) == 1
    request = resend.sent[0]
    assert request['url'] == 'https://api.resend.com/emails'
    assert request['headers'] == {'Authorization': 'Bearer re_test',
                                  'Idempotency-Key': 'farmbridge-results-sim-carolina-0001'}
    assert request['body']['from'] == 'results@farmbridge.test'
    assert request['body']['to'] == ['carolina@example.com']
    assert request['body']['reply_to'] == 'help@farmbridge.test'
    assert request['body']['subject'] == 'Your Willow Assistance Results'
    assert all('Environmental Quality Incentives Program' in request['body'][part] for part in ('text', 'html'))


@pytest.mark.parametrize('change,expected', [
    ({'email_delivery_consent': False}, 'not_requested'),
    ({'email_delivery_consent': 'unknown'}, 'not_requested'),
    ({'email_delivery_consent': None}, 'not_requested'),
    ({'deep_matching_requested': False}, 'not_requested'),
    ({'results_email': 'carolina at gmail'}, 'skipped'),
    ({'results_email': 'carolina@'}, 'skipped'),
    ({'results_email': 'unknown'}, 'skipped'),
])
def test_no_email_without_consent_and_valid_address(make, change, expected):
    resend = Resend()
    with make(resend) as client:
        body = deliver(client, carolina(**{**CONSENT, **change}))
    assert body['email_delivery']['status'] == expected
    assert resend.sent == []


@pytest.mark.parametrize('heard', ['rajivostner1@gmail.com', 'unknown'])
def test_override_address_replaces_heard_address_but_still_needs_consent(make, heard):
    resend = Resend()
    with make(resend, email_override_to='tester@example.com') as client:
        deliver(client, carolina(**{**CONSENT, 'results_email': heard}))
        deliver(client, carolina('no-consent', **{**CONSENT, 'email_delivery_consent': False}))
    assert [r['body']['to'] for r in resend.sent] == [['tester@example.com']]


def test_duplicate_webhook_sends_once(make):
    resend = Resend()
    with make(resend) as client:
        payload = carolina(**CONSENT)
        deliver(client, payload)
        deliver(client, payload)
        with client.app.state.db.transaction() as db:
            assert db.query(EmailDelivery).count() == 1
    assert len(resend.sent) == 1


def test_incomplete_matching_is_skipped():
    status, _ = results_email.decide(SimpleNamespace(status='failed', profile=CONSENT))
    assert status == 'skipped'


def test_missing_resend_credentials_fail_without_request(make):
    resend = Resend()
    with make(resend, resend_api_key='') as client:
        body = deliver(client, carolina(**CONSENT))
    assert body['email_delivery']['status'] == 'failed'
    assert resend.sent == []


@pytest.mark.parametrize('resend,expected', [
    (Resend(status=422), 'failed'),
    (Resend(status=503), 'uncertain'),
    (Resend(error=httpx.ReadTimeout('slow')), 'uncertain'),
])
def test_provider_failure_is_never_reported_as_sent_or_retried(make, resend, expected):
    with make(resend) as client:
        body = deliver(client, carolina(**CONSENT))
        deliver(client, carolina(**CONSENT))
        with client.app.state.db.transaction() as db:
            assert db.query(EmailDelivery).one().status == expected
    assert body['email_delivery']['status'] == expected
    assert len(resend.sent) == 1


def test_dry_run_stores_template_without_sending(make):
    resend = Resend()
    with make(resend, email_delivery_enabled='false') as client:
        body = deliver(client, carolina(**CONSENT))
        with client.app.state.db.transaction() as db:
            delivery = db.query(EmailDelivery).one()
            assert delivery.body_text and delivery.body_html
    assert body['email_delivery']['status'] == 'dry_run'
    assert resend.sent == []


def test_restart_sends_pending_and_never_resends_in_flight(make):
    resend = Resend()
    with make(resend) as client:
        deliver(client, carolina('pending-call', **CONSENT))
        deliver(client, carolina('sending-call', **CONSENT))
        with client.app.state.db.transaction() as db:
            db.query(EmailDelivery).filter_by(call_id='pending-call').one().status = 'pending'
            db.query(EmailDelivery).filter_by(call_id='sending-call').one().status = 'sending'
        resend.sent.clear()
        resume_interrupted(client.app.state.db, client.app.state.settings)
        with client.app.state.db.transaction() as db:
            assert db.query(EmailDelivery).filter_by(call_id='pending-call').one().status == 'sent'
            assert db.query(EmailDelivery).filter_by(call_id='sending-call').one().status == 'uncertain'
    assert len(resend.sent) == 1


def test_no_match_email_is_honest():
    text, _ = render({'farmer_name': None}, [])
    assert 'no' in text.lower()


def test_email_escapes_farmer_supplied_text():
    _, page = render({'farmer_name': '<script>x</script>', 'county': 'A & B'}, [])
    assert '<script>' not in page
    assert '&lt;script&gt;' in page


def test_resend_rejection_reason_is_recorded(make):
    resend = Resend(status=403)
    with make(resend) as client:
        deliver(client, carolina(**CONSENT))
        with client.app.state.db.transaction() as db:
            row = db.query(EmailDelivery).one()
    assert row.status == 'failed' and 'domain not verified' in row.provider_response
