"""AppTest coverage for the Phase 3 tabs (empty and seeded databases)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from trading_journal import cli  # noqa: E402
from trading_journal.config import get_settings  # noqa: E402
from trading_journal.db import init_db, reset_engine_cache, session_scope  # noqa: E402
from trading_journal.seed import seed_demo  # noqa: E402

APP_PATH = str(cli.APP_PATH)


def _clean_env(monkeypatch, tmp_path) -> None:
    for var in ("TRADELOCKER_EMAIL", "TRADELOCKER_PASSWORD", "TRADELOCKER_SERVER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TRADELOCKER_ENABLED", "false")
    monkeypatch.setenv("TRADING_JOURNAL_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    get_settings.cache_clear()
    reset_engine_cache()


@pytest.fixture
def empty_app(tmp_path, monkeypatch) -> Iterator[None]:
    _clean_env(monkeypatch, tmp_path)
    yield
    get_settings.cache_clear()
    reset_engine_cache()


@pytest.fixture
def seeded_app(tmp_path, monkeypatch) -> Iterator[None]:
    _clean_env(monkeypatch, tmp_path)
    init_db()
    with session_scope() as session:
        seed_demo(session)
    yield
    get_settings.cache_clear()
    reset_engine_cache()


def test_all_tabs_render_with_empty_db(empty_app):
    at = AppTest.from_file(APP_PATH, default_timeout=90).run()
    assert not at.exception
    assert len(at.tabs) == 8
    subheaders = [s.value for s in at.subheader]
    assert any("Backup & export" in t for t in subheaders)
    assert any("Data quality" in t for t in subheaders)


_TOP_LEVEL_TABS = {
    "Dashboard",
    "Trades",
    "Analytics",
    "Calendar / Reviews",
    "Import",
    "Sync",
    "Account / Backup",
    "Help / Data Quality",
}


def test_all_tabs_render_with_seeded_db(seeded_app):
    at = AppTest.from_file(APP_PATH, default_timeout=120).run()
    assert not at.exception
    # Analytics renders nested breakdown tabs when seeded, so check labels, not count.
    assert _TOP_LEVEL_TABS <= {t.label for t in at.tabs}

    subheaders = [s.value for s in at.subheader]
    assert any("Risk & R analytics" in t for t in subheaders)
    assert any("Calendar" in t for t in subheaders)
    assert any("Trade detail & review" in t for t in subheaders)
    assert any("Backup & export" in t for t in subheaders)
    assert any("Needs Review" in t for t in subheaders)

    # The dashboard Journal Score is present with seeded data.
    score_metrics = [m.label for m in at.metric if m.label == "Journal Score"]
    assert score_metrics


def test_trade_review_buttons_present_when_seeded(seeded_app):
    at = AppTest.from_file(APP_PATH, default_timeout=120).run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any("Mark reviewed" in label for label in labels)
    assert any("Add trade" in label for label in labels)
    assert any("Create backup" in label for label in labels)
