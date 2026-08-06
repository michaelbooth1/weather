# Workstation report: fix the watcher stretch

Date: 2026-08-05

Branch: `codex/workstation-fix-the-watcher-stretch-2026-09-14a`

Base: `origin/master @ eeb214c40b1de26ddcf890340d5dac3e0e6fba33`

## Outcome

The observation watcher no longer executes a triggered model snapshot in its
polling iteration. It writes one immutable trigger request to a durable spool
and returns to observation polling. The existing snapshot supervisor checks the
spool every five seconds during its normal idle sleep and consumes it on the
next pass, using the same two-child admission, per-child resource limit,
host-memory reserve, timeout, and 540-second fleet deadline as scheduled
snapshots. A trigger arriving during an active pass waits durably for that pass
to finish.

This is a real separation of the fast and heavy paths, not a higher tolerance:

- watcher tolerance remains 120 seconds;
- maker model freshness remains 900 seconds;
- CLOB gap tolerance remains loop-derived (140.1 seconds in the supplied host
  incident);
- retryable triggered work remains pending rather than disappearing;
- terminal success or failure has a durable receipt and event; and
- the watcher retains its process-start runtime identity instead of replacing
  it with the current filesystem identity on every poll.

The maker CLOB audit also had a correctness defect independent of the incident:
it ignored CLOB-loop startup gaps but did not align its historical-gap window
to the maker's 07:00 active-window start. A 05:30 gap could therefore poison a
07:00–20:00 maker day. The maker now counts only gaps ending after the later of
the CLOB startup-grace cutoff and the maker active-window start. The threshold
is unchanged.

Finally, the paper maker's default loop now freezes at 20:00 America/Toronto.
It no longer runs an old target until the western markets reach local midnight
around 03:00 Toronto the next day.

No process was restarted, re-adopted, reconfigured, or registered. No provider
was called. No release, PIT corpus, promotion gate, trusted observed-high floor,
reservation, live-order path, or production runtime state changed.

## Reservation and evidence boundary

I re-read `docs/operations/reserved-confirmation-window.md`. It says no dates
are reserved; the window is armed but undated until the first retrain candidate
is fitted and frozen. Its five binding rules remain unchanged.

The handoff explicitly says the approximately 11:50 production-host evidence
is invisible to this mirror. The mirror ends at approximately 04:30 Toronto and
contains neither the August 5 maker run nor the later Denver, Los Angeles, and
Miami gap endpoints. I use the handed-off counts and maxima as facts, but I do
not invent timestamps that were not supplied.

## P1 — bounded watcher iteration

### Previous mechanism

`observation_trigger.run_once` performed this call inside its per-market loop:

```text
capture_snapshot(force=True, cadence="triggered", ...)
```

The watcher iteration time therefore included the sum of every triggered
snapshot duration. The retained incident is the constructive counterexample:
six synchronous captures produced a 174.125-second iteration and a maker read
at 152.371 seconds against the 120-second limit.

### New mechanism

The state machine is:

```text
observation poll
  -> atomic pending/<work_id>.json
  -> snapshot supervisor claims inflight/<work_id>.json
  -> existing bounded isolated capture batch
       retryable failure -> pending/<work_id>.json
       terminal result   -> completed/<work_id>.json
  -> watcher publishes observation_triggers.jsonl
  -> compact acknowledged/<work_id>.json tombstone
```

`work_id` is deterministic over market, target, event, current observation
time, and trigger records. A watcher retry cannot duplicate the same queued
observation. At most one item per market is claimed in a snapshot iteration;
additional items remain pending. A triggered request replaces that market's
scheduled request for the current bounded batch, so concurrency never exceeds
the existing admission. The scheduled request remains due and is reconsidered
on the next loop.

The snapshot supervisor still enforces:

| Bound | Value |
| --- | ---: |
| Maximum capture children | 2 |
| Per-child process-tree working-set/private-commit ceiling | 1,792 MiB |
| Host reserve after admission | 1,536 MiB |
| Per-market timeout ceiling | 120 seconds |
| Fleet pass deadline | 540 seconds |
| Trigger-spool check during existing idle sleep | 5 seconds |

