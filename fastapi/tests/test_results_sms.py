import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import results_sms
from app.config import Settings
from app.db import ReportLink, SmsDelivery
from app.main import create_app
from app.results_sms import resume_interrupted


SECRET, KEY = 'x' * 32, 'k' * 32
CONSENT = {'deep_matching_requested': True, 'sms_delivery_consent': True,
           'sms_results_phone': '+15555550123',
           'sms_consent_statement': 'Yes, text the results to this number.'}


class Twilio:
    def __init__(self, status=201, error=None):
        self.status, self.error, self.sent = status, error, []

    def __call__(self, url, data, auth, timeout):
        self.sent.append({'url': url, 'data': dict(data), 'auth': auth})
        if self.error:
            raise self.error
        return httpx.Response(self.status, json={'sid': 'SM123', 'status': 'queued'},
                              request=httpx.Request('POST', url))


def carolina(call_id='sms-carolina-0001', **result):
    payload = json.loads(Path('fixtures/carolina-end-of-call.json').read_text(encoding='utf-8'))
    payload['message']['call']['id'] = call_id
    next(iter(payload['message']['artifact']['structuredOutputs'].values()))['result'].update(result)
    return payload


@pytest.fixture
def make(tmp_path, monkeypatch):
    def build(twilio=None, **extra):
        fake = twilio if twilio is not None else Twilio()
        monkeypatch.setattr(results_sms.httpx, 'post', fake)
        base = dict(database_url=f"sqlite:///{tmp_path / 'test.db'}", webhook_secret=SECRET, api_key=KEY,
                    sms_delivery_enabled='true', twilio_account_sid='AC123', twilio_auth_token='token',
                    twilio_from_number='+15555550111', report_base_url='https://example.test')
        return TestClient(create_app(Settings(**{**base, **extra})))
    return build


def deliver(client, payload):
    r = client.post('/webhooks/vapi', json=payload, headers={'X-Vapi-Secret': SECRET})
    assert r.status_code == 200
    r = client.get(f"/api/matches/{payload['message']['call']['id']}", headers={'X-Api-Key': KEY})
    assert r.status_code == 200
    return r.json()


def test_explicit_sms_consent_submits_one_short_summary(make):
    twilio = Twilio()
    with make(twilio) as c:
        body = deliver(c, carolina(**CONSENT))
        with c.app.state.db.transaction() as db:
            row = db.query(SmsDelivery).one()
            stored = (row.status, row.provider_message_id, row.consent_statement, row.submitted_at)
    assert body['sms_delivery']['status'] == 'submitted'
    assert body['sms_delivery']['submitted_at']
    assert 'sms_consent_statement' not in body['profile']
    assert stored[0:3] == ('submitted', 'SM123', CONSENT['sms_consent_statement'])
    assert stored[3]
    assert len(twilio.sent) == 1
    request = twilio.sent[0]
    assert request['url'].endswith('/Accounts/AC123/Messages.json')
    assert request['auth'] == ('AC123', 'token')
    assert request['data']['From'] == '+15555550111'
    assert request['data']['To'] == '+15555550123'
    assert 'EQIP' in request['data']['Body'] and 'FSA microloan' in request['data']['Body']
    assert 'USDA decides eligibility' in request['data']['Body']
    assert 'https://example.test/report/' in request['data']['Body']
    assert len(results_sms.render(body['matches'],
                                  'https://timing-acronym-emission.ngrok-free.dev/report/' + 'x' * 24)) <= 160
    assert body['email_delivery']['status'] == 'not_requested'


def test_private_report_link_shows_real_results_and_expires(make):
    with make() as c:
        deliver(c, carolina(**CONSENT))
        with c.app.state.db.transaction() as db:
            sms = db.query(SmsDelivery).one()
            link = db.query(ReportLink).one()
            token = re.search(r'/report/([A-Za-z0-9_-]+)', sms.body_text).group(1)
            assert link.token_hash != token
        response = c.get(f'/report/{token}')
        assert response.status_code == 200
        assert 'Environmental Quality Incentives Program' in response.text
        assert 'FSA Operating Microloan' in response.text
        assert c.get('/report/not-a-token').status_code == 404
        with c.app.state.db.transaction() as db:
            db.query(ReportLink).one().expires_at = 0
        assert c.get(f'/report/{token}').status_code == 404


