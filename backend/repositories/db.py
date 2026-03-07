from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pymysql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config.settings import get_settings

# Install pymysql as MySQLdb to ensure SQLAlchemy uses it
pymysql.install_as_MySQLdb()

_engine: Engine | None = None
_session_factory: sessionmaker | None = None

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.mysql_url,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


def init_db() -> None:
    """Execute schema.sql to ensure all tables exist (idempotent)."""
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    engine = get_engine()
    with engine.begin() as conn:
        for statement in schema_sql.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)
    return _session_factory


@contextmanager
def db_session(existing: Session | None = None) -> Iterator[Session]:
    if existing is not None:
        yield existing
        return
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
