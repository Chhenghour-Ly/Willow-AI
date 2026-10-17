import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = 'sqlite:///./willow.db'
    webhook_secret: str = ''
    # Required on every GET /api/* request (X-Api-Key header). Empty = those endpoints return 503.
    api_key: str = ''
    # Server-side Vapi private key, used only to fetch a finished call when the webhook lacks structured outputs.
    vapi_api_key: str = ''
    vapi_base_url: str = 'https://api.vapi.ai'
    # Seconds to wait between GET /call/{id} attempts while Vapi finishes post-call analysis.
    vapi_retry_delays: str = '2,4,8,16'
    # Results email via Resend. While EMAIL_DELIVERY_ENABLED is false, emails are generated and stored as dry runs.
    email_delivery_enabled: str = 'false'
    resend_api_key: str = ''
    resend_base_url: str = 'https://api.resend.com'
    farmbridge_from_email: str = ''
    farmbridge_reply_to: str = ''
    sms_delivery_enabled: str = 'false'
    twilio_account_sid: str = ''
    twilio_auth_token: str = ''
    twilio_from_number: str = ''
    report_base_url: str = ''
    frontend_origin: str = 'http://localhost:5173'
    programs_path: str = 'fixtures/programs.json'

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv()
        return cls(**{name: os.environ[name.upper()] for name in cls.__dataclass_fields__
                      if os.getenv(name.upper()) is not None})

    def email_enabled(self):
        return self.email_delivery_enabled.strip().lower() == 'true'

    def sms_enabled(self):
        return self.sms_delivery_enabled.strip().lower() == 'true'

    def retry_delays(self):
        return [float(x) for x in self.vapi_retry_delays.split(',') if x.strip()]
