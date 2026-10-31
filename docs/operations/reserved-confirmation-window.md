# Reserved confirmation window

**Status: RESERVED (narrow scope, MG-1, signed 2026-10-04; dated by the owner 2026-10-16, option 2 BOUND): the first
45 promotion-countable local target dates from MG-1 D0 = 2026-10-15 through provisional MG-1 last = 2026-11-28
(inclusive; D0 + 44 days) are held out ONLY against NBM-guidance-to-band forecast candidates. D0 is final; the last date
is provisional and may only move later (each missed promotion-countable date moves it one day later).** Everything else
may use those dates (see the exemption below).
**MG-2 exemption (owner 2026-10-25, option 2, MG-2 only):** MG-2 may score its own as-of-capture vectors on these dates
in ONE look, strictly after MG-1's look, against MG-1 and (owner Q1 "Yes to both") against the capture-time market
as forward test B. Nothing else is exempted; see the MG-2 exemption row.
**MG-3 exemption (owner 2026-10-26, MG-3 only, dates 2026-11-11..2026-11-28):** MG-3 may use these dates as a paired D-C test
against MG-2 on B's dates (H1 = MG-3 − MG-2), frozen before its D0 ≈ 11-10/11; see the MG-3 exemption row and DECISION_LOG 2026-10-26.
**Retrain window: ARMED, not dated, narrow scope (owner 2026-10-21, bundle-B (k)): once declared it holds its dates ONLY
against retrain-family candidates; EDGE-1, MG-1, the evening-fix scorer, t3-r3, maker scoring and every other use are exempt.**
**Read further** before scoring any forecast candidate that reads NBM station guidance, or before freezing a retrain candidate.

**Single source of truth for which dates are held out and what they are held out *for*.** Every
research handoff must carry this status line. If this file and a handoff disagree, this file wins.
When a window is declared, replace the status line with the dated range and its endpoints.

## The reservation

