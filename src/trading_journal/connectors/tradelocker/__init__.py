"""Read-only TradeLocker connector.

Public surface is deliberately limited to read-only operations. There is no
exported function that can place, modify, cancel, or close an order/position.
"""

from __future__ import annotations

from .client import HealthCheckResult, TradeLockerReadOnlyClient
from .errors import (
    TradeLockerAuthError,
    TradeLockerConfigError,
    TradeLockerError,
    TradeLockerHTTPError,
    TradeLockerParseError,
    TradeLockerRateLimitError,
)
from .schemas import AuthTokens, TradeLockerAccount, TradeLockerConfig

__all__ = [
    "AuthTokens",
    "HealthCheckResult",
    "TradeLockerAccount",
    "TradeLockerAuthError",
    "TradeLockerConfig",
    "TradeLockerConfigError",
    "TradeLockerError",
    "TradeLockerHTTPError",
    "TradeLockerParseError",
    "TradeLockerRateLimitError",
    "TradeLockerReadOnlyClient",
]
