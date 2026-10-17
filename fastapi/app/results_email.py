"""Results email after matching, sent through Resend.

    python -m app.results_email CALL_ID                 show the stored delivery and write the email to outbox/
    python -m app.results_email test you@example.com [CALL_ID]
                                                        send that call's email to an address you own (asks to confirm)

An email goes out only when matching completed, the farmer explicitly asked for deeper
matching AND explicitly consented to email, a confirmed well-formed address exists, and
EMAIL_DELIVERY_ENABLED is true. Content comes only from the stored matching results.
"""
import argparse
import html
import logging
import time
from pathlib import Path
import httpx

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import Call, Database, EmailDelivery, Farmer

log = logging.getLogger('willow')
SUBJECT = 'Your Willow Assistance Results'
SERVICE_CENTER = 'https://www.farmers.gov/working-with-us/service-center-locator'
DISCLAIMER = ('Willow identifies potential assistance programs from public USDA information. It cannot guarantee '
              'eligibility, approval, or funding; the agency running each program makes those decisions.')
LABELS = {'irrigation_upgrade': 'irrigation upgrade', 'water_conservation': 'water conservation',
          'soil_health': 'soil health', 'long_term_conservation': 'long-term conservation', 'crop_damage': 'crop damage'}


# ---------- deciding ----------

def decide(call: Call, override_to: str = '') -> tuple[str, str | None]:
    """(status, reason) before any send. 'pending' means an email may be prepared for this call."""
    p = call.profile or {}
    if p.get('deep_matching_requested') is not True or p.get('email_delivery_consent') is not True:
        return 'not_requested', 'no explicit request for deeper matching and email consent'
    if not (override_to or p.get('results_email')):
        return 'skipped', 'no confirmed, valid email address'
    if call.status != 'completed':
        return 'skipped', f'matching status is {call.status}; no report is sent until matching completes'
    return 'pending', None


# ---------- writing ----------

def farm_summary(p: dict) -> list[tuple[str, str]]:
    place = ', '.join(x for x in (p.get('county'), p.get('state')) if x)
    needs = ', '.join(LABELS.get(n, n) for n in p.get('needs') or [])
    rows = [('Location', place), ('Crops', ', '.join(p.get('crops') or [])), ('Problem', p.get('primary_problem')),
            ('Project', p.get('desired_project')), ('Needs', needs)]
    return [(k, v) for k, v in rows if v]


def sections(p: dict, matches: list[dict], login_code: str | None = None, app_url: str = '') -> list[dict]:
    """The email as structured blocks; both the HTML and the text version are rendered from this."""
    fits = [m for m in matches if m['fit_status'] == 'potential_fit']
    out = [{'kind': 'intro', 'lines': [
        f"Hi {p.get('farmer_name') or 'there'},",
        'Thank you for calling Willow. As you asked on the call, we looked more closely at USDA programs '
        'for your farm. Here is what we found.']}]
    summary = farm_summary(p)
    if summary:
        out.append({'kind': 'facts', 'title': 'Your farm', 'rows': summary})
    if not fits:
        out.append({'kind': 'text', 'title': 'What we found', 'lines': [
            'We did not find a program in our current list that clearly fits what you described. That does not '
            'mean no help exists. Your local USDA Service Center can review your situation with you.']})
    for i, m in enumerate(fits[:2]):
        out.append({
            'kind': 'program', 'title': ('Best potential match: ' if i == 0 else 'Alternative: ') + m['program_name'],
            'agency': m['agency'], 'description': m.get('description'),
            'repay': 'Must be repaid (this is a loan).' if m.get('repayable') else 'Does not have to be repaid.',
            'lists': [('Why it may fit', m['reasons']), ('Possible obstacles', m['obstacles']),
                      ('Still to confirm', m['missing_requirements'])],
            'deadline': m.get('application_deadline'),
            'sources': m.get('official_source_urls') or []})
    steps = [m['next_action'] for m in fits[:2]] or ['Contact your local USDA Service Center about your situation.']
    out.append({'kind': 'steps', 'title': 'Getting ready to apply', 'lines': steps,
                'link': ('Find your USDA Service Center', SERVICE_CENTER)})
    if login_code and app_url:
        out.append({'kind': 'steps', 'title': 'Review and approve in the Willow app', 'lines': [
            f'Your Willow login code: {login_code}',
            'Open the app, enter the code, check your details and approve the programs you want.',
            'Keep this code private. It opens your Willow profile.'],
            'link': ('Open the Willow app', f'{app_url.rstrip("/")}/app')})
    out.append({'kind': 'note', 'lines': [DISCLAIMER]})
    return out


