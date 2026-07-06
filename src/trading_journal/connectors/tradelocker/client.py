"""Read-only TradeLocker REST client.

Safety model
------------
* All HTTP goes through :meth:`TradeLockerReadOnlyClient._request`, which is the
  single choke point for the connector.
* That method **refuses** any HTTP verb other than ``GET`` — the only exception
  being ``POST`` to the two authentication paths (token + refresh), exactly as the
  official API requires. There is no code path that can create, modify, cancel, or
  close an order/position.
* Secrets (password, tokens) are never logged and never placed in exception
  messages.

Testability
-----------
The client talks to a small ``Transport`` callable, not to ``requests`` directly.
The default transport uses ``requests``; tests inject a fake transport and thus run
entirely offline. This is the same seam that keeps the read-only guarantee auditable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ...config import TradeLockerSettings
from . import endpoints
from .config_parser import instruments_from_config, unwrap_envelope
from .errors import (
    TradeLockerAuthError,
    TradeLockerConfigError,
    TradeLockerError,
    TradeLockerHTTPError,
    TradeLockerParseError,
    TradeLockerRateLimitError,
)
from .schemas import AuthTokens, TradeLockerAccount, TradeLockerConfig

# Paths that may be reached with a POST body. Authentication only — never trading.
_ALLOWED_POST_PATHS = frozenset({endpoints.AUTH_TOKEN, endpoints.AUTH_REFRESH})


# ---------------------------------------------------------------------------
# Transport abstraction (keeps the client independent of `requests`)
# ---------------------------------------------------------------------------
@dataclass
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] | None = None
    json_body: dict[str, Any] | None = None
    timeout: float = 30.0


@dataclass
class HttpResponse:
    status_code: int
    body: Any = None  # parsed JSON, when available
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)


Transport = Callable[[HttpRequest], HttpResponse]


class RequestsTransport:
    """Default transport backed by the ``requests`` library."""

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - requests is a declared dep
            raise TradeLockerConfigError(
                "The 'requests' package is required for live TradeLocker calls. "
                "Install it with: pip install requests"
            ) from exc

        try:
            resp = requests.request(
                request.method,
                request.url,
                headers=request.headers,
                params=request.params,
                json=request.json_body,
                timeout=request.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise TradeLockerHTTPError(
                f"Request to {request.url} timed out after {request.timeout}s"
            ) from exc
        except requests.exceptions.RequestException as exc:
            # Do not leak the exception's repr (could echo request internals);
            # surface a safe, actionable message instead.
            raise TradeLockerHTTPError(
                f"Network error contacting {request.url} (check server/environment)."
            ) from exc

        body: Any = None
        try:
            body = resp.json()
        except ValueError:
            body = None
        return HttpResponse(
            status_code=resp.status_code,
            body=body,
            text=resp.text,
            headers=dict(resp.headers),
        )


# ---------------------------------------------------------------------------
# Health-check result
# ---------------------------------------------------------------------------
@dataclass
class HealthCheckResult:
    ok: bool
    environment: str
    base_url: str
    authenticated: bool
    accounts_found: int
    message: str


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------
class TradeLockerReadOnlyClient:
    """A strictly read-only TradeLocker API client."""

    def __init__(
        self,
        settings: TradeLockerSettings,
        transport: Transport | None = None,
    ) -> None:
        self._settings = settings
        self._transport: Transport = transport or RequestsTransport()
        self._tokens: AuthTokens | None = None

    @classmethod
    def from_settings(
        cls, settings: TradeLockerSettings, transport: Transport | None = None
    ) -> TradeLockerReadOnlyClient:
        return cls(settings, transport=transport)

    # -- low-level request -------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        acc_num: str | int | None = None,
        authorized: bool = True,
    ) -> Any:
        """Perform one request and return the parsed JSON body.

        Enforces the read-only contract and raises typed errors on failure.
        """
        method = method.upper()
        if method != "GET" and not (method == "POST" and path in _ALLOWED_POST_PATHS):
            # Defensive: the connector must never issue writes. The only non-GET
            # calls permitted are POSTs to the two authentication endpoints.
            raise TradeLockerError(
                f"Read-only connector refused a {method} request to {path}. "
                "This connector never performs trading/write operations."
            )

        headers: dict[str, str] = {"Accept": "application/json"}
        if authorized:
            if self._tokens is None:
                raise TradeLockerAuthError("Not authenticated. Call authenticate() first.")
            headers["Authorization"] = f"Bearer {self._tokens.access_token}"
        if acc_num is not None:
            headers["accNum"] = str(acc_num)

        request = HttpRequest(
            method=method,
            url=f"{self._settings.api_base_url}{path}",
            headers=headers,
            params=params,
            json_body=json_body,
            timeout=float(self._settings.request_timeout_seconds),
        )
        response = self._transport(request)
        return self._handle_response(response, path)

    def _handle_response(self, response: HttpResponse, path: str) -> Any:
        status = response.status_code
        if 200 <= status < 300:
            return response.body

        if status in (401, 403):
            raise TradeLockerAuthError(
                f"Authentication/authorization failed (HTTP {status}) for {path}. "
                "Check your email/password/server and that the environment "
                "(demo vs live) matches your account."
            )
        if status == 429:
            retry_after = _to_float(response.headers.get("Retry-After"))
            raise TradeLockerRateLimitError(
                f"Rate limited (HTTP 429) for {path}. Slow down and retry later.",
                retry_after=retry_after,
            )
        raise TradeLockerHTTPError(
            f"Unexpected HTTP {status} for {path}.",
            status_code=status,
        )

    # -- authentication ----------------------------------------------------
    def authenticate(self) -> AuthTokens:
        """Authenticate with email/password/server and cache the JWT."""
        settings = self._settings
        missing = settings.missing_credential_fields()
        if missing:
            raise TradeLockerConfigError(
                "Missing TradeLocker credentials: "
                + ", ".join(missing)
                + ". Set them in your environment or .env (never committed)."
            )

        body = self._request(
            "POST",
            endpoints.AUTH_TOKEN,
            json_body={
                "email": settings.email,
                "password": settings.password,
                "server": settings.server,
            },
            authorized=False,
        )
        self._tokens = _parse_auth_tokens(body)
        return self._tokens

    def refresh(self) -> AuthTokens:
        """Refresh the access token using the cached refresh token."""
        if self._tokens is None or not self._tokens.refresh_token:
            # No refresh material — fall back to a full re-auth.
            return self.authenticate()
        body = self._request(
            "POST",
            endpoints.AUTH_REFRESH,
            json_body={"refreshToken": self._tokens.refresh_token},
            authorized=False,
        )
        self._tokens = _parse_auth_tokens(body, previous=self._tokens)
        return self._tokens

    def _ensure_authenticated(self) -> None:
        if self._tokens is None or self._tokens.is_expired:
            if self._tokens is not None and self._tokens.refresh_token:
                self.refresh()
            else:
                self.authenticate()

    # -- read-only discovery / data ---------------------------------------
    def list_accounts(self) -> list[TradeLockerAccount]:
        self._ensure_authenticated()
        body = self._request("GET", endpoints.ALL_ACCOUNTS)
        return _parse_accounts(body)

    def get_config(
        self, account_id: str | int, acc_num: str | int | None = None
    ) -> TradeLockerConfig:
        self._ensure_authenticated()
        body = self._request("GET", endpoints.TRADE_CONFIG, acc_num=acc_num)
        return _parse_config(body)

    def get_account_details(self, account_id: str | int, acc_num: str | int | None = None) -> Any:
        self._ensure_authenticated()
        return self._request("GET", endpoints.account_state(account_id), acc_num=acc_num)

    def get_open_positions(self, account_id: str | int, acc_num: str | int | None = None) -> Any:
        self._ensure_authenticated()
        return self._request("GET", endpoints.positions(account_id), acc_num=acc_num)

    def get_orders_history(
        self,
        account_id: str | int,
        acc_num: str | int | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> Any:
        self._ensure_authenticated()
        params = _date_range_params(from_date, to_date)
        return self._request(
            "GET", endpoints.orders_history(account_id), params=params or None, acc_num=acc_num
        )

    def get_filled_orders(
        self,
        account_id: str | int,
        acc_num: str | int | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> Any:
        """Filled orders.

        TradeLocker exposes filled orders through the orders-history endpoint; the
        mapper is responsible for selecting only rows that represent completed
        (filled) trades. Kept as a distinct method for clarity and forward
        compatibility.
        """
        return self.get_orders_history(account_id, acc_num, from_date, to_date)

    def get_instruments(
        self, account_id: str | int, acc_num: str | int | None = None
    ) -> dict[str, str]:
        """Best-effort map of tradable-instrument id -> symbol name."""
        self._ensure_authenticated()
        try:
            body = self._request("GET", endpoints.instruments(account_id), acc_num=acc_num)
        except TradeLockerHTTPError:
            return {}
        return instruments_from_config(body)

    def health_check(self) -> HealthCheckResult:
        """Verify config + auth without writing anything. Never raises."""
        settings = self._settings
        missing = settings.missing_credential_fields()
        if missing:
            return HealthCheckResult(
                ok=False,
                environment=settings.environment,
                base_url=settings.base_url,
                authenticated=False,
                accounts_found=0,
                message="Missing credentials: " + ", ".join(missing),
            )
        try:
            self.authenticate()
            accounts = self.list_accounts()
        except TradeLockerAuthError as exc:
            return HealthCheckResult(
                False, settings.environment, settings.base_url, False, 0, str(exc)
            )
        except TradeLockerError as exc:
            return HealthCheckResult(
                False, settings.environment, settings.base_url, True, 0, str(exc)
            )
        return HealthCheckResult(
            ok=True,
            environment=settings.environment,
            base_url=settings.base_url,
            authenticated=True,
            accounts_found=len(accounts),
            message=f"Authenticated OK; {len(accounts)} account(s) visible.",
        )


# ---------------------------------------------------------------------------
# Parsing helpers (module-level so they are independently testable)
# ---------------------------------------------------------------------------
def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_auth_tokens(body: Any, previous: AuthTokens | None = None) -> AuthTokens:
    if not isinstance(body, dict):
        raise TradeLockerParseError("Auth response was not a JSON object.")
    payload = unwrap_envelope(body)
    if not isinstance(payload, dict):
        payload = body
    access = (
        payload.get("accessToken")
        or payload.get("access_token")
        or payload.get("token")
        or payload.get("jwt")
    )
    if not access:
        # Do NOT echo the body — it may contain sensitive fields.
        raise TradeLockerAuthError(
            "Authentication failed: no access token in the response "
            "(check credentials, server, and demo/live environment)."
        )
    refresh = (
        payload.get("refreshToken")
        or payload.get("refresh_token")
        or (previous.refresh_token if previous else None)
    )
    return AuthTokens(
        access_token=str(access),
        refresh_token=str(refresh) if refresh else None,
        expires_at=_parse_expiry(payload),
    )


def _parse_expiry(payload: dict[str, Any]) -> datetime | None:
    for key in ("expireDate", "expiresAt", "expiry", "exp"):
        if key in payload and payload[key]:
            dt = _coerce_datetime(payload[key])
            if dt is not None:
                return dt
    for key in ("expiresIn", "expires_in"):
        seconds = _to_float(payload.get(key))
        if seconds is not None:
            return datetime.now() + timedelta(seconds=seconds)
    return None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    number = _to_float(value)
    if number is not None:
        # Heuristic: treat large numbers as epoch ms, otherwise epoch seconds.
        if number > 1e11:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        from dateutil import parser as _dateparser

        parsed = _dateparser.parse(str(value))
    except (ValueError, TypeError, ImportError, OverflowError):
        return None
    # The app stores naive local datetimes; drop any tzinfo consistently.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _parse_accounts(body: Any) -> list[TradeLockerAccount]:
    payload = unwrap_envelope(body)
    rows: list[Any] = []
    if isinstance(payload, dict):
        for key in ("accounts", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
    elif isinstance(payload, list):
        rows = payload

    accounts: list[TradeLockerAccount] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        account_id = row.get("id") or row.get("accountId") or row.get("account_id")
        if account_id is None:
            continue
        acc_num = row.get("accNum") or row.get("accountNumber") or row.get("acc_num")
        accounts.append(
            TradeLockerAccount(
                account_id=str(account_id),
                acc_num=str(acc_num) if acc_num is not None else None,
                name=row.get("name") or row.get("accountName"),
                currency=row.get("currency") or row.get("baseCurrency"),
                balance=_to_float(row.get("accountBalance") or row.get("balance")),
                status=row.get("status"),
                raw=row,
            )
        )
    return accounts


def _parse_config(body: Any) -> TradeLockerConfig:
    payload = unwrap_envelope(body)
    sections: dict[str, list[str]] = {}
    if isinstance(payload, dict):
        from .config_parser import columns_from_section

        for name, section in payload.items():
            if not name.endswith("Config"):
                continue
            columns = columns_from_section(section)
            if columns:
                sections[name] = columns
    return TradeLockerConfig(
        sections=sections,
        instruments=instruments_from_config(body),
        raw=body if isinstance(body, dict) else {},
    )


def _date_range_params(from_date: datetime | None, to_date: datetime | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if from_date is not None:
        params["from"] = int(from_date.timestamp() * 1000)
    if to_date is not None:
        params["to"] = int(to_date.timestamp() * 1000)
    return params
