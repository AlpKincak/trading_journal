"""Trade operations: querying, filtering, manual entry, and derived fields."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..metrics import compute_planned_rr, compute_realized_r, trades_to_dataframe
from ..models import Trade, TradeStatus, normalize_side, normalize_status


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


def recalculate_derived(trade: Trade) -> None:
    """Fill in ``net_pnl`` (from gross - fees), ``planned_rr``, ``realized_r``.

    Existing money-based inputs are respected; only missing values are derived.
    """
    if trade.net_pnl is None and trade.gross_pnl is not None:
        trade.net_pnl = trade.gross_pnl - (trade.fees or 0.0)

    trade.planned_rr = compute_planned_rr(
        trade.side, trade.entry_price, trade.stop_loss, trade.take_profit
    )

    if trade.status == TradeStatus.CLOSED.value:
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
    recalculate_derived(trade)
    session.add(trade)
    session.flush()
    return trade


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
