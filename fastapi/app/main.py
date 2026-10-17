import copy
import hashlib
import json
import secrets
import time

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.adapters import allowed_recipient
from app.config import Settings
from app.db import (Activity, Approval, CallBinding, Case, Database, Document, Farmer, Job,
                    Notification, Report, ReviewToken, SessionToken, Submission)
from app.reports import missing, normalize_demo, tasks_for
from app.schemas import (CasePatch, CaseResponse, SessionResponse, SubmissionResponse,
                         TokenExchange, VersionRequest)
from app.security import digest


def current_report(db, case):
    return db.scalar(select(Report).where(Report.case_id == case.id, Report.version == case.draft_version))


def scoped_case(db, case_id, authorization):
    token = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    session = db.get(SessionToken, digest(token)) if token else None
    if not session or session.expires_at <= time.time():
        raise HTTPException(401, 'Invalid or expired session')
    if session.case_id != case_id:
        raise HTTPException(404, 'Case not found')
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, 'Case not found')
    return case


def resolve_attachments(db, case_id, references):
    resolved = []
    seen = set()
    for ref in references:
        key = (ref['document_id'], ref['version'])
        if key in seen:
            raise HTTPException(422, 'Duplicate attachment')
        seen.add(key)
        document = db.scalar(select(Document).where(Document.case_id == case_id,
                             Document.document_id == key[0], Document.version == key[1]))
        if not document or hashlib.sha256(document.content).hexdigest() != document.sha256:
            raise HTTPException(422, 'Attachment version unavailable')
        resolved.append({'document_id': document.document_id, 'version': document.version,
                         'name': document.name, 'sha256': document.sha256})
    return resolved


