"""Non-strategy risk & R analytics for the Analytics tab.

Everything here is generic trade/risk analysis (R distribution, streaks, trade
durations, risk consistency, and simple weekday/symbol/side breakdowns). There is
deliberately **no** strategy/setup analysis — all trades are assumed to come from
one strategy, so strategy breakdowns are out of scope for v1.

All functions are defensive: empty/partial data yields ``None`` scalars and empty
DataFrames rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .metrics import (
    _ensure_dataframe,
    _mean_or_none,
    _sum,
    daily_pnl_frame,
    daily_r_frame,
)
from .models import RMethod, TradeStatus

_WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class RiskAnalytics:
    """All non-strategy analytics for a set of trades."""

    closed_trade_count: int = 0
    r_trade_count: int = 0

    total_realized_r: float = 0.0
    avg_realized_r: float | None = None
    median_realized_r: float | None = None
    std_realized_r: float | None = None
    best_r: float | None = None
    worst_r: float | None = None
    avg_planned_rr: float | None = None
    median_planned_rr: float | None = None

    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    current_streak: int = 0  # >0 = winning streak, <0 = losing streak

    avg_trade_duration_hours: float | None = None
    avg_winner_duration_hours: float | None = None
    avg_loser_duration_hours: float | None = None

    largest_winning_day: float | None = None
    largest_losing_day: float | None = None
    largest_winning_day_date: Any = None
    largest_losing_day_date: Any = None

    avg_initial_risk: float | None = None
    median_initial_risk: float | None = None
    min_initial_risk: float | None = None
    max_initial_risk: float | None = None
    risk_coefficient_of_variation: float | None = None
    risk_sample_size: int = 0

    r_method_counts: dict[str, int] = field(default_factory=dict)
    pct_money_r: float | None = None
    pct_price_r: float | None = None
    pct_manual_r: float | None = None
    pct_unknown_r: float | None = None

    cumulative_r: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(
            columns=["date", "realized_r", "cumulative_realized_r"]
        )
    )
    daily_pnl: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=["date", "net_pnl", "cumulative_net_pnl"])
    )
    realized_r_values: pd.Series = field(default_factory=lambda: pd.Series(dtype="float64"))
    planned_rr_values: pd.Series = field(default_factory=lambda: pd.Series(dtype="float64"))
    weekday_performance: pd.DataFrame = field(default_factory=pd.DataFrame)
    symbol_performance: pd.DataFrame = field(default_factory=pd.DataFrame)
    side_performance: pd.DataFrame = field(default_factory=pd.DataFrame)


def _std_or_none(series: pd.Series, ddof: int = 1) -> float | None:
    clean = series.dropna()
    if len(clean) < ddof + 1:
        return None
    return float(clean.std(ddof=ddof))


def _median_or_none(series: pd.Series) -> float | None:
    clean = series.dropna()
    if clean.empty:
        return None
    return float(clean.median())


def _streaks(wins: list[bool]) -> tuple[int, int, int]:
    """Return (max_consecutive_wins, max_consecutive_losses, current_streak).

    ``wins`` is an ordered list where True is a winning trade and False a losing
    one (breakeven/undecided trades should be excluded before calling).
    """
    max_win = max_loss = 0
    run_win = run_loss = 0
    for is_win in wins:
        if is_win:
            run_win += 1
            run_loss = 0
            max_win = max(max_win, run_win)
        else:
            run_loss += 1
            run_win = 0
            max_loss = max(max_loss, run_loss)
    if not wins:
        current = 0
    else:
        current = run_win if wins[-1] else -run_loss
    return max_win, max_loss, current


def _duration_hours(df: pd.DataFrame) -> pd.Series:
    """Trade durations in hours for rows with both open and close timestamps."""
    both = df.dropna(subset=["opened_at", "closed_at"])
    if both.empty:
        return pd.Series(dtype="float64")
    delta = both["closed_at"] - both["opened_at"]
    return delta.dt.total_seconds() / 3600.0


def _weekday_performance(closed_with_pnl: pd.DataFrame) -> pd.DataFrame:
    columns = ["weekday", "trades", "net_pnl", "avg_realized_r", "win_rate"]
    if closed_with_pnl.empty:
        return pd.DataFrame(columns=columns)
    d = closed_with_pnl.copy()
    d["weekday"] = d["closed_at"].dt.dayofweek
    rows = []
    for wd, group in d.groupby("weekday"):
        decisive = group[group["net_pnl"] != 0]
        wins = int((group["net_pnl"] > 0).sum())
        win_rate = (wins / len(decisive) * 100.0) if len(decisive) else None
        rows.append(
            {
                "weekday": _WEEKDAY_ORDER[int(wd)],
                "trades": int(len(group)),
                "net_pnl": _sum(group["net_pnl"]),
                "avg_realized_r": _mean_or_none(group["realized_r"]),
                "win_rate": win_rate,
                "_order": int(wd),
            }
        )
    out = pd.DataFrame(rows).sort_values("_order").drop(columns="_order").reset_index(drop=True)
    return out[columns]


def _group_performance(closed_with_pnl: pd.DataFrame, key: str) -> pd.DataFrame:
    columns = [key, "trades", "net_pnl", "avg_realized_r", "win_rate"]
    if closed_with_pnl.empty or key not in closed_with_pnl.columns:
        return pd.DataFrame(columns=columns)
    rows = []
    for value, group in closed_with_pnl.groupby(closed_with_pnl[key].astype("string")):
        decisive = group[group["net_pnl"] != 0]
        wins = int((group["net_pnl"] > 0).sum())
        win_rate = (wins / len(decisive) * 100.0) if len(decisive) else None
        rows.append(
            {
                key: value,
                "trades": int(len(group)),
                "net_pnl": _sum(group["net_pnl"]),
                "avg_realized_r": _mean_or_none(group["realized_r"]),
                "win_rate": win_rate,
            }
        )
    out = pd.DataFrame(rows).sort_values("net_pnl", ascending=False).reset_index(drop=True)
    return out[columns]


def compute_risk_analytics(trades: pd.DataFrame | Any) -> RiskAnalytics:
    """Compute the full non-strategy analytics bundle from a set of trades."""
    df = _ensure_dataframe(trades)
    status = df["status"].astype("string").str.upper()
    closed = df[status == TradeStatus.CLOSED.value]

    result = RiskAnalytics(closed_trade_count=int(len(closed)))
    if closed.empty and df.empty:
        return result

    closed_with_pnl = closed[closed["net_pnl"].notna()]
    closed_with_r = closed[closed["realized_r"].notna()]

    # --- R distribution ---
    r_values = closed_with_r["realized_r"]
    result.r_trade_count = int(len(r_values))
    result.total_realized_r = _sum(r_values)
    result.avg_realized_r = _mean_or_none(r_values)
    result.median_realized_r = _median_or_none(r_values)
    result.std_realized_r = _std_or_none(r_values)
    result.best_r = float(r_values.max()) if not r_values.dropna().empty else None
    result.worst_r = float(r_values.min()) if not r_values.dropna().empty else None
    result.realized_r_values = r_values.dropna().reset_index(drop=True)

    planned = df["planned_rr"].dropna()
    result.avg_planned_rr = _mean_or_none(planned)
    result.median_planned_rr = _median_or_none(planned)
    result.planned_rr_values = planned.reset_index(drop=True)

    # --- streaks (decisive closed trades in chronological order) ---
    decisive = closed_with_pnl[closed_with_pnl["net_pnl"] != 0].copy()
    if not decisive.empty:
        decisive["_sort"] = decisive["closed_at"].fillna(decisive["opened_at"])
        decisive = decisive.sort_values(["_sort", "id"], na_position="last")
        wins = [bool(v > 0) for v in decisive["net_pnl"]]
        result.max_consecutive_wins, result.max_consecutive_losses, result.current_streak = (
            _streaks(wins)
        )

    # --- durations ---
    result.avg_trade_duration_hours = _mean_or_none(_duration_hours(closed))
    result.avg_winner_duration_hours = _mean_or_none(
        _duration_hours(closed_with_pnl[closed_with_pnl["net_pnl"] > 0])
    )
    result.avg_loser_duration_hours = _mean_or_none(
        _duration_hours(closed_with_pnl[closed_with_pnl["net_pnl"] < 0])
    )

    # --- daily P&L / cumulative R ---
    daily = daily_pnl_frame(closed_with_pnl)
    result.daily_pnl = daily
    result.cumulative_r = daily_r_frame(closed_with_r)
    if not daily.empty:
        best_idx = daily["net_pnl"].idxmax()
        worst_idx = daily["net_pnl"].idxmin()
        result.largest_winning_day = float(daily.loc[best_idx, "net_pnl"])
        result.largest_winning_day_date = daily.loc[best_idx, "date"]
        result.largest_losing_day = float(daily.loc[worst_idx, "net_pnl"])
        result.largest_losing_day_date = daily.loc[worst_idx, "date"]

    # --- risk consistency ---
    ira = df["initial_risk_amount"].dropna()
    ira = ira[ira > 0]
    result.risk_sample_size = int(len(ira))
    if not ira.empty:
        result.avg_initial_risk = float(ira.mean())
        result.median_initial_risk = float(ira.median())
        result.min_initial_risk = float(ira.min())
        result.max_initial_risk = float(ira.max())
        std = _std_or_none(ira)
        mean = result.avg_initial_risk
        if std is not None and mean and mean != 0:
            result.risk_coefficient_of_variation = std / mean

    # --- risk-multiple quality (how R was derived across closed trades) ---
    if not closed.empty:
        methods = closed["r_method"].astype("string").fillna(RMethod.UNKNOWN.value)
        counts = methods.value_counts().to_dict()
        result.r_method_counts = {str(k): int(v) for k, v in counts.items()}
        n = int(len(closed))
        result.pct_money_r = counts.get(RMethod.MONEY.value, 0) / n * 100.0
        result.pct_price_r = counts.get(RMethod.PRICE.value, 0) / n * 100.0
        result.pct_manual_r = counts.get(RMethod.MANUAL.value, 0) / n * 100.0
        result.pct_unknown_r = counts.get(RMethod.UNKNOWN.value, 0) / n * 100.0

    # --- breakdowns ---
    result.weekday_performance = _weekday_performance(closed_with_pnl)
    result.symbol_performance = _group_performance(closed_with_pnl, "symbol")
    result.side_performance = _group_performance(closed_with_pnl, "side")

    return result
