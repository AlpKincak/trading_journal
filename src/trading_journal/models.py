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
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    MANUAL = "manual"
    UNKNOWN = "unknown"


class ReviewStatus(enum.StrEnum):
    """Where a trade sits in the review workflow."""

    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    NEEDS_FIX = "NEEDS_FIX"


class MistakeCategory(enum.StrEnum):
    """Generic, non-strategy-specific journaling categories for review.

    These describe *process/execution* mistakes, not trading setups, so they stay
    within the journal's non-strategy scope.
    """

    EARLY_ENTRY = "EARLY_ENTRY"
    LATE_ENTRY = "LATE_ENTRY"
    EARLY_EXIT = "EARLY_EXIT"
    LATE_EXIT = "LATE_EXIT"
    OVER_RISK = "OVER_RISK"
    MOVED_STOP = "MOVED_STOP"
    NO_STOP = "NO_STOP"
    REVENGE_TRADE = "REVENGE_TRADE"
    IMPULSE_TRADE = "IMPULSE_TRADE"
    MISREAD_MARKET = "MISREAD_MARKET"
    DATA_ISSUE = "DATA_ISSUE"
    OTHER = "OTHER"


class SyncStatus(enum.StrEnum):
    """Outcome of a broker sync run."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    DRY_RUN = "DRY_RUN"


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


def normalize_review_status(value: object) -> str | None:
    """Map a free-form review status to the canonical vocabulary (or None)."""
    if value is None:
        return None
    key = str(value).strip().upper().replace(" ", "_").replace("-", "_")
    try:
        return ReviewStatus(key).value
    except ValueError:
        return None


def normalize_mistake_category(value: object) -> str | None:
    """Map a free-form mistake category to the canonical vocabulary (or None).

    An empty/blank value clears the category (returns ``None`` without error);
    an unrecognized non-blank value also returns ``None`` so callers can decide
    whether to reject it.
    """
    if value is None:
        return None
    key = str(value).strip().upper().replace(" ", "_").replace("-", "_")
    if not key:
        return None
    try:
        return MistakeCategory(key).value
    except ValueError:
        return None


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

    # Phase 2 sync metadata (nullable / defaulted for backward compatibility).
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="local")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    external_account_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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

    # Phase 3 review workflow + manual-correction metadata (all nullable/defaulted
    # for backward compatibility with Phase 1/2 databases).
    review_status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=ReviewStatus.UNREVIEWED.value
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    mistake_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_manual_overrides: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_override_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_quality_flags_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase 2 sync metadata (all nullable for backward compatibility).
    external_position_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    external_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    external_account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_account_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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


class SyncRun(Base):
    """A record of one broker-sync attempt (audit trail for the Sync tab/CLI)."""

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="tradelocker")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=SyncStatus.SUCCESS.value
    )
    environment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acc_num: Mapped[str | None] = mapped_column(String(60), nullable=True)

    imported_count: Mapped[int] = mapped_column(default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(default=0, nullable=False)

    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<SyncRun id={self.id} source={self.source} status={self.status} "
            f"imported={self.imported_count} updated={self.updated_count}>"
        )


class SyncState(Base):
    """A key/value cursor for incremental sync (e.g. last history timestamp).

    Scoped by ``(source, environment, account_id, acc_num, key)``.
    """

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="tradelocker")
    environment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acc_num: Mapped[str | None] = mapped_column(String(60), nullable=True)
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<SyncState {self.source}/{self.environment}/{self.account_id} "
            f"{self.key}={self.value!r}>"
        )


class DailyReview(Base):
    """A generic daily review note with optional self-scores (0-100).

    Not strategy-specific: it captures process/discipline reflections keyed by
    date (optionally scoped to an account). Uniqueness is on
    ``(account_id, review_date)`` so at most one review exists per account per day.
    """

    __tablename__ = "daily_reviews"
    __table_args__ = (
        UniqueConstraint("account_id", "review_date", name="uq_daily_review_account_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    review_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    mood: Mapped[str | None] = mapped_column(String(40), nullable=True)
    discipline_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lesson: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<DailyReview id={self.id} account_id={self.account_id} "
            f"date={self.review_date} discipline={self.discipline_score}>"
        )
