"""Shared test doubles for the TradeLocker connector.

A ``FakeTransport`` implements the client's transport seam, so every connector
test runs fully offline. Canned payloads mirror TradeLocker's real, config-driven
"array rows + column config" shape so the tests exercise the parser end-to-end.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_journal.config import TradeLockerSettings
from trading_journal.connectors.tradelocker.client import HttpRequest, HttpResponse

# A far-future expiry so cached tokens never look expired mid-test.
FUTURE_EXPIRY = "2999-01-01T00:00:00.000Z"

# Instrument-name resolution: tradableInstrumentId -> symbol.
INSTRUMENTS = [
    {"tradableInstrumentId": "278", "name": "EURUSD"},
    {"tradableInstrumentId": "279", "name": "GBPUSD"},
]


def make_settings(**overrides: Any) -> TradeLockerSettings:
    """Build a fully-populated settings object without touching the environment."""
    base = {
        "enabled": True,
        "environment": "demo",
        "base_url": "https://demo.tradelocker.test",
        "email": "trader@example.com",
        "server": "DEMO-SERVER",
        "account_id": "12345",
        "acc_num": "1",
        "lookback_days": 90,
        "request_timeout_seconds": 30,
        "dry_run": True,
        "password": "s3cr3t-pw",
    }
    base.update(overrides)
    return TradeLockerSettings(**base)


def auth_response(access: str = "ACCESS-TOKEN", refresh: str = "REFRESH-TOKEN") -> dict[str, Any]:
    return {"accessToken": access, "refreshToken": refresh, "expireDate": FUTURE_EXPIRY}


def accounts_response() -> dict[str, Any]:
    return {
        "accounts": [
            {
                "id": "12345",
                "accNum": "1",
                "currency": "USD",
                "accountBalance": "10000.00",
                "name": "Demo",
            }
        ]
    }


def config_response() -> dict[str, Any]:
    return {
        "d": {
            "positionsConfig": {
                "columns": [
                    {"id": "id"},
                    {"id": "tradableInstrumentId"},
                    {"id": "side"},
                    {"id": "qty"},
                    {"id": "avgPrice"},
                    {"id": "stopLossPrice"},
                    {"id": "takeProfitPrice"},
                    {"id": "openDate"},
                    {"id": "unrealizedPl"},
                ]
            },
            "ordersHistoryConfig": {
                "columns": [
                    {"id": "id"},
                    {"id": "positionId"},
                    {"id": "tradableInstrumentId"},
                    {"id": "side"},
                    {"id": "qty"},
                    {"id": "avgPrice"},
                    {"id": "closePrice"},
                    {"id": "stopLossPrice"},
                    {"id": "takeProfitPrice"},
                    {"id": "openDate"},
                    {"id": "closeDate"},
                    {"id": "status"},
                    {"id": "profit"},
                    {"id": "fee"},
                    {"id": "swap"},
                ]
            },
            "accountDetailsConfig": {
                "columns": [{"id": "balance"}, {"id": "equity"}, {"id": "marginAvailable"}]
            },
            "instruments": INSTRUMENTS,
        }
    }


# Epoch-ms timestamps used across positions/history.
OPEN_MS = 1_719_800_000_000
CLOSE_MS = 1_719_900_000_000


def positions_response() -> dict[str, Any]:
    """One open EURUSD long, position id 1001."""
    return {
        "d": {
            "positions": [
                ["1001", "278", "buy", "0.10", "1.10000", "1.09500", "1.11500", OPEN_MS, "12.50"],
            ]
        }
    }


def empty_positions_response() -> dict[str, Any]:
    return {"d": {"positions": []}}


def orders_history_response() -> dict[str, Any]:
    """One filled closing order for position 1001 (converts the open -> closed)."""
    return {
        "d": {
            "ordersHistory": [
                [
                    "9001",
                    "1001",
                    "278",
                    "buy",
                    "0.10",
                    "1.10000",
                    "1.11000",
                    "1.09500",
                    "1.11500",
                    OPEN_MS,
                    CLOSE_MS,
                    "Filled",
                    "200.00",
                    "-3.00",
                    "-1.00",
                ]
            ]
        }
    }


def account_state_response(balance: str = "10250.00", equity: str = "10275.50") -> dict[str, Any]:
    return {"d": {"accountDetailsData": [balance, equity, "8000.00"]}}


class FakeTransport:
    """A transport that answers canned responses and records every request.

    ``routes`` maps a path fragment (matched with ``in``) to either an
    ``HttpResponse``, a ``(status_code, body)`` tuple, or a callable taking the
    :class:`HttpRequest`. The first matching fragment wins; unmatched paths get 404.
    """

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.routes = routes or default_routes()
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        for fragment, handler in self.routes.items():
            if fragment in request.url:
                return _as_response(handler, request)
        return HttpResponse(status_code=404, body={"error": "not found"}, text="not found")

    # -- assertions helpers ------------------------------------------------
    def last_request_for(self, fragment: str) -> HttpRequest | None:
        for request in reversed(self.requests):
            if fragment in request.url:
                return request
        return None

    def paths(self) -> list[str]:
        return [r.url for r in self.requests]


def _as_response(handler: Any, request: HttpRequest) -> HttpResponse:
    if callable(handler) and not isinstance(handler, HttpResponse):
        result = handler(request)
        return _as_response(result, request)
    if isinstance(handler, HttpResponse):
        return handler
    if isinstance(handler, tuple):
        status, body = handler
        return HttpResponse(status_code=status, body=body, text=str(body))
    # Bare body -> 200 OK.
    return HttpResponse(status_code=200, body=handler, text=str(handler))


def default_routes(
    positions: dict[str, Any] | None = None,
    history: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A full happy-path route table for account 12345."""
    return {
        "/auth/jwt/token": auth_response(),
        "/auth/jwt/all-accounts": accounts_response(),
        "/trade/config": config_response(),
        "/positions": positions if positions is not None else positions_response(),
        "/ordersHistory": history if history is not None else orders_history_response(),
        "/state": state if state is not None else account_state_response(),
        "/instruments": {"d": {"instruments": INSTRUMENTS}},
    }


def make_client(routes: dict[str, Any] | None = None, **settings_overrides: Any):
    """Build a client wired to a :class:`FakeTransport` (returns (client, transport))."""
    from trading_journal.connectors.tradelocker.client import TradeLockerReadOnlyClient

    transport = FakeTransport(routes)
    settings = make_settings(**settings_overrides)
    client = TradeLockerReadOnlyClient(settings, transport=transport)
    return client, transport


Handler = Callable[[HttpRequest], Any]