def render(p: dict, matches: list[dict], login_code: str | None = None, app_url: str = '') -> tuple[str, str]:
    """(text, html) built only from the stored matching results."""
    text, parts = [], []
    e = html.escape
    for s in sections(p, matches, login_code, app_url):
        if s['kind'] in ('intro', 'note'):
            text += s['lines'] + ['']
            style = 'color:#6b6a5f;font-size:13px' if s['kind'] == 'note' else ''
            parts += [f'<p style="{style}">{e(line)}</p>' for line in s['lines']]
            continue
        text += [s['title'].upper()]
        parts.append(f'<h2 style="font-size:18px;margin:28px 0 8px">{e(s["title"])}</h2>')
        if s['kind'] == 'facts':
            text += [f'{k}: {v}' for k, v in s['rows']]
            parts.append('<table style="border-collapse:collapse">' + ''.join(
                f'<tr><td style="padding:2px 16px 2px 0;color:#6b6a5f">{e(k)}</td><td>{e(v)}</td></tr>'
                for k, v in s['rows']) + '</table>')
        elif s['kind'] == 'text':
            text += s['lines']
            parts += [f'<p>{e(line)}</p>' for line in s['lines']]
        elif s['kind'] == 'program':
            text += [s['agency'], s['description'] or '', s['repay']]
            parts.append(f'<p style="color:#6b6a5f;margin:0">{e(s["agency"])}</p>')
            if s['description']:
                parts.append(f'<p>{e(s["description"])}</p>')
            parts.append(f'<p><strong>{e(s["repay"])}</strong></p>')
            for label, items in s['lists']:
                if items:
                    text += [f'{label}:'] + [f'  - {i["text"]}' for i in items]
                    parts.append(f'<p style="margin:12px 0 4px"><strong>{e(label)}</strong></p><ul style="margin:0">'
                                 + ''.join(f'<li>{e(i["text"])}</li>' for i in items) + '</ul>')
            if s['deadline']:
                d = s['deadline']
                text.append(f"Deadline: {d['date']} ({d['note']}) Source: {d['source_url']}")
                parts.append(f'<p><strong>Deadline:</strong> {e(d["date"])} ({e(d["note"])}). '
                             f'<a href="{e(d["source_url"])}">Source</a></p>')
            if s['sources']:
                text += ['Official sources:'] + [f"  - {src['title']}: {src['url']}" for src in s['sources']]
                parts.append('<p style="margin:12px 0 4px"><strong>Official sources</strong></p><ul style="margin:0">'
                             + ''.join(f'<li><a href="{e(src["url"])}">{e(src["title"])}</a></li>' for src in s['sources'])
                             + '</ul>')
        elif s['kind'] == 'steps':
            label, url = s['link']
            text += [f'- {line}' for line in s['lines']] + [f'{label}: {url}']
            parts.append('<ul>' + ''.join(f'<li>{e(line)}</li>' for line in s['lines']) + '</ul>'
                         f'<p><a href="{e(url)}">{e(label)}</a></p>')
        text.append('')
    page = ('<!doctype html><html><head><meta charset="utf-8"><title>' + SUBJECT + '</title></head><body>'
            '<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:600px;margin:0 auto;'
            'color:#1f2a22;line-height:1.5;font-size:15px">' + ''.join(parts) + '</div></body></html>')
    return '\n'.join(text).strip() + '\n', page


# ---------- sending ----------

class Uncertain(Exception):
    """The request may have reached Resend; resending could duplicate the email."""


def send_via_resend(settings: Settings, to: str, text: str, page: str, idempotency_key: str) -> tuple[str, str]:
    """Returns (message_id, short provider response). Raises Uncertain or httpx.HTTPStatusError."""
    if not (settings.resend_api_key and settings.farmbridge_from_email):
        raise RuntimeError('RESEND_API_KEY and FARMBRIDGE_FROM_EMAIL are required')
    body = {'from': settings.farmbridge_from_email, 'to': [to], 'subject': SUBJECT, 'text': text, 'html': page}
    if settings.farmbridge_reply_to:
        body['reply_to'] = settings.farmbridge_reply_to
    try:
        response = httpx.post(f'{settings.resend_base_url}/emails', json=body, timeout=20,
                              headers={'Authorization': f'Bearer {settings.resend_api_key}',
                                       'Idempotency-Key': idempotency_key})
    except httpx.TransportError as exc:
        raise Uncertain(type(exc).__name__) from exc
    if response.status_code >= 500:
        raise Uncertain(f'HTTP {response.status_code}')
    if response.status_code >= 400:
        # Resend's error message (e.g. unverified domain) is safe to keep and explains the failure.
        detail = response.json().get('message', '') if 'json' in response.headers.get('content-type', '') else ''
        raise httpx.HTTPStatusError(f'HTTP {response.status_code} {detail}'.strip(), request=response.request,
                                    response=response)
    return response.json()['id'], f'HTTP {response.status_code}'

