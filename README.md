# trading_journal

A **local, single-user forex trading journal and dashboard** — a "TradeZella-lite"
you run on your own machine. Point it at a CSV of your trades (or seed the bundled
demo data) and get clean performance, risk, and journaling metrics with charts.

This is **Phase 1**. It is a *journal/dashboard*, not a trading bot, not a broker
interface, and not a TradeZella clone. It is designed to later sync (read-only)
with TradeLocker, but **Phase 1 does not use the TradeLocker API at all**.

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

## What is intentionally NOT included (Phase 1 scope)

- ❌ No TradeLocker sync / API (that is Phase 2, read-only).
- ❌ No live trading, order placement/closing, or account modification.
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

Three tables (see `src/trading_journal/models.py`):

- **Account** — `id, name, broker, base_currency, created_at, updated_at`.
- **AccountSnapshot** — `id, account_id, timestamp, balance, equity, source, created_at`.
- **Trade** — `id, account_id, source, external_id?, symbol, side (BUY/SELL),
  status (OPEN/CLOSED), opened_at, closed_at?, entry_price, exit_price?, quantity?,
  stop_loss?, take_profit?, initial_risk_amount?, gross_pnl?, fees?, net_pnl?,
  planned_rr?, realized_r?, r_method?, notes?, created_at, updated_at`.

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
  cli.py             # `trading-journal` entry point
  importers/csv_importer.py
  services/          # trade_service, account_service (query + manual entry)
  ui/                # streamlit_app.py, charts.py
```

> **Structure notes:** the requested layout was followed, with a few small,
> single-purpose modules split out for readability rather than one large file —
> `journal_score.py` (scoring rubric), `seed.py` (shared by CLI + UI),
> `formatting.py` (shared display helpers), and `ui/charts.py` (Plotly builders).

---

## Development

```bash
pip install -e ".[dev]"
pytest          # 36 tests
ruff check src tests
ruff format src tests
```

---

## Phase 2 (planned)

**Read-only TradeLocker sync**: pull accounts, balances/equity, and trade history
from TradeLocker into this same local model — still no order placement, closing, or
account modification. The data model and importer were shaped with that read-only
sync in mind (`source` and `external_id` fields, duplicate-safe imports).
