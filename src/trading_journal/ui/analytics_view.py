"""Analytics tab: non-strategy risk & R analytics.

Deliberately free of strategy/setup breakdowns — all analytics are generic
(R distribution, streaks, durations, risk consistency, and simple
weekday/symbol/side splits).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from trading_journal.analytics import compute_risk_analytics
from trading_journal.formatting import fmt_money, fmt_num, fmt_pct, fmt_r
from trading_journal.ui import charts
from trading_journal.ui.common import kpi


def _fmt_hours(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 48:
        return f"{value / 24:.1f} d"
    return f"{value:.1f} h"


def render_analytics(trades: pd.DataFrame) -> None:
    st.subheader("Risk & R analytics")
    if trades.empty:
        st.info("No trades yet. Import data or add a manual trade to see analytics.")
        return

    a = compute_risk_analytics(trades)
    if a.closed_trade_count == 0:
        st.info("No closed trades yet — analytics appear once trades are closed.")
        return

    r1 = st.columns(4)
    kpi(r1[0], "Total realized R", fmt_r(a.total_realized_r))
    kpi(r1[1], "Avg realized R", fmt_r(a.avg_realized_r))
    kpi(r1[2], "Median R", fmt_r(a.median_realized_r))
    kpi(r1[3], "R std dev", fmt_num(a.std_realized_r))

    r2 = st.columns(4)
    kpi(r2[0], "Best R", fmt_r(a.best_r))
    kpi(r2[1], "Worst R", fmt_r(a.worst_r))
    kpi(r2[2], "Avg planned RR", fmt_num(a.avg_planned_rr))
    kpi(r2[3], "Median planned RR", fmt_num(a.median_planned_rr))

    r3 = st.columns(4)
    kpi(r3[0], "Max consecutive wins", str(a.max_consecutive_wins))
    kpi(r3[1], "Max consecutive losses", str(a.max_consecutive_losses))
    streak = f"{a.current_streak:+d} ({'W' if a.current_streak > 0 else 'L' if a.current_streak < 0 else '—'})"
    kpi(r3[2], "Current streak", streak)
    kpi(r3[3], "Avg trade duration", _fmt_hours(a.avg_trade_duration_hours))

    r4 = st.columns(4)
    kpi(r4[0], "Avg winner duration", _fmt_hours(a.avg_winner_duration_hours))
    kpi(r4[1], "Avg loser duration", _fmt_hours(a.avg_loser_duration_hours))
    kpi(r4[2], "Largest winning day", fmt_money(a.largest_winning_day))
    kpi(r4[3], "Largest losing day", fmt_money(a.largest_losing_day))

    st.divider()

    c1, c2 = st.columns(2)
    fig = charts.cumulative_r_line(a.cumulative_r)
    if fig:
        c1.plotly_chart(fig, width="stretch", key="an_cum_r")
    else:
        c1.info("No realized R values to plot yet.")
    fig = charts.realized_r_hist(trades)
    if fig:
        c2.plotly_chart(fig, width="stretch", key="an_r_hist")

    c3, c4 = st.columns(2)
    fig = charts.planned_rr_hist(a.planned_rr_values)
    if fig:
        c3.plotly_chart(fig, width="stretch", key="an_planned_rr")
    else:
        c3.info("No planned RR values to plot yet.")
    fig = charts.weekday_bar(a.weekday_performance)
    if fig:
        c4.plotly_chart(fig, width="stretch", key="an_weekday")

    st.divider()
    _render_risk_consistency(a)
    _render_r_quality(a)
    _render_breakdowns(a)


def _render_risk_consistency(a) -> None:
    st.subheader("Risk consistency")
    st.caption("How consistent your dollar risk per trade is (money-based risk only).")
    cols = st.columns(5)
    kpi(cols[0], "Avg risk", fmt_money(a.avg_initial_risk))
    kpi(cols[1], "Median risk", fmt_money(a.median_initial_risk))
    kpi(cols[2], "Min risk", fmt_money(a.min_initial_risk))
    kpi(cols[3], "Max risk", fmt_money(a.max_initial_risk))
    cv = (
        None if a.risk_coefficient_of_variation is None else a.risk_coefficient_of_variation * 100.0
    )
    kpi(
        cols[4],
        "Risk variability (CV)",
        fmt_pct(cv),
        "Coefficient of variation of risk — lower is more consistent.",
    )
    if a.risk_sample_size < 2:
        st.caption("Not enough money-based risk data yet for a variability figure.")


def _render_r_quality(a) -> None:
    st.subheader("Risk-multiple quality")
    st.caption("How your realized R was derived across closed trades.")
    cols = st.columns(4)
    kpi(cols[0], "Money-based R", fmt_pct(a.pct_money_r))
    kpi(cols[1], "Price-estimated R", fmt_pct(a.pct_price_r))
    kpi(cols[2], "Manual R", fmt_pct(a.pct_manual_r))
    kpi(cols[3], "Unknown R", fmt_pct(a.pct_unknown_r))


def _render_breakdowns(a) -> None:
    st.subheader("Breakdowns")
    st.caption("Generic splits (not strategy-specific).")
    tab_wd, tab_sym, tab_side = st.tabs(["By weekday", "By symbol", "By side"])
    with tab_wd:
        _show_perf_table(a.weekday_performance)
    with tab_sym:
        _show_perf_table(a.symbol_performance)
    with tab_side:
        _show_perf_table(a.side_performance)


def _show_perf_table(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.caption("No data yet.")
        return
    out = df.copy()
    for col in ("net_pnl", "avg_realized_r", "win_rate"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(3)
    st.dataframe(out, hide_index=True, width="stretch")