def case_response(db, case):
    report = current_report(db, case)
    body = report.body if report else {}
    approval = db.get(Approval, case.approval_id) if case.approval_id else None
    notification = db.scalar(select(Notification).where(Notification.case_id == case.id))
    submission = db.scalar(select(Submission).where(Submission.case_id == case.id))
    tasks = tasks_for(case.facts, body.get('attachments', []))
    if notification and notification.status in ('failed', 'uncertain'):
        tasks.append({'kind': 'notification', 'text': f'Review-link delivery {notification.status}; contact support.'})
    if submission and submission.status in ('failed', 'uncertain'):
        tasks.append({'kind': 'submission', 'text': f'Submission {submission.status}; operator reconciliation required.'})
    if case.processing_status == 'failed':
        tasks.append({'kind': 'processing', 'text': 'Report preparation failed; contact support.'})
    if body.get('draft_needs_review'):
        tasks.append({'kind': 'draft_review', 'text': 'Review the draft against corrected facts before approving.'})
    return CaseResponse(id=case.id, facts=case.facts, missing_information=missing(case.facts),
                        requirements=body.get('requirements', []), unresolved_questions=body.get('unresolved_questions', []),
                        rag_simulated=body.get('rag_simulated', True), draft_notice=body.get('draft_notice'),
                        recipient=body.get('recipient'), attachments=body.get('attachments', []),
                        draft_version=case.draft_version, approval_version=approval.version if approval else None,
                        processing_status=case.processing_status, submission=submission,
                        notification={'status': notification.status, 'simulated': notification.simulated,
                                      'provider_id': notification.provider_id} if notification else None, tasks=tasks)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    app = FastAPI(title='Crop Damage Notice Demo', version='0.1.0',
                  description='Farmer-reviewed damage notices. Does not complete insurance payout claims.')
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    database = app.state.db
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin],
                       allow_methods=['GET', 'PATCH', 'POST'], allow_headers=['Authorization', 'Content-Type'])

    @app.middleware('http')
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default errors echo input, including credentials and personal data.
        return JSONResponse(status_code=422, content={'detail': [
            {'loc': list(error['loc']), 'type': error['type'], 'msg': 'Invalid value'} for error in exc.errors()]})

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    @app.post('/webhooks/vapi', status_code=202)
    async def webhook(request: Request, authorization: str | None = Header(default=None)) -> dict:
        if not settings.webhook_secret:
            raise HTTPException(503, 'Webhook authentication is not configured')
        if not secrets.compare_digest((authorization or '').encode(), ('Bearer '+settings.webhook_secret).encode()):
            raise HTTPException(401, 'Invalid webhook authentication')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1_000_000:
                raise HTTPException(413, 'Payload too large')
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get('message'), dict):
                raise ValueError()
            event_type = payload['message'].get('type')
            if not isinstance(event_type, str):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(422, 'Invalid event envelope')
        if event_type != 'end-of-call-report':
            return {'status': 'ignored'}
        if not settings.demo_mode:
            raise HTTPException(503, 'Live Vapi parser blocked pending captured payload and authentication configuration')
        try:
            call_id, facts = normalize_demo(payload)
        except (KeyError, TypeError, ValueError, ValidationError):
            raise HTTPException(422, 'Invalid fictional demo payload')
        with database.transaction() as db:
            existing = db.scalar(select(Case).where(Case.call_id == call_id))
            if existing:
                return {'status': 'accepted', 'case_id': existing.id}
            binding = db.get(CallBinding, call_id)
            farmer = db.get(Farmer, binding.farmer_id) if binding else None
            if not farmer or not farmer.verified:
                raise HTTPException(403, 'Call is not linked to a verified account')
            case = Case(call_id=call_id, farmer_id=farmer.id, original_payload=payload, facts=facts)
            db.add(case)
            db.flush()
            db.add(Job(key=f'process:{case.id}', kind='process', case_id=case.id))
            db.add(Activity(case_id=case.id, kind='call_received'))
            return {'status': 'accepted', 'case_id': case.id}

    @app.post('/auth/exchange', response_model=SessionResponse)
    def exchange(body: TokenExchange):
        with database.transaction() as db:
            token = db.get(ReviewToken, digest(body.token))
            if not token or token.used or token.expires_at <= time.time():
                raise HTTPException(401, 'Invalid or expired review token')
            token.used = True
            session_token = secrets.token_urlsafe(32)
            db.add(SessionToken(token_hash=digest(session_token), case_id=token.case_id,
                                expires_at=time.time()+settings.session_ttl))
            db.add(Activity(case_id=token.case_id, kind='review_session_created'))
            return SessionResponse(session_token=session_token, case_id=token.case_id, expires_in=settings.session_ttl)

    @app.get('/cases/{case_id}', response_model=CaseResponse)
    def get_case(case_id: str, authorization: str | None = Header(default=None)):
        with database.read() as db:
            return case_response(db, scoped_case(db, case_id, authorization))

    @app.patch('/cases/{case_id}', response_model=CaseResponse)
    def patch_case(case_id: str, patch: CasePatch, authorization: str | None = Header(default=None)):
        with database.transaction() as db:
            case = scoped_case(db, case_id, authorization)
            if case.processing_status != 'ready' or case.draft_version != patch.version:
                raise HTTPException(409, 'Report is not ready or version is stale')
            if db.scalar(select(Submission).where(Submission.case_id == case_id)):
                raise HTTPException(409, 'A submitted case is locked; reconcile its submission first')
            report = current_report(db, case)
            body = copy.deepcopy(report.body)
            facts = copy.deepcopy(case.facts)
            if patch.facts is not None:
                for name, fact in patch.facts.items():
                    if fact.value == facts[name]['value'] and fact.confirmed == facts[name]['confirmed']:
                        continue
                    updated = fact.model_dump()
                    # Complete correction history remains in immutable report versions.
                    extracted_sources = [source for source in facts[name]['sources']
                                         if not source.startswith('farmer-correction:')]
                    updated['sources'] = extracted_sources + [f'farmer-correction:v{case.draft_version+1}']
                    facts[name] = updated
            if 'draft_notice' in patch.model_fields_set:
                if patch.draft_notice is None:
                    raise HTTPException(422, 'Draft cannot be null')
                body['draft_notice'] = patch.draft_notice
                body['draft_needs_review'] = False
            if 'recipient' in patch.model_fields_set:
                body['recipient'] = patch.recipient
            if patch.attachments is not None:
                body['attachments'] = resolve_attachments(db, case_id, [ref.model_dump() for ref in patch.attachments])
            if facts != case.facts:
                # A fact correction never overwrites a manually edited draft.
                body['unresolved_questions'] = ['Facts changed; verify requirements and reconcile the draft with corrections.']
                body['draft_needs_review'] = patch.draft_notice is None
                for requirement in body['requirements']:
                    requirement['applicability'] = 'unknown'
                    requirement['reviewed'] = False
            if facts != case.facts or body != report.body:
                case.facts = facts
                case.draft_version += 1
                case.approval_id = None
                body['facts'] = facts
                body['missing_information'] = missing(facts)
                body['tasks'] = tasks_for(facts, body['attachments'])
                db.add(Report(case_id=case_id, version=case.draft_version, body=body))
                db.add(Activity(case_id=case_id, kind='case_edited', detail={'version': case.draft_version}))
                db.flush()
            return case_response(db, case)

    @app.post('/cases/{case_id}/approve')
    def approve(case_id: str, body: VersionRequest, authorization: str | None = Header(default=None)) -> dict:
        with database.transaction() as db:
            case = scoped_case(db, case_id, authorization)
            if case.processing_status != 'ready' or case.draft_version != body.version:
                raise HTTPException(409, 'Report is not ready or version is stale')
            report = current_report(db, case)
            if report.body.get('draft_needs_review'):
                raise HTTPException(409, 'Reconcile and save the draft after fact corrections before approval')
            if not report.body.get('recipient') or not report.body.get('draft_notice'):
                raise HTTPException(422, 'Recipient and draft are required')
            if case.approval_id:
                return {'approval_id': case.approval_id, 'version': case.draft_version}
            attachments = resolve_attachments(db, case_id, report.body['attachments'])
            approval = Approval(case_id=case_id, version=case.draft_version,
                                snapshot={'draft_notice': report.body['draft_notice'],
                                          'recipient': report.body['recipient'], 'attachments': attachments})
            db.add(approval)
            db.flush()
            case.approval_id = approval.id
            db.add(Activity(case_id=case_id, kind='approved', detail={'version': case.draft_version}))
            return {'approval_id': approval.id, 'version': case.draft_version}

    @app.post('/cases/{case_id}/submit', response_model=SubmissionResponse)
    def submit(case_id: str, authorization: str | None = Header(default=None)):
        with database.transaction() as db:
            case = scoped_case(db, case_id, authorization)
            existing = db.scalar(select(Submission).where(Submission.case_id == case_id))
            if existing:
                return SubmissionResponse.model_validate(existing)
            approval = db.get(Approval, case.approval_id) if case.approval_id else None
            if not approval or approval.version != case.draft_version:
                raise HTTPException(409, 'Current approval required')
            if not allowed_recipient(approval.snapshot['recipient'], settings):
                raise HTTPException(422, 'Recipient is not in the server test allowlist')
            submission = Submission(case_id=case_id, approval_id=approval.id)
            db.add(submission)
            db.add(Job(key=f'submit:{case_id}', kind='submit', case_id=case_id))
            db.add(Activity(case_id=case_id, kind='submission_queued'))
            db.flush()
            return SubmissionResponse.model_validate(submission)

    @app.get('/cases/{case_id}/documents/{document_id}/{version}')
    def get_document(case_id: str, document_id: str, version: int, authorization: str | None = Header(default=None)):
        with database.read() as db:
            scoped_case(db, case_id, authorization)
            document = db.scalar(select(Document).where(Document.case_id == case_id,
                                 Document.document_id == document_id, Document.version == version))
            if not document:
                raise HTTPException(404, 'Document not found')
            return Response(document.content, media_type='application/octet-stream',
                            headers={'Content-Disposition': 'attachment'})

    return app
