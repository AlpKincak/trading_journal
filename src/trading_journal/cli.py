"""Command-line interface: ``trading-journal <command>``.

Commands
--------
* ``init-db``               Create the SQLite schema.
* ``seed-demo``             Load the bundled deterministic demo data.
* ``import-csv PATH``       Import trades from a CSV file.
* ``metrics``               Print a summary of dashboard metrics.
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
from pathlib import Path

from . import __version__
from .config import get_settings, get_tradelocker_settings
from .connectors.tradelocker import (
    TradeLockerConfigError,
    TradeLockerError,
    TradeLockerReadOnlyClient,
)
from .db import init_db, session_scope
from .formatting import fmt_money, fmt_num, fmt_pct, fmt_r, fmt_ratio
from .importers.csv_importer import import_csv
from .journal_score import compute_journal_score
from .metrics import compute_metrics
from .seed import seed_demo
from .services.account_service import snapshots_dataframe
from .services.sync_service import SyncResult, build_sync_service
from .services.sync_state_service import sync_runs_dataframe
from .services.trade_service import trades_dataframe

APP_PATH = Path(__file__).resolve().parent / "ui" / "streamlit_app.py"


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
    metrics = compute_metrics(trades, snaps)
    score = compute_journal_score(trades, metrics)

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

    sub.add_parser("metrics", help="Print a metrics summary.").set_defaults(func=_cmd_metrics)
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
