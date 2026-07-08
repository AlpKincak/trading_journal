# Graph Report - trading_journal  (2026-07-06)

## Corpus Check
- 23 files · ~12,670 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 348 nodes · 804 edges · 13 communities (11 shown, 2 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 91 edges (avg confidence: 0.75)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9bd49529`
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

## God Nodes (most connected - your core abstractions)
1. `compute_metrics()` - 27 edges
2. `compute_journal_score()` - 20 edges
3. `get_or_create_default_account()` - 19 edges
4. `parse_trades_frame()` - 16 edges
5. `Trade` - 16 edges
6. `_cmd_metrics()` - 15 edges
7. `_parse_row()` - 15 edges
8. `get_settings()` - 14 edges
9. `session_scope()` - 14 edges
10. `TradeMetrics` - 14 edges

## Surprising Connections (you probably didn't know these)
- `test_normalize_columns_maps_aliases()` --calls--> `normalize_columns()`  [INFERRED]
  tests/test_csv_importer.py → src/trading_journal/importers/csv_importer.py
- `test_missing_stop_produces_warning_but_imports()` --calls--> `parse_trades_frame()`  [INFERRED]
  tests/test_csv_importer.py → src/trading_journal/importers/csv_importer.py
- `test_parse_messy_numbers_and_dollar_signs()` --calls--> `parse_trades_frame()`  [INFERRED]
  tests/test_csv_importer.py → src/trading_journal/importers/csv_importer.py
- `test_parse_normalizes_side_status_and_derives_rr()` --calls--> `parse_trades_frame()`  [INFERRED]
  tests/test_csv_importer.py → src/trading_journal/importers/csv_importer.py
- `test_validation_reports_missing_required_fields()` --calls--> `parse_trades_frame()`  [INFERRED]
  tests/test_csv_importer.py → src/trading_journal/importers/csv_importer.py

## Import Cycles
- None detected.

## Communities (13 total, 2 thin omitted)

### Community 0 - "trade_service.py"
Cohesion: 0.09
Nodes (40): BaseModel, date, A single trade (open or closed)., Trade, get_or_create_default_account(), ManualSnapshotInput, Validated input for a manually-entered account snapshot (UI form)., Return the first account, creating a local demo account if none exist. (+32 more)

### Community 1 - "account_service.py"
Cohesion: 0.07
Nodes (37): DeclarativeBase, _as_bool(), get_settings(), _load_dotenv(), Path, Application configuration.  Configuration is intentionally small and environment, Populate ``os.environ`` from a simple ``.env`` file if present.      This is a t, Resolved application settings. (+29 more)

### Community 2 - "metrics.py"
Cohesion: 0.08
Nodes (32): daily_pnl_frame(), _ensure_dataframe(), _is_missing(), latest_account_values(), _max_drawdown(), _mean_or_none(), _profit_factor(), Any (+24 more)

### Community 3 - "parse_trades_frame"
Cohesion: 0.10
Nodes (29): import_csv(), import_parsed(), ImportResult, normalize_columns(), parse_trades_csv(), parse_trades_frame(), ParsedImport, DataFrame (+21 more)

### Community 4 - "streamlit_app.py"
Cohesion: 0.12
Nodes (30): Engine, sessionmaker, get_engine(), get_session_factory(), Session, Database engine, session management, and schema creation helpers., Return a cached SQLAlchemy engine for the configured database., Return a cached session factory bound to the engine. (+22 more)

### Community 5 - "journal_score.py"
Cohesion: 0.13
Nodes (31): _completeness_component(), compute_journal_score(), JournalScore, _nonempty_string_mask(), _overall_confidence(), _performance_component(), _price_r_computable(), Any (+23 more)

### Community 6 - "compute_metrics"
Cohesion: 0.12
Nodes (31): compute_metrics(), compute_planned_rr(), compute_realized_r(), Planned reward-to-risk ratio from price distances.      BUY:  risk = entry - sto, Realized R multiple and the method used to derive it.      Preference order:, Compute all dashboard metrics from trades (+ optional snapshots).      ``trades`, _component(), make_trade() (+23 more)

### Community 7 - "csv_importer.py"
Cohesion: 0.16
Nodes (24): _clean_str(), _coerce_date(), _get(), _normalize_header(), _normalize_side(), _normalize_status(), _parse_row(), Any (+16 more)

### Community 8 - "cli.py"
Cohesion: 0.18
Nodes (23): ArgumentParser, Namespace, build_parser(), _cmd_dashboard(), _cmd_import_csv(), _cmd_init_db(), _cmd_metrics(), _cmd_seed_demo() (+15 more)

### Community 9 - "trading_journal"
Cohesion: 0.12
Nodes (16): Data model, Development, Import your own CSV, Journal Score (transparent, local — NOT the Zella Score), Metric formulas, Phase 2 (planned), Planned RR (reward-to-risk from price), Print metrics without the UI (+8 more)

### Community 10 - "charts.py"
Cohesion: 0.27
Nodes (14): Figure, calendar_heatmap(), cumulative_pnl_line(), daily_pnl_bar(), equity_line(), DataFrame, Plotly chart builders for the dashboard.  Pure functions: each takes a DataFrame, Balance and equity over time from account snapshots. (+6 more)

## Knowledge Gaps
- **13 isolated node(s):** `trading_journal`, `What Phase 1 includes`, `What is intentionally NOT included (Phase 1 scope)`, `Seed demo data`, `Import your own CSV` (+8 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `compute_metrics()` connect `compute_metrics` to `cli.py`, `metrics.py`, `streamlit_app.py`, `journal_score.py`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `get_or_create_default_account()` connect `trade_service.py` to `account_service.py`, `parse_trades_frame`, `streamlit_app.py`, `csv_importer.py`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Why does `Trade` connect `trade_service.py` to `account_service.py`, `metrics.py`, `parse_trades_frame`, `csv_importer.py`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `compute_metrics()` (e.g. with `render_dashboard()` and `test_avg_planned_rr_includes_open_and_closed()`) actually correct?**
  _`compute_metrics()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `compute_journal_score()` (e.g. with `render_dashboard()` and `test_journal_score_components_full()`) actually correct?**
  _`compute_journal_score()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `get_or_create_default_account()` (e.g. with `render_import()` and `test_duplicate_prevention_across_imports()`) actually correct?**
  _`get_or_create_default_account()` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `parse_trades_frame()` (e.g. with `render_import()` and `test_duplicate_prevention_across_imports()`) actually correct?**
  _`parse_trades_frame()` has 7 INFERRED edges - model-reasoned connections that need verification._