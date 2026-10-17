import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.config import Settings
from app.db import Case, Job, Notification, Report, Submission, SessionToken, Farmer, CallBinding
from app.main import create_app
from app.security import digest, issue_review_token
from app.worker import run_once


@pytest.fixture
def env(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", webhook_secret='x'*32)
    app = create_app(settings)
    with app.state.db.transaction() as db:
        db.add(Farmer(id='farmer-a', phone='+12025550101', verified=True, sms_consent=True))
        db.add(CallBinding(call_id='fictional-call-001', farmer_id='farmer-a'))
    with TestClient(app) as client:
        yield app, client


def receive(env):
    app, client = env
    payload = json.loads(Path('fixtures/fictional-call.json').read_text())
    response = client.post('/webhooks/vapi', json=payload, headers={'Authorization': 'Bearer '+'x'*32})
    assert response.status_code == 202, response.text
    return response.json()['case_id']


def ready(env):
    app, client = env
    case_id = receive(env)
    assert run_once(app.state.db, app.state.settings)
    with app.state.db.transaction() as db:
        token = issue_review_token(db, case_id, app.state.settings)
    response = client.post('/auth/exchange', json={'token': token})
    assert response.status_code == 200
    headers = {'Authorization': 'Bearer '+response.json()['session_token']}
    return case_id, headers


def approve(env, case_id, headers):
    client = env[1]
    version = client.get(f'/cases/{case_id}', headers=headers).json()['draft_version']
    response = client.post(f'/cases/{case_id}/approve', json={'version': version}, headers=headers)
    assert response.status_code == 200, response.text


def test_invalid_webhook_auth_and_unrelated_event(env):
    assert env[1].post('/webhooks/vapi', json={}).status_code == 401
    assert env[1].post('/webhooks/vapi', json={'message': {'type': 'status-update'}},
                       headers={'Authorization': 'Bearer '+'x'*32}).json()['status'] == 'ignored'


def test_repeated_events_one_case_report_notification(env):
    case_id = receive(env)
    assert receive(env) == case_id
    for _ in range(5):
        run_once(env[0].state.db, env[0].state.settings)
    assert receive(env) == case_id
    with env[0].state.db.read() as db:
        for model in (Case, Report, Notification):
            assert db.scalar(select(func.count()).select_from(model)) == 1


def test_scope_unknowns_and_token_single_use(env):
    case_id, headers = ready(env)
    client = env[1]
    report = client.get(f'/cases/{case_id}', headers=headers).json()
    assert report['facts']['policy_number']['value'] is None
    assert 'policy_number' in report['missing_information']
    assert report['facts']['crop']['confirmed'] is False
    assert report['tasks'][0]['kind'] == 'contact_agent'
    with env[0].state.db.transaction() as db:
        db.add(SessionToken(token_hash=digest('other-session'), case_id='another-case', expires_at=9999999999))
        token = issue_review_token(db, case_id, env[0].state.settings)
    other = {'Authorization': 'Bearer other-session'}
    for method, suffix, body in [('get', '', None), ('patch', '', {'version': 1}),
                                  ('post', '/approve', {'version': 1}), ('post', '/submit', None)]:
        args = {'headers': other}
        if body is not None:
            args['json'] = body
        assert getattr(client, method)(f'/cases/{case_id}{suffix}', **args).status_code == 404
    assert client.post('/auth/exchange', json={'token': token}).status_code == 200
    assert client.post('/auth/exchange', json={'token': token}).status_code == 401


def test_edit_invalidates_approval_stale_versions_and_preserves_payload(env):
    case_id, headers = ready(env)
    approve(env, case_id, headers)
    response = env[1].patch(f'/cases/{case_id}', headers=headers,
                            json={'version': 1, 'draft_notice': 'Corrected farmer damage notice.'})
    assert response.status_code == 200, response.text
    assert response.json()['draft_version'] == 2
    assert response.json()['approval_version'] is None
    assert env[1].post(f'/cases/{case_id}/approve', headers=headers, json={'version': 1}).status_code == 409
    assert env[1].post(f'/cases/{case_id}/submit', headers=headers).status_code == 409
    with env[0].state.db.read() as db:
        assert db.get(Case, case_id).original_payload['message']['call']['id'] == 'fictional-call-001'


def test_unapproved_and_duplicate_submission(env):
    case_id, headers = ready(env)
    url = f'/cases/{case_id}/submit'
    assert env[1].post(url, headers=headers).status_code == 409
    approve(env, case_id, headers)
    first = env[1].post(url, headers=headers)
    second = env[1].post(url, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()['id'] == second.json()['id']
    for _ in range(4):
        run_once(env[0].state.db, env[0].state.settings)
    result = env[1].post(url, headers=headers).json()
    assert result['status'] == 'sent'
    assert result['simulated'] is True
    assert result['acknowledged'] is False
    with env[0].state.db.read() as db:
        assert db.scalar(select(func.count()).select_from(Submission)) == 1


@pytest.mark.parametrize('outcome', ['failed', 'uncertain'])
def test_send_failures_not_success(env, monkeypatch, outcome):
    from app.adapters import DeliveryResult
    case_id, headers = ready(env)
    approve(env, case_id, headers)
    env[1].post(f'/cases/{case_id}/submit', headers=headers)
    monkeypatch.setattr('app.worker.send_email', lambda *args: DeliveryResult(status=outcome, error='test'))
    for _ in range(4):
        run_once(env[0].state.db, env[0].state.settings)
    assert env[1].post(f'/cases/{case_id}/submit', headers=headers).json()['status'] == outcome


def test_pending_jobs_survive_restart(env):
    case_id = receive(env)
    restarted = create_app(env[0].state.settings)
    assert run_once(restarted.state.db, restarted.state.settings)
    with restarted.state.db.read() as db:
        assert db.get(Case, case_id).processing_status == 'ready'


def test_allowlist_cannot_be_bypassed(env):
    case_id, headers = ready(env)
    response = env[1].patch(f'/cases/{case_id}', headers=headers,
                            json={'version': 1, 'recipient': 'attacker@example.net'})
    assert response.status_code == 200
    approve(env, case_id, headers)
    assert env[1].post(f'/cases/{case_id}/submit', headers=headers).status_code == 422


def test_live_vapi_is_blocked_without_real_sample(env):
    env[0].state.settings.demo_mode = False
    response = env[1].post('/webhooks/vapi', headers={'Authorization': 'Bearer '+'x'*32},
                           json=json.loads(Path('fixtures/fictional-call.json').read_text()))
    assert response.status_code == 503


def test_unbound_call_is_rejected_even_with_caller_identity(env):
    payload = json.loads(Path('fixtures/fictional-call.json').read_text())
    payload['message']['call']['id'] = 'unbound-call'
    payload['message']['call']['customer'] = {'number': '+12025550101'}
    response = env[1].post('/webhooks/vapi', json=payload, headers={'Authorization': 'Bearer '+'x'*32})
    assert response.status_code == 403


def test_expired_credentials_and_no_side_effects_from_get(env):
    from app.db import ReviewToken, Approval
    case_id, headers = ready(env)
    with env[0].state.db.transaction() as db:
        token = issue_review_token(db, case_id, env[0].state.settings)
        db.flush()
        db.get(ReviewToken, digest(token)).expires_at = 0
    assert env[1].post('/auth/exchange', json={'token': token}).status_code == 401
    for _ in range(2):
        assert env[1].get(f'/cases/{case_id}', headers=headers).status_code == 200
    with env[0].state.db.transaction() as db:
        assert db.scalar(select(func.count()).select_from(Approval)) == 0
        assert db.scalar(select(func.count()).select_from(Submission)) == 0
        session = db.get(SessionToken, digest(headers['Authorization'][7:]))
        session.expires_at = 0
    assert env[1].get(f'/cases/{case_id}', headers=headers).status_code == 401


def test_crashed_send_becomes_uncertain_and_never_resends(env, monkeypatch):
    case_id, headers = ready(env)
    approve(env, case_id, headers)
    env[1].post(f'/cases/{case_id}/submit', headers=headers)
    with env[0].state.db.transaction() as db:
        job = db.scalar(select(Job).where(Job.key == f'submit:{case_id}'))
        job.status = 'running'
        job.lease_until = 0
        job.attempts = 1
        db.scalar(select(Submission).where(Submission.case_id == case_id)).status = 'sending'
    calls = []
    monkeypatch.setattr('app.worker.send_email', lambda *args: calls.append(args))
    restarted = create_app(env[0].state.settings)
    for _ in range(4):
        run_once(restarted.state.db, restarted.state.settings)
    response = env[1].post(f'/cases/{case_id}/submit', headers=headers)
    assert response.json()['status'] == 'uncertain'
    assert calls == []


def test_concurrent_submit_queues_once(env):
    from concurrent.futures import ThreadPoolExecutor
    case_id, headers = ready(env)
    approve(env, case_id, headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: env[1].post(f'/cases/{case_id}/submit', headers=headers), range(2)))
    assert [result.status_code for result in results] == [200, 200]
    assert results[0].json()['id'] == results[1].json()['id']
    with env[0].state.db.read() as db:
        assert db.scalar(select(func.count()).select_from(Job).where(Job.key == f'submit:{case_id}')) == 1


def test_concurrent_exchange_is_single_use(env):
    from concurrent.futures import ThreadPoolExecutor
    case_id = receive(env)
    with env[0].state.db.transaction() as db:
        token = issue_review_token(db, case_id, env[0].state.settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: env[1].post('/auth/exchange', json={'token': token}), range(2)))
    assert sorted(response.status_code for response in results) == [200, 401]


