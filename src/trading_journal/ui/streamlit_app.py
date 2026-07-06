"""Streamlit dashboard for the trading journal.

Run with:  ``streamlit run src/trading_journal/ui/streamlit_app.py``
or:        ``trading-journal dashboard``

The script uses absolute imports (``trading_journal.*``) because Streamlit runs
it as a standalone script rather than as part of the package.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from trading_journal.db import init_db, session_scope
from trading_journal.formatting import fmt_money, fmt_num, fmt_pct, fmt_r, fmt_ratio
from trading_journal.importers.csv_importer import import_parsed, parse_trades_frame
from trading_journal.journal_score import JournalScore, compute_journal_score
from trading_journal.metrics import TradeMetrics, compute_metrics
from trading_journal.models import Side, TradeStatus
from trading_journal.seed import seed_demo
from trading_journal.services.account_service import (
    ManualSnapshotInput,
    add_snapshot,
    get_or_create_default_account,
    latest_snapshot,
    list_accounts,
    snapshots_dataframe,
)
from trading_journal.services.trade_service import (
    distinct_symbols,
    trades_dataframe,
)
from trading_journal.ui import charts

st.set_page_config(page_title="Trading Journal", page_icon="📈", layout="wide")

# The database must exist before any query (safe/idempotent).
init_db()


# ---------------------------------------------------------------------------
# Data loading (each helper opens and closes its own session)
# ---------------------------------------------------------------------------
def load_accounts() -> list[dict]:
    with session_scope() as session:
        return [
            {"id": a.id, "name": a.name, "broker": a.broker, "base_currency": a.base_currency}
            for a in list_accounts(session)
        ]


def load_trades(account_id: int | None = None, **filters) -> pd.DataFrame:
    with session_scope() as session:
        return trades_dataframe(session, account_id=account_id, **filters)


def load_snapshots(account_id: int | None = None) -> pd.DataFrame:
    with session_scope() as session:
        return snapshots_dataframe(session, account_id=account_id)


def load_symbols(account_id: int | None = None) -> list[str]:
    with session_scope() as session:
        return distinct_symbols(session, account_id=account_id)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
TRADE_DISPLAY_COLUMNS = [
    "opened_at",
    "closed_at",
    "symbol",
    "side",
    "status",
    "entry_price",
    "exit_price",
    "quantity",
    "net_pnl",
    "realized_r",
    "r_method",
    "planned_rr",
    "stop_loss",
    "take_profit",
    "initial_risk_amount",
    "notes",
]

OPEN_DISPLAY_COLUMNS = [
    "opened_at",
    "symbol",
    "side",
    "entry_price",
    "quantity",
    "stop_loss",
    "take_profit",
    "initial_risk_amount",
    "planned_rr",
    "notes",
]


def _prep_display(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=columns)
    present = [c for c in columns if c in df.columns]
    out = df[present].copy()
    for col in (
        "net_pnl",
        "realized_r",
        "planned_rr",
        "entry_price",
        "exit_price",
        "stop_loss",
        "take_profit",
        "initial_risk_amount",
        "quantity",
    ):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(5)
    return out


def kpi(col, label: str, value: str, help_text: str | None = None) -> None:
    col.metric(label, value, help=help_text)


# ---------------------------------------------------------------------------
# Tab: Dashboard
# ---------------------------------------------------------------------------
def render_journal_score(score: JournalScore) -> None:
    left, right = st.columns([1, 2])
    with left:
        st.metric("Journal Score", f"{score.score:.1f} / 100", help=score.explanation)
        st.caption(f"Confidence: **{score.confidence}**")
        st.caption("Transparent local score — *not* TradeZella's Zella Score.")
    with right:
        st.dataframe(
            score.to_frame(),
            hide_index=True,
            width="stretch",
        )


def render_kpis(m: TradeMetrics) -> None:
    r1 = st.columns(4)
    kpi(r1[0], "Net P&L", fmt_money(m.net_pnl), "Sum of net P&L across closed trades.")
    kpi(
        r1[1],
        "Total realized R",
        fmt_r(m.total_realized_r),
        "Sum of realized R over closed trades.",
    )
    kpi(
        r1[2],
        "Trade win %",
        fmt_pct(m.trade_win_pct),
        "Winners / (winners + losers), breakeven excluded.",
    )
    kpi(
        r1[3],
        "Profit factor",
        fmt_ratio(m.profit_factor),
        "Gross profit / gross loss. ∞ = no losing trades.",
    )

    r2 = st.columns(4)
    kpi(r2[0], "Day win %", fmt_pct(m.day_win_pct), "Share of trading days with positive net P&L.")
    kpi(r2[1], "Expectancy (R)", fmt_r(m.expectancy_r), "p(win)·avgWinR + p(loss)·avgLossR.")
    kpi(
        r2[2],
        "Avg realized R",
        fmt_r(m.avg_realized_r),
        "Average R per closed trade with an R value.",
    )
    kpi(
        r2[3],
        "Avg planned RR",
        fmt_num(m.avg_planned_rr),
        "Average planned reward-to-risk (open + closed).",
    )

    r3 = st.columns(4)
    kpi(r3[0], "Avg win / loss", f"{fmt_money(m.avg_win)} / {fmt_money(m.avg_loss)}")
    kpi(r3[1], "Avg win / loss (R)", f"{fmt_r(m.avg_win_r)} / {fmt_r(m.avg_loss_r)}")
    kpi(r3[2], "Latest balance", fmt_money(m.latest_balance))
    kpi(r3[3], "Latest equity", fmt_money(m.latest_equity))

    r4 = st.columns(4)
    kpi(r4[0], "Closed trades", str(m.closed_trade_count))
    kpi(r4[1], "Open trades", str(m.open_trade_count))
    kpi(
        r4[2],
        "Wins / Losses / BE",
        f"{m.winning_trade_count} / {m.losing_trade_count} / {m.breakeven_trade_count}",
    )
    kpi(
        r4[3],
        "Max drawdown",
        fmt_money(m.max_drawdown),
        "Largest peak-to-trough drop of cumulative daily P&L.",
    )


def render_dashboard(trades: pd.DataFrame, snaps: pd.DataFrame) -> None:
    if trades.empty:
        st.info("No trades yet. Head to the **Import** tab to seed demo data or upload a CSV.")
        return

    metrics = compute_metrics(trades, snaps)
    score = compute_journal_score(trades, metrics)

    render_kpis(metrics)
    st.divider()
    render_journal_score(score)
    st.divider()

    c1, c2 = st.columns(2)
    fig = charts.daily_pnl_bar(metrics.daily)
    if fig:
        c1.plotly_chart(fig, width="stretch")
    fig = charts.cumulative_pnl_line(metrics.daily)
    if fig:
        c2.plotly_chart(fig, width="stretch")

    c3, c4 = st.columns(2)
    fig = charts.realized_r_hist(trades)
    if fig:
        c3.plotly_chart(fig, width="stretch")
    else:
        c3.info("No realized R values to plot yet.")
    fig = charts.calendar_heatmap(metrics.daily)
    if fig:
        c4.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# Tab: Trades
# ---------------------------------------------------------------------------
def render_trades(account_id: int | None) -> None:
    symbols = load_symbols(account_id)
    all_trades = load_trades(account_id)
    if all_trades.empty:
        st.info("No trades yet. Import data on the **Import** tab.")
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
    st.dataframe(_prep_display(recent, TRADE_DISPLAY_COLUMNS), hide_index=True, width="stretch")

    open_positions = filtered[
        filtered["status"].astype("string").str.upper() == TradeStatus.OPEN.value
    ]
    st.subheader(f"Open positions ({len(open_positions)})")
    if open_positions.empty:
        st.caption("No open positions in the current filter.")
    else:
        st.dataframe(
            _prep_display(open_positions, OPEN_DISPLAY_COLUMNS),
            hide_index=True,
            width="stretch",
        )

    closed = filtered[filtered["status"].astype("string").str.upper() == TradeStatus.CLOSED.value]
    st.subheader(f"Closed trades ({len(closed)})")
    st.dataframe(
        _prep_display(closed.sort_values("closed_at", ascending=False), TRADE_DISPLAY_COLUMNS),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "`r_method` = how R was derived: **money** (net P&L / risk), **price** (estimated from prices), or **unknown**."
    )


# ---------------------------------------------------------------------------
# Tab: Import
# ---------------------------------------------------------------------------
def render_import(account_id: int | None) -> None:
    st.subheader("Seed demo data")
    st.caption(
        "Load the bundled sample of EUR/USD trades and account snapshots. Safe to run repeatedly."
    )
    if st.button("Seed demo data", type="secondary"):
        with session_scope() as session:
            result = seed_demo(session)
        st.success(f"Demo data ready — {result.summary()}")
        st.rerun()

    st.divider()
    st.subheader("Import a CSV")
    st.caption(
        "Recognized column aliases include: symbol/pair, side/direction, "
        "opened_at/open_time, entry_price/entry, stop_loss/sl, take_profit/tp, "
        "net_pnl/profit, initial_risk_amount/risk, and more."
    )
    uploaded = st.file_uploader("Choose a trades CSV", type=["csv"])
    if uploaded is None:
        return

    try:
        raw = pd.read_csv(uploaded, dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001 - surface any parse error to the user
        st.error(f"Could not read CSV: {exc}")
        return

    st.write("**Raw preview**")
    st.dataframe(raw.head(20), hide_index=True, width="stretch")

    parsed = parse_trades_frame(raw)
    c1, c2, c3 = st.columns(3)
    c1.metric("Valid rows", parsed.ok_count)
    c2.metric("Failed rows", parsed.error_count)
    c3.metric("Warnings", len(parsed.warnings))

    if parsed.trades:
        st.write("**Parsed valid rows (preview)**")
        st.dataframe(pd.DataFrame(parsed.trades).head(20), hide_index=True, width="stretch")

    if parsed.row_errors:
        st.error("Some rows failed validation and will NOT be imported:")
        st.dataframe(
            pd.DataFrame(
                [{"row": e.row_number, "errors": "; ".join(e.errors)} for e in parsed.row_errors]
            ),
            hide_index=True,
            width="stretch",
        )

    if parsed.warnings:
        with st.expander(f"Data-quality warnings ({len(parsed.warnings)})"):
            for warning in parsed.warnings:
                st.write(f"- {warning}")

    if parsed.trades and st.button(f"Import {parsed.ok_count} valid rows", type="primary"):
        with session_scope() as session:
            if account_id is None:
                account_id = get_or_create_default_account(session).id
            result = import_parsed(session, account_id, parsed)
        st.success(f"Imported: {result.summary()}")
        st.rerun()


# ---------------------------------------------------------------------------
# Tab: Account
# ---------------------------------------------------------------------------
def render_account(account_id: int | None) -> None:
    if account_id is None:
        st.info("No account yet. Seed demo data or import a CSV to create the local account.")
        return

    snaps = load_snapshots(account_id)
    with session_scope() as session:
        latest = latest_snapshot(session, account_id)

    c1, c2, c3 = st.columns(3)
    c1.metric("Latest balance", fmt_money(latest.balance if latest else None))
    c2.metric("Latest equity", fmt_money(latest.equity if latest else None))
    c3.metric("Snapshots", str(len(snaps)))

    fig = charts.equity_line(snaps)
    if fig:
        st.plotly_chart(fig, width="stretch")

    st.subheader("Snapshots")
    if snaps.empty:
        st.caption("No snapshots yet.")
    else:
        st.dataframe(
            snaps[["timestamp", "balance", "equity", "source"]].sort_values(
                "timestamp", ascending=False
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Add a manual snapshot")
    with st.form("add_snapshot"):
        d1, d2, d3 = st.columns(3)
        snap_date = d1.date_input("Date", value=date.today())
        balance = d2.number_input("Balance", value=10000.0, step=100.0, format="%.2f")
        equity = d3.number_input("Equity (optional)", value=10000.0, step=100.0, format="%.2f")
        submitted = st.form_submit_button("Add snapshot")
        if submitted:
            try:
                payload = ManualSnapshotInput(
                    timestamp=datetime.combine(snap_date, datetime.min.time()),
                    balance=balance,
                    equity=equity,
                )
                with session_scope() as session:
                    add_snapshot(
                        session,
                        account_id=account_id,
                        balance=payload.balance,
                        equity=payload.equity,
                        timestamp=payload.timestamp,
                        source="manual",
                    )
                st.success("Snapshot added.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - show validation error to user
                st.error(f"Could not add snapshot: {exc}")


# ---------------------------------------------------------------------------
# Tab: Help / Data Quality
# ---------------------------------------------------------------------------
def _missing_data_report(trades: pd.DataFrame) -> pd.DataFrame:
    status = trades["status"].astype("string").str.upper()
    closed = trades[status == TradeStatus.CLOSED.value]
    checks = {
        "Trades missing stop loss": int(trades["stop_loss"].isna().sum()),
        "Trades missing initial risk": int(trades["initial_risk_amount"].isna().sum()),
        "Closed trades missing close time": int(closed["closed_at"].isna().sum()),
        "Closed trades missing P&L": int(closed["net_pnl"].isna().sum()),
        "Trades with no valid planned RR": int(trades["planned_rr"].isna().sum()),
    }
    return pd.DataFrame([{"Check": k, "Count": v} for k, v in checks.items()])


def render_help(trades: pd.DataFrame) -> None:
    st.subheader("Data-quality checks")
    if trades.empty:
        st.caption("No trades yet.")
    else:
        st.dataframe(_missing_data_report(trades), hide_index=True, width="stretch")
        st.caption("These counts flag where metrics may be incomplete or estimated.")

    st.subheader("Money-based R vs price-based R")
    st.markdown(
        """
