"""Streamlit AppTest coverage for the Sync tab.

These tests confirm the dashboard (including the new Sync tab) renders without
credentials and without crashing, and that opening it triggers no network calls.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from trading_journal import cli  # noqa: E402
from trading_journal.config import get_settings  # noqa: E402
from trading_journal.db import reset_engine_cache  # noqa: E402

APP_PATH = str(cli.APP_PATH)


@pytest.fixture
def isolated_app(tmp_path, monkeypatch) -> Iterator[None]:
    # No TradeLocker credentials -> must still render.
    for var in ("TRADELOCKER_EMAIL", "TRADELOCKER_PASSWORD", "TRADELOCKER_SERVER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TRADELOCKER_ENABLED", "false")
    monkeypatch.setenv("TRADING_JOURNAL_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    get_settings.cache_clear()
    reset_engine_cache()
    yield
    get_settings.cache_clear()
    reset_engine_cache()


def test_dashboard_renders_with_sync_tab(isolated_app):
    at = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert not at.exception
    # Phase 3: eight tabs (Dashboard, Trades, Analytics, Calendar/Reviews, Import,
    # Sync, Account/Backup, Help/Data Quality).
    assert len(at.tabs) == 8
    subheaders = [s.value for s in at.subheader]
    assert any("TradeLocker sync" in text for text in subheaders)


def test_sync_tab_shows_missing_credentials_gracefully(isolated_app):
    at = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert not at.exception
    # The config summary reports credentials as Missing (no secret values shown).
    credential_metrics = [m.value for m in at.metric if m.label == "Credentials"]
    assert credential_metrics == ["Missing"]
    infos = [i.value for i in at.info]
    assert any("credentials are not set" in text for text in infos)


def test_health_button_without_credentials_is_safe_offline(isolated_app):
    at = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert not at.exception

    health_buttons = [b for b in at.button if b.label == "Health check"]
    assert health_buttons, "expected a Health check button in the Sync tab"
    # Clicking with no credentials short-circuits before any network call.
    health_buttons[0].click().run()
    assert not at.exception
    errors = [e.value for e in at.error]
    assert any("FAILED" in text or "Missing" in text for text in errors)
