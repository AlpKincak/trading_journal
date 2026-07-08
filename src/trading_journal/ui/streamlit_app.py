"""Streamlit dashboard for the trading journal.

Run with:  ``streamlit run src/trading_journal/ui/streamlit_app.py``
or:        ``trading-journal dashboard``

The script uses absolute imports (``trading_journal.*``) because Streamlit runs
it as a standalone script rather than as part of the package. Per-tab rendering
lives in sibling modules under ``trading_journal.ui`` to keep this file small;
all business logic stays in the services/metrics/analytics layers.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from trading_journal.config import get_tradelocker_settings
from trading_journal.connectors.tradelocker import (
    TradeLockerConfigError,
    TradeLockerError,
    TradeLockerReadOnlyClient,
)
from trading_journal.data_quality import data_quality_report, needs_review_frame
from trading_journal.db import init_db, session_scope
from trading_journal.formatting import fmt_money, fmt_num, fmt_pct, fmt_r, fmt_ratio
from trading_journal.importers.csv_importer import import_parsed, parse_trades_frame
from trading_journal.journal_score import JournalScore, compute_journal_score
from trading_journal.metrics import TradeMetrics, compute_metrics
from trading_journal.seed import seed_demo
from trading_journal.services.account_service import get_or_create_default_account
from trading_journal.services.review_service import daily_reviews_dataframe
from trading_journal.services.sync_service import build_sync_service
from trading_journal.services.sync_state_service import sync_runs_dataframe
from trading_journal.ui import analytics_view, backup_view, charts, reviews_view, trades_view
from trading_journal.ui.common import kpi, load_accounts, load_snapshots, load_trades

st.set_page_config(page_title="Trading Journal", page_icon="📈", layout="wide")

# The database must exist before any query (safe/idempotent).
init_db()


def _load_reviews(account_id: int | None) -> pd.DataFrame:
    with session_scope() as session:
        return daily_reviews_dataframe(session, account_id=account_id)


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
        st.dataframe(score.to_frame(), hide_index=True, width="stretch")


def render_kpis(m: TradeMetrics) -> None:
    r1 = st.columns(4)
    kpi(r1[0], "Net P&L", fmt_money(m.net_pnl), "Sum of net P&L across closed trades.")
    kpi(
        r1[1],
        "Total realized R",
        fmt_r(m.total_realized_r),
        "Sum of realized R over closed trades.",
    )
    kpi(r1[2], "Trade win %", fmt_pct(m.trade_win_pct), "Winners / (winners + losers).")
    kpi(r1[3], "Profit factor", fmt_ratio(m.profit_factor), "Gross profit / gross loss.")

    r2 = st.columns(4)
    kpi(r2[0], "Day win %", fmt_pct(m.day_win_pct), "Share of trading days with positive net P&L.")
    kpi(r2[1], "Expectancy (R)", fmt_r(m.expectancy_r), "p(win)·avgWinR + p(loss)·avgLossR.")
    kpi(r2[2], "Avg realized R", fmt_r(m.avg_realized_r), "Average R per closed trade with an R.")
    kpi(r2[3], "Avg planned RR", fmt_num(m.avg_planned_rr), "Average planned reward-to-risk.")

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
    kpi(r4[3], "Max drawdown", fmt_money(m.max_drawdown), "Largest peak-to-trough drop.")


def render_dashboard(trades: pd.DataFrame, snaps: pd.DataFrame, reviews: pd.DataFrame) -> None:
    if trades.empty:
        st.info("No trades yet. Head to the **Import** tab to seed demo data or upload a CSV.")
        return

    metrics = compute_metrics(trades, snaps)
    score = compute_journal_score(trades, metrics, reviews)

    render_kpis(metrics)
    st.divider()
    render_journal_score(score)
    st.divider()

    c1, c2 = st.columns(2)
    fig = charts.daily_pnl_bar(metrics.daily)
    if fig:
        c1.plotly_chart(fig, width="stretch", key="dash_daily_pnl")
    fig = charts.cumulative_pnl_line(metrics.daily)
    if fig:
        c2.plotly_chart(fig, width="stretch", key="dash_cum_pnl")

    c3, c4 = st.columns(2)
    fig = charts.realized_r_hist(trades)
    if fig:
        c3.plotly_chart(fig, width="stretch", key="dash_r_hist")
    else:
        c3.info("No realized R values to plot yet.")
    fig = charts.calendar_heatmap(metrics.daily)
    if fig:
        c4.plotly_chart(fig, width="stretch", key="dash_cal")


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
# Tab: Sync (read-only TradeLocker)
# ---------------------------------------------------------------------------
def _render_sync_config_summary() -> object:
    """Show the TradeLocker config summary (no secrets) and return the settings."""
    settings = get_tradelocker_settings()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Enabled", "Yes" if settings.enabled else "No")
    c2.metric("Environment", settings.environment)
    c3.metric("Credentials", "Present" if settings.has_credentials else "Missing")
    c4.metric("Default account", settings.account_id or "—")
    st.caption(
        f"Base URL: `{settings.base_url}`  ·  email: {settings.masked_email}  ·  "
        f"accNum: {settings.acc_num or '—'}  ·  lookback: {settings.lookback_days}d  ·  "
        "**read-only** — this never places, modifies, or closes trades."
    )
    if not settings.has_credentials:
        missing = ", ".join(settings.missing_credential_fields())
        st.info(
            f"TradeLocker credentials are not set ({missing}). Add them to your `.env` "
            "to enable health checks and syncing. The rest of the dashboard works without them."
        )
    return settings


def _render_sync_result(result) -> None:
    st.write(
        f"**Result:** `{result.status}`"
        + ("  *(dry run — nothing written)*" if result.dry_run else "")
    )
    m = st.columns(4)
    m[0].metric("Imported", result.trades_imported)
    m[1].metric("Updated", result.trades_updated)
    m[2].metric("Skipped", result.trades_skipped)
    m[3].metric("Snapshots", result.snapshots_imported)
    m2 = st.columns(3)
    m2[0].metric("Open positions seen", result.open_positions_seen)
    m2[1].metric("Closed rows seen", result.closed_rows_seen)
    m2[2].metric("Accounts seen", result.accounts_seen)
    if result.errors:
        st.error("Errors:\n" + "\n".join(f"- {e}" for e in result.errors))
    if result.warnings:
        with st.expander(f"Data-quality warnings ({len(result.warnings)})"):
            for warning in result.warnings:
                st.write(f"- {warning}")


def render_sync() -> None:
    st.subheader("TradeLocker sync (read-only)")
    st.caption(
        "Pull accounts, open positions, closed history, and balance/equity from "
        "TradeLocker into this local journal. No orders are ever placed, modified, "
        "or closed. Your manual corrections and review notes are preserved on resync."
    )
    settings = _render_sync_config_summary()
    st.divider()

    with st.expander("Sync target", expanded=True):
        i1, i2, i3 = st.columns(3)
        account_id = i1.text_input("Account ID", value=settings.account_id or "")
        acc_num = i2.text_input("accNum (optional)", value=settings.acc_num or "")
        lookback = i3.number_input(
            "Lookback (days)", min_value=1, max_value=3650, value=int(settings.lookback_days)
        )
        sync_all = st.checkbox("Sync all discovered accounts", value=False)

    b1, b2, b3, b4 = st.columns(4)
    do_health = b1.button("Health check", width="stretch")
    do_accounts = b2.button("List accounts", width="stretch")
    do_dry_run = b3.button("Dry-run sync", type="secondary", width="stretch")
    do_apply = b4.button("Apply import", type="primary", width="stretch")
    st.caption(
        "**Apply import** writes only to this local journal (read-only against your "
        "broker). Dry-run previews the same counts without writing."
    )

    def _client() -> TradeLockerReadOnlyClient:
        return TradeLockerReadOnlyClient.from_settings(settings)

    def _service():
        return build_sync_service(settings)

    def _run_sync(dry_run: bool):
        try:
            with session_scope() as session:
                service = _service()
                if sync_all:
                    return service.sync_all_configured_accounts(
                        session, lookback_days=int(lookback), dry_run=dry_run
                    )
                if not account_id:
                    st.warning("Enter an Account ID or tick 'Sync all discovered accounts'.")
                    return None
                return service.sync_account(
                    session,
                    account_id.strip(),
                    acc_num.strip() or None,
                    lookback_days=int(lookback),
                    dry_run=dry_run,
                )
        except TradeLockerConfigError as exc:
            st.error(f"Configuration problem: {exc}")
        except TradeLockerError as exc:
            st.error(f"TradeLocker error: {exc}")
        return None

    if do_health:
        result = _client().health_check()
        (st.success if result.ok else st.error)(
            f"{'OK' if result.ok else 'FAILED'} · env={result.environment} · "
            f"authenticated={result.authenticated} · accounts={result.accounts_found}\n\n"
            f"{result.message}"
        )

    if do_accounts:
        try:
            client = _client()
            client.authenticate()
            accounts = client.list_accounts()
            if not accounts:
                st.info("No TradeLocker accounts found for these credentials/environment.")
            else:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "account_id": a.account_id,
                                "accNum": a.acc_num,
                                "currency": a.currency,
                                "balance": a.balance,
                                "name": a.name,
                            }
                            for a in accounts
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
        except TradeLockerConfigError as exc:
            st.error(f"Configuration problem: {exc}")
        except TradeLockerError as exc:
            st.error(f"TradeLocker error: {exc}")

    if do_dry_run:
        result = _run_sync(dry_run=True)
        if result is not None:
            st.info("Dry run complete — nothing was written.")
            _render_sync_result(result)

    if do_apply:
        result = _run_sync(dry_run=False)
        if result is not None:
            st.success("Import complete.")
            _render_sync_result(result)

    st.divider()
    st.subheader("Recent sync runs")
    with session_scope() as session:
        runs = sync_runs_dataframe(session, limit=20)
    if runs.empty:
        st.caption("No sync runs yet.")
    else:
        st.dataframe(runs, hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# Tab: Help / Data Quality
# ---------------------------------------------------------------------------
def render_help(trades: pd.DataFrame) -> None:
    st.subheader("Data quality & reconciliation")
    if trades.empty:
        st.caption("No trades yet.")
    else:
        st.dataframe(data_quality_report(trades), hide_index=True, width="stretch")
        st.caption("These counts flag where metrics may be incomplete or estimated.")

        queue = needs_review_frame(trades)
        st.subheader(f"Needs Review queue ({len(queue)})")
        if queue.empty:
            st.caption("Nothing needs review right now. 🎉")
        else:
            show = queue.copy()
            for col in ("net_pnl", "realized_r"):
                if col in show.columns:
                    show[col] = pd.to_numeric(show[col], errors="coerce").round(3)
            st.dataframe(show, hide_index=True, width="stretch")
            st.caption(
                "Fix these on the **Trades** tab: correct data, then Mark reviewed / Needs fix."
            )

    with session_scope() as session:
        runs = sync_runs_dataframe(session, limit=10)
    if not runs.empty:
        with st.expander("Recent sync runs (warnings / errors)"):
            st.dataframe(
                runs[["id", "started_at", "status", "warning_count", "error_count"]],
                hide_index=True,
                width="stretch",
            )

    st.divider()
    st.subheader("Money-based R vs price-based R")
    st.markdown(
        """
