"""Daily-review operations: generic, non-strategy-specific reflection notes.

A :class:`DailyReview` is keyed by ``(account_id, review_date)`` so there is at
most one review per account per day. All writes go through this module so the
uniqueness/upsert logic lives in one place.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DailyReview

DAILY_REVIEW_COLUMNS = [
    "id",
    "account_id",
    "review_date",
    "notes",
    "mood",
    "discipline_score",
    "risk_score",
    "execution_score",
    "lesson",
    "created_at",
    "updated_at",
]

_SCORE_FIELDS = ("discipline_score", "risk_score", "execution_score")


class DailyReviewInput(BaseModel):
    """Validated input for creating/updating a daily review."""

    review_date: date
    notes: str | None = None
    mood: str | None = None
    discipline_score: int | None = None
    risk_score: int | None = None
    execution_score: int | None = None
    lesson: str | None = None

    @field_validator("discipline_score", "risk_score", "execution_score")
    @classmethod
    def _score_in_range(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if not 0 <= value <= 100:
            raise ValueError("scores must be between 0 and 100")
        return value


def get_daily_review(
    session: Session, account_id: int | None, review_date: date
) -> DailyReview | None:
    """Fetch the review for an account/date (or None)."""
    stmt = select(DailyReview).where(
        DailyReview.account_id == account_id,
        DailyReview.review_date == review_date,
    )
    return session.execute(stmt).scalars().first()


def upsert_daily_review(
    session: Session, account_id: int | None, data: DailyReviewInput
) -> DailyReview:
    """Create or update the review for ``(account_id, data.review_date)``."""
    review = get_daily_review(session, account_id, data.review_date)
    payload = data.model_dump(exclude={"review_date"})
    if review is None:
        review = DailyReview(account_id=account_id, review_date=data.review_date, **payload)
        session.add(review)
    else:
        for name, value in payload.items():
            setattr(review, name, value)
    session.flush()
    return review


def list_daily_reviews(
    session: Session, account_id: int | None = None, limit: int | None = None
) -> list[DailyReview]:
    """List reviews (most recent first), optionally scoped to an account."""
    stmt = select(DailyReview).order_by(DailyReview.review_date.desc(), DailyReview.id.desc())
    if account_id is not None:
        stmt = stmt.where(DailyReview.account_id == account_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().all())


def daily_reviews_dataframe(
    session: Session, account_id: int | None = None, limit: int | None = None
) -> pd.DataFrame:
    """Return daily reviews as a DataFrame for display/export."""
    reviews = list_daily_reviews(session, account_id=account_id, limit=limit)
    rows = [{col: getattr(r, col) for col in DAILY_REVIEW_COLUMNS} for r in reviews]
    df = pd.DataFrame(rows, columns=DAILY_REVIEW_COLUMNS)
    for col in ("review_date", "created_at", "updated_at"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def delete_daily_review(session: Session, review: DailyReview) -> None:
    session.delete(review)
    session.flush()


def _coerce_date(value: date | datetime | str) -> date:
    """Best-effort coercion of a date-ish value to a ``date``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()
