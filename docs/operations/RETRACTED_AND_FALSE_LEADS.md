# Retracted Claims and False Leads

Status: canonical. Written for LLM agents.

| | |
| --- | --- |
| **Owns** | Claims that look true, or were once believed, and are not: what it looked like, what is true, why it fooled us. |
| **Read when** | You have a surprising result, are about to "discover" something, or are about to cite a number you did not measure today. The one-line list of retired numbers is in [FINDINGS_DIGEST.md](FINDINGS_DIGEST.md); come here for the mechanism. |
| **Do not use for** | What survived ([ESTABLISHED_FINDINGS.md](ESTABLISHED_FINDINGS.md)); the recurring shapes behind these entries ([HOW_WE_GET_THINGS_WRONG.md](HOW_WE_GET_THINGS_WRONG.md)). |

**Everything in this file looks true, or was once believed true, and is not.** Each entry cost real
agent hours at least once. Sections: §1 model claims · §2 statistical traps · §3 operational false
alarms · §4 backlog and branch traps · §4a maker-economics traps · §5 how to add an entry.

---

## 1. Retracted model claims

### The 24.69% absorption claim — RETRACTED

Published, then found to **cross zero under crossed date x market clustering**. It was produced with
exchangeable market-day resampling, which yields intervals that are too narrow.

**Do not cite it.** The correct served figure is **18.32%**.

### The 5.39% figure — RETRACTED as described

It was a **separately fitted transform**, not a propagated one. The real served value is **18.32%**.
A separately fitted transform measures what a fresh fit could achieve, not what the deployed pipeline
does — those are different claims and the difference is the whole point.

### The 78% absorption leak — NEVER EXISTED

It was **mismatched denominators**, not a leak. Time was spent hunting a defect that was an
arithmetic artifact. **Only the floor's absorption interval excludes zero. The floor stays.**

### item-224's "win" over the market — LEAKAGE

The one result that appeared to beat the market was leakage. Toronto parity is **underpowered, not a
win**. Any future claim of beating the market must clear the method rules in `ESTABLISHED_FINDINGS.md`
§5 before it is reported as real.

### The age-curve evidence for the cool bias — DIED 2026-08-05

Do not build on it. The cool bias itself survives (`ESTABLISHED_FINDINGS.md` §2); the *age* mechanism
explanation does not.

### Blindness as the cause of centre displacement — REJECTED

Intuitive, and wrong. In the excluded lane, blindness moves the centre **warmer** (`+0.005453` bands)
while the served displacement is `-0.297504` bands **cooler**. Blindness destroys information; it is
not the centre mechanism. The actual mechanism is floor truncation (`ESTABLISHED_FINDINGS.md` §2).

### "The gap is 1.7x" — CONTAMINATED WINDOW

On the clean regime it is **1.24x**. The larger figure came from windows mixing artifact regimes.

### "Recalibration will close the gap" — FALSE BY DECOMPOSITION

98.88% resolution / 1.12% reliability. There is almost no calibration error left to harvest. The gap
is information. Calibration work is not a path to edge.

### "Production served 0.0 on the realized band" (Denver 2026-06-08) — REPLAY ARTIFACT

- **What it looked like:** `-09-63a` failed closed at Gate 3 on a row where the incumbent put exactly
  zero on the winning band; the panel showed 28 such rows in B.
- **What is true:** production served **0.5206** on that row. Replay rebuilt a floor of 91 from
  yesterday's `max_since_7am_c` before dawn; the served floor was 68. Only **two** B zeros come from
  a floor actually served (Chicago 2026-06-14, San Francisco 2026-06-09); a third is a blank-floor
  fallback row. `ESTABLISHED_FINDINGS.md` §1j, §1k (`-09-65a`, `-09-66a`, `-09-68a`).
- **Why it fooled us:** the panel's feature row and floor are reconstructed by replay code, not the
  values serving recorded, and nobody had joined the two. A fail-on-any-row gate then turned one
  artifact row into a retired decision.

### "Realized-band zeros are a live serving defect at 1.017%" — WRONG REGIME, WRONG TENSE

