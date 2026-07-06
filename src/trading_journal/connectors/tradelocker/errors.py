"""Typed errors for the TradeLocker connector.

All messages are constructed from safe, non-secret data. Tokens, passwords, and
raw auth payloads are never interpolated into these exceptions.
"""

from __future__ import annotations


class TradeLockerError(Exception):
    """Base class for all TradeLocker connector errors."""


class TradeLockerConfigError(TradeLockerError):
    """Missing/invalid configuration (e.g. absent credentials)."""


class TradeLockerAuthError(TradeLockerError):
    """Authentication/authorization failure (bad creds, 401, 403, expired JWT)."""


class TradeLockerRateLimitError(TradeLockerError):
    """The API returned HTTP 429 (too many requests)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TradeLockerHTTPError(TradeLockerError):
    """A non-2xx HTTP response that is not specifically auth/rate-limit."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TradeLockerParseError(TradeLockerError):
    """A response could not be parsed into the expected shape."""
