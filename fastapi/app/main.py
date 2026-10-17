import json
import hashlib
import logging
import secrets
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select

from app.config import Settings
from app.db import Call, Database, Program, ReportLink
from app.matching import match_programs
from app.profile import call_id_of, extract_profile, structured_data, transcript_of
from app.results_email import delivery_summary, deliver_results, render as render_email, resume_interrupted
from app.results_sms import delivery_summary as sms_summary, deliver_results as deliver_sms, resume_interrupted as resume_sms
from app.vapi import fetch_call

log = logging.getLogger('willow')


def same_secret(given, expected):
    return bool(expected) and secrets.compare_digest((given or '').encode(), expected.encode())


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def process_call(database: Database, settings: Settings, call_id: str):
    """Post-call pipeline: profile -> (Vapi fetch if needed) -> retrieval + matching. Runs after the webhook is acknowledged."""
    with database.transaction() as db:
        call = db.get(Call, call_id)
        if call.status != 'received':
            return  # another delivery already took this call
        call.status = 'processing'
        payload = call.payload
    try:
        profile = extract_profile(payload)
        if profile.source == 'none':
            fetched = fetch_call(call_id, settings)
            if fetched:
                payload = {**payload, 'message': {**payload['message'], 'call': fetched}}
                profile = extract_profile(payload)
        with database.transaction() as db:
            programs = [p.data for p in db.scalars(select(Program))]
        matches = match_programs(profile, programs, date.today())
        status = 'needs_information' if profile.missing_core() else 'completed'
        error = None
    except Exception as exc:  # stored as a safe code; payload text never goes to logs
        log.exception('call_id=%s processing failed', call_id)
        profile, matches, status, error = None, [], 'failed', type(exc).__name__
    with database.transaction() as db:
        call = db.get(Call, call_id)
        call.payload = payload
        call.profile = profile.model_dump(mode='json') if profile else None
        call.matches, call.status, call.error = matches, status, error
    log.info('call_id=%s status=%s profile_source=%s matches=%d', call_id, status,
             profile.source if profile else '-', len(matches))
    try:
        deliver_results(database, settings, call_id)
    except Exception:  # an email problem must never undo a stored matching result
        log.exception('call_id=%s results email step failed', call_id)
    try:
        deliver_sms(database, settings, call_id)
    except Exception:
        log.exception('call_id=%s results SMS step failed', call_id)


