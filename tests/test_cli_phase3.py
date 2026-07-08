"""Tests for the Phase 3 CLI commands (offline, isolated temp DB)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from trading_journal import cli
from trading_journal.db import reset_engine_cache, session_scope
from trading_journal.models import DailyReview, Trade


@pytest.fixture
def isolated_db(tmp_path, monkeypatch) -> Iterator[None]:
    from trading_journal.config import get_settings

    monkeypatch.setenv("TRADING_JOURNAL_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    get_settings.cache_clear()
    reset_engine_cache()
    yield
    get_settings.cache_clear()
    reset_engine_cache()


def test_add_trade_creates_manual_trade(isolated_db, capsys):
    rc = cli.main(
        [
            "add-trade",
            "--symbol",
            "eurusd",
            "--side",
            "buy",
            "--status",
            "closed",
            "--opened-at",
            "2025-03-01 09:00",
            "--closed-at",
            "2025-03-01 15:00",
            "--entry-price",
            "1.10",
            "--exit-price",
            "1.11",
            "--stop-loss",
            "1.095",
            "--gross-pnl",
            "210",
            "--fees",
            "10",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Added manual trade" in out
    with session_scope() as session:
        trade = session.query(Trade).one()
        assert trade.source == "manual"
        assert trade.is_manual is True
        assert trade.symbol == "EURUSD"


def test_add_trade_invalid_side_fails(isolated_db, capsys):
    rc = cli.main(
        [
            "add-trade",
            "--symbol",
            "EURUSD",
            "--side",
            "sideways",
            "--opened-at",
            "2025-03-01",
            "--entry-price",
            "1.1",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "invalid trade input" in err


def test_export_csv_and_json(isolated_db, tmp_path, capsys):
    cli.main(["seed-demo"])
    capsys.readouterr()
    rc = cli.main(["export-csv", "--out", str(tmp_path / "exp")])
    capsys.readouterr()
    assert rc == 0
    assert (tmp_path / "exp" / "trades.csv").exists()

    rc = cli.main(["export-json", "--out", str(tmp_path / "exp")])
    capsys.readouterr()
    assert rc == 0
    assert (tmp_path / "exp" / "export.json").exists()


def test_backup_and_restore_roundtrip(isolated_db, tmp_path, capsys):
    cli.main(["seed-demo"])
    capsys.readouterr()

    rc = cli.main(["backup", "--out", str(tmp_path / "bk")])
    assert rc == 0
    zips = list((tmp_path / "bk").glob("*.zip"))
    assert len(zips) == 1

    # Restore without --yes must refuse.
    rc = cli.main(["restore-backup", str(zips[0])])
    assert rc == 1

    # With --yes it restores and the data is intact.
    rc = cli.main(["restore-backup", str(zips[0]), "--yes"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Restored" in out
    with session_scope() as session:
        assert session.query(Trade).count() > 0


def test_data_quality_command(isolated_db, capsys):
    cli.main(["seed-demo"])
    capsys.readouterr()
    rc = cli.main(["data-quality", "--limit", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Data-quality checks" in out
    assert "Trades needing review" in out


def test_review_day_saves_and_shows(isolated_db, capsys):
    cli.main(["seed-demo"])
    capsys.readouterr()
    rc = cli.main(["review-day", "2025-05-05", "--notes", "good day", "--discipline", "80"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Day review" in out
    assert "Daily review saved." in out
    with session_scope() as session:
        review = session.query(DailyReview).one()
        assert review.notes == "good day"
        assert review.discipline_score == 80


def test_review_day_bad_date(isolated_db, capsys):
    rc = cli.main(["review-day", "not-a-date"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "could not parse date" in err


def test_existing_commands_still_work(isolated_db, capsys):
    # Phase 1/2 commands must be unchanged.
    assert cli.main(["init-db"]) == 0
    assert cli.main(["seed-demo"]) == 0
    assert cli.main(["metrics"]) == 0
    capsys.readouterr()
    assert cli.main(["sync-status"]) == 0
