"""Tests for local export, backup, and conservative restore (temp DBs only)."""

from __future__ import annotations

import json
from datetime import date, datetime
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from trading_journal.models import Trade
from trading_journal.services.account_service import add_snapshot, get_or_create_default_account
from trading_journal.services.backup_service import (
    create_backup,
    export_csv,
    export_json,
    inspect_backup,
    restore_backup,
)
from trading_journal.services.review_service import DailyReviewInput, upsert_daily_review
from trading_journal.services.trade_service import ManualTradeInput, add_trade


def _seed(session) -> int:
    account = get_or_create_default_account(session)
    add_trade(
        session,
        account.id,
        ManualTradeInput(
            symbol="EURUSD",
            side="buy",
            status="closed",
            opened_at=datetime(2025, 3, 1, 9, 0),
            closed_at=datetime(2025, 3, 1, 15, 0),
            entry_price=1.10,
            exit_price=1.11,
            stop_loss=1.095,
            gross_pnl=200.0,
        ),
    )
    add_snapshot(
        session, account.id, balance=10000.0, equity=10050.0, timestamp=datetime(2025, 3, 1)
    )
    upsert_daily_review(
        session, account.id, DailyReviewInput(review_date=date(2025, 3, 1), notes="ok")
    )
    session.commit()
    return account.id


def test_export_csv_creates_expected_files(session, tmp_path):
    _seed(session)
    paths = export_csv(session, tmp_path / "exp")
    names = {p.name for p in paths}
    assert names == {
        "accounts.csv",
        "trades.csv",
        "account_snapshots.csv",
        "daily_reviews.csv",
        "sync_runs.csv",
    }
    for p in paths:
        assert p.exists()


def test_export_json_structure(session, tmp_path):
    _seed(session)
    path = export_json(session, tmp_path / "exp")
    payload = json.loads(path.read_text())
    assert payload["manifest"]["app"] == "trading_journal"
    assert set(payload["tables"]) == {
        "accounts",
        "trades",
        "account_snapshots",
        "daily_reviews",
        "sync_runs",
    }
    assert len(payload["tables"]["trades"]) == 1
    assert payload["manifest"]["counts"]["trades"] == 1


def test_backup_zip_contains_manifest_and_database(session, tmp_path):
    _seed(session)
    zip_path = create_backup(session, tmp_path / "backups")
    assert zip_path.exists()
    with ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "test.db" in names  # the temp DB file name from the fixture
    assert "trades.csv" in names
    assert "export.json" in names


def test_inspect_backup_validates(session, tmp_path):
    _seed(session)
    zip_path = create_backup(session, tmp_path / "backups")
    info = inspect_backup(zip_path)
    assert info.valid
    assert info.database_file == "test.db"
    assert info.manifest["counts"]["trades"] == 1


def test_inspect_backup_rejects_bad_archive(tmp_path):
    bad = tmp_path / "not_a_backup.zip"
    with ZipFile(bad, "w") as zf:
        zf.writestr("random.txt", "hello")
    info = inspect_backup(bad)
    assert not info.valid
    assert info.problems


def test_restore_backup_into_temp_db(session, tmp_path):
    _seed(session)
    zip_path = create_backup(session, tmp_path / "backups")

    target = tmp_path / "restored.db"
    result = restore_backup(zip_path, target, make_backup=False)
    assert result.restored
    assert target.exists()

    engine = create_engine(f"sqlite:///{target}")
    factory = sessionmaker(bind=engine, class_=Session)
    with factory() as s2:
        assert s2.query(Trade).count() == 1


def test_restore_backs_up_current_db_first(session, tmp_path):
    _seed(session)
    zip_path = create_backup(session, tmp_path / "backups")

    # Restore over the *existing* fixture DB; a pre-restore copy must be made.
    target = tmp_path / "test.db"
    assert target.exists()
    result = restore_backup(zip_path, target, make_backup=True)
    assert result.backup_of_current is not None
    assert result.backup_of_current.exists()


def test_restore_rejects_invalid_backup(tmp_path):
    bad = tmp_path / "bad.zip"
    with ZipFile(bad, "w") as zf:
        zf.writestr("random.txt", "hello")
    with pytest.raises(ValueError):
        restore_backup(bad, tmp_path / "whatever.db")
