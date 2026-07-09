<h1 align="center">Trading Journal</h1>

<p align="center">
  <strong>A local-first forex trading journal with a Streamlit dashboard, CLI tools, CSV import, and optional read-only TradeLocker sync.</strong>
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Streamlit" src="https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white">
  <img alt="TradeLocker read-only" src="https://img.shields.io/badge/TradeLocker-read--only-2E7D32">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-blue">
</p>

Trading Journal is a small, single-user desktop-style app for reviewing forex
trades on your own machine. Import a CSV, seed the bundled demo data, or sync
TradeLocker data in read-only mode, then review performance, risk, data quality,
and journaling consistency without sending your trading records to a cloud service.

This is analysis software, not trading software. It never places, modifies,
cancels, or closes orders.

## Contents

- [What It Does](#what-it-does)
- [Current Scope](#current-scope)
- [Quick Start](#quick-start)
- [Dashboard](#dashboard)
- [CLI Commands](#cli-commands)
- [CSV Import](#csv-import)
- [TradeLocker Sync](#tradelocker-sync)
- [Metrics And Scoring](#metrics-and-scoring)
- [Data Storage And Privacy](#data-storage-and-privacy)
- [Project Layout](#project-layout)
- [Development](#development)
- [Limitations](#limitations)
- [License](#license)

## What It Does

| Area | Included |
| --- | --- |
| Dashboard | Streamlit app with KPIs, Plotly charts, trade tables, analytics, calendar reviews, import, sync, backup, and data-quality tabs. |
| Trade import | Flexible CSV importer with common column aliases, messy-number parsing, validation errors, warnings, and duplicate prevention. |
| Manual journaling | Add trades manually, edit/correct imported trades, record notes, review status, mistake category, exit reason, and daily reflections. |
| Risk analytics | Net P&L, win rate, day win rate, profit factor, expectancy, R multiples, planned RR, streaks, duration, drawdown, risk consistency, and split views. |
| Journal Score | Transparent local 0-100 score for data completeness, risk tracking, risk control, performance health, trade review, and daily-review consistency. |
| Broker sync | Optional read-only TradeLocker connector for accounts, open positions, closed history, and balance/equity snapshots. |
| Data portability | CSV export, JSON export, timestamped zip backups, and conservative restore that backs up the current DB first. |
| CLI | `trading-journal` command for setup, import, metrics, manual trades, reviews, data quality, sync, backup, export, and restore. |

## Current Scope

This repo is intentionally small and complete for its current purpose:

- Local, single-user SQLite app.
- Forex-focused trade journaling and review.
- CSV import plus optional TradeLocker read-only sync.
- No live trading or broker-side write actions.
- No cloud backend, authentication system, subscriptions, teams, or mobile app.
- No MT4, MT5, cTrader, or other broker connectors today.

Additional broker support could be added later, but the public promise of this
project is currently limited to CSV import and TradeLocker read-only sync.

## Quick Start

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e .

trading-journal init-db
trading-journal seed-demo
trading-journal dashboard
```

The default SQLite database is created at:

```text
data/trading_journal.db
```

You can override this with environment variables in `.env`:

```dotenv
TRADING_JOURNAL_DATA_DIR=data
TRADING_JOURNAL_DB_NAME=trading_journal.db
# TRADING_JOURNAL_DATABASE_URL=sqlite:///data/trading_journal.db
```

Use the bundled demo data to explore the app safely:

```bash
trading-journal seed-demo
```

The demo seed is idempotent, so running it more than once does not duplicate
trades or snapshots.

## Dashboard

Launch the dashboard with:

```bash
trading-journal dashboard
```

Or directly with Streamlit:

```bash
streamlit run src/trading_journal/ui/streamlit_app.py
```

Dashboard tabs:

| Tab | Purpose |
| --- | --- |
| Dashboard | KPIs, Journal Score, daily P&L, cumulative P&L, R distribution, and calendar heatmap. |
| Trades | Filter trades, inspect details, add manual trades, edit/correct fields, mark reviewed, and record review notes. |
| Analytics | Non-strategy risk and R analytics, including streaks, duration, risk consistency, and weekday/symbol/side splits. |
| Calendar / Reviews | Day-level trade summary and daily review notes with discipline, risk, and execution self-scores. |
| Import | Seed demo data or upload a trades CSV with preview, validation, and warnings before commit. |
| Sync | Read-only TradeLocker health check, account listing, dry-run sync, apply import, and recent sync runs. |
| Account / Backup | Account snapshots, CSV/JSON export, zip backup, and restore. |
| Help / Data Quality | Needs Review queue, missing/estimated data checks, R-method notes, Journal Score rubric, and safety notes. |

## CLI Commands

```bash
trading-journal --help
```

| Command | Description |
| --- | --- |
| `init-db` | Create or update the local SQLite schema. |
| `seed-demo` | Load bundled sample trades and account snapshots. |
| `import-csv PATH` | Import trades from a CSV file. |
| `add-trade` | Add a manual trade locally. |
| `metrics` | Print dashboard metrics in the terminal. |
| `review-day DATE` | Show a day summary and optionally save a daily review. |
| `data-quality` | Print data-quality checks and the Needs Review queue. |
| `tradelocker-health` | Check TradeLocker config/auth without printing secrets. |
| `tradelocker-accounts` | List available TradeLocker accounts. |
| `sync-tradelocker` | Sync TradeLocker data in read-only mode; dry-run unless `--apply` is passed. |
| `sync-status` | Show recent TradeLocker sync runs. |
| `export-csv` | Export logical tables as CSV files. |
| `export-json` | Export all logical tables to one JSON file. |
| `backup` | Create a timestamped zip backup containing DB, CSV, JSON, and manifest. |
| `restore-backup PATH` | Restore a backup zip after validation; requires `--yes` to overwrite. |
| `dashboard` | Launch the Streamlit app. |

Example manual trade:

```bash
trading-journal add-trade \
  --symbol EURUSD \
  --side buy \
  --status closed \
  --opened-at "2025-03-01 09:00" \
  --closed-at "2025-03-01 15:00" \
  --entry-price 1.1000 \
  --exit-price 1.1100 \
  --stop-loss 1.0950 \
  --gross-pnl 210 \
  --fees 10
```

Example daily review:

```bash
trading-journal review-day 2025-03-01 \
  --notes "Disciplined day" \
  --discipline 85 \
  --risk 80 \
  --execution 90
```

## CSV Import

Import from the CLI:

```bash
trading-journal import-csv path/to/trades.csv
```

Or upload a CSV from the dashboard's Import tab.

Required fields:

- `symbol`
- `side`
- `entry_price`
- `opened_at`

`status` can be omitted; it is inferred from close time / exit price when possible.
Numbers such as `$1,234.50` and `(12.50)` are parsed. Invalid rows are reported
with reasons and are not silently imported.

Common aliases:

| Canonical field | Accepted aliases |
| --- | --- |
| `symbol` | `pair`, `instrument`, `ticker`, `market` |
| `side` | `direction`, `buy_sell`, `type`, `action` |
| `status` | `state` |
| `opened_at` | `open_time`, `entry_time`, `open_date`, `open` |
| `closed_at` | `close_time`, `exit_time`, `close_date`, `close` |
| `entry_price` | `entry`, `open_price`, `price_in` |
| `exit_price` | `exit`, `close_price`, `price_out` |
| `quantity` | `size`, `lots`, `volume`, `qty`, `units` |
| `stop_loss` | `sl`, `stop` |
| `take_profit` | `tp`, `target` |
| `initial_risk_amount` | `risk_amount`, `risk`, `risk_usd` |
| `gross_pnl` | `pnl`, `gross`, `gross_profit` |
| `fees` | `commission`, `fee`, `cost` |
| `net_pnl` | `net_profit`, `profit`, `net`, `realized_pnl` |
| `notes` | `note`, `comment`, `journal`, `remarks` |
| `external_id` | `id`, `trade_id`, `ticket`, `order_id`, `deal_id`, `ref` |

## TradeLocker Sync

TradeLocker support is optional. The dashboard and CSV workflow work without any
TradeLocker credentials.

Copy `.env.example` to `.env` and fill the TradeLocker block only if you want to
sync from TradeLocker:

```dotenv
TRADELOCKER_ENABLED=true
TRADELOCKER_ENVIRONMENT=demo        # demo | live
TRADELOCKER_EMAIL=you@example.com
TRADELOCKER_PASSWORD=your-password
TRADELOCKER_SERVER=YOUR-SERVER
TRADELOCKER_ACCOUNT_ID=12345        # optional default
TRADELOCKER_ACC_NUM=1               # optional
TRADELOCKER_SYNC_LOOKBACK_DAYS=90
```

Run a safe preview first:

```bash
trading-journal tradelocker-health
trading-journal tradelocker-accounts
trading-journal sync-tradelocker --account-id 12345 --dry-run
```

Write imported data only when ready:

```bash
trading-journal sync-tradelocker --account-id 12345 --apply
```

Safety guarantees:

- The connector reads accounts, open positions, closed history, and account state.
- The default sync mode is dry-run; database writes require explicit `--apply`.
- The only non-GET request is authentication.
- No order placement, order modification, order cancellation, or position closing methods exist in the connector.
- Credentials and tokens are read from environment variables and are never stored in the database.
- Manual notes, review fields, and manually corrected trade fields are preserved across resyncs.
- Sync warnings and conflicts appear in the audit trail and Needs Review queue.

TradeLocker demo/live environment must match the account. A mismatch is the most
common cause of `401` / `403` authentication errors.

## Metrics And Scoring

Performance metrics use closed trades only. Open trades do not affect win rate,
profit factor, expectancy, or drawdown.

| Metric | Definition |
| --- | --- |
| Net P&L | Sum of `net_pnl` over closed trades. |
| Trade win % | Winners / (winners + losers), excluding breakeven trades. |
| Day win % | Winning days / trading days, grouped by close date. |
| Profit factor | Gross profit / absolute gross loss. |
| Expectancy (R) | Average R per closed trade with a known R value. |
| Planned RR | Reward-to-risk from entry, stop loss, and take profit. |
| Realized R | Trade result as a multiple of initial risk. |
| Max drawdown | Largest peak-to-trough drop in the cumulative daily P&L curve. |

R is computed in this order:

1. Money-based: `net_pnl / initial_risk_amount`.
2. Price-based estimate: price distance from entry to exit divided by entry to stop.
3. Unknown when not enough data exists.

If you manually override realized R while correcting a trade, the value is kept
and marked as `manual`.

The UI always shows the R method so exact, estimated, manual, and unknown values
are not mixed silently.

The Journal Score is a transparent local score, not TradeZella's Zella Score:

| Component | Points |
| --- | ---: |
| Data completeness | 25 |
| Risk tracking | 20 |
| Risk control | 20 |
| Performance health | 15 |
| Trade review | 12 |
| Daily review consistency | 8 |

Each component includes a confidence level based on sample size. Low confidence
means "not enough data yet", not "bad performance".

## Data Storage And Privacy

- Everything is stored locally.
- Default database: `data/trading_journal.db`.
- Exports and backups are written to local folders such as `exports/` and `backups/`.
- Restore validates the archive and saves a copy of the current database before replacing it.
- TradeLocker credentials stay in environment variables, not in SQLite.
- This project is independent and is not affiliated with TradeZella or TradeLocker.

Backup examples:

```bash
trading-journal export-csv --out exports/
trading-journal export-json --out exports/
trading-journal backup --out backups/
trading-journal restore-backup backups/trading_journal_backup_YYYYMMDD_HHMMSS.zip --yes
```

## Project Layout

```text
src/trading_journal/
  cli.py                  # trading-journal command entry point
  config.py               # environment-driven settings
  db.py                   # SQLAlchemy engine/session/schema setup
  models.py               # accounts, snapshots, trades, reviews, sync state
  metrics.py              # P&L, R/RR, drawdown, and day-detail calculations
  analytics.py            # non-strategy risk analytics
  journal_score.py        # transparent local scoring rubric
  data_quality.py         # checks and Needs Review queue
  seed.py                 # bundled demo data seeding
  importers/
    csv_importer.py       # CSV parsing, validation, and import
  connectors/
    tradelocker/          # read-only TradeLocker client and mappers
  services/               # trade, account, review, sync, state, backup services
  ui/                     # Streamlit app, charts, and tab renderers

sample_data/              # bundled demo trades and account snapshots
tests/                    # pytest suite
```

## Development

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Run checks:

```bash
pytest
ruff check src tests
ruff format src tests
```

The test suite covers the CSV importer, metrics, review workflow, manual trade
corrections, TradeLocker client, sync service, Streamlit behavior, data-quality
checks, and backup/restore.

## Limitations

- No live trading or broker-side write actions.
- No MT4, MT5, cTrader, or other broker connectors.
- No real-time websocket sync; TradeLocker sync is on demand.
- No cloud sync, web authentication, multi-user mode, or mobile app.
- No strategy-specific analytics; the analytics are generic risk and review tools.
- No MFE/MAE because intraday candle history is not stored.
- Partial closes depend on the fields returned by TradeLocker and may need manual review.
- Trade screenshots/attachments are not implemented.

## License

MIT, as declared in `pyproject.toml`.
