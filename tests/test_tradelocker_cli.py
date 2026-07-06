"""Tests for the TradeLocker CLI commands (offline, isolated DB)."""

from __future__ import annotations

import types
from collections.abc import Iterator

import pytest

import tradelocker_fakes as fakes
from trading_journal import cli
from trading_journal.connectors.tradelocker.client import TradeLockerReadOnlyClient
from trading_journal.db import reset_engine_cache, session_scope
from trading_journal.models import SyncRun, Trade
from trading_journal.services.sync_service import build_sync_service


@pytest.fixture
def isolated_db(tmp_path, monkeypatch) -> Iterator[None]:
    """Point the app database at a throwaway file for the duration of a test."""
    from trading_journal.config import get_settings

    monkeypatch.setenv("TRADING_JOURNAL_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    get_settings.cache_clear()
    reset_engine_cache()
    yield
    get_settings.cache_clear()
    reset_engine_cache()


def _patch_connector(monkeypatch, routes=None, **settings_overrides):
    """Wire the CLI to a fake-transport-backed client + settings."""
    settings = fakes.make_settings(**settings_overrides)
    monkeypatch.setattr(cli, "get_tradelocker_settings", lambda: settings)

    def fake_from_settings(s, transport=None):
        return TradeLockerReadOnlyClient(s, transport=fakes.FakeTransport(routes))

    monkeypatch.setattr(
        cli, "TradeLockerReadOnlyClient", types.SimpleNamespace(from_settings=fake_from_settings)
    )

    def fake_build(s, transport=None, client=None):
        return build_sync_service(s, transport=fakes.FakeTransport(routes))

    monkeypatch.setattr(cli, "build_sync_service", fake_build)
    return settings


def test_health_ok_returns_zero(isolated_db, monkeypatch, capsys):
    _patch_connector(monkeypatch)
    rc = cli.main(["tradelocker-health"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out
    assert "s3cr3t" not in out  # no secrets in output


def test_health_missing_credentials_returns_nonzero(isolated_db, monkeypatch, capsys):
    _patch_connector(monkeypatch, password=None)
    rc = cli.main(["tradelocker-health"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "s3cr3t" not in out


def test_accounts_lists_without_secrets(isolated_db, monkeypatch, capsys):
    _patch_connector(monkeypatch)
    rc = cli.main(["tradelocker-accounts"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "id=12345" in out
    assert "s3cr3t" not in out
    assert "ACCESS-TOKEN" not in out


def test_sync_default_is_dry_run_and_writes_nothing(isolated_db, monkeypatch, capsys):
    _patch_connector(monkeypatch)
    rc = cli.main(["sync-tradelocker", "--account-id", "12345", "--acc-num", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    with session_scope() as session:
        assert session.query(Trade).count() == 0
        assert session.query(SyncRun).count() == 0


def test_sync_apply_writes_idempotently(isolated_db, monkeypatch, capsys):
    _patch_connector(monkeypatch)
    rc = cli.main(["sync-tradelocker", "--apply", "--account-id", "12345", "--acc-num", "1"])
    assert rc == 0
    with session_scope() as session:
        assert session.query(Trade).count() == 1
        assert session.query(SyncRun).count() == 1

    # Re-running does not duplicate.
    cli.main(["sync-tradelocker", "--apply", "--account-id", "12345", "--acc-num", "1"])
    with session_scope() as session:
        assert session.query(Trade).count() == 1


def test_sync_requires_account_or_all(isolated_db, monkeypatch, capsys):
    _patch_connector(monkeypatch, account_id=None)
    rc = cli.main(["sync-tradelocker", "--apply"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "account-id" in err or "--all" in err


def test_sync_apply_and_dry_run_conflict(isolated_db, monkeypatch, capsys):
    _patch_connector(monkeypatch)
    rc = cli.main(["sync-tradelocker", "--apply", "--dry-run", "--account-id", "12345"])
    assert rc == 2


def test_sync_status_after_apply(isolated_db, monkeypatch, capsys):
    _patch_connector(monkeypatch)
    cli.main(["sync-tradelocker", "--apply", "--account-id", "12345", "--acc-num", "1"])
    capsys.readouterr()  # clear
    rc = cli.main(["sync-status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SUCCESS" in out


def test_sync_status_empty(isolated_db, monkeypatch, capsys):
    _patch_connector(monkeypatch)
    rc = cli.main(["sync-status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No sync runs" in out
