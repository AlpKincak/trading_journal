# Graph Report - trading_journal  (2026-07-08)

## Corpus Check
- 56 files · ~39,385 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 975 nodes · 2468 edges · 31 communities (28 shown, 3 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 367 edges (avg confidence: 0.73)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c450bb24`
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
- [[_COMMUNITY_DailyReviewInput|DailyReviewInput]]
- [[_COMMUNITY_data_quality_report|data_quality_report]]
- [[_COMMUNITY_TradeLockerReadOnlyClient|TradeLockerReadOnlyClient]]
- [[_COMMUNITY_trades_view.py|trades_view.py]]
- [[_COMMUNITY_TradeLockerSettings|TradeLockerSettings]]
- [[_COMMUNITY_sync_service.py|sync_service.py]]
- [[_COMMUNITY_streamlit_app.py|streamlit_app.py]]

## God Nodes (most connected - your core abstractions)
1. `session_scope()` - 41 edges
2. `TradeLockerReadOnlyClient` - 35 edges
3. `Trade` - 34 edges
4. `TradeLockerSyncService` - 31 edges
5. `get_or_create_default_account()` - 30 edges
6. `compute_metrics()` - 28 edges
7. `compute_risk_analytics()` - 27 edges
8. `SyncResult` - 25 edges
9. `apply_manual_correction()` - 25 edges
10. `TradeEditInput` - 24 edges

## Surprising Connections (you probably didn't know these)
- `test_health_check_reports_missing_credentials_safely()` --calls--> `TradeLockerReadOnlyClient`  [INFERRED]
  tests/test_tradelocker_client.py → src/trading_journal/connectors/tradelocker/client.py
- `test_missing_credentials_raises_config_error()` --calls--> `TradeLockerReadOnlyClient`  [INFERRED]
  tests/test_tradelocker_client.py → src/trading_journal/connectors/tradelocker/client.py
- `isolated_db()` --calls--> `reset_engine_cache()`  [INFERRED]
  tests/test_cli_phase3.py → src/trading_journal/db.py
- `test_day_detail_empty_is_safe()` --calls--> `day_detail()`  [INFERRED]
  tests/test_review_service.py → src/trading_journal/metrics.py
- `test_empty_analytics_is_safe()` --calls--> `compute_risk_analytics()`  [INFERRED]
  tests/test_analytics.py → src/trading_journal/analytics.py

## Import Cycles
- None detected.

## Communities (31 total, 3 thin omitted)

### Community 0 - "trade_service.py"
Cohesion: 0.09
Nodes (38): BaseModel, Account, AccountSnapshot, A trading account (broker + base currency)., A point-in-time balance/equity reading for an account., add_snapshot(), get_or_create_default_account(), latest_snapshot() (+30 more)

### Community 1 - "account_service.py"
Cohesion: 0.18
Nodes (24): Exception, HealthCheckResult, HttpRequest, HttpResponse, Read-only TradeLocker REST client.  Safety model ------------ * All HTTP goes th, Default transport backed by the ``requests`` library., RequestsTransport, Typed errors for the TradeLocker connector.  All messages are constructed from s (+16 more)

### Community 2 - "metrics.py"
Cohesion: 0.16
Nodes (18): All non-strategy analytics for a set of trades., RiskAnalytics, DayDetail, _profit_factor(), Metric calculations for the trading journal.  This module contains two layers:, Per-day summary used by the Calendar/Reviews day-detail panel., gross_profit / abs(gross_loss).      * ``inf`` when there are profits but no los, All dashboard metrics for a set of trades. (+10 more)

### Community 3 - "parse_trades_frame"
Cohesion: 0.06
Nodes (63): _clean_str(), _coerce_date(), _coerce_float(), _get(), import_csv(), import_parsed(), ImportResult, normalize_columns() (+55 more)

### Community 4 - "streamlit_app.py"
Cohesion: 0.08
Nodes (46): sessionmaker, trading_journal: a local, TradeZella-lite forex trading journal.  Phase 1: local, BackupInfo, build_export_dict(), _build_manifest(), create_backup(), export_csv(), export_json() (+38 more)

### Community 5 - "journal_score.py"
Cohesion: 0.17
Nodes (26): _completeness_component(), compute_journal_score(), _daily_review_component(), JournalScore, _nonempty_string_mask(), _overall_confidence(), _performance_component(), Any (+18 more)

### Community 6 - "compute_metrics"
Cohesion: 0.12
Nodes (32): compute_metrics(), compute_planned_rr(), compute_realized_r(), Planned reward-to-risk ratio from price distances.      BUY:  risk = entry - sto, Realized R multiple and the method used to derive it.      Preference order:, Compute all dashboard metrics from trades (+ optional snapshots).      ``trades`, _component(), make_trade() (+24 more)

### Community 7 - "csv_importer.py"
Cohesion: 0.09
Nodes (49): account_details_to_dict(), aggregate_position_legs(), composite_dedup_key(), _fees_from(), _first(), _looks_numeric(), map_account(), map_account_snapshot() (+41 more)

### Community 8 - "cli.py"
Cohesion: 0.06
Nodes (79): ArgumentParser, Engine, Namespace, build_parser(), _cmd_add_trade(), _cmd_backup(), _cmd_dashboard(), _cmd_data_quality() (+71 more)

### Community 9 - "trading_journal"
Cohesion: 0.06
Nodes (35): Add / review / correct trades without the UI, Analytics (non-strategy), Back up and export your data, Backup, export & restore, Corrections survive TradeLocker resyncs, Daily reviews, Data model, Data quality & the Needs-Review queue (+27 more)

### Community 10 - "charts.py"
Cohesion: 0.19
Nodes (21): Figure, calendar_heatmap(), cumulative_pnl_line(), cumulative_r_line(), daily_pnl_bar(), equity_line(), planned_rr_hist(), DataFrame (+13 more)

### Community 13 - "TradeLockerSyncService"
Cohesion: 0.10
Nodes (17): MappedTrade, A single trade (open or closed)., Trade, Any, datetime, Session, Fold another result's counts/messages into this one (for --all)., Orchestrates a read-only TradeLocker sync into the local database. (+9 more)

### Community 14 - "tradelocker_fakes.py"
Cohesion: 0.09
Nodes (22): Tests for the read-only TradeLocker client (offline, via a fake transport)., Belt-and-braces: the public client must not expose any trading operations., test_connector_exposes_no_write_methods(), test_health_check_reports_missing_credentials_safely(), test_missing_credentials_raises_config_error(), account_state_response(), accounts_response(), auth_response() (+14 more)

### Community 15 - "sync_service.py"
Cohesion: 0.14
Nodes (24): _parse_config(), columns_from_section(), find_rows(), instruments_from_config(), parse_table(), Any, Tolerant parsing of TradeLocker "table" responses.  TradeLocker frequently retur, End-to-end: unwrap envelope, find rows, and convert to dicts. (+16 more)

### Community 16 - "test_tradelocker_cli.py"
Cohesion: 0.09
Nodes (22): Clear cached engine/session factory.      Useful in tests that swap the database, reset_engine_cache(), _clean_env(), empty_app(), AppTest coverage for the Phase 3 tabs (empty and seeded databases)., seeded_app(), isolated_db(), _patch_connector() (+14 more)

### Community 17 - "_to_float"
Cohesion: 0.16
Nodes (19): daily_pnl_frame(), daily_r_frame(), day_detail(), _ensure_dataframe(), latest_account_values(), _max_drawdown(), Any, DataFrame (+11 more)

### Community 18 - "sync_state_service.py"
Cohesion: 0.16
Nodes (18): DeclarativeBase, Base, A record of one broker-sync attempt (audit trail for the Sync tab/CLI)., Declarative base for all models., A key/value cursor for incremental sync (e.g. last history timestamp).      Scop, SyncRun, SyncState, _find_state() (+10 more)

### Community 19 - "test_tradelocker_sync_service.py"
Cohesion: 0.06
Nodes (75): MistakeCategory, normalize_mistake_category(), normalize_review_status(), Map a free-form review status to the canonical vocabulary (or None)., Map a free-form mistake category to the canonical vocabulary (or None).      An, Generic, non-strategy-specific journaling categories for review.      These desc, add_data_quality_flag(), _apply_filters() (+67 more)

### Community 20 - "endpoints.py"
Cohesion: 0.17
Nodes (11): account_state(), instruments(), orders(), orders_history(), positions(), Centralized TradeLocker REST endpoint paths.  Every path the connector may touch, Account details/balance/equity snapshot for one account., Currently open positions for one account. (+3 more)

### Community 21 - "_risk_tracked"
Cohesion: 0.28
Nodes (9): _price_r_computable(), Series, True when a price-based R could be derived for this (closed) trade., True when risk is knowable: a recorded risk amount or a computable price R., _risk_tracked(), _is_missing(), Best-effort float conversion; returns None for missing/invalid values., True if the value is None or NaN. (+1 more)

### Community 22 - "compute_planned_rr"
Cohesion: 0.11
Nodes (35): compute_risk_analytics(), _duration_hours(), _group_performance(), _median_or_none(), Any, DataFrame, Series, Non-strategy risk & R analytics for the Analytics tab.  Everything here is gener (+27 more)

### Community 24 - "DailyReviewInput"
Cohesion: 0.09
Nodes (34): DailyReview, A generic daily review note with optional self-scores (0-100).      Not strategy, _coerce_date(), daily_reviews_dataframe(), DailyReviewInput, delete_daily_review(), get_daily_review(), list_daily_reviews() (+26 more)

### Community 25 - "data_quality_report"
Cohesion: 0.15
Nodes (29): _closed_mask(), data_quality_report(), duplicate_like_ids(), _has_sync_conflict(), _invalid_planned_rr_mask(), needs_review_frame(), Any, DataFrame (+21 more)

### Community 26 - "TradeLockerReadOnlyClient"
Cohesion: 0.17
Nodes (16): _coerce_datetime(), _date_range_params(), _parse_accounts(), _parse_auth_tokens(), _parse_expiry(), Any, datetime, A strictly read-only TradeLocker API client. (+8 more)

### Community 27 - "trades_view.py"
Cohesion: 0.13
Nodes (27): distinct_symbols(), get_trade(), Fetch a single trade by id (or None)., Distinct symbols present, for populating UI filters., load_accounts(), load_snapshots(), load_symbols(), load_trades() (+19 more)

### Community 28 - "TradeLockerSettings"
Cohesion: 0.13
Nodes (7): Resolved TradeLocker connector settings.      ``password`` is a secret: it is ex, Base URL for backend API calls (``<base_url>/backend-api``)., Email with the local part partly masked (safe for display)., TradeLockerSettings, FakeTransport, A transport that answers canned responses and records every request.      ``rout, Transport

### Community 29 - "sync_service.py"
Cohesion: 0.18
Nodes (8): AuthTokens, Lightweight, API-facing data structures for the TradeLocker connector.  These de, JWT auth material. Token strings are excluded from ``repr`` (secrets)., Parsed ``/trade/config`` response.      ``sections`` maps a config-section name, TradeLockerConfig, Outcome of a broker sync run., SyncStatus, Read-only TradeLocker sync orchestration.  ``TradeLockerSyncService`` ties toget

### Community 30 - "streamlit_app.py"
Cohesion: 0.36
Nodes (7): Streamlit dashboard for the trading journal.  Run with:  ``streamlit run src/tra, Show the TradeLocker config summary (no secrets) and return the settings., render_dashboard(), render_journal_score(), render_sync(), _render_sync_config_summary(), _render_sync_result()

## Knowledge Gaps
- **30 isolated node(s):** `trading_journal`, `What Phase 1 includes`, `What Phase 3 adds`, `What is intentionally NOT included`, `Seed demo data` (+25 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TradeLockerReadOnlyClient` connect `TradeLockerReadOnlyClient` to `account_service.py`, `cli.py`, `tradelocker_fakes.py`, `TradeLockerSettings`, `sync_service.py`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `Trade` connect `TradeLockerSyncService` to `trade_service.py`, `metrics.py`, `parse_trades_frame`, `streamlit_app.py`, `sync_state_service.py`, `test_tradelocker_sync_service.py`, `trades_view.py`, `sync_service.py`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `SyncResult` connect `TradeLockerSyncService` to `cli.py`, `sync_service.py`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `session_scope()` (e.g. with `_render_backup_export()` and `_render_restore()`) actually correct?**
  _`session_scope()` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `TradeLockerReadOnlyClient` (e.g. with `TradeLockerAuthError` and `TradeLockerConfigError`) actually correct?**
  _`TradeLockerReadOnlyClient` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `get_or_create_default_account()` (e.g. with `render_import()` and `_render_add_trade()`) actually correct?**
  _`get_or_create_default_account()` has 17 INFERRED edges - model-reasoned connections that need verification._
- **What connects `trading_journal`, `trading_journal: a local, TradeZella-lite forex trading journal.  Phase 1: local`, `Non-strategy risk & R analytics for the Analytics tab.  Everything here is gener` to the rest of the system?**
  _273 weakly-connected nodes found - possible documentation gaps or missing edges._