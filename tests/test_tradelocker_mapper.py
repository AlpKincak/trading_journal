"""Tests for pure TradeLocker -> local mapping."""

from __future__ import annotations

import pytest

from trading_journal.connectors.tradelocker.mapper import (
    MappingContext,
    account_details_to_dict,
    aggregate_position_legs,
    map_account,
    map_account_snapshot,
    map_closed_order,
    map_open_position,
    order_is_completed_trade,
)
from trading_journal.connectors.tradelocker.schemas import TradeLockerAccount

OPEN_MS = 1_719_800_000_000
CLOSE_MS = 1_719_900_000_000


def _ctx() -> MappingContext:
    return MappingContext(
        environment="demo",
        account_id="12345",
        acc_num="1",
        instruments={"278": "EURUSD"},
    )


def test_map_open_position_to_open_candidate():
    row = {
        "id": "1001",
        "tradableInstrumentId": "278",
        "side": "buy",
        "qty": "0.10",
        "avgPrice": "1.10000",
        "stopLossPrice": "1.09500",
        "takeProfitPrice": "1.11500",
        "openDate": OPEN_MS,
        "unrealizedPl": "12.50",
    }
    warnings: list[str] = []
    cand = map_open_position(row, _ctx(), warnings)
    assert cand is not None
    assert cand.status == "OPEN"
    assert cand.symbol == "EURUSD"  # resolved via instruments map
    assert cand.side == "BUY"
    assert cand.entry_price == pytest.approx(1.10)
    assert cand.stop_loss == pytest.approx(1.095)
    assert cand.take_profit == pytest.approx(1.115)
    assert cand.quantity == pytest.approx(0.10)
    assert cand.gross_pnl == pytest.approx(12.5)  # unrealized
    assert cand.net_pnl is None  # never a realized net for an open trade
    assert cand.external_position_id == "1001"
    assert cand.dedup_key == "tl:demo:12345:pos:1001"
    assert cand.key_confidence == "high"


def test_map_closed_order_to_closed_candidate():
    row = {
        "id": "9001",
        "positionId": "1001",
        "tradableInstrumentId": "278",
        "side": "buy",
        "qty": "0.10",
        "avgPrice": "1.10000",
        "closePrice": "1.11000",
        "stopLossPrice": "1.09500",
        "openDate": OPEN_MS,
        "closeDate": CLOSE_MS,
        "status": "Filled",
        "profit": "200.00",
        "fee": "-3.00",
        "swap": "-1.00",
    }
    warnings: list[str] = []
    cand = map_closed_order(row, _ctx(), warnings)
    assert cand is not None
    assert cand.status == "CLOSED"
    assert cand.symbol == "EURUSD"
    assert cand.side == "BUY"
    assert cand.entry_price == pytest.approx(1.10)
    assert cand.exit_price == pytest.approx(1.11)
    assert cand.net_pnl == pytest.approx(200.0)
    assert cand.fees == pytest.approx(4.0)  # |−3| + |−1|
    assert cand.closed_at is not None
    assert cand.external_position_id == "1001"
    assert cand.external_order_id == "9001"
    # Position id is preferred for the dedup key (shared with the open trade).
    assert cand.dedup_key == "tl:demo:12345:pos:1001"


def test_symbol_resolution_placeholder_when_unknown_instrument():
    row = {
        "id": "1",
        "tradableInstrumentId": "999",
        "side": "sell",
        "avgPrice": "1",
        "openDate": OPEN_MS,
    }
    warnings: list[str] = []
    cand = map_open_position(row, _ctx(), warnings)
    assert cand is not None
    assert cand.symbol == "INSTR_999"
    assert any("could not resolve symbol" in w for w in warnings)


def test_missing_required_fields_returns_none_with_warning():
    row = {"id": "1", "side": "buy", "openDate": OPEN_MS}  # no symbol/entry
    warnings: list[str] = []
    cand = map_open_position(row, _ctx(), warnings)
    assert cand is None
    assert any("missing" in w for w in warnings)


