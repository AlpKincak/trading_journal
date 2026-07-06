"""Tolerant parsing of TradeLocker "table" responses.

TradeLocker frequently returns tabular data as arrays of arrays, where the column
order is described separately in ``/trade/config`` (e.g. ``positionsConfig``,
``ordersHistoryConfig``). This module turns those into lists of dicts so the
mapper can work with named fields regardless of the wire shape.

Design goals (per the Phase 2 brief):
* If a response is already ``list[dict]`` → pass it through unchanged.
* If it is ``list[list]`` and we know the columns → zip them into dicts.
* If columns are missing → fall back to positional keys and **warn** (never
  silently corrupt).
* Be tolerant of extra/short rows and of envelope wrappers like ``{"d": {...}}``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def unwrap_envelope(payload: Any) -> Any:
    """Return the meaningful body of a response.

    TradeLocker wraps most payloads as ``{"s": "ok", "d": <body>}``. When present,
    the ``d`` body is returned; otherwise the payload is returned unchanged.
    """
    if isinstance(payload, dict) and "d" in payload:
        return payload["d"]
    return payload


def find_rows(body: Any, row_keys: Sequence[str]) -> list[Any]:
    """Locate the row collection inside a (possibly nested) body.

    ``body`` may itself be a list, or a dict holding the rows under one of
    ``row_keys`` (e.g. ``positions``, ``ordersHistory``). Returns ``[]`` when no
    list is found.
    """
    if isinstance(body, list):
        return list(body)
    if isinstance(body, dict):
        for key in row_keys:
            value = body.get(key)
            if isinstance(value, list):
                return list(value)
        # Fall back to the first list-valued entry, if any.
        for value in body.values():
            if isinstance(value, list):
                return list(value)
    return []


def columns_from_section(section: Any) -> list[str] | None:
    """Extract an ordered list of column ids from a config section.

    Accepts the common shapes:
    * ``{"columns": [{"id": "x"}, {"id": "y"}]}``
    * ``[{"id": "x"}, {"id": "y"}]``
    * ``["x", "y"]``
    """
    if section is None:
        return None
    columns = section.get("columns") if isinstance(section, dict) else section
    if not isinstance(columns, list) or not columns:
        return None

    ids: list[str] = []
    for col in columns:
        if isinstance(col, str):
            ids.append(col)
        elif isinstance(col, dict):
            cid = col.get("id") or col.get("name") or col.get("key")
            if cid is None:
                return None
            ids.append(str(cid))
        else:
            return None
    return ids


def rows_to_dicts(
    rows: Sequence[Any],
    columns: list[str] | None,
    *,
    context: str,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Convert raw rows to dicts, using ``columns`` for array rows.

    * ``dict`` rows pass through (copied).
    * ``list``/``tuple`` rows are zipped with ``columns``. Extra cells beyond the
      known columns are preserved under ``extra_<index>`` keys so nothing is lost.
    * When ``columns`` is unknown but rows are arrays, positional keys are used and
      a single warning is emitted for ``context``.
    """
    warn = warnings if warnings is not None else []
    out: list[dict[str, Any]] = []
    warned_missing_columns = False

    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
            continue
        if isinstance(row, (list, tuple)):
            if columns:
                record: dict[str, Any] = {}
                for i, value in enumerate(row):
                    key = columns[i] if i < len(columns) else f"extra_{i}"
                    record[key] = value
                out.append(record)
            else:
                if not warned_missing_columns:
                    warn.append(
                        f"{context}: array rows received but no column config was "
                        f"available; falling back to positional keys (col_0, col_1, …). "
                        f"Field mapping may be unreliable."
                    )
                    warned_missing_columns = True
                out.append({f"col_{i}": value for i, value in enumerate(row)})
        else:
            warn.append(f"{context}: skipped unexpected row of type {type(row).__name__}")
    return out


def parse_table(
    payload: Any,
    columns: list[str] | None,
    *,
    row_keys: Sequence[str],
    context: str,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """End-to-end: unwrap envelope, find rows, and convert to dicts."""
    body = unwrap_envelope(payload)
    rows = find_rows(body, row_keys)
    return rows_to_dicts(rows, columns, context=context, warnings=warnings)


def instruments_from_config(payload: Any) -> dict[str, str]:
    """Best-effort map of tradable-instrument id -> human symbol name.

    Looks for an ``instruments`` list in the config body; tolerant of unknown
    shapes (returns ``{}`` when nothing usable is found).
    """
    body = unwrap_envelope(payload)
    rows = find_rows(body, ("instruments",)) if isinstance(body, dict) else []
    mapping: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        inst_id = row.get("tradableInstrumentId") or row.get("id") or row.get("routeId")
        name = row.get("name") or row.get("symbol") or row.get("title")
        if inst_id is not None and name:
            mapping[str(inst_id)] = str(name)
    return mapping
