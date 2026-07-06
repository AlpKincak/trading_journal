"""Flexible CSV importer for trades.

Goals:
* Accept common column-name variants (``pair`` -> ``symbol``, ``sl`` -> ``stop_loss``).
* Parse dates and messy numbers ("$1,234.50", "(50.00)").
* Normalize ``side`` (BUY/SELL) and ``status`` (OPEN/CLOSED).
* Derive missing ``planned_rr`` / ``realized_r`` / ``net_pnl`` when possible.
* Never silently drop bad rows: failures are reported with clear per-row errors,
  and softer data-quality issues are surfaced as warnings.
* Prevent duplicate imports using ``external_id``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..metrics import compute_planned_rr, compute_realized_r
from ..models import Trade, TradeStatus, normalize_side, normalize_status

# ---------------------------------------------------------------------------
# Column aliases (human-friendly; normalized at import time).
# ---------------------------------------------------------------------------
COLUMN_ALIASES: dict[str, list[str]] = {
    "symbol": ["symbol", "pair", "instrument", "ticker", "market"],
    "side": ["side", "direction", "buy_sell", "type", "action"],
    "status": ["status", "state"],
    "opened_at": ["opened_at", "open_time", "entry_time", "open_date", "date_opened", "open"],
    "closed_at": ["closed_at", "close_time", "exit_time", "close_date", "date_closed", "close"],
    "entry_price": ["entry_price", "entry", "open_price", "price_in"],
    "exit_price": ["exit_price", "exit", "close_price", "price_out"],
    "quantity": ["quantity", "size", "lots", "volume", "qty", "units"],
    "stop_loss": ["stop_loss", "sl", "stop", "stoploss"],
    "take_profit": ["take_profit", "tp", "target", "takeprofit"],
    "initial_risk_amount": ["initial_risk_amount", "risk_amount", "risk", "risk_usd"],
    "gross_pnl": ["gross_pnl", "pnl", "gross", "gross_profit", "p_l"],
    "fees": ["fees", "commission", "commissions", "fee", "cost"],
    "net_pnl": ["net_pnl", "net_profit", "profit", "net", "realized_pnl"],
    "notes": ["notes", "note", "comment", "comments", "journal", "remarks"],
    "external_id": ["external_id", "id", "trade_id", "ticket", "order_id", "deal_id", "ref"],
}

_BLANK_TOKENS = {"", "nan", "none", "null", "na", "n/a", "-"}

# Columns written to the Trade model (source is added separately).
_TRADE_FIELDS = [
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
]


def _normalize_header(name: Any) -> str:
    """Lowercase a header and collapse non-alphanumerics into single underscores."""
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# Reverse map: normalized alias -> canonical column name.
_REVERSE_ALIASES: dict[str, str] = {}
for _canonical, _aliases in COLUMN_ALIASES.items():
    for _alias in _aliases:
        _REVERSE_ALIASES.setdefault(_normalize_header(_alias), _canonical)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------
@dataclass
class RowError:
    """A single row that failed validation and was not imported."""

    row_number: int  # 1-based data row (header excluded)
    errors: list[str]
    raw: dict[str, Any]


@dataclass
class ParsedImport:
    """Result of parsing (pre-database): valid rows, failures, and warnings."""

    trades: list[dict[str, Any]] = field(default_factory=list)
    row_errors: list[RowError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return len(self.trades)

    @property
    def error_count(self) -> int:
        return len(self.row_errors)


@dataclass
class ImportResult:
    """Result of importing parsed rows into the database."""

    imported: int = 0
    skipped_duplicates: int = 0
    failed: int = 0
    row_errors: list[RowError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_trade_ids: list[int] = field(default_factory=list)
    account_id: int | None = None

    def summary(self) -> str:
        return (
            f"imported={self.imported} skipped_duplicates={self.skipped_duplicates} "
            f"failed={self.failed} warnings={len(self.warnings)}"
        )


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------
def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    if s == "" or s.lower() in _BLANK_TOKENS:
        return None
    return s


def _coerce_float(value: Any) -> float | None:
    """Parse a possibly-messy numeric cell. Raises ValueError if not parseable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    s = str(value).strip()
    if s.lower() in _BLANK_TOKENS:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = s.replace(",", "").replace("$", "").replace("%", "").strip()
    if s.lower() in _BLANK_TOKENS:
        return None
    value_f = float(s)  # ValueError bubbles up to the caller
    return -value_f if negative else value_f


