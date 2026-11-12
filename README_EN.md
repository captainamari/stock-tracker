# Stock Tracker

[中文](README.md) · [Operations and upgrade](DEPLOY.md) · [Acceptance evidence](docs/progress/GUEST_WATCHLIST_RESULTS.md)

A public, login-free US stock notebook using FastAPI, Jinja2, native JavaScript, Chart.js, SQLite WAL, yfinance and notification-hub. Three independent lists control collection, browser favorites and the owner's private digest.

## Run

Use Python 3.12 in a virtual environment and install `requirements.txt`. Native processes need exported variables; they do not automatically read `.env`.

```sh
export STOCK_DB=/absolute/path/stock_tracker.db
export PUBLIC_URL=http://127.0.0.1:8000
python -m lib.cli init
uvicorn web.app:app --host 127.0.0.1 --port 8000
# Separate processes, same database and environment:
python -m lib.cli worker
python -m lib.cli scheduler
python -m lib.cli update
```

On PowerShell use `$env:STOCK_DB='C:\absolute\stock_tracker.db'`. There is no login or public administration API. Use `python -m lib.cli --help` for collection, queue, schedule, export, backup and delivery operations.

## Browser favorites

First visits initialize AAPL, MSFT, AMZN, GOOG, META, NVDA, TSLA, SPY and QQQ from the single `config/browser-watchlist.json` default. Explicitly empty lists stay empty. Favorites support ordering, add/remove, confirmed reset, strict JSON import/export and same-origin tab synchronization. Only version and symbols are stored, up to 100 securities. Storage errors remain visible while the tab stays usable. Damaged or unknown-version state has explicit import/reset recovery.

Favorites stay in this browser; clearing site data loses them and there is no automatic device synchronization. Unknown or nonpublic imports are rejected and never change server collection. Overview candidates, counts, changes and exceptions use favorites. Discover provides the complete public directory with search and pagination. SPY/QQQ show benchmark prices and applicable indicators without stock-screen badges. Details retain charts, price export and conditions.

Market context is server-rendered, then the browser loads its selection pinned to that same publication. `GET /api/assets?symbols=AAPL,SPY&batch=...` selects before filtering/pagination. An empty `symbols=` returns no rows; omission selects the discover directory. Private flags, raw errors and notification data are never returned. Visibility is checked against current configuration and frozen asset permissions, including historical reports. Nonpublic selections become unavailable placeholders with no prices. Dynamic responses use no-store.

Web reports filter frozen public data by **current** favorites and offer an explicit all-public view. This is not a record of historical favorites. Legacy text snapshots can only be explicitly expanded in full. Private historical reports remain inaccessible.

## Collection and breadth

Collection remains S&P 500 ∪ Nasdaq-100 ∪ enabled extra configuration plus SPY, QQQ, IWM and VIX. Yahoo aliases deduplicate; distinct share classes stay distinct. Membership is checked weekly by the worker; failed refreshes retain the complete previous lists and wait at least 24 hours before another attempt. Each task freezes its own snapshot. Leaving an index never deletes history. Existing disabled/private choices survive upgrades; `assets` reports conflicts with default browser symbols and explicit per-symbol public commands.

New breadth version 2 uses the frozen **index union**, independently of visibility, favorites or owner configuration, excluding benchmarks and non-index extras. Expected count includes disabled/missing members. Saved coverage and per-metric valid denominators distinguish missing input from a false result. Incomplete coverage suppresses a complete-market regime; all-missing percentages are null. Old reports retain the legacy public-watchlist label.

Prices retain adjusted OHLC/native volume, incremental last-saved-session overlap, repair on genuine gaps or adjustment changes, input revisions and atomic publication. Initial history is 800 calendar days. Short contiguous histories remain incremental. Existing strategy definitions and thresholds are unchanged. No previous valid adjacent-session evaluation means no confirmed entry/exit. Yahoo calls are sequential with five-second spacing and a persisted six-hour rate-limit pause; IP immunity is not guaranteed.

## Independent owner notification

```sh
python -m lib.cli export-digest --scope personal --output /etc/stock-tracker/daily-report.json
python -m scripts.send_daily_report --config /etc/stock-tracker/daily-report.json --dry-run
# Real send, only when the owner chooses to run it:
python -m scripts.send_daily_report --config /etc/stock-tracker/daily-report.json
```

Alternatively copy `config/daily-report.example.json`, then edit the covered symbols, stable profile, channel alias and standard/compact mode. Credentials remain in `NOTIFICATION_API_URL` / `NOTIFICATION_API_TOKEN`. Never commit private configuration.

The script selects the latest closed XNYS session (including holidays, early closes and DST), freezes one published batch and sends its own outbox parts directly. It does not collect, refresh membership, calculate, migrate or drain other deliveries. `--date` selects a trading session. `--dry-run` performs no network calls or database writes. A missing target publication produces an explicit frozen missing-data notice, never a stale substitute or automatic later resend.

The database uniquely identifies automatic deliveries by profile + target session + channel, even across concurrent runs, changed configuration and same-day publications. Successful parts are retained on retry. Ambiguous/partial delivery requires review. The hub has no remote idempotency/receipt lookup, so network exactly-once is not promised. `--manual-reissue --date ...` explicitly permits an additional report; original history remains frozen.

Only the separate systemd oneshot/timer in `deploy/` invokes notifications. The app scheduler handles market updates only; the old notification worker is removed. Follow [DEPLOY.md](DEPLOY.md) for backups, migration, legacy queue review, timer installation, exit codes and rollback. No production deployment or real notification was performed by this change.

## Validation

```sh
pip install -r requirements-dev.txt
python -m pytest -q
node --check web/static/js/main.js
node --check web/static/js/watchlist.js
node --check web/static/js/stock-table.js
node tests/frontend.test.cjs
python -m compileall -q lib web scripts
python -m playwright install chromium
python -m scripts.browser_acceptance --database /new/isolated-browser.db --artifacts /tmp/browser-evidence
```

Browser acceptance refuses an existing DB and uses explicitly synthetic prices. Existing incremental prices, strategies, publication and report regression tests remain. Hub contract testing is documented in operations. Synthetic data and capacity checks do not establish production readiness or real market coverage.

## Compact stock tables

Overview, My watchlist and Discover share a semantic stock table. Use Market or Strategies columns; mobile defaults to Market and collapses advanced filters. Header sorting applies before pagination. Strategy-score sorting requires a selected strategy. Counts cover the complete watchlist/public scope before search and filters; overlapping strategies cannot be summed as distinct stocks.

Use stars to save stocks. Edit list enables keyboard-accessible order controls only with favorite order and no filters. Manage favorites contains JSON import/export and confirmed reset/clear actions; import opens a file chooser. Failed requests retain the last successful results with Retry.

Reports retain their historical batch, comparisons and expandable saved details. Ticker charts offer 1M/3M/6M/1Y/All using saved bars only. Return links restore source filters, page, columns and scroll when session storage is available. The browser acceptance command now checks five pages at six widths and writes compact-results.json. See [Chinese UI acceptance record](docs/progress/COMPACT_STOCK_UI_RESULTS.md).
