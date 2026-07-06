"""Map parsed TradeLocker records into local database candidates.

This layer is intentionally free of any database access: it converts dicts (as
produced by :mod:`.config_parser`) into plain candidate dataclasses. The sync
service is responsible for turning candidates into inserts/updates. Keeping the
two apart makes the mapping logic trivially unit-testable and guarantees that a
weird API response can never directly corrupt the database.

Tolerance rules:
* Field lookups use alias lists, so differing broker field names still map.
* Missing *required* fields (symbol/side/entry/open time) cause the row to be
  skipped **with a warning**, never silently dropped.
* Unknown fields survive in ``raw_payload`` for debugging.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ...models import Side, TradeStatus, normalize_side

SOURCE = "tradelocker"

# --- alias tables ---------------------------------------------------------
_SYMBOL_KEYS = ("symbol", "name", "instrument", "tradableInstrumentName", "instrumentName")
_INSTRUMENT_ID_KEYS = ("tradableInstrumentId", "instrumentId", "routeId")
_SIDE_KEYS = ("side", "direction", "positionSide")
_QTY_KEYS = ("qty", "quantity", "lots", "size", "filledQty", "volume")
_ENTRY_KEYS = ("avgPrice", "openPrice", "entryPrice", "avgOpenPrice", "price", "openAvgPrice")
_EXIT_KEYS = ("closePrice", "exitPrice", "avgClosePrice", "closeAvgPrice", "closedPrice")
_OPEN_DATE_KEYS = ("openDate", "openTime", "createdDate", "dateCreated", "created")
_CLOSE_DATE_KEYS = ("closeDate", "closeTime", "dateClosed", "lastModified", "closed")
_STOP_KEYS = ("stopLossPrice", "stopLoss", "sl", "stopPrice")
_TAKE_KEYS = ("takeProfitPrice", "takeProfit", "tp")
_GROSS_PNL_KEYS = ("grossPnl", "grossProfit")
_NET_PNL_KEYS = ("netPnl", "realizedPl", "realizedPnl", "netProfit")
_ANY_PNL_KEYS = ("profit", "pl", "pnl", "profitLoss")
_UNREALIZED_KEYS = ("unrealizedPl", "unrealizedPnl", "openPl", "floatingPl")
_FEE_KEYS = ("fee", "commission", "fees", "commissions")
_SWAP_KEYS = ("swap", "rollover", "storage")
_POSITION_ID_KEYS = ("positionId", "posId")
_ORDER_ID_KEYS = ("orderId", "id", "ticket")
_ORDER_STATUS_KEYS = ("status", "orderStatus", "state")

# Order statuses that represent a completed (executed) trade.
_FILLED_STATUSES = {"filled", "closed", "executed", "done", "complete", "completed"}
# Statuses that are clearly not completed trades (skip when building closed trades).
_NON_TRADE_STATUSES = {"cancelled", "canceled", "rejected", "expired", "new", "working", "pending"}


# ---------------------------------------------------------------------------
# Candidate dataclasses (DB-agnostic)
# ---------------------------------------------------------------------------
@dataclass
class MappingContext:
    environment: str
    account_id: str
    acc_num: str | None = None
    instruments: dict[str, str] = field(default_factory=dict)


@dataclass
class MappedAccount:
    external_id: str
    external_account_number: str | None
    name: str
    broker: str
    base_currency: str | None
    environment: str
    source: str = SOURCE
    warnings: list[str] = field(default_factory=list)


@dataclass
class MappedTrade:
    dedup_key: str
    key_confidence: str  # "high" | "low"
    symbol: str
    side: str
    status: str
    opened_at: datetime
    external_account_id: str | None = None
    external_account_number: str | None = None
    external_position_id: str | None = None
    external_order_id: str | None = None
    external_status: str | None = None
    closed_at: datetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    quantity: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    gross_pnl: float | None = None
    fees: float | None = None
    net_pnl: float | None = None
    initial_risk_amount: float | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def raw_payload_json(self) -> str:
        return json.dumps(self.raw_payload, default=str, sort_keys=True)


@dataclass
class MappedSnapshot:
    balance: float
    equity: float | None = None
    timestamp: datetime | None = None
    source: str = SOURCE
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------
def _first(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _to_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    number = _to_float(value)
    if number is not None:
        # Epoch ms if large, else seconds.
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
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _looks_numeric(value: Any) -> bool:
    return _to_float(value) is not None


def resolve_symbol(row: dict[str, Any], ctx: MappingContext, warnings: list[str]) -> str | None:
    """Resolve a human symbol from a row, using the instruments map as a fallback."""
    for key in _SYMBOL_KEYS:
        value = row.get(key)
        if value and not _looks_numeric(value):
            return str(value).upper()
    inst_id = _first(row, _INSTRUMENT_ID_KEYS)
    if inst_id is not None:
        name = ctx.instruments.get(str(inst_id))
        if name:
            return name.upper()
        warnings.append(
            f"could not resolve symbol for tradable-instrument id {inst_id}; "
            f"using placeholder INSTR_{inst_id}"
        )
        return f"INSTR_{inst_id}"
    return None


def _fees_from(row: dict[str, Any]) -> float | None:
    fee = _to_float(_first(row, _FEE_KEYS))
    swap = _to_float(_first(row, _SWAP_KEYS))
    if fee is None and swap is None:
        return None
    # Store the combined non-spread cost; commissions/swaps are typically negative
    # already, so we sum their magnitudes as a positive "fees" figure.
    total = abs(fee or 0.0) + abs(swap or 0.0)
    return total or None


# ---------------------------------------------------------------------------
# Dedup keys
# ---------------------------------------------------------------------------
def position_dedup_key(environment: str, account_id: str, position_id: str) -> str:
    return f"tl:{environment}:{account_id}:pos:{position_id}"


def order_dedup_key(environment: str, account_id: str, order_id: str) -> str:
    return f"tl:{environment}:{account_id}:ord:{order_id}"


def composite_dedup_key(
    environment: str,
    account_id: str,
    symbol: str,
    side: str,
    opened_at: datetime | None,
    entry_price: float | None,
    extra: str = "",
) -> str:
    parts = [
        environment,
        account_id,
        symbol,
        side,
        opened_at.isoformat() if opened_at else "?",
        f"{entry_price:.6f}" if entry_price is not None else "?",
        extra,
    ]
    return "tl:cmp:" + ":".join(parts)


# ---------------------------------------------------------------------------
# Account mapping
# ---------------------------------------------------------------------------
def map_account(account: Any, environment: str) -> MappedAccount:
    """Map a :class:`TradeLockerAccount` (or dict) to an account candidate."""
    if isinstance(account, dict):
        external_id = str(account.get("id") or account.get("account_id") or "")
        acc_num = account.get("accNum") or account.get("acc_num")
        currency = account.get("currency")
        name_hint = account.get("name")
    else:
        external_id = str(account.account_id)
        acc_num = account.acc_num
        currency = account.currency
        name_hint = account.name

    acc_num_str = str(acc_num) if acc_num is not None else None
    label = name_hint or (f"#{acc_num_str}" if acc_num_str else external_id)
    name = f"TradeLocker {environment} · {label}"
    return MappedAccount(
        external_id=external_id,
        external_account_number=acc_num_str,
        name=name,
        broker="TradeLocker",
        base_currency=currency,
        environment=environment,
    )


# ---------------------------------------------------------------------------
# Position / order mapping
# ---------------------------------------------------------------------------
def _map_common(row: dict[str, Any], ctx: MappingContext, warnings: list[str]) -> dict[str, Any]:
    symbol = resolve_symbol(row, ctx, warnings)
    side = normalize_side(_first(row, _SIDE_KEYS))
    return {
        "symbol": symbol,
        "side": side,
        "quantity": _to_float(_first(row, _QTY_KEYS)),
        "entry_price": _to_float(_first(row, _ENTRY_KEYS)),
        "stop_loss": _to_float(_first(row, _STOP_KEYS)),
        "take_profit": _to_float(_first(row, _TAKE_KEYS)),
    }


def map_open_position(
    row: dict[str, Any], ctx: MappingContext, warnings: list[str]
) -> MappedTrade | None:
    """Map one open-position row to an OPEN trade candidate."""
    local: list[str] = []
    common = _map_common(row, ctx, local)
    opened_at = _to_dt(_first(row, _OPEN_DATE_KEYS))
    position_id = _first(row, _POSITION_ID_KEYS)
    # On the positions endpoint the row's own id is the position id.
    if position_id is None:
        position_id = row.get("id")

    missing = _missing_required(common, opened_at)
    if missing:
        warnings.append(
            f"open position skipped (account {ctx.account_id}): missing {', '.join(missing)}"
        )
        return None

    if position_id is not None:
        key = position_dedup_key(ctx.environment, ctx.account_id, str(position_id))
        confidence = "high"
    else:
        key = composite_dedup_key(
            ctx.environment,
            ctx.account_id,
            common["symbol"],
            common["side"],
            opened_at,
            common["entry_price"],
            extra="open",
        )
        confidence = "low"
        local.append(
            f"open position for {common['symbol']} has no position id; using a "
            f"composite key (low confidence)."
        )

    warnings.extend(local)
    return MappedTrade(
        dedup_key=key,
        key_confidence=confidence,
        symbol=common["symbol"],
        side=common["side"],
        status=TradeStatus.OPEN.value,
        opened_at=opened_at,
        external_account_id=ctx.account_id,
        external_account_number=ctx.acc_num,
        external_position_id=str(position_id) if position_id is not None else None,
        external_status="OPEN",
        entry_price=common["entry_price"],
        quantity=common["quantity"],
        stop_loss=common["stop_loss"],
        take_profit=common["take_profit"],
        gross_pnl=_to_float(_first(row, _UNREALIZED_KEYS)),  # unrealized; net stays None
        raw_payload=dict(row),
        warnings=local,
    )


def order_is_completed_trade(row: dict[str, Any]) -> bool:
    """True when an orders-history row represents a completed (filled) trade."""
    status = _first(row, _ORDER_STATUS_KEYS)
    if status is not None:
        status_l = str(status).strip().lower()
        if status_l in _FILLED_STATUSES:
            return True
        if status_l in _NON_TRADE_STATUSES:
            return False
    filled_qty = _to_float(row.get("filledQty"))
    if filled_qty is not None:
        return filled_qty > 0
    # Unknown status but has a P&L or exit -> treat as completed.
    return (
        _first(row, _ANY_PNL_KEYS + _NET_PNL_KEYS) is not None
        or _first(row, _EXIT_KEYS) is not None
    )


def map_closed_order(
    row: dict[str, Any], ctx: MappingContext, warnings: list[str]
) -> MappedTrade | None:
    """Map one closed/filled order-history row to a CLOSED trade candidate."""
    local: list[str] = []
    common = _map_common(row, ctx, local)
    opened_at = _to_dt(_first(row, _OPEN_DATE_KEYS))
    closed_at = _to_dt(_first(row, _CLOSE_DATE_KEYS))
    position_id = _first(row, _POSITION_ID_KEYS)
    order_id = _first(row, _ORDER_ID_KEYS)

    missing = _missing_required(common, opened_at)
    if missing:
        warnings.append(
            f"closed order skipped (account {ctx.account_id}): missing {', '.join(missing)}"
        )
        return None

    # P&L: prefer an explicit net/realized figure. Otherwise treat the generic
    # "profit" field as the realized figure (and say so) to avoid double-counting
    # commissions/swaps against it.
    gross_pnl = _to_float(_first(row, _GROSS_PNL_KEYS))
    net_pnl = _to_float(_first(row, _NET_PNL_KEYS))
    fees = _fees_from(row)
    if net_pnl is None:
        any_pnl = _to_float(_first(row, _ANY_PNL_KEYS))
        if any_pnl is not None:
            net_pnl = any_pnl
            if gross_pnl is None:
                gross_pnl = any_pnl
            local.append(
                "closed trade P&L taken from 'profit' field and assumed to be net of "
                "costs (broker did not provide an explicit gross/net split)."
            )

    # Dedup-key preference: position id > order id > composite.
    if position_id is not None:
        key = position_dedup_key(ctx.environment, ctx.account_id, str(position_id))
        confidence = "high"
    elif order_id is not None:
        key = order_dedup_key(ctx.environment, ctx.account_id, str(order_id))
        confidence = "high"
    else:
        key = composite_dedup_key(
            ctx.environment,
            ctx.account_id,
            common["symbol"],
            common["side"],
            opened_at,
            common["entry_price"],
            extra=(closed_at.isoformat() if closed_at else "closed"),
        )
        confidence = "low"
        local.append(
            f"closed trade for {common['symbol']} has neither position nor order id; "
            f"using a composite key (low confidence)."
        )

    if closed_at is None:
        local.append(f"closed trade for {common['symbol']} is missing a close time.")

    warnings.extend(local)
    return MappedTrade(
        dedup_key=key,
        key_confidence=confidence,
        symbol=common["symbol"],
        side=common["side"],
        status=TradeStatus.CLOSED.value,
        opened_at=opened_at,
        closed_at=closed_at,
        external_account_id=ctx.account_id,
        external_account_number=ctx.acc_num,
        external_position_id=str(position_id) if position_id is not None else None,
        external_order_id=str(order_id) if order_id is not None else None,
        external_status=str(_first(row, _ORDER_STATUS_KEYS) or "CLOSED"),
        entry_price=common["entry_price"],
        exit_price=_to_float(_first(row, _EXIT_KEYS)),
        quantity=common["quantity"],
        stop_loss=common["stop_loss"],
        take_profit=common["take_profit"],
        gross_pnl=gross_pnl,
        fees=fees,
        net_pnl=net_pnl,
        raw_payload=dict(row),
        warnings=local,
    )


def aggregate_position_legs(legs: list[MappedTrade], warnings: list[str]) -> MappedTrade:
    """Aggregate multiple closed legs of one position into a single closed trade.

    Used when a position has multiple fills/partial closes under the same position
    id. This is a **best-effort** aggregation, not exact institutional
    reconstruction: P&L/fees are summed, entry is the first leg's, exit is the
    last leg's, quantity is summed, and the trade spans the earliest open to the
    latest close. A warning is always emitted so the user can review manually.
    """
    if len(legs) == 1:
        return legs[0]

    ordered = sorted(legs, key=lambda c: c.closed_at or c.opened_at)
    base = ordered[-1]
    first = ordered[0]

    def _sum(attr: str) -> float | None:
        vals = [getattr(c, attr) for c in ordered if getattr(c, attr) is not None]
        return float(sum(vals)) if vals else None

    opened = min((c.opened_at for c in ordered if c.opened_at), default=base.opened_at)
    closed = max((c.closed_at for c in ordered if c.closed_at), default=base.closed_at)

    message = (
        f"position {base.external_position_id} had {len(ordered)} fills/legs; "
        f"aggregated into one trade (P&L summed). Review partial closes manually."
    )
    warnings.append(message)

    return MappedTrade(
        dedup_key=base.dedup_key,
        key_confidence=base.key_confidence,
        symbol=base.symbol,
        side=first.side,
        status=TradeStatus.CLOSED.value,
        opened_at=opened,
        closed_at=closed,
        external_account_id=base.external_account_id,
        external_account_number=base.external_account_number,
        external_position_id=base.external_position_id,
        external_order_id=base.external_order_id,
        external_status=base.external_status,
        entry_price=first.entry_price,
        exit_price=base.exit_price,
        quantity=_sum("quantity"),
        stop_loss=first.stop_loss,
        take_profit=first.take_profit,
        gross_pnl=_sum("gross_pnl"),
        fees=_sum("fees"),
        net_pnl=_sum("net_pnl"),
        raw_payload={"aggregated_legs": [c.raw_payload for c in ordered]},
        warnings=[message],
    )


def _missing_required(common: dict[str, Any], opened_at: datetime | None) -> list[str]:
    missing = []
    if not common["symbol"]:
        missing.append("symbol")
    if not common["side"]:
        missing.append("side")
    if common["entry_price"] is None:
        missing.append("entry_price")
    if opened_at is None:
        missing.append("opened_at")
    return missing


# ---------------------------------------------------------------------------
# Snapshot mapping
# ---------------------------------------------------------------------------
_BALANCE_KEYS = ("balance", "accountBalance", "projectedBalance")
_EQUITY_KEYS = ("equity", "accountEquity", "projectedEquity")


def map_account_snapshot(
    details: dict[str, Any], timestamp: datetime | None = None
) -> MappedSnapshot | None:
    """Map account-details fields into a balance/equity snapshot candidate.

    ``details`` should be a flat dict of account-detail fields (already parsed from
    the table config). Returns ``None`` when no balance figure is present.
    """
    warnings: list[str] = []
    balance = _to_float(_first(details, _BALANCE_KEYS))
    equity = _to_float(_first(details, _EQUITY_KEYS))
    if balance is None:
        if equity is None:
            return None
        # Equity present but no balance — use equity as balance and warn.
        balance = equity
        warnings.append("account snapshot: no balance field; used equity as balance.")
    return MappedSnapshot(
        balance=balance,
        equity=equity,
        timestamp=timestamp,
        warnings=warnings,
    )


def account_details_to_dict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse account-details rows into a single flat dict.

    The account-state endpoint sometimes returns a single row of values keyed by
    the ``accountDetailsConfig`` columns; sometimes a list of ``{id, value}`` pairs.
    This normalizes both into one dict.
    """
    flat: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        # {id/name/key: ..., value: ...} pair form.
        if "value" in row and any(k in row for k in ("id", "name", "key")):
            key = row.get("id") or row.get("name") or row.get("key")
            if key is not None:
                flat[str(key)] = row["value"]
        else:
            flat.update(row)
    return flat


def normalize_side_value(value: Any) -> str | None:
    """Public helper: normalize a side value to BUY/SELL (or None)."""
    result = normalize_side(value)
    if result in (Side.BUY.value, Side.SELL.value):
        return result
    return None