def deliver_results(database: Database, settings: Settings, call_id: str) -> str:
    """Decide, record and (at most once) send the results email for a processed call. Returns the delivery status."""
    with database.transaction() as db:
        call = db.get(Call, call_id)
        status, reason = decide(call, settings.email_override_to)
        p = call.profile or {}
        recipient = settings.email_override_to or p.get('results_email') or ''
        text_body = page = None
        if status == 'pending':
            farmer = db.get(Farmer, call.phone) if call.phone else None
            text_body, page = render(p, call.matches, farmer and farmer.login_code, settings.frontend_origin)
            if not settings.email_enabled():
                status, reason = 'dry_run', 'EMAIL_DELIVERY_ENABLED is false; email generated, not sent'
    try:
        with database.transaction() as db:
            db.add(EmailDelivery(call_id=call_id, recipient_email=recipient, status=status, reason=reason,
                                 consent_statement=p.get('email_consent_statement'), consent_at=p.get('consent_at'),
                                 subject=SUBJECT if text_body else None, body_text=text_body, body_html=page))
    except IntegrityError:
        log.info('call_id=%s results email already recorded; not sending again', call_id)
        return 'duplicate'
    log.info('call_id=%s results email %s%s', call_id, status, f' ({reason})' if reason else '')
    return send_pending(database, settings, call_id, recipient) if status == 'pending' else status


def send_pending(database: Database, settings: Settings, call_id: str, recipient: str) -> str:
    # Claim pending -> sending atomically so two workers can never both send.
    with database.transaction() as db:
        claimed = db.execute(update(EmailDelivery)
                             .where(EmailDelivery.call_id == call_id, EmailDelivery.recipient_email == recipient,
                                    EmailDelivery.status == 'pending')
                             .values(status='sending')).rowcount
        row = db.query(EmailDelivery).filter_by(call_id=call_id, recipient_email=recipient).one()
        text_body, page = row.body_text, row.body_html
    if not claimed:
        return row.status
    message_id = sent_at = None
    try:
        message_id, response = send_via_resend(settings, recipient, text_body, page, f'farmbridge-results-{call_id}')
        status, reason, sent_at = 'sent', None, time.time()
    except Uncertain as exc:  # never auto-resend: the farmer may already have the email
        status, reason, response = 'uncertain', 'delivery outcome unknown; check Resend before resending', str(exc)
    except httpx.HTTPStatusError as exc:
        status, reason, response = 'failed', 'Resend rejected the email', str(exc)[:300]
    except Exception as exc:
        status, reason, response = 'failed', 'email not sent', type(exc).__name__
    with database.transaction() as db:
        row = db.query(EmailDelivery).filter_by(call_id=call_id, recipient_email=recipient).one()
        row.status, row.reason, row.provider_response = status, reason, response
        row.provider_message_id, row.sent_at = message_id, sent_at
    log.info('call_id=%s results email %s (%s)', call_id, status, response)
    return status


def resume_interrupted(database: Database, settings: Settings) -> list[str]:
    """On startup: emails left 'pending' are sent; emails left 'sending' are marked uncertain, never resent."""
    with database.transaction() as db:
        db.execute(update(EmailDelivery).where(EmailDelivery.status == 'sending')
                   .values(status='uncertain', reason='server stopped mid-send; check Resend before resending'))
        pending = [(r.call_id, r.recipient_email) for r in db.query(EmailDelivery).filter_by(status='pending')]
    return [send_pending(database, settings, call_id, to) for call_id, to in pending]


def delivery_summary(database: Database, call_id: str) -> dict | None:
    with database.transaction() as db:
        row = db.query(EmailDelivery).filter_by(call_id=call_id).order_by(EmailDelivery.id.desc()).first()
        if not row:
            return None
        return {'requested': row.status != 'not_requested', 'status': row.status, 'reason': row.reason,
                'sent_at': row.sent_at}


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description='Willow results email')
    parser.add_argument('cmd_or_call', help='a call id, or "test"')
    parser.add_argument('rest', nargs='*')
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_url)

    if args.cmd_or_call == 'test':
        from app.profile import email
        to = email(args.rest[0] if args.rest else '')
        call_id = args.rest[1] if len(args.rest) > 1 else 'sim-carolina-0001'
        if not to:
            raise SystemExit('usage: python -m app.results_email test you@example.com [CALL_ID]')
        with database.transaction() as db:
            call = db.get(Call, call_id)
            if not call or call.status != 'completed':
                raise SystemExit(f'{call_id} has no completed matching result')
            text_body, page = render(call.profile, call.matches)
        print(text_body)
        if input(f'Send this as ONE real email to {to}? Type "send": ').strip().lower() == 'send':
            print('Resend message id:', send_via_resend(settings, to, text_body, page, f'farmbridge-test-{call_id}-{to}')[0])
        return

    call_id = args.cmd_or_call
    with database.transaction() as db:
        row = db.query(EmailDelivery).filter_by(call_id=call_id).order_by(EmailDelivery.id.desc()).first()
        if not row:
            raise SystemExit(f'No email delivery recorded for {call_id}')
        print(f'status: {row.status}  reason: {row.reason or "-"}  provider: {row.provider_response or "-"}')
        if row.body_html:
            out = Path('outbox'); out.mkdir(exist_ok=True)
            (out / f'{call_id}.html').write_text(row.body_html, encoding='utf-8')
            print(f'HTML written to outbox/{call_id}.html\n')
            print(row.body_text)


if __name__ == '__main__':
    main()
