"""Command-line interface: ``trading-journal <command>``.

Commands
--------
* ``init-db``            Create the SQLite schema.
* ``seed-demo``         Load the bundled deterministic demo data.
* ``import-csv PATH``   Import trades from a CSV file.
* ``metrics``           Print a summary of dashboard metrics.
* ``dashboard``         Launch the Streamlit dashboard.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import get_settings
from .db import init_db, session_scope
from .formatting import fmt_money, fmt_num, fmt_pct, fmt_r, fmt_ratio
from .importers.csv_importer import import_csv
from .journal_score import compute_journal_score
from .metrics import compute_metrics
from .seed import seed_demo
from .services.account_service import snapshots_dataframe
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-journal",
        description="A local, TradeZella-lite forex trading journal (Phase 1).",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
