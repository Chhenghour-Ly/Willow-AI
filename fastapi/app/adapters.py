import smtplib
import ssl
import logging
from contextlib import closing
from dataclasses import dataclass
from email.message import EmailMessage

from app.schemas import RagInput, RagOutput, Requirement, validate_email


def retrieve_requirements(request: RagInput) -> RagOutput:
    """Proposed teammate boundary; documents are data, never authority to send."""
    return RagOutput(requirements=[Requirement(
        text='FICTIONAL DEMO: Example insurer requests crop, location and a description of damage.',
        sources=['fictional-document:demo-policy#page=1'], applicability='unknown', reviewed=False)],
        unresolved_questions=['Which policy rules apply?', 'What timing does the agent confirm?'], simulated=True)


@dataclass
class DeliveryResult:
    status: str
    provider_id: str | None = None
    error: str | None = None
    simulated: bool = False


def allowed_recipient(recipient, settings):
    try:
        normalized = validate_email(recipient)
    except (ValueError, TypeError):
        return False
    # This entire backend is a test-submission prototype, even when DEMO_MODE is false.
    return normalized in {validate_email(x) for x in settings.test_recipients}


def send_sms(phone, link, settings):
    if settings.sms_provider == 'mock':
        return DeliveryResult('sent', 'simulated-sms', simulated=True)
    if settings.sms_provider != 'twilio' or not settings.real_sms_enabled:
        return DeliveryResult('failed', error='real_sms_not_enabled')
    if not all((settings.twilio_sid, settings.twilio_token, settings.twilio_from)):
        return DeliveryResult('failed', error='twilio_not_configured')
    from twilio.base.exceptions import TwilioRestException
    from twilio.http.http_client import TwilioHttpClient
    from twilio.rest import Client
    try:
        provider_logger = logging.getLogger('damage_notice.twilio_silent')
        provider_logger.disabled = True
        client = Client(settings.twilio_sid, settings.twilio_token,
                        http_client=TwilioHttpClient(timeout=20, max_retries=0, logger=provider_logger))
        message = client.messages.create(to=phone, from_=settings.twilio_from,
                                        body=f'Your damage notice is ready to review: {link}')
        return DeliveryResult('sent', message.sid)
    except TwilioRestException as exc:
        # Only a definite rejection is safe to classify as failed.
        return DeliveryResult('failed' if 400 <= exc.status < 500 else 'uncertain', error='twilio_rejected_or_unavailable')
    except Exception:
        return DeliveryResult('uncertain', error='twilio_delivery_unknown')


def send_email(snapshot, documents, settings, submission_id):
    if not allowed_recipient(snapshot['recipient'], settings):
        return DeliveryResult('failed', error='recipient_not_allowed')
    if settings.email_provider == 'mock':
        return DeliveryResult('sent', f'simulated-email-{submission_id}', simulated=True)
    if settings.email_provider != 'smtp' or not settings.smtp_host or not settings.smtp_from:
        return DeliveryResult('failed', error='smtp_not_configured')
    message_id = f'<{submission_id}@damage-notice.invalid>'
    try:
        sender = validate_email(settings.smtp_from)
        message = EmailMessage()
        message['From'] = sender
        message['To'] = snapshot['recipient']
        message['Subject'] = '[TEST DAMAGE NOTICE] Farmer-reviewed damage report'
        message['Message-ID'] = message_id
        message.set_content(snapshot['draft_notice'])
        for document in documents:
            message.add_attachment(document['content'], maintype='application', subtype='octet-stream',
                                   filename=document['name'])
    except (ValueError, TypeError):
        return DeliveryResult('failed', error='invalid_message')
    dispatch_started = False
    try:
        with closing(smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            dispatch_started = True
            refused = smtp.send_message(message, from_addr=sender, to_addrs=[snapshot['recipient']])
            if refused:
                return DeliveryResult('failed', message_id, error='recipient_refused')
            # Persist acceptance even if QUIT later fails.
            result = DeliveryResult('sent', message_id)
            try:
                smtp.quit()
            except (OSError, smtplib.SMTPException):
                pass
            return result
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
        return DeliveryResult('failed', message_id, error='smtp_rejected')
    except (OSError, smtplib.SMTPException):
        return DeliveryResult('uncertain' if dispatch_started else 'failed', message_id,
                              error='smtp_response_lost' if dispatch_started else 'smtp_connection_failed')
