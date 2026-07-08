"""Account / Backup tab: snapshots plus local export, backup, and restore.

Restore is deliberately conservative: it validates the archive, snapshots the
current database first, and requires an explicit confirmation checkbox.
"""

from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path

import streamlit as st

from trading_journal.config import get_settings
from trading_journal.db import reset_engine_cache, session_scope
from trading_journal.formatting import fmt_money
from trading_journal.services.account_service import (
    ManualSnapshotInput,
    add_snapshot,
    latest_snapshot,
)
from trading_journal.services.backup_service import (
    create_backup,
    export_csv,
    export_json,
    inspect_backup,
    restore_backup,
    sqlite_path_from_session,
)
from trading_journal.ui import charts
from trading_journal.ui.common import load_snapshots

EXPORTS_DIR = "exports"
BACKUPS_DIR = "backups"


def _render_snapshots(account_id: int) -> None:
    snaps = load_snapshots(account_id)
    with session_scope() as session:
        latest = latest_snapshot(session, account_id)

    c1, c2, c3 = st.columns(3)
    c1.metric("Latest balance", fmt_money(latest.balance if latest else None))
    c2.metric("Latest equity", fmt_money(latest.equity if latest else None))
    c3.metric("Snapshots", str(len(snaps)))

    fig = charts.equity_line(snaps)
    if fig:
        st.plotly_chart(fig, width="stretch", key="bk_equity")

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


def _render_backup_export() -> None:
    st.subheader("Backup & export")
    st.caption(
        "All exports stay on your machine. A backup zip bundles a copy of the SQLite "
        "database plus CSV and JSON exports and a manifest."
    )

    c1, c2, c3 = st.columns(3)
    if c1.button("Export CSV", width="stretch"):
        with session_scope() as session:
            paths = export_csv(session, EXPORTS_DIR)
        st.success(f"Wrote {len(paths)} CSV files to `{EXPORTS_DIR}/`.")
    if c2.button("Export JSON", width="stretch"):
        with session_scope() as session:
            path = export_json(session, EXPORTS_DIR)
        st.success(f"Wrote `{path}`.")
    if c3.button("Create backup", type="primary", width="stretch"):
        with session_scope() as session:
            zip_path = create_backup(session, BACKUPS_DIR)
        st.session_state["last_backup_path"] = str(zip_path)
        st.success(f"Backup written: `{zip_path}`")

    last = st.session_state.get("last_backup_path")
    if last and Path(last).exists():
        with open(last, "rb") as fh:
            st.download_button(
                "Download latest backup",
                data=fh.read(),
                file_name=Path(last).name,
                mime="application/zip",
                width="stretch",
            )


def _render_restore() -> None:
    st.subheader("Restore from backup")
    st.warning(
        "Restoring **replaces** the current database. Your current database is backed "
        "up first (a `.pre-restore-…` file next to it), but proceed carefully."
    )
    uploaded = st.file_uploader("Upload a backup .zip", type=["zip"], key="restore_zip")
    if uploaded is None:
        return

    tmp = Path(tempfile.mkdtemp()) / uploaded.name
    tmp.write_bytes(uploaded.getvalue())
    info = inspect_backup(tmp)
    if not info.valid:
        st.error("Invalid backup: " + "; ".join(info.problems))
        return

    st.info(
        f"Archive OK — database `{info.database_file}`, counts: {info.manifest.get('counts', {})}"
    )
    confirm = st.checkbox("I understand this will replace my current database.")
    if st.button("Restore now", type="primary", disabled=not confirm):
        with session_scope() as session:
            target = sqlite_path_from_session(session) or get_settings().db_path
        reset_engine_cache()
        result = restore_backup(tmp, target, make_backup=True)
        reset_engine_cache()
        st.success(result.message)
        st.rerun()


def render_account_and_backup(account_id: int | None) -> None:
    if account_id is None:
        st.info("No account yet. Seed demo data or import a CSV to create the local account.")
    else:
        _render_snapshots(account_id)
        st.divider()
    _render_backup_export()
    st.divider()
    _render_restore()
