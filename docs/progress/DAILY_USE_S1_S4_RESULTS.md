# Daily use S0–S4 results

Baseline: origin/main `b35ab1ddf68924efd581c3258992d43edea65de4` (fetched 2026-10-21).
Branch: `codex/daily-use-s1-s4`. Clean isolated clone; no existing work overwritten.
No applicable AGENTS.md found in repository or workspace ancestors.
Read planning/review, README, DEPLOY, DEPLOY_QA and actual source. User authorizes continuous S0–S4; S5 and real messaging excluded.

## Implementation and acceptance map (in progress)

| Scope | Findings | Implementation | Verification |
|---|---|---|---|
| S0 / R01 | unauthenticated writes, no migration/backup framework | settings, auth, migrations, backup | foundation tests |
| S1 / R02–04,09,12,14 | JSON authority, HTTP-owned execution, wrong dates/basis | persistent queue, worker, calendar, provider | concurrency, interruption, real provider |
| S2 / R05–08,10–11,13 | stale signals/cache, incomplete dependencies | strategy service, revisions, publications | five reproductions + integration |
| S3 / R16 | global language filters, dark UI | routes/templates/CSS/JS | mobile/desktop bilingual browser |
| S4 / R15 | direct Telegram, mutable reports | frozen snapshots, hub adapter | pinned real hub contract |

Hub inspected at `7c6ef039047e9adae7c6ca14d4e32204f352957c`: Bearer POST `/api/v1/notify`, title/message/channel/level/source/metadata; `sent|partial` response. No idempotency or delivery lookup. Unknown/partial deliveries require explicit resolution, never blind retries.
Market Lab visual reference tree accessible at `c13f613a670301962003f75ee2da77ae550bd761`; use plan palette and existing FastAPI stack.

Stage status: S0 implementation in progress; S1–S4 pending. No production or real notification acceptance claimed.