- **What it looked like:** 1,017 of 100,040 served snapshots carried a zero on the realized band.
- **What is true:** the rate was **8.486%** of Fahrenheit rows before commit `28d1c146` (2026-06-15)
  and **0.000%** after. There is nothing to patch in serving.
  [SERVED_BAND_FLOOR_DEFECT_2026-08-10.md](SERVED_BAND_FLOOR_DEFECT_2026-08-10.md).
- **Why it fooled us:** a pooled rate averaged across a fix. The first version of the trace document
  was cited in a handoff before it was corrected.

### "The 11 extra PIT fields are untested, not disproven" — STALE SINCE 2026-09-02

EF §1g (2026-08-10) said the fields were untested, making the re-fetch the top item. The fetch ran 2026-08-10 and the
fields were tested three times on the unmerged workstation research lineage (EF §1m): a pooled-refit replacement
worsened the C-pre centre; an NWP-anchored residual challenger was `INCONCLUSIVE_UNDERPOWERED` (2025 May-Aug +0.2751 C²
[−0.0234, 0.6186]), directionally consistent in 2026, near zero outside the window. Still not disproven; no longer
untested. It fooled us because the reports sat on unmerged branches whose ids were reused by later production missions.

### "`high_so_far` is a running maximum" — FALSE

- **What it looked like:** a day's high so far can only rise, so a fall must be a rare pre-dawn
  fallback.
- **What is true:** it fell 906 times in B and 1,284 times in C. In B, 40.62% of falls sit in the
  peak-heating or settlement window, because the vendor observation series drops rows and the cutoff
  follows the latest retained row backward (658 of 658 cutoff changes narrowed).
  `ESTABLISHED_FINDINGS.md` §1k (`-09-70a`, `-09-71a`).
- **Why it fooled us:** the name describes the intent. The input it is computed from is not
  append-only, and the expectation was checked on C, where it happens to hold.

### "Union every observation ever published and the floor is safe" — UNSAFE

- **What it looked like:** an append-only envelope repairs all 658 cutoff events and every
  decision-window event.
- **What is true:** it also freezes a transient print into the trusted floor: **55 new
  above-settlement rows**, all San Francisco 2026-06-09 (68 °F published, 67 settled). The safe rule
  recovers a row only when the current payload has nothing at or after its minute: 744 of 906 events,
  zero new above-settlement rows on 28,254 snapshots. `ESTABLISHED_FINDINGS.md` §1k (`-09-72a`,
  `-09-73a`).
- **Why it fooled us:** "cosmetic in the mean" is not "safe in the extreme". A floor error is a hard
  zero on the winner.

### "`M1_restatement` rows are restatements, so filter on `M5 ∪ M3`" — THE LABELS WERE WRONG

- **What it looked like:** excluding the two `M1` rows gave a tidy 736-event repair with no unsafe
  row.
- **What is true:** both B `M1` rows are timestamp **replacements** (one row vanished, a later one
  appeared), not same-timestamp restatements. The filter was fitted to a label error and is post hoc:
  it defines no value for non-event snapshots and cannot be served. `-09-73a`.
- **Why it fooled us:** the rule was written over our own mechanism labels instead of over what the
  payload shows at capture time.

### "Check out the recorded runtime commit and replay reproduces what we served" — FALSE

- **What it looked like:** each replay record carries a runtime commit and a model identity; one
  Austin market-day had matched to `2.23e-16`.
- **What is true:** 114 of 358 commit-bound decision rows match (31.84%); identity binding gets 105
  (29.33%) and rescues none. **0 of 368** decision rows and 111 of 28,254 B rows are exactly
  reconstructable, because production served working-tree bytes that were never committed.
  `ESTABLISHED_FINDINGS.md` §1k (`-09-74a`..`-09-76a`);
  [REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md](REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md).
- **Why it fooled us:** the identity fingerprint reads files from disk at capture time while
  `git_commit` records `HEAD`; roll-free commits move `HEAD` without restarting the process. One
  passing market at diagnostic grade was generalised to "reproduces".

### "The 0.4720 repair ceiling clears the detectable effect, so the look is worth its α" — A BOUND WITH NO SIGN

- **What it looked like:** `-09-77a`'s outcome-free ceiling (mean 0.4720, upper 0.6423) exceeded the
  detectable effect 0.2164.
