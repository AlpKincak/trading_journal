"""Tests for the TradeLocker sync orchestration (idempotency, dry-run, upserts)."""

from __future__ import annotations

import pytest

import tradelocker_fakes as fakes
from trading_journal.models import AccountSnapshot, SyncRun, Trade, TradeStatus
from trading_journal.services.sync_service import TradeLockerSyncService


def _service(routes=None, **settings_overrides):
    client, transport = fakes.make_client(routes, **settings_overrides)
    settings = fakes.make_settings(**settings_overrides)
    return TradeLockerSyncService(client, settings), transport


def test_sync_creates_account_trade_and_snapshot(session):
    service, _ = _service()
    result = service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()

    assert result.status == "SUCCESS"
    trade = session.query(Trade).one()
    assert trade.source == "tradelocker"
    assert trade.status == TradeStatus.CLOSED.value  # closed history is authoritative
    assert session.query(AccountSnapshot).count() == 1
    account = trade.account
    assert account.source == "tradelocker"
    assert account.external_id == "12345"


def test_planned_rr_and_realized_r_are_computed(session):
    service, _ = _service()
    service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()
    trade = session.query(Trade).one()
    # Uses the same Phase 1 calculators via recalculate_derived.
    assert trade.planned_rr == pytest.approx(3.0)
    assert trade.realized_r == pytest.approx(2.0)
    assert trade.r_method == "price"  # no initial_risk_amount from the broker


def test_idempotent_sync_does_not_duplicate(session):
    service, _ = _service()
    service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()
    first_count = session.query(Trade).count()

    service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()
    assert session.query(Trade).count() == first_count == 1
    assert session.query(AccountSnapshot).count() == 1  # snapshot deduped within 5 min


def test_open_position_update_updates_mutable_fields(session):
    open_only = fakes.default_routes(history={"d": {"ordersHistory": []}})
    service, _ = _service(open_only)
    service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()
    trade = session.query(Trade).one()
    assert trade.status == TradeStatus.OPEN.value
    assert trade.stop_loss == pytest.approx(1.095)

    # A later sync with a moved stop / updated size / unrealized P&L.
    moved = fakes.default_routes(
        history={"d": {"ordersHistory": []}},
        positions={
            "d": {
                "positions": [
                    [
                        "1001",
                        "278",
                        "buy",
                        "0.20",
                        "1.10000",
                        "1.10500",
                        "1.12000",
                        fakes.OPEN_MS,
                        "40.00",
                    ],
                ]
            }
        },
    )
    service2, _ = _service(moved)
    service2.sync_account(session, "12345", "1", dry_run=False)
    session.commit()

    trade = session.query(Trade).one()  # still exactly one trade
    assert trade.stop_loss == pytest.approx(1.105)
    assert trade.take_profit == pytest.approx(1.120)
    assert trade.quantity == pytest.approx(0.20)
    assert trade.gross_pnl == pytest.approx(40.0)
    assert trade.net_pnl is None  # open trade never carries realized net


def test_closed_history_converts_open_to_closed(session):
    # Phase 1: only an open position.
    service_open, _ = _service(fakes.default_routes(history={"d": {"ordersHistory": []}}))
    service_open.sync_account(session, "12345", "1", dry_run=False)
    session.commit()
    assert session.query(Trade).one().status == TradeStatus.OPEN.value

    # Phase 2: position gone from open feed, now present in closed history.
    service_closed, _ = _service(fakes.default_routes(positions={"d": {"positions": []}}))
    service_closed.sync_account(session, "12345", "1", dry_run=False)
    session.commit()

    trade = session.query(Trade).one()  # same row, converted
    assert trade.status == TradeStatus.CLOSED.value
    assert trade.closed_at is not None
    assert trade.exit_price == pytest.approx(1.11)


def test_user_notes_and_manual_risk_are_preserved(session):
    service_open, _ = _service(fakes.default_routes(history={"d": {"ordersHistory": []}}))
    service_open.sync_account(session, "12345", "1", dry_run=False)
    session.commit()

    trade = session.query(Trade).one()
    trade.notes = "my trade thesis"
    trade.initial_risk_amount = 100.0
    session.commit()

    # Closed history arrives and updates the trade.
    service_closed, _ = _service(fakes.default_routes(positions={"d": {"positions": []}}))
    service_closed.sync_account(session, "12345", "1", dry_run=False)
    session.commit()

    trade = session.query(Trade).one()
    assert trade.status == TradeStatus.CLOSED.value
    assert trade.notes == "my trade thesis"  # never overwritten
    assert trade.initial_risk_amount == pytest.approx(100.0)  # manual value kept
    assert trade.r_method == "money"  # now uses the manual risk (200 / 100 = 2R)
    assert trade.realized_r == pytest.approx(2.0)


def test_snapshot_duplicate_prevention_within_interval(session):
    service, _ = _service()
    service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()
    service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()
    # Same balance/equity within 5 minutes -> only one snapshot.
    assert session.query(AccountSnapshot).count() == 1

    # A different balance -> a new snapshot is allowed.
    changed = fakes.default_routes(
        state=fakes.account_state_response(balance="99999.00", equity="99999.00")
    )
    service2, _ = _service(changed)
    service2.sync_account(session, "12345", "1", dry_run=False)
    session.commit()
    assert session.query(AccountSnapshot).count() == 2


def test_dry_run_writes_nothing(session):
    service, _ = _service()
    result = service.sync_account(session, "12345", "1", dry_run=True)
    session.commit()

    assert result.status == "DRY_RUN"
    assert result.trades_imported >= 1  # it still previews the counts
    assert session.query(Trade).count() == 0
    assert session.query(AccountSnapshot).count() == 0
    assert session.query(SyncRun).count() == 0


def test_sync_run_recorded_on_success(session):
    service, _ = _service()
    service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()
    runs = session.query(SyncRun).all()
    assert len(runs) == 1
    assert runs[0].status == "SUCCESS"
    assert runs[0].source == "tradelocker"
    assert runs[0].imported_count >= 1


def test_sync_run_recorded_on_failure(session):
    routes = fakes.default_routes()
    routes["/positions"] = (500, {"error": "boom"})
    service, _ = _service(routes)
    result = service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()

    assert result.status == "FAILED"
    assert result.errors
    run = session.query(SyncRun).one()
    assert run.status == "FAILED"


def test_sync_accounts_upserts_metadata_only(session):
    service, _ = _service()
    result = service.sync_accounts(session, dry_run=False)
    session.commit()
    assert result.accounts_seen == 1
    assert session.query(Trade).count() == 0  # metadata-only, no trades
    from trading_journal.models import Account

    account = session.query(Account).filter(Account.source == "tradelocker").one()
    assert account.external_id == "12345"


def test_missing_credentials_propagate_as_config_error(session):
    from trading_journal.connectors.tradelocker import TradeLockerConfigError

    service, _ = _service(email=None, password=None, server=None)
    with pytest.raises(TradeLockerConfigError):
        service.sync_account(session, "12345", "1", dry_run=False)


def test_local_accounts_are_not_touched_by_sync(session):
    from trading_journal.services.account_service import get_or_create_default_account

    local = get_or_create_default_account(session)
    session.commit()
    local_id, local_name = local.id, local.name

    service, _ = _service()
    service.sync_account(session, "12345", "1", dry_run=False)
    session.commit()

    refreshed = session.get(type(local), local_id)
    assert refreshed.name == local_name
    assert refreshed.source == "local"  # untouched
    # The TradeLocker account is a separate row.
    from trading_journal.models import Account

    assert session.query(Account).count() == 2
