"""Metric calculations for the trading journal.

This module contains two layers:

1. **Per-trade calculations** (``compute_planned_rr`` / ``compute_realized_r``)
   implementing the risk/reward rules. These are reused by the importer and
   services so that derived values are computed in exactly one place.
2. **Aggregate metrics** (``compute_metrics``) that summarize a set of trades
   into the dashboard KPIs, plus daily P&L series.

All functions are defensive: missing/None values never raise, and undefined
ratios/averages return ``None`` rather than a misleading ``0``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .models import RMethod, Side, TradeStatus

# ---------------------------------------------------------------------------
# Canonical trade columns used throughout the analytics layer.
# ---------------------------------------------------------------------------
TRADE_COLUMNS: list[str] = [
    "id",
    "account_id",
    "source",
    "external_id",
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
    # Phase 3 review workflow + manual-correction metadata.
    "review_status",
    "reviewed_at",
    "review_notes",
    "mistake_category",
    "exit_reason",
    "is_manual",
    "has_manual_overrides",
    "data_quality_flags_json",
    # Phase 2 sync metadata surfaced for data-quality / detail views.
    "external_status",
    "last_synced_at",
]

_DATE_COLUMNS = ("opened_at", "closed_at", "reviewed_at", "last_synced_at")

_NUMERIC_COLUMNS = [
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
]

# A closed R that is worse than this threshold is treated as "risk control broken"
# by the Journal Score (a stop was blown through, or the position was oversized).
RISK_CONTROL_R_FLOOR = -1.2


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------
def _is_missing(value: Any) -> bool:
    """True if the value is None or NaN."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _to_float(value: Any) -> float | None:
    """Best-effort float conversion; returns None for missing/invalid values."""
    if _is_missing(value):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _mean_or_none(series: pd.Series) -> float | None:
    """Mean of a series, or None if it is empty/all-NaN."""
    clean = series.dropna()
    if clean.empty:
        return None
    return float(clean.mean())


def _sum(series: pd.Series) -> float:
    """Sum of a series treating NaN as 0 (empty sum is 0.0)."""
    return float(series.dropna().sum())


# ---------------------------------------------------------------------------
# Per-trade risk/reward calculations
# ---------------------------------------------------------------------------
def compute_planned_rr(
    side: str | None,
    entry_price: float | None,
    stop_loss: float | None,
    take_profit: float | None,
) -> float | None:
    """Planned reward-to-risk ratio from price distances.

    BUY:  risk = entry - stop_loss,   reward = take_profit - entry
    SELL: risk = stop_loss - entry,   reward = entry - take_profit

    Returns ``reward / risk`` when both risk and reward are strictly positive,
    otherwise ``None``.
    """
    entry = _to_float(entry_price)
    stop = _to_float(stop_loss)
    target = _to_float(take_profit)
    if entry is None or stop is None or target is None or side is None:
        return None

    side = side.upper()
    if side == Side.BUY.value:
        risk = entry - stop
        reward = target - entry
    elif side == Side.SELL.value:
        risk = stop - entry
        reward = entry - target
    else:
        return None

    if risk > 0 and reward > 0:
        return reward / risk
    return None


def compute_realized_r(
    side: str | None,
    entry_price: float | None,
    exit_price: float | None,
    stop_loss: float | None,
    net_pnl: float | None,
    initial_risk_amount: float | None,
) -> tuple[float | None, str]:
    """Realized R multiple and the method used to derive it.

    Preference order:
    1. **money**: ``net_pnl / initial_risk_amount`` when both are present and the
       risk amount is a positive number. This is the most accurate.
    2. **price**: derived from price distances for a closed trade with entry,
       exit, stop, and side. This is an *estimate* and is flagged as such.
    3. **unknown**: neither is possible -> ``(None, "unknown")``.
    """
    risk_amount = _to_float(initial_risk_amount)
    pnl = _to_float(net_pnl)

    # 1. Money-based R (preferred).
    if risk_amount is not None and risk_amount > 0 and pnl is not None:
        return pnl / risk_amount, RMethod.MONEY.value

    # 2. Price-based R (estimate).
    entry = _to_float(entry_price)
    exit_ = _to_float(exit_price)
    stop = _to_float(stop_loss)
    if entry is not None and exit_ is not None and stop is not None and side is not None:
        side_u = side.upper()
        if side_u == Side.BUY.value:
            risk = entry - stop
            move = exit_ - entry
        elif side_u == Side.SELL.value:
            risk = stop - entry
            move = entry - exit_
        else:
            risk = 0.0
            move = 0.0
        if risk > 0:
            return move / risk, RMethod.PRICE.value

    # 3. Not computable.
    return None, RMethod.UNKNOWN.value