- **What is true:** that statistic bounds the candidate's maximum **cost**, is non-negative by
  construction, and made the NO-GO branch unreachable. On the real estimand the look is unpowered
  (MDE 0.1571 against a most-favourable effect of 0.1385) and the repair mostly sharpens (254 of 368
  rows). Thread closed, α kept. `ESTABLISHED_FINDINGS.md` §1k (`-09-78a`).
- **Why it fooled us:** the commissioning handoff specified a screen that could not fail. Prove both
  decision branches reachable before reading data.

---

## 2. Statistical traps

### The slice gate was a lottery

False rejection rate **99.885–99.9905%** — it rejected a **better** candidate. **Every slice-gate
rejection in that month is uninformative.** Do not treat a historical rejection as evidence about a
candidate's quality.

### The 5-date window was a convention, not a constraint

**We have 34 date clusters.** Analyses limited to 5 dates were self-limiting for no reason.

### `quality_grade == "complete"` is NOT the admission bar

The bar is **`promotion_countable`**. The complete-only bar starved a previous corpus and produced
underpowered results that were then misread as null findings.

### `market_day_labels.csv` is NOT the settlement authority

**`data/settlements/<market>/ledger.jsonl` is.** The CSV is a projection and can disagree.

### `2026-07-31` is not a date cutoff

It is an **artifact-provenance regime boundary**. Filtering by target-date age instead of artifact
provenance silently mixes regimes. Anchor commit: `b77cfbed`.

---

### Ledger rows are NOT market-days — a 20.8x inflation trap

`data/settlements/<market>/ledger.jsonl` is **append-only with revisions**. Counting lines, or
counting lines carrying a `target_date`, counts *settlement revisions*, not market-days.

Measured 2026-08-06:

| Count | Value |
| --- | ---: |
| Ledger rows with a `target_date` | **15,174** |
| Distinct `(market, target_date)` | **729** |
| Admitted under `promotion_countable` (`-09-32a` corpus) | **108** |

**Inflation factor 20.8x** before the admission bar, and ~140x after it. The production agent
put "~2.23M snapshots across 15,174 settled market-days" into handoff `-09-32a` as support
scale; `-09-32a` caught it and corrected the corpus to **108 market-days, 19,265 snapshots,
211,915 band rows**. Summing repeated records also inflates snapshot and band-row counts the
same way.

**Always deduplicate to `(market, target_date)` and then apply `promotion_countable`.** A
support figure that was not deduplicated is not a support figure. This is the same family as the
mismatched-denominator error that produced the retracted 78% absorption "leak".

---

## 3. Operational false alarms

### "A reboot kills the fleet" — FALSE

Capture is all S4U and survives unattended reboot. This was fixed and verified. Do not re-raise it.

### "The merge report shows a failure" — STALE, BUT REAL

The merge `0x1` is stale-but-real, and the merge report file is **last-write-wins**. No merge trigger
is scheduled. Read the file's timestamp before reacting to its contents.

### "99 stale / 33 permission" on the maker — WRONG FRAMING

That was a **post-window rollover tick**, not the active window. Recorded by the operations agent as
its own error. Do not build on it.

### LA's `stale_code` was not an LA defect

It was **process-wide deployment drift across all 12 markets**, and it is **already resolved** — the
01:15 roll onto current code cleared it. Do not re-fix it.

### `live_variant_settlement_scorecard` reporting BLOCK with 0.0 coverage — CORRECT BEHAVIOUR

It is a **release/variant-contract gate**, not a skill series. Served rows on a pre-release host carry
blank `release_id` and `release_identity_status=research_unbound_non_countable`, and the scorecard
correctly requires an explicit immutable release ID. It should begin returning real verdicts after
release #1. **Do not "fix" it by relaxing release identity or deleting expected variants** — that
turns a valid gate into a misleading skill claim.

### "All Toronto ECCC payloads failed their pinned hashes" — FALSE, THE VERIFIER WAS WRONG

`-09-22a` reported that every available Toronto ECCC raw-payload receipt failed its pinned canonical
hash, fell back to METAR, and therefore shipped free-source parity with `humidity`, `pressure`, and
`pressure_trend_3h` at **0% population**. **There is no ECCC integrity problem.**

