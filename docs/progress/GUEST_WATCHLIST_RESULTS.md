# Guest watchlist and independent digest acceptance

Date: 2026-11-11. Base: `origin/main` at `b4069bba9cd4ba4599c252a7afcc3af028e1004e`, re-fetched before submission; no later main commit. Work used a fresh isolated checkout and branch `codex/guest-watchlist-independent-digest`. No existing user modifications or production databases were accessed.

## Implemented behavior

- Browser-only versioned favorites initialize the nine defaults once, preserve explicit empty lists, synchronize tabs, support order/import/export/reset and expose storage errors. Overview selection/candidates/counts/changes and public frozen reports use the current favorites; Discover remains a searchable public directory. Details retain charts, CSV and saved conditions. Market context and requests pin one batch.
- Public HTTP has no authentication/admin routes or write operations. Old cookies do not grant access. Private owner labels, raw errors and private report IDs cannot be extracted using symbols/scope/report_id. Visibility revocation also applies across Yahoo aliases and historical structured reports. Unavailable favorites retain only symbol/remove controls. No-store responses prevent HTTP cache reuse.
- New breadth scope/version is `index_union`/2. It uses the run's frozen snapshot, deduplicates BRK.B/BRK-B, retains GOOG/GOOGL, excludes benchmarks/non-index extras, and includes missing/disabled members in expected coverage. Valid metric denominators are saved separately; all-missing percentages are null. The existing strict complete-input rule is retained: incomplete coverage suppresses a market regime. Historical reports retain their old label, and refresh-failure retention is frozen on the run.
- Owner digest reads strict private configuration, resolves the latest closed XNYS session, reads one complete publication, freezes its selected content and sends only its own outbox delivery. Unique profile/session/channel identity prevents repeat execution even after configuration or batch changes. Missing reports produce a frozen delay summary with no automatic replacement. Manual reissue is explicit. No update, membership refresh or strategy calculation occurs in the sender; scheduler now handles updates only.
- CLI replaces collection configuration, visibility, task queue/status, legacy label export, update schedule and delivery review/retry operations. Migration 008 adds `digest_runs` and `update_runs.universe_status` without deleting history. Authentication tables remain for rollback.

## Local commands and actual results

Environment: Windows, Python 3.12 isolated venv, pinned application requirements, Node, Chromium 158 via Playwright. Every market fixture is explicitly synthetic, with isolated SQLite and fake/local Hub adapters.

| Check | Result |
|---|---|
| `python -m pytest -q --disable-warnings` | 102 passed, 1 dependency deprecation warning, 176.36s (full run before the final delivery-inspection command addition) |
| `python -m pytest tests/test_notifications.py tests/test_guest_digest.py::test_cli_delivery_review_is_explicit_and_preserves_records tests/test_guest_digest.py::test_real_module_entry_sends_to_local_hub_and_exits -q --disable-warnings` | 8 passed in 14.39s (final delivery review and real entry verification) |
| `node --check web/static/js/main.js` and `watchlist.js` | Passed |
| `python -m compileall -q lib web scripts` | Passed |
| `python -m scripts.browser_acceptance --database <new isolated path> --artifacts <evidence path>` | Passed: 8 grouped scenarios, no page JavaScript exceptions |
| `python -m scripts.verify_hub_contract --checkout <pinned hub checkout>` | Passed against notification-hub `7c6ef039047e9adae7c6ca14d4e32204f352957c`: sent, auth rejection, partial, ambiguous provider failure, unknown channel, unconfigured provider; external sends 0 |

The real `python -m scripts.send_daily_report` subprocess was exercised against a loopback HTTP Hub implementing the existing request/receipt contract, including a multi-part standard report and duplicate invocation. No actual notification provider was called. Dry-run database dumps before/after are identical and forbidden download/calculation/queue adapters remain untouched. Tests exercise concurrent freeze/send, target-session dedupe, changed config/new batch, safe retries, partial/timeout uncertainty, manual acknowledgement, legacy queue isolation and update/web availability after delivery failure.

Calendar cases include Friday after close, Saturday, Monday morning, Christmas, early close, and both DST transitions. Date validation rejects holidays, weekends and malformed dates. Browser tests exercise two independent contexts, add/remove across pages, reload, same-origin tabs, explicit clear/reset with confirmation, move order, export/reimport, duplicate normalization, unsupported/version/oversize/injection import rejection, favorites spanning market pagination, no-match versus pending/stale/failed/short history, benchmark rendering, real detail Chart.js canvas, historical current-favorites labeling, explicit full-public reports, blocked/corrupt/quota storage, English/Chinese and 390px no horizontal overflow. Desktop/mobile screenshots and JSON evidence are produced by the reusable acceptance script.

## Compatibility and migration evidence

Tests construct legacy schemas/data, apply migrations repeatedly, and compare price/revision/report/document/delivery/part rows before and after. Private AAPL remains private across initialization. A fresh installation exposes the default nine. Historical private reports remain inaccessible, legacy text retains the public-watchlist scope, and current membership/visibility/owner-label changes cannot rewrite saved breadth. Existing incremental collection, adjustment-repair, provider cooldown, strategy and publication atomicity regression coverage remains.

Upgrade: backup DB/config; migrate/check a restored copy; inspect conflicts; export/check owner config; dry-run; stop old notification scheduling/worker and review pending outbox; keep market scheduling; then the owner may install the independent timer. Rollback pairs the old code/config with a verified pre-upgrade backup restored to a new path. See DEPLOY.md for exact commands.

## Limits

No production deploy, real provider notification, production SQLite migration, live Yahoo whole-market collection or user acceptance was performed. Native systemd/WSL is unavailable on this Windows machine; local unit execution is not claimed. Linux CI includes `systemd-analyze verify`, timezone calendar validation and the real Chromium acceptance script. Remote CI results must be read separately from local results. No unrelated large-scale performance test was repeated. The Hub has no remote idempotency/receipt lookup; network exactly-once is not claimed. The old 04:00 trading-day update schedule can leave Friday data unavailable over a weekend; documentation explicitly describes the frozen delay behavior and requires schedule alignment based on actual runtimes.