# ---------------------------------------------------------------------------
# DataFrame conversion
# ---------------------------------------------------------------------------
def trades_to_dataframe(trades: Iterable[Any]) -> pd.DataFrame:
    """Convert Trade ORM objects (or dicts) into a normalized DataFrame."""
    rows: list[dict[str, Any]] = []
    for trade in trades:
        if isinstance(trade, dict):
            rows.append({col: trade.get(col) for col in TRADE_COLUMNS})
        else:
            rows.append({col: getattr(trade, col, None) for col in TRADE_COLUMNS})

    df = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    if df.empty:
        # Guarantee correct dtypes on empty frames so downstream filters work.
        for col in _DATE_COLUMNS:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        for col in _NUMERIC_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    for col in _DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in _NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def snapshots_to_dataframe(snapshots: Iterable[Any]) -> pd.DataFrame:
    """Convert AccountSnapshot ORM objects (or dicts) into a DataFrame."""
    columns = ["id", "account_id", "timestamp", "balance", "equity", "source"]
    rows: list[dict[str, Any]] = []
    for snap in snapshots:
        if isinstance(snap, dict):
            rows.append({col: snap.get(col) for col in columns})
        else:
            rows.append({col: getattr(snap, col, None) for col in columns})
    df = pd.DataFrame(rows, columns=columns)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for col in ("balance", "equity"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if not df.empty:
        df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _ensure_dataframe(trades: pd.DataFrame | Iterable[Any]) -> pd.DataFrame:
    if isinstance(trades, pd.DataFrame):
        df = trades.copy()
        # Make sure required columns exist even on externally-built frames.
        for col in TRADE_COLUMNS:
            if col not in df.columns:
                df[col] = None
        for col in _DATE_COLUMNS:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        for col in _NUMERIC_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    return trades_to_dataframe(trades)


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------
def latest_account_values(
    snapshots: pd.DataFrame | Iterable[Any] | None,
) -> tuple[float | None, float | None]:
    """Return (latest_balance, latest_equity) from account snapshots."""
    if snapshots is None:
        return None, None
    df = snapshots if isinstance(snapshots, pd.DataFrame) else snapshots_to_dataframe(snapshots)
    if df.empty:
        return None, None
    df = df.sort_values("timestamp")
    last = df.iloc[-1]
    return _to_float(last.get("balance")), _to_float(last.get("equity"))


def daily_pnl_frame(closed_with_pnl: pd.DataFrame) -> pd.DataFrame:
    """Build a per-day P&L frame with cumulative column.

    Days are keyed on ``closed_at`` (the day a trade was realized). Returns a
    DataFrame with columns: ``date``, ``net_pnl``, ``cumulative_net_pnl``.
    """
    columns = ["date", "net_pnl", "cumulative_net_pnl"]
    dated = closed_with_pnl.dropna(subset=["closed_at"])
    if dated.empty:
        return pd.DataFrame(columns=columns)

    grouped = (
        dated.assign(date=dated["closed_at"].dt.normalize())
        .groupby("date", as_index=False)["net_pnl"]
        .sum()
        .sort_values("date")
        .reset_index(drop=True)
    )
    grouped["cumulative_net_pnl"] = grouped["net_pnl"].cumsum()
    return grouped[columns]


def daily_r_frame(closed_with_r: pd.DataFrame) -> pd.DataFrame:
    """Build a per-day realized-R frame keyed on ``closed_at``.

    Columns: ``date``, ``realized_r`` (daily sum), ``cumulative_realized_r``.
    """
    columns = ["date", "realized_r", "cumulative_realized_r"]
    dated = closed_with_r.dropna(subset=["closed_at", "realized_r"])
    if dated.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        dated.assign(date=dated["closed_at"].dt.normalize())
        .groupby("date", as_index=False)["realized_r"]
        .sum()
        .sort_values("date")
        .reset_index(drop=True)
    )
    grouped["cumulative_realized_r"] = grouped["realized_r"].cumsum()
    return grouped[columns]