This adds no provider-polling loop, no extra empty fleet pass, and no new
concurrent child allowance. The existing sleep is merely interruptible by a
cheap pending-directory check; triggered work moves into the already-admitted
snapshot lane.

### Proof of the watcher bound

The bound is about triggered-snapshot work, exactly as the incident requires.
The managed watcher loop no longer has a call edge to `capture_func`; it can
only perform bounded market trigger detection plus one atomic work-file write
per registered market. A regression test supplies 12 simultaneously triggered
markets and a `capture_func` that fails the test if called. The loop queues all
12, publishes all 12 poll results, and records an iteration below two seconds.
The test passes with the 120-second tolerance unchanged.

This proves that making any queued capture arbitrarily slow cannot add that
duration to the watcher iteration: the capture callable is not entered by the
managed watcher. It does not claim that arbitrary disk failure or arbitrarily
slow observation-provider calls are impossible. Those are distinct loop errors
and remain visible. The watcher now records `last_iteration_elapsed_seconds`,
the last 12 elapsed values, and their maximum so the production bound is
mechanically observable.

### No silent loss

- Enqueue completes before the watcher advances its persisted observation.
  If enqueue fails, that market poll errors and the same observation can be
  retried; it is not marked completed.
- Retryable timeout, fleet-deadline, memory-admission, and process failures
  return the same work item to `pending` with attempt count and last result.
- An orphaned `inflight` file is recovered when the next single-writer snapshot
  supervisor starts.
- Terminal failure is not made quote-permissioned. It is retained as a receipt
  and observation-trigger event; only a snapshot with `written=true` updates
  `latest_triggered`.
- Event publication is at-least-once across a process exit and includes stable
  `work_id`; the persisted watcher deduplication horizon prevents normal
  duplicate publication. Work is never treated as complete merely because it
  left memory.

No load shedding is currently needed. Backlog is explicit in
`trigger_queue.pending_count`; the consumer claims rather than discards.
Compact acknowledgement tombstones are bounded at 4,096 because the canonical
event has already been persisted.

## P2 — the gap window and poisoning semantics

### What the old rule measured

The previous maker preflight called `audit_book_tape` with only:

```text
ignore_gaps_before = clob_loop.started_at + 180 seconds
```

It then scanned every remaining internal gap in the target folder. Therefore,
yes: a gap ending at 05:30 local could block a maker at 07:00 while the latest
book was fresh. That is a window-definition defect, not a reason to loosen
140.1 seconds.

The repaired policy is:

```text
ignore_gaps_before = max(
    clob_loop.started_at + startup_grace,
    target_date at 07:00 in the maker evidence timezone,
)
```

A gap crossing 07:00 or ending after 07:00 is still counted. The active start
and effective policy are emitted in each maker book-audit payload. Focused tests
prove that a 119-minute pre-window gap is ignored while a 300-second gap ending
inside the window still blocks. Neither the configured threshold nor the
loop-cycle-derived effective threshold changed.

### Were the three handed-off gaps inside 07:00–20:00?

The available evidence cannot answer that historical question honestly. The
handoff supplies only maxima (`201.0`, `151.8`, `207.5` seconds), not the earlier
and later timestamps for those gaps, and says the relevant host evidence is
invisible to this mirror. The mirrored August 5 tapes stop before the active
window and show no comparable gap. The handoff's causal statement that the
watcher stretch produced gaps is important, but it is not a timestamp pair.

Consequently I do **not** relabel the three observed blockers as pre-window or
in-window. After deployment, the same audit will make the distinction
mechanical:

- if their later endpoints are at or before the emitted 07:00 cutoff, the gate
  clears them as out-of-window;
- if their later endpoints are after 07:00, all three remain correct blockers,
  even with 11.7-second trailing books.

