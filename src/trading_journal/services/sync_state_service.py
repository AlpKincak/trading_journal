"""Persistence + reporting for sync runs and incremental cursors.

Kept separate from :mod:`.sync_service` (and importing none of it) so there is no
circular dependency: the orchestrator calls *into* these helpers with primitive
values, and the UI/CLI read run history back out.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SyncRun, SyncState

SYNC_RUN_COLUMNS = [
    "id",
    "source",
    "started_at",
    "finished_at",
    "status",
    "environment",
    "account_id",
    "acc_num",
    "imported_count",
    "updated_count",
    "skipped_count",
    "warning_count",
    "error_count",
]


def record_sync_run(
    session: Session,
    *,
    source: str,
    status: str,
    started_at: datetime,
    finished_at: datetime | None,
    environment: str | None,
    account_id: str | None,
    acc_num: str | None,
    imported_count: int,
    updated_count: int,
    skipped_count: int,
    warning_count: int,
    error_count: int,
    summary_json: str | None = None,
) -> SyncRun:
    """Persist one :class:`SyncRun` audit row."""
    run = SyncRun(
        source=source,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        environment=environment,
        account_id=account_id,
        acc_num=acc_num,
        imported_count=imported_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        warning_count=warning_count,
        error_count=error_count,
        summary_json=summary_json,
    )
    session.add(run)
    session.flush()
    return run


def recent_sync_runs(session: Session, source: str | None = None, limit: int = 20) -> list[SyncRun]:
    stmt = select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(limit)
    if source:
        stmt = stmt.where(SyncRun.source == source)
    return list(session.execute(stmt).scalars().all())


def sync_runs_dataframe(
    session: Session, source: str | None = None, limit: int = 20
) -> pd.DataFrame:
    runs = recent_sync_runs(session, source=source, limit=limit)
    rows = [{col: getattr(run, col) for col in SYNC_RUN_COLUMNS} for run in runs]
    df = pd.DataFrame(rows, columns=SYNC_RUN_COLUMNS)
    for col in ("started_at", "finished_at"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def get_sync_state(
    session: Session,
    *,
    source: str,
    key: str,
    environment: str | None = None,
    account_id: str | None = None,
    acc_num: str | None = None,
) -> str | None:
    state = _find_state(
        session,
        source=source,
        key=key,
        environment=environment,
        account_id=account_id,
        acc_num=acc_num,
    )
    return state.value if state else None


def set_sync_state(
    session: Session,
    *,
    source: str,
    key: str,
    value: str,
    environment: str | None = None,
    account_id: str | None = None,
    acc_num: str | None = None,
) -> SyncState:
    state = _find_state(
        session,
        source=source,
        key=key,
        environment=environment,
        account_id=account_id,
        acc_num=acc_num,
    )
    if state is None:
        state = SyncState(
            source=source,
            environment=environment,
            account_id=account_id,
            acc_num=acc_num,
            key=key,
            value=value,
        )
        session.add(state)
    else:
        state.value = value
    session.flush()
    return state


def _find_state(
    session: Session,
    *,
    source: str,
    key: str,
    environment: str | None,
    account_id: str | None,
    acc_num: str | None,
) -> SyncState | None:
    stmt = select(SyncState).where(
        SyncState.source == source,
        SyncState.key == key,
        SyncState.environment == environment,
        SyncState.account_id == account_id,
        SyncState.acc_num == acc_num,
    )
    return session.execute(stmt).scalars().first()
