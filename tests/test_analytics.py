"""Tests for the non-strategy risk & R analytics engine."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from trading_journal.analytics import _streaks, compute_risk_analytics


def _trade(day, net_pnl, realized_r, *, duration_h=2.0, symbol="EURUSD", side="BUY", risk=100.0):
    closed = datetime(2025, 1, day, 15, 0)
    return {
        "symbol": symbol,
        "side": side,
        "status": "CLOSED",
        "opened_at": closed - timedelta(hours=duration_h),
        "closed_at": closed,
        "entry_price": 1.10,
        "exit_price": 1.11,
        "stop_loss": 1.095,
        "net_pnl": net_pnl,
        "realized_r": realized_r,
        "r_method": "money",
        "planned_rr": 2.0,
        "initial_risk_amount": risk,
    }


def _dataset():
    # Chronological W W L W L L.
    return [
        _trade(1, 100.0, 1.0, duration_h=2.0),
        _trade(2, 100.0, 1.0, duration_h=2.0),
        _trade(3, -100.0, -1.0, duration_h=4.0),
        _trade(4, 100.0, 1.0, duration_h=2.0),
        _trade(5, -100.0, -1.0, duration_h=4.0),
        _trade(6, -100.0, -1.0, duration_h=4.0),
    ]


def test_empty_analytics_is_safe():
    a = compute_risk_analytics([])
    assert a.closed_trade_count == 0
    assert a.total_realized_r == 0.0
    assert a.avg_realized_r is None
    assert a.median_realized_r is None
    assert a.std_realized_r is None
    assert a.max_consecutive_wins == 0
    assert a.cumulative_r.empty
    assert a.weekday_performance.empty


def test_r_distribution_stats():
    a = compute_risk_analytics(_dataset())
    assert a.total_realized_r == pytest.approx(0.0)
    assert a.avg_realized_r == pytest.approx(0.0)
    assert a.median_realized_r == pytest.approx(0.0)
    assert a.std_realized_r == pytest.approx((1.2) ** 0.5)  # sample std of ±1 values
    assert a.best_r == pytest.approx(1.0)
    assert a.worst_r == pytest.approx(-1.0)


def test_cumulative_r_curve():
    a = compute_risk_analytics(_dataset())
    assert list(a.cumulative_r["cumulative_realized_r"]) == pytest.approx([1, 2, 1, 2, 1, 0])


def test_streaks_helper():
    assert _streaks([True, True, False, True, False, False]) == (2, 2, -2)
    assert _streaks([True, True, True]) == (3, 0, 3)
    assert _streaks([]) == (0, 0, 0)


def test_streaks_from_dataset():
    a = compute_risk_analytics(_dataset())
    assert a.max_consecutive_wins == 2
    assert a.max_consecutive_losses == 2
    assert a.current_streak == -2


def test_durations():
    a = compute_risk_analytics(_dataset())
    assert a.avg_trade_duration_hours == pytest.approx(3.0)  # (2*3 + 4*3)/6
    assert a.avg_winner_duration_hours == pytest.approx(2.0)
    assert a.avg_loser_duration_hours == pytest.approx(4.0)


def test_largest_days():
    a = compute_risk_analytics(_dataset())
    assert a.largest_winning_day == pytest.approx(100.0)
    assert a.largest_losing_day == pytest.approx(-100.0)


def test_risk_consistency():
    a = compute_risk_analytics(_dataset())
    assert a.avg_initial_risk == pytest.approx(100.0)
    assert a.median_initial_risk == pytest.approx(100.0)
    assert a.min_initial_risk == pytest.approx(100.0)
    assert a.max_initial_risk == pytest.approx(100.0)
    assert a.risk_coefficient_of_variation == pytest.approx(0.0)  # identical risks
    assert a.risk_sample_size == 6


def test_risk_multiple_quality_percentages():
    a = compute_risk_analytics(_dataset())
    assert a.pct_money_r == pytest.approx(100.0)
    assert a.pct_price_r == pytest.approx(0.0)
    assert a.pct_unknown_r == pytest.approx(0.0)


def test_symbol_and_side_breakdowns():
    trades = _dataset() + [_trade(7, 300.0, 3.0, symbol="GBPUSD", side="SELL")]
    a = compute_risk_analytics(trades)
    symbols = set(a.symbol_performance["symbol"])
    assert {"EURUSD", "GBPUSD"} <= symbols
    # net P&L across the weekday breakdown equals the total closed net P&L.
    assert a.weekday_performance["net_pnl"].sum() == pytest.approx(300.0)
    assert set(a.side_performance["side"]) == {"BUY", "SELL"}


def test_price_and_unknown_r_quality():
    trades = [
        _trade(1, 100.0, 1.0),  # money
        {**_trade(2, 50.0, 0.5), "r_method": "price"},
        {**_trade(3, None, None), "r_method": "unknown", "net_pnl": None, "realized_r": None},
    ]
    a = compute_risk_analytics(trades)
    assert a.pct_money_r == pytest.approx(100 / 3)
    assert a.pct_price_r == pytest.approx(100 / 3)
    assert a.pct_unknown_r == pytest.approx(100 / 3)