This branch fixes the proven structural error without widening the gate to fit
the incident.

### Is whole-day poisoning right for 12 markets?

Calendar-day poisoning is wrong; active-window poisoning is right for a
countability claim. A missing interval inside a quote/execution evidence window
cannot later be repaired by a fresh trailing book. The correct result is to
lose that market-day, not silently call it continuous.

The fleet consequence is severe and should be explicit. If a market has daily
breach probability `p`, the expected blocked count is `12p` and the probability
that all 12 are clear is `(1-p)^12`. Treating the latest 3-of-12 incident as
representative would imply only about 3.2% all-clear fleet days, but one incident
is not an estimator. The post-fix soak must measure this. Until it does, planning
should allow for the latest observed residual of three markets, not assume zero.

## P3 — maker rollover

The old default end was the maximum `23:59:59` across every selected market's
native timezone. For an all-market run that kept an August 4 maker alive until
about 03:00 Toronto on August 5, creating exactly the old-target rollover tick
diagnosed in `-09-13a`.

The default maker loop end is now `20:00 America/Toronto` on the target date,
and the loop refuses to begin a new tick at or after that instant. The final
retained run is then passed through the existing scoring-projection finalizer.
Explicit `--until-utc` remains an operator override, and explicitly classified
post-settlement evaluation remains available as a separate one-shot path.

Tests prove the June 16 cutoff is exactly `2026-06-17T00:00:00Z` even when the
selected market is Los Angeles, and that no tick starts at that cutoff. Thus a
07:05 active-day worker self-retires after the evidence window and cannot be
re-adopted as yesterday's live-forward worker while the next day's start gate
waits.

### The 08:33 quarantine

It is separate from this rollover defect and is not expected rollover behavior.
08:33 is inside the active window and on the same target date; the repaired
20:00 boundary cannot cause it. The daily-roll supervisor's code also treats
content statuses `LATEST_TICK_EMPTY`, `INFRA_STARVED_CLOB`, and
`INFRA_STARVED_SNAPSHOT` as non-restartable. A forced same-target quarantine
therefore requires a distinct stale-code or artifact/process-liveness recovery
path, not merely a correct CLOB/useful-work refusal.

The exact 08:33 supervisor receipt is absent from the mirror, so this report
does not choose between stale-code and artifact/process liveness. It classifies
the event as a separate incident requiring that receipt; it is neither the
normal daily boundary nor proof that the gap threshold should change.

## P4 — mechanical pre-window check for all 12 markets

Run this against the exact target date before 07:00 and require every predicate
below for every ID returned by `market_registry.all_specs()`:

```yaml
scope:
  target_date: exact upcoming maker date
  expected_market_count: 12
  selected_market_count: 12
  reservation_declared_for_target: false

runtime_identity:
  snapshot_process_matches_deployed_tree: true
  clob_process_matches_deployed_tree: true
  observation_process_matches_deployed_tree: true
  latest_nested_stale_code_or_blocked_market_count: 0

observation_watcher:
  state: RUNNING
  consecutive_errors: 0
  last_iteration_elapsed_seconds_lt: 120
  max_recent_iteration_elapsed_seconds_lt: 120
  current_per_market_poll_count: 12
  trigger_queue_pending_count: 0
  trigger_queue_inflight_count: 0
  trigger_queue_completed_unacknowledged_count: 0

model_and_sources_per_market:
  latest_target_folder_snapshot_present: true
  matching_source_status_present: true
  model_age_seconds_lte: 900
  source_status_current: true

clob_per_market:
  target_token_and_condition_present: true
  current_book_rows_present: true
  current_band_features_present: true
  trailing_book_age_lte_effective_threshold: true
  maker_active_window_start_is_07_00_local: true
  counted_gap_over_effective_threshold: 0

maker_preflight:
  active_event: PASS
  model_freshness: PASS_12_of_12
  source_status: PASS_12_of_12
  clob_discovery_books_features_freshness: PASS_12_of_12
  observation_trigger: PASS_12_of_12
  useful_work_liveness: PASS_12_of_12
```

