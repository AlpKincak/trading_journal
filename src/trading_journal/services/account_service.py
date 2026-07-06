"""Account and account-snapshot operations."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..metrics import snapshots_to_dataframe
from ..models import Account, AccountSnapshot


class ManualSnapshotInput(BaseModel):
    """Validated input for a manually-entered account snapshot (UI form)."""

    timestamp: datetime
    balance: float
    equity: float | None = None
    source: str = "manual"

    @field_validator("balance")
    @classmethod
    def _balance_finite(cls, value: float) -> float:
        if value != value:  # NaN check
            raise ValueError("balance must be a number")
        return value


def get_or_create_default_account(session: Session) -> Account:
    """Return the first account, creating a local demo account if none exist."""
    account = session.execute(select(Account).order_by(Account.id)).scalars().first()
    if account is not None:
        return account

    settings = get_settings()
    account = Account(
        name=settings.demo_account_name,
        broker="TradeLocker (demo)",
        base_currency="USD",
    )
    session.add(account)
    session.flush()
    return account


def list_accounts(session: Session) -> list[Account]:
    return list(session.execute(select(Account).order_by(Account.id)).scalars().all())


def add_snapshot(
    session: Session,
    account_id: int,
    balance: float,
    equity: float | None = None,
    timestamp: datetime | None = None,
    source: str = "manual",
) -> AccountSnapshot:
    """Create and persist an account snapshot."""
    snapshot = AccountSnapshot(
        account_id=account_id,
        timestamp=timestamp or datetime.now(),
        balance=balance,
        equity=equity,
        source=source,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def list_snapshots(session: Session, account_id: int | None = None) -> list[AccountSnapshot]:
    stmt = select(AccountSnapshot).order_by(AccountSnapshot.timestamp)
    if account_id is not None:
        stmt = stmt.where(AccountSnapshot.account_id == account_id)
    return list(session.execute(stmt).scalars().all())


def latest_snapshot(session: Session, account_id: int | None = None) -> AccountSnapshot | None:
    stmt = select(AccountSnapshot).order_by(AccountSnapshot.timestamp.desc()).limit(1)
    if account_id is not None:
        stmt = stmt.where(AccountSnapshot.account_id == account_id)
    return session.execute(stmt).scalars().first()


def snapshots_dataframe(session: Session, account_id: int | None = None) -> pd.DataFrame:
    """Return account snapshots as a DataFrame (sorted by timestamp)."""
    return snapshots_to_dataframe(list_snapshots(session, account_id))
