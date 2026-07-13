# 322. Bounded Taker Long-Loop Memory And Incremental Tape Persistence [PARTIAL 2026-07-13 - INCREMENTAL PATH AND RESTART TESTS LANDED; MULTI-HOUR SOAK PENDING]

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

Full-run post-fix soak evidence confirms the narrow repair removed the dominant
lifetime-retention slope but did not close this item. Replacement worker PID
45132 ran for about 5.6 hours with 336 one-minute resource enrichments. Its
deep-release floor settled near 1.55-1.59 GiB with a roughly 39 MiB/hour slope,
about 96.5% below the superseded worker's 1,122 MiB/hour floor slope. Across
all samples its private memory was 736.3 MiB minimum, 2,294.7 MiB median,
4,524.5 MiB p95, and 6,226.1 MiB maximum. Fifty of 51 observed episodes above
3 GiB released to 2.5 GiB or less within 1-3 minutes (1.001-minute median),
which is inconsistent with recurrence of the repaired strong-reference leak.

The same soak also proves why this item remains urgent. Ordinary ticks still
reread, rescore, and rewrite complete growing histories, producing transient
allocation and I/O peaks whose magnitude rises with tape length. Host physical
availability reached 32.2 MiB at 12:09:55Z while the taker held 5,462.8 MiB
private memory, even though commit was only 52.818%; commit-only protection is
therefore insufficient. The final high-allocation episode did not show a deep
release before the supervisor replaced PID 45132 at 13:34Z under a stale-
heartbeat classification. The current-code replacement started near 810 MiB
private and remained below 936 MiB through the monitor boundary. Lifecycle
evidence does not establish an OOM and this item does not attribute that
replacement to one; it requires a bounded incremental path so neither growing
peaks nor resource-triggered recycling are necessary.

Why this matters: Item 312 owns process lifecycle and current-code
re-adoption, Item 239 owns bot disk preflight and settled-run retention, and
Item 273 owns counterfactual evidence semantics. Item 321 is the parent
resource-isolated production-readiness program. None currently requires a
taker private-memory slope, bounded multi-hour soak, or an ordinary tick path
whose read/write work is independent of complete tape length.

## Scope

- [x] Define explicit taker-loop private-memory, working-set, and per-tick I/O
  budgets, including warmup and growing-tape measurement rules.
- [x] Expose worker memory, I/O, tick duration, and bounded slope diagnostics in
  daily-roll status and fleet observability without making process existence a
  health claim.
- [x] Replace ordinary full-history reread/rewrite work with an incremental,
  indexed, or checkpointed path. Keep any full rebuild as an explicit bounded
  recovery or maintenance operation.
- [x] Preserve deterministic order intent keys, idempotent append semantics,
  counterfactual strategy attribution, cumulative PnL/scoring equivalence, and
  crash recovery from repository-owned artifacts.
- [ ] Add an accelerated growing-tape test and a representative multi-hour
  paper soak proving a constant number of tick payloads remain live and the
  declared post-warmup memory/I/O budgets hold. The accelerated deterministic
  growing-tape and restart-tail tests pass; the representative scheduled paper
  soak remains outstanding.
- [x] If a resource-triggered recycle remains necessary, make it supervisor
  owned, backoff bounded, evidence preserving, and fail closed; never delete
  tapes or broaden trading permission as part of recovery. The incremental
  path does not introduce a resource-triggered recycle; budget breaches are
  advisory and leave existing supervisor/liveness semantics unchanged.

## Implementation evidence (2026-07-13)

- `weather.market.taker_bot_incremental` keeps the CSV order and
  counterfactual tapes append-only and stores a rebuildable SQLite intent index,
  bounded filled-position state, cumulative counters, and byte checkpoint.
  Ordinary ticks neither reread nor rewrite either complete tape. A restart
  with a current checkpoint reads zero tape bytes; a crash between CSV append
  and checkpoint commit replays only the uncheckpointed byte tail without
  rescoring it.
- Cumulative PnL is rebuilt from the policy-bounded filled-position set plus
  incremental reason/strategy/benchmark counters. Existing deterministic
  intent keys and counterfactual attribution remain on the canonical CSV rows.
  A one-tick SQLite outbox binds the exact order, counterfactual, and budget-
  ledger batches; restart completes missing phases without duplicating durable
  tails. Settlement-sensitive benchmark inputs are retained per bounded
  snapshot group, refreshed in bounded batches against one captured label
  generation, and block promotion while any group is stale. A one-time
  streaming migration rebuilds those groups and the canonical NO-side
  strategy/market/hour dimensions from pre-upgrade tapes.
- Explicit `--fresh` preserves the prior generation under the sibling
  `<runs_root>_fresh_archives/<target-date>/` root before creating an empty
  active run folder. This prevents a stale SQLite byte checkpoint from being
  paired with rewritten tapes without exposing archived evidence to active-run
  discovery or finalization.
- Each tick reports current private bytes, working set, process and tape I/O,
  duration, warmup state, and a restart-safe post-warmup private-memory slope
  against declared budgets. The checkpoint retains one compact diagnostic row
  per tick for later soak reporting. Daily-roll and fleet readers expose the
  latest fields as advisory evidence; tests retain the existing non-terminal
  empty-tick and tri-state process-liveness behavior.
- Focused deterministic verification after settlement-generation, tail-
  migration, and phase-crash review: taker persistence/scoring suites `89`
  passed plus `8` subtests; daily-roll/storage suites `35` passed plus `25`
  subtests; schema registry `7` passed; agent-doc audit passed.

Remaining proof: run the representative multi-hour paper soak outside Stage A
and the protected near-close window, then record worker PID continuity,
post-warmup private-memory slope, peak working set, tick latency, and tape I/O
against the declared budgets. No live worker or local trading evidence was
touched while landing this implementation.

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
