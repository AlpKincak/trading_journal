"""Tests for the manual-correction and review workflow (trade_service)."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from trading_journal.models import ReviewStatus
from trading_journal.services.account_service import get_or_create_default_account
from trading_journal.services.trade_service import (
    ManualTradeInput,
    TradeEditInput,
    add_trade,
    apply_manual_correction,
    load_data_quality_flags,
    manual_locked_fields,
    mark_needs_fix,
    mark_reviewed,
)


def _closed(**overrides) -> ManualTradeInput:
    data = {
        "symbol": "EURUSD",
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


def _add(session, **overrides):
    account = get_or_create_default_account(session)
    return add_trade(session, account.id, _closed(**overrides))


def test_manual_entry_marks_source_and_is_manual(session):
    trade = _add(session)
    assert trade.source == "manual"
    assert trade.is_manual is True


def test_edit_recalculates_planned_rr(session):
    trade = _add(session)
    assert trade.planned_rr == pytest.approx(3.0)
    # Move the take-profit closer -> planned RR drops.
    apply_manual_correction(session, trade, TradeEditInput(take_profit=1.1100))
    assert trade.planned_rr == pytest.approx(2.0)


def test_edit_recalculates_realized_r(session):
    trade = _add(session)
    assert trade.r_method == "price"
    assert trade.realized_r == pytest.approx(2.0)
    # Providing a money risk switches R to money-based.
    apply_manual_correction(session, trade, TradeEditInput(initial_risk_amount=100.0))
    assert trade.r_method == "money"
    assert trade.realized_r == pytest.approx(2.0)  # net 200 / 100


def test_edit_stores_manual_overrides_with_old_and_new(session):
    trade = _add(session)
    apply_manual_correction(session, trade, TradeEditInput(stop_loss=1.0900))
    assert trade.has_manual_overrides is True
    assert "stop_loss" in manual_locked_fields(trade)
    import json

    log = json.loads(trade.manual_override_json)
    assert log["fields"]["stop_loss"]["new"] == pytest.approx(1.0900)
    assert log["fields"]["stop_loss"]["old"] == pytest.approx(1.0950)


def test_edit_no_change_does_not_lock(session):
    trade = _add(session)
    # Re-supplying the same value is not a change.
    apply_manual_correction(session, trade, TradeEditInput(stop_loss=1.0950))
    assert trade.has_manual_overrides is False
    assert manual_locked_fields(trade) == set()


def test_review_only_edit_does_not_lock_data(session):
    trade = _add(session)
    apply_manual_correction(
        session, trade, TradeEditInput(review_notes="clean exit", review_status="REVIEWED")
    )
    assert trade.review_status == ReviewStatus.REVIEWED.value
    assert trade.reviewed_at is not None
    assert trade.has_manual_overrides is False  # no data field locked


def test_explicit_realized_r_override(session):
    trade = _add(session)
    apply_manual_correction(
        session, trade, TradeEditInput(realized_r=1.5, override_realized_r=True)
    )
    assert trade.realized_r == pytest.approx(1.5)
    assert trade.r_method == "manual"
    assert "realized_r" in manual_locked_fields(trade)


def test_explicit_planned_rr_override_is_not_recomputed(session):
    trade = _add(session)
    apply_manual_correction(
        session, trade, TradeEditInput(planned_rr=9.9, override_planned_rr=True)
    )
    assert trade.planned_rr == pytest.approx(9.9)
    # A later, unrelated review edit must not recompute the locked planned RR.
    apply_manual_correction(session, trade, TradeEditInput(review_status="REVIEWED"))
    assert trade.planned_rr == pytest.approx(9.9)


def test_net_pnl_rederived_when_gross_or_fees_change(session):
    trade = _add(session)
    assert trade.net_pnl == pytest.approx(200.0)
    apply_manual_correction(session, trade, TradeEditInput(fees=20.0))
    assert trade.net_pnl == pytest.approx(190.0)  # 210 gross - 20 fees


def test_mark_reviewed_and_needs_fix(session):
    trade = _add(session)
    mark_reviewed(session, trade)
    assert trade.review_status == ReviewStatus.REVIEWED.value
    assert trade.reviewed_at is not None
    mark_needs_fix(session, trade)
    assert trade.review_status == ReviewStatus.NEEDS_FIX.value


def test_edit_rejects_bad_side(session):
    trade = _add(session)
    with pytest.raises(ValidationError):
        apply_manual_correction(session, trade, TradeEditInput(side="upways"))


def test_edit_rejects_bad_mistake_category(session):
    trade = _add(session)
    with pytest.raises(ValidationError):
        apply_manual_correction(session, trade, TradeEditInput(mistake_category="BAD_STRATEGY"))


def test_edit_clears_mistake_category_with_blank(session):
    trade = _add(session)
    apply_manual_correction(session, trade, TradeEditInput(mistake_category="LATE_ENTRY"))
    assert trade.mistake_category == "LATE_ENTRY"
    apply_manual_correction(session, trade, TradeEditInput(mistake_category=""))
    assert trade.mistake_category is None


def test_data_quality_flag_helpers_roundtrip(session):
    from trading_journal.services.trade_service import (
        add_data_quality_flag,
        clear_data_quality_flag,
    )

    trade = _add(session)
    add_data_quality_flag(trade, "sync_conflict", ["stop_loss"])
    flags = load_data_quality_flags(trade)
    assert flags["sync_conflict"]["detail"] == ["stop_loss"]
    clear_data_quality_flag(trade, "sync_conflict")
    assert "sync_conflict" not in load_data_quality_flags(trade)
