"""Calendar / Reviews tab: monthly heatmap, per-day detail, and daily reviews."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from trading_journal.db import session_scope
from trading_journal.formatting import fmt_money, fmt_r
from trading_journal.metrics import compute_metrics, day_detail, trades_on_day
from trading_journal.services.review_service import (
    DailyReviewInput,
    daily_reviews_dataframe,
    get_daily_review,
    upsert_daily_review,
)
from trading_journal.ui import charts
from trading_journal.ui.common import TRADE_DISPLAY_COLUMNS, kpi, prep_display


def _load_review(account_id: int | None, day: date) -> dict | None:
    with session_scope() as session:
        review = get_daily_review(session, account_id, day)
        if review is None:
            return None
        return {
            "notes": review.notes,
            "mood": review.mood,
            "discipline_score": review.discipline_score,
            "risk_score": review.risk_score,
            "execution_score": review.execution_score,
            "lesson": review.lesson,
        }


def _render_day_detail(trades: pd.DataFrame, day: date) -> None:
    detail = day_detail(trades, day)
    c = st.columns(4)
    kpi(c[0], "Net P&L", fmt_money(detail.net_pnl))
    kpi(c[1], "Total realized R", fmt_r(detail.total_realized_r))
    kpi(c[2], "Avg realized R", fmt_r(detail.avg_realized_r))
    kpi(c[3], "Trades", str(detail.trade_count))

    c2 = st.columns(4)
    kpi(
        c2[0],
        "Wins / Losses / BE",
        f"{detail.winning_count} / {detail.losing_count} / {detail.breakeven_count}",
    )
    kpi(c2[1], "Closed / opened", f"{detail.closed_count} / {detail.open_count}")
    best = detail.best_trade.get("net_pnl") if detail.best_trade else None
    worst = detail.worst_trade.get("net_pnl") if detail.worst_trade else None
    kpi(c2[2], "Best trade", fmt_money(best))
    kpi(c2[3], "Worst trade", fmt_money(worst))

    day_trades = trades_on_day(trades, day)
    if day_trades.empty:
        st.caption("No trades opened or closed on this day.")
    else:
        st.dataframe(
            prep_display(day_trades.sort_values("opened_at"), TRADE_DISPLAY_COLUMNS),
            hide_index=True,
            width="stretch",
        )


def _render_review_form(account_id: int | None, day: date) -> None:
    existing = _load_review(account_id, day) or {}
    st.subheader("Daily review")
    with st.form(f"daily_review_{day}"):
        notes = st.text_area("Notes", value=str(existing.get("notes") or ""))
        c = st.columns(4)
        discipline = c[0].number_input(
            "Discipline (0-100)",
            min_value=0,
            max_value=100,
            value=int(existing.get("discipline_score") or 0),
        )
        risk = c[1].number_input(
            "Risk (0-100)", min_value=0, max_value=100, value=int(existing.get("risk_score") or 0)
        )
        execution = c[2].number_input(
            "Execution (0-100)",
            min_value=0,
            max_value=100,
            value=int(existing.get("execution_score") or 0),
        )
        mood = c[3].text_input("Mood", value=str(existing.get("mood") or ""))
        lesson = st.text_area("Lesson", value=str(existing.get("lesson") or ""))
        submitted = st.form_submit_button("Save daily review", type="primary")

    if submitted:
        try:
            payload = DailyReviewInput(
                review_date=day,
                notes=notes or None,
                mood=mood or None,
                discipline_score=int(discipline),
                risk_score=int(risk),
                execution_score=int(execution),
                lesson=lesson or None,
            )
            with session_scope() as session:
                upsert_daily_review(session, account_id, payload)
            st.success("Daily review saved.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001 - surface validation errors to the user
            st.error(f"Could not save review: {exc}")


def render_calendar_reviews(account_id: int | None, trades: pd.DataFrame) -> None:
    st.subheader("Calendar")
    if trades.empty:
        st.info("No trades yet. Import data or add a manual trade to populate the calendar.")
    else:
        metrics = compute_metrics(trades)
        fig = charts.calendar_heatmap(metrics.daily)
        if fig:
            st.plotly_chart(fig, width="stretch", key="rev_cal")
        else:
            st.caption("No closed-trade days to chart yet.")

    st.divider()
    st.subheader("Day detail")
    opened = pd.to_datetime(trades["opened_at"], errors="coerce") if not trades.empty else None
    default_day = (
        opened.max().date() if opened is not None and opened.notna().any() else date.today()
    )
    day = st.date_input("Select a day", value=default_day)
    if isinstance(day, (list, tuple)):
        day = day[0] if day else default_day

    if not trades.empty:
        _render_day_detail(trades, day)
    _render_review_form(account_id, day)

    st.divider()
    st.subheader("Recent daily reviews")
    with session_scope() as session:
        reviews = daily_reviews_dataframe(session, account_id=account_id, limit=30)
    if reviews.empty:
        st.caption("No daily reviews yet.")
    else:
        show = reviews[
            [
                "review_date",
                "discipline_score",
                "risk_score",
                "execution_score",
                "mood",
                "notes",
                "lesson",
            ]
        ]
        st.dataframe(show, hide_index=True, width="stretch")
