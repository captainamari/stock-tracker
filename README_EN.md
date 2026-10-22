# Stock Tracker

[中文](README.md) · [Operations](DEPLOY.md) · [Acceptance evidence](docs/progress/DAILY_USE_S1_S4_RESULTS.md)

A daily US equity notebook using FastAPI, Jinja2, native JavaScript, Chart.js and SQLite WAL. One durable pipeline collects closed yfinance sessions, computes database-backed strategies and technical indicators, then atomically publishes a dashboard and immutable daily report.

Visitors have read-only access. One administrator manages symbols, updates data and configures notification-hub. There is no manual price/indicator/result editing or market CSV upload. Unknown legacy prices remain preserved but unverified. Pending/short-history symbols retain readable prices independently of strategy signals.

## Start locally

Use Python 3.12, a virtual environment, and `pip install -r requirements.txt`. Export `STOCK_DB` as an absolute local path, `COOKIE_SECURE=false` for local HTTP only, and `PUBLIC_URL=http://127.0.0.1:8000`. Native processes require exported variables; Compose reads `.env`.

```sh
python -m lib.cli init
python -m lib.cli init-admin
uvicorn web.app:app --host 127.0.0.1 --port 8000
# Separate terminals, same environment/database:
python -m lib.cli worker
python -m lib.cli scheduler
python -m lib.cli notify-worker
```

Sign in at `/admin`, add symbols on **Watchlist & data**, choose public visibility explicitly and click **Update data**. The worker survives browser closure. Optional `seed-watchlist` imports configuration into an empty watchlist; importing into a populated watchlist requires `--explicit`. Updates never overwrite database configuration from JSON.

Default XNYS trading-day schedule: 04:00 New York update, 06:00 independent notification. Notifications default disabled. The hub base URL defaults to `https://notify.watchpoint.space`; `NOTIFICATION_API_URL` can override it. Supply `NOTIFICATION_API_TOKEN` through the private server environment. The administration page defaults to channel `trading` (Telegram); existing saved channels are preserved. Telegram/SMTP credentials remain in the hub. Saving settings does not send.

For deployment, set the URL above and the existing hub API token in Stock Tracker's ignored `.env`, then run `docker compose up -d --force-recreate` to load the environment into all four services. For an existing installation, edit `.env` in place; an explicitly empty URL remains disabled and must be filled in. In `/admin`, select `trading`, save, use **Send a test message**, confirm receipt, and then enable scheduled notifications when ready. Native processes need exported variables because they do not load `.env`. Never commit the API token. See [the notification setup steps](DEPLOY.md#公网通知服务配置).

Prices use adjusted OHLC and native volume, without unadjusted fallback. Source revisions preserve historical inputs. Missing inputs do not shrink condition denominators; failure does not imply candidate exit. Contraction candidates retain the original VCP thresholds; countertrend observations are separate. Checklist includes the provisional week and is not a win probability. Zero current matches stay zero.

Code deployments reuse the persistent SQLite database. With no reusable history, collection requests an initial 800-calendar-day window. Subsequent updates request only the last saved session through the latest closed session, retaining that one overlap bar to check adjusted OHLC. New sessions, weekends, holidays and an unsaved tail are not historical gaps. Contiguous IPO histories under 252 bars remain incremental; strategies still report insufficient history where appropriate. Every enabled asset is checked, not just followed stocks.

Actual gaps/invalid stored bars or source omissions of saved sessions trigger an 800-day repair window. Changed adjusted OHLC on the overlap or a corporate action on a new session triggers recollection covering all saved history (at least the 800-day window), avoiding mixed adjustment bases. Already incorporated actions on the overlap do not repeatedly trigger full requests. A failed expanded request does not commit partially adjusted prices, and published reports keep their original revisions. Older volume-only corrections and historical revisions that leave the overlap unchanged cannot be comprehensively detected by this narrow request.

Strategy badges in the watchlist and daily report use green for Match, soft amber for Near, and gray for No match, with text labels retained. Failed or insufficient-data results are never highlighted as Near.

The hub lacks remote idempotency and receipt lookup. Ambiguous/partial deliveries are held for review, never blindly retried. Missing daily publications produce a missing-data summary, without later automatic resend. No exactly-once guarantee is claimed.

Run `pip install -r requirements-dev.txt`, `python -m pytest -q`, `node --check web/static/js/main.js`, and `python -m compileall -q lib web scripts`. The isolated capacity tool accepts only a new database: `python -m scripts.capacity_check --database /new/path/synthetic.db --output /new/path/results.json`. It exercises 5,000 synthetic stocks and does not prove real full-market collection. See operations for backups, migration and the pinned real hub contract test. Production cutover and real messaging are outside this change.

Yahoo precautions: sequential calls, persistent five-second spacing and a six-hour cooldown on rate limiting; the failed run stops before other symbols and keeps the previous publication. No VPS IP immunity is guaranteed. Configure YAHOO_MIN_INTERVAL_SECONDS / YAHOO_COOLDOWN_SECONDS. git pull does not include SQLite data. The 1.26 million capacity bars are synthetic; only the separate 3,300 real bars can be transferred as a verified backup for a fresh installation. See DEPLOY.md for reuse and existing-database migration.

## Collection universe

The default is **S&P 500 ∪ Nasdaq-100 ∪ enabled personal entries**, plus SPY, QQQ, IWM and VIX. The bundled membership snapshot retrieved on 2026-10-22 contains 503 + 101 listings with 86 overlaps: **518 unique index stocks**. Distinct share classes remain distinct stocks. Requests are deduplicated by normalized Yahoo ticker, including BRK.B/BRK-B aliases.

On an empty installation, the existing 44 entries in config/tickers.json are seeded as personal configuration before index members are added: the current configuration produces **540 download assets**, including four benchmarks. On an existing installation, database watchlist rows are preserved as personal entries; names, source mappings, disabled choices and privacy flags are not overwritten. New index-only entries are public. Use the existing Add symbol form to retain an index stock as a personal entry even after it leaves the index.

Both public Wikipedia constituent tables are refreshed together by the worker when the last complete snapshot is at least seven days old. GET pages and enqueue never fetch membership or prices. Failure keeps both previous lists and waits at least 24 hours before another membership attempt. An update freezes its membership snapshot and asset list before collection, including after worker restart. Former index-only stocks stop being collected; stored prices/results/reports remain. An explicit disable survives index refresh and re-entry.

The watchlist/admin pages show membership counts, retrieval time and refresh warnings; the admin table separates personal and index-managed rows. INDEX_UNIVERSE_ENABLED=false opts into personal-only collection plus the four benchmarks; it does not delete historical data. Isolated synthetic tests explicitly use this setting except tests of index-universe behavior.

This changes which stocks the next update collects; it does not mean 518 stocks have already been downloaded. Existing yfinance pacing, cooldown and incremental-history behavior still apply. See DEPLOY.md for sources and operational limits.
