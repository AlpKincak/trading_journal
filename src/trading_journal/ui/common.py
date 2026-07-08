"""Shared Streamlit helpers: data loaders and table-display formatting.

Kept separate from ``streamlit_app`` so the individual tab modules (trades,
analytics, reviews) can import these without a circular dependency on the app
entry point. Business logic stays in the services/metrics/analytics layers; this
module only shapes data for display.
"""

from __future__ import annotations

import pandas as pd

from trading_journal.db import session_scope
from trading_journal.services.account_service import list_accounts, snapshots_dataframe
from trading_journal.services.trade_service import distinct_symbols, trades_dataframe

TRADE_DISPLAY_COLUMNS = [
    "id",
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
    "review_status",
    "mistake_category",
    "notes",
]

OPEN_DISPLAY_COLUMNS = [
    "id",
    "opened_at",
    "symbol",
    "side",
    "entry_price",
    "quantity",
    "stop_loss",
    "take_profit",
    "initial_risk_amount",
    "planned_rr",
    "review_status",
    "notes",
]

_NUMERIC_DISPLAY = (
    "net_pnl",
    "realized_r",
    "planned_rr",
    "entry_price",
    "exit_price",
    "stop_loss",
    "take_profit",
    "initial_risk_amount",
    "quantity",
)


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


def prep_display(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Select display columns and round numeric ones for readability."""
    if df.empty:
        return pd.DataFrame(columns=columns)
    present = [c for c in columns if c in df.columns]
    out = df[present].copy()
    for col in _NUMERIC_DISPLAY:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(5)
    return out


def kpi(col, label: str, value: str, help_text: str | None = None) -> None:
    col.metric(label, value, help=help_text)
