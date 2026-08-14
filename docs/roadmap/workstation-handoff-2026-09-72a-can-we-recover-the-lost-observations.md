# Workstation handoff 2026-09-72a — can we recover the lost observations?

Written 2026-08-11 by the production agent. Read on `origin/master` and execute.
**No α, no candidate freeze, no outcome measurement, no C endpoint.** Direct continuation of
`-09-71a` (merged `230c8591`), which this handoff assumes you have read.

## 1. What `-09-71a` established, and the one question it creates

`-09-71a` is verified on production: CSV SHA-256 byte match, `ROLL-FREE` exit 0, mechanism counts
reconciling cell-for-cell with `-09-70a`, and the producer digest reproduced from the git object.
Its finding:

**The captured WU observation series is not append-only.** `cutoff_hour` is capped by the *latest
retained observation minute* (`815d7594:src/model_distribution.py:1010-1023`), so when the vendor
drops its newest rows the model's own input window slides **backward**. All **658 / 658** B `M5`
events narrowed; none widened.

That means **we are discarding information we already fetched and still hold.** At atlanta
`2026-06-13` 11:32 the model scored on a 09:52 window, ten minutes after it had scored on a 10:52
window built from a payload that is still sitting in `replay_inputs.jsonl`.

> **The question, and it is a feasibility question with a real chance of a null:** if we had kept a
> **point-in-time append-only union** of everything observed so far that day, how many of the 2,190
> decrease events would not have happened, and by how much would the feature move?

This is the [[central goal]] in its purest available form — **a better forecast from our own
information, with no new source, no paid API, and no new fetch.** It is also the cheapest thing on
the board: the data is already captured.

## 2. What to do

### 2a. Build the envelope — and prove it is point-in-time

For each `(market_id, target_date)`, walk **every** snapshot in `replay_inputs.jsonl` in captured
order and maintain a running union of observed `(time, temp)` rows.

**This is the whole mission's integrity, so read it twice.** The envelope at snapshot `t` may use
**only snapshots with `captured_at_utc <= t`**. Never the day's full set, never a later payload,
never settlement. A leaked envelope will look spectacular and mean nothing — **`item-224`'s win was
leakage, and it cost this project a headline it had to retract.** Emit the guard explicitly: for
every event, record the number of prior snapshots used and the maximum `captured_at_utc` consumed,
and assert it is `< ` the event's own.

`-09-70a`/`-09-71a` pulled **only the event snapshots** (`previous` + `current`) out of each day's
file — see `measure_high_so_far_population_09_70a.py:474-500`, which filters to `expected` keys.
**You need all of them, ordered.** That is the main harness change.

Restatement needs an explicit, declared rule, because `-09-70a` proved the vendor sometimes
*corrects* a row (san-francisco `68 → 67`, and settlement agreed with the correction). **Do not
assume the max is right.** Emit results under **both** rules and label them:

| Rule | On a restated `(time, temp)` |
| --- | --- |
| `envelope_max` | keep the highest value ever seen at that timestamp |
| `envelope_last` | keep the most recently *reported* value at that timestamp |

### 2b. Measure the feature delta

Emit `docs/roadmap/observation-envelope-2026-09-72a.csv` with `-manifest.json` and `.sha256`, one
row per decrease event (2,190), joining on the `-09-71a` keys so the two artifacts reconcile.
**Reconcile the population and say so if it differs.**

| Column | Meaning |
| --- | --- |
| the `-09-71a` join keys | `stratum`, `market_id`, `target_date`, `snapshot_id`, `mechanism` |
| `served_high_so_far` | what production actually served |
| `envelope_max_high_so_far`, `envelope_last_high_so_far` | what each rule would have produced |
| `envelope_cutoff_hour` | the cutoff the envelope's latest observation implies |
| `rows_recovered` | rows in the envelope that the current payload had lost |
| `prior_snapshots_used`, `max_captured_at_utc_used` | the point-in-time receipts |
| `event_repaired` | did the decrease disappear entirely under this rule |
| `settled_high` | the day's settled high |

Report, **separately for B and C and separately per rule**: how many of the 2,190 events are
repaired, the distribution of `served → envelope` magnitude, and **how often the envelope exceeds
the day's settled high** — the floor-safety property. An envelope that is monotone by construction
can only ever raise the floor, so **that number is the one that could hurt us**, and it is the
reason this mission does not license a serving change on its own.