def _coerce_date(value: Any) -> datetime | None:
    """Parse a date/datetime cell. Raises ValueError if not parseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if s.lower() in _BLANK_TOKENS:
        return None
    ts = pd.to_datetime(s, errors="raise")
    return ts.to_pydatetime()


def _normalize_side(value: Any) -> str | None:
    return normalize_side(_clean_str(value))


def _normalize_status(value: Any) -> str | None:
    return normalize_status(_clean_str(value))


# ---------------------------------------------------------------------------
# Column normalization
# ---------------------------------------------------------------------------
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to their canonical names using the alias map."""
    rename: dict[Any, str] = {}
    for col in df.columns:
        norm = _normalize_header(col)
        rename[col] = _REVERSE_ALIASES.get(norm, norm)
    out = df.rename(columns=rename)
    # If aliasing produced duplicate canonical columns, keep the first occurrence.
    out = out.loc[:, ~out.columns.duplicated()]
    return out


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _get(row: pd.Series, key: str) -> Any:
    return row[key] if key in row.index else None


def _try_float(row: pd.Series, key: str, errors: list[str]) -> float | None:
    try:
        return _coerce_float(_get(row, key))
    except (ValueError, TypeError):
        errors.append(f"invalid number for '{key}': {_get(row, key)!r}")
        return None


def _try_date(row: pd.Series, key: str, errors: list[str]) -> datetime | None:
    try:
        return _coerce_date(_get(row, key))
    except (ValueError, TypeError):
        errors.append(f"could not parse date for '{key}': {_get(row, key)!r}")
        return None


def _required_float(row: pd.Series, key: str, errors: list[str]) -> float | None:
    """Parse a required numeric field, adding a 'missing' error only when blank."""
    before = len(errors)
    value = _try_float(row, key, errors)
    if value is None and len(errors) == before:
        errors.append(f"missing required field '{key}'")
    return value


def _required_date(row: pd.Series, key: str, errors: list[str]) -> datetime | None:
    """Parse a required date field, adding a 'missing' error only when blank."""
    before = len(errors)
    value = _try_date(row, key, errors)
    if value is None and len(errors) == before:
        errors.append(f"missing required field '{key}'")
    return value


