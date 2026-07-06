"""Lightweight, API-facing data structures for the TradeLocker connector.

These describe what the *client* returns after auth/discovery/config parsing.
Database-facing mapping candidates live in :mod:`.mapper`; keeping the two
separate is deliberate — response parsing must not know about the ORM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AuthTokens:
    """JWT auth material. Token strings are excluded from ``repr`` (secrets)."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() >= self.expires_at


@dataclass(frozen=True)
class TradeLockerAccount:
    """A TradeLocker account discovered via ``all-accounts``."""

    account_id: str
    acc_num: str | None
    name: str | None = None
    currency: str | None = None
    balance: float | None = None
    status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class TradeLockerConfig:
    """Parsed ``/trade/config`` response.

    ``sections`` maps a config-section name (e.g. ``positionsConfig``) to its list
    of column ids, when the API exposes column definitions. ``instruments`` maps a
    tradable-instrument id to a human-readable symbol name when available.
    """

    sections: dict[str, list[str]] = field(default_factory=dict)
    instruments: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def columns(self, section: str) -> list[str] | None:
        return self.sections.get(section)