Verified on the production host 2026-08-06: **836 of 836** `eccc_swob` payloads across five Toronto
market-days reproduce their declared `payload_hash` exactly. The payloads also contain `rel_hum`,
`stn_pres`, `dwpt_temp`, `air_temp` and `mslp` — precisely the fields reported as unpopulated.

**The trap:** `payload_hash_algorithm` is **`sha256-canonical-json`**, not a raw-bytes digest. The
hash is taken over `canonical_json(parsed_payload)`, not over the file. The stored file carries a
trailing newline, so it is exactly **one byte longer** than the hashed canonical form (8,014 vs
8,013 in the checked example) and its raw digest never matches. Hashing the file bytes fails 100% of
the time by construction, which is what "all 254 failed" actually means.

```python
# WRONG - fails every time
hashlib.sha256(path.read_bytes()).hexdigest() == row["payload_hash"]
# RIGHT
hashlib.sha256(canonical_json(json.loads(path.read_bytes())).encode("utf-8")).hexdigest()
```

**Consequence: full free-source parity has never actually been measured.** `-09-22a`'s severe-tail
result (6.58%, crossed CI [0.49%, 14.14%], D=5) was measured with Toronto's ECCC-only fields
needlessly absent — and Toronto humidity/pressure were the point of that work. Re-run before drawing
any conclusion about what free-source parity is worth.

**Generalises: a 100% failure rate is a signal about the verifier, not the data.** Check the declared
algorithm before concluding that canonical evidence is corrupt.

### "A reconnect gap can be backfilled from the public API" — FALSE, AND IT IS A HARD CONSTRAINT

`-09-27a` tested this at P0 and returned a hard NO-GO. **The public API cannot exactly reconstruct a
sub-second coverage gap.** Do not re-propose backfill without new API capability.

| Route | What it gives | Why it fails |
| --- | --- | --- |
| `/orderbook-history` | 101 ms-snapshots across 52 of 264 tokens | **Indicative only** — no sequencing, completeness, loss-detection, or exact-boundary contract; only partly documented |
| Trade history | ~3 years retention | **Second-level timestamps**; omits book changes |
| Price history | sampled `t/p` points | Sampled, not exact |

**Exact-replay retention horizon is effectively zero seconds.** Snapshot retention is undocumented
(empirically ≥12 h 17 m after the fact). An indicative reconstruction presented as exact would
corrupt every maker P&L number downstream, so this fails closed.

**Consequence:** gaps cannot be proven empty (`-09-25a`: cadence threshold `0.000 s`, receipts carry
no maker-state fields) and cannot be filled after the fact (`-09-27a`). The only remaining directions
are preventing the gap or accepting bounded uncertainty in maker scoring.

### The maker's connection losses are NOT a host or network common-cause failure

Measured on production 2026-08-06 against the `-09-18a` soak window. During the maker's
settlement-breaking loss (04:08:24.6→04:08:26.8 UTC) the CLOB capture loop straddled the gap
**unbroken** — records at 04:08:16.948 and 04:08:31.962, both `ok`, 22 tokens, 15-second cadence,
no error anywhere in the surrounding ±2.5 minutes.

Across the **entire** 6 h 52 m soak window the CLOB feed logged **19,625 records with exactly one
error**. So whatever dropped the maker's socket left a concurrent connection to the same exchange
from the same host completely unaffected — the cause is **connection-specific, not environmental**.

**But redundancy is not a complete answer.** The same scan found 6 gaps >60 s all clustered at
00:53–00:56 UTC across houston/LA/toronto/atlanta/seattle — a genuine fleet-wide common-cause stall,
the pattern `-09-14a` targets. Independent-connection redundancy defends against the connection-
specific drops that caused the `-09-18a` NO-GO; it does **not** defend against a fleet-wide stall.
Any proposal must price that residual rather than claim the problem solved.

### The `SOURCE_PATTERNS` glob is NOT the roll-sensitivity test

Roll sensitivity is the **loaded-module import closure**, recorded in the capture status files as
`runtime_identity.source_scope_files`. Markdown under `docs/` is not a source-identity file and is
roll-free. Deriving a roll verdict from the glob over-reports and wastes quiet windows.

