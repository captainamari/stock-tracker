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

Default XNYS trading-day schedule: 04:00 New York update, 06:00 independent notification. Notifications default disabled. Edit times/channel references in the administration page. Supply `NOTIFICATION_API_URL` and `NOTIFICATION_API_TOKEN` only on the server; channel credentials remain in the hub. Saving settings does not send.

Prices use adjusted OHLC and native volume, without unadjusted fallback. Source revisions preserve historical inputs. Missing inputs do not shrink condition denominators; failure does not imply candidate exit. Contraction candidates retain the original VCP thresholds; countertrend observations are separate. Checklist includes the provisional week and is not a win probability. Zero current matches stay zero.

The hub lacks remote idempotency and receipt lookup. Ambiguous/partial deliveries are held for review, never blindly retried. Missing daily publications produce a missing-data summary, without later automatic resend. No exactly-once guarantee is claimed.

Run `pip install -r requirements-dev.txt`, `python -m pytest -q`, `node --check web/static/js/main.js`, and `python -m compileall -q lib web scripts`. The isolated capacity tool accepts only a new database: `python -m scripts.capacity_check --database /new/path/synthetic.db --output /new/path/results.json`. It exercises 5,000 synthetic stocks and does not prove real full-market collection. See operations for backups, migration and the pinned real hub contract test. Production cutover and real messaging are outside this change.
