"""Command-line interface: ``trading-journal <command>``.

Commands
--------
* ``init-db``               Create the SQLite schema.
* ``seed-demo``             Load the bundled deterministic demo data.
* ``import-csv PATH``       Import trades from a CSV file.
* ``add-trade``             Add a manual trade locally.
* ``metrics``               Print a summary of dashboard metrics.
* ``review-day DATE``       Show a day's summary and add/update its daily review.
* ``data-quality``          Print data-quality checks and the Needs-Review count.
* ``export-csv``            Export all tables to CSV files.
* ``export-json``           Export all tables to a single JSON file.
* ``backup``                Write a timestamped zip backup (DB + CSV + JSON).
* ``restore-backup PATH``   Restore the database from a backup zip (conservative).
* ``dashboard``             Launch the Streamlit dashboard.
* ``tradelocker-health``    Check TradeLocker config/auth (read-only).
* ``tradelocker-accounts``  List available TradeLocker accounts (read-only).
* ``sync-tradelocker``      Read-only sync into the journal (dry-run unless ``--apply``).
* ``sync-status``           Show recent sync runs.

The TradeLocker commands never place, modify, or close trades. Credentials and
tokens are never printed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import __version__
from .config import get_settings, get_tradelocker_settings
from .connectors.tradelocker import (
    TradeLockerConfigError,
    TradeLockerError,
    TradeLockerReadOnlyClient,
)
from .data_quality import data_quality_report, needs_review_frame
from .db import init_db, reset_engine_cache, session_scope
from .formatting import fmt_money, fmt_num, fmt_pct, fmt_r, fmt_ratio
from .importers.csv_importer import import_csv
from .journal_score import compute_journal_score
from .metrics import compute_metrics, day_detail
from .seed import seed_demo
from .services.account_service import get_or_create_default_account, snapshots_dataframe
from .services.backup_service import (
    create_backup,
    inspect_backup,
    restore_backup,
    sqlite_path_from_session,
)
from .services.backup_service import (
    export_csv as export_csv_files,
)
from .services.backup_service import (
    export_json as export_json_file,
)
from .services.review_service import DailyReviewInput, daily_reviews_dataframe, upsert_daily_review
from .services.sync_service import SyncResult, build_sync_service
from .services.sync_state_service import sync_runs_dataframe
from .services.trade_service import ManualTradeInput, add_trade, trades_dataframe

APP_PATH = Path(__file__).resolve().parent / "ui" / "streamlit_app.py"


def _parse_dt(value: str | None) -> datetime | None:
    """Parse a CLI date/datetime string, or None. Raises ValueError on bad input."""
    if value is None or str(value).strip() == "":
        return None
    return pd.to_datetime(value).to_pydatetime()


def _cmd_init_db(_: argparse.Namespace) -> int:
    init_db()
    settings = get_settings()
    print(f"Initialized database at: {settings.db_path}")
    return 0


def _cmd_seed_demo(_: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        result = seed_demo(session)
    print("Seeded demo data.")
    print(f"  {result.summary()}")
    if result.trades.warnings:
        print(
            f"  ({len(result.trades.warnings)} data-quality warnings — see the Help tab in the UI)"
        )
    return 0


def _cmd_import_csv(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1
    init_db()
    with session_scope() as session:
        result = import_csv(session, path)
    print(f"Imported '{path}': {result.summary()}")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    for row_error in result.row_errors:
        print(
            f"  row {row_error.row_number} failed: {'; '.join(row_error.errors)}", file=sys.stderr
        )
    return 0


def _print_metric(label: str, value: str) -> None:
    print(f"  {label:<26} {value}")


def _cmd_metrics(_: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        trades = trades_dataframe(session)
        snaps = snapshots_dataframe(session)
        reviews = daily_reviews_dataframe(session)
    metrics = compute_metrics(trades, snaps)
    score = compute_journal_score(trades, metrics, reviews)

    if metrics.trade_count == 0:
        print("No trades yet. Run 'trading-journal seed-demo' or import a CSV.")
        return 0

    print("Trading Journal — metrics summary")
    print("-" * 42)
    _print_metric("Net P&L", fmt_money(metrics.net_pnl))
    _print_metric("Total realized R", fmt_r(metrics.total_realized_r))
    _print_metric(
        "Trades (closed/open)", f"{metrics.closed_trade_count}/{metrics.open_trade_count}"
    )
    _print_metric(
        "Wins/Losses/BE",
        f"{metrics.winning_trade_count}/{metrics.losing_trade_count}/{metrics.breakeven_trade_count}",
    )
    _print_metric("Trade win %", fmt_pct(metrics.trade_win_pct))
    _print_metric("Day win %", fmt_pct(metrics.day_win_pct))
    _print_metric("Profit factor", fmt_ratio(metrics.profit_factor))
    _print_metric("Avg win / loss", f"{fmt_money(metrics.avg_win)} / {fmt_money(metrics.avg_loss)}")
    _print_metric("Avg win / loss (R)", f"{fmt_r(metrics.avg_win_r)} / {fmt_r(metrics.avg_loss_r)}")
    _print_metric("Avg realized R", fmt_r(metrics.avg_realized_r))
    _print_metric("Avg planned RR", fmt_num(metrics.avg_planned_rr))
    _print_metric("Expectancy (R)", fmt_r(metrics.expectancy_r))
    _print_metric("Max drawdown", fmt_money(metrics.max_drawdown))
    _print_metric("Latest balance", fmt_money(metrics.latest_balance))
    _print_metric("Latest equity", fmt_money(metrics.latest_equity))
    print("-" * 42)
    _print_metric("Journal Score", f"{score.score:.1f}/100  (confidence: {score.confidence})")
    for component in score.components:
        _print_metric(
            f"  · {component.label}",
            f"{component.points:.1f}/{component.max_points:.0f}  [{component.confidence}]",
        )
    print("\nNote: Journal Score is a transparent local score, not TradeZella's Zella Score.")
    return 0


def _cmd_add_trade(args: argparse.Namespace) -> int:
    try:
        payload = ManualTradeInput(
            symbol=args.symbol,
            side=args.side,
            status=args.status,
            opened_at=_parse_dt(args.opened_at),
            closed_at=_parse_dt(args.closed_at),
            entry_price=args.entry_price,
            exit_price=args.exit_price,
            quantity=args.quantity,
            stop_loss=args.stop_loss,
            take_profit=args.take_profit,
            initial_risk_amount=args.risk,
            gross_pnl=args.gross_pnl,
            fees=args.fees,
            net_pnl=args.net_pnl,
            notes=args.notes,
        )
    except (ValueError, TypeError) as exc:
        print(f"Error: invalid trade input: {exc}", file=sys.stderr)
        return 2

    init_db()
    with session_scope() as session:
        account_id = args.account_id or get_or_create_default_account(session).id
        trade = add_trade(session, account_id, payload)
        summary = (
            f"#{trade.id} {trade.symbol} {trade.side} {trade.status} "
            f"net_pnl={fmt_money(trade.net_pnl)} planned_rr={fmt_num(trade.planned_rr)} "
            f"realized_r={fmt_r(trade.realized_r)} ({trade.r_method or '—'})"
        )
    print(f"Added manual trade: {summary}")
    return 0


def _cmd_review_day(args: argparse.Namespace) -> int:
    try:
        day = pd.to_datetime(args.date).date()
    except (ValueError, TypeError):
        print(f"Error: could not parse date: {args.date!r}", file=sys.stderr)
        return 2

    init_db()
    with session_scope() as session:
        account_id = args.account_id or get_or_create_default_account(session).id
        trades = trades_dataframe(session, account_id=account_id)
        detail = day_detail(trades, day)

        wrote_review = any(
            v is not None
            for v in (
                args.notes,
                args.mood,
                args.discipline,
                args.risk,
                args.execution,
                args.lesson,
            )
        )
        if wrote_review:
            try:
                review = DailyReviewInput(
                    review_date=day,
                    notes=args.notes,
                    mood=args.mood,
                    discipline_score=args.discipline,
                    risk_score=args.risk,
                    execution_score=args.execution,
                    lesson=args.lesson,
                )
            except (ValueError, TypeError) as exc:
                print(f"Error: invalid review input: {exc}", file=sys.stderr)
                return 2
            upsert_daily_review(session, account_id, review)

    print(f"Day review — {day:%Y-%m-%d}")
    print("-" * 42)
    _print_metric("Net P&L", fmt_money(detail.net_pnl))
    _print_metric("Total realized R", fmt_r(detail.total_realized_r))
    _print_metric("Avg realized R", fmt_r(detail.avg_realized_r))
    _print_metric("Trades (day)", str(detail.trade_count))
    _print_metric("Closed / opened", f"{detail.closed_count} / {detail.open_count}")
    _print_metric(
        "Wins / Losses / BE",
        f"{detail.winning_count} / {detail.losing_count} / {detail.breakeven_count}",
    )
    if detail.best_trade:
        _print_metric("Best trade", fmt_money(detail.best_trade.get("net_pnl")))
    if detail.worst_trade:
        _print_metric("Worst trade", fmt_money(detail.worst_trade.get("net_pnl")))
    if wrote_review:
        print("\nDaily review saved.")
    return 0


def _cmd_data_quality(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        trades = trades_dataframe(session, account_id=args.account_id)
    if trades.empty:
        print("No trades yet. Run 'trading-journal seed-demo' or import a CSV.")
        return 0

    report = data_quality_report(trades)
    print("Data-quality checks")
    print("-" * 42)
    for _, row in report.iterrows():
        _print_metric(row["Check"], str(int(row["Count"])))

    queue = needs_review_frame(trades)
    print("-" * 42)
    _print_metric("Trades needing review", str(len(queue)))
    for _, row in queue.head(args.limit).iterrows():
        opened = row.get("opened_at")
        opened_str = opened.strftime("%Y-%m-%d") if pd.notna(opened) else "—"
        print(f"  #{int(row['id'])} {opened_str} {row['symbol']} {row['side']}: {row['reasons']}")
    if len(queue) > args.limit:
        print(f"  … and {len(queue) - args.limit} more")
    return 0


def _cmd_export_csv(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        paths = export_csv_files(session, args.out)
    print(f"Exported {len(paths)} CSV files to {args.out}:")
    for path in paths:
        print(f"  - {path.name}")
    return 0


def _cmd_export_json(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        path = export_json_file(session, args.out)
    print(f"Exported JSON to {path}")
    return 0


def _cmd_backup(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        zip_path = create_backup(session, args.out)
    print(f"Backup written: {zip_path}")
    return 0


def _cmd_restore_backup(args: argparse.Namespace) -> int:
    info = inspect_backup(args.path)
    if not info.valid:
        print(f"Error: invalid backup: {'; '.join(info.problems)}", file=sys.stderr)
        return 2

    init_db()
    with session_scope() as session:
        target = sqlite_path_from_session(session)
    if target is None:
        target = get_settings().db_path

    counts = info.manifest.get("counts", {})
    print(f"Backup contains database '{info.database_file}' with counts: {counts}")
    print(f"This will REPLACE the current database at: {target}")
    if not args.yes:
        print(
            "Refusing to overwrite without confirmation. Re-run with --yes to proceed "
            "(the current database is backed up first).",
            file=sys.stderr,
        )
        return 1

    # Drop pooled connections so the SQLite file is not held open during replace.
    reset_engine_cache()
    result = restore_backup(args.path, target, make_backup=True)
    reset_engine_cache()
    print(result.message)
    return 0


def _cmd_dashboard(_: argparse.Namespace) -> int:
    init_db()
    command = [sys.executable, "-m", "streamlit", "run", str(APP_PATH)]
    try:
        return subprocess.call(command)
    except FileNotFoundError:
        print("Could not launch Streamlit automatically. Run this command:")
        print(f"  {' '.join(command)}")
        return 1


# ---------------------------------------------------------------------------
# Phase 2: read-only TradeLocker sync commands
# ---------------------------------------------------------------------------
def _cmd_tradelocker_health(_: argparse.Namespace) -> int:
    settings = get_tradelocker_settings()
    client = TradeLockerReadOnlyClient.from_settings(settings)
    result = client.health_check()  # never raises; returns a safe summary
    print("TradeLocker health check")
    print("-" * 42)
    _print_metric("Enabled", "yes" if settings.enabled else "no")
    _print_metric("Environment", result.environment)
    _print_metric("Base URL", result.base_url)
    _print_metric("Credentials present", "yes" if settings.has_credentials else "no")
    _print_metric("Authenticated", "yes" if result.authenticated else "no")
    _print_metric("Accounts visible", str(result.accounts_found))
    _print_metric("Status", "OK" if result.ok else "FAILED")
    print(f"\n{result.message}")
    return 0 if result.ok else 1


def _cmd_tradelocker_accounts(_: argparse.Namespace) -> int:
    settings = get_tradelocker_settings()
    client = TradeLockerReadOnlyClient.from_settings(settings)
    try:
        client.authenticate()
        accounts = client.list_accounts()
    except TradeLockerConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except TradeLockerError as exc:
        print(f"TradeLocker error: {exc}", file=sys.stderr)
        return 1

    if not accounts:
        print("No TradeLocker accounts found for these credentials/environment.")
        return 0
    print(f"TradeLocker accounts ({settings.environment}):")
    for acc in accounts:
        print(
            f"  id={acc.account_id}  accNum={acc.acc_num or '—'}  "
            f"currency={acc.currency or '—'}  balance={fmt_money(acc.balance)}  "
            f"name={acc.name or '—'}"
        )
    return 0


def _print_sync_result(result: SyncResult, dry_run: bool) -> None:
    mode = "DRY-RUN (no changes written)" if dry_run else "APPLIED"
    print(f"TradeLocker sync — {mode}")
    print("-" * 42)
    _print_metric("Status", result.status)
    _print_metric("Accounts seen", str(result.accounts_seen))
    _print_metric(
        "Trades",
        f"imported={result.trades_imported} updated={result.trades_updated} "
        f"skipped={result.trades_skipped}",
    )
    _print_metric(
        "Positions/history seen",
        f"open={result.open_positions_seen} closed_rows={result.closed_rows_seen}",
    )
    _print_metric("Snapshots imported", str(result.snapshots_imported))
    _print_metric("Warnings / errors", f"{len(result.warnings)} / {len(result.errors)}")
    if result.warnings:
        print("  warnings:")
        for warning in result.warnings[:20]:
            print(f"    - {warning}")
        if len(result.warnings) > 20:
            print(f"    … and {len(result.warnings) - 20} more")
    for error in result.errors:
        print(f"  error: {error}", file=sys.stderr)
    if dry_run:
        print("\nThis was a dry run. Re-run with --apply to write these changes.")


def _cmd_sync_tradelocker(args: argparse.Namespace) -> int:
    if args.apply and args.dry_run:
        print("Error: pass only one of --apply / --dry-run.", file=sys.stderr)
        return 2
    # Safety default: writes require an explicit --apply.
    dry_run = not args.apply

    settings = get_tradelocker_settings()
    service = build_sync_service(settings)
    try:
        init_db()
        with session_scope() as session:
            if args.all:
                result = service.sync_all_configured_accounts(
                    session, lookback_days=args.lookback_days, dry_run=dry_run
                )
            else:
                account_id = args.account_id or settings.account_id
                acc_num = args.acc_num or settings.acc_num
                if not account_id:
                    print(
                        "Error: provide --account-id (or set TRADELOCKER_ACCOUNT_ID), "
                        "or use --all.",
                        file=sys.stderr,
                    )
                    return 2
                result = service.sync_account(
                    session,
                    account_id,
                    acc_num,
                    lookback_days=args.lookback_days,
                    dry_run=dry_run,
                )
    except TradeLockerConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except TradeLockerError as exc:
        print(f"Sync error: {exc}", file=sys.stderr)
        return 1

    _print_sync_result(result, dry_run)
    return 1 if result.status == "FAILED" else 0


def _cmd_sync_status(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        df = sync_runs_dataframe(session, limit=args.limit)
    if df.empty:
        print("No sync runs recorded yet. Run 'trading-journal sync-tradelocker --apply'.")
        return 0
    print("Recent TradeLocker sync runs")
    print("-" * 42)
    for _, row in df.iterrows():
        started = row["started_at"]
        started_str = started.strftime("%Y-%m-%d %H:%M") if started == started else "—"
        print(
            f"  #{row['id']}  {started_str}  {row['status']:<8}  "
            f"env={row['environment'] or '—'} acct={row['account_id'] or '—'}  "
            f"imported={row['imported_count']} updated={row['updated_count']} "
            f"skipped={row['skipped_count']} warn={row['warning_count']} err={row['error_count']}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-journal",
        description="A local, TradeZella-lite forex trading journal (Phase 1 + read-only sync).",
    )
    parser.add_argument("--version", action="version", version=f"trading-journal {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create the database schema.").set_defaults(func=_cmd_init_db)
    sub.add_parser("seed-demo", help="Load bundled demo data.").set_defaults(func=_cmd_seed_demo)

    p_import = sub.add_parser("import-csv", help="Import trades from a CSV file.")
    p_import.add_argument("path", help="Path to the CSV file.")
    p_import.set_defaults(func=_cmd_import_csv)

    p_add = sub.add_parser("add-trade", help="Add a manual trade locally.")
    p_add.add_argument("--symbol", required=True, help="Instrument symbol, e.g. EURUSD.")
    p_add.add_argument("--side", required=True, help="buy/sell (long/short).")
    p_add.add_argument("--status", default="open", help="open or closed (default: open).")
    p_add.add_argument("--opened-at", required=True, help="Open time, e.g. '2025-03-01 09:00'.")
    p_add.add_argument("--closed-at", help="Close time (required for a closed trade).")
    p_add.add_argument("--entry-price", type=float, required=True, help="Entry price.")
    p_add.add_argument("--exit-price", type=float, help="Exit price (closed trades).")
    p_add.add_argument("--quantity", type=float, help="Position size / lots.")
    p_add.add_argument("--stop-loss", type=float, help="Stop-loss price.")
    p_add.add_argument("--take-profit", type=float, help="Take-profit price.")
    p_add.add_argument("--risk", type=float, help="Initial risk amount (money).")
    p_add.add_argument("--gross-pnl", type=float, help="Gross P&L.")
    p_add.add_argument("--fees", type=float, help="Fees / commission.")
    p_add.add_argument("--net-pnl", type=float, help="Net P&L (else derived from gross - fees).")
    p_add.add_argument("--notes", help="Free-text notes.")
    p_add.add_argument("--account-id", type=int, help="Target account id (default: local account).")
    p_add.set_defaults(func=_cmd_add_trade)

    sub.add_parser("metrics", help="Print a metrics summary.").set_defaults(func=_cmd_metrics)

    p_review = sub.add_parser(
        "review-day", help="Show a day's summary and optionally add/update its daily review."
    )
    p_review.add_argument("date", help="The day to review, e.g. 2025-03-01.")
    p_review.add_argument("--account-id", type=int, help="Account id (default: local account).")
    p_review.add_argument("--notes", help="Daily review notes.")
    p_review.add_argument("--mood", help="Mood label.")
    p_review.add_argument("--discipline", type=int, help="Discipline score 0-100.")
    p_review.add_argument("--risk", type=int, help="Risk score 0-100.")
    p_review.add_argument("--execution", type=int, help="Execution score 0-100.")
    p_review.add_argument("--lesson", help="Lesson learned.")
    p_review.set_defaults(func=_cmd_review_day)

    p_dq = sub.add_parser("data-quality", help="Print data-quality checks and Needs-Review queue.")
    p_dq.add_argument("--account-id", type=int, help="Account id (default: all).")
    p_dq.add_argument("--limit", type=int, default=20, help="Max needs-review rows to list.")
    p_dq.set_defaults(func=_cmd_data_quality)

    p_ecsv = sub.add_parser("export-csv", help="Export all tables to CSV files.")
    p_ecsv.add_argument("--out", default="exports", help="Output directory (default: exports/).")
    p_ecsv.set_defaults(func=_cmd_export_csv)

    p_ejson = sub.add_parser("export-json", help="Export all tables to a single JSON file.")
    p_ejson.add_argument("--out", default="exports", help="Output directory (default: exports/).")
    p_ejson.set_defaults(func=_cmd_export_json)

    p_backup = sub.add_parser("backup", help="Write a timestamped zip backup (DB + CSV + JSON).")
    p_backup.add_argument("--out", default="backups", help="Output directory (default: backups/).")
    p_backup.set_defaults(func=_cmd_backup)

    p_restore = sub.add_parser(
        "restore-backup", help="Restore the database from a backup zip (backs up current first)."
    )
    p_restore.add_argument("path", help="Path to the backup .zip file.")
    p_restore.add_argument(
        "--yes", action="store_true", help="Confirm overwriting the current database."
    )
    p_restore.set_defaults(func=_cmd_restore_backup)

    sub.add_parser("dashboard", help="Launch the Streamlit dashboard.").set_defaults(
        func=_cmd_dashboard
    )

    # --- Phase 2: read-only TradeLocker sync ---
    sub.add_parser(
        "tradelocker-health", help="Check TradeLocker config/auth (read-only, no secrets printed)."
    ).set_defaults(func=_cmd_tradelocker_health)
    sub.add_parser(
        "tradelocker-accounts", help="List available TradeLocker accounts (read-only)."
    ).set_defaults(func=_cmd_tradelocker_accounts)

    p_sync = sub.add_parser(
        "sync-tradelocker",
        help="Read-only sync from TradeLocker into the local journal (dry-run unless --apply).",
    )
    p_sync.add_argument("--account-id", help="TradeLocker account id to sync.")
    p_sync.add_argument("--acc-num", help="TradeLocker accNum (auto-discovered if omitted).")
    p_sync.add_argument("--all", action="store_true", help="Sync every discovered account.")
    p_sync.add_argument(
        "--lookback-days", type=int, default=None, help="History window in days (default: config)."
    )
    p_sync.add_argument(
        "--apply", action="store_true", help="Write changes (default is a safe dry-run)."
    )
    p_sync.add_argument(
        "--dry-run", action="store_true", help="Explicitly preview without writing (the default)."
    )
    p_sync.set_defaults(func=_cmd_sync_tradelocker)

    p_status = sub.add_parser("sync-status", help="Show recent TradeLocker sync runs.")
    p_status.add_argument("--limit", type=int, default=20, help="How many runs to show.")
    p_status.set_defaults(func=_cmd_sync_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