### Capture-loop restart risk is not avoidable by keeping a schema local

`schema_version()` raises `KeyError` on any name absent from the central `SCHEMAS_BY_NAME`, so central
registration in `schema_registry_data.py` is **mandatory**. That module is in **all four** capture
import closures. The roll is unavoidable — the objective is to make it **purely additive** so it is
behaviourally inert, not to eliminate it.

### The `clob_enrichment` closure being 10 days stale — HARMLESS, AND IT WAS NEVER SCHEDULED

The staleness sweep raised `closure/clob-enrichment` at **CRITICAL** on the reasoning that "a closure
that stops reporting is silently dropped from every later roll verdict; merges then look safer than
they are." **That reasoning does not hold for this closure, and it can be checked mechanically.**

Compare the two file sets in the status JSONs:

| Set | Files |
| --- | ---: |
| `clob_enrichment_status.json` → `runtime_identity.source_scope_files` | 21 |
| `clob_loop_supervisor_status.json` → `runtime_identity_before.source_scope_files` | 23 |
| **Files unique to `clob_enrichment`** | **0** |

The enrichment closure is a **strict subset** of the live CLOB closure — the live loop adds
`market/storage_pressure_policy.py` and `operations/windows_processes.py`, and nothing is lost the
other way. So **its staleness cannot make a roll verdict wrong**: every file it would contribute is
already contributed by a closure that reports every 60 seconds.

Second, it is not a regression. **No scheduled task has ever driven it.** It was hand-launched once
on 2026-07-27 in `research_enrichment` mode with `blocks_raw_book_capture: false` and
`counts_toward_raw_book_freshness: false`. "Dormant since 07-27" is the expected state of a one-shot
research tool, not a loop that died.

**What is real, and much smaller:** that single run captured `ws_event_rows: 819` for Toronto.
Websocket event capture is not running. That is a data-collection choice worth making deliberately —
it is not a capture-fleet fault, and it does not belong at CRITICAL beside a dead learning loop.

Do not re-raise this as a fleet incident. **If you want to change the severity, re-run the set
difference first** — the subset relation is the whole argument, and it would stop holding the moment
the enrichment loop imported a module the CLOB loop does not.

### Two scheduled tasks exit non-zero every day BY DESIGN — do not treat them as failures

Task Scheduler shows two standing red results on a healthy host. Both are the task faithfully
reporting a **downstream block**, not a task fault.

| Task | Result | What it actually means |
| --- | ---: | --- |
| `WeatherTrainingWindow` | **2** | `training_window.log`: `[RETRAIN] promoting non-success nightly status to window exit 2`. The nightly retrain is blocked by the season window (0 / 12,600 cells). Capture stops and is restored — on 2026-08-06 in **20 seconds**. |
| `WeatherDailySettlementPromotionRefresh` | **1** | The chain errors at `settled_day_analysis_barrier`, which is the documented, expected stop. |

`WeatherTrainingWindow` will report **2 every night until the season window lands**, and the chain
will report **1 every day until `-09-29a` merges.** Neither number changing is progress; neither
number staying is an incident.

**The distinguishing evidence is the log, not the exit code.** For the training window, check that
`[RESTORE]` lines follow the `[STOP]` lines in `data\logs\training_window.log` — that is the only
part that can cost a streak day. If capture was restored, exit 2 is a healthy run.

### "A live PID proves it still owns an old lock" — FALSE UNDER PID REUSE

On 2026-08-19 a killed daily-refresh process left locks naming PID `3212`. Hours later Windows
reused `3212` for an unrelated Codex `node_repl.exe`. PID-only liveness therefore classified dead
lock metadata as active and would have blocked the next Stage-A run. Lock ownership needs a process
creation token/image identity as well as PID. Never kill the current process merely because an old
lock names its reused PID.

### "Setting PYTHONPATH makes a worktree import authoritative" — FALSE FROM ANOTHER CWD

The fixed-scope wrapper set the successor worktree on `PYTHONPATH` but invoked `python -c` from the
production checkout. Python's current-directory entry selected production's root `weather`
bootstrap first, so successor-only modules were absent. Execute with the exact worktree as the
working directory and print module `__file__`; an environment variable alone is not proof.

