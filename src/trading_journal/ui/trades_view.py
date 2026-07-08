"""Trades tab: filters, tables, a trade detail/review panel, and manual entry.

All database writes go through the ``trade_service`` (manual entry, corrections,
review status). This module only collects form input and renders results.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from trading_journal.db import session_scope
from trading_journal.formatting import fmt_money, fmt_num, fmt_r
from trading_journal.models import MistakeCategory, ReviewStatus, Side, TradeStatus
from trading_journal.services.account_service import get_or_create_default_account
from trading_journal.services.trade_service import (
    ManualTradeInput,
    TradeEditInput,
    add_trade,
    apply_manual_correction,
    get_trade,
    load_data_quality_flags,
    manual_locked_fields,
    mark_needs_fix,
    mark_reviewed,
)
from trading_journal.ui.common import (
    OPEN_DISPLAY_COLUMNS,
    TRADE_DISPLAY_COLUMNS,
    load_symbols,
    load_trades,
    prep_display,
)

_DETAIL_COLUMNS = [
    "id",
    "account_id",
    "source",
    "symbol",
    "side",
    "status",
    "opened_at",
    "closed_at",
    "entry_price",
    "exit_price",
    "quantity",
    "stop_loss",
    "take_profit",
    "initial_risk_amount",
    "gross_pnl",
    "fees",
    "net_pnl",
    "planned_rr",
    "realized_r",
    "r_method",
    "notes",
    "review_status",
    "reviewed_at",
    "review_notes",
    "mistake_category",
    "exit_reason",
    "is_manual",
    "has_manual_overrides",
    "external_status",
    "external_position_id",
    "external_order_id",
    "last_synced_at",
]

_MISTAKE_OPTIONS = ["(none)"] + [m.value for m in MistakeCategory]
_REVIEW_OPTIONS = [s.value for s in ReviewStatus]


# ---------------------------------------------------------------------------
# Parsing helpers (blank -> None; raise ValueError on bad numbers/dates)
# ---------------------------------------------------------------------------
def _num(text: str | None) -> float | None:
    s = (text or "").strip()
    if s == "":
        return None
    return float(s.replace(",", ""))


def _dt(text: str | None) -> datetime | None:
    s = (text or "").strip()
    if s == "":
        return None
    return pd.to_datetime(s).to_pydatetime()


def _fmt_dt(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")


def _load_trade_detail(trade_id: int) -> dict | None:
    with session_scope() as session:
        trade = get_trade(session, trade_id)
        if trade is None:
            return None
        detail = {col: getattr(trade, col, None) for col in _DETAIL_COLUMNS}
        detail["locked_fields"] = sorted(manual_locked_fields(trade))
        detail["data_quality_flags"] = load_data_quality_flags(trade)
        return detail


# ---------------------------------------------------------------------------
# Detail + review panel
# ---------------------------------------------------------------------------
def _render_detail_facts(d: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Net P&L", fmt_money(d.get("net_pnl")))
    c2.metric("Realized R", fmt_r(d.get("realized_r")))
    c3.metric("Planned RR", fmt_num(d.get("planned_rr")))
    c4.metric("R method", str(d.get("r_method") or "—"))

    badges = [f"source: **{d.get('source') or '—'}**", f"status: **{d.get('status')}**"]
    if d.get("is_manual"):
        badges.append("**manual entry**")
    if d.get("has_manual_overrides"):
        badges.append(f"manual overrides: {', '.join(d['locked_fields']) or '—'}")
    if str(d.get("r_method") or "").lower() == "price":
        badges.append("R is *price-estimated*")
    st.caption(" · ".join(badges))

    if d.get("source") == "tradelocker":
        st.caption(
            f"Sync: external_status={d.get('external_status') or '—'} · "
            f"position={d.get('external_position_id') or '—'} · "
            f"order={d.get('external_order_id') or '—'} · "
            f"last_synced={_fmt_dt(d.get('last_synced_at')) or '—'}"
        )

    flags = d.get("data_quality_flags") or {}
    if flags:
        st.warning(
            "Data-quality flags: " + "; ".join(f"{k}: {v.get('detail')}" for k, v in flags.items())
        )


def _render_review_actions(trade_id: int, d: dict) -> None:
    st.write(f"**Review status:** `{d.get('review_status')}`")
    b1, b2, b3 = st.columns(3)
    if b1.button("✅ Mark reviewed", key=f"rev_{trade_id}", width="stretch"):
        with session_scope() as session:
            mark_reviewed(session, get_trade(session, trade_id))
        st.success("Marked reviewed.")
        st.rerun()
    if b2.button("🛠️ Needs fix", key=f"fix_{trade_id}", width="stretch"):
        with session_scope() as session:
            mark_needs_fix(session, get_trade(session, trade_id))
        st.warning("Marked needs-fix.")
        st.rerun()
    b3.caption("Or edit fields below and **Save corrections**.")


def _render_edit_form(trade_id: int, d: dict) -> None:
    with st.expander("Edit / correct this trade", expanded=False):
        with st.form(f"edit_trade_{trade_id}"):
            st.caption(
                "Blank a numeric/date field to clear it. planned_rr and realized_r are "
                "recomputed unless you tick the override boxes."
            )
            c1, c2, c3 = st.columns(3)
            symbol = c1.text_input("Symbol", value=str(d.get("symbol") or ""))
            side = c2.selectbox(
                "Side",
                options=[Side.BUY.value, Side.SELL.value],
                index=0 if str(d.get("side")) == Side.BUY.value else 1,
            )
            status = c3.selectbox(
                "Status",
                options=[TradeStatus.OPEN.value, TradeStatus.CLOSED.value],
                index=0 if str(d.get("status")) == TradeStatus.OPEN.value else 1,
            )

            t1, t2 = st.columns(2)
            opened_at = t1.text_input("Opened at", value=_fmt_dt(d.get("opened_at")))
            closed_at = t2.text_input("Closed at", value=_fmt_dt(d.get("closed_at")))

            p1, p2, p3 = st.columns(3)
            entry_price = p1.text_input("Entry price", value=_str_num(d.get("entry_price")))
            exit_price = p2.text_input("Exit price", value=_str_num(d.get("exit_price")))
            quantity = p3.text_input("Quantity", value=_str_num(d.get("quantity")))

            r1, r2, r3 = st.columns(3)
            stop_loss = r1.text_input("Stop loss", value=_str_num(d.get("stop_loss")))
            take_profit = r2.text_input("Take profit", value=_str_num(d.get("take_profit")))
            initial_risk = r3.text_input(
                "Initial risk amount", value=_str_num(d.get("initial_risk_amount"))
            )

            m1, m2, m3 = st.columns(3)
            gross_pnl = m1.text_input("Gross P&L", value=_str_num(d.get("gross_pnl")))
            fees = m2.text_input("Fees", value=_str_num(d.get("fees")))
            net_pnl = m3.text_input("Net P&L", value=_str_num(d.get("net_pnl")))

            o1, o2 = st.columns(2)
            override_planned = o1.checkbox("Override planned RR", value=False)
            planned_rr = o1.text_input("planned_rr", value=_str_num(d.get("planned_rr")))
            override_realized = o2.checkbox("Override realized R", value=False)
            realized_r = o2.text_input("realized_r", value=_str_num(d.get("realized_r")))

            review_status = st.selectbox(
                "Review status",
                options=_REVIEW_OPTIONS,
                index=_REVIEW_OPTIONS.index(str(d.get("review_status")))
                if str(d.get("review_status")) in _REVIEW_OPTIONS
                else 0,
            )
            cur_mistake = str(d.get("mistake_category") or "(none)")
            mistake = st.selectbox(
                "Mistake category",
                options=_MISTAKE_OPTIONS,
                index=_MISTAKE_OPTIONS.index(cur_mistake) if cur_mistake in _MISTAKE_OPTIONS else 0,
            )
            exit_reason = st.text_input("Exit reason", value=str(d.get("exit_reason") or ""))
            notes = st.text_area("Notes", value=str(d.get("notes") or ""))
            review_notes = st.text_area("Review notes", value=str(d.get("review_notes") or ""))

            submitted = st.form_submit_button("Save corrections", type="primary")

        if submitted:
            try:
                kwargs = dict(
                    symbol=symbol,
                    side=side,
                    status=status,
                    opened_at=_dt(opened_at),
                    closed_at=_dt(closed_at),
                    entry_price=_num(entry_price),
                    exit_price=_num(exit_price),
                    quantity=_num(quantity),
                    stop_loss=_num(stop_loss),
                    take_profit=_num(take_profit),
                    initial_risk_amount=_num(initial_risk),
                    gross_pnl=_num(gross_pnl),
                    fees=_num(fees),
                    net_pnl=_num(net_pnl),
                    review_status=review_status,
                    exit_reason=exit_reason or None,
                    notes=notes or None,
                    review_notes=review_notes or None,
                    mistake_category=None if mistake == "(none)" else mistake,
                )
                if override_planned:
                    kwargs["planned_rr"] = _num(planned_rr)
                    kwargs["override_planned_rr"] = True
                if override_realized:
                    kwargs["realized_r"] = _num(realized_r)
                    kwargs["override_realized_r"] = True
                edit = TradeEditInput(**kwargs)
                with session_scope() as session:
                    apply_manual_correction(session, get_trade(session, trade_id), edit)
                st.success("Corrections saved. Manual edits are preserved across resyncs.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - surface validation errors to the user
                st.error(f"Could not save corrections: {exc}")


def _str_num(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def _render_trade_detail(filtered: pd.DataFrame) -> None:
    st.subheader("Trade detail & review")
    if filtered.empty:
        st.caption("No trades match the current filter.")
        return

    ordered = filtered.sort_values("opened_at", ascending=False)
    options: dict[str, int] = {}
    for _, row in ordered.iterrows():
        if pd.isna(row.get("id")):
            continue
        opened = _fmt_dt(row.get("opened_at"))
        label = f"#{int(row['id'])} · {opened} · {row['symbol']} {row['side']} {row['status']}"
        options[label] = int(row["id"])
    if not options:
        st.caption("No selectable trades.")
        return

    choice = st.selectbox("Select a trade", options=list(options.keys()))
    trade_id = options[choice]
    detail = _load_trade_detail(trade_id)
    if detail is None:
        st.info("That trade no longer exists.")
        return

    _render_detail_facts(detail)
    _render_review_actions(trade_id, detail)
    _render_edit_form(trade_id, detail)


# ---------------------------------------------------------------------------
# Manual trade entry
# ---------------------------------------------------------------------------
def _render_add_trade(account_id: int | None) -> None:
    with st.expander("➕ Add a manual trade", expanded=False):
        with st.form("add_manual_trade"):
            c1, c2, c3 = st.columns(3)
            symbol = c1.text_input("Symbol", value="EURUSD")
            side = c2.selectbox("Side", options=[Side.BUY.value, Side.SELL.value])
            status = c3.selectbox(
                "Status", options=[TradeStatus.OPEN.value, TradeStatus.CLOSED.value]
            )

            t1, t2 = st.columns(2)
            opened_date = t1.date_input("Opened date", value=date.today())
            opened_time = t2.time_input("Opened time", value=datetime.now().time())
            closed_str = st.text_input("Closed at (for closed trades)", value="")

            p1, p2, p3 = st.columns(3)
            entry_price = p1.number_input("Entry price", value=1.0, step=0.0001, format="%.5f")
            exit_str = p2.text_input("Exit price", value="")
            quantity_str = p3.text_input("Quantity", value="")

            r1, r2, r3 = st.columns(3)
            stop_str = r1.text_input("Stop loss", value="")
            tp_str = r2.text_input("Take profit", value="")
            risk_str = r3.text_input("Initial risk amount", value="")

            m1, m2, m3 = st.columns(3)
            gross_str = m1.text_input("Gross P&L", value="")
            fees_str = m2.text_input("Fees", value="")
            net_str = m3.text_input("Net P&L", value="")

            notes = st.text_area("Notes", value="")
            submitted = st.form_submit_button("Add trade", type="primary")

        if submitted:
            try:
                payload = ManualTradeInput(
                    symbol=symbol,
                    side=side,
                    status=status,
                    opened_at=datetime.combine(opened_date, opened_time),
                    closed_at=_dt(closed_str),
                    entry_price=float(entry_price),
                    exit_price=_num(exit_str),
                    quantity=_num(quantity_str),
                    stop_loss=_num(stop_str),
                    take_profit=_num(tp_str),
                    initial_risk_amount=_num(risk_str),
                    gross_pnl=_num(gross_str),
                    fees=_num(fees_str),
                    net_pnl=_num(net_str),
                    notes=notes or None,
                )
                with session_scope() as session:
                    acct = account_id or get_or_create_default_account(session).id
                    trade = add_trade(session, acct, payload)
                    label = f"#{trade.id} {trade.symbol} {trade.side} {trade.status}"
                st.success(f"Added manual trade {label}.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - surface validation errors to the user
                st.error(f"Could not add trade: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def render_trades(account_id: int | None) -> None:
    symbols = load_symbols(account_id)
    all_trades = load_trades(account_id)

    _render_add_trade(account_id)

    if all_trades.empty:
        st.info("No trades yet. Add one above, or import data on the **Import** tab.")
        return

    opened = pd.to_datetime(all_trades["opened_at"], errors="coerce")
    min_date = opened.min().date() if opened.notna().any() else date.today()
    max_date = opened.max().date() if opened.notna().any() else date.today()

    with st.expander("Filters", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        date_range = f1.date_input("Opened between", value=(min_date, max_date))
        symbol = f2.selectbox("Symbol", options=["(all)"] + symbols)
        side = f3.selectbox("Side", options=["(all)", Side.BUY.value, Side.SELL.value])
        status = f4.selectbox(
            "Status", options=["(all)", TradeStatus.OPEN.value, TradeStatus.CLOSED.value]
        )

    start = end = None
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start, end = date_range

    filtered = load_trades(
        account_id,
        symbol=None if symbol == "(all)" else symbol,
        side=None if side == "(all)" else side,
        status=None if status == "(all)" else status,
        start=start,
        end=end,
    )

    st.subheader("Recent trades")
    recent = filtered.sort_values("opened_at", ascending=False).head(10)
    st.dataframe(prep_display(recent, TRADE_DISPLAY_COLUMNS), hide_index=True, width="stretch")

    open_positions = filtered[
        filtered["status"].astype("string").str.upper() == TradeStatus.OPEN.value
    ]
    st.subheader(f"Open positions ({len(open_positions)})")
    if open_positions.empty:
        st.caption("No open positions in the current filter.")
    else:
        st.dataframe(
            prep_display(open_positions, OPEN_DISPLAY_COLUMNS), hide_index=True, width="stretch"
        )

    closed = filtered[filtered["status"].astype("string").str.upper() == TradeStatus.CLOSED.value]
    st.subheader(f"Closed trades ({len(closed)})")
    st.dataframe(
        prep_display(closed.sort_values("closed_at", ascending=False), TRADE_DISPLAY_COLUMNS),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "`r_method` = how R was derived: **money** (net P&L / risk), **price** "
        "(estimated from prices), **manual** (user override), or **unknown**."
    )

    st.divider()
    _render_trade_detail(filtered)
