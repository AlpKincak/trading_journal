"""Read-only TradeLocker sync orchestration.

``TradeLockerSyncService`` ties together the read-only client, the tolerant
parsers, and the pure mappers, then writes the results into the local database
through idempotent upserts. It is the *only* place that turns TradeLocker data
into database rows.

Guarantees:
* **Read-only** — it uses the read-only client exclusively; it can only pull data.
* **Idempotent** — re-running a sync never duplicates trades/snapshots.
* **Dry-run safe** — in dry-run mode it performs zero mutations (it computes the
  would-be counts by inspecting existing rows without changing them), so wrapping
  it in a committing ``session_scope`` is harmless.
* **Non-destructive** — user ``notes`` are never overwritten; a manually-entered
  ``initial_risk_amount`` is only filled when locally empty; disappeared open
  positions are flagged, never deleted.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import TradeLockerSettings
from ..connectors.tradelocker import mapper
from ..connectors.tradelocker.client import TradeLockerReadOnlyClient
from ..connectors.tradelocker.config_parser import parse_table, unwrap_envelope
from ..connectors.tradelocker.errors import TradeLockerConfigError, TradeLockerError
from ..connectors.tradelocker.mapper import MappedTrade, MappingContext
from ..connectors.tradelocker.schemas import TradeLockerAccount, TradeLockerConfig
from ..models import Account, AccountSnapshot, SyncStatus, Trade, TradeStatus
from . import sync_state_service
from .account_service import add_snapshot
from .trade_service import recalculate_derived

SOURCE = mapper.SOURCE

# Fields carried straight from a candidate onto a Trade row (excludes derived
# fields, notes, and initial_risk_amount, which have special handling).
_TRADE_VALUE_FIELDS = (
    "symbol",
    "side",
    "status",
    "opened_at",
    "closed_at",
    "entry_price",
    "exit_price",
    "quantity",
    "stop_loss",
    "take_profit",
    "gross_pnl",
    "fees",
    "net_pnl",
    "external_position_id",
    "external_order_id",
    "external_account_id",
    "external_account_number",
    "external_status",
    "raw_payload_json",
)


@dataclass
class SyncResult:
    """Structured outcome of a sync operation."""

    status: str = SyncStatus.SUCCESS.value
    dry_run: bool = False
    environment: str | None = None
    account_id: str | None = None
    acc_num: str | None = None

    accounts_seen: int = 0
    trades_imported: int = 0
    trades_updated: int = 0
    trades_skipped: int = 0
    open_positions_seen: int = 0
    closed_rows_seen: int = 0
    snapshots_imported: int = 0

    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None

    def summary(self) -> str:
        return (
            f"status={self.status} accounts={self.accounts_seen} "
            f"imported={self.trades_imported} updated={self.trades_updated} "
            f"skipped={self.trades_skipped} snapshots={self.snapshots_imported} "
            f"warnings={len(self.warnings)} errors={len(self.errors)}"
        )

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "dry_run": self.dry_run,
            "environment": self.environment,
            "account_id": self.account_id,
            "acc_num": self.acc_num,
            "accounts_seen": self.accounts_seen,
            "trades_imported": self.trades_imported,
            "trades_updated": self.trades_updated,
            "trades_skipped": self.trades_skipped,
            "open_positions_seen": self.open_positions_seen,
            "closed_rows_seen": self.closed_rows_seen,
            "snapshots_imported": self.snapshots_imported,
            "warnings": self.warnings,
            "errors": self.errors,
        }

    def merge(self, other: SyncResult) -> None:
        """Fold another result's counts/messages into this one (for --all)."""
        self.accounts_seen += other.accounts_seen
        self.trades_imported += other.trades_imported
        self.trades_updated += other.trades_updated
        self.trades_skipped += other.trades_skipped
        self.open_positions_seen += other.open_positions_seen
        self.closed_rows_seen += other.closed_rows_seen
        self.snapshots_imported += other.snapshots_imported
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)
        if other.status == SyncStatus.FAILED.value:
            self.status = SyncStatus.FAILED.value
        elif other.errors and self.status == SyncStatus.SUCCESS.value:
            self.status = SyncStatus.PARTIAL.value


