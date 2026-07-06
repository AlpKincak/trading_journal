"""Centralized TradeLocker REST endpoint paths.

Every path the connector may touch lives here so the read-only surface is
auditable in one place. Paths are relative to ``<base_url>/backend-api``.

Only two of these are ever called with a POST body — the JWT auth token and
refresh endpoints — and both are authentication-only, per the official API.
There are deliberately **no** order/position write endpoints (create/modify/
close/cancel) defined anywhere in this module.
"""

from __future__ import annotations

# --- Authentication (POST is allowed only here) ---------------------------
AUTH_TOKEN = "/auth/jwt/token"
AUTH_REFRESH = "/auth/jwt/refresh"

# --- Read-only discovery / config -----------------------------------------
ALL_ACCOUNTS = "/auth/jwt/all-accounts"
TRADE_CONFIG = "/trade/config"


def account_state(account_id: str | int) -> str:
    """Account details/balance/equity snapshot for one account."""
    return f"/trade/accounts/{account_id}/state"


def positions(account_id: str | int) -> str:
    """Currently open positions for one account."""
    return f"/trade/accounts/{account_id}/positions"


def orders(account_id: str | int) -> str:
    """Working (live) orders for one account."""
    return f"/trade/accounts/{account_id}/orders"


def orders_history(account_id: str | int) -> str:
    """Historical orders (includes filled/closed) for one account."""
    return f"/trade/accounts/{account_id}/ordersHistory"


def instruments(account_id: str | int) -> str:
    """Tradable instruments for one account (used to resolve symbol names)."""
    return f"/trade/accounts/{account_id}/instruments"
