# 322. Bounded Taker Long-Loop Memory And Incremental Tape Persistence [OPEN 2026-07-13 - CUMULATIVE TAPE REWRITES AND RSS SOAK GATE NOT IMPLEMENTED]

Goal: keep the taker paper loop's steady-state memory and per-tick I/O bounded
by its current working set rather than elapsed tick count or cumulative tape
length, while preserving append-only evidence, deterministic recovery,
scoring parity, and the existing no-live-trading posture.

Owner/package: weather.market, weather.operations, weather.reporting

Source: the 2026-07-13 12-hour runtime-monitor incident
`taker-loop-retains-full-payload-history-memory-growth`. The immediate Python
reference leak is repaired under Item 312: `run_loop` now keeps only its latest
payload, and a weak-reference regression proves earlier payloads are
collectible. The broader persistence path still rereads cumulative order and
counterfactual tapes, materializes and scores their full histories, and
rewrites full CSV views on every minute tick.

Observed evidence: before the narrow repair, worker PID 29836 rose from
727.5 MiB to 3,349.1 MiB private memory between 06:10:50Z and 07:57:51Z. The
retained payload surface was about 19 MiB per tick, explaining that incident.
Separately, the same run's cumulative order tape reached about 18.7 MiB and its
counterfactual tape about 170.9 MiB after roughly 104 minutes. Reprocessing and
rewriting those growing tapes explains large transient allocation and I/O
peaks even after historical result references are released.

Post-fix soak evidence through 2026-07-13T08:52:52Z confirms the narrow repair
removed the dominant retention slope but did not close this item. Across 55
one-minute samples, the replacement worker's 10-minute private-memory floor
rose at about 385 MiB/hour versus 1,122 MiB/hour for the superseded worker, a
66% reduction. Its floor still rose from 736.3 MiB to 1,049.1 MiB while
transient peaks reached 1,719.6 MiB as the active counterfactual tape grew to
about 109 MiB. This remaining growth is the bounded-resource and incremental-
persistence work owned here; it is not evidence to recycle an otherwise
healthy, countable paper worker.

Why this matters: Item 312 owns process lifecycle and current-code
re-adoption, Item 239 owns bot disk preflight and settled-run retention, and
Item 273 owns counterfactual evidence semantics. Item 321 is the parent
resource-isolated production-readiness program. None currently requires a
taker private-memory slope, bounded multi-hour soak, or an ordinary tick path
whose read/write work is independent of complete tape length.

## Scope

- [ ] Define explicit taker-loop private-memory, working-set, and per-tick I/O
  budgets, including warmup and growing-tape measurement rules.
- [ ] Expose worker memory, I/O, tick duration, and bounded slope diagnostics in
  daily-roll status and fleet observability without making process existence a
  health claim.
- [ ] Replace ordinary full-history reread/rewrite work with an incremental,
  indexed, or checkpointed path. Keep any full rebuild as an explicit bounded
  recovery or maintenance operation.
- [ ] Preserve deterministic order intent keys, idempotent append semantics,
  counterfactual strategy attribution, cumulative PnL/scoring equivalence, and
  crash recovery from repository-owned artifacts.
- [ ] Add an accelerated growing-tape test and a representative multi-hour
  paper soak proving a constant number of tick payloads remain live and the
  declared post-warmup memory/I/O budgets hold.
- [ ] If a resource-triggered recycle remains necessary, make it supervisor
  owned, backoff bounded, evidence preserving, and fail closed; never delete
  tapes or broaden trading permission as part of recovery.

Acceptance: ordinary paper ticks do not reread or rewrite the complete order
and counterfactual histories; persisted outputs and cumulative scores remain
equivalent across uninterrupted and restart/recovery runs; status and fleet
evidence report the declared resource budgets; and a growing-tape soak passes
the post-warmup private-memory slope, tick-duration, and I/O limits without
manual recycling or evidence loss.

Verification:

- Focused taker persistence, scoring, recovery, and supervisor tests.
- Accelerated growing-tape memory/I/O regression with a deterministic input
  corpus.
- Multi-hour read-only/paper soak report with worker PID identity, artifact
  growth, private-memory slope, peak working set, tick latency, and I/O rate.
- `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint`.

Related: items 95, 152, 161, 239, 273, 312, 321.
