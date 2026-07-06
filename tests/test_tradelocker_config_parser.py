"""Tests for the tolerant config/table parser."""

from __future__ import annotations

from trading_journal.connectors.tradelocker.config_parser import (
    columns_from_section,
    instruments_from_config,
    parse_table,
    rows_to_dicts,
    unwrap_envelope,
)


def test_columns_from_section_variants():
    assert columns_from_section({"columns": [{"id": "a"}, {"id": "b"}]}) == ["a", "b"]
    assert columns_from_section([{"id": "x"}, {"id": "y"}]) == ["x", "y"]
    assert columns_from_section(["p", "q"]) == ["p", "q"]
    assert columns_from_section(None) is None
    assert columns_from_section({"columns": []}) is None


def test_parse_table_maps_array_rows_using_columns():
    payload = {"d": {"positions": [["1001", "buy", "0.10"], ["1002", "sell", "0.20"]]}}
    columns = ["id", "side", "qty"]
    rows = parse_table(payload, columns, row_keys=("positions",), context="positions")
    assert rows == [
        {"id": "1001", "side": "buy", "qty": "0.10"},
        {"id": "1002", "side": "sell", "qty": "0.20"},
    ]


def test_parse_table_passes_through_list_of_dicts():
    payload = {"d": {"positions": [{"id": "1", "side": "buy"}]}}
    rows = parse_table(payload, ["id", "side"], row_keys=("positions",), context="positions")
    assert rows == [{"id": "1", "side": "buy"}]


def test_parse_table_missing_columns_falls_back_and_warns():
    payload = {"d": {"positions": [["1001", "buy"]]}}
    warnings: list[str] = []
    rows = parse_table(
        payload, None, row_keys=("positions",), context="positions", warnings=warnings
    )
    assert rows == [{"col_0": "1001", "col_1": "buy"}]
    assert any("positional keys" in w for w in warnings)


def test_parse_table_handles_bare_list_payload():
    payload = [{"id": "1"}, {"id": "2"}]
    rows = parse_table(payload, None, row_keys=("positions",), context="x")
    assert rows == [{"id": "1"}, {"id": "2"}]


def test_rows_to_dicts_preserves_extra_cells():
    rows = rows_to_dicts([["a", "b", "c"]], ["one", "two"], context="ctx")
    assert rows == [{"one": "a", "two": "b", "extra_2": "c"}]


def test_unwrap_envelope():
    assert unwrap_envelope({"s": "ok", "d": {"x": 1}}) == {"x": 1}
    assert unwrap_envelope({"x": 1}) == {"x": 1}
    assert unwrap_envelope([1, 2]) == [1, 2]


def test_instruments_from_config():
    payload = {"d": {"instruments": [{"tradableInstrumentId": "278", "name": "EURUSD"}]}}
    assert instruments_from_config(payload) == {"278": "EURUSD"}
