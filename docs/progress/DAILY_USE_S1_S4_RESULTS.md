# Daily use S0–S4 results

Baseline: latest fetched `origin/main` = `b35ab1ddf68924efd581c3258992d43edea65de4`, 2026-10-21. Branch: `codex/daily-use-s1-s4`. Clean isolated clone; no existing work overwritten. No applicable AGENTS.md found. Read the full implementation plan, review, README, DEPLOY, DEPLOY_QA and relevant source. User authorized continuous S0–S4, one Draft PR; no merge, VPS action or real messaging.

## Status and decisions

- **S0 complete:** centralized settings, opaque expiring admin sessions, CSRF, persistent login limiting, default-private watchlist, additive transactional migrations and new-target-only backup/restore.
- **S1 complete:** database configuration authority, strict configuration-only API, closed XNYS sessions, explicit yfinance adjusted basis, immutable source revisions, singleton durable jobs, lease fencing, independent worker. Both allowed triggers use `request_update`; GET performs no source call or calculation.
- **S2 complete:** fixed Stage2 missing benchmark/20-session boundary/aligned dates, run-scoped input loader, complete condition denominators, ordered evaluations, failed versus successful exits, preserved entry dates, atomic results/pointer/report publication. Zero remains zero; old report inputs remain pinned. Rule IDs are `stage2_us`, `contraction_us`, `bottom_fisher_us`, `checklist_us`, version `v1`.
- **S3 complete:** functional bilingual warm UI; database prices independent of matches, precomputed technical details, saved conditions, CSV, private/admin boundaries, add/disable/update/progress. Browser at 360 and 1440 pixels, including real and isolated fault data.
- **S4 complete implementation:** independent New York schedule, immutable reports and segmented durable delivery outbox, actual notification-hub adapter/receipt validation, conservative unknown/partial handling, settings/test/status controls, separate startup processes. Capacity, real-source, browser and local regression evidence are complete below; production S5 remains unexecuted.

Market Lab style reference read at `c13f613a670301962003f75ee2da77ae550bd761`; only palette/type/layout adopted. Stack retained. Existing strategy thresholds retained. Checklist weekly data remains **provisional**, explicitly labeled. Old collection/strategy CLIs and deployment/cron scripts now fail with the replacement instructions; there is no competing direct Telegram schedule. Old CSVs/databases/history were not deleted.

Hub source inspected and executed at `7c6ef039047e9adae7c6ca14d4e32204f352957c`: Bearer `POST /api/v1/notify`, actual schema and `sent|partial` receipt. It has **no idempotency key or delivery lookup**. Unknown/partial results are held for human reconciliation without resend. A crash after remote acceptance cannot be proven exactly-once. Provider calls in contract tests are intercepted only at Apprise; no real message sent.

## A01–A19 acceptance matrix

| ID | Implementation | Executed verification and result |
|---|---|---|
| A01 | queries, DB-only routes, precomputed technical | `test_all_gets_read_only_no_download_or_calculation`: all source/calculator entrypoints fail if invoked; GET pages/API/CSV/report pass |
| A02 | auth middleware, sessions/CSRF/rate limiting | foundation tests reject anonymous writes, missing CSRF, expired logout session; rate limit persisted |
| A03 | config, jobs dependencies, configuration API | add/disable + JSON sync regression; stored `yf_ticker` and fixed benchmark dependencies retained |
| A04 | singleton unique index, enqueue/claim IMMEDIATE transactions | 16 concurrent manual/scheduled submissions → one ID; 8 concurrent claimers → one owner |
| A05 | worker leases/heartbeats/fencing | real browser closed at 5/6; published after reopen. Actual subprocess killed, expired lease reclaimed, attempt=2, one publication/25 results; superseded owner rejected |
| A06 | XNYS calendar, NY schedule | Christmas, early close, DST, New Year, duplicate due checks; legacy offline weekday reproduction now uses actual calendar |
| A07 | source/strategy statuses, complete totals | missing SPY remains total 8; absent aligned date is insufficient; short history retains price; missing volume remains null; provider failure explicit |
| A08 | immutable revisions and per-run loader | cache reproduction + second full run source revision; current prices change, first batch prices/report frozen |
| A09 | ordered Stage2/VCP and successful transition only | actual full pipeline leaves Stage2 pool → VCP exit; zero displayed; calculation exception preserves prior state; sustained entry date unchanged |
| A10 | batch-pinned queries | injected old legacy signal never becomes latest; first-batch candidates remain historical only |
| A11 | every explicit update recomputes results | same-input/no-new-row run saves fresh results; isolated failure/short-history states distinguish unknown signal |
| A12 | fixed auto_adjust, filtering/normalization, overlap revision detection | unfinished bar excluded, invalid OHLC/missing volume marked; 3 source retries all preserve auto_adjust=True; revision full-chain covered |
| A13 | one evaluator pass / strategy, atomic publication | exactly five results per asset/run; repeated candidate entry keeps date/price; transition uniqueness and duplicate scheduling tested |
| A14 | one batch pointer + snapshots | real six-asset audit checks dates/prices/technical/report; CSV and detail pinned to same input watermark; no mixed latest-strategy fallback |
| A15 | strict request models, no numeric write routes | administrator extra `close` rejected; prices/indicators/results/import endpoints absent; old CSV utility is read-only audit |
| A16 | source revision rows + immutable report | full-chain correction changes current series without changing previous report/chart; notify schedule key prevents historical auto-resend |
| A17 | delivery/part state machine | actual hub contract plus fault tests: safe connection retry, partial, unknown read timeout, lease crash, duplicate schedule, long split/retry; successful parts not resent |
| A18 | complete-range CSV, SQLite backup API | >500 row CSV equals pinned history; legacy and full published DB backup restored into new file; integrity and rows checked; overwrite rejected |
| A19 | request-local language + responsive templates/CSS/Chart.js | bilingual concurrent render tests; real 1440/360 browser, empty/pending/failed/stale/short history; login/add/update/close/reopen/save/search; no private entry or raw owner token |

