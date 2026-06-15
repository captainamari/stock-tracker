# Stock Tracker

Stock Tracker is a backend-first US stock analysis pipeline. It collects daily market data, stores prices and strategy state in SQLite, runs several technical-analysis strategies, renders daily reports, and can send Telegram notifications. The `web/` directory is frontend-facing code and is intentionally not covered here.

## Backend Architecture

```text
config/tickers.json
        |
        v
scripts/save_prices_yfinance.py
        |
        v
data/stock_tracker.db  <---- lib/db.py, lib/config.py, lib/models.py
        |
        +--> scripts/market_pulse.py
        +--> scripts/stage2_monitor.py
        +--> scripts/vcp_scanner.py
        +--> scripts/bottom_fisher.py
        +--> scripts/buying_checklist.py
        |
        v
lib/report.py + templates/*.j2
        |
        v
reports/daily/*.md + *_telegram.html + *_manifest.txt
        |
        v
scripts/daily_pipeline.py --> lib/notifier.py --> Telegram Bot API
```

The backend is organized around a SQLite database and a small set of scripts. Strategy scripts read from the database, calculate signals, persist results, and render reports through shared library code.

## Core Components

| Path | Responsibility |
| --- | --- |
| `config/tickers.json` | Source-of-truth watchlist configuration. Contains monitored equities plus market/index symbols used by yfinance. |
| `scripts/save_prices_yfinance.py` | Main price collection entry point. Fetches incremental OHLCV data, writes SQLite rows, and can trigger strategy refreshes. |
| `scripts/save_prices.py` | Legacy Stooq collector kept for compatibility. It is not the current primary collection path. |
| `scripts/daily_pipeline.py` | Three-phase daily workflow: data collection, strategy calculation/report generation, and optional notification delivery. |
| `scripts/market_pulse.py` | Market regime analysis using SPY, QQQ, IWM, VIX, breadth, and distribution-day pressure. |
| `scripts/stage2_monitor.py` | Stan Weinstein / Minervini Stage 2 trend detection. |
| `scripts/vcp_scanner.py` | VCP scanner for Stage 2 names with volatility contraction and volume dry-up. |
| `scripts/bottom_fisher.py` | Mean-reversion / bottom-fishing scanner for quality stocks after pullbacks. |
| `scripts/buying_checklist.py` | Final buy-readiness checklist combining trend, momentum, structure, volume, and strategy confluence. |
| `lib/db.py` | SQLite data-access layer, schema creation, UPSERT helpers, and idempotency tables. |
| `lib/config.py` | Loads `tickers.json` and syncs the configured watchlist into SQLite. |
| `lib/indicators.py` | Shared technical indicators: SMA, EMA, RSI, MACD, ATR, Bollinger bandwidth, streaks, divergence, candles, weekly resampling, Elder Impulse. |
| `lib/models.py` | Dataclass models for tickers, strategy results, market pulse, and signal changes. |
| `lib/report.py` | Jinja2 report rendering, Telegram-safe formatting helpers, and message splitting. |
| `lib/notifier.py` | Telegram delivery with retry, HTML fallback, dry-run mode, and notification idempotency. |
| `lib/pipeline.py` | Backend pipeline helpers for ticker validation, price refresh, strategy refresh, and market pulse updates. |
| `templates/*.j2` | Markdown and Telegram HTML report templates. |
| `reports/daily/` | Generated daily report artifacts. |

## Data Model

The backend persists state in `data/stock_tracker.db`. The schema is created and managed by `lib/db.py`.

| Table | Purpose | Primary key |
| --- | --- | --- |
| `watchlist` | Configured symbols, names, sectors, enabled state, and source metadata. | `symbol` |
| `stock_prices` | Daily OHLCV price history. | `(symbol, date)` |
| `strategy_results` | Per-symbol, per-date strategy outputs with JSON details and metrics. | `(symbol, date, strategy)` |
| `strategy_states` | Latest active/inactive state for each symbol and strategy. | `(symbol, strategy)` |
| `signal_changes` | Signal entry/exit history. | `id` |
| `market_pulse` | Daily market regime and distribution-day analysis. | `date` |
| `pipeline_runs` | Daily pipeline step status for idempotent reruns. | `(run_date, strategy)` |
| `notification_log` | Telegram delivery status for idempotent notifications. | `(notify_date, channel, strategy)` |
| `db_meta` | Database metadata and migration/version markers. | `key` |