def test_no_sms_without_consent(env, monkeypatch):
    receive(env)
    with env[0].state.db.transaction() as db:
        db.get(Farmer, 'farmer-a').sms_consent = False
    calls = []
    monkeypatch.setattr('app.worker.send_sms', lambda *args: calls.append(args))
    for _ in range(4):
        run_once(env[0].state.db, env[0].state.settings)
    assert calls == []
    with env[0].state.db.read() as db:
        assert db.scalar(select(Notification)).status == 'failed'


def test_allowlist_is_rechecked_at_dispatch(env, monkeypatch):
    case_id, headers = ready(env)
    approve(env, case_id, headers)
    env[1].post(f'/cases/{case_id}/submit', headers=headers)
    env[0].state.settings.test_recipients = ('different@example.test',)
    for _ in range(4):
        run_once(env[0].state.db, env[0].state.settings)
    assert env[1].post(f'/cases/{case_id}/submit', headers=headers).json()['status'] == 'failed'


def test_documents_private_and_approved_bytes_are_exact(env, monkeypatch):
    import hashlib
    from app.db import Document, Approval
    from app.adapters import DeliveryResult
    case_id, headers = ready(env)
    content = b'Fictional crop damage evidence'
    with env[0].state.db.transaction() as db:
        db.add(Document(case_id=case_id, document_id='evidence', version=1, name='evidence.txt',
                        content=content, sha256=hashlib.sha256(content).hexdigest()))
    url = f'/cases/{case_id}/documents/evidence/1'
    assert env[1].get(url).status_code == 401
    assert env[1].get(url, headers=headers).content == content
    approve(env, case_id, headers)
    response = env[1].patch(f'/cases/{case_id}', headers=headers,
                            json={'version': 1, 'attachments': [{'document_id': 'evidence', 'version': 1}]})
    assert response.status_code == 200
    assert response.json()['approval_version'] is None
    approve(env, case_id, headers)
    with env[0].state.db.read() as db:
        approval = db.get(Approval, db.get(Case, case_id).approval_id)
        snapshot = approval.snapshot
        assert snapshot['attachments'][0]['sha256'] == hashlib.sha256(content).hexdigest()
    seen = []
    def capture(approved, documents, settings, submission_id):
        seen.append((approved, documents))
        return DeliveryResult('sent', 'test-message', simulated=True)
    monkeypatch.setattr('app.worker.send_email', capture)
    env[1].post(f'/cases/{case_id}/submit', headers=headers)
    for _ in range(4):
        run_once(env[0].state.db, env[0].state.settings)
    assert seen[0][0] == snapshot
    assert seen[0][1][0]['content'] == content


