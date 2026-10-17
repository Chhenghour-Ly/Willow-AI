"""Send a short matching summary by SMS after explicit Vapi consent."""
import argparse
import hashlib
import logging
import secrets
import time
from urllib.parse import urlsplit

import httpx
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import Call, Database, ReportLink, SmsDelivery

log = logging.getLogger('willow')
# shortcut: these labels cover the two current programs; add one when the program list grows.
SHORT_NAMES = {'eqip': 'EQIP', 'fsa-operating-microloan': 'FSA microloan'}


class Uncertain(Exception):
    """The provider may have received the request; never retry automatically."""


def decide(call: Call) -> tuple[str, str | None]:
    profile = call.profile or {}
    if profile.get('deep_matching_requested') is not True or profile.get('sms_delivery_consent') is not True:
        return 'not_requested', 'no explicit request for deeper matching and SMS consent'
    if not profile.get('sms_consent_statement'):
        return 'skipped', 'no recorded SMS consent statement'
    if not profile.get('sms_results_phone'):
        return 'skipped', 'no confirmed, valid SMS number'
    if call.status != 'completed':
        return 'skipped', f'matching status is {call.status}; no summary is sent until matching completes'
    return 'pending', None


def render(matches: list[dict], report_url: str | None = None) -> str:
    names = [SHORT_NAMES.get(m['program_id'], m['program_name'])
             for m in matches if m['fit_status'] == 'potential_fit'][:2]
    if names:
        body = 'FarmBridge: Potential matches: ' + ', '.join(names) + '. USDA decides eligibility.'
    else:
        body = 'FarmBridge: We did not find a clear match in our list. Ask your local USDA Service Center.'
    return body + (f' {report_url}' if report_url else '')


def public_report_base(settings: Settings) -> str | None:
    base = settings.report_base_url.strip().rstrip('/')
    parts = urlsplit(base)
    return base if parts.scheme == 'https' and parts.netloc and not parts.path and not parts.query and not parts.fragment else None


def send_via_twilio(settings: Settings, recipient: str, body: str) -> tuple[str, str]:
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
        raise RuntimeError('Twilio credentials or sender are not configured')
    url = f'https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json'
    try:
        response = httpx.post(url, data={'To': recipient, 'From': settings.twilio_from_number, 'Body': body},
                              auth=(settings.twilio_account_sid, settings.twilio_auth_token), timeout=20)
    except httpx.TransportError as exc:
        raise Uncertain(type(exc).__name__) from exc
    if response.status_code >= 500:
        raise Uncertain(f'HTTP {response.status_code}')
    response.raise_for_status()
    try:
        result = response.json()
        return result['sid'], result['status']
    except (ValueError, KeyError, TypeError) as exc:
        raise Uncertain('Twilio accepted request but returned no message SID') from exc


def deliver_results(database: Database, settings: Settings, call_id: str) -> str:
    with database.transaction() as db:
        call = db.get(Call, call_id)
        status, reason = decide(call)
        profile = call.profile or {}
        recipient = profile.get('sms_results_phone') or ''
        base = public_report_base(settings)
        if status == 'pending' and not base:
            status, reason = 'skipped', 'REPORT_BASE_URL must be a public HTTPS origin'
        token = secrets.token_urlsafe(18) if status == 'pending' else None
        body = render(call.matches, f'{base}/report/{token}') if token else None
        if status == 'pending' and not settings.sms_enabled():
            status, reason = 'dry_run', 'SMS_DELIVERY_ENABLED is false; summary generated, not sent'
    try:
        with database.transaction() as db:
            if token:
                db.add(ReportLink(call_id=call_id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                  expires_at=time.time() + 30 * 86400))
            db.add(SmsDelivery(call_id=call_id, recipient_phone=recipient, status=status, reason=reason,
                               consent_statement=profile.get('sms_consent_statement'),
                               consent_at=profile.get('consent_at'), body_text=body))
    except IntegrityError:
        log.info('call_id=%s results SMS already recorded; not sending again', call_id)
        return 'duplicate'
    log.info('call_id=%s results SMS %s%s', call_id, status, f' ({reason})' if reason else '')
    return send_pending(database, settings, call_id, recipient) if status == 'pending' else status


def send_pending(database: Database, settings: Settings, call_id: str, recipient: str) -> str:
    with database.transaction() as db:
        claimed = db.execute(update(SmsDelivery)
                             .where(SmsDelivery.call_id == call_id, SmsDelivery.recipient_phone == recipient,
                                    SmsDelivery.status == 'pending')
                             .values(status='sending')).rowcount
        row = db.query(SmsDelivery).filter_by(call_id=call_id, recipient_phone=recipient).one()
        body = row.body_text
        current_status = row.status
    if not claimed:
        return current_status
    message_id = provider_status = submitted_at = None
    try:
        message_id, provider_status = send_via_twilio(settings, recipient, body)
        status, reason, submitted_at = 'submitted', None, time.time()
    except Uncertain as exc:
        status, reason = 'uncertain', f'delivery outcome unknown ({exc}); check Twilio before resending'
    except httpx.HTTPStatusError as exc:
        status, reason = 'failed', f'Twilio HTTP {exc.response.status_code}'
    except RuntimeError as exc:
        status, reason = 'failed', str(exc)
    with database.transaction() as db:
        row = db.query(SmsDelivery).filter_by(call_id=call_id, recipient_phone=recipient).one()
        row.status, row.reason = status, reason
        row.provider_message_id, row.provider_status, row.submitted_at = message_id, provider_status, submitted_at
    log.info('call_id=%s results SMS %s%s', call_id, status, f' ({reason})' if reason else '')
    return status


def resume_interrupted(database: Database, settings: Settings) -> list[str]:
    with database.transaction() as db:
        db.execute(update(SmsDelivery).where(SmsDelivery.status == 'sending')
                   .values(status='uncertain', reason='server stopped mid-send; check Twilio before resending'))
        pending = [(r.call_id, r.recipient_phone) for r in db.query(SmsDelivery).filter_by(status='pending')]
    return [send_pending(database, settings, call_id, phone) for call_id, phone in pending]


def delivery_summary(database: Database, call_id: str) -> dict | None:
    with database.transaction() as db:
        row = db.query(SmsDelivery).filter_by(call_id=call_id).order_by(SmsDelivery.id.desc()).first()
        if not row:
            return None
        return {'requested': row.status != 'not_requested', 'status': row.status, 'reason': row.reason,
                'provider_status': row.provider_status, 'submitted_at': row.submitted_at}


def main():
    parser = argparse.ArgumentParser(description='Show a call\'s results SMS delivery')
    parser.add_argument('call_id')
    args = parser.parse_args()
    database = Database(Settings.from_env().database_url)
    with database.transaction() as db:
        row = db.query(SmsDelivery).filter_by(call_id=args.call_id).order_by(SmsDelivery.id.desc()).first()
        if not row:
            raise SystemExit(f'No SMS delivery recorded for {args.call_id}')
        print(f'status: {row.status} reason: {row.reason or "-"} provider: {row.provider_status or "-"}')
        if row.body_text:
            print(row.body_text)


if __name__ == '__main__':
    main()