Design notes:

- `strategy_results.conditions`, `condition_details`, and `metrics` are JSON payloads so individual strategies can evolve without schema churn.
- `pipeline_runs` and `notification_log` make daily runs safe to retry.
- SQLite WAL mode is used for better read concurrency.
- The DAL handles numpy-compatible JSON serialization for strategy metrics.

## Data Flow

1. `config/tickers.json` defines enabled equities and market/index symbols.
2. `lib.config.sync_watchlist()` syncs that configuration into `watchlist`.
3. `scripts/save_prices_yfinance.py` checks the latest stored date per symbol and fetches only missing price rows.
4. Strategy scripts read normalized prices through `lib/db.py` and shared indicators from `lib/indicators.py`.
5. Strategy outputs are written to `strategy_results`, `strategy_states`, and `signal_changes`.
6. `lib/report.py` renders Markdown and Telegram HTML reports from `templates/*.j2` into `reports/daily/`.
7. `scripts/daily_pipeline.py` coordinates the full backend run and uses idempotency tables to avoid duplicate work.
8. `lib/notifier.py` optionally sends rendered reports to Telegram and records delivery status.

## Strategy Layer

| Strategy | Script | Role |
| --- | --- | --- |
| Market Pulse | `scripts/market_pulse.py` | Macro regime gauge. Scores SPY/QQQ/IWM trend, VIX, internal breadth, sector heat, and distribution days. |
| Stage 2 Monitor | `scripts/stage2_monitor.py` | Trend foundation. Detects stocks meeting Stage 2 / trend-template requirements. |
| VCP Scanner | `scripts/vcp_scanner.py` | Right-side setup scanner. Looks for volatility contraction and volume dry-up among Stage 2 names. |
| Bottom Fisher | `scripts/bottom_fisher.py` | Left-side pullback scanner. Looks for oversold quality names with support and reversal evidence. |
| Buying Checklist | `scripts/buying_checklist.py` | Final confirmation layer. Combines trend, momentum, price structure, volume, and strategy confluence. |

## Reports and Notifications

Reports are generated from database results, not from ad hoc script output. The shared report layer provides:

- Markdown report rendering for local review.
- Telegram HTML rendering for push notifications.
- Telegram escaping and formatting filters.
- Long-message splitting near paragraph boundaries.
- Report manifests under `reports/daily/`.

Telegram delivery is optional and controlled by environment configuration. `lib/notifier.py` supports dry-run mode, retry/backoff, HTML-to-text fallback, and notification de-duplication through `notification_log`.

## Common Commands

Run commands from the repository root.

```bash
# Install dependencies
pip install -r requirements.txt

# Inspect database status
python -m lib.db stats

# Sync config/tickers.json into the database
python -m lib.config

# Fetch incremental prices through the current main collector
python scripts/save_prices_yfinance.py

# Run individual strategies
python scripts/market_pulse.py
python scripts/stage2_monitor.py
python scripts/vcp_scanner.py
python scripts/bottom_fisher.py
python scripts/buying_checklist.py

# Run the daily backend pipeline without sending Telegram messages
python scripts/daily_pipeline.py --dry-run

# Run the daily backend pipeline with notification delivery enabled
python scripts/daily_pipeline.py
```

## Environment

Create a local `.env` file from `.env.example` when Telegram delivery or deployment-specific settings are needed. Do not commit secrets.

Typical notification settings:

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Frontend Refactor Boundary

For frontend refactoring, keep these backend contracts stable unless a coordinated API change is planned:

- `data/stock_tracker.db` schema and DAL behavior in `lib/db.py`.
- Watchlist semantics from `config/tickers.json` and `lib/config.py`.
- Strategy names and result shape stored in `strategy_results` and `strategy_states`.
- Report generation APIs in `lib/report.py`.
- Pipeline helper behavior in `lib/pipeline.py` for ticker validation, refresh, and strategy execution.
- Daily report artifact paths under `reports/daily/`.

The frontend can be reorganized independently as long as it continues to consume the backend through these stable data and pipeline boundaries.