def test_fact_corrections_preserve_provenance_and_draft(env):
    case_id, headers = ready(env)
    client = env[1]
    before = client.get(f'/cases/{case_id}', headers=headers).json()
    response = client.patch(f'/cases/{case_id}', headers=headers, json={
        'version': 1, 'facts': {'crop': {'value': 'soybeans', 'confirmed': True},
                               'policy_number': {'value': 'FICTIONAL-123', 'confirmed': True}}})
    after = response.json()
    assert response.status_code == 200
    assert after['facts']['crop']['value'] == 'soybeans'
    assert after['facts']['crop']['sources'][0] == before['facts']['crop']['sources'][0]
    assert 'policy_number' not in after['missing_information']
    assert after['draft_notice'] == before['draft_notice']
    receive(env)
    assert client.get(f'/cases/{case_id}', headers=headers).json()['facts']['crop']['value'] == 'soybeans'
    assert client.post(f'/cases/{case_id}/approve', headers=headers, json={'version': 2}).status_code == 409
    reviewed = client.patch(f'/cases/{case_id}', headers=headers,
                            json={'version': 2, 'draft_notice': 'Reviewed correction: soybeans; FICTIONAL-123.'})
    assert reviewed.status_code == 200
    approve(env, case_id, headers)


def test_processing_retries_are_bounded(env, monkeypatch):
    case_id = receive(env)
    def unavailable(*args):
        raise TimeoutError('sensitive provider body must not be stored')
    monkeypatch.setattr('app.worker.retrieve_requirements', unavailable)
    for _ in range(3):
        run_once(env[0].state.db, env[0].state.settings)
        with env[0].state.db.transaction() as db:
            db.scalar(select(Job).where(Job.kind == 'process')).available_at = 0
    with env[0].state.db.read() as db:
        job = db.scalar(select(Job).where(Job.kind == 'process'))
        assert job.status == 'failed' and job.attempts == 3
        assert 'sensitive' not in job.error
        assert db.get(Case, case_id).processing_status == 'failed'