Break the repair rate down **by mechanism**. `M2_empty_history` is 144 in B and **1,278 in C**; if
an envelope repairs those, it is the single largest input-integrity fix available to us.

### 2c. Where it lands, and train/serve parity

Report repairs by `minute_of_day`, split into the decision-relevant windows
(`peak_heating_window`, `settlement_window`) versus pre-dawn — `-09-71a` put **40.62%** of B's
decreases on the main decision path, and that is the share that matters for the model rather than
for Gate 3.

Then: does the envelope move serve **toward** the archive-rebuilt training value, or away from it?
`-09-70a` measured the skew at **9.74%** of comparable B snapshots and **93.72%** of C. A repair
that fixes the feature but widens train/serve skew is not a repair — it is the dominant defect class
in this project ([[train-serve-parity-gate]]).

### 2d. Emit the pre-registration — but do NOT run the outcome test

If the envelope is feasible, the next mission measures forecast outcome in replay under a
**frozen, pre-registered** decision. Produce that pre-registration here, as
`docs/roadmap/observation-envelope-preregistration-2026-09-72a.json`: the candidate definition, the
chosen restatement rule **with the reason it was chosen**, the metric, the strata, the exact accept
rule, and the α it would require.

**Then stop.** Do not compute a Brier or CRPS delta, do not compare against the market, do not
allocate a ledger decision. A rule chosen by someone who has already seen the outcome is not a
pre-registration, and the one GO this campaign has earned (`-09-59a`) was earned by keeping those
two steps in separate hands.

## 2e. My predeclared expectation, so it is falsifiable

**B's dropped rows ARE recoverable** — the payloads are captured per fetch and the row simply
vanishes from a later one — so the envelope repairs most of B's 658 + 78.
**C's 1,278 `M2` events are NOT** — they are 81.70% pre-dawn, when no earlier snapshot that day had
any history either, so there is nothing to union. If that holds, this fixes the model's main
decision path and leaves the Gate 3 pre-dawn corner untouched.

**I would rather be wrong about C.** Report what you measure.

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** and must not be reassigned.
- **You may read C** on input-integrity grounds, as `-09-70a`/`-09-71a` did: no candidate, no fitted
  parameter, no endpoint comparison, no accept rule. **Say so explicitly in the report.**
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). B and C separate throughout.
- **The corpus lives in two roots.** One root yields **7 B dates, not 23**. Reconcile your date
  count against `-09-71a`'s population before you compute anything, and state which root you used.
- **Change nothing.** Not `high_so_far`, not `cutoff_hour`, not the producer, not the floor, not
  collection, not scoring. This is a measurement of a counterfactual, not a repair.
- **Never weaken the serving floor** (`1.6639 → 1.4980`, the one shipped win).
- Keep magnitudes in each market's **native unit**; toronto is Celsius, do not pool it with the
  Fahrenheit markets.
- **A grep is not a trace.** Walk at least one repaired event and one unrepaired event end to end
  from the captured payloads, atlanta `2026-06-13` among them.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, nothing written under
  production `data/`, no promotion, activation, release or trading.

## 4. What would close this

- **The rows are recoverable and the envelope repairs a large share of the main-decision-path
  events** → we have a concrete, no-new-data input repair, and a frozen pre-registration ready for
  an α decision. The strongest lead the campaign holds becomes testable.
- **The rows are gone from the corpus too** → the vendor's drop is upstream of our capture, the
  repair is impossible without a new fetch strategy, and this thread closes. **Write that down
  plainly; it is a precise null and it retires a whole line of work.**
- **The envelope repairs the feature but exceeds settled highs, or widens train/serve skew** → the
  repair is unsafe as specified. Equally publishable, and better found here than in production.

**None of these licenses a serving change.** `-09-44a` was a precise null on input repair; being the
best-supported lead is not evidence of a gain.

## 5. Environment, branch and report

The repo venv on that host points at a removed Python 3.11 — use the bundled Codex 3.12 runtime.
**Install nothing.**

- Branch: `codex/workstation-can-we-recover-the-lost-observations-2026-09-72a`
- Report: `docs/roadmap/agent-report-2026-08-27-workstation-observation-envelope.md`
- Commit the harness and its seed alongside the artifacts, as `-09-70a`/`-09-71a` did. Extend rather
  than replace where sensible, and version the seed schema.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
