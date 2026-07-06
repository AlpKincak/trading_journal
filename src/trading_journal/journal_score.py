"""Journal Score: a transparent, local 0-100 quality score.

This is **not** TradeZella's proprietary Zella Score. It is a simple, fully
documented rubric that rewards good *journaling and risk-tracking habits*, not
just profitability. Every component and its formula is shown to the user.

Rubric (max points)
--------------------
* Data completeness  (30) - closed trades with the core fields filled in.
* Risk tracking      (25) - closed trades where R is knowable (money or price).
* Risk control       (20) - losing trades that respected the stop (R >= -1.2).
* Performance health  (15) - positive expectancy in R and profit factor > 1.
* Review completeness (10) - closed trades that have written notes.

Each component also reports a confidence (HIGH/MEDIUM/LOW) based on sample size,
and the overall score carries an overall confidence label. Low confidence means
"not enough data to trust this number yet", not "bad".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .metrics import (
    RISK_CONTROL_R_FLOOR,
    TradeMetrics,
    _ensure_dataframe,
    _to_float,
    compute_metrics,
)
from .models import TradeStatus

# Component maximum points.
MAX_COMPLETENESS = 30.0
MAX_RISK_TRACKING = 25.0
MAX_RISK_CONTROL = 20.0
MAX_PERFORMANCE = 15.0
MAX_REVIEW = 10.0

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"


@dataclass
class ScoreComponent:
    """One line of the Journal Score breakdown."""

    key: str
    label: str
    points: float
    max_points: float
    detail: str
    confidence: str


@dataclass
class JournalScore:
    """Overall Journal Score plus its component breakdown."""

    score: float
    components: list[ScoreComponent]
    confidence: str
    explanation: str

    def to_frame(self) -> pd.DataFrame:
        """Component breakdown as a DataFrame for display."""
        return pd.DataFrame(
            [
                {
                    "Component": c.label,
                    "Points": round(c.points, 1),
                    "Max": c.max_points,
                    "Confidence": c.confidence,
                    "Detail": c.detail,
                }
                for c in self.components
            ]
        )


def _sample_confidence(n: int) -> str:
    """Confidence purely from sample size."""
    if n >= 20:
        return CONFIDENCE_HIGH
    if n >= 8:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _nonempty_string_mask(series: pd.Series) -> pd.Series:
    """Boolean mask: True where the value is a non-empty, non-whitespace string."""
    as_str = series.astype("string").str.strip()
    return series.notna() & (as_str != "")


def _price_r_computable(row: pd.Series) -> bool:
    """True when a price-based R could be derived for this (closed) trade."""
    entry = _to_float(row.get("entry_price"))
    exit_ = _to_float(row.get("exit_price"))
    stop = _to_float(row.get("stop_loss"))
    side = row.get("side")
    if entry is None or exit_ is None or stop is None or side is None or pd.isna(side):
        return False
    side_u = str(side).upper()
    if side_u == "BUY":
        risk = entry - stop
    elif side_u == "SELL":
        risk = stop - entry
    else:
        return False
    return risk > 0


def _risk_tracked(row: pd.Series) -> bool:
    """True when risk is knowable: a recorded risk amount or a computable price R."""
    ira = _to_float(row.get("initial_risk_amount"))
    if ira is not None and ira > 0:
        return True
    return _price_r_computable(row)


def _completeness_component(closed: pd.DataFrame) -> ScoreComponent:
    n = len(closed)
    if n == 0:
        return ScoreComponent(
            "completeness",
            "Data completeness",
            0.0,
            MAX_COMPLETENESS,
            "No closed trades yet.",
            CONFIDENCE_LOW,
        )
    complete = (
        closed["net_pnl"].notna()
        & closed["opened_at"].notna()
        & closed["closed_at"].notna()
        & _nonempty_string_mask(closed["side"])
        & _nonempty_string_mask(closed["symbol"])
    )
    frac = complete.mean()
    return ScoreComponent(
        "completeness",
        "Data completeness",
        MAX_COMPLETENESS * frac,
        MAX_COMPLETENESS,
        f"{int(complete.sum())}/{n} closed trades have all core fields.",
        _sample_confidence(n),
    )


def _risk_tracking_component(closed: pd.DataFrame) -> ScoreComponent:
    n = len(closed)
    if n == 0:
        return ScoreComponent(
            "risk_tracking",
            "Risk tracking",
            0.0,
            MAX_RISK_TRACKING,
            "No closed trades yet.",
            CONFIDENCE_LOW,
        )
    tracked = closed.apply(_risk_tracked, axis=1)
    frac = tracked.mean()
    return ScoreComponent(
        "risk_tracking",
        "Risk tracking",
        MAX_RISK_TRACKING * frac,
        MAX_RISK_TRACKING,
        f"{int(tracked.sum())}/{n} closed trades have a knowable R (money or price).",
        _sample_confidence(n),
    )


def _risk_control_component(closed: pd.DataFrame) -> ScoreComponent:
    losers = closed[closed["net_pnl"].notna() & (closed["net_pnl"] < 0)]
    assessable = losers[losers["realized_r"].notna()]
    n_assess = len(assessable)

    # Insufficient data: award a neutral half-credit and flag it, never misleading.
    if len(losers) == 0:
        return ScoreComponent(
            "risk_control",
            "Risk control",
            MAX_RISK_CONTROL * 0.5,
            MAX_RISK_CONTROL,
            "No losing trades to assess (neutral placeholder).",
            CONFIDENCE_LOW,
        )
    if n_assess == 0:
        return ScoreComponent(
            "risk_control",
            "Risk control",
            MAX_RISK_CONTROL * 0.5,
            MAX_RISK_CONTROL,
            "Losing trades have no R data to assess (neutral placeholder).",
            CONFIDENCE_LOW,
        )

    respected = assessable["realized_r"] >= RISK_CONTROL_R_FLOOR
    frac = respected.mean()
    confidence = _sample_confidence(n_assess) if n_assess >= 8 else CONFIDENCE_LOW
    return ScoreComponent(
        "risk_control",
        "Risk control",
        MAX_RISK_CONTROL * frac,
        MAX_RISK_CONTROL,
        f"{int(respected.sum())}/{n_assess} losing trades kept R >= {RISK_CONTROL_R_FLOOR}.",
        confidence,
    )


def _performance_component(metrics: TradeMetrics) -> ScoreComponent:
    half = MAX_PERFORMANCE / 2.0  # 7.5 each for expectancy and profit factor
    exp = metrics.expectancy_r
    pf = metrics.profit_factor

    if exp is None:
        exp_pts = 0.0
    elif exp >= 0.1:
        exp_pts = half
    elif exp >= 0.0:
        exp_pts = half / 2.0
    else:
        exp_pts = 0.0

    if pf is None:
        pf_pts = 0.0
    elif pf >= 1.5:  # includes +inf (profits, no losses)
        pf_pts = half
    elif pf >= 1.0:
        pf_pts = half / 2.0
    else:
        pf_pts = 0.0

    exp_txt = "n/a" if exp is None else f"{exp:.2f}R"
    pf_txt = "n/a" if pf is None else ("∞" if pf == float("inf") else f"{pf:.2f}")
    confidence = _sample_confidence(metrics.closed_trade_count)
    return ScoreComponent(
        "performance",
        "Performance health",
        exp_pts + pf_pts,
        MAX_PERFORMANCE,
        f"Expectancy {exp_txt}, profit factor {pf_txt}.",
        confidence,
    )


def _review_component(closed: pd.DataFrame) -> ScoreComponent:
    n = len(closed)
    if n == 0:
        return ScoreComponent(
            "review",
            "Review completeness",
            0.0,
            MAX_REVIEW,
            "No closed trades yet.",
            CONFIDENCE_LOW,
        )
    has_notes = _nonempty_string_mask(closed["notes"])
    frac = has_notes.mean()
    return ScoreComponent(
        "review",
        "Review completeness",
        MAX_REVIEW * frac,
        MAX_REVIEW,
        f"{int(has_notes.sum())}/{n} closed trades have notes.",
        _sample_confidence(n),
    )


def _overall_confidence(closed: pd.DataFrame, completeness: ScoreComponent) -> str:
    n = len(closed)
    completeness_frac = (
        completeness.points / completeness.max_points if completeness.max_points else 0
    )
    if n >= 20 and completeness_frac >= 0.8:
        return CONFIDENCE_HIGH
    if n >= 8 and completeness_frac >= 0.5:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def compute_journal_score(
    trades: pd.DataFrame | Any,
    metrics: TradeMetrics | None = None,
) -> JournalScore:
    """Compute the Journal Score and its component breakdown."""
    df = _ensure_dataframe(trades)
    if metrics is None:
        metrics = compute_metrics(df)

    status = df["status"].astype("string").str.upper()
    closed = df[status == TradeStatus.CLOSED.value]

    completeness = _completeness_component(closed)
    components = [
        completeness,
        _risk_tracking_component(closed),
        _risk_control_component(closed),
        _performance_component(metrics),
        _review_component(closed),
    ]

    raw = sum(c.points for c in components)
    score = max(0.0, min(100.0, raw))
    confidence = _overall_confidence(closed, completeness)

    explanation = (
        "Journal Score is a transparent local metric (0-100) rewarding good "
        "journaling and risk habits, not just profit. It is NOT TradeZella's "
        "Zella Score. Confidence reflects how much data backs the number."
    )
    return JournalScore(
        score=round(score, 1),
        components=components,
        confidence=confidence,
        explanation=explanation,
    )
