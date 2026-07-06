"""Tests for the read-only TradeLocker client (offline, via a fake transport)."""

from __future__ import annotations

import pytest

import tradelocker_fakes as fakes
from trading_journal.connectors.tradelocker import (
    TradeLockerAuthError,
    TradeLockerConfigError,
    TradeLockerError,
    TradeLockerReadOnlyClient,
)
from trading_journal.connectors.tradelocker.client import HttpRequest


def test_missing_credentials_raises_config_error():
    settings = fakes.make_settings(email=None, password=None, server=None)
    client = TradeLockerReadOnlyClient(settings, transport=fakes.FakeTransport())
    with pytest.raises(TradeLockerConfigError) as exc:
        client.authenticate()
    message = str(exc.value)
    assert "TRADELOCKER_EMAIL" in message
    assert "TRADELOCKER_PASSWORD" in message


def test_auth_success_caches_token_without_logging_secrets():
    client, transport = fakes.make_client()
    tokens = client.authenticate()

    assert tokens.access_token == "ACCESS-TOKEN"
    # The token/password must never appear in reprs (secret hygiene).
    assert "ACCESS-TOKEN" not in repr(tokens)
    assert "s3cr3t-pw" not in repr(client._settings)

    # The auth request carried the credentials in the JSON body (POST), not a log.
    auth_req = transport.last_request_for("/auth/jwt/token")
    assert auth_req is not None
    assert auth_req.method == "POST"
    assert auth_req.json_body["email"] == "trader@example.com"


def test_auth_failure_http_401_raises_auth_error():
    routes = fakes.default_routes()
    routes["/auth/jwt/token"] = (401, {"error": "invalid credentials"})
    client, _ = fakes.make_client(routes)
    with pytest.raises(TradeLockerAuthError):
        client.authenticate()


def test_auth_missing_token_in_body_raises_auth_error():
    routes = fakes.default_routes()
    routes["/auth/jwt/token"] = (200, {"somethingElse": True})
    client, _ = fakes.make_client(routes)
    with pytest.raises(TradeLockerAuthError):
        client.authenticate()


def test_accnum_header_included_for_trade_endpoints():
    client, transport = fakes.make_client()
    client.authenticate()
    client.get_open_positions("12345", acc_num="7")

    req = transport.last_request_for("/positions")
    assert req is not None
    assert req.method == "GET"
    assert req.headers.get("accNum") == "7"
    assert req.headers.get("Authorization") == "Bearer ACCESS-TOKEN"


def test_list_accounts_parses_discovery():
    client, _ = fakes.make_client()
    client.authenticate()
    accounts = client.list_accounts()
    assert len(accounts) == 1
    assert accounts[0].account_id == "12345"
    assert accounts[0].acc_num == "1"
    assert accounts[0].currency == "USD"
    assert accounts[0].balance == pytest.approx(10000.0)


def test_get_config_extracts_sections_and_instruments():
    client, _ = fakes.make_client()
    client.authenticate()
    config = client.get_config("12345", "1")
    assert "positionsConfig" in config.sections
    assert config.sections["positionsConfig"][0] == "id"
    assert config.instruments["278"] == "EURUSD"


def test_health_check_ok_without_raising():
    client, _ = fakes.make_client()
    result = client.health_check()
    assert result.ok is True
    assert result.authenticated is True
    assert result.accounts_found == 1
    assert result.environment == "demo"


def test_health_check_reports_missing_credentials_safely():
    settings = fakes.make_settings(password=None)
    client = TradeLockerReadOnlyClient(settings, transport=fakes.FakeTransport())
    result = client.health_check()
    assert result.ok is False
    assert "TRADELOCKER_PASSWORD" in result.message
    assert "s3cr3t" not in result.message


def test_rate_limit_maps_to_typed_error():
    from trading_journal.connectors.tradelocker import TradeLockerRateLimitError

    routes = fakes.default_routes()
    routes["/positions"] = (429, {"error": "slow down"})
    client, _ = fakes.make_client(routes)
    client.authenticate()
    with pytest.raises(TradeLockerRateLimitError):
        client.get_open_positions("12345", "1")


def test_readonly_guard_refuses_non_get_non_auth_requests():
    client, _ = fakes.make_client()
    client.authenticate()
    # Attempting any write verb through the single request choke point is refused.
    with pytest.raises(TradeLockerError):
        client._request("DELETE", "/trade/accounts/12345/positions/1", acc_num="1")
    with pytest.raises(TradeLockerError):
        client._request("POST", "/trade/accounts/12345/orders", acc_num="1")


def test_connector_exposes_no_write_methods():
    """Belt-and-braces: the public client must not expose any trading operations."""
    forbidden = {
        "create_order",
        "place_order",
        "close_position",
        "close_all_positions",
        "modify_position",
        "modify_order",
        "cancel_order",
        "delete_order",
    }
    attrs = set(dir(TradeLockerReadOnlyClient))
    assert forbidden.isdisjoint(attrs)


def test_transport_records_requests_are_httprequest():
    client, transport = fakes.make_client()
    client.authenticate()
    assert all(isinstance(r, HttpRequest) for r in transport.requests)
