"""Tests for CSV column-alias normalization, validation, and duplicate prevention."""

from __future__ import annotations

import pandas as pd

from trading_journal.importers.csv_importer import (
    import_parsed,
    normalize_columns,
    parse_trades_frame,
)
from trading_journal.services.account_service import get_or_create_default_account


def test_normalize_columns_maps_aliases():
    df = pd.DataFrame(
        columns=[
            "Pair",
            "Direction",
            "Open Time",
            "Close Time",
            "Entry",
            "Exit",
            "SL",
            "TP",
            "Profit",
            "Risk",
            "Ticket",
        ]
    )
    out = normalize_columns(df)
    expected = {
        "symbol",
        "side",
        "opened_at",
        "closed_at",
        "entry_price",
        "exit_price",
        "stop_loss",
        "take_profit",
        "net_pnl",
        "initial_risk_amount",
        "external_id",
    }
    assert expected.issubset(set(out.columns))


def test_parse_normalizes_side_status_and_derives_rr():
    df = pd.DataFrame(
        [
            {
                "pair": "EURUSD",
                "direction": "long",
                "status": "closed",
                "open_time": "2025-01-01 09:00",
                "close_time": "2025-01-01 12:00",
                "entry": "1.1000",
                "exit": "1.1100",
                "sl": "1.0950",
                "tp": "1.1150",
                "profit": "200",
                "risk": "100",
            }
        ]
    )
    parsed = parse_trades_frame(df)
    assert parsed.ok_count == 1
    trade = parsed.trades[0]
    assert trade["side"] == "BUY"
    assert trade["status"] == "CLOSED"
    assert round(trade["planned_rr"], 2) == 3.0
    assert round(trade["realized_r"], 2) == 2.0
    assert trade["r_method"] == "money"


def test_parse_messy_numbers_and_dollar_signs():
    df = pd.DataFrame(
        [
            {
                "symbol": "EURUSD",
                "side": "sell",
                "opened_at": "2025-02-03",
                "closed_at": "2025-02-04",
                "entry_price": "1.2000",
                "exit_price": "1.1900",
                "stop_loss": "1.2050",
                "net_pnl": "$1,250.50",
                "fees": "(12.50)",
            }
        ]
    )
    parsed = parse_trades_frame(df)
    assert parsed.ok_count == 1
    trade = parsed.trades[0]
    assert trade["net_pnl"] == 1250.50
    assert trade["fees"] == -12.50
    assert trade["status"] == "CLOSED"  # inferred from close time


def test_validation_reports_missing_required_fields():
    df = pd.DataFrame(
        [
            {"symbol": "", "side": "BUY", "entry_price": "1.1", "opened_at": "2025-01-01"},
            {"symbol": "EURUSD", "side": "wat", "entry_price": "1.1", "opened_at": "2025-01-01"},
            {"symbol": "EURUSD", "side": "BUY", "entry_price": "abc", "opened_at": "2025-01-01"},
        ]
    )
    parsed = parse_trades_frame(df)
    assert parsed.ok_count == 0
    assert parsed.error_count == 3
    assert any("symbol" in e for e in parsed.row_errors[0].errors)
    assert any("side" in e for e in parsed.row_errors[1].errors)
    assert any("entry_price" in e for e in parsed.row_errors[2].errors)


def test_missing_stop_produces_warning_but_imports():
    df = pd.DataFrame(
        [
            {
                "symbol": "EURUSD",
                "side": "BUY",
                "status": "CLOSED",
                "opened_at": "2025-01-01",
                "closed_at": "2025-01-02",
                "entry_price": "1.1000",
                "exit_price": "1.1100",
                "initial_risk_amount": "100",
                "net_pnl": "150",
            }
        ]
    )
    parsed = parse_trades_frame(df)
    assert parsed.ok_count == 1
    assert any("missing stop loss" in w for w in parsed.warnings)
    # Money-based R still works despite no stop.
    assert parsed.trades[0]["r_method"] == "money"


def _dup_frame():
    return pd.DataFrame(
        [
            {
                "external_id": "X-1",
                "symbol": "EURUSD",
                "side": "BUY",
                "status": "CLOSED",
                "opened_at": "2025-01-01",
                "closed_at": "2025-01-02",
                "entry_price": "1.1000",
                "exit_price": "1.1100",
                "stop_loss": "1.0950",
                "net_pnl": "100",
            }
        ]
    )


def test_duplicate_prevention_across_imports(session):
    account = get_or_create_default_account(session)
    session.flush()

    first = import_parsed(session, account.id, parse_trades_frame(_dup_frame()))
    second = import_parsed(session, account.id, parse_trades_frame(_dup_frame()))

    assert first.imported == 1
    assert first.skipped_duplicates == 0
    assert second.imported == 0
    assert second.skipped_duplicates == 1


def test_duplicate_prevention_within_single_file(session):
    account = get_or_create_default_account(session)
    session.flush()

    frame = pd.concat([_dup_frame(), _dup_frame()], ignore_index=True)
    result = import_parsed(session, account.id, parse_trades_frame(frame))

    assert result.imported == 1
    assert result.skipped_duplicates == 1
