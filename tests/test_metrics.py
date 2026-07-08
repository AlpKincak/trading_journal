"""Tests for the metrics engine, R/RR calculations, and Journal Score."""

from __future__ import annotations

import math
from datetime import datetime

import pytest

from trading_journal.journal_score import (
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    compute_journal_score,
)
from trading_journal.metrics import (
    compute_metrics,
    compute_planned_rr,
    compute_realized_r,
)


def make_trade(**overrides):
    """Build a closed-trade dict with sensible defaults for metric tests."""
    base = {
        "symbol": "EURUSD",
        "side": "BUY",
        "status": "CLOSED",
        "opened_at": datetime(2025, 1, 1, 9, 0),
        "closed_at": datetime(2025, 1, 1, 12, 0),
        "entry_price": 1.1000,
        "exit_price": 1.1100,
        "stop_loss": 1.0950,
        "take_profit": 1.1150,
        "net_pnl": 100.0,
        "realized_r": 2.0,
        "planned_rr": 3.0,
        "initial_risk_amount": 50.0,
        "notes": "",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Planned RR
# ---------------------------------------------------------------------------
def test_planned_rr_buy():
    assert compute_planned_rr("BUY", 1.1000, 1.0950, 1.1150) == pytest.approx(3.0)


def test_planned_rr_sell():
    assert compute_planned_rr("SELL", 1.1000, 1.1050, 1.0900) == pytest.approx(2.0)


def test_planned_rr_invalid_returns_none():
    # Stop above entry on a BUY -> non-positive risk.
    assert compute_planned_rr("BUY", 1.1000, 1.1050, 1.1150) is None
    # Missing take profit.
    assert compute_planned_rr("BUY", 1.1000, 1.0950, None) is None


# ---------------------------------------------------------------------------
# Realized R
# ---------------------------------------------------------------------------
def test_realized_r_money_based():
    r, method = compute_realized_r(
        "BUY", 1.10, 1.11, 1.095, net_pnl=200.0, initial_risk_amount=100.0
    )
    assert r == pytest.approx(2.0)
    assert method == "money"


def test_realized_r_money_takes_precedence_over_price():
    # Even though price data is present, money-based R is preferred.
    r, method = compute_realized_r(
        "BUY", 1.10, 1.20, 1.095, net_pnl=50.0, initial_risk_amount=100.0
    )
    assert method == "money"
    assert r == pytest.approx(0.5)


def test_realized_r_price_based_buy():
    r, method = compute_realized_r("BUY", 1.10, 1.11, 1.095, net_pnl=None, initial_risk_amount=None)
    assert r == pytest.approx(2.0)
    assert method == "price"


def test_realized_r_price_based_sell():
    r, method = compute_realized_r(
        "SELL", 1.10, 1.09, 1.105, net_pnl=None, initial_risk_amount=None
    )
    assert r == pytest.approx(2.0)
    assert method == "price"


def test_realized_r_unknown():
    r, method = compute_realized_r("BUY", 1.10, None, None, net_pnl=None, initial_risk_amount=None)
    assert r is None
    assert method == "unknown"


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------
def test_no_trades_is_safe():
    m = compute_metrics([])
    assert m.net_pnl == 0.0
    assert m.trade_count == 0
    assert m.trade_win_pct is None
    assert m.profit_factor is None
    assert m.max_drawdown is None
    assert m.expectancy_r is None


def test_profit_factor_normal():
    trades = [
        make_trade(net_pnl=200.0),
        make_trade(net_pnl=100.0),
        make_trade(net_pnl=-100.0),
    ]
    m = compute_metrics(trades)
    assert m.gross_profit == pytest.approx(300.0)
    assert m.gross_loss == pytest.approx(-100.0)
    assert m.profit_factor == pytest.approx(3.0)


def test_profit_factor_no_losses_is_infinite():
    trades = [make_trade(net_pnl=200.0), make_trade(net_pnl=50.0)]
    m = compute_metrics(trades)
    assert math.isinf(m.profit_factor)


def test_profit_factor_only_losses_is_zero():
    trades = [make_trade(net_pnl=-200.0), make_trade(net_pnl=-50.0)]
    m = compute_metrics(trades)
    assert m.profit_factor == pytest.approx(0.0)


def test_win_rate_excludes_breakeven():
    trades = [
        make_trade(net_pnl=100.0),
        make_trade(net_pnl=100.0),
        make_trade(net_pnl=100.0),
        make_trade(net_pnl=-50.0),
        make_trade(net_pnl=-50.0),
        make_trade(net_pnl=0.0),  # breakeven, excluded from win %
    ]
    m = compute_metrics(trades)
    assert m.winning_trade_count == 3
    assert m.losing_trade_count == 2
    assert m.breakeven_trade_count == 1
    assert m.trade_win_pct == pytest.approx(60.0)


def test_open_trades_do_not_distort_closed_metrics():
    trades = [
        make_trade(net_pnl=100.0),
        make_trade(net_pnl=-50.0),
        make_trade(status="OPEN", net_pnl=None, closed_at=None, realized_r=None),
    ]
    m = compute_metrics(trades)
    assert m.closed_trade_count == 2
    assert m.open_trade_count == 1
    assert m.net_pnl == pytest.approx(50.0)


def test_day_win_pct_and_max_drawdown():
    # Four trading days with net P&L: +100, +50, -120, +30.
    trades = [
        make_trade(net_pnl=100.0, closed_at=datetime(2025, 1, 1, 12)),
        make_trade(net_pnl=50.0, closed_at=datetime(2025, 1, 2, 12)),
        make_trade(net_pnl=-120.0, closed_at=datetime(2025, 1, 3, 12)),
        make_trade(net_pnl=30.0, closed_at=datetime(2025, 1, 6, 12)),
    ]
    m = compute_metrics(trades)
    # 3 of 4 days are positive.
    assert m.day_win_pct == pytest.approx(75.0)
    # Cumulative: 100, 150, 30, 60. Peak 150 -> trough 30 => drawdown 120.
    assert m.max_drawdown == pytest.approx(120.0)


def test_expectancy_and_avg_r():
    trades = [
        make_trade(net_pnl=200.0, realized_r=2.0),
        make_trade(net_pnl=200.0, realized_r=2.0),
        make_trade(net_pnl=100.0, realized_r=1.0),
        make_trade(net_pnl=-100.0, realized_r=-1.0),
        make_trade(net_pnl=-100.0, realized_r=-1.0),
    ]
    m = compute_metrics(trades)
    # mean R = (2+2+1-1-1)/5 = 0.6
    assert m.avg_realized_r == pytest.approx(0.6)
    assert m.expectancy_r == pytest.approx(0.6)
    assert m.avg_win_r == pytest.approx((2 + 2 + 1) / 3)
    assert m.avg_loss_r == pytest.approx(-1.0)


def test_avg_planned_rr_includes_open_and_closed():
    trades = [
        make_trade(planned_rr=2.0),
        make_trade(planned_rr=4.0),
        make_trade(status="OPEN", net_pnl=None, closed_at=None, realized_r=None, planned_rr=3.0),
    ]
    m = compute_metrics(trades)
    assert m.avg_planned_rr == pytest.approx(3.0)


def test_latest_balance_and_equity_from_snapshots():
    trades = [make_trade(net_pnl=100.0)]
    snaps = [
        {"timestamp": datetime(2025, 1, 1), "balance": 10000.0, "equity": 10000.0},
        {"timestamp": datetime(2025, 1, 8), "balance": 10250.0, "equity": 10310.0},
    ]
    m = compute_metrics(trades, snaps)
    assert m.latest_balance == pytest.approx(10250.0)
    assert m.latest_equity == pytest.approx(10310.0)


# ---------------------------------------------------------------------------
# Journal Score
# ---------------------------------------------------------------------------
def _component(score, key):
    return next(c for c in score.components if c.key == key)


def test_journal_score_components_full():
    winners = [
        make_trade(
            net_pnl=200.0, realized_r=2.0, r_method="money", notes="reviewed" if i < 5 else ""
        )
        for i in range(6)
    ]
    losers = [
        make_trade(net_pnl=-100.0, realized_r=-1.0, r_method="money", exit_price=1.0950)
        for _ in range(4)
    ]
    score = compute_journal_score(winners + losers)

    # Phase 3 rubric: 25 / 20 / 20 / 15 / 12 / 8 = 100.
    assert _component(score, "completeness").points == pytest.approx(25.0)
    assert _component(score, "risk_tracking").points == pytest.approx(20.0)
    assert _component(score, "risk_control").points == pytest.approx(20.0)
    assert _component(score, "performance").points == pytest.approx(15.0)
    # 5 of 10 closed trades have notes (counted as reviewed) -> half of 12.
    assert _component(score, "trade_review").points == pytest.approx(6.0)
    # No daily reviews supplied -> 0 of the trading days covered.
    assert _component(score, "daily_review").points == pytest.approx(0.0)
    assert score.score == pytest.approx(86.0)
    assert score.confidence == CONFIDENCE_MEDIUM  # 10 closed trades


def test_journal_score_daily_review_component_rewards_coverage():
    import pandas as pd

    # Two closed trades on two distinct days; one day has a daily review.
    trades = [
        make_trade(net_pnl=100.0, closed_at=datetime(2025, 1, 1, 12)),
        make_trade(net_pnl=-50.0, closed_at=datetime(2025, 1, 2, 12)),
    ]
    reviews = pd.DataFrame({"review_date": [datetime(2025, 1, 1)]})
    score = compute_journal_score(trades, daily_reviews=reviews)
    daily = _component(score, "daily_review")
    # 1 of 2 trading days covered -> half of 8.
    assert daily.points == pytest.approx(4.0)


def test_journal_score_risk_control_low_confidence_without_losers():
    winners = [make_trade(net_pnl=100.0, realized_r=1.5, r_method="money") for _ in range(5)]
    score = compute_journal_score(winners)
    rc = _component(score, "risk_control")
    # Neutral half-credit, flagged low confidence, never misleading.
    assert rc.points == pytest.approx(10.0)
    assert rc.confidence == CONFIDENCE_LOW


def test_journal_score_risk_control_penalizes_blown_stops():
    winners = [make_trade(net_pnl=100.0, realized_r=1.5) for _ in range(6)]
    losers = [
        make_trade(net_pnl=-100.0, realized_r=-1.0),
        make_trade(net_pnl=-300.0, realized_r=-3.0),  # blew through the stop
    ]
    score = compute_journal_score(winners + losers)
    rc = _component(score, "risk_control")
    # 1 of 2 losers respected R >= -1.2 -> half of 20.
    assert rc.points == pytest.approx(10.0)