- **Money-based R** = `net_pnl / initial_risk_amount`. Most accurate — it uses the
  dollars you actually risked. Method shows as **money**.
- **Price-based R** is estimated from price distances when no risk amount was
  recorded: for a BUY, `(exit − entry) / (entry − stop_loss)`. It is a reasonable
  estimate but assumes your stop equals your true risk. Method shows as **price**.
- If neither is possible the trade's R is left blank (method **unknown**).

Price-based R is **never** treated as equal in accuracy to money-based R.
"""
    )

    st.subheader("Metric formulas")
    st.markdown(
        """
| Metric | Formula |
| --- | --- |
| Net P&L | Σ net_pnl over closed trades |
| Profit factor | gross profit / \\|gross loss\\| (∞ if no losses) |
| Trade win % | winners / (winners + losers) — breakeven excluded |
| Day win % | winning days / trading days (by close date) |
| Avg win / loss | mean net_pnl of winners / of losers |
| Avg realized R | mean realized_r over closed trades with R |
| Expectancy (R) | p(win)·avgWinR + p(loss)·avgLossR |
| Avg planned RR | mean planned_rr over all trades that have one |
| Max drawdown | largest peak-to-trough drop of cumulative daily P&L |
| Planned RR (BUY) | (take_profit − entry) / (entry − stop_loss) |
| Planned RR (SELL) | (entry − take_profit) / (stop_loss − entry) |
"""
    )

    st.subheader("Journal Score")
    st.markdown(
        """
