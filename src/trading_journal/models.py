"""SQLAlchemy ORM models for the trading journal.

Design notes
------------
* Enum-like fields (``side``, ``status``, ``r_method``) are stored as plain
  strings. We normalize/validate them in the importer and service layers so that
  messy imported data never crashes the ORM. The ``str`` enums below act as the
  canonical vocabulary.
* Timestamps use timezone-naive ``datetime`` values stored in the account's local
  time. Phase 1 is single-user and local, so we do not carry timezone info.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""


class Side(enum.StrEnum):
    """Trade direction."""

    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(enum.StrEnum):
    """Trade lifecycle status."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RMethod(enum.StrEnum):
    """How realized R was derived."""

    MONEY = "money"
    PRICE = "price"
    UNKNOWN = "unknown"


_SIDE_ALIASES: dict[str, str] = {
    "buy": Side.BUY.value,
    "b": Side.BUY.value,
    "long": Side.BUY.value,
    "bull": Side.BUY.value,
    "sell": Side.SELL.value,
    "s": Side.SELL.value,
    "short": Side.SELL.value,
    "bear": Side.SELL.value,
}

_STATUS_ALIASES: dict[str, str] = {
    "open": TradeStatus.OPEN.value,
    "o": TradeStatus.OPEN.value,
    "opened": TradeStatus.OPEN.value,
    "active": TradeStatus.OPEN.value,
    "closed": TradeStatus.CLOSED.value,
    "c": TradeStatus.CLOSED.value,
    "close": TradeStatus.CLOSED.value,
    "filled": TradeStatus.CLOSED.value,
    "done": TradeStatus.CLOSED.value,
}


def normalize_side(value: object) -> str | None:
    """Map a free-form side value to ``BUY``/``SELL`` (or None if unrecognized)."""
    if value is None:
        return None
    key = str(value).strip().lower()
    return _SIDE_ALIASES.get(key)


def normalize_status(value: object) -> str | None:
    """Map a free-form status value to ``OPEN``/``CLOSED`` (or None if unrecognized)."""
    if value is None:
        return None
    key = str(value).strip().lower()
    return _STATUS_ALIASES.get(key)


def _utcnow() -> datetime:
    """Naive UTC timestamp for created/updated bookkeeping columns."""
    return datetime.now(UTC).replace(tzinfo=None)


class Account(Base):
    """A trading account (broker + base currency)."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    broker: Mapped[str | None] = mapped_column(String(120), nullable=True)
    base_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    snapshots: Mapped[list[AccountSnapshot]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    trades: Mapped[list[Trade]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Account id={self.id} name={self.name!r} currency={self.base_currency}>"


class AccountSnapshot(Base):
    """A point-in-time balance/equity reading for an account."""

    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    balance: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    account: Mapped[Account] = relationship(back_populates="snapshots")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AccountSnapshot id={self.id} account_id={self.account_id} "
            f"ts={self.timestamp:%Y-%m-%d} balance={self.balance} equity={self.equity}>"
        )


class Trade(Base):
    """A single trade (open or closed)."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(6), nullable=False, default=TradeStatus.OPEN.value)

    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)

    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_risk_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    gross_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

    planned_rr: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_method: Mapped[str | None] = mapped_column(String(10), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    account: Mapped[Account] = relationship(back_populates="trades")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Trade id={self.id} {self.symbol} {self.side} {self.status} "
            f"net_pnl={self.net_pnl} r={self.realized_r}>"
        )

    @property
    def is_closed(self) -> bool:
        return self.status == TradeStatus.CLOSED.value

    @property
    def is_open(self) -> bool:
        return self.status == TradeStatus.OPEN.value