def _parse_row(
    row: pd.Series, row_number: int
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    """Parse and validate a single row.

    Returns ``(trade_dict_or_None, errors, warnings)``. When ``errors`` is
    non-empty the row is rejected and ``trade_dict`` is None.
    """
    errors: list[str] = []
    warnings: list[str] = []

    symbol = _clean_str(_get(row, "symbol"))
    if symbol is None:
        errors.append("missing required field 'symbol'")

    side = _normalize_side(_get(row, "side"))
    if side is None:
        errors.append(f"missing or unrecognized 'side': {_get(row, 'side')!r}")

    entry_price = _required_float(row, "entry_price", errors)
    opened_at = _required_date(row, "opened_at", errors)

    closed_at = _try_date(row, "closed_at", errors)
    exit_price = _try_float(row, "exit_price", errors)
    quantity = _try_float(row, "quantity", errors)
    stop_loss = _try_float(row, "stop_loss", errors)
    take_profit = _try_float(row, "take_profit", errors)
    initial_risk_amount = _try_float(row, "initial_risk_amount", errors)
    gross_pnl = _try_float(row, "gross_pnl", errors)
    fees = _try_float(row, "fees", errors)
    net_pnl = _try_float(row, "net_pnl", errors)

    status = _normalize_status(_get(row, "status"))
    status_raw = _clean_str(_get(row, "status"))
    if status is None:
        if status_raw is not None:
            errors.append(f"unrecognized 'status': {status_raw!r}")
        else:
            # Infer from presence of a close time / exit price.
            status = (
                TradeStatus.CLOSED.value if (closed_at or exit_price) else TradeStatus.OPEN.value
            )

    if errors:
        return None, errors, warnings

    # Derive net_pnl from gross - fees when only gross is available.
    if net_pnl is None and gross_pnl is not None:
        net_pnl = gross_pnl - (fees or 0.0)

    planned_rr = compute_planned_rr(side, entry_price, stop_loss, take_profit)

    if status == TradeStatus.CLOSED.value:
        realized_r, r_method = compute_realized_r(
            side, entry_price, exit_price, stop_loss, net_pnl, initial_risk_amount
        )
    else:
        realized_r, r_method = None, None

    # Soft data-quality warnings (row is still imported).
    label = f"row {row_number} ({symbol} {side})"
    if status == TradeStatus.CLOSED.value:
        if closed_at is None:
            warnings.append(f"{label}: closed trade missing close time")
        if exit_price is None:
            warnings.append(f"{label}: closed trade missing exit price")
        if net_pnl is None and gross_pnl is None:
            warnings.append(f"{label}: closed trade missing P&L")
    if stop_loss is None:
        warnings.append(f"{label}: missing stop loss (planned RR / price R unavailable)")
    if stop_loss is not None and take_profit is not None and planned_rr is None:
        warnings.append(f"{label}: invalid planned RR (risk/reward not both positive)")

    trade = {
        "external_id": _clean_str(_get(row, "external_id")),
        "symbol": symbol,
        "side": side,
        "status": status,
        "opened_at": opened_at,
        "closed_at": closed_at,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "initial_risk_amount": initial_risk_amount,
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "planned_rr": planned_rr,
        "realized_r": realized_r,
        "r_method": r_method,
        "notes": _clean_str(_get(row, "notes")),
    }
    return trade, errors, warnings


def parse_trades_frame(df: pd.DataFrame) -> ParsedImport:
    """Parse and validate a DataFrame of raw trade rows."""
    normalized = normalize_columns(df)
    result = ParsedImport()
    for i, (_, row) in enumerate(normalized.iterrows(), start=1):
        trade, errors, warnings = _parse_row(row, i)
        result.warnings.extend(warnings)
        if errors:
            result.row_errors.append(RowError(row_number=i, errors=errors, raw=row.to_dict()))
            continue
        assert trade is not None
        result.trades.append(trade)
    return result


def parse_trades_csv(path: str | Path) -> ParsedImport:
    """Read a CSV file and parse/validate its rows."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return parse_trades_frame(df)


# ---------------------------------------------------------------------------
# Database import
# ---------------------------------------------------------------------------
def import_parsed(
    session: Session, account_id: int, parsed: ParsedImport, source: str = "csv"
) -> ImportResult:
    """Insert parsed trades into the database, skipping duplicate ``external_id``s.

    Duplicates are detected both against existing rows in the database and within
    the current batch.
    """
    result = ImportResult(
        account_id=account_id,
        failed=len(parsed.row_errors),
        row_errors=list(parsed.row_errors),
        warnings=list(parsed.warnings),
    )
    seen_external: set[str] = set()

    for data in parsed.trades:
        external_id = data.get("external_id")
        if external_id:
            if external_id in seen_external:
                result.skipped_duplicates += 1
                continue
            seen_external.add(external_id)
            exists = session.execute(
                select(Trade.id).where(
                    Trade.account_id == account_id,
                    Trade.external_id == external_id,
                )
            ).first()
            if exists is not None:
                result.skipped_duplicates += 1
                continue

        trade = Trade(account_id=account_id, source=source, **data)
        session.add(trade)
        session.flush()  # populate trade.id
        result.created_trade_ids.append(trade.id)
        result.imported += 1

    return result


def import_csv(
    session: Session,
    path: str | Path,
    account_id: int | None = None,
    source: str = "csv",
) -> ImportResult:
    """Import a CSV file into the database.

    When ``account_id`` is not given, the local demo account is used (created if
    necessary), honoring the Phase 1 "single local account" default.
    """
    if account_id is None:
        # Imported lazily to avoid a circular import at module load.
        from ..services.account_service import get_or_create_default_account

        account = get_or_create_default_account(session)
        account_id = account.id

    parsed = parse_trades_csv(path)
    return import_parsed(session, account_id, parsed, source=source)
