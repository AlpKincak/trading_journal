"""Tests for the trade service: manual entry, derived fields, and filtering."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from trading_journal.models import TradeStatus
from trading_journal.services.account_service import (
    add_snapshot,
    get_or_create_default_account,
    latest_snapshot,
)
from trading_journal.services.trade_service import (
    ManualTradeInput,
    add_trade,
    get_open_positions,
    list_trades,
    recalculate_derived,
)


def _closed_input(**overrides) -> ManualTradeInput:
    data = {
        "symbol": "eurusd",
        "side": "buy",
        "status": "closed",
        "opened_at": datetime(2025, 3, 1, 9, 0),
        "closed_at": datetime(2025, 3, 1, 15, 0),
        "entry_price": 1.1000,
        "exit_price": 1.1100,
        "stop_loss": 1.0950,
        "take_profit": 1.1150,
        "gross_pnl": 210.0,
        "fees": 10.0,
    }
    data.update(overrides)
    return ManualTradeInput(**data)


def test_add_trade_normalizes_and_derives_price_r(session):
    account = get_or_create_default_account(session)
    trade = add_trade(session, account.id, _closed_input())

    assert trade.symbol == "EURUSD"
    assert trade.side == "BUY"
    assert trade.status == "CLOSED"
    # net_pnl derived from gross - fees.
    assert trade.net_pnl == pytest.approx(200.0)
    assert trade.planned_rr == pytest.approx(3.0)
    # No initial_risk_amount -> price-based R.
    assert trade.r_method == "price"
    assert trade.realized_r == pytest.approx(2.0)


def test_add_trade_prefers_money_r(session):
    account = get_or_create_default_account(session)
    trade = add_trade(session, account.id, _closed_input(initial_risk_amount=100.0))
    assert trade.r_method == "money"
    assert trade.realized_r == pytest.approx(2.0)  # net 200 / risk 100


def test_open_trade_has_no_realized_r(session):
    account = get_or_create_default_account(session)
    data = ManualTradeInput(
        symbol="EURUSD",
        side="sell",
        status="open",
        opened_at=datetime(2025, 3, 2, 9, 0),
        entry_price=1.1000,
        stop_loss=1.1050,
        take_profit=1.0900,
    )
    trade = add_trade(session, account.id, data)
    assert trade.status == "OPEN"
    assert trade.realized_r is None
    assert trade.r_method is None
    # Planned RR is still known for an open trade.
    assert trade.planned_rr == pytest.approx(2.0)


def test_manual_trade_input_rejects_bad_side():
    with pytest.raises(ValidationError):
        ManualTradeInput(
            symbol="EURUSD",
            side="upways",
            opened_at=datetime(2025, 3, 1, 9, 0),
            entry_price=1.10,
        )


def test_recalculate_derived_updates_open_to_none():
    from trading_journal.models import Trade

    trade = Trade(
        account_id=1,
        symbol="EURUSD",
        side="BUY",
        status=TradeStatus.OPEN.value,
        opened_at=datetime(2025, 3, 1, 9, 0),
        entry_price=1.10,
        stop_loss=1.095,
        take_profit=1.115,
        realized_r=5.0,  # stale value that should be cleared for an open trade
    )
    recalculate_derived(trade)
    assert trade.realized_r is None
    assert trade.planned_rr == pytest.approx(3.0)


def test_list_trades_filters(session):
    account = get_or_create_default_account(session)
    add_trade(session, account.id, _closed_input(symbol="eurusd", side="buy"))
    add_trade(
        session,
        account.id,
        _closed_input(
            symbol="gbpusd",
            side="sell",
            entry_price=1.2000,
            exit_price=1.1900,
            stop_loss=1.2050,
            take_profit=1.1850,
        ),
    )
    add_trade(
        session,
        account.id,
        ManualTradeInput(
            symbol="EURUSD",
            side="buy",
            status="open",
            opened_at=datetime(2025, 3, 3, 9, 0),
            entry_price=1.10,
            stop_loss=1.095,
            take_profit=1.115,
        ),
    )

    assert len(list_trades(session)) == 3
    assert len(list_trades(session, symbol="EURUSD")) == 2
    assert len(list_trades(session, side="SELL")) == 1
    assert len(list_trades(session, status=TradeStatus.OPEN.value)) == 1

    open_positions = get_open_positions(session, account.id)
    assert len(open_positions) == 1
    assert open_positions[0].status == "OPEN"


def test_list_trades_date_filter(session):
    account = get_or_create_default_account(session)
    add_trade(session, account.id, _closed_input(opened_at=datetime(2025, 1, 5, 9, 0)))
    add_trade(session, account.id, _closed_input(opened_at=datetime(2025, 6, 5, 9, 0)))

    in_range = list_trades(session, start=date(2025, 5, 1), end=date(2025, 12, 31))
    assert len(in_range) == 1
    assert in_range[0].opened_at.month == 6


def test_snapshot_service_roundtrip(session):
    account = get_or_create_default_account(session)
    add_snapshot(
        session, account.id, balance=10000.0, equity=10000.0, timestamp=datetime(2025, 1, 1)
    )
    add_snapshot(
        session, account.id, balance=10500.0, equity=10600.0, timestamp=datetime(2025, 1, 8)
    )

    latest = latest_snapshot(session, account.id)
    assert latest is not None
    assert latest.balance == pytest.approx(10500.0)
