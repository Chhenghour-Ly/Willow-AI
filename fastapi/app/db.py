import json
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import JSON, Float, Integer, String, UniqueConstraint, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Program(Base):
    __tablename__ = 'programs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class Call(Base):
    __tablename__ = 'calls'
    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    # received -> processing -> completed | needs_information | failed
    status: Mapped[str] = mapped_column(String, default='received')
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    matches: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)


class EmailDelivery(Base):
    """One results email per original call and recipient; the unique constraint blocks duplicate sends."""
    __tablename__ = 'email_deliveries'
    __table_args__ = (UniqueConstraint('call_id', 'recipient_email'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String, index=True)
    recipient_email: Mapped[str] = mapped_column(String, default='')  # '' when no valid address was given
    # not_requested | skipped | dry_run | pending | sending | sent | failed | uncertain
    status: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    consent_statement: Mapped[str | None] = mapped_column(String, nullable=True)
    consent_at: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    body_text: Mapped[str | None] = mapped_column(String, nullable=True)
    body_html: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_response: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)


class SmsDelivery(Base):
    __tablename__ = 'sms_deliveries'
    __table_args__ = (UniqueConstraint('call_id', 'recipient_phone'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String, index=True)
    recipient_phone: Mapped[str] = mapped_column(String, default='')
    status: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    consent_statement: Mapped[str | None] = mapped_column(String, nullable=True)
    consent_at: Mapped[str | None] = mapped_column(String, nullable=True)
    body_text: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String, nullable=True)
    submitted_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)


class Farmer(Base):
    """One profile per caller phone. The 6-digit login code opens it in the farmer app."""
    __tablename__ = 'farmers'
    phone: Mapped[str] = mapped_column(String, primary_key=True)
    login_code: Mapped[str] = mapped_column(String, unique=True)
    # {call_id: {'approved': [program_id], 'edits': {field: value}, 'confirmed': bool}}
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)


class LoginAttempt(Base):
    """A wrong login code. The Vercel functions count recent rows to slow down guessing."""
    __tablename__ = 'login_attempts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


DEMO_CODE = '000000'  # opens sample data in the app; never issued to a farmer


class ReportLink(Base):
    __tablename__ = 'report_links'
    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[float] = mapped_column(Float)


def ensure_farmer(db, phone: str) -> Farmer:
    """The farmer for this phone, created with a fresh unique 6-digit code the first time."""
    farmer = db.get(Farmer, phone)
    if farmer:
        return farmer
    while True:
        code = f'{secrets.randbelow(10**6):06d}'
        if code != DEMO_CODE and not db.scalar(select(Farmer).where(Farmer.login_code == code)):
            break
    farmer = Farmer(phone=phone, login_code=code, state={})
    db.add(farmer)
    db.flush()
    return farmer


def engine_url(url):
    # Supabase hands out postgres:// URLs; SQLAlchemy needs the psycopg driver named.
    for prefix in ('postgres://', 'postgresql://'):
        if url.startswith(prefix):
            return 'postgresql+psycopg://' + url[len(prefix):]
    return url


class Database:
    def __init__(self, url):
        self.engine = create_engine(engine_url(url))
        Base.metadata.create_all(self.engine)
        if self.engine.dialect.name == 'postgresql':
            # Supabase exposes the public schema over its REST API; RLS with no
            # policies keeps these tables reachable only through this backend.
            with self.engine.begin() as conn:
                for table in Base.metadata.tables:
                    conn.execute(text(f'alter table {table} enable row level security'))
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self):
        with self.sessions.begin() as session:
            yield session

    def sync_programs(self, path: Path):
        programs = json.loads(path.read_text(encoding='utf-8'))
        with self.transaction() as db:
            db.query(Program).filter(Program.id.not_in([p['id'] for p in programs])).delete()
            for program in programs:
                db.merge(Program(id=program['id'], data=program))
