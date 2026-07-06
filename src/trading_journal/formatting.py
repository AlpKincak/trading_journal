"""Small display-formatting helpers shared by the CLI and the Streamlit UI.

Centralized so that ``None`` and infinite profit factor render consistently
everywhere (``—`` for missing, ``∞`` for undefined-but-good profit factor).
"""

from __future__ import annotations

import math

MISSING = "—"


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def fmt_money(value: float | None, currency: str = "$", nd: int = 2) -> str:
    if _is_missing(value):
        return MISSING
    assert value is not None
    sign = "-" if value < 0 else ""
    return f"{sign}{currency}{abs(value):,.{nd}f}"


def fmt_r(value: float | None, nd: int = 2) -> str:
    if _is_missing(value):
        return MISSING
    assert value is not None
    return f"{value:+.{nd}f}R"


def fmt_pct(value: float | None, nd: int = 1) -> str:
    if _is_missing(value):
        return MISSING
    assert value is not None
    return f"{value:.{nd}f}%"


def fmt_ratio(value: float | None, nd: int = 2) -> str:
    if _is_missing(value):
        return MISSING
    assert value is not None
    if math.isinf(value):
        return "∞"
    return f"{value:.{nd}f}"


def fmt_num(value: float | None, nd: int = 2) -> str:
    if _is_missing(value):
        return MISSING
    assert value is not None
    return f"{value:,.{nd}f}"