Before 07:00 there are not yet any active-window internal gaps, so the CLOB
check proves a fresh tail and correct window binding rather than predicting the
future. The same invariant must remain enforced at every maker tick through
20:00. A promotion/known-edge refusal may correctly produce no quote; it is not
infrastructure starvation. Any freshness or useful-work failure makes that
market-day non-countable.

## Residual after this branch

The honest typical-day blocked count is **not yet estimable** from one later
host incident whose timestamps are missing. The conditional residual is:

- zero markets from the repaired synchronous watcher mechanism itself, because
  triggered capture duration is no longer in the watcher iteration;
- zero markets from gaps wholly before 07:00, because the maker no longer
  measures them;
- every market with a real post-07:00 CLOB gap above the unchanged effective
  threshold remains blocked; and
- the latest observed conservative planning residual is three markets until a
  post-deployment active-window soak shows otherwise.

Two complete 07:00–20:00 windows with all-market gap endpoint evidence are the
minimum useful falsification/soak. A point-in-time green preflight is necessary
but cannot prove the rest of the day.

## Roll safety by actual import closure

The retained production scopes contain 77 snapshot files, 23 CLOB files, and
85 observation-trigger files. Static reverse imports were also checked for the
new file, which could not appear in an old recorded scope.

| File | Verdict |
| --- | --- |
| `src/weather/collection/triggered_snapshot_queue.py` | **Roll-sensitive: snapshot + observation.** Newly imported directly by both protected processes. Not imported by CLOB. |
| `src/weather/collection/snapshot_capture_batch.py` | **Roll-sensitive: snapshot + observation.** Present in both retained scopes because observation imports snapshot tracker. Not in CLOB. |
| `src/weather/collection/snapshot_tracker.py` | **Roll-sensitive: snapshot + observation.** Present in both retained scopes. Not in CLOB. Also imported by maker/taker daily-roll operations. |
| `src/weather/operations/observation_trigger.py` | **Roll-sensitive: observation only.** Present in the retained observation scope, not snapshot or CLOB. |
| `src/weather/market/market_making_run.py` | Capture-roll-free; **maker-worker sensitive**. It is the launched maker worker and is absent from all three capture scopes. |
| `src/weather/market/market_making_run_support.py` | Capture-roll-free; **maker/taker-worker sensitive**. It is absent from the capture scopes but is imported by maker and taker strategy/runtime code. |
| `README.md`, `docs/operations/OPERATIONS_DESIGN.md`, and this report | Roll-free. Not Python runtime inputs. |
| All changed tests | Roll-free. Not runtime imports. |

Unlike `-09-11a` and `-09-12a`, this branch does not edit
`schema_registry_data.py`; it therefore does not force a CLOB roll by registry
closure. It still must deploy only in 01:00–04:00 because snapshot and
observation are streak-critical.

## Integration order and conflicts

Recommended order after Release #1:

1. integrate `codex/workstation-build-the-first-retrain-2026-09-12a`;
2. integrate `codex/workstation-make-mm-days-countable-2026-09-11a`;
3. integrate this branch last;
4. perform one quiet-window re-adoption/verification of the affected capture
   processes, then activate the separately authorized MM execution producer.

This order combines the unavoidable all-three-loop schema rolls from `-09-11a`
and `-09-12a` with this branch's snapshot/observation roll instead of risking a
second Toronto interruption. The two earlier branches both edit
`schema_registry_data.py` and already require integration conflict resolution.

There is no source-code overlap between this branch and either earlier branch.
`-09-11a` overlaps only `README.md` and
`docs/operations/OPERATIONS_DESIGN.md`; preserve both its execution-capture
documentation and this branch's trigger-spool documentation. `-09-12a` has no
path overlap with this branch.

## Exact revert

Once this branch is committed, the code revert is one step:

```powershell
git revert --no-edit origin/codex/workstation-fix-the-watcher-stretch-2026-09-14a
```