A transparent local 0–100 score (**not** TradeZella's Zella Score) rewarding good
journaling and risk habits:

- **Data completeness (30)** — closed trades with all core fields.
- **Risk tracking (25)** — closed trades where R is knowable (money or price).
- **Risk control (20)** — losing trades that respected the stop (R ≥ −1.2).
- **Performance health (15)** — positive expectancy and profit factor > 1.
- **Review completeness (10)** — closed trades that have notes.

Each component reports a confidence based on sample size. **LOW** confidence means
*not enough data yet*, not *bad*.
"""
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    st.title("📈 Trading Journal")
    st.caption(
        "A local, TradeZella-lite forex journal — Phase 1 (no live trading, no broker sync)."
    )

    accounts = load_accounts()
    account_id: int | None = None
    with st.sidebar:
        st.header("Account")
        if accounts:
            labels = {f"{a['name']} ({a['base_currency']})": a["id"] for a in accounts}
            choice = st.selectbox("Select account", options=list(labels.keys()))
            account_id = labels[choice]
            selected = next(a for a in accounts if a["id"] == account_id)
            st.caption(f"Broker: {selected['broker'] or '—'}")
        else:
            st.info("No account yet.\nSeed demo data on the Import tab.")
        st.divider()
        st.caption("Phase 2 (planned): read-only TradeLocker sync.")

    trades = load_trades(account_id)
    snaps = load_snapshots(account_id)

    tab_dash, tab_trades, tab_import, tab_account, tab_help = st.tabs(
        ["Dashboard", "Trades", "Import", "Account", "Help / Data Quality"]
    )
    with tab_dash:
        render_dashboard(trades, snaps)
    with tab_trades:
        render_trades(account_id)
    with tab_import:
        render_import(account_id)
    with tab_account:
        render_account(account_id)
    with tab_help:
        render_help(trades)


main()