Review's five offline findings have repository regressions: holiday (`test_calendar_boundaries`), missing benchmark (`test_missing_benchmark_keeps_all_eight_conditions`), cache (`test_no_cross_run_cache` plus revision integration), VCP zero (`test_leaving_stage2_pool_clears_vcp_via_real_chain`), and historical fallback (`test_old_legacy_signals_never_appear_as_latest`).

## Commands and evidence

Windows 11 build 26200; Python 3.12.14; 4 logical CPUs; ~15.95 GiB RAM. Runtime versions pinned in requirements. Tests use distinct disposable databases under `work/`, never the real preview database. Local tests include Starlette's deprecation warning for its httpx TestClient; no test was skipped or assertions relaxed.

```text
python -m pytest -q --basetemp=../test-temp-15
# 38 passed, 1 warning, 43.87 s; publication rollback/concurrent reads, malformed receipts, provider cooldown
python -m pytest tests/test_provider_guard.py -vv -s --basetemp=../test-temp-16
# 2 passed, 2.99 s
node --check web/static/js/main.js
python -m compileall -q lib web scripts
python -m scripts.verify_hub_contract --checkout ../notification-hub
# pinned actual hub app: 6 contract cases passed, external sends = 0
python -m scripts.capacity_check --database ../capacity-final.db --output ../capacity-result.json
# 5,000 stocks + four benchmarks, 252 bars each; complete pipeline/concurrent HTTP reads
```

Real run `c4b72f44a99842ba90be70036da53c28`: triggered by administrator browser button, independent `python -m lib.cli worker --once`, actual yfinance (no substitute), target **2026-10-20**. AAPL/MSFT/SPY/QQQ/IWM/^VIX each returned **550** sessions, 2024-08-12 through 2026-10-20; 3,300 verified bars and 30 strategy/technical results, all available. Published candidates: Stage2 2, contraction 2, countertrend 0, Checklist 2. Real report and restored copy verified; no notification delivery queued or sent. Full details in `evidence/real-market-validation.json`.

Browser: actual Uvicorn on loopback. Real data `/` /watchlist /ticker/AAPL /admin; separate isolated synthetic host/database for missing/stale/short/private rows. 360px detail document width 345px with 281px chart; no horizontal overflow or JS errors after fixes. Initial browser verification found a JS syntax error and default GET login form; both fixed, POST fallback and JS syntax CI added. Process kill test initially terminated only the Windows venv launcher; now kills the actual worker PID and passes. Screenshots in `evidence/` distinguish real and synthetic validation.

## Capacity, provider safeguards and limits

