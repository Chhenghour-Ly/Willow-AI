import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = 'sqlite:///./cases.db'
    demo_mode: bool = True
    webhook_secret: str = ''
    review_base_url: str = 'http://localhost:3000/review'
    frontend_origin: str = 'http://localhost:3000'
    review_ttl: int = 3600
    session_ttl: int = 3600
    sms_provider: str = 'mock'
    email_provider: str = 'mock'
    real_sms_enabled: bool = False
    test_recipients: tuple[str, ...] = ('damage-demo@example.test',)
    default_recipient: str = 'damage-demo@example.test'
    twilio_sid: str = ''
    twilio_token: str = ''
    twilio_from: str = ''
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    smtp_from: str = ''
    job_lease_seconds: int = 300

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv()
        values = {}
        defaults = cls()
        for name in cls.__dataclass_fields__:
            raw = os.getenv(name.upper())
            if raw is None:
                continue
            default = getattr(defaults, name)
            if isinstance(default, bool):
                if raw.lower() not in ('true', 'false'):
                    raise ValueError(f'{name.upper()} must be true or false')
                values[name] = raw.lower() == 'true'
            elif isinstance(default, int):
                values[name] = int(raw)
            elif isinstance(default, tuple):
                values[name] = tuple(x.strip().lower() for x in raw.split(',') if x.strip())
            else:
                values[name] = raw
        result = cls(**values)
        if result.sms_provider not in ('mock', 'twilio') or result.email_provider not in ('mock', 'smtp'):
            raise ValueError('Unknown delivery provider')
        if not result.demo_mode and not result.review_base_url.startswith('https://'):
            raise ValueError('HTTPS review URL required outside demo mode')
        if result.real_sms_enabled and not result.review_base_url.startswith('https://'):
            raise ValueError('Real SMS requires an HTTPS review URL')
        from urllib.parse import urlsplit
        review_url = urlsplit(result.review_base_url)
        if review_url.scheme not in ('http', 'https') or not review_url.netloc or review_url.query or review_url.fragment or review_url.username:
            raise ValueError('REVIEW_BASE_URL must be an HTTP(S) URL without credentials, query or fragment')
        if min(result.review_ttl, result.session_ttl) <= 0 or result.job_lease_seconds < 60:
            raise ValueError('Token lifetimes must be positive and job lease at least 60 seconds')
        from app.schemas import validate_email
        result.test_recipients = tuple(validate_email(address) for address in result.test_recipients)
        if result.default_recipient:
            result.default_recipient = validate_email(result.default_recipient)
        return result
