# 322. Bounded Taker Long-Loop Memory And Incremental Tape Persistence [PARTIAL 2026-07-14 - 488-TICK SOAK COLLECTED; ACCEPTANCE REVIEW PENDING]

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
  growing-tape and restart-tail tests pass. A 488-tick scheduled soak has now
  been audited, but its tapes did not grow and its earlier post-warmup slope
  verdicts did not remain continuously passing, so acceptance remains open.
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

## 2026-07-13b adoption and readback plan

The live paper worker was deliberately left untouched. The incremental path is
expected to adopt through the normal 2026-07-14 00:05 daily roll; no restart or
signal will be used to force it early. The first representative readback is
the four consecutive post-training hours ending at approximately 08:15 local.
At 08:20, the persisted diagnostics will be checked for one continuous
PID/process-instance identity, peak private and working set, post-warmup
private-memory slope, per-tick tape and process read/write bytes, tick duration,
and every declared budget verdict. Any process replacement, positive growing
slope, missing tick receipt, or ceiling breach reopens implementation rather
than being averaged away. This checkbox remains open until that evidence is
present.

## 2026-07-14 audited 488-tick soak

The quarantined run at
`data/taker_runs/2026-07-14/_quarantine/taker-20260714-9f58e760__20260714T124945Z/`
contains 488 contiguous resource samples from worker PID 35804 under one
process-instance identity with restart count zero. The complete observation
covered 8.725912 hours (8.73 hours rounded), including 8.473055 post-warmup
hours (8.47 hours rounded). Final private-memory slope was
11.599731 MiB/hour, below the declared 16 MiB/hour ceiling. Peak private memory
and working set were 835.97 MiB and 210.92 MiB, respectively, and maximum tick
duration was 11.227930 seconds.

That final verdict does not by itself satisfy the strict adoption plan above.
There were 364 earlier `WARN` samples, all caused solely by slope above
16 MiB/hour; the last was tick 448 at 16.096031 MiB/hour. Only ticks 449-488
formed the final continuous `PASS` interval, and the final slope remained
positive. The evidence must not average those earlier warnings away.

The run also did not exercise growing-tape behavior. Its event metadata still
targeted 2026-07-13 while the run date was 2026-07-14, so all 12 markets blocked
and the final order and counterfactual row counts were both zero. Persisted
diagnostics nevertheless confirm zero ordinary full-history reads and zero
full-history rewrites. Maximum per-tick tape read/write bytes were 0/10,991;
those bounded writes were not evidence of cumulative-tape scaling. The
deterministic 600-tick regression remains the only populated growing-tape
proof.

This is useful bounded-memory and incremental-I/O evidence, but it is not a
representative populated-tape acceptance soak. The checkbox remains open
pending review of the earlier slope warnings and a current-target-date,
multi-hour paper run that exercises growing order and counterfactual tapes
without a ceiling breach, process replacement, manual recycle, or evidence
loss.

## 2026-07-15 four-hour adoption readback

The current-day run at
`data/taker_runs/2026-07-15/taker-20260715-c318b182/` contributed 218
contiguous persisted samples from ticks 242 through 459 between 04:18:41 and
08:19:39 local, a 4.016-hour interval. Every sample retained PID 56560 and
process-instance ID `ff093a1838ed48cb9cfebe454f972262`; restart count stayed
zero, no tick was missing, and the largest inter-sample gap was 72.183 seconds.

Absolute resource ceilings had ample margin. Private memory ranged from
762.930 to 818.312 MiB and the process peak field reached 832.570 MiB against
the 3,072 MiB ceiling. Working set ranged from 137.965 to 191.051 MiB and its
peak field reached 205.086 MiB against 2,560 MiB. Maximum tick duration was
12.171970 seconds against 55 seconds. Maximum per-tick process read/write was
439,297,352/95,972 bytes against 536,870,912/134,217,728. Ordinary tape reads,
writes, full-history reads, and full-history rewrites were all zero.

The strict slope and populated-tape evidence did not pass. Of the 218 samples,
147 were `WARN` solely for post-warmup private-memory slope. The slope began at
22.896 MiB/hour, peaked at 22.927, and remained positive at 12.271 at the end;
only the final 14 ticks, about 15 minutes, were continuously below the declared
16 MiB/hour ceiling. Although the run target was 2026-07-15, all 12 markets
were blocked because event metadata still said 2026-07-14. Both order and
counterfactual tapes therefore remained header-only with zero rows. There was
also no persisted four-hour host-RAM/commit/disk series from which to claim a
host slope. Item 322 remains open pending one continuously passing,
current-target-date populated-tape soak; the earlier warnings and positive
slope are not averaged away.

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
