# Daily use S0–S4 results

Baseline: latest fetched `origin/main` = `b35ab1ddf68924efd581c3258992d43edea65de4`, 2026-10-21. Branch: `codex/daily-use-s1-s4`. Clean isolated clone; no existing work overwritten. No applicable AGENTS.md found. Read the full implementation plan, review, README, DEPLOY, DEPLOY_QA and relevant source. User authorized continuous S0–S4, one Draft PR; no merge, VPS action or real messaging.

## Status and decisions

- **S0 complete:** centralized settings, opaque expiring admin sessions, CSRF, persistent login limiting, default-private watchlist, additive transactional migrations and new-target-only backup/restore.
- **S1 complete:** database configuration authority, strict configuration-only API, closed XNYS sessions, explicit yfinance adjusted basis, immutable source revisions, singleton durable jobs, lease fencing, independent worker. Both allowed triggers use `request_update`; GET performs no source call or calculation.
- **S2 complete:** fixed Stage2 missing benchmark/20-session boundary/aligned dates, run-scoped input loader, complete condition denominators, ordered evaluations, failed versus successful exits, preserved entry dates, atomic results/pointer/report publication. Zero remains zero; old report inputs remain pinned. Rule IDs are `stage2_us`, `contraction_us`, `bottom_fisher_us`, `checklist_us`, version `v1`.
- **S3 complete:** functional bilingual warm UI; database prices independent of matches, precomputed technical details, saved conditions, CSV, private/admin boundaries, add/disable/update/progress. Browser at 360 and 1440 pixels, including real and isolated fault data.
- **S4 complete implementation:** independent New York schedule, immutable reports and segmented durable delivery outbox, actual notification-hub adapter/receipt validation, conservative unknown/partial handling, settings/test/status controls, separate startup processes. Final capacity run and remote CI evidence are being completed below.

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
python -m pytest -q --basetemp=../test-temp-08
# 32 passed, 1 warning, 77.71 s
python -m pytest tests/test_strategies.py::test_twenty_elapsed_sessions_and_benchmark_date_alignment -q --basetemp=../test-temp-09
# 1 passed, 1.82 s (added boundary-specific regression)
node --check web/static/js/main.js
python -m compileall -q lib web scripts
python -m scripts.verify_hub_contract --checkout ../notification-hub
# pinned actual hub app: 6 contract cases passed, external sends = 0
python -m scripts.capacity_check --database ../capacity-final.db --output ../capacity-result.json
# 5,000 stocks + four benchmarks, 252 bars each; complete pipeline/concurrent HTTP reads
```

Real run `c4b72f44a99842ba90be70036da53c28`: triggered by administrator browser button, independent `python -m lib.cli worker --once`, actual yfinance (no substitute), target **2026-10-20**. AAPL/MSFT/SPY/QQQ/IWM/^VIX each returned **550** sessions, 2024-08-12 through 2026-10-20; 3,300 verified bars and 30 strategy/technical results, all available. Published candidates: Stage2 2, contraction 2, countertrend 0, Checklist 2. Real report and restored copy verified; no notification delivery queued or sent. Full details in `evidence/real-market-validation.json`.

Browser: actual Uvicorn on loopback. Real data `/` /watchlist /ticker/AAPL /admin; separate isolated synthetic host/database for missing/stale/short/private rows. 360px detail document width 345px with 281px chart; no horizontal overflow or JS errors after fixes. Initial browser verification found a JS syntax error and default GET login form; both fixed, POST fallback and JS syntax CI added. Process kill test initially terminated only the Windows venv launcher; now kills the actual worker PID and passes. Screenshots in `evidence/` distinguish real and synthetic validation.

## Remaining evidence and limits

- Capacity: final 5,000-stock run in progress; final measured database size/time/RSS/HTTP latency/lock results will replace this line. An initial exploratory run was interrupted to improve last-connection WAL checkpoint overhead; it is not claimed as completed capacity acceptance.
- Remote CI / Draft PR: publishing through the connected GitHub API because local Git credential helper fails under the Windows sandbox. The final remote commit and CI result will be recorded after publication.
- No thousands-symbol live Yahoo test, production Docker/VPS execution, real Telegram/Email send, or production recovery drill is claimed. Synthetic capacity is not a full-market network benchmark.
- Hub cannot prove remote exactly-once or query an uncertain receipt; the app surfaces that limitation instead of retrying blindly.

Startup and manual acceptance: follow README/DEPLOY, initialize admin, start web/worker/scheduler/notify-worker with one DB, add symbols, Update data, reopen progress, inspect same-date report/CSV; save notification settings without sending. Test send requires intentional action and real credentials only after separate authorization.

S5 checklist (not executed): production backup+isolated restore, confirm volume/path/TLS/cookies, disable old cron/direct Telegram, start four processes, verify real NY 04:00/06:00 and DST/holiday behavior, authorize real channel receipt test, monitor locks/disk/leases, and run rollback drill. See DEPLOY.md for exact operational steps.
