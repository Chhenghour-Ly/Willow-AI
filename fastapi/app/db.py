import time
import uuid
from contextlib import contextmanager

from sqlalchemy import JSON, Boolean, Float, Integer, LargeBinary, String, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def new_id():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Farmer(Base):
    __tablename__ = 'farmers'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    phone: Mapped[str] = mapped_column(String)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_consent: Mapped[bool] = mapped_column(Boolean, default=False)


class CallBinding(Base):
    __tablename__ = 'call_bindings'
    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    farmer_id: Mapped[str] = mapped_column(String)


class Case(Base):
    __tablename__ = 'cases'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    call_id: Mapped[str] = mapped_column(String, unique=True)
    farmer_id: Mapped[str] = mapped_column(String)
    original_payload: Mapped[dict] = mapped_column(JSON)
    facts: Mapped[dict] = mapped_column(JSON)
    processing_status: Mapped[str] = mapped_column(String, default='queued')
    draft_version: Mapped[int] = mapped_column(Integer, default=0)
    approval_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Report(Base):
    __tablename__ = 'reports'
    __table_args__ = (UniqueConstraint('case_id', 'version'),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(JSON)


class Document(Base):
    __tablename__ = 'documents'
    __table_args__ = (UniqueConstraint('case_id', 'document_id', 'version'),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(String, index=True)
    document_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    content: Mapped[bytes] = mapped_column(LargeBinary)


class Approval(Base):
    __tablename__ = 'approvals'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Submission(Base):
    __tablename__ = 'submissions'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(String, unique=True)
    approval_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default='queued')
    provider_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String, default='queued')
    provider_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)


class ReviewToken(Base):
    __tablename__ = 'review_tokens'
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String)
    expires_at: Mapped[float] = mapped_column(Float)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class SessionToken(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String)
    expires_at: Mapped[float] = mapped_column(Float)


class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)
    case_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default='queued')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[float] = mapped_column(Float, default=time.time)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class Activity(Base):
    __tablename__ = 'activity'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Database:
    def __init__(self, url):
        if not url.startswith('sqlite:'):
            raise ValueError('This prototype supports SQLite only')
        self.engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30})
        @event.listens_for(self.engine, 'connect')
        def pragmas(connection, _):
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def read(self):
        with self.sessions() as session:
            yield session

    @contextmanager
    def transaction(self):
        with self.sessions() as session:
            try:
                session.connection().exec_driver_sql('BEGIN IMMEDIATE')
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise
