# trading_journal

A **local, single-user forex trading journal and dashboard** — a "TradeZella-lite"
you run on your own machine. Point it at a CSV of your trades (or seed the bundled
demo data) and get clean performance, risk, and journaling metrics with charts.

It is a *journal/dashboard*, not a trading bot, not a broker interface, and not a
TradeZella clone. **Phase 2** adds an optional, strictly **read-only** TradeLocker
sync (accounts, open positions, closed history, balance/equity). It **never**
places, modifies, cancels, or closes orders/positions — see
[Phase 2: read-only TradeLocker sync](#phase-2-read-only-tradelocker-sync).

---

## What Phase 1 includes

- **SQLite + SQLAlchemy 2.x** data model for accounts, account snapshots, and trades
  (open *and* closed).
- A **metrics engine** (pandas) computing Net P&L, win %, profit factor, day win %,
  average win/loss (money and R), expectancy, realized R, planned RR, cumulative /
  daily P&L, and max drawdown.
- A transparent **Journal Score** (0–100) — our own local, fully-documented score,
  explicitly **not** TradeZella's proprietary Zella Score.
- A **flexible CSV importer** with column-alias detection, messy-number parsing,
  clear validation errors, data-quality warnings, and duplicate prevention.
- Deterministic, realistic **sample data** (40 closed + 4 open EUR/USD-centric
  trades over ~9 weeks, plus 9 account snapshots).
- A **CLI** (`trading-journal`) and a **Streamlit dashboard** (Plotly charts).
- A **pytest** suite and **ruff** configuration.

## What is intentionally NOT included

- ❌ No live trading, order placement/closing, or account modification (Phase 2's
  TradeLocker sync is **read-only** — it can only pull data in).
- ❌ No authentication, multi-user, cloud deployment, billing, teams, or subscriptions.
- ❌ No strategy-specific analytics (all trades are assumed to come from one strategy).
- ❌ No React/Vue frontend — Streamlit is used for speed.
- ❌ Nothing is imported from the separate `forex_trader` project.

Invalid data is **never silently dropped**: failed rows are reported with reasons,
and softer issues (missing stop, missing P&L, estimated R) are shown as warnings.

---

## Setup

Requires **Python 3.11+**.

```bash
# From the repository root
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .                 # add ".[dev]" for pytest + ruff

trading-journal init-db          # create the SQLite database
trading-journal seed-demo        # load the bundled demo data
trading-journal dashboard        # launch the Streamlit dashboard
```

The database lives at `data/trading_journal.db` by default. Override via a `.env`
file (see `.env.example`): `TRADING_JOURNAL_DATA_DIR`, `TRADING_JOURNAL_DB_NAME`,
or a full `TRADING_JOURNAL_DATABASE_URL`.

### Seed demo data

```bash
trading-journal seed-demo
```

Imports `sample_data/sample_trades.csv` and `sample_data/sample_account_snapshots.csv`.
It is **idempotent** — trades de-duplicate by `external_id` and snapshots by
`(account, timestamp)`, so running it twice does not create duplicates. You can also
seed from the dashboard's **Import** tab.

### Import your own CSV

```bash
trading-journal import-csv path/to/your_trades.csv
```

Or drag-and-drop a file into the dashboard **Import** tab (with a live preview,
validation errors, and warnings before you commit the import).

The importer recognizes common column aliases, e.g.:

| Canonical | Accepted aliases |
| --- | --- |
| `symbol` | pair, instrument, ticker, market |
| `side` | direction, buy_sell, type, action (buy/sell/long/short/b/s) |
| `status` | state (open/closed/o/c/filled…) |
| `opened_at` | open_time, entry_time, open_date, open |
| `closed_at` | close_time, exit_time, close_date, close |
| `entry_price` | entry, open_price, price_in |
| `exit_price` | exit, close_price, price_out |
| `quantity` | size, lots, volume, qty, units |
| `stop_loss` | sl, stop |
| `take_profit` | tp, target |
| `initial_risk_amount` | risk_amount, risk, risk_usd |
| `gross_pnl` | pnl, gross, gross_profit |
| `fees` | commission, fee, cost |
| `net_pnl` | net_profit, profit, net, realized_pnl |
| `notes` | note, comment, journal, remarks |
| `external_id` | id, trade_id, ticket, order_id, deal_id, ref |

Only `symbol`, `side`, `entry_price`, and `opened_at` are strictly required.
`status` is inferred from the presence of a close time / exit price when omitted.
Numbers like `"$1,234.50"` and `"(12.50)"` (parenthesized negatives) are parsed.

### Run the dashboard

```bash
trading-journal dashboard
# equivalently:
streamlit run src/trading_journal/ui/streamlit_app.py
```

Tabs: **Dashboard** (KPIs, charts, Journal Score), **Trades** (filterable tables,
open positions), **Import** (upload/seed), **Account** (balance/equity + manual
snapshots), **Help / Data Quality** (formulas and missing-data checks).

### Print metrics without the UI

```bash
trading-journal metrics
```

---

## Metric formulas

Performance metrics use **closed** trades only; open trades never distort them.

| Metric | Definition |
| --- | --- |
| **Net P&L** | Σ `net_pnl` over closed trades |
| **Gross profit / loss** | Σ `net_pnl` of winners / of losers (loss is negative) |
| **Profit factor** | gross profit / \|gross loss\| — `∞` if there are no losses, `None` if no P&L data |
| **Trade win %** | winners / (winners + losers) — breakeven (scratch) trades excluded |
| **Day win %** | winning days / trading days, grouped by close date |
| **Avg win / loss** | mean `net_pnl` of winners / of losers |
| **Avg win / loss (R)** | mean `realized_r` where R > 0 / where R < 0 |
| **Avg realized R** | mean `realized_r` over closed trades that have an R value |
| **Expectancy (R)** | p(win)·avgWinR + p(loss)·avgLossR (equals mean R by construction) |
| **Avg planned RR** | mean `planned_rr` over **all** trades that have one (open + closed) |
| **Max drawdown** | largest peak-to-trough drop of the cumulative daily P&L curve |
| **Latest balance / equity** | most recent account snapshot |

### Planned RR (reward-to-risk from price)

- **BUY:** `risk = entry − stop_loss`, `reward = take_profit − entry`
- **SELL:** `risk = stop_loss − entry`, `reward = entry − take_profit`
- `planned_rr = reward / risk` when both are strictly positive, else `None`.

### Realized R — money-based vs price-based

R is *how many multiples of your initial risk* a trade returned. We derive it two
ways, and we **never** treat the estimate as equal to the exact figure:

1. **Money-based (preferred, `r_method = "money"`):**
   `realized_r = net_pnl / initial_risk_amount`. Uses the dollars you actually risked.
2. **Price-based (estimate, `r_method = "price"`):** when no risk amount is recorded,
   estimate from price distances:
   - BUY: `(exit − entry) / (entry − stop_loss)`
   - SELL: `(entry − exit) / (stop_loss − entry)`
3. If neither is possible, `realized_r` is `None` and `r_method = "unknown"`.

The UI labels each trade's `r_method` so estimated R is always visible as such.

### Journal Score (transparent, local — NOT the Zella Score)

A 0–100 score that rewards good *journaling and risk habits*, not just profit:

| Component | Max | Measures |
| --- | --- | --- |
| Data completeness | 30 | closed trades with all core fields (P&L, dates, side, symbol) |
| Risk tracking | 25 | closed trades where R is knowable (money **or** price) |
| Risk control | 20 | losing trades that respected the stop (`realized_r ≥ −1.2`) |
| Performance health | 15 | positive expectancy (R) and profit factor > 1 |
| Review completeness | 10 | closed trades that have non-empty notes |

Each component and the overall score carry a **confidence** (HIGH / MEDIUM / LOW)
based on sample size. **LOW confidence means "not enough data yet", not "bad."** If
there are no losing trades to judge, risk control returns a neutral placeholder
flagged LOW rather than a misleading 0 or 20.

---

## Data model

See `src/trading_journal/models.py`:

- **Account** — `id, name, broker, base_currency, …` plus Phase 2 sync metadata
  `source (local/tradelocker), external_id?, external_account_number?, environment?,
  last_synced_at?`.
- **AccountSnapshot** — `id, account_id, timestamp, balance, equity, source, created_at`.
- **Trade** — the Phase 1 fields (`symbol, side, status, opened_at, closed_at?,
  entry_price, exit_price?, quantity?, stop_loss?, take_profit?, initial_risk_amount?,
  gross_pnl?, fees?, net_pnl?, planned_rr?, realized_r?, r_method?, notes?`) plus
  Phase 2 metadata `external_position_id?, external_order_id?, external_account_id?,
  external_account_number?, external_status?, raw_payload_json?, last_synced_at?`.
- **SyncRun** — one row per sync attempt (status, counts, warnings/errors, summary).
- **SyncState** — key/value cursors for incremental sync.

New columns are added to existing SQLite databases automatically and
non-destructively via additive `ALTER TABLE` on `init-db` — existing Phase 1
databases upgrade in place.

`planned_rr`, `realized_r`, and `r_method` are derived on import / manual entry and
computed in one place (`metrics.compute_planned_rr` / `compute_realized_r`).

### Project layout

```
src/trading_journal/
  config.py          # env-driven settings
  db.py              # engine, session_scope, init_db
  models.py          # SQLAlchemy models + side/status normalization
  metrics.py         # R/RR calculations + aggregate metrics engine
  journal_score.py   # the transparent Journal Score rubric
  formatting.py      # shared money/R/% display helpers (CLI + UI)
  seed.py            # idempotent demo-data seeding
  cli.py             # `trading-journal` entry point (+ tradelocker-* commands)
  importers/csv_importer.py
  connectors/        # read-only broker connectors
    tradelocker/     # client, endpoints, schemas, config_parser, mapper, errors
  services/          # trade_service, account_service, sync_service, sync_state_service
  ui/                # streamlit_app.py (+ Sync tab), charts.py
```

> **Structure notes:** the requested layout was followed, with a few small,
> single-purpose modules split out for readability rather than one large file —
> `journal_score.py` (scoring rubric), `seed.py` (shared by CLI + UI),
> `formatting.py` (shared display helpers), and `ui/charts.py` (Plotly builders).

---

## Development

```bash
pip install -e ".[dev]"
pytest          # 93 tests (Phase 1 + Phase 2)
ruff check src tests
ruff format src tests
```

---

## Phase 2: read-only TradeLocker sync

Phase 2 pulls your TradeLocker data **into** this local journal so the existing
Dashboard, Trades, Calendar, and Account views work over real broker data. It is
**strictly read-only**:

- ✅ authenticate, discover accounts, read open positions, read closed history,
  read balance/equity.
- ❌ **no** `create_order` / `place_order` / `close_position` / `modify_order` /
  `cancel_order` — those methods **do not exist** anywhere in the codebase.
- The only non-`GET` request the connector can make is the authentication POST
  (JWT token/refresh) required by the official API. All HTTP flows through one
  guarded choke point that refuses any other write verb.

### Design

```
connectors/tradelocker/
  endpoints.py     # every reachable path in one auditable place (read-only)
  errors.py        # typed errors (auth/config/rate-limit/http/parse)
  schemas.py       # AuthTokens (token repr redacted), account/config models
  config_parser.py # tolerant array-rows + column-config -> list[dict]
  client.py        # TradeLockerReadOnlyClient (+ injectable HTTP transport)
  mapper.py        # pure TradeLocker -> local candidate mapping (no DB access)
services/
  sync_service.py       # idempotent orchestration + upserts (the only writer)
  sync_state_service.py # SyncRun audit trail + incremental cursors
```

Response parsing is isolated from database writes; unexpected shapes produce
**warnings**, never silent corruption; unknown fields are retained in each trade's
`raw_payload_json`.

### Setup (`.env`)

Copy `.env.example` to `.env` and fill in the TradeLocker block (see that file for
the full list). Minimum for a sync:

```dotenv
TRADELOCKER_ENVIRONMENT=demo        # demo | live  — MUST match your account
TRADELOCKER_EMAIL=you@example.com
TRADELOCKER_PASSWORD=your-password
TRADELOCKER_SERVER=YOUR-SERVER
TRADELOCKER_ACCOUNT_ID=12345        # optional default (or pass --account-id)
TRADELOCKER_ACC_NUM=1               # optional (auto-discovered if omitted)
TRADELOCKER_SYNC_LOOKBACK_DAYS=90
```

> ⚠️ **Demo vs live:** `demo` talks to `https://demo.tradelocker.com` and `live`
> to `https://live.tradelocker.com`. Using the wrong one for your account is the
> most common cause of a 401. Never point a "test" run at a live account.

> 🔒 **Credential handling:** credentials are read from the environment only. They
> are **never** stored in the database, **never** logged, and **never** printed by
> the CLI. Passwords and JWT tokens are excluded from object `repr`s. Do **not**
> commit your `.env` (it is git-ignored).

### How to run

```bash
# 1. Verify config + auth (prints a safe summary, no secrets):
trading-journal tradelocker-health

# 2. List the accounts your credentials can see:
trading-journal tradelocker-accounts

# 3. Preview a sync — writes NOTHING (this is the default):
trading-journal sync-tradelocker --account-id 12345 --dry-run
#    (equivalently, just omit --apply)

# 4. Actually import into the local journal (idempotent; safe to repeat):
trading-journal sync-tradelocker --account-id 12345 --apply

# Sync every discovered account, custom history window:
trading-journal sync-tradelocker --all --lookback-days 30 --apply

# Review the audit trail of past runs:
trading-journal sync-status

# See it all in the dashboard's new "Sync" tab:
trading-journal dashboard
```

Writes require an explicit **`--apply`** — the default is always a dry run. The
same actions are available on the dashboard's **Sync** tab (health check, list
accounts, dry-run, apply, recent-runs table, and post-sync warnings). Opening the
dashboard performs **no** network calls; only clicking a Sync button does.