- Capacity completed: 5,000 synthetic stocks + four benchmarks × 252 sessions = **1,261,008 bars**, 25,020 successful results, one atomic publication. **1,884.08 s (31m24s)**, **753.46 MiB** database, **134.72 MiB** peak sampled RSS. During update, 720 HTTP reads: p95 **0.998 s**, max **1.424 s**, zero HTTP/lock errors. Published dashboard/detail/watchlist HTTP: 1.339 / 0.114 / 1.898 s. Independent integrity check and all 5,004 asset / 25,020 result statuses passed. RSS was periodically sampled, not absolute OS peak; host also ran other verification. See evidence/capacity-validation.json. An initial exploratory run was interrupted to improve WAL checkpoint overhead and is not counted.
- Draft PR [#2](https://github.com/captainamari/stock-tracker/pull/2), branch codex/daily-use-s1-s4. Earlier complete code at 6a980caa passed [remote CI](https://github.com/captainamari/stock-tracker/actions/runs/39597124750) (33 tests + compile + JS syntax + actual hub contract). Final follow-up adds five tests and the provider guard; the final SHA-specific CI status is tracked on this same Draft PR. Publishing uses the connected GitHub API because the local Windows Git credential helper is unavailable; every uploaded tree SHA is verified against its local commit.
- Docker Compose configuration validated; Docker daemon was unavailable, so image build/container runtime remain unverified. No thousands-symbol live Yahoo test, production Docker/VPS execution, real Telegram/Email send, or production recovery drill is claimed. Synthetic capacity is not a full-market network benchmark. At the default five seconds between history calls, 5,004 assets alone take at least about 6h57m, excluding network, retries and calculation; the synthetic result does not establish completion before 06:00.
- Hub cannot prove remote exactly-once or query an uncertain receipt; the app surfaces that limitation instead of retrying blindly.

Startup and manual acceptance: follow README/DEPLOY, initialize admin, start web/worker/scheduler/notify-worker with one DB, add symbols, Update data, reopen progress, inspect same-date report/CSV; save notification settings without sending. Test send requires intentional action and real credentials only after separate authorization.

S5 checklist (not executed): production backup+isolated restore, confirm volume/path/TLS/cookies, disable old cron/direct Telegram, start four processes, verify real NY 04:00/06:00 and DST/holiday behavior, authorize real channel receipt test, monitor locks/disk/leases, and run rollback drill. See DEPLOY.md for exact operational steps.


## Yahoo request policy and reusable real data

The unified worker makes sequential history calls, reuses stored history, and rechecks a 45-day overlap (800-day window for missing history or source revisions). Migration 005 persists pacing across processes: five seconds minimum between history-call starts. One yfinance call may issue multiple HTTP requests, so this is not an HTTP quota guarantee. Rate-limit exceptions / HTTP 429 stop the entire run without trying remaining assets or replacing the published batch, and persist a six-hour cooldown. Failed runs remain inspectable; manual attempts during cooldown make no source calls. No automatic retry at cooldown expiry; the next explicit or scheduled update can try again. Other failures have at most three attempts with 10/30-second backoff. The admin progress message shows the pause deadline. Both intervals are configured in .env.example, with conservative lower bounds. Tests verify one network call on rate limiting, restart persistence, expiry and lock-free pacing waits. These are precautions, not proof that Yahoo cannot restrict a VPS IP. Reference: [yfinance rate-limit exception](https://github.com/ranaroussi/yfinance/blob/main/yfinance/exceptions.py).

The 1.26 million capacity bars are **synthetic and never deployment data**. Only the separate 3,300 real bars are reusable. SQLite databases are excluded from Git; git pull transfers code only. A separately delivered 2,023,424-byte real bootstrap backup has been restored and integrity-checked, with temporary admin/session/login/notification state removed from the new copy. SHA-256: 5dec3fc72657ab4eb0c936ad6a05422f97c04bcb7d52ae28afd6afe3f10d8144. It contains only AAPL/MSFT/SPY/QQQ/IWM/^VIX through 2026-10-20, 30 saved results and one publication. It is for a fresh installation, never a replacement for an existing VPS database. Frozen report links retain their original localhost URL; future reports use production PUBLIC_URL. Notifications default disabled and a new administrator must be initialized.

## Stage commits

| Stage | Published commit |
|---|---|
| S0 | 82162ab5ac81615013da549f417f00cc0ab0b6be |
| S1 | 545bc57a2040c07c0120845216fd02c786f2f16d |
| S2 | a78f96de4a64fa5aa6286fb702e6267c7af1fd29 |
| S3 | 11eb915e82fdbfa159e00545547979724bf0a2ff |
| S4 | 0b2b10cfa558be44a21833450f05575bc672442b |
| Recovery/source validation | 6a980caa1c43ca83c0832a73f8d94bfb9e7bc126 |

Final follow-up and its evidence are included in the same PR; no main merge or production cutover was performed.