@dataclass
class DayDetail:
    """Per-day summary used by the Calendar/Reviews day-detail panel."""

    date: Any
    net_pnl: float = 0.0
    total_realized_r: float = 0.0
    avg_realized_r: float | None = None
    trade_count: int = 0
    closed_count: int = 0
    open_count: int = 0
    winning_count: int = 0
    losing_count: int = 0
    breakeven_count: int = 0
    best_trade: dict[str, Any] | None = None
    worst_trade: dict[str, Any] | None = None


def trades_on_day(trades: pd.DataFrame | Iterable[Any], day: Any) -> pd.DataFrame:
    """Return trades opened or closed on the given calendar ``day``."""
    df = _ensure_dataframe(trades)
    if df.empty:
        return df
    target = pd.Timestamp(day).normalize()
    opened = df["opened_at"].dt.normalize()
    closed = df["closed_at"].dt.normalize()
    mask = (opened == target) | (closed == target)
    return df[mask].copy()


def day_detail(trades: pd.DataFrame | Iterable[Any], day: Any) -> DayDetail:
    """Compute the net P&L, realized R, and win/loss breakdown for one day.

    P&L and R are attributed to the day a trade *closed* (was realized). Open
    counts reflect positions opened that day. Never raises on empty/missing data.
    """
    df = _ensure_dataframe(trades)
    target = pd.Timestamp(day).normalize()
    detail = DayDetail(date=pd.Timestamp(day).date())
    if df.empty:
        return detail

    status = df["status"].astype("string").str.upper()
    closed = df[status == TradeStatus.CLOSED.value]
    closed_day = closed[closed["closed_at"].dt.normalize() == target]
    opened_day = df[df["opened_at"].dt.normalize() == target]

    with_pnl = closed_day[closed_day["net_pnl"].notna()]
    winners = with_pnl[with_pnl["net_pnl"] > 0]
    losers = with_pnl[with_pnl["net_pnl"] < 0]
    breakeven = with_pnl[with_pnl["net_pnl"] == 0]
    with_r = closed_day[closed_day["realized_r"].notna()]

    detail.net_pnl = _sum(with_pnl["net_pnl"])
    detail.total_realized_r = _sum(with_r["realized_r"])
    detail.avg_realized_r = _mean_or_none(with_r["realized_r"])
    detail.closed_count = int(len(closed_day))
    detail.open_count = int(
        len(opened_day[opened_day["status"].astype("string").str.upper() == TradeStatus.OPEN.value])
    )
    detail.trade_count = int(len(trades_on_day(df, day)))
    detail.winning_count = int(len(winners))
    detail.losing_count = int(len(losers))
    detail.breakeven_count = int(len(breakeven))

    if not with_pnl.empty:
        detail.best_trade = with_pnl.loc[with_pnl["net_pnl"].idxmax()].to_dict()
        detail.worst_trade = with_pnl.loc[with_pnl["net_pnl"].idxmin()].to_dict()
    return detail


def _max_drawdown(daily: pd.DataFrame) -> float | None:
    """Largest peak-to-trough decline of the cumulative daily P&L curve.

    Returned as a non-negative magnitude. ``None`` when there is no daily data.
    """
    if daily.empty:
        return None
    curve = daily["cumulative_net_pnl"]
    running_max = curve.cummax()
    drawdown = curve - running_max  # <= 0 everywhere
    return float(abs(drawdown.min()))


def _profit_factor(gross_profit: float, gross_loss: float) -> float | None:
    """gross_profit / abs(gross_loss).

    * ``inf`` when there are profits but no losses.
    * ``0.0`` when there are only losses.
    * ``None`` when there is no closed P&L data at all.
    """
    if gross_loss == 0:
        if gross_profit > 0:
            return math.inf
        return None
    return gross_profit / abs(gross_loss)