def resume_work(database: Database, settings: Settings):
    """Background tasks die with the server. On startup, finish calls and emails that were cut off."""
    with database.transaction() as db:
        for call in db.scalars(select(Call).where(Call.status.in_(('received', 'processing')))):
            call.status = 'received'
        waiting = [c.call_id for c in db.scalars(select(Call).where(Call.status == 'received'))]
    for call_id in waiting:
        process_call(database, settings, call_id)
    resume_interrupted(database, settings)
    resume_sms(database, settings)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
    app = FastAPI(title='Willow matching API', version='0.3.0',
                  description='Matches farmers to USDA programs after a Willow call. Results are not eligibility decisions.')
    app.state.settings = settings
    app.state.db = database = Database(settings.database_url)
    database.sync_programs(Path(settings.programs_path))
    threading.Thread(target=resume_work, args=(database, settings), daemon=True).start()
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_methods=['GET'],
                       allow_headers=['X-Api-Key'])

    @app.middleware('http')
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default errors echo input, including personal data.
        return JSONResponse(status_code=422, content={'detail': [
            {'loc': list(error['loc']), 'type': error['type'], 'msg': 'Invalid value'} for error in exc.errors()]})

    # ponytail: one shared key for trusted callers (Vapi tool, our server). Farmer-facing reads need per-farmer sign-in.
    def require_api_key(x_api_key: str | None = Header(default=None)):
        if not settings.api_key:
            raise HTTPException(503, 'API key is not configured')
        if not same_secret(x_api_key, settings.api_key):
            raise HTTPException(401, 'Invalid API key')

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    @app.post('/webhooks/vapi')
    async def webhook(request: Request, background: BackgroundTasks,
                      authorization: str | None = Header(default=None),
                      x_vapi_secret: str | None = Header(default=None)) -> dict:
        if not settings.webhook_secret:
            raise HTTPException(503, 'Webhook authentication is not configured')
        if not (same_secret((authorization or '').removeprefix('Bearer '), settings.webhook_secret)
                or same_secret(x_vapi_secret, settings.webhook_secret)):
            raise HTTPException(401, 'Invalid webhook authentication')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 2_000_000:
                raise HTTPException(413, 'Payload too large')
        try:
            payload = json.loads(raw)
            message = payload['message']
            event_type = message.get('type')
        except (ValueError, UnicodeDecodeError, KeyError, TypeError, AttributeError):
            raise HTTPException(422, 'Invalid event envelope')
        if event_type != 'end-of-call-report':
            return {'status': 'ignored'}
        try:
            call_id = call_id_of(payload)
        except ValueError:
            raise HTTPException(422, 'Invalid end-of-call report')
        transcript = transcript_of(message)
        log.info('vapi event=%s call_id=%s transcript=%s chars=%d structured_output=%s', event_type, call_id,
                 bool(transcript), len(transcript), bool(structured_data(message)))
        with database.transaction() as db:
            existing = db.get(Call, call_id)
            if existing:
                return {'status': existing.status, 'call_id': call_id, 'duplicate': True}
            customer = (message.get('call') or {}).get('customer') or message.get('customer') or {}
            db.add(Call(call_id=call_id, phone=customer.get('number'), payload=payload))
        background.add_task(process_call, database, settings, call_id)
        return {'status': 'received', 'call_id': call_id}

    @app.get('/api/matches/{call_id}', dependencies=[Depends(require_api_key)])
    def get_matches(call_id: str) -> dict:
        with database.transaction() as db:
            call = db.get(Call, call_id)
            if not call:
                raise HTTPException(404, 'Call not found')
            email = delivery_summary(database, call_id)
            sms = sms_summary(database, call_id)
            profile = dict(call.profile or {}) or None
            if profile:
                profile.pop('email_consent_statement', None)  # consent evidence stays server-side
                profile.pop('sms_consent_statement', None)
            return {'call_id': call.call_id, 'status': call.status, 'error': call.error,
                    'received_at': iso(call.created_at), 'updated_at': iso(call.updated_at),
                    'profile': profile, 'matches': call.matches,
                    'email_delivery': email and {**email, 'sent_at': iso(email['sent_at']) if email['sent_at'] else None},
                    'sms_delivery': sms and {**sms, 'submitted_at': iso(sms['submitted_at']) if sms['submitted_at'] else None},
                    'disclaimer': 'Potential matches only. The agency decides eligibility.'}

    @app.get('/api/calls/{call_id}', dependencies=[Depends(require_api_key)])
    def get_call(call_id: str) -> dict:
        """Confirms Vapi's end-of-call report reached the backend and shows the structured output it carried."""
        with database.transaction() as db:
            call = db.get(Call, call_id)
            if not call:
                raise HTTPException(404, 'Call not received')
            message = call.payload.get('message', {})
            return {'call_id': call.call_id, 'received': True, 'status': call.status,
                    'received_at': iso(call.created_at), 'ended_reason': message.get('endedReason'),
                    'transcript_chars': len(transcript_of(message)),
                    'structured_output': structured_data(message), 'profile': call.profile}

    @app.get('/report/{token}', response_class=HTMLResponse)
    def get_private_report(token: str):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with database.transaction() as db:
            link = db.scalar(select(ReportLink).where(ReportLink.token_hash == digest))
            if not link or link.expires_at <= time.time():
                raise HTTPException(404, 'Report link not found')
            call = db.get(Call, link.call_id)
            if not call or call.status != 'completed':
                raise HTTPException(404, 'Report link not found')
            _, page = render_email(call.profile or {}, call.matches)
        return HTMLResponse(page, headers={'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'"})

    return app
