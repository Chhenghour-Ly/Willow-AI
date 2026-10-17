import json
import secrets
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.config import Settings
from app.db import Call, Database, Program
from app.matching import match_programs
from app.profile import extract_profile


def authorized(settings, authorization, vapi_secret):
    expected = settings.webhook_secret.encode()
    bearer = (authorization or '').removeprefix('Bearer ').encode()
    return secrets.compare_digest(bearer, expected) or secrets.compare_digest((vapi_secret or '').encode(), expected)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    app = FastAPI(title='Willow matching API', version='0.2.0',
                  description='Matches farmers to recovery programs after a Willow call. Program data is synthetic.')
    app.state.settings = settings
    app.state.db = database = Database(settings.database_url)
    database.sync_programs(Path(settings.programs_path))
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_methods=['GET'])

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

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    @app.post('/webhooks/vapi')
    async def webhook(request: Request, authorization: str | None = Header(default=None),
                      x_vapi_secret: str | None = Header(default=None)) -> dict:
        if not settings.webhook_secret:
            raise HTTPException(503, 'Webhook authentication is not configured')
        if not authorized(settings, authorization, x_vapi_secret):
            raise HTTPException(401, 'Invalid webhook authentication')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1_000_000:
                raise HTTPException(413, 'Payload too large')
        try:
            payload = json.loads(raw)
            message = payload['message']
            if message.get('type') != 'end-of-call-report':
                return {'status': 'ignored'}
            profile = extract_profile(payload)
        except (ValueError, UnicodeDecodeError, KeyError, TypeError, AttributeError):
            raise HTTPException(422, 'Invalid end-of-call report')
        with database.transaction() as db:
            existing = db.get(Call, profile.call_id)
            if existing:
                return {'status': 'accepted', 'call_id': existing.call_id, 'matches': len(existing.matches)}
            programs = [p.data for p in db.scalars(select(Program))]
            matches = [m.to_dict() for m in match_programs(profile, programs, date.today())]
            db.add(Call(call_id=profile.call_id, phone=profile.phone, payload=payload,
                        profile=profile.model_dump(mode='json'), matches=matches))
        return {'status': 'accepted', 'call_id': profile.call_id, 'matches': len(matches)}

    # ponytail: anyone holding the call id can read the results; add farmer auth before real users.
    @app.get('/api/matches/{call_id}')
    def get_matches(call_id: str) -> dict:
        with database.transaction() as db:
            call = db.get(Call, call_id)
            if not call:
                raise HTTPException(404, 'Call not found')
            return {'call_id': call.call_id, 'created_at': call.created_at, 'profile': call.profile,
                    'matches': call.matches}

    return app