@dataclass
class TradeMetrics:
    """All dashboard metrics for a set of trades."""

    net_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    trade_count: int = 0
    closed_trade_count: int = 0
    open_trade_count: int = 0
    winning_trade_count: int = 0
    losing_trade_count: int = 0
    breakeven_trade_count: int = 0

    trade_win_pct: float | None = None
    profit_factor: float | None = None

    avg_win: float | None = None
    avg_loss: float | None = None
    avg_win_r: float | None = None
    avg_loss_r: float | None = None
    avg_realized_r: float | None = None
    total_realized_r: float = 0.0
    avg_planned_rr: float | None = None
    expectancy_r: float | None = None

    day_win_pct: float | None = None
    max_drawdown: float | None = None

    latest_balance: float | None = None
    latest_equity: float | None = None

    daily: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=["date", "net_pnl", "cumulative_net_pnl"])
    )

    @property
    def daily_net_pnl(self) -> pd.Series:
        """Series of net P&L per trading day, indexed by date."""
        if self.daily.empty:
            return pd.Series(dtype="float64")
        return self.daily.set_index("date")["net_pnl"]

    @property
    def cumulative_daily_net_pnl(self) -> pd.Series:
        """Series of cumulative net P&L per trading day, indexed by date."""
        if self.daily.empty:
            return pd.Series(dtype="float64")
        return self.daily.set_index("date")["cumulative_net_pnl"]


def compute_metrics(
    trades: pd.DataFrame | Iterable[Any],
    snapshots: pd.DataFrame | Iterable[Any] | None = None,
) -> TradeMetrics:
    """Compute all dashboard metrics from trades (+ optional snapshots).

    ``trades`` may be a normalized DataFrame or an iterable of Trade objects.
    Open trades are counted but never contribute to closed-trade performance
    metrics.
    """
    df = _ensure_dataframe(trades)

    status = df["status"].astype("string").str.upper()
    closed = df[status == TradeStatus.CLOSED.value]
    open_trades = df[status == TradeStatus.OPEN.value]

    closed_with_pnl = closed[closed["net_pnl"].notna()]
    winners = closed_with_pnl[closed_with_pnl["net_pnl"] > 0]
    losers = closed_with_pnl[closed_with_pnl["net_pnl"] < 0]
    breakeven = closed_with_pnl[closed_with_pnl["net_pnl"] == 0]

    gross_profit = _sum(winners["net_pnl"])
    gross_loss = _sum(losers["net_pnl"])  # negative or zero
    net_pnl = _sum(closed_with_pnl["net_pnl"])

    decisive = len(winners) + len(losers)
    trade_win_pct = (len(winners) / decisive * 100.0) if decisive else None

    # Realized-R population (closed trades that have an R value).
    closed_with_r = closed[closed["realized_r"].notna()]
    r_winners = closed_with_r[closed_with_r["realized_r"] > 0]
    r_losers = closed_with_r[closed_with_r["realized_r"] < 0]

    avg_win_r = _mean_or_none(r_winners["realized_r"])
    avg_loss_r = _mean_or_none(r_losers["realized_r"])
    avg_realized_r = _mean_or_none(closed_with_r["realized_r"])
    total_realized_r = _sum(closed_with_r["realized_r"])

    n_r = len(closed_with_r)
    if n_r:
        p_win = len(r_winners) / n_r
        p_loss = len(r_losers) / n_r
        expectancy_r = p_win * (avg_win_r or 0.0) + p_loss * (avg_loss_r or 0.0)
    else:
        expectancy_r = None

    # Planned RR is a pre-trade plan; average it over every trade that has one
    # (open and closed), since it does not depend on the outcome.
    avg_planned_rr = _mean_or_none(df["planned_rr"])

    daily = daily_pnl_frame(closed_with_pnl)
    if not daily.empty:
        winning_days = int((daily["net_pnl"] > 0).sum())
        day_win_pct = winning_days / len(daily) * 100.0
    else:
        day_win_pct = None

    latest_balance, latest_equity = latest_account_values(snapshots)

    return TradeMetrics(
        net_pnl=net_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        trade_count=int(len(df)),
        closed_trade_count=int(len(closed)),
        open_trade_count=int(len(open_trades)),
        winning_trade_count=int(len(winners)),
        losing_trade_count=int(len(losers)),
        breakeven_trade_count=int(len(breakeven)),
        trade_win_pct=trade_win_pct,
        profit_factor=_profit_factor(gross_profit, gross_loss),
        avg_win=_mean_or_none(winners["net_pnl"]),
        avg_loss=_mean_or_none(losers["net_pnl"]),
        avg_win_r=avg_win_r,
        avg_loss_r=avg_loss_r,
        avg_realized_r=avg_realized_r,
        total_realized_r=total_realized_r,
        avg_planned_rr=avg_planned_rr,
        expectancy_r=expectancy_r,
        day_win_pct=day_win_pct,
        max_drawdown=_max_drawdown(daily),
        latest_balance=latest_balance,
        latest_equity=latest_equity,
        daily=daily,
    )
