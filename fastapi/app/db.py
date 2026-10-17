import json
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import JSON, Float, String, create_engine, text
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
    phone: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    profile: Mapped[dict] = mapped_column(JSON)
    matches: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


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
        with self.transaction() as db:
            for program in json.loads(path.read_text(encoding='utf-8')):
                db.merge(Program(id=program['id'], data=program))