Synced trades/positions/snapshots use `source = "tradelocker"` and flow through the
same Phase 1 metrics — planned RR and realized R are recomputed with the exact same
calculators, so your KPIs and Journal Score "just work".

### Idempotency & safe updates

- Trades are keyed by `source + environment + account + position id` (falling back
  to order id, then a cautious composite key flagged low-confidence). Re-running a
  sync never duplicates rows.
- A closing history row **updates** the matching open trade to `CLOSED` (open and
  closed share the position key).
- Your **`notes` are never overwritten**, and a manually-entered
  `initial_risk_amount` is only filled when locally empty.
- An open position that disappears from TradeLocker is **flagged** (marked stale,
  with a warning) — never auto-deleted or auto-closed.
- Balance/equity snapshots skip an identical reading within 5 minutes.

### Data safety rules

- Read-only only: no order/position writes exist in the codebase.
- Credentials/tokens are never persisted or logged.
- All API parsing is separated from DB writes; malformed data warns instead of
  corrupting.
- Dry-run performs zero database mutations.

### Known limitations

- **Response shapes vary by broker/server.** The parser is config-driven and
  tolerant, but some fields may be unavailable; those cases warn rather than guess.
- **Partial closes may need manual review.** Multiple fills under one position id
  are aggregated (P&L summed) into a single trade with a warning; this is a
  best-effort journal reconstruction, not exact institutional accounting.
- **Closed-trade reconstruction depends on the fields TradeLocker returns** in
  order history (position/order ids, open/close times, prices, P&L).
- Symbols come from a `tradableInstrumentId` and are resolved via the instruments
  list; unresolved ids fall back to an `INSTR_<id>` placeholder with a warning.
- **No trading/write actions** and **no real-time websocket sync** — sync is
  on-demand only.

### Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `401` / `403` on auth | Wrong **demo/live** environment, wrong `TRADELOCKER_SERVER`, or bad email/password. |
| Wrong server | `TRADELOCKER_SERVER` must be the exact server name shown in your TradeLocker login. |
| "no accNum" warning / some endpoints reject | Pass `--acc-num` or set `TRADELOCKER_ACC_NUM`; it is otherwise auto-discovered. |
| Auth expired mid-session | The client refreshes automatically; if it can't, re-run the command. |
| No accounts found | Credentials are valid but for a different environment, or the login has no accounts. |
| No closed trades imported | Nothing closed within the lookback window — widen it with `--lookback-days`. |
| `429` rate limited | You're syncing too often; wait and retry. |