class TradeLockerSyncService:
    """Orchestrates a read-only TradeLocker sync into the local database."""

    def __init__(
        self,
        client: TradeLockerReadOnlyClient,
        settings: TradeLockerSettings,
        snapshot_dedup_minutes: int = 5,
    ) -> None:
        self._client = client
        self._settings = settings
        self._snapshot_dedup_seconds = snapshot_dedup_minutes * 60

    # -- discovery ---------------------------------------------------------
    def discover_accounts(self) -> list[TradeLockerAccount]:
        return self._client.list_accounts()

    # -- public sync entrypoints ------------------------------------------
    def sync_accounts(self, session: Session, dry_run: bool = False) -> SyncResult:
        """Discover TradeLocker accounts and upsert their metadata only."""
        result = SyncResult(dry_run=dry_run, environment=self._settings.environment)
        try:
            accounts = self.discover_accounts()
            for account in accounts:
                self._upsert_account(session, account, dry_run, result)
        except TradeLockerConfigError:
            raise
        except TradeLockerError as exc:
            result.errors.append(str(exc))
            result.status = SyncStatus.FAILED.value
        return self._finalize(session, result, dry_run)

    def sync_account(
        self,
        session: Session,
        account_id: str | int,
        acc_num: str | int | None = None,
        lookback_days: int | None = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """Full read-only sync of one account: metadata, positions, history, balance."""
        result = SyncResult(
            dry_run=dry_run,
            environment=self._settings.environment,
            account_id=str(account_id),
            acc_num=str(acc_num) if acc_num is not None else None,
        )
        try:
            self._run_account_sync(session, result, account_id, acc_num, lookback_days, dry_run)
        except TradeLockerConfigError:
            raise
        except TradeLockerError as exc:
            result.errors.append(str(exc))
            result.status = SyncStatus.FAILED.value
        return self._finalize(session, result, dry_run)

    def sync_all_configured_accounts(
        self, session: Session, lookback_days: int | None = None, dry_run: bool = False
    ) -> SyncResult:
        """Discover every account and sync each one."""
        aggregate = SyncResult(dry_run=dry_run, environment=self._settings.environment)
        try:
            accounts = self.discover_accounts()
        except TradeLockerConfigError:
            raise
        except TradeLockerError as exc:
            aggregate.errors.append(str(exc))
            aggregate.status = SyncStatus.FAILED.value
            aggregate.finished_at = datetime.now()
            return aggregate

        for account in accounts:
            one = self.sync_account(
                session, account.account_id, account.acc_num, lookback_days, dry_run
            )
            aggregate.merge(one)
        aggregate.finished_at = datetime.now()
        return aggregate

    def preview_sync(
        self,
        session: Session,
        account_id: str | int,
        acc_num: str | int | None = None,
        lookback_days: int | None = None,
    ) -> SyncResult:
        """Dry-run equivalent: compute what *would* change without writing."""
        return self.sync_account(session, account_id, acc_num, lookback_days, dry_run=True)

    # -- account-level pipeline -------------------------------------------
    def _run_account_sync(
        self,
        session: Session,
        result: SyncResult,
        account_id: str | int,
        acc_num: str | int | None,
        lookback_days: int | None,
        dry_run: bool,
    ) -> None:
        env = self._settings.environment

        # Resolve metadata (currency/name) and fill in a missing accNum via discovery.
        tl_account = self._resolve_account(account_id, result)
        if acc_num is None:
            if tl_account is not None and tl_account.acc_num:
                acc_num = tl_account.acc_num
                result.acc_num = str(acc_num)
            else:
                result.warnings.append(
                    "No accNum provided and it could not be discovered; some /trade "
                    "endpoints may reject the request."
                )

        # Config: column definitions + instrument-name resolution.
        config = self._safe_get_config(account_id, acc_num, result)
        instruments = dict(config.instruments)
        instruments.update(self._safe_get_instruments(account_id, acc_num))

        ctx = MappingContext(
            environment=env,
            account_id=str(account_id),
            acc_num=str(acc_num) if acc_num is not None else None,
            instruments=instruments,
        )

        # Upsert the local Account (needed as FK target for trades/snapshots).
        local_account = self._upsert_account_by_id(
            session, account_id, acc_num, tl_account, dry_run, result
        )
        local_account_id = local_account.id if local_account is not None else None

        seen_open_keys: set[str] = set()
        seen_closed_keys: set[str] = set()

        # Collect both feeds first so closed history can take precedence over a
        # position that (contradictorily) still appears in the open feed.
        open_candidates = self._collect_open_positions(account_id, acc_num, config, ctx, result)
        result.open_positions_seen = len(open_candidates)
        closed_candidates = self._collect_closed_history(
            account_id, acc_num, config, ctx, lookback_days, result
        )
        closed_keys = {cand.dedup_key for cand in closed_candidates}

        # --- open positions (skip any that closed history already covers) ---
        for cand in open_candidates:
            seen_open_keys.add(cand.dedup_key)
            if cand.dedup_key in closed_keys:
                # Closed history is authoritative; do not re-open the trade.
                continue
            self._upsert_trade(session, local_account_id, cand, dry_run, result)

        # --- closed history ---
        for cand in closed_candidates:
            seen_closed_keys.add(cand.dedup_key)
            self._upsert_trade(session, local_account_id, cand, dry_run, result)

        # --- flag disappeared open positions (never auto-delete/close) ---
        if local_account_id is not None:
            self._flag_stale_open_positions(
                session, local_account_id, seen_open_keys, seen_closed_keys, dry_run, result
            )

        # --- balance / equity snapshot ---
        self._sync_snapshot(session, account_id, acc_num, config, local_account_id, dry_run, result)

    # -- account resolution / upsert --------------------------------------
    def _resolve_account(
        self, account_id: str | int, result: SyncResult
    ) -> TradeLockerAccount | None:
        try:
            accounts = self.discover_accounts()
        except TradeLockerError as exc:
            result.warnings.append(f"account discovery unavailable: {exc}")
            return None
        for account in accounts:
            if str(account.account_id) == str(account_id):
                return account
        result.warnings.append(
            f"account {account_id} was not found in the discovered account list."
        )
        return None

    def _upsert_account(
        self, session: Session, account: TradeLockerAccount, dry_run: bool, result: SyncResult
    ) -> Account | None:
        return self._upsert_account_by_id(
            session, account.account_id, account.acc_num, account, dry_run, result
        )

    def _upsert_account_by_id(
        self,
        session: Session,
        account_id: str | int,
        acc_num: str | int | None,
        tl_account: TradeLockerAccount | None,
        dry_run: bool,
        result: SyncResult,
    ) -> Account | None:
        env = self._settings.environment
        candidate = mapper.map_account(
            tl_account if tl_account is not None else {"id": account_id, "accNum": acc_num},
            env,
        )
        result.warnings.extend(candidate.warnings)

        existing = (
            session.execute(
                select(Account).where(
                    Account.source == SOURCE,
                    Account.external_id == candidate.external_id,
                    Account.environment == env,
                )
            )
            .scalars()
            .first()
        )

        result.accounts_seen += 1

        if existing is not None:
            if not dry_run:
                existing.broker = candidate.broker
                if candidate.base_currency:
                    existing.base_currency = candidate.base_currency
                if candidate.external_account_number:
                    existing.external_account_number = candidate.external_account_number
                existing.last_synced_at = datetime.now()
            return existing

        if dry_run:
            return None

        account = Account(
            name=self._unique_account_name(session, candidate.name, candidate.external_id),
            broker=candidate.broker,
            base_currency=candidate.base_currency or "USD",
            source=SOURCE,
            external_id=candidate.external_id,
            external_account_number=candidate.external_account_number,
            environment=env,
            last_synced_at=datetime.now(),
        )
        session.add(account)
        session.flush()
        return account

    @staticmethod
    def _unique_account_name(session: Session, name: str, external_id: str) -> str:
        taken = session.execute(select(Account.name).where(Account.name == name)).first()
        if taken is None:
            return name
        return f"{name} ({external_id})"

    # -- data collection ---------------------------------------------------
    def _safe_get_config(
        self, account_id: str | int, acc_num: str | int | None, result: SyncResult
    ) -> TradeLockerConfig:
        try:
            return self._client.get_config(account_id, acc_num)
        except TradeLockerError as exc:
            result.warnings.append(
                f"/trade/config unavailable ({exc}); falling back to field-name aliases."
            )
            return TradeLockerConfig()

    def _safe_get_instruments(
        self, account_id: str | int, acc_num: str | int | None
    ) -> dict[str, str]:
        try:
            return self._client.get_instruments(account_id, acc_num)
        except TradeLockerError:
            return {}

    def _collect_open_positions(
        self,
        account_id: str | int,
        acc_num: str | int | None,
        config: TradeLockerConfig,
        ctx: MappingContext,
        result: SyncResult,
    ) -> list[MappedTrade]:
        raw = self._client.get_open_positions(account_id, acc_num)
        rows = parse_table(
            raw,
            config.columns("positionsConfig"),
            row_keys=("positions", "openPositions"),
            context="positions",
            warnings=result.warnings,
        )
        candidates: list[MappedTrade] = []
        for row in rows:
            cand = mapper.map_open_position(row, ctx, result.warnings)
            if cand is not None:
                candidates.append(cand)
        return candidates

    def _collect_closed_history(
        self,
        account_id: str | int,
        acc_num: str | int | None,
        config: TradeLockerConfig,
        ctx: MappingContext,
        lookback_days: int | None,
        result: SyncResult,
    ) -> list[MappedTrade]:
        days = lookback_days if lookback_days is not None else self._settings.lookback_days
        from_date = datetime.now() - timedelta(days=days)
        raw = self._client.get_orders_history(account_id, acc_num, from_date=from_date)
        rows = parse_table(
            raw,
            config.columns("ordersHistoryConfig") or config.columns("filledOrdersConfig"),
            row_keys=("ordersHistory", "orders", "filledOrders"),
            context="ordersHistory",
            warnings=result.warnings,
        )
        result.closed_rows_seen = len(rows)

        # Map completed rows, then aggregate multi-leg positions.
        completed: list[MappedTrade] = []
        for row in rows:
            if not mapper.order_is_completed_trade(row):
                continue
            cand = mapper.map_closed_order(row, ctx, result.warnings)
            if cand is not None:
                completed.append(cand)

        by_position: dict[str, list[MappedTrade]] = defaultdict(list)
        standalone: list[MappedTrade] = []
        for cand in completed:
            if cand.external_position_id:
                by_position[cand.dedup_key].append(cand)
            else:
                standalone.append(cand)

        final: list[MappedTrade] = []
        for legs in by_position.values():
            if len(legs) == 1:
                final.append(legs[0])
            else:
                final.append(mapper.aggregate_position_legs(legs, result.warnings))
        final.extend(standalone)
        return final

    # -- trade upsert (idempotent) ----------------------------------------
    def _upsert_trade(
        self,
        session: Session,
        local_account_id: int | None,
        cand: MappedTrade,
        dry_run: bool,
        result: SyncResult,
    ) -> None:
        result.warnings.extend(cand.warnings)

        existing = None
        if local_account_id is not None:
            existing = (
                session.execute(
                    select(Trade).where(
                        Trade.account_id == local_account_id,
                        Trade.source == SOURCE,
                        Trade.external_id == cand.dedup_key,
                    )
                )
                .scalars()
                .first()
            )

        if existing is None:
            if dry_run:
                result.trades_imported += 1
                return
            trade = Trade(account_id=local_account_id, source=SOURCE, external_id=cand.dedup_key)
            self._apply_trade_values(trade, self._trade_target_values(cand, None))
            trade.last_synced_at = datetime.now()
            recalculate_derived(trade)
            self._post_derive_fixups(trade, cand)
            session.add(trade)
            session.flush()
            result.trades_imported += 1
            return

        target = self._trade_target_values(cand, existing.initial_risk_amount)
        changed = any(getattr(existing, attr) != value for attr, value in target.items())
        if dry_run:
            result.trades_updated += 1 if changed else 0
            result.trades_skipped += 0 if changed else 1
            return

        existing.last_synced_at = datetime.now()
        if changed:
            self._apply_trade_values(existing, target)
            recalculate_derived(existing)
            self._post_derive_fixups(existing, cand)
            session.flush()
            result.trades_updated += 1
        else:
            result.trades_skipped += 1

    def _trade_target_values(
        self, cand: MappedTrade, existing_initial_risk: float | None
    ) -> dict[str, Any]:
        values: dict[str, Any] = {attr: getattr(cand, attr) for attr in _TRADE_VALUE_FIELDS}
        # Only fill initial_risk_amount when the broker provides one and the local
        # value is empty — never clobber a manually-entered risk figure.
        if cand.initial_risk_amount is not None and existing_initial_risk is None:
            values["initial_risk_amount"] = cand.initial_risk_amount
        return values

    @staticmethod
    def _apply_trade_values(trade: Trade, values: dict[str, Any]) -> None:
        for attr, value in values.items():
            setattr(trade, attr, value)

    @staticmethod
    def _post_derive_fixups(trade: Trade, cand: MappedTrade) -> None:
        # An open trade must not carry a realized net P&L: any value derived from
        # unrealized gross is cleared (spec: net_pnl null for open trades).
        if trade.status == TradeStatus.OPEN.value:
            trade.net_pnl = cand.net_pnl  # None for open candidates

    def _flag_stale_open_positions(
        self,
        session: Session,
        local_account_id: int,
        seen_open_keys: set[str],
        seen_closed_keys: set[str],
        dry_run: bool,
        result: SyncResult,
    ) -> None:
        existing_open = (
            session.execute(
                select(Trade).where(
                    Trade.account_id == local_account_id,
                    Trade.source == SOURCE,
                    Trade.status == TradeStatus.OPEN.value,
                )
            )
            .scalars()
            .all()
        )
        for trade in existing_open:
            key = trade.external_id
            if key in seen_open_keys or key in seen_closed_keys:
                continue
            result.warnings.append(
                f"open position {trade.external_position_id or key} is no longer reported "
                f"by TradeLocker; left OPEN (not auto-closed). Review manually."
            )
            if not dry_run and trade.external_status != "STALE":
                trade.external_status = "STALE"
                trade.last_synced_at = datetime.now()

    # -- snapshot ----------------------------------------------------------
    def _sync_snapshot(
        self,
        session: Session,
        account_id: str | int,
        acc_num: str | int | None,
        config: TradeLockerConfig,
        local_account_id: int | None,
        dry_run: bool,
        result: SyncResult,
    ) -> None:
        try:
            raw = self._client.get_account_details(account_id, acc_num)
        except TradeLockerError as exc:
            result.warnings.append(f"account details unavailable: {exc}")
            return

        details = self._extract_account_details(raw, config, result.warnings)
        snap = mapper.map_account_snapshot(details)
        if snap is None:
            result.warnings.append("no balance/equity found in account details; snapshot skipped.")
            return
        result.warnings.extend(snap.warnings)

        if local_account_id is None:
            # Dry-run with no local account yet — would import one snapshot.
            result.snapshots_imported += 1
            return

        timestamp = snap.timestamp or datetime.now()
        if self._snapshot_is_duplicate(session, local_account_id, snap, timestamp):
            return

        if dry_run:
            result.snapshots_imported += 1
            return

        add_snapshot(
            session,
            account_id=local_account_id,
            balance=snap.balance,
            equity=snap.equity,
            timestamp=timestamp,
            source=SOURCE,
        )
        result.snapshots_imported += 1

    def _snapshot_is_duplicate(
        self, session: Session, local_account_id: int, snap: Any, timestamp: datetime
    ) -> bool:
        latest = (
            session.execute(
                select(AccountSnapshot)
                .where(
                    AccountSnapshot.account_id == local_account_id,
                    AccountSnapshot.source == SOURCE,
                )
                .order_by(AccountSnapshot.timestamp.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if latest is None:
            return False
        within_window = (
            abs((timestamp - latest.timestamp).total_seconds()) < self._snapshot_dedup_seconds
        )
        same_values = latest.balance == snap.balance and latest.equity == snap.equity
        return within_window and same_values

    @staticmethod
    def _extract_account_details(
        raw: Any, config: TradeLockerConfig, warnings: list[str]
    ) -> dict[str, Any]:
        """Flatten the account-state response into a single field dict."""
        body = unwrap_envelope(raw)
        columns = config.columns("accountDetailsConfig")
        data: Any = None
        if isinstance(body, dict):
            for key in ("accountDetailsData", "accountDetails", "details", "balances"):
                if key in body:
                    data = body[key]
                    break
            if data is None:
                # The body may itself already be a flat dict of values.
                if any(k in body for k in ("balance", "equity", "accountBalance")):
                    return dict(body)
        elif isinstance(body, list):
            data = body

        if data is None:
            warnings.append("account details: unrecognized shape; balance/equity unavailable.")
            return {}

        # A single row nested one level deep.
        if isinstance(data, list) and data and isinstance(data[0], (list, tuple)):
            data = data[0]

        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return mapper.account_details_to_dict(data)
        if isinstance(data, list) and columns:
            return {columns[i]: data[i] for i in range(min(len(columns), len(data)))}

        warnings.append("account details: no column config; balance/equity may be unavailable.")
        return {}

    # -- finalize / record -------------------------------------------------
    def _finalize(self, session: Session, result: SyncResult, dry_run: bool) -> SyncResult:
        result.finished_at = datetime.now()
        if result.status != SyncStatus.FAILED.value:
            if dry_run:
                result.status = SyncStatus.DRY_RUN.value
            elif result.errors:
                result.status = SyncStatus.PARTIAL.value
            else:
                result.status = SyncStatus.SUCCESS.value
        if not dry_run:
            self._record(session, result)
        return result

    def _record(self, session: Session, result: SyncResult) -> None:
        sync_state_service.record_sync_run(
            session,
            source=SOURCE,
            status=result.status,
            started_at=result.started_at,
            finished_at=result.finished_at,
            environment=result.environment,
            account_id=result.account_id,
            acc_num=result.acc_num,
            imported_count=result.trades_imported,
            updated_count=result.trades_updated,
            skipped_count=result.trades_skipped,
            warning_count=len(result.warnings),
            error_count=len(result.errors),
            summary_json=json.dumps(result.to_summary_dict(), default=str),
        )


def build_sync_service(
    settings: TradeLockerSettings,
    transport: Any = None,
    client: TradeLockerReadOnlyClient | None = None,
) -> TradeLockerSyncService:
    """Factory used by the CLI/UI to construct a service from settings.

    ``transport`` allows tests to inject a fake HTTP transport; ``client`` allows
    injecting a fully-built client. In normal use both are omitted and a
    ``requests``-backed read-only client is created.
    """
    if client is None:
        client = TradeLockerReadOnlyClient.from_settings(settings, transport=transport)
    return TradeLockerSyncService(client, settings)
