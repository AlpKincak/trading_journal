"""Seed the database with the bundled deterministic demo data.

Seeding is idempotent: trades are de-duplicated by ``external_id`` and snapshots
by ``(account_id, timestamp)``, so running ``seed-demo`` twice does not create
duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .importers.csv_importer import ImportResult, _coerce_date, _coerce_float, import_csv
from .models import AccountSnapshot
from .services.account_service import get_or_create_default_account


@dataclass
class SeedResult:
    account_id: int
    trades: ImportResult
    snapshots_added: int
    snapshots_skipped: int

    def summary(self) -> str:
        return (
            f"account_id={self.account_id} | trades: {self.trades.summary()} | "
            f"snapshots: added={self.snapshots_added} skipped={self.snapshots_skipped}"
        )


def _load_snapshots(session: Session, account_id: int, path: Path) -> tuple[int, int]:
    """Load account snapshots from CSV, skipping ones that already exist."""
    if not path.exists():
        return 0, 0

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    existing = {
        ts
        for ts in session.execute(
            select(AccountSnapshot.timestamp).where(AccountSnapshot.account_id == account_id)
        ).scalars()
    }

    added = 0
    skipped = 0
    for _, row in df.iterrows():
        timestamp = _coerce_date(row.get("timestamp"))
        balance = _coerce_float(row.get("balance"))
        if timestamp is None or balance is None:
            skipped += 1
            continue
        if timestamp in existing:
            skipped += 1
            continue
        equity = _coerce_float(row.get("equity"))
        source = (row.get("source") or "seed").strip() or "seed"
        session.add(
            AccountSnapshot(
                account_id=account_id,
                timestamp=timestamp,
                balance=balance,
                equity=equity,
                source=source,
            )
        )
        existing.add(timestamp)
        added += 1

    return added, skipped


def seed_demo(session: Session, sample_dir: Path | None = None) -> SeedResult:
    """Seed the demo account with sample trades and account snapshots."""
    settings = get_settings()
    sample_dir = sample_dir or settings.sample_data_dir

    account = get_or_create_default_account(session)
    trades_result = import_csv(
        session, sample_dir / "sample_trades.csv", account_id=account.id, source="seed"
    )
    added, skipped = _load_snapshots(
        session, account.id, sample_dir / "sample_account_snapshots.csv"
    )

    return SeedResult(
        account_id=account.id,
        trades=trades_result,
        snapshots_added=added,
        snapshots_skipped=skipped,
    )
