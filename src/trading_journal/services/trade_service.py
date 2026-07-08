"""Trade operations: querying, filtering, manual entry, editing, and review.

This module owns all local writes to :class:`Trade` rows (manual entry, manual
correction, and the review workflow) plus the small JSON helpers that record
which fields a user has manually overridden. The sync service imports
:func:`manual_locked_fields` from here so there is a single source of truth for
"which fields must a TradeLocker resync leave alone".
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..metrics import compute_planned_rr, compute_realized_r, trades_to_dataframe
from ..models import (
    ReviewStatus,
    RMethod,
    Trade,
    TradeStatus,
    normalize_mistake_category,
    normalize_review_status,
    normalize_side,
    normalize_status,
)


def _utcnow() -> datetime:
    """Naive UTC timestamp (matches the models' bookkeeping columns)."""
    return datetime.now(UTC).replace(tzinfo=None)


# Fields a manual correction may "lock" so a later TradeLocker resync leaves them
# alone. Review/journal fields (notes, review_notes, review_status,
# mistake_category, exit_reason) are always user-owned and never touched by sync,
# so they are not part of this lock set.
LOCKABLE_FIELDS: tuple[str, ...] = (
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
)


class ManualTradeInput(BaseModel):
    """Validated input for a manually-entered trade (UI form)."""

    symbol: str
    side: str
    status: str = TradeStatus.OPEN.value
    opened_at: datetime
    closed_at: datetime | None = None
    entry_price: float
    exit_price: float | None = None
    quantity: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    initial_risk_amount: float | None = None
    gross_pnl: float | None = None
    fees: float | None = None
    net_pnl: float | None = None
    notes: str | None = None

    @field_validator("symbol")
    @classmethod
    def _symbol_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("symbol is required")
        return value.upper()

    @field_validator("side")
    @classmethod
    def _side_valid(cls, value: str) -> str:
        normalized = normalize_side(value)
        if normalized is None:
            raise ValueError(f"unrecognized side: {value!r}")
        return normalized

    @field_validator("status")
    @classmethod
    def _status_valid(cls, value: str) -> str:
        normalized = normalize_status(value)
        if normalized is None:
            raise ValueError(f"unrecognized status: {value!r}")
        return normalized


def recalculate_derived(trade: Trade, locked: set[str] | None = None) -> None:
    """Fill in ``net_pnl`` (from gross - fees), ``planned_rr``, ``realized_r``.

    Existing money-based inputs are respected; only missing values are derived.
    ``locked`` names any manually-overridden derived fields to leave untouched
    (used by the TradeLocker resync path so user corrections survive).
    """
    locked = locked or set()

    if trade.net_pnl is None and trade.gross_pnl is not None and "net_pnl" not in locked:
        trade.net_pnl = trade.gross_pnl - (trade.fees or 0.0)

    if "planned_rr" not in locked:
        trade.planned_rr = compute_planned_rr(
            trade.side, trade.entry_price, trade.stop_loss, trade.take_profit
        )

    if "realized_r" in locked:
        # A manually overridden R is kept as-is and flagged as manual.
        trade.r_method = RMethod.MANUAL.value
    elif trade.status == TradeStatus.CLOSED.value:
        realized_r, r_method = compute_realized_r(
            trade.side,
            trade.entry_price,
            trade.exit_price,
            trade.stop_loss,
            trade.net_pnl,
            trade.initial_risk_amount,
        )
        trade.realized_r = realized_r
        trade.r_method = r_method
    else:
        trade.realized_r = None
        trade.r_method = None


def add_trade(
    session: Session, account_id: int, data: ManualTradeInput, source: str = "manual"
) -> Trade:
    """Create, derive fields for, and persist a manually-entered trade."""
    trade = Trade(account_id=account_id, source=source, **data.model_dump())
    trade.is_manual = source == "manual"
    recalculate_derived(trade)
    session.add(trade)
    session.flush()
    return trade


# ---------------------------------------------------------------------------
# JSON helpers for the manual-override audit trail and data-quality flags.
# Trade fields are not secrets, so nothing is redacted.
# ---------------------------------------------------------------------------
def _load_json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _values_equal(a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def manual_locked_fields(trade: Trade) -> set[str]:
    """Return the set of trade *data* fields the user has manually overridden.

    A TradeLocker resync must not overwrite these. Review/journal fields are not
    included because sync never writes them in the first place.
    """
    if not trade.has_manual_overrides or not trade.manual_override_json:
        return set()
    fields = _load_json_dict(trade.manual_override_json).get("fields", {})
    return {name for name in fields if name in LOCKABLE_FIELDS}


def load_data_quality_flags(trade: Trade) -> dict:
    """Parse the trade's ``data_quality_flags_json`` into a dict (never raises)."""
    return _load_json_dict(trade.data_quality_flags_json)


def add_data_quality_flag(
    trade: Trade, key: str, detail: object, *, timestamp: datetime | None = None
) -> None:
    """Record/refresh a data-quality flag on the trade (e.g. a sync conflict)."""
    flags = _load_json_dict(trade.data_quality_flags_json)
    flags[key] = {"detail": detail, "at": (timestamp or _utcnow()).isoformat()}
    trade.data_quality_flags_json = json.dumps(flags)


def clear_data_quality_flag(trade: Trade, key: str) -> None:
    """Remove a data-quality flag if present."""
    flags = _load_json_dict(trade.data_quality_flags_json)
    if key in flags:
        flags.pop(key)
        trade.data_quality_flags_json = json.dumps(flags) if flags else None


# ---------------------------------------------------------------------------
# Manual correction / review workflow
# ---------------------------------------------------------------------------
class TradeEditInput(BaseModel):
    """Validated, *partial* edit for an existing trade.

    Only fields the caller explicitly sets are applied (tracked via pydantic's
    ``model_fields_set``), so passing ``None`` deliberately clears a field while
    omitting it leaves the current value untouched. ``planned_rr`` /
    ``realized_r`` are recomputed from the other fields unless the matching
    ``override_*`` flag is set.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str | None = None
    side: str | None = None
    status: str | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    quantity: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    initial_risk_amount: float | None = None
    gross_pnl: float | None = None
    fees: float | None = None
    net_pnl: float | None = None
    planned_rr: float | None = None
    realized_r: float | None = None
    notes: str | None = None
    review_notes: str | None = None
    mistake_category: str | None = None
    exit_reason: str | None = None
    review_status: str | None = None

    # Control flags (never written to the Trade row).
    override_planned_rr: bool = False
    override_realized_r: bool = False

    @field_validator("symbol")
    @classmethod
    def _symbol_nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("symbol cannot be blank")
        return value.upper()

    @field_validator("side")
    @classmethod
    def _side_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_side(value)
        if normalized is None:
            raise ValueError(f"unrecognized side: {value!r}")
        return normalized

    @field_validator("status")
    @classmethod
    def _status_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_status(value)
        if normalized is None:
            raise ValueError(f"unrecognized status: {value!r}")
        return normalized

    @field_validator("review_status")
    @classmethod
    def _review_status_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_review_status(value)
        if normalized is None:
            raise ValueError(f"unrecognized review_status: {value!r}")
        return normalized

    @field_validator("mistake_category")
    @classmethod
    def _mistake_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if str(value).strip() == "":
            return None  # explicit clear
        normalized = normalize_mistake_category(value)
        if normalized is None:
            raise ValueError(f"unrecognized mistake_category: {value!r}")
        return normalized


_CONTROL_FIELDS = {"override_planned_rr", "override_realized_r"}


def _recalc_after_edit(
    trade: Trade, changed: set[str], override_planned: bool, override_realized: bool
) -> None:
    """Recompute net_pnl / planned_rr / realized_r after an edit, honoring locks.

    A previously-locked (manually overridden) ``planned_rr`` / ``realized_r`` /
    ``net_pnl`` is never silently recomputed.
    """
    locked = manual_locked_fields(trade)

    if (
        "net_pnl" not in changed
        and "net_pnl" not in locked
        and ("gross_pnl" in changed or "fees" in changed)
        and trade.gross_pnl is not None
    ):
        trade.net_pnl = trade.gross_pnl - (trade.fees or 0.0)

    keep_planned = (override_planned and "planned_rr" in changed) or "planned_rr" in locked
    if not keep_planned:
        trade.planned_rr = compute_planned_rr(
            trade.side, trade.entry_price, trade.stop_loss, trade.take_profit
        )

    keep_realized = (override_realized and "realized_r" in changed) or "realized_r" in locked
    if keep_realized:
        trade.r_method = RMethod.MANUAL.value
    elif trade.status == TradeStatus.CLOSED.value:
        realized_r, r_method = compute_realized_r(
            trade.side,
            trade.entry_price,
            trade.exit_price,
            trade.stop_loss,
            trade.net_pnl,
            trade.initial_risk_amount,
        )
        trade.realized_r = realized_r
        trade.r_method = r_method
    else:
        trade.realized_r = None
        trade.r_method = None


def apply_manual_correction(session: Session, trade: Trade, edit: TradeEditInput) -> Trade:
    """Apply a partial manual correction to ``trade`` and record the overrides.

    * Only explicitly-set fields are applied.
    * Every changed field is recorded in ``manual_override_json`` (old + new).
    * Any changed *data* field marks the trade ``has_manual_overrides`` and locks
      that field against future TradeLocker overwrites.
    * ``planned_rr`` / ``realized_r`` are recomputed unless explicitly overridden.
    """
    changes = {
        name: value
        for name, value in edit.model_dump(exclude_unset=True).items()
        if name not in _CONTROL_FIELDS
    }

    override_log = _load_json_dict(trade.manual_override_json)
    fields_log = override_log.setdefault("fields", {})
    now = _utcnow()

    changed: set[str] = set()
    locked_changed = False
    for name, new_value in changes.items():
        old_value = getattr(trade, name)
        if _values_equal(old_value, new_value):
            continue
        setattr(trade, name, new_value)
        changed.add(name)
        fields_log[name] = {
            "old": _json_safe(old_value),
            "new": _json_safe(new_value),
            "at": now.isoformat(),
        }
        if name in LOCKABLE_FIELDS:
            locked_changed = True

    if locked_changed:
        trade.has_manual_overrides = True
    if fields_log:
        trade.manual_override_json = json.dumps(override_log)

    # Review-status bookkeeping: stamp reviewed_at when moving to REVIEWED.
    if trade.review_status == ReviewStatus.REVIEWED.value and trade.reviewed_at is None:
        trade.reviewed_at = now

    _recalc_after_edit(trade, changed, edit.override_planned_rr, edit.override_realized_r)

    session.flush()
    return trade


def get_trade(session: Session, trade_id: int) -> Trade | None:
    """Fetch a single trade by id (or None)."""
    return session.get(Trade, trade_id)


def set_review_status(session: Session, trade: Trade, status: str) -> Trade:
    """Set a trade's review status (validated) and stamp reviewed_at as needed."""
    return apply_manual_correction(session, trade, TradeEditInput(review_status=status))


def mark_reviewed(session: Session, trade: Trade) -> Trade:
    return set_review_status(session, trade, ReviewStatus.REVIEWED.value)


def mark_needs_fix(session: Session, trade: Trade) -> Trade:
    return set_review_status(session, trade, ReviewStatus.NEEDS_FIX.value)


def _apply_filters(
    stmt,
    account_id: int | None,
    symbol: str | None,
    side: str | None,
    status: str | None,
    start: date | datetime | None,
    end: date | datetime | None,
):
    if account_id is not None:
        stmt = stmt.where(Trade.account_id == account_id)
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol)
    if side:
        stmt = stmt.where(Trade.side == side)
    if status:
        stmt = stmt.where(Trade.status == status)
    if start is not None:
        start_dt = (
            datetime.combine(start, datetime.min.time())
            if isinstance(start, date) and not isinstance(start, datetime)
            else start
        )
        stmt = stmt.where(Trade.opened_at >= start_dt)
    if end is not None:
        end_dt = (
            datetime.combine(end, datetime.max.time())
            if isinstance(end, date) and not isinstance(end, datetime)
            else end
        )
        stmt = stmt.where(Trade.opened_at <= end_dt)
    return stmt


def list_trades(
    session: Session,
    account_id: int | None = None,
    symbol: str | None = None,
    side: str | None = None,
    status: str | None = None,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
) -> list[Trade]:
    """List trades matching the given filters (ordered by open time)."""
    stmt = select(Trade)
    stmt = _apply_filters(stmt, account_id, symbol, side, status, start, end)
    stmt = stmt.order_by(Trade.opened_at.asc(), Trade.id.asc())
    return list(session.execute(stmt).scalars().all())


def trades_dataframe(
    session: Session,
    account_id: int | None = None,
    symbol: str | None = None,
    side: str | None = None,
    status: str | None = None,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
) -> pd.DataFrame:
    """Return filtered trades as a normalized DataFrame for analytics."""
    return trades_to_dataframe(list_trades(session, account_id, symbol, side, status, start, end))


def get_open_positions(session: Session, account_id: int | None = None) -> list[Trade]:
    return list_trades(session, account_id=account_id, status=TradeStatus.OPEN.value)


def get_closed_trades(session: Session, account_id: int | None = None) -> list[Trade]:
    return list_trades(session, account_id=account_id, status=TradeStatus.CLOSED.value)


def recent_trades(session: Session, limit: int = 10, account_id: int | None = None) -> list[Trade]:
    """Most recently active trades (by close time, falling back to open time)."""
    recency = func.coalesce(Trade.closed_at, Trade.opened_at)
    stmt = select(Trade).order_by(recency.desc(), Trade.id.desc()).limit(limit)
    if account_id is not None:
        stmt = stmt.where(Trade.account_id == account_id)
    return list(session.execute(stmt).scalars().all())


def distinct_symbols(session: Session, account_id: int | None = None) -> list[str]:
    """Distinct symbols present, for populating UI filters."""
    stmt = select(Trade.symbol).distinct().order_by(Trade.symbol)
    if account_id is not None:
        stmt = stmt.where(Trade.account_id == account_id)
    return list(session.execute(stmt).scalars().all())
