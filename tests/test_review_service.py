"""Tests for the daily-review service and per-day summary calculations."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from trading_journal.metrics import day_detail
from trading_journal.models import DailyReview
from trading_journal.services.account_service import get_or_create_default_account
from trading_journal.services.review_service import (
    DailyReviewInput,
    get_daily_review,
    list_daily_reviews,
    upsert_daily_review,
)
from trading_journal.services.trade_service import ManualTradeInput, add_trade


def test_create_and_update_daily_review_is_unique_per_day(session):
    account = get_or_create_default_account(session)
    upsert_daily_review(
        session,
        account.id,
        DailyReviewInput(review_date=date(2025, 3, 1), notes="first", discipline_score=70),
    )
    review = upsert_daily_review(
        session,
        account.id,
        DailyReviewInput(review_date=date(2025, 3, 1), notes="updated", discipline_score=90),
    )
    # Same (account, date) -> updated in place, not duplicated.
    assert session.query(DailyReview).count() == 1
    assert review.notes == "updated"
    assert review.discipline_score == 90


def test_get_daily_review_scoped_by_account_and_date(session):
    account = get_or_create_default_account(session)
    upsert_daily_review(
        session, account.id, DailyReviewInput(review_date=date(2025, 3, 1), lesson="stay patient")
    )
    found = get_daily_review(session, account.id, date(2025, 3, 1))
    assert found is not None and found.lesson == "stay patient"
    assert get_daily_review(session, account.id, date(2025, 3, 2)) is None


def test_daily_review_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        DailyReviewInput(review_date=date(2025, 3, 1), discipline_score=150)


def test_list_daily_reviews_orders_recent_first(session):
    account = get_or_create_default_account(session)
    for d in (date(2025, 3, 1), date(2025, 3, 5), date(2025, 3, 3)):
        upsert_daily_review(session, account.id, DailyReviewInput(review_date=d))
    reviews = list_daily_reviews(session, account.id)
    dates = [r.review_date for r in reviews]
    assert dates == [date(2025, 3, 5), date(2025, 3, 3), date(2025, 3, 1)]


def test_day_detail_summarizes_trades_for_a_day(session):
    account = get_or_create_default_account(session)
    common = {
        "symbol": "EURUSD",
        "side": "buy",
        "status": "closed",
        "opened_at": datetime(2025, 3, 1, 9, 0),
        "closed_at": datetime(2025, 3, 1, 15, 0),
        "entry_price": 1.10,
        "stop_loss": 1.095,
    }
    add_trade(
        session,
        account.id,
        ManualTradeInput(exit_price=1.11, initial_risk_amount=100.0, gross_pnl=200.0, **common),
    )
    add_trade(
        session,
        account.id,
        ManualTradeInput(exit_price=1.095, initial_risk_amount=100.0, gross_pnl=-100.0, **common),
    )

    from trading_journal.services.trade_service import trades_dataframe

    df = trades_dataframe(session, account_id=account.id)
    detail = day_detail(df, date(2025, 3, 1))
    assert detail.net_pnl == pytest.approx(100.0)  # +200 - 100
    assert detail.total_realized_r == pytest.approx(1.0)  # +2R - 1R
    assert detail.winning_count == 1
    assert detail.losing_count == 1
    assert detail.trade_count == 2
    assert detail.best_trade["net_pnl"] == pytest.approx(200.0)
    assert detail.worst_trade["net_pnl"] == pytest.approx(-100.0)


def test_day_detail_empty_is_safe(session):
    detail = day_detail([], date(2025, 3, 1))
    assert detail.net_pnl == 0.0
    assert detail.trade_count == 0
    assert detail.best_trade is None