Do that only after `pending_count`, `inflight_count`, and
`completed_unacknowledged_count` are all zero; otherwise the old synchronous
implementation would leave durable queued work unconsumed. Merge/deploy the
revert in the same 01:00–04:00 quiet-window procedure and re-adopt the snapshot
and observation processes. The ignored queue directory may remain as audit
state; deletion is neither required nor authorized.

The revert restores synchronous triggered captures, the startup-only gap
cutoff, and the native-market-midnight maker end together. It does not alter or
delete any snapshot, book, maker, queue, or event tape.

## Verification

Passed at report time:

- affected watcher/snapshot/maker slice: 99 tests plus 5 subtests;
- expanded observation, snapshot, collection robustness, maker, maker-roll,
  taker, schema, and import-architecture slice: 275 tests plus 13 subtests;
- focused proof that 12 triggers are queued without entering the capture
  callable and with recorded iteration time below two seconds;
- focused proof that retryable work returns to pending and orphaned inflight
  work is recovered;
- focused proof that the existing bounded snapshot batch receives the exact
  trigger context and emits a durable receipt;
- focused proof of pre-window-ignore/in-window-count gap semantics;
- focused proof of the exact 20:00 Toronto cutoff; and
- `compileall` over `app`, `src`, and `tests`, the agent-docs audit (18 agent
  files and 621 Markdown files), and `git diff --check`.

The unfiltered repository suite completed with 3,291 passed, 820 subtests
passed, 4 skipped, and 17 failures. None of the failing test files or their
implementations is changed by this branch. The failures split into two
workstation constraints:

- the daily-refresh, producer-provenance, and training-window failures were
  PowerShell execution-policy rejections; all of those tests passed when
  rerun with a process-scoped `Bypass` policy; and
- the remaining experiment-executor failures were `WinError 206`/nested
  atomic-write `FileNotFoundError` failures at Windows path-length limits in
  unchanged `experiment_executor.py`/`io.py`. A rerun of all four affected
  files with a process-scoped policy bypass and a short pytest base produced
  50 passed and only those 12 path-length failures.

No provider or production-host command was used by these tests. The policy
bypass was process-scoped, and the short pytest base was test-only scratch.

## What would falsify this

1. A managed observation-loop stack or test showing `capture_snapshot` is
   entered before the watcher publishes all market polls would falsify the
   decoupling claim.
2. A slow triggered capture increasing
   `observation_trigger_status.last_iteration_elapsed_seconds` would falsify
   the bound. Slow observation fetch or disk I/O is a different diagnosed cause
   and must not be mislabelled as trigger work.
3. A retryable child timeout, fleet deadline, or memory-admission block with no
   pending work file or terminal receipt would falsify the no-loss contract.
4. More than two triggered snapshot children, a child without the 1,792 MiB
   ceiling, or admission below the 1,536 MiB host reserve would falsify the
   resource-safety claim.
5. A maker audit that ignores a gap crossing 07:00, or counts a gap ending at
   05:30 solely because it is in the same folder, would falsify the repaired
   window semantics.
6. Host endpoint timestamps showing the Denver, Los Angeles, and Miami gaps
   inside 07:00–20:00 would leave those historical blockers valid; timestamps
   at or before 07:00 would clear them under the corrected rule. Either result
   would resolve, not contradict, the report's stated evidence boundary.
7. A paper worker starting a tick at or after 20:00 Toronto without explicit
   `--until-utc` would falsify the rollover repair.
8. A same-target 08:33 quarantine receipt naming only normal window rollover
   would falsify the classification of that event as separate.
9. Two complete post-deployment active windows with recurring in-window CLOB
   gaps on roughly three markets would falsify any expectation that P1 alone
   makes typical fleet days all-clear and would establish the residual as an
   independent CLOB/resource problem.
10. Any Toronto capture gap caused by merging or re-adopting this branch outside
    the quiet window would falsify the deployment-safety procedure even if the
    code tests remain green.
