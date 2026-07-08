"""Tests for data-quality checks and the Needs-Review queue."""

from __future__ import annotations

import json
from datetime import datetime

from trading_journal.data_quality import (
    data_quality_report,
    duplicate_like_ids,
    needs_review_frame,
)


def _trade(**overrides):
    base = {
        "id": 1,
        "source": "manual",
        "symbol": "EURUSD",
        "side": "BUY",
        "status": "CLOSED",
        "opened_at": datetime(2025, 1, 1, 9, 0),
        "closed_at": datetime(2025, 1, 1, 12, 0),
        "entry_price": 1.10,
        "exit_price": 1.11,
        "stop_loss": 1.095,
        "take_profit": 1.115,
        "initial_risk_amount": 100.0,
        "net_pnl": 200.0,
        "realized_r": 2.0,
        "r_method": "money",
        "planned_rr": 3.0,
        "review_status": "UNREVIEWED",
    }
    base.update(overrides)
    return base


def _counts(report):
    return dict(zip(report["Check"], report["Count"], strict=True))


def test_empty_report_is_safe():
    report = data_quality_report([])
    assert not report.empty
    assert all(v == 0 for v in report["Count"])
    assert needs_review_frame([]).empty


def test_missing_net_pnl_flagged():
    trades = [_trade(id=1, net_pnl=None, realized_r=None, r_method="unknown")]
    counts = _counts(data_quality_report(trades))
    assert counts["Closed trades missing net P&L"] == 1


def test_missing_risk_flagged():
    trades = [_trade(id=1, initial_risk_amount=None, r_method="price")]
    counts = _counts(data_quality_report(trades))
    assert counts["Trades missing initial risk amount"] == 1


def test_invalid_planned_rr_flagged():
    # Stop and target are set, but planned RR could not be computed.
    trades = [_trade(id=1, planned_rr=None)]
    counts = _counts(data_quality_report(trades))
    assert counts["Trades with invalid planned RR"] == 1


def test_estimated_r_and_unknown_r_flagged():
    trades = [
        _trade(id=1, source="tradelocker", r_method="price", initial_risk_amount=None),
        _trade(id=2, r_method="unknown", realized_r=None),
    ]
    counts = _counts(data_quality_report(trades))
    assert counts["Synced trades with estimated (price) R"] == 1
    assert counts["Closed trades with unknown R"] == 1


def test_sync_conflict_flagged():
    flags = json.dumps({"sync_conflict": {"detail": ["stop_loss"], "at": "x"}})
    trades = [_trade(id=1, data_quality_flags_json=flags)]
    counts = _counts(data_quality_report(trades))
    assert counts["Synced trades with manual conflicts"] == 1


def test_needs_fix_flagged():
    trades = [_trade(id=1, review_status="NEEDS_FIX")]
    counts = _counts(data_quality_report(trades))
    assert counts["Trades marked Needs Fix"] == 1


def test_duplicate_like_detection():
    trades = [
        _trade(id=1),
        _trade(id=2),  # same symbol/side/open time as #1
        _trade(id=3, opened_at=datetime(2025, 2, 2, 9, 0)),
    ]
    dups = duplicate_like_ids(_frame(trades))
    assert set(dups) == {1, 2}


def test_needs_review_queue_annotates_reasons():
    trades = [
        _trade(id=1, review_status="NEEDS_FIX", opened_at=datetime(2025, 1, 1, 9, 0)),
        _trade(
            id=2,
            source="tradelocker",
            r_method="price",
            initial_risk_amount=None,
            opened_at=datetime(2025, 1, 2, 9, 0),
        ),
        _trade(id=3, opened_at=datetime(2025, 1, 3, 9, 0)),  # clean -> excluded
    ]
    queue = needs_review_frame(trades)
    ids = set(queue["id"])
    assert 1 in ids and 2 in ids
    assert 3 not in ids
    reason_for_1 = queue.loc[queue["id"] == 1, "reasons"].iloc[0]
    assert "NEEDS_FIX" in reason_for_1


def _frame(trades):
    from trading_journal.metrics import trades_to_dataframe

    return trades_to_dataframe(trades)