- **Money-based R** = `net_pnl / initial_risk_amount`. Most accurate — it uses the
  dollars you actually risked. Method shows as **money**.
- **Price-based R** is estimated from price distances when no risk amount was
  recorded: for a BUY, `(exit − entry) / (entry − stop_loss)`. Method shows as **price**.
- **Manual** means you overrode R yourself. If none is possible the R is blank (**unknown**).

Price-based R is **never** treated as equal in accuracy to money-based R.
"""
    )

    st.subheader("Journal Score")
    st.markdown(
        """
A transparent local 0–100 score (**not** TradeZella's Zella Score) rewarding good
journaling and risk habits:

- **Data completeness (25)** — closed trades with all core fields.
- **Risk tracking (20)** — closed trades where R is knowable (money or price).
- **Risk control (20)** — losing trades that respected the stop (R ≥ −1.2).
- **Performance health (15)** — positive expectancy and profit factor > 1.
- **Trade review (12)** — closed trades reviewed (status set or notes written).
- **Daily review consistency (8)** — trading days that have a daily review.

Each component reports a confidence based on sample size. **LOW** confidence means
*not enough data yet*, not *bad*.
"""
    )

    st.subheader("Safety")
    st.markdown(
        """
- TradeLocker sync is **read-only**: no order placement, modification, or closing.
- Credentials are read from the environment only — never written to the DB or logged.
- Everything is **local-first**; use **Account / Backup** to export or back up your data.
"""
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    st.title("📈 Trading Journal")
    st.caption(
        "A local, TradeZella-lite forex journal — with read-only TradeLocker sync "
        "(no live trading, no order placement)."
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
        st.caption("The **Sync** tab pulls read-only data from TradeLocker.")

    trades = load_trades(account_id)
    snaps = load_snapshots(account_id)
    reviews = _load_reviews(account_id)

    (
        tab_dash,
        tab_trades,
        tab_analytics,
        tab_reviews,
        tab_import,
        tab_sync,
        tab_account,
        tab_help,
    ) = st.tabs(
        [
            "Dashboard",
            "Trades",
            "Analytics",
            "Calendar / Reviews",
            "Import",
            "Sync",
            "Account / Backup",
            "Help / Data Quality",
        ]
    )
    with tab_dash:
        render_dashboard(trades, snaps, reviews)
    with tab_trades:
        trades_view.render_trades(account_id)
    with tab_analytics:
        analytics_view.render_analytics(trades)
    with tab_reviews:
        reviews_view.render_calendar_reviews(account_id, trades)
    with tab_import:
        render_import(account_id)
    with tab_sync:
        render_sync()
    with tab_account:
        backup_view.render_account_and_backup(account_id)
    with tab_help:
        render_help(trades)


main()
