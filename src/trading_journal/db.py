"""Database engine, session management, and schema creation helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return a cached SQLAlchemy engine for the configured database."""
    settings: Settings = get_settings()
    # ``check_same_thread=False`` keeps Streamlit (which uses threads) happy.
    connect_args = (
        {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    )
    return create_engine(settings.database_url, echo=settings.sql_echo, connect_args=connect_args)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return a cached session factory bound to the engine."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Commits on success, rolls back on exception, and always closes the session.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables. Safe to call repeatedly (idempotent)."""
    # Import here to avoid a circular import at module load time.
    from .models import Base

    Base.metadata.create_all(bind=get_engine())


def reset_engine_cache() -> None:
    """Clear cached engine/session factory.

    Useful in tests that swap the database URL between runs.
    """
    get_engine.cache_clear()
    get_session_factory.cache_clear()