@pytest.mark.parametrize('kind', ['notify', 'submit'])
def test_expired_claim_cannot_dispatch_after_recovery(env, monkeypatch, kind):
    from contextlib import contextmanager
    from app.worker import recover_expired
    case_id, headers = ready(env)
    database = env[0].state.db
    if kind == 'submit':
        run_once(database, env[0].state.settings)
        approve(env, case_id, headers)
        env[1].post(f'/cases/{case_id}/submit', headers=headers)
    original_transaction = database.transaction
    count = 0
    @contextmanager
    def recover_before_preparation():
        nonlocal count
        count += 1
        if count == 2:
            with original_transaction() as db:
                job = db.scalar(select(Job).where(Job.key == f'{kind}:{case_id}'))
                job.lease_until = 0
                db.flush()
                recover_expired(db)
        with original_transaction() as db:
            yield db
    calls = []
    monkeypatch.setattr(database, 'transaction', recover_before_preparation)
    monkeypatch.setattr('app.worker.send_email', lambda *args: calls.append(args))
    monkeypatch.setattr('app.worker.send_sms', lambda *args: calls.append(args))
    run_once(database, env[0].state.settings)
    assert calls == []
    with database.read() as db:
        model = Submission if kind == 'submit' else Notification
        assert db.scalar(select(model).where(model.case_id == case_id)).status == 'uncertain'


def test_many_corrections_preserve_history_without_source_overflow(env):
    case_id, headers = ready(env)
    for version in range(1, 26):
        response = env[1].patch(f'/cases/{case_id}', headers=headers, json={
            'version': version, 'facts': {'crop': {'value': f'fictional-crop-{version}', 'confirmed': True}}})
        assert response.status_code == 200, response.text
        assert response.json()['draft_version'] == version+1
        assert len(response.json()['facts']['crop']['sources']) == 2
        assert response.json()['facts']['crop']['sources'][0].startswith('call:')
    with env[0].state.db.read() as db:
        assert db.scalar(select(func.count()).select_from(Report).where(Report.case_id == case_id)) == 26
        first = db.scalar(select(Report).where(Report.case_id == case_id, Report.version == 1))
        assert first.body['facts']['crop']['value'] == 'corn'
        previous = db.scalar(select(Report).where(Report.case_id == case_id, Report.version == 25))
        assert previous.body['facts']['crop']['value'] == 'fictional-crop-24'