| | |
| :--- | :--- |
| **Reserved dates** | **MG-1 (narrow scope):** first 45 promotion-countable local target dates from D0 = 2026-10-15 (MG-1 §3) through a provisional last date of 2026-11-28, inclusive. The retrain-triggered window below stays *armed but not dated*, and narrow when declared (retrain scope row). |
| **MG-1 dating (owner, 2026-10-16 ~09:22, relayed by master-agent: option 2, BOUND)** | D0 = 2026-10-15, final; it sets aside MG-1 §3 (b) and (c), and parser v2 verification and shadow-stage capture stay reporting caveats ([Clarification 1](../research/morning-guidance-read-mg1-clarification-1-2026-10-16.md)). Provisional last = D0 + 44 days = 2026-11-28, the 45th calendar date, which is the 45th countable date only if every date from D0 is promotion-countable. MG-1 §3 counts countable dates from D0 with no skipping, so each date found not countable moves the 45th countable date, and the recorded last date, one day later. The last date **may only move later**: it is extended (same OD32 mechanics below) as soon as a non-countable date is known, and in any case before any date after the recorded last date is scored, enumerated or joined to an outcome by an NBM-guidance-to-band candidate. Before the change the window was open-ended from 2026-10-15; bounding it releases no date earlier than 2026-11-29. `tests/reporting/test_mg1_reserved_window.py` fails if D0 moves or the last date is set earlier than 2026-11-28 or D0 + 44 days. |
| **MG-1 binding** | `docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md` at `02c410a5`, raw SHA-256 `b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665`, signed 2026-10-04T16:10Z (DECISION_LOG). |
| **MG-1 scope and exemption (owner, 2026-10-04; explicit exemption under rule 4)** | Reserved **only** against reading or modifying the morning guidance-read (forecast-scoring) family: do not score, enumerate outcomes for, or join to an outcome the MG-1 vector or any other candidate that reads NBM station guidance into band probabilities (including the held RV-1 and HG-1), do not substitute reserved dates for such a candidate, and do not modify MG-1, without a new explicit owner decision. **Exempt and untouched:** the 88a desk-study decision panel (UTC 2026-10-15..10-30), MM paper scoring, and every other use of these dates' captures, served vectors and settlements; outcome-blind operational checks (coverage, PIT, replay reproduction, parser version) are permitted. |
| **MG-2 exemption (owner, 2026-10-25, "Yes to all" to master's question 1: option 2, MG-2 only; relayed by master; DECISION_LOG)** | An explicit owner decision under the scope row above, for the MG-2 composite only (rule on `claude/mg2-c7-asof-gate-20261025`, §4.3; the drafted wording, as master and the B design read it): MG-2 gets a **single** outcome look on its first 45 countable dates from its own D0, **strictly after MG-1's look**. Its scorer refuses until an MG-1 look receipt exists and the recorded MG-1 window has closed; labels (and, under owner answer Q1 of 2026-10-25, "Yes to both (Recommended)", the capture-time prices for test B) travel once, at that look. Before the look, MG-2 on reserved dates is limited to the outcome-blind checks this file already permits. **Not exempted:** any other NBM-reading candidate (each needs its own owner decision), any interim look, and MG-1 itself. Design: [B forward test design](B_FORWARD_TEST_DESIGN.md). |
| **MG-3 exemption (owner, 2026-10-26 ~16:4x EDT, verbatim "same dates, need answers quick as possible"; relayed by master; DECISION_LOG 2026-10-26)** | An explicit owner decision under the scope row above, for MG-3 only, over **2026-11-11..2026-11-28**. MG-3 runs as a paired D-C test on B's dates with H1 = MG-3 − MG-2; the evidence it shares with B is declared up front in its pre-registration (being prepared by L2); D0 ≈ 11-10/11, after the HRRR recorder's 14-day clock and the parity pass, with everything frozen before D0; result ~mid-December. **Not exempted:** any other NBM-reading candidate, any interim look, MG-1 itself, and any date outside 11-11..11-28. |
| **MG-2 input export for the 10-28 forward date (master ruling, 2026-10-26, not an owner decision)** | Master's wording: option 2 covers the 2026-10-27 event folder for the 10-28 forward date, for **INPUT rows only**: previous-day METAR and NBM, exactly the inputs MG-2 reads live to serve 10-28. No 10-27 prices, books, trades or labels go into any agent-readable output beyond the exporter's counts-only coverage fields. **General rule (amended by master, 2026-10-26):** "day D's export may read D-1 inputs (prev-day METAR + NBM) and D+1 NBM rows captured ≤ D's cut; nothing else." Exporter: `claude/mg2-input-export-20261026` @ `a0950c7fe48dcf302474f6a3a4cccb000ee4abbe`; master's host `roll_verdict` was ROLL-FREE. Exporter test commit `76b13cca2` proves no D-1 or D+1 price, book, trade or label reaches the bundle; the allowlist and receiver are unchanged. |
| **PT-1 single read (owner, 2026-10-25, Q9 "Yes (Recommended)"; DECISION_LOG)** | A separate dated embargo line for the cool-season paper test PT-1 only ([draft](COOL_SEASON_PAPER_TEST_PREREG.md)): ONE price-and-label read for its own dates, 2026-12-12..2027-01-25 (owner Q6 "Separate dates (Recommended)", disjoint from B's), at its single look after B's. Its PT_D0 and rule sha are recorded at binding. Nothing else is exempted: no interim look, no other candidate, no other dates. |
| **Maker shadow fair value (owner, 2026-10-07, OD3, OD31, OD32)** | The shadow's NBM-guidance view may be used on reserved dates for quoting and MM paper scoring only. Every view-vs-outcome metric on it (markouts on the view, Brier/PIT, fair-value score) stays reserved and is refused in code; plugin-view accuracy is never exempt, including inside the 88a panel. The item-190 NBM scorer drops reserved dates before any outcome join (filter, not refuse). D0 is recorded by whoever dates the status line above, in the same commit, test-enforced. |
| **MG-1 dating format (OD32 mechanics)** | Date the status line with `MG-1 D0 = YYYY-MM-DD` and `MG-1 last = YYYY-MM-DD`, and record the same `MG1_D0`/`MG1_LAST` in `weather.mg1_reserved_window` (and, once landed, `maker_core.mg1_window`) in the same commit. `tests/reporting/test_mg1_reserved_window.py` fails if they differ; a recorded window shorter than 45 calendar days fails wide. Item-190 filter behaviour (counts-only disclosure, exit codes, `--as-of`): [item 190](../roadmap/items/item-190-nbm-probabilistic-tmax-consumption.md). |
| **Retrain scope (owner, 2026-10-21, bundle-B question (k); DECISION_LOG)** | Narrow, MG-1-style, exactly: *"hold the dates only against retrain-family candidates; exempt EDGE-1, MG-1, the evening-fix scorer, t3-r3, maker scoring and every other use of those dates; the 20-date look is futility-only; the freeze is not timed to dodge dates."* This replaces the as-written scope under which freezing the first retrain candidate held **every** date from the trigger absolutely and stopped MM paper scoring (binding rules 3-4 below, as amended). |
| **Retrain-family, defined (master ruling, 2026-10-25, not an owner decision)** | A refit of the served per-market feature model (R0 and its successors). A candidate that is never served and is not a refit of the served per-market model is a serving-stage candidate, as MG-1 is, and is outside the retrain window; P3d_N and MG-2 as a whole are not retrain-family. |
| **Trigger** | The retrain window begins on the **first target date after the first retrain candidate is fitted and frozen** (earliest R0 start 11-17), and runs forward from there, at the narrow scope above. |
| **Size** | Computed at freeze time against endpoints that still stand — see *Sizing at freeze* below. Not fixed in advance. |
| Status | MG-1 narrow reservation active from its signature, dated 2026-10-15..2026-11-28 (last provisional, may only move later); retrain window armed, not dated, narrow scope (2026-10-21); no date is held out against anything else. |
| Declared | 2026-08-04 by the operator (re-base). Previously 2026-08-03. |
| Supersedes | 2026-08-06 → 2026-11-03 (90 dates); before that, 2026-08-06 → 08-19 (14 dates) |

### OPERATOR DECISION 2026-08-04 — re-base the reservation to the retrain

**Decided by the operator on 2026-08-04, with reasons recorded here as this file requires.**

The 90-date block was replaced by a **forward reservation triggered at candidate freeze.** Three
reasons:

1. **It was reserving against something that does not exist.** Release #1 *freezes* the June
   per-market HGBs — it does not retrain. The first retrain has **no candidate and no schedule**.
   Dates held out *before* a candidate exists add no protection: the candidate cannot have seen them
   either way. What actually protects a confirmation is that its dates are unseen **at the moment the
   candidate is fitted and selected** — which a forward reservation guarantees exactly.
2. **Its sizing basis had been superseded on every row** (see the table below, retained for history).
3. **It blocked the operator's stated end goal by about four months.** `-09-10a` established that no
   reserved date can contribute a countable market-making day, because scoring a maker day reads that
   date's settlement. Under the 90-date block the first possible MM decision was **2026-12-16**.

**This is a re-base, not a retroactive shortening.** It was decided on **2026-08-04**, before the
window's own start date of 2026-08-06. **Not one reserved date had elapsed, so no holdout was
consumed and nothing was un-reserved after the fact** — the specific hazard the *Changing this file*
section below warns about does not apply.

### OWNER DECISION 2026-10-21 — the retrain window is narrow

Decided by the owner on 2026-10-21 (bundle-B question (k), every Recommended default accepted; relayed by
master-agent; DECISION_LOG row of that date). **Reason:** the model-edge programme's retrain arm R0 could
freeze from 11-17, and under the as-written rules that freeze would have held every later date absolutely
and stopped maker paper scoring, colliding with EDGE-1 and MG-1 on the same dates. The retrain look is
futility-only, so a narrow hold protects what it needs. **No date had been declared, so nothing was
un-reserved after the fact.** Rules 1, 2 and 5 below are unchanged; rules 3 and 4 are amended in place.

### Why this does not collide with market making

The two tracks become **sequential instead of overlapping**. MM consumes *current* dates for its
paper clock now; the confirmation window consumes *future* dates once a candidate is frozen. On the
`-09-10a` design at `$25/tier-20`, the MM clock is ~22 countable dates — it should complete well
before any retrain candidate is frozen. Once MM is live it no longer needs countable paper days.

### Binding rules under the re-base

1. **Until a candidate is frozen, nothing is reserved.** MM scoring, diagnostics, and research may
   use any settled date.
2. **At candidate freeze, the window is declared here immediately** — dated, sized, and with its
   endpoints named — *before* any confirmation scoring begins. An undeclared window reserves nothing.
3. **Once declared, the window holds its dates against retrain-family candidates only** (owner
   2026-10-21, (k); was "absolute again"): for those candidates they are not read, not enumerated, not
   evaluated, not substituted, and reading one destroys it permanently. Every other use is exempt.
4. **MM paper scoring continues on declared retrain dates** under the 2026-10-21 exemption in the
   retrain scope row (was: must stop unless granted a fresh exemption here).
5. **The freeze must not be timed to dodge the reservation.** Declaring a candidate frozen only after
   convenient dates have been consumed would defeat the protection this file exists to provide.

### Sizing at freeze

Do **not** reuse the superseded table below. At freeze, compute N against endpoints that still stand,
under **crossed date × market** clustering, and record the derivation here. Known constraints:

- **Severe-tail SSE remains the only plausibly powered primary**, but `N=4` is **not** established:
  measured power at N=4 is **72.94%**, and the candidate-native N is **UNKNOWN**.
- **Pooled all-hour Brier is a guardrail, not a primary.** Its `N=53` was a weak 3-date variance
  proxy and cannot be described as crossed-bootstrap power.
- **09:00–14:00 remains unconfirmable** — 75.76% power at N=34, MDE 19.44% of baseline.
- **Toronto-only is not viable at any endpoint. Fleet or nothing.**

If no endpoint is powered at achievable N, **say so and do not declare a confirmation** rather than
reserving dates against a test that cannot decide.

## Historical sizing basis — SUPERSEDED, retained for audit

Everything in the next two sections was the justification for the 90-date block. **Every row of its N
table has since been retracted or downgraded.** It is kept because the reasoning trail matters, not
because it is still load-bearing.

- severe-tail `N=4` → measured **72.94%** power; candidate-native N unknown (`-09-06a`)
- pooled all-hour `N=53` → "weak 3-date variance proxy" by its own admission; `-09-07a` ruled it
  cannot be called crossed-bootstrap power at all
- the `5.39%` anchor → `-09-05a` found it a **separately fitted transform, not a propagated one**
  (real propagated served effect **18.32%**), and the `24.69%` figure was retracted outright

The previous 14-date window was chosen by calendar convenience. It was never a powered
confirmation and must not be described as one retrospectively: its 09:00–14:00 minimum detectable
effect was **32.30% of the served gap**, giving **10.96% power** at the optimistic effect.

## What changed, and why

`-08-04a` derived the honest served-level effect range for the first retrain as **0 to 5.39% of the
served incumbent-versus-market Brier gap**. The 24.69% raw-HGB closure does not survive the
downstream floor, blend, cap and calibration stages.

Fleet N required at 80% power, alpha 0.05 one-sided, two-way clustered by target date and market:

| Endpoint | N at 5.39% | N at 2.5% midpoint |
| --- | ---: | ---: |
| **Frozen severe-tail SSE** | **4** | **9** |
| Pooled all-hour Brier | 53 (weak 3-date variance proxy) | 246 |
| 09:00–14:00 Brier | 504 | 2,337 |
| Toronto-only, any endpoint | 3,350 | 15,550 |

**90 dates covers the two endpoints that are actually powered, with buffer for the weak pooled
variance estimate.** It does not cover the 09:00–14:00 slice, and nothing practical does.

## Endpoints for the first retrain's confirmation

- **Primary: frozen severe-tail SSE, fleet, paired, clustered by date and market.** It is powered at
  achievable N, and it is where the conditional correction improved *all five* held-out dates.
- **Guardrail: pooled all-hour Brier non-regression, fleet.** The primary endpoint alone is
  narrow — a candidate could improve the incumbent's worst rows while degrading elsewhere. This
  catches that.
- **Harm gate: one-sided two-way-cluster max-T, familywise error 5%.** Replaces the frozen
  53–54-slice bar, which falsely rejects a uniformly better candidate 99.885%–99.9905% of the time.
- **Reported but not confirmatory: the 09:00–14:00 slice.** Report it, label it directional, and do
  not call it a confirmation.

**Toronto-only evaluation is not viable at any endpoint.** Fleet or nothing.

## Standing consequence for the primary objective

The 09:00–14:00 slice remains the thing we are trying to *fix*. It is no longer the thing we can
*confirm* in a single shot. Those are different claims and conflating them is how this project
previously called an underpowered Toronto result a win.

## Changing this file

Extending the reservation is cheap; shortening it after the fact is not, and reading a reserved date
destroys it permanently. Any change needs an explicit operator decision recorded here with its date
and reason. **The `Status:` line at the top and the reservation table must change in the same
edit** — agents are told to stop reading at that line, so a stale status line is a destroyed
holdout.