def test_no_public_report_url_sends_nothing(make):
    twilio = Twilio()
    with make(twilio, report_base_url='') as c:
        body = deliver(c, carolina(**CONSENT))
    assert body['sms_delivery']['status'] == 'skipped'
    assert twilio.sent == []


@pytest.mark.parametrize('change,expected', [
    ({'sms_delivery_consent': False}, 'not_requested'),
    ({'sms_delivery_consent': 'unknown'}, 'not_requested'),
    ({'deep_matching_requested': False}, 'not_requested'),
    ({'sms_consent_statement': 'unknown'}, 'skipped'),
    ({'sms_results_phone': '5555550123'}, 'skipped'),
    ({'sms_results_phone': 'unknown'}, 'skipped'),
])
def test_no_sms_without_explicit_consent_and_confirmed_number(make, change, expected):
    twilio = Twilio()
    with make(twilio) as c:
        body = deliver(c, carolina(**{**CONSENT, **change}))
    assert body['sms_delivery']['status'] == expected
    assert twilio.sent == []


def test_duplicate_webhook_never_sends_twice(make):
    twilio = Twilio()
    with make(twilio) as c:
        deliver(c, carolina(**CONSENT))
        deliver(c, carolina(**CONSENT))
        with c.app.state.db.transaction() as db:
            assert db.query(SmsDelivery).count() == 1
    assert len(twilio.sent) == 1


def test_sms_and_email_send_independently_when_both_consented(make):
    sent = []

    def post(url, **kwargs):
        sent.append(url)
        if url.endswith('/emails'):
            return httpx.Response(200, json={'id': 're_test_123'}, request=httpx.Request('POST', url))
        return httpx.Response(201, json={'sid': 'SM123', 'status': 'queued'},
                              request=httpx.Request('POST', url))

    with make(post, email_delivery_enabled='true', resend_api_key='re_test',
              farmbridge_from_email='results@farmbridge.test') as c:
        body = deliver(c, carolina(**CONSENT, email_delivery_consent=True,
                                   results_email='carolina@example.com'))
    assert body['email_delivery']['status'] == 'sent'
    assert body['sms_delivery']['status'] == 'submitted'
    assert len(sent) == 2


def test_incomplete_matching_sends_nothing(make):
    twilio = Twilio()
    with make(twilio) as c:
        body = deliver(c, carolina(**CONSENT, state='unknown', needs=[]))
    assert body['status'] == 'needs_information'
    assert body['sms_delivery']['status'] == 'skipped'
    assert twilio.sent == []


def test_dry_run_stores_message_without_sending(make):
    twilio = Twilio()
    with make(twilio, sms_delivery_enabled='false') as c:
        body = deliver(c, carolina(**CONSENT))
        with c.app.state.db.transaction() as db:
            assert 'EQIP' in db.query(SmsDelivery).one().body_text
    assert body['sms_delivery']['status'] == 'dry_run'
    assert twilio.sent == []


@pytest.mark.parametrize('twilio,expected', [
    (Twilio(status=422), 'failed'),
    (Twilio(status=503), 'uncertain'),
    (Twilio(error=httpx.ReadTimeout('slow')), 'uncertain'),
])
def test_provider_error_is_not_reported_as_sent(make, twilio, expected):
    with make(twilio) as c:
        body = deliver(c, carolina(**CONSENT))
        deliver(c, carolina(**CONSENT))
    assert body['sms_delivery']['status'] == expected
    assert body['sms_delivery']['submitted_at'] is None
    assert len(twilio.sent) == 1


def test_no_clear_match_text_is_honest():
    text = results_sms.render([])
    assert 'did not find a clear match' in text
    assert 'eligible' not in text.lower()


def test_restart_sends_pending_once_and_marks_in_flight_uncertain(make):
    twilio = Twilio()
    with make(twilio) as c:
        with c.app.state.db.transaction() as db:
            db.add(SmsDelivery(call_id='pending', recipient_phone='+15555550123', status='pending',
                               body_text='FarmBridge test'))
            db.add(SmsDelivery(call_id='sending', recipient_phone='+15555550124', status='sending',
                               body_text='FarmBridge test'))
        assert resume_interrupted(c.app.state.db, c.app.state.settings) == ['submitted']
        with c.app.state.db.transaction() as db:
            statuses = {r.call_id: r.status for r in db.query(SmsDelivery)}
    assert statuses == {'pending': 'submitted', 'sending': 'uncertain'}
    assert len(twilio.sent) == 1
