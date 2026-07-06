"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from trading_journal.models import Base


@pytest.fixture
def session(tmp_path) -> Iterator[Session]:
    """A SQLAlchemy session bound to an isolated temp-file SQLite database.

    A temp file (rather than ``:memory:``) avoids the per-connection in-memory
    pitfall and matches how the app runs against a real file.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    with factory() as sess:
        yield sess