def test_closed_order_without_ids_uses_composite_low_confidence():
    row = {
        "symbol": "EURUSD",
        "side": "buy",
        "avgPrice": "1.1000",
        "closePrice": "1.1100",
        "openDate": OPEN_MS,
        "closeDate": CLOSE_MS,
        "profit": "50",
    }
    warnings: list[str] = []
    cand = map_closed_order(row, _ctx(), warnings)
    assert cand is not None
    assert cand.key_confidence == "low"
    assert cand.dedup_key.startswith("tl:cmp:")


def test_order_is_completed_trade():
    assert order_is_completed_trade({"status": "Filled"}) is True
    assert order_is_completed_trade({"status": "Cancelled"}) is False
    assert order_is_completed_trade({"status": "Rejected"}) is False
    assert order_is_completed_trade({"filledQty": "0.5"}) is True
    assert order_is_completed_trade({"filledQty": "0"}) is False
    assert order_is_completed_trade({"profit": "10"}) is True  # unknown status, has P&L


def test_profit_only_assumed_net_emits_warning():
    row = {
        "symbol": "EURUSD",
        "side": "buy",
        "avgPrice": "1.1",
        "openDate": OPEN_MS,
        "profit": "80",
    }
    warnings: list[str] = []
    cand = map_closed_order(row, _ctx(), warnings)
    assert cand.net_pnl == pytest.approx(80.0)
    assert cand.gross_pnl == pytest.approx(80.0)
    assert any("assumed to be net" in w for w in cand.warnings)


def test_aggregate_position_legs_sums_pnl_and_warns():
    ctx = _ctx()
    leg1 = map_closed_order(
        {
            "positionId": "1001",
            "id": "1",
            "tradableInstrumentId": "278",
            "side": "buy",
            "qty": "0.05",
            "avgPrice": "1.1000",
            "closePrice": "1.1050",
            "openDate": OPEN_MS,
            "closeDate": OPEN_MS + 1000,
            "profit": "50",
            "status": "Filled",
        },
        ctx,
        [],
    )
    leg2 = map_closed_order(
        {
            "positionId": "1001",
            "id": "2",
            "tradableInstrumentId": "278",
            "side": "buy",
            "qty": "0.05",
            "avgPrice": "1.1050",
            "closePrice": "1.1100",
            "openDate": OPEN_MS + 2000,
            "closeDate": CLOSE_MS,
            "profit": "70",
            "status": "Filled",
        },
        ctx,
        [],
    )
    warnings: list[str] = []
    agg = aggregate_position_legs([leg1, leg2], warnings)
    assert agg.net_pnl == pytest.approx(120.0)  # 50 + 70
    assert agg.quantity == pytest.approx(0.10)  # 0.05 + 0.05
    assert agg.dedup_key == "tl:demo:12345:pos:1001"
    assert any("aggregated into one trade" in w for w in warnings)


def test_map_account():
    tl = TradeLockerAccount(account_id="12345", acc_num="1", currency="EUR", name="Live")
    cand = map_account(tl, "live")
    assert cand.external_id == "12345"
    assert cand.external_account_number == "1"
    assert cand.broker == "TradeLocker"
    assert cand.base_currency == "EUR"
    assert cand.environment == "live"
    assert "live" in cand.name


def test_map_account_snapshot():
    snap = map_account_snapshot({"balance": "10250.00", "equity": "10275.50"})
    assert snap is not None
    assert snap.balance == pytest.approx(10250.0)
    assert snap.equity == pytest.approx(10275.5)

    # Equity-only: uses equity as balance and warns.
    eq_only = map_account_snapshot({"equity": "500"})
    assert eq_only.balance == pytest.approx(500.0)
    assert any("used equity as balance" in w for w in eq_only.warnings)

    assert map_account_snapshot({}) is None


def test_account_details_to_dict_pair_and_flat_forms():
    pairs = [{"id": "balance", "value": "100"}, {"id": "equity", "value": "200"}]
    assert account_details_to_dict(pairs) == {"balance": "100", "equity": "200"}
    flat = [{"balance": "100", "equity": "200"}]
    assert account_details_to_dict(flat) == {"balance": "100", "equity": "200"}