### "Tiering task 0x0 means disk was reclaimed" — FALSE

Both 2026-08-19 tiering tasks returned Scheduler zero while their durable task statuses were
`SKIPPED_WORKLOAD_LEASE_BUSY`. The wrappers deliberately make a busy-lease skip nonfatal. Read the
status artifact and measured free-space trail; Scheduler zero proves only that the wrapper handled
the collision as designed.

### "Disk headroom is about 4 days" — THE DAILY LOW IS WHAT BINDS (2026-09-19)

- **What it looked like:** the status monitor printed roughly four days of headroom.
- **What is true:** it divided the **instantaneous** free space by a same-clock 24-hour slope
  (`scripts/ops/status.ps1`, `$diskDaysLeft`). Free space is a daily sawtooth: it bottoms near 04:50,
  10–13 GiB under the evening reading, before the 05:00 tiering job hands about 13 GiB back. Measured
  at the low, headroom was about 1.5–2.5 days. `ESTABLISHED_FINDINGS.md` §10b.
- **Why it fooled us:** a slope between two readings at the same phase of a sawtooth is correct about
  the trend and blind to the trough. Different free-space numbers quoted the same day were one
  instrument read at different phases. Ask of any level reading: *when in its cycle was it taken?*

### "Low disk directly blocks the settlement chain" — REFUTED; AN INDIRECT ROUTE IS PLAUSIBLE, UNPROVEN (2026-09-19)

- **What it looked like:** the disk was nearly full and 10 of the last 14 dates were unsettled, so
  the one caused the other.
- **What is true:** the Stage-A chain has **no disk gate**. The proven deferrals were memory-commit
  admission (72.5% and 91.4% against a 70% ceiling) at `ingest_quality_gate`, which sits ahead of the
  WU restore and finalize, in a single-shot chain with no retry. `ESTABLISHED_FINDINGS.md` §10d.
- **What is NOT settled:** the live commit limit had shrunk to about 22 GB, so the 70% gate trips with
  little real load. A dynamic pagefile on a nearly full system volume is the likely mechanism, which
  would make low disk an **indirect** cause. The pagefile setting was not read. Treat it as a
  hypothesis to trace, not a finding.
- **Why it fooled us:** two alarms that co-occur invite a causal arrow. Only 2 of the 10 dates have a
  provable cause at all, because the chain's status file is overwritten daily.

---

## 4. Backlog and branch traps

### "Today's exchange-economics snapshot can score historical maker runs" — RETRACTED

That is false for International markets because each dated condition has its own condition and
token identities. A current snapshot is evidence for its own target date, not a timeless fee table
that can rehabilitate older quote legs. Historical legs require the exact snapshot frozen by their
run; absent or tampered captures remain unbound with zero incentive economics. See §8k of
`ESTABLISHED_FINDINGS.md` for the immutable suite receipt and corrected binding contract.

### "Forward public execution capture is the only route to the maker's informed-fill fraction" — RETRACTED

This looked true because the retained book tape cannot distinguish cancellations from executions,
and the public market stream adds explicit trade events. That fixes the **market path**, not our
selection into fills. Public trades do not prove that our resting order filled, where it sat in
queue, what fee or rebate applied, or what inventory the account held.

The corrected evidence split is: public executions for price paths and counterfactual markouts;
authoritative own-account user events, orders, positions, fees and rebate receipts for realized
lifecycle and P&L. The authenticated stream is not a market-wide flow denominator, but it is
indispensable for our own economics. Treating either source as a substitute for the other recreates
the project's recurring error of calling eligibility evidence an outcome.

### Branch names lie

`-09-01a` is named "consolidate merge queue" and contains a 1,536-line point-in-time training corpus,
a fail-closed all-market base retrain, and the PIT binding. It was nearly retired as housekeeping.
**Read the commits before judging a branch.**

### No held branch clears any of the 97 retrain blockers

Checked exhaustively. Do not go looking for one.

### Agent reports exist only on unmerged branches

**46 reports live nowhere else. Never delete a branch**, even one declared superseded. Retiring a
branch from the merge queue and deleting its ref are different operations; only the first is ever
authorized.

### A "held" branch is not necessarily refreshable

