"""Data-quality checks and the "Needs Review" queue.

These operate on a normalized trades DataFrame (see :func:`metrics.trades_to_dataframe`)
so both the CLI and Streamlit can share the exact same logic. Nothing here writes
to the database — it only surfaces where local data is missing, estimated, or
conflicting so the user can decide what to correct.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .metrics import _ensure_dataframe
from .models import ReviewStatus, RMethod, TradeStatus

SOURCE_TRADELOCKER = "tradelocker"
STALE_STATUS = "STALE"


def _closed_mask(df: pd.DataFrame) -> pd.Series:
    return df["status"].astype("string").str.upper() == TradeStatus.CLOSED.value


def _has_sync_conflict(raw: Any) -> bool:
    if not raw or not isinstance(raw, str):
        return False
    try:
        flags = json.loads(raw)
    except (ValueError, TypeError):
        return False
    return isinstance(flags, dict) and "sync_conflict" in flags


def _invalid_planned_rr_mask(df: pd.DataFrame) -> pd.Series:
    """Trades that *should* have a planned RR (stop + target set) but don't."""
    return df["stop_loss"].notna() & df["take_profit"].notna() & df["planned_rr"].isna()


def duplicate_like_ids(df: pd.DataFrame) -> list[int]:
    """Ids of trades that look like duplicates (same symbol/side/open time).

    A soft heuristic to flag possible double-imports or partial-close artifacts
    for manual review — it never deletes anything.
    """
    if df.empty:
        return []
    keyed = df.dropna(subset=["opened_at"]).copy()
    if keyed.empty:
        return []
    keyed["_key"] = (
        keyed["symbol"].astype("string").str.upper()
        + "|"
        + keyed["side"].astype("string").str.upper()
        + "|"
        + keyed["opened_at"].astype("string")
    )
    dup_mask = keyed["_key"].duplicated(keep=False)
    ids = keyed.loc[dup_mask, "id"].dropna().tolist()
    return [int(i) for i in ids]


def data_quality_report(trades: pd.DataFrame | Any) -> pd.DataFrame:
    """A table of named data-quality checks and their counts."""
    df = _ensure_dataframe(trades)
    closed = df[_closed_mask(df)]
    source = df["source"].astype("string").str.lower()
    r_method = df["r_method"].astype("string").str.lower()
    external_status = df["external_status"].astype("string").str.upper()
    review_status = df["review_status"].astype("string").str.upper()

    unknown_r_closed = closed[
        closed["realized_r"].isna()
        | (closed["r_method"].astype("string").str.lower() == RMethod.UNKNOWN.value)
    ]
    estimated_synced = df[(source == SOURCE_TRADELOCKER) & (r_method == RMethod.PRICE.value)]
    conflicts = df["data_quality_flags_json"].apply(_has_sync_conflict)

    checks = {
        "Closed trades missing net P&L": int(closed["net_pnl"].isna().sum()),
        "Closed trades missing open/close time": int(
            (closed["opened_at"].isna() | closed["closed_at"].isna()).sum()
        ),
        "Trades missing stop loss": int(df["stop_loss"].isna().sum()),
        "Trades missing initial risk amount": int(df["initial_risk_amount"].isna().sum()),
        "Trades with invalid planned RR": int(_invalid_planned_rr_mask(df).sum()),
        "Closed trades with unknown R": int(len(unknown_r_closed)),
        "Synced trades with estimated (price) R": int(len(estimated_synced)),
        "Open positions gone stale after sync": int((external_status == STALE_STATUS).sum()),
        "Synced trades with manual conflicts": int(conflicts.sum()),
        "Duplicate-like trades (review)": len(duplicate_like_ids(df)),
        "Trades marked Needs Fix": int((review_status == ReviewStatus.NEEDS_FIX.value).sum()),
    }
    return pd.DataFrame([{"Check": k, "Count": v} for k, v in checks.items()])


NEEDS_REVIEW_COLUMNS = [
    "id",
    "opened_at",
    "closed_at",
    "symbol",
    "side",
    "status",
    "net_pnl",
    "realized_r",
    "r_method",
    "review_status",
    "reasons",
]


def _row_reasons(row: pd.Series, duplicates: set[int]) -> list[str]:
    reasons: list[str] = []
    is_closed = str(row.get("status") or "").upper() == TradeStatus.CLOSED.value
    source = str(row.get("source") or "").lower()
    r_method = str(row.get("r_method") or "").lower()

    if str(row.get("review_status") or "").upper() == ReviewStatus.NEEDS_FIX.value:
        reasons.append("marked NEEDS_FIX")
    if _has_sync_conflict(row.get("data_quality_flags_json")):
        reasons.append("sync conflict vs manual edit")
    if str(row.get("external_status") or "").upper() == STALE_STATUS:
        reasons.append("stale open position")
    if is_closed and (pd.isna(row.get("realized_r")) or r_method == RMethod.UNKNOWN.value):
        reasons.append("unknown R")
    if is_closed and pd.isna(row.get("net_pnl")):
        reasons.append("missing net P&L")
    if is_closed and pd.isna(row.get("initial_risk_amount")) and r_method != RMethod.MONEY.value:
        reasons.append("no money-based risk")
    if source == SOURCE_TRADELOCKER and r_method == RMethod.PRICE.value:
        reasons.append("estimated (price) R")
    if not pd.isna(row.get("id")) and int(row["id"]) in duplicates:
        reasons.append("possible duplicate")
    return reasons


def needs_review_frame(trades: pd.DataFrame | Any) -> pd.DataFrame:
    """Rows that need attention, each annotated with the reason(s)."""
    df = _ensure_dataframe(trades)
    if df.empty:
        return pd.DataFrame(columns=NEEDS_REVIEW_COLUMNS)

    duplicates = set(duplicate_like_ids(df))
    rows = []
    for _, row in df.iterrows():
        reasons = _row_reasons(row, duplicates)
        if not reasons:
            continue
        record = {col: row.get(col) for col in NEEDS_REVIEW_COLUMNS if col != "reasons"}
        record["reasons"] = "; ".join(reasons)
        rows.append(record)

    out = pd.DataFrame(rows, columns=NEEDS_REVIEW_COLUMNS)
    if not out.empty:
        out = out.sort_values("opened_at", ascending=False).reset_index(drop=True)
    return out
