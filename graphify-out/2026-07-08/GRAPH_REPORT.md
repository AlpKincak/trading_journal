# Graph Report - trading_journal  (2026-07-06)

## Corpus Check
- 40 files · ~26,642 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 681 nodes · 1645 edges · 24 communities (21 shown, 3 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 177 edges (avg confidence: 0.68)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `05dbd58f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_trade_service.py|trade_service.py]]
- [[_COMMUNITY_account_service.py|account_service.py]]
- [[_COMMUNITY_metrics.py|metrics.py]]
- [[_COMMUNITY_parse_trades_frame|parse_trades_frame]]
- [[_COMMUNITY_streamlit_app.py|streamlit_app.py]]
- [[_COMMUNITY_journal_score.py|journal_score.py]]
- [[_COMMUNITY_compute_metrics|compute_metrics]]
- [[_COMMUNITY_csv_importer.py|csv_importer.py]]
- [[_COMMUNITY_cli.py|cli.py]]
- [[_COMMUNITY_trading_journal|trading_journal]]
- [[_COMMUNITY_charts.py|charts.py]]
- [[_COMMUNITY___init__.py|__init__.py]]
- [[_COMMUNITY_trading_journal|trading_journal]]
- [[_COMMUNITY_TradeLockerSyncService|TradeLockerSyncService]]
- [[_COMMUNITY_tradelocker_fakes.py|tradelocker_fakes.py]]
- [[_COMMUNITY_sync_service.py|sync_service.py]]
- [[_COMMUNITY_test_tradelocker_cli.py|test_tradelocker_cli.py]]
- [[_COMMUNITY__to_float|_to_float]]
- [[_COMMUNITY_sync_state_service.py|sync_state_service.py]]
- [[_COMMUNITY_test_tradelocker_sync_service.py|test_tradelocker_sync_service.py]]
- [[_COMMUNITY_endpoints.py|endpoints.py]]
- [[_COMMUNITY__risk_tracked|_risk_tracked]]
- [[_COMMUNITY_compute_planned_rr|compute_planned_rr]]
- [[_COMMUNITY___init__.py|__init__.py]]

## God Nodes (most connected - your core abstractions)
1. `TradeLockerReadOnlyClient` - 35 edges
2. `TradeLockerSyncService` - 29 edges
3. `compute_metrics()` - 27 edges
4. `SyncResult` - 23 edges
5. `compute_journal_score()` - 20 edges
6. `Trade` - 20 edges
7. `get_or_create_default_account()` - 20 edges
8. `session_scope()` - 19 edges
9. `TradeLockerError` - 18 edges
10. `map_closed_order()` - 18 edges

## Surprising Connections (you probably didn't know these)
- `test_health_check_reports_missing_credentials_safely()` --calls--> `TradeLockerReadOnlyClient`  [INFERRED]
  tests/test_tradelocker_client.py → src/trading_journal/connectors/tradelocker/client.py
- `test_missing_credentials_raises_config_error()` --calls--> `TradeLockerReadOnlyClient`  [INFERRED]
  tests/test_tradelocker_client.py → src/trading_journal/connectors/tradelocker/client.py
- `FakeTransport` --uses--> `TradeLockerSettings`  [INFERRED]
  tests/tradelocker_fakes.py → src/trading_journal/config.py
- `FakeTransport` --uses--> `HttpRequest`  [INFERRED]
  tests/tradelocker_fakes.py → src/trading_journal/connectors/tradelocker/client.py
- `FakeTransport` --uses--> `HttpResponse`  [INFERRED]
  tests/tradelocker_fakes.py → src/trading_journal/connectors/tradelocker/client.py

## Import Cycles
- None detected.

## Communities (24 total, 3 thin omitted)

### Community 0 - "trade_service.py"
Cohesion: 0.06
Nodes (58): BaseModel, date, DeclarativeBase, Account, AccountSnapshot, Base, A trading account (broker + base currency)., A point-in-time balance/equity reading for an account. (+50 more)

### Community 1 - "account_service.py"
Cohesion: 0.09
Nodes (46): Exception, _coerce_datetime(), _date_range_params(), HealthCheckResult, HttpRequest, HttpResponse, _parse_accounts(), _parse_auth_tokens() (+38 more)

### Community 2 - "metrics.py"
Cohesion: 0.11
Nodes (21): _mean_or_none(), _profit_factor(), Series, Metric calculations for the trading journal.  This module contains two layers:, Sum of a series treating NaN as 0 (empty sum is 0.0)., gross_profit / abs(gross_loss).      * ``inf`` when there are profits but no los, All dashboard metrics for a set of trades., Series of net P&L per trading day, indexed by date. (+13 more)

### Community 3 - "parse_trades_frame"
Cohesion: 0.06
Nodes (61): _clean_str(), _coerce_date(), _coerce_float(), _get(), import_csv(), import_parsed(), ImportResult, normalize_columns() (+53 more)

### Community 4 - "streamlit_app.py"
Cohesion: 0.40
Nodes (4): sessionmaker, Shared pytest fixtures., A SQLAlchemy session bound to an isolated temp-file SQLite database.      A temp, session()

### Community 5 - "journal_score.py"
Cohesion: 0.20
Nodes (20): _completeness_component(), compute_journal_score(), JournalScore, _nonempty_string_mask(), _overall_confidence(), _performance_component(), Any, DataFrame (+12 more)

### Community 6 - "compute_metrics"
Cohesion: 0.15
Nodes (26): compute_metrics(), compute_realized_r(), Realized R multiple and the method used to derive it.      Preference order:, Compute all dashboard metrics from trades (+ optional snapshots).      ``trades`, _component(), make_trade(), Tests for the metrics engine, R/RR calculations, and Journal Score., Build a closed-trade dict with sensible defaults for metric tests. (+18 more)

### Community 7 - "csv_importer.py"
Cohesion: 0.10
Nodes (49): account_details_to_dict(), aggregate_position_legs(), composite_dedup_key(), _fees_from(), _first(), _looks_numeric(), map_account(), map_account_snapshot() (+41 more)

### Community 8 - "cli.py"
Cohesion: 0.05
Nodes (79): ArgumentParser, Engine, Namespace, build_parser(), _cmd_dashboard(), _cmd_import_csv(), _cmd_init_db(), _cmd_metrics() (+71 more)

### Community 9 - "trading_journal"
Cohesion: 0.08
Nodes (23): Data model, Data safety rules, Design, Development, How to run, Idempotency & safe updates, Import your own CSV, Journal Score (transparent, local — NOT the Zella Score) (+15 more)

### Community 10 - "charts.py"
Cohesion: 0.27
Nodes (14): Figure, calendar_heatmap(), cumulative_pnl_line(), daily_pnl_bar(), equity_line(), DataFrame, Plotly chart builders for the dashboard.  Pure functions: each takes a DataFrame, Balance and equity over time from account snapshots. (+6 more)

### Community 13 - "TradeLockerSyncService"
Cohesion: 0.13
Nodes (13): MappedTrade, Any, Session, Fold another result's counts/messages into this one (for --all)., Orchestrates a read-only TradeLocker sync into the local database., Discover TradeLocker accounts and upsert their metadata only., Full read-only sync of one account: metadata, positions, history, balance., Discover every account and sync each one. (+5 more)

### Community 14 - "tradelocker_fakes.py"
Cohesion: 0.08
Nodes (24): Tests for the read-only TradeLocker client (offline, via a fake transport)., Belt-and-braces: the public client must not expose any trading operations., test_connector_exposes_no_write_methods(), test_health_check_reports_missing_credentials_safely(), test_missing_credentials_raises_config_error(), account_state_response(), accounts_response(), auth_response() (+16 more)

### Community 15 - "sync_service.py"
Cohesion: 0.11
Nodes (28): _parse_config(), columns_from_section(), find_rows(), instruments_from_config(), parse_table(), Any, Tolerant parsing of TradeLocker "table" responses.  TradeLocker frequently retur, End-to-end: unwrap envelope, find rows, and convert to dicts. (+20 more)

### Community 16 - "test_tradelocker_cli.py"
Cohesion: 0.12
Nodes (18): Clear cached engine/session factory.      Useful in tests that swap the database, reset_engine_cache(), isolated_db(), _patch_connector(), Tests for the TradeLocker CLI commands (offline, isolated DB)., Point the app database at a throwaway file for the duration of a test., Wire the CLI to a fake-transport-backed client + settings., test_accounts_lists_without_secrets() (+10 more)

### Community 17 - "_to_float"
Cohesion: 0.17
Nodes (17): daily_pnl_frame(), _ensure_dataframe(), _is_missing(), latest_account_values(), _max_drawdown(), Any, DataFrame, Convert Trade ORM objects (or dicts) into a normalized DataFrame. (+9 more)

### Community 18 - "sync_state_service.py"
Cohesion: 0.22
Nodes (13): A record of one broker-sync attempt (audit trail for the Sync tab/CLI)., A key/value cursor for incremental sync (e.g. last history timestamp).      Scop, SyncRun, SyncState, _find_state(), get_sync_state(), datetime, Session (+5 more)

### Community 19 - "test_tradelocker_sync_service.py"
Cohesion: 0.23
Nodes (15): Tests for the TradeLocker sync orchestration (idempotency, dry-run, upserts)., _service(), test_closed_history_converts_open_to_closed(), test_dry_run_writes_nothing(), test_idempotent_sync_does_not_duplicate(), test_local_accounts_are_not_touched_by_sync(), test_missing_credentials_propagate_as_config_error(), test_open_position_update_updates_mutable_fields() (+7 more)

### Community 20 - "endpoints.py"
Cohesion: 0.17
Nodes (11): account_state(), instruments(), orders(), orders_history(), positions(), Centralized TradeLocker REST endpoint paths.  Every path the connector may touch, Account details/balance/equity snapshot for one account., Currently open positions for one account. (+3 more)

### Community 21 - "_risk_tracked"
Cohesion: 0.50
Nodes (5): _price_r_computable(), Series, True when a price-based R could be derived for this (closed) trade., True when risk is knowable: a recorded risk amount or a computable price R., _risk_tracked()

### Community 22 - "compute_planned_rr"
Cohesion: 0.40
Nodes (5): compute_planned_rr(), Planned reward-to-risk ratio from price distances.      BUY:  risk = entry - sto, test_planned_rr_buy(), test_planned_rr_invalid_returns_none(), test_planned_rr_sell()

## Knowledge Gaps
- **19 isolated node(s):** `trading_journal`, `What Phase 1 includes`, `What is intentionally NOT included`, `Seed demo data`, `Import your own CSV` (+14 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TradeLockerReadOnlyClient` connect `account_service.py` to `cli.py`, `tradelocker_fakes.py`, `sync_service.py`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Why does `SyncResult` connect `TradeLockerSyncService` to `cli.py`, `sync_service.py`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Why does `compute_metrics()` connect `compute_metrics` to `cli.py`, `_to_float`, `metrics.py`, `journal_score.py`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `TradeLockerReadOnlyClient` (e.g. with `TradeLockerAuthError` and `TradeLockerConfigError`) actually correct?**
  _`TradeLockerReadOnlyClient` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `compute_metrics()` (e.g. with `render_dashboard()` and `test_avg_planned_rr_includes_open_and_closed()`) actually correct?**
  _`compute_metrics()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `compute_journal_score()` (e.g. with `render_dashboard()` and `test_journal_score_components_full()`) actually correct?**
  _`compute_journal_score()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `trading_journal`, `trading_journal: a local, TradeZella-lite forex trading journal.  Phase 1: local`, `Command-line interface: ``trading-journal <command>``.  Commands -------- * ``in` to the rest of the system?**
  _197 weakly-connected nodes found - possible documentation gaps or missing edges._