`-09-01a` sat 59 commits behind master. Held branches rot. Age a branch against master before
planning work that depends on it.

### "Release #1 is not on the critical path to a countable MM day" — RETRACTED

Claimed and retracted the same day, 2026-08-06, before it was acted on.

The claim was reached by grepping `live_forward_gate.py`, `market_making_preflight.py` and
`market_making_readiness.py` for "release", finding zero hits, and concluding that market
making is decoupled from the release. **The grep result is true. The conclusion does not
follow.**

Tracing the path that actually produces a countable day falsifies it: today's 924 quote
intents all carry `promotion_state: BLOCK`, and **847 of them (91.7%) are denied with
`known_edge_reason: promotion_block`**. Promotion BLOCK denies known-edge permission → no
quotes → no fills → `fill_evidence_completeness=BLOCK`, which is one of the six countability
blockers. The modules do not name a release; the causal chain runs through promotion anyway.

**What is still true:** release #1 is not *sufficient* for promotion —
`hourly_model_performance` independently BLOCKs on early-hour Brier (0.0205 vs 0.0030
tolerance, all 12 markets) with the remediation `keep promotion blocked`. Whether release #1
is *necessary* for promotion remains **unestablished**; it could not be tested on 2026-08-06
because the chain died at the settled-day barrier before promotion refresh ran, making its
all-null summary a `not_run` default rather than evidence.

**The trap, and it is the second time:** a literal search is not a trace. §7 of
`ESTABLISHED_FINDINGS.md` records the same error made against `-09-01a`, where the absence of
a `covered_years` expression was mistaken for the absence of the self-sizing defect. Both
times, absence of a string was read as absence of a behaviour. **Trace the path that produces
the outcome, not the vocabulary of the modules near it.**

---

## 4a. Maker-economics traps

### "Liquidity rewards are about $16 a day — a subsidy, not a business" — TRUE FOR 2026-06-13, STALE SINCE (2026-09-19)

- **What it looked like:** `MARKET_MAKING_PLAN.md` Part 0 measured about $1 per event per day and
  about $16 per day fleet-wide, and concluded rewards are a cost offset. The July
  `NOT_VIABLE_CURRENT_TRACK` report had only that figure as a scale (it recorded the July allocation
  as `UNKNOWN_NOT_ZERO`), and the zero-edge sensitivity grid's reward axis stops at $1 per band per
  day.
- **What is true:** the June measurement was correct for its date. The **configured** pool for our
  12 markets has been about **2,800 per day same-day and about 4,800 per day across all active
  events** on 31 of 31 sampled days from 2026-08-15 to 2026-09-19 — roughly 175 to 300 times the June
  figure. The project's own `exchange_economics_snapshot.json` held the per-market field
  (`current_daily_rate_usdc`) every day; item 330 recorded the allocation count without a total.
  `ESTABLISHED_FINDINGS.md` §10a.
- **What this does NOT say:** that the July verdict was wrong — its input is stale, and its first leg
  (a reward-qualifying two-sided quote does not fit the 10 pUSD band cap) is unchanged. Nor that the
  pool is income: it is shared by Q-score, **our share is unmeasured**, no paid reward has ever been
  observed, and the unit is unconfirmed by any paid epoch.
- **Why it fooled us:** a dated measurement hardened into a constant. Every later document cited the
  conclusion, nobody re-opened the input, and nobody summed a column we collected daily. Pattern 4 in
  `HOW_WE_GET_THINGS_WRONG.md`.

---

## 5. How to add to this file

When a claim is retracted or a false lead is closed, record:

1. **What it looked like** — the version that seemed true.
2. **What is actually true**, with the corrected number if there is one.
3. **Why it fooled us** — the mechanism, so the same shape is recognised next time.

Do not delete retracted claims from the record. A deleted mistake gets re-derived; a documented one
does not.

## Update this file when

A claim is retracted, a false lead is closed, or an alarm is shown to be misread. In the same change
add the number to the "Retracted numbers" table in [FINDINGS_DIGEST.md](FINDINGS_DIGEST.md), and ask
which pattern in [HOW_WE_GET_THINGS_WRONG.md](HOW_WE_GET_THINGS_WRONG.md) the entry belongs to.
