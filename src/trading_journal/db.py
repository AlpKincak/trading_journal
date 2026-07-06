"""Database engine, session management, and schema creation helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings

# Columns added in Phase 2. ``create_all`` builds these on fresh databases, but it
# does NOT alter pre-existing tables, so we additively ``ALTER TABLE ADD COLUMN``
# any that are missing. All are nullable or defaulted, so the change is safe and
# non-destructive on an existing SQLite database.
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "accounts": [
        ("source", "VARCHAR(40) NOT NULL DEFAULT 'local'"),
        ("external_id", "VARCHAR(120)"),
        ("external_account_number", "VARCHAR(60)"),
        ("environment", "VARCHAR(20)"),
        ("last_synced_at", "DATETIME"),
    ],
    "trades": [
        ("external_position_id", "VARCHAR(120)"),
        ("external_order_id", "VARCHAR(120)"),
        ("external_account_id", "VARCHAR(120)"),
        ("external_account_number", "VARCHAR(60)"),
        ("external_status", "VARCHAR(30)"),
        ("raw_payload_json", "TEXT"),
        ("last_synced_at", "DATETIME"),
    ],
}


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


def _apply_additive_migrations(engine: Engine) -> None:
    """Add any missing Phase 2 columns to pre-existing tables.

    No-op on a freshly created database (``create_all`` already made complete
    tables) and safe to run repeatedly.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    """Create all tables and apply additive migrations. Idempotent."""
    # Import here to avoid a circular import at module load time.
    from .models import Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _apply_additive_migrations(engine)


def reset_engine_cache() -> None:
    """Clear cached engine/session factory.

    Useful in tests that swap the database URL between runs.
    """
    get_engine.cache_clear()
    get_session_factory.cache_clear()
