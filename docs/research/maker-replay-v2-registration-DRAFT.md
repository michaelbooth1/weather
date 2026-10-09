# Maker replay v2 — successor registration, DRAFT 2026-10-03

**Status: DRAFT, UNSIGNED, prospective. Not an execution approval and not a live-trading approval.** This draft
owns the proposed successor to `maker-replay-2026-10-15`, which the owner closed **NOT EXECUTED** on 2026-10-03 under
Clarification 2's host limits. It may be signed only after the [executability gate](#executability-gate-before-signature)
and the [reachability gate](#reachability-gate-before-signature) have run, and only before any export or read of the
panel's 88a data. The engineering plan and the measurements it needs are in
[the companion plan](maker-replay-v2-engineering-plan-DRAFT.md). Bracketed `[GATE: …]` cells are filled from
calibration-only measurements before signature; every other rule is fixed by this text.

**Read when:** deciding the successor to the closed exam, or building its tooling. **Do not use for:** current state
([STATE_OF_PLAY](../operations/STATE_OF_PLAY.md)) or the decisions in force ([DECISION_LOG](../operations/DECISION_LOG.md)).

## 1. Why a successor, and what it inherits

The signed exam is the registration (`docs/research/maker-replay-hurdles-preregistration-2026-09-27.md`),
execution addendum (`docs/research/maker-replay-execution-addendum-2026-09-27.md`) and Clarifications
1 (`docs/research/maker-replay-clarification-1-2026-09-27.md`), 2 (`docs/research/maker-replay-clarification-2-2026-09-29.md`) and
3 (`docs/research/maker-replay-clarification-3-2026-10-01.md`); all read at `origin/codex/integration-exam-20261002` `664c8943`.
It could not run, for three measured reasons:

| Measured fact | Source | Consequence under Clarification 2 |
| --- | --- | --- |
| Real daily band union **170 conditions** on calibration date 2026-09-27 (owner-reported). The fixture's 12 bands were a 14x undercount. | owner 2026-10-03 | Engine cost grows with the square of the union: one 12-band date takes 373 s; one ~120-band date takes ≥ 7.5 h and ~31.5 GiB of report. At 170 bands that projects to ≥ 15 h per date (ESTIMATED from the 120-band measurement × (170/120)²), against a ~546 s budget. |
| **1.30 GB input per date** (owner-reported) | owner 2026-10-03 | × 15 = ~19.5 GB, above the 70%-of-16-GiB input limit (11.2 GiB) before any compute. |
| **9.9 GiB export peak** for one date on the 16 GB capture host (owner-reported) | owner 2026-10-03 | 62% of host RAM for one export; 5x the nightly export wrapper's 2 GiB child ceiling. |

Mechanism, from code at `664c8943` ([plan B audit](../roadmap/audits/exam-plan-b-2026-10-03.md) §A; reports
#166, #168 and #175): the engine ticks every active band at every heap pop, each band adds about two pops a minute,
the exporter repeats per-condition coverage at every capture, and the report writes one row per uncovered span.
None of this is the economic question; all of it is frozen by the signed text, so the fix needs a new registration.

**The question is unchanged.** On captured International Polymarket weather inputs, does the informed maker
(`informed-v0`) earn more than quoting blind (`blind_re1`) and more than not quoting (`no_quote`), counting modelled
liquidity rewards, nominal rebates and settled inventory P&L, so that rewards are measured **net of adverse selection**?
And does it avoid large price moves at least twice as efficiently as an exposure-matched clock (`clock_only`)?

**Inherited unchanged unless §3 lists it:** the estimand, both hurdles and their conjunction, the four policies and
their kernels, pricing, fill bounds, caps and cash, the net screen and adverse-loss input, the hazard recipe
(addendum plus Clarification 1's pooled fallback), the calibration dates 2026-09-27..29, the quote-market rule
(Clarification 2), the 05:00–08:00 UTC exclusion, the bootstrap, look protection, the k = 0.3 and competitor-reaction
reporting (Clarification 2), and Clarification 3's quote presence, MDE, screen-suppression label and next-step rules.

## 2. Panel, prior reads and disclosure

- **Quote panel:** 2026-09-30 through 2026-10-13 UTC, fourteen closed 88a capture dates (unchanged).
- **Settlement-only:** 2026-10-14 **and 2026-10-15** UTC, with no active intervals and no date clusters (change C9).
- **Calibration:** 2026-09-27, 09-28 and 09-29 UTC, for the hazard (unchanged), the ceilings rehearsal and the
  reachability gate (§9, §11).
- **Excluded market-date (owner, 2026-10-05): Austin, local target date 2026-10-03.** The production agent saw that
  day's settlement band at 07:20 America/Toronto on 2026-10-05 (protected-window exposure). Every condition of the
  Austin event with target date 2026-10-03 has no active interval on any panel date (exclusion reason
  `OWNER_EXCLUDED_PRIOR_READ`): it is never quoted, and no reward, fill, markout, pull opportunity or score of it enters
  any band-day, cell, contrast or gate. Other Austin target dates and other markets on the same UTC dates are unaffected.
- **Owner decision 2026-10-03:** the panel is UNREAD and may be reused by a new prospective registration signed before
  any export or read of it. No panel or settlement date's 88a data may be exported or read before signature.

Disclosed prior reads (production completes this list at signature; any omission voids the signature):

1. Calibration 2026-09-27..29: calibration-format exports, their receipts, the band union, input bytes and export
   peak above. Production states whether the hazard scalar was computed and, if so, its value.
2. Synthetic-fixture cost studies #166, #168 and #175 and the plan B audit. No real data.
3. Other studies' reads before 2026-09-30 (plugin bar on 09-26; the T+1/T+2 market-only and desk-study pilots on
   dates up to 09-29). None reads panel dates.
4. **Conflict to resolve before signature:** the T+1 fair-value read (`docs/research/t1-fair-value-preregistration-2026-09-25.md` at the exam tree)
   scores target dates up to 2026-10-08 against captured 88a T+1/T+2 mids, which were captured on panel dates
   09-30..10-07. If it runs before this draft is signed, those dates are no longer unread. Recommended: defer that read
   until this registration's look, or until the owner abandons it.
5. Austin, target date 2026-10-03: its settlement band was seen by the production agent at 07:20 America/Toronto on
   2026-10-05; that market-date is excluded from the panel (above).
6. The author of this draft read code and documents only. No 88a, settlement, wallet or replay output was opened.

## 3. Changes from the signed exam, each with its motivation

Every change below is motivated by measured cost, by a defect found in code, or by the design document. None is
motivated by an outcome: no panel data has been read, and no economic result exists for any date.

| # | Change | Class | Motivation | Effect on the estimand |
| --- | --- | --- | --- | --- |
| C1 | **Decision schedule:** a band is decided only at its own events (§5) | semantic | Cost: removes the band-squared term, which is what made the exam unrunnable. Defect: under the frozen loop, a band with resting `informed-v0` legs is cancelled by another band's event 10–60 s after its own book, because the 10 s freshness gate runs before the hold path. `blind_re1` returns before that gate, so the coupling penalizes only the informed policy, for reasons unrelated to information (plan B audit §A). Live parity: the venue's book stream sends book *changes*, so a live maker re-decides a band when its book changes, not when a capture re-sends an unchanged book; waking on every re-sent book would re-create the same stale-book cancellation through the band's own re-projections (owner decision 2026-10-04, §5 rule 1). The same stale-book cancellation re-entered through re-stamped outcome views, which every evaluation re-emits; rule 4 wakes only on view content (owner decision 2026-10-05, §5 rule 4 = B). | Same estimand; policy behaviour differs from the frozen loop, so the result is not comparable with the frozen engine's. |
| C2 | **Universe:** a band-minute is quotable only while its captured descriptor says local horizon 1 or 2 (§4) | population | Design: T+1/T+2 are "the bands the maker quotes" ([design](../operations/informed-maker-design-2026-09-25.md) build item 5 and band choice item 8); `informed-v0`'s `eligible_horizons` is already (1, 2); the hazard denominator is already T+1/T+2. Under the frozen universe the informed-minus-blind contrast on T+0 cells compared `blind_re1`'s T+0 quoting with an informed policy that refuses by construction. Cost: removes T+0 decisions. | Cells stay market × UTC date. The contrast becomes like-for-like on the bands the informed policy can quote. |
| C3 | **Bundle format v0.2:** coverage groups per trade-stream subscription, sorted streams and a streaming exporter (§6). Duplicate elision is admitted by the format but removes nothing against the v0.1 exporter. | representation | Cost: the 9.9 GiB export peak on 1.30 GB per date (exporter peak ≈ 6x output) comes from holding the whole output in memory, copying it, and parsing it twice to validate. Per-condition coverage rows are the one kind that compacts: 92.5% smaller on the W2 fixture. | None, proven by an expansion-equivalence test on calibration dates (gate E3). |
| C4 | **Per-cell aggregate report** with the full interval list in a hash-bound sidecar (§7) | representation | Cost: `excluded_intervals` made up most of the 225 MB fixture report and is read by no estimator. | None: every estimator reads cell sums. Band-day scores and excluded cells with reasons are still published. |
| C5 | **Exact money arithmetic:** amounts quantized to 1e-6 pUSD with Decimal Inexact trapped; reward accrual in integer microseconds, divided once per band-day | arithmetic convention | Needed for running portfolio totals (C1) to be exact. The frozen float/Decimal path differs at about 1e-25. | Digits beyond 1e-6 pUSD only. |
| C6 | **Designated host:** the 32 GB workstation runs the rehearsal and the look; the capture host only exports (§8) | operational | Capture evidence is the first operating objective; a multi-hour run on the 16 GB capture host risks it. The workstation's limits are measured and fixed here. | None. |
| C7 | **Ceilings** derived from calibration-only rehearsals of the v2 pipeline, per date and for the whole run, with host limits for the designated host (§9) | operational | Clarification 2's rule applied to the v2 pipeline and host; adds a whole-run memory measurement because v2 streams days. | None. |
| C8 | **Two gates before signature** (executability, reachability) | governance | The exam was signed before it was measured, and Clarification 3 showed that a screen-suppressed run cannot reach MET. | None; a failed gate stops signature, not a scored run. |
| C9 | **Settlement-only 10-15** in addition to 10-14 | operational | `informed-v0` quotes only T+1/T+2, so its 10-13 positions settle on target 10-14. That settlement fact may be captured on the 10-15 UTC day. Without it, those fills stay unresolved and their cells drop out. The signed exam had the same latent gap. | Fewer unresolved-fill exclusions; no quote minutes added. |
| C10 | **Small-cluster sensitivity** reported beside each economic cell (§12) | reporting | With 14 date clusters the percentile bootstrap probably under-covers (plan B audit §C). | None: the decision rule is unchanged. |
| C11 | **Own legs in the decision book:** the decision book holds each resting leg on its token's bid array at its price and mirrored on the other token's ask array at `1 − price`, creating levels and summing sizes (`compose_book`) | engine correction (defect) | Defect found in code by the shadow-gate review (2026-10-06): the frozen loop added own size only at existing public levels and only to the YES arrays, so the policy decided on a book that is neither the public book nor the venue's book. Live parity: the venue book shows own orders on both token books (RE-1, YES/NO mirror). Not motivated by any outcome: no panel date had been read or run. | Policy behaviour differs from the frozen loop wherever a leg rests at a price without public liquidity, including the qualified mid and the HOLD/requote path. An own leg touched or crossed by the public book without a print now pulls `CROSSED_BOOK` (no same-instant replacement) where the frozen loop pulled `TOUCH_BUFFER` and replaced; on the venue that state is an at-price fill, which paper does not credit. The values of the registered estimands change in every quoting arm (informed-v0, blind_re1 and clock_only); their definitions do not. Not comparable with the frozen engine on those decisions. |
| C12 | **Replacement book:** the same-instant replacement after a replacement-reason CANCEL decides on the public book, without the just-cancelled own legs | engine correction (defect) | Defect found in code by the shadow-gate review (2026-10-06): the frozen loop re-used the pre-cancel book, so the cancelled own size counted as competing liquidity and displayed depth for the replacement. Live parity: live decides again only after the cancel is acknowledged, on a book without those orders. Not motivated by any outcome. | Replacement QUOTEs differ from the frozen loop where cancelled legs sat on public levels; the replacement still happens at the cancel instant (live: after acknowledgement), and that timing is not changed. |
| C13 | **Local-midnight descriptor refresh:** at each market's local midnight the engine's inputs carry a derived descriptor whose `horizon_days` follows the new local date; a later captured descriptor supersedes it | input-construction correction | Found by the shadow-gate review (2026-10-06): captured descriptors kept the previous day's horizon for 15-120 min after local midnight (rediscovery cadence), so horizon-gated decisions and the lead-0 boundary lagged the market's local date. Live parity: the live executor applies the same function. Not motivated by any outcome: no panel date had been read or run. | Horizon-gated decisions in `[local midnight, next captured descriptor)` differ from the frozen loop. If the exam's per-day reader applies the day-open re-emission, decisions in `[00:00, first fresh record)` of each UTC day differ too (class A7). |
| C15 | **Horizon clause applied mechanically:** active intervals end at the market's local midnight when the latest captured **or derived** (C13) descriptor leaves leads 1..2; the resting legs are withdrawn at that interval end; `blind_re1` gets the same horizon gate as `informed-v0` (`HORIZON_NOT_ELIGIBLE`) | input-construction and engine correction | Owner decision Q2(a) full, 2026-10-08. Found by the gate-logic review: the manifest builder wrote whole-day intervals minus 05-08Z, so the §4 text ("intervals derive mechanically from descriptors") did not hold, T+0 minutes after local midnight were scored as NO_QUOTE instead of exclusions, legs rested until their next own wake, and `blind_re1` (no `eligible_horizons`) kept quoting T+0 bands the informed arm refuses. Not motivated by any outcome: no panel date had been read or run. | Fewer active minutes (T+0 after local midnight becomes `horizon_outside_1_2` exclusions), no T+0 quoting in any arm, legs pulled `OUTSIDE_ACTIVE_INTERVAL` at local midnight. Re-run attributed as its own class **A8** against W1+W2+F3 (not folded into A6). A8 is not self-labelling: a difference is A8 only where the engine's own horizon read is missing or outside 1..2, and the re-run fails on any decision taken at such a horizon other than the `OUTSIDE_ACTIVE_INTERVAL` cancel at the instant the horizon leaves 1..2, on legs still resting after that instant, or on any window cut where the engine reads 1..2. The A8 fixtures show zero quote, fill and cash deltas; the value effects rest on the hand-built engine tests. Exclusion precedence, gate ordering and the v1 manifest change are disclosed in §4. |

C11-C13 are engine rulings W1(a), W2(a) and F3 (owner decision 2026-10-07); C15 is ruling Q2(a) (owner decision
2026-10-08; the number C14 is reserved for R1). They land before signature; if the
engine fix misses the signature date, the signature slips (no "known deviation" fallback). Each was re-run against
the frozen engine on fictional fixtures only, and every changed decision was attributed to its allowed class
(A1-A3 for C11, A5 for C12, A6 for C13; C15 against the C11-C13 engine, class A8), directly or as a cascade from a direct difference; an unattributed
difference fails the re-run (`tools/research/maker_replay_v2/attribution.py`, pinned by
`tests/maker_core/test_replay_v2_attribution.py`). C11 also adds the diagnostic `OWN_LEG_CROSSED`: a recorded
`CANCEL CROSSED_BOOK` at which the public book alone is not crossed. It is the paper analogue of a live at-price
fill, is reported per day, and is never counted as a fill. The fixture re-runs bind no panel value.

C13's inputs are bound as follows (owner decisions T1(a), T2(a) and T3(a), 2026-10-09). They add binding fields
only; no decision, P&L or base-pass prefix digest changes.
- **Zone data (T1):** `tzdata` is a pinned dependency (`bundle.TZDATA_VERSION`, the same pin in `pyproject.toml`
  and `requirements.txt`). Zone names and zone rules come only from that package, never from the platform's
  TZPATH, so local midnights do not depend on the machine. The run binding records the tzdata version, its IANA
  release and the SHA-256 of each zone file the run used. A different installed tzdata refuses the run
  (`tzdata_version_unpinned`), and so does an imported `tzdata` module that is not the installed distribution's
  (its `__version__` differs, or its file is not in the distribution's package directory; a sourceless `.pyc`-only
  install is accepted; `tzdata_package_mismatch`).
- **Run binding (T2):** `pipeline.run_passes` copies the zone map once and binds the refresh flag (always on;
  `day_roll.NO_REFRESH` is refused), the exact market-to-zone map, its SHA-256 and its source, the tzdata block and
  a SHA-256 of the run's own days, provenance, input hashes, markets, report configuration and the zone map it
  actually drove with (kept as `Run.time_zones`, with its source) into `run_binding`,
  with a SHA-256 over all of them, and the report carries it. The report refuses a run without that binding, with
  another run's binding (also one from a run with the same inputs driven with another map), with the refresh off, with an altered map or with a tzdata block that differs from the one
  it recomputes from the zone bytes it loads. A scored (non-fixture) report also requires the full source that
  `execution_manifest.market_time_zones` records (builder, `registry_checked`, inventory and registry digests).
  This stops accidental misuse: a run that bypasses `run_passes`, passes a hand-made zone map or reuses a binding
  produces no scored report. It is an integrity check, not an authenticity check: code can still construct a
  forged source, so a verifier recomputes the map from the bound inventory and registry.
- **Registry (T3):** `market_time_zones` requires `registered=` (the domain's market-to-zone registry). Omitting it
  is an error; `None` or a non-mapping refuses `market_time_zone_registry_required`. A market missing from the
  registry, or registered under another name, is refused.
- **Day gaps (Q2 N1, decided (a), 2026-10-09):** across a missing panel day the day roll carries the last lead
  (current behaviour). It is no longer an open owner item.

Explicitly **not** changed: the 10 s submit freshness gate (still applied at every decision), the 60 s replacement
cooldown (still not scheduled as an event), every profile parameter, the strict net screen, the hazard recipe and
`max_m U_m` scalar, caps and cash, the fill predicate and sibling cancellation, and the RE-1 first-fill/session
convention. Also unchanged: the shared portfolio carried across all dates, never reset.

## 4. Population and universe

- Bundles keep **every** discovered condition of every horizon, so carried inventory can settle and the inventory
  stays complete. The universe rule acts only through active intervals in the execution manifest.
- A condition is **active** at UTC minute t when all of these hold:
  - t is on a quote-panel date;
  - the latest captured or derived descriptor for the condition at or before t has `horizon_days` 1 or 2. A derived
    descriptor recomputes `horizon_days` at each market's local midnight (time zone database rule, from the pinned
    `tzdata` only; §3 after C13) and is otherwise identical to the descriptor before it (C13). Before a condition's
    first descriptor it is inactive (`missing_descriptor`);
  - t is outside 05:00–08:00 UTC;
  - the condition's local target date is on or before 2026-10-14;
  - the condition is not in an owner-excluded market-date (Austin, target 2026-10-03; §2).
  The manifest builder computes intervals mechanically from the panel bundles' descriptors (C15): it replays their
  descriptor records through the engine's own local-midnight reader (`maker_core.replay.v2.horizon`, `day_roll`), so
  an interval ends at the same local midnight at which the engine's `horizon_days` leaves 1..2. Nothing is chosen by
  judgment. The v0.2 exporter's per-condition `active_from`/`active_until` envelope is the single-day form of the same
  rule, `[local midnight of target − 2, local midnight of target)`, clipped to the UTC day.
- Both arms are gated alike: `informed-v0` by its `eligible_horizons` (1, 2) and `blind_re1` by the same set in the
  engine (`HORIZON_NOT_ELIGIBLE`), so the contrast never compares T+0 quoting with a refusal by construction.
- Inactive minutes are exclusions, never zeros. A band that leaves the universe (T+1 → T+0 at local midnight) has its
  resting legs withdrawn by the engine at the interval end (`OUTSIDE_ACTIVE_INTERVAL`). Its inventory is held to
  settlement, as before.
- Disclosure: the calibration hazard count (`calibration.py`, `outside_t1_t2`) still reads **captured** descriptors
  only, with no derived descriptor and no horizon clause. The hazard recipe is inherited unchanged from the signed
  exam; the count's T+1/T+2 denominator can therefore include up to one rediscovery lag (15-120 min) of T+0 time per
  band after local midnight.
- Exclusion takes precedence over maintenance: an ineligible run (`horizon_outside_1_2`, `missing_descriptor`) is one
  exclusion row over its whole span, including any 05:00–08:00 UTC minutes it covers; the maintenance split applies
  only to eligible runs, so no minute is listed twice and maintenance is never the reason for an ineligible minute.
- Gate ordering (disclosure): `blind_re1`'s horizon gate runs in `Kernel.tick` before `blind_tick`, so a blind band
  outside 1..2 is pulled before its runtime is consulted; `informed-v0`'s gate is inside `decide()`, after the HOLD path
  for existing legs. The asymmetry cannot be reached inside the clause windows (every active minute has a lead in 1..2,
  and the interval end withdraws the legs), so it changes no scored decision.
- The v1 exam's manifest output changes: `build_manifest` and `verify_manifest` now emit and check the clause intervals
  and the new exclusion rows, so a v1 manifest rebuilt with this code differs from one built before C15. This is
  acceptable only because the v1 exam is closed NOT EXECUTED; no signed v1 result depends on the old intervals.
- Decided against C13 (owner Q2 N1 (a), 2026-10-09; not changed by C15): a panel with a missing day carries the
  last lead across it, because derived descriptors are produced only at local midnights inside the days driven.
  Manifest and engine agree (both read the same carried lead); a band can stay active at a true lead of 0 or below
  after the gap, and that is the ruled behaviour. A test pins it.
- The inventory lists every discovered condition with its exclusion reason: `HORIZON_OUTSIDE_1_2`
  (`horizon_outside_1_2` in the manifest), `MISSING_DESCRIPTOR` (`missing_descriptor`), `MAINTENANCE_UTC`,
  `TARGET_AFTER_PANEL`, `OWNER_EXCLUDED_PRIOR_READ`, plus every coverage reason.
- Cluster minimums are unchanged: at least 10 date and 10 market clusters per primary contrast after exclusions, and
  the whole-cell rule.

## 5. Engine semantics (the decision schedule)

The engine keeps the frozen record ordering: records are sorted by `(captured_at, sequence)`, same-time prints meet
previously resting orders before new inputs, and same-time wakes are processed in sorted condition-ID order after
every record at that timestamp has been ingested. What changes is **who is decided when**.

A condition is decided at a timestamp only if one of these own events occurs:

1. a book record that changes the condition's **decision-relevant book state**: every price level and size of all four
   sides (`yes_bids`, `yes_asks`, `no_bids`, `no_asks`, as decoded: levels merged by price, zero sizes dropped, sorted)
   and `post_only_available`. The book's `as_of_utc` is not part of that state. A book record whose state equals the
   previous one (a re-sent unchanged book, including the exporter's re-projection of an earlier fetch) is not an own
   event and never reaches `decide()`. It still becomes the condition's latest book, so its `as_of_utc` refreshes the
   **freshness clock** that the book-gap timer, the 10 s submit freshness gate and the re-entry check read: a quiet but
   healthy feed that keeps re-sending an unchanged book never looks stale, while a silent feed, or a re-projection that
   carries the old `as_of_utc`, still goes stale on time (rule 5's book-gap timer wakes it and it is excluded). An
   invalid book record drops the state and is a change. **Decided (owner, 2026-10-05):** (a) re-entry after an
   `INFO_PULL` needs a book whose `as_of_utc` is after the pull (a book merely captured after it is not enough), and
   (b) a re-projection carrying an old `as_of_utc` does not refresh freshness;
2. a change in the condition's trade-coverage state, whether by a coverage-group record or by its `valid_until` expiry.
   A refresh that leaves the state unchanged does not wake it;
3. a terms record whose body differs from the previous one, or terms expiry (`as_of` + 1 h);
4. an info-event record affecting the condition with a changed payload; an outcome-view record that changes the
   condition's **decision-relevant view state**: an available view's condition, exact `p_yes`, joint,
   `valid_until_utc`, calibration grade, model and `inputs_hash`, or an unavailable view's reason and kind. The view's
   `as_of_utc` and `stdev` are not part of that state. The exporter re-stamps every view at every evaluation
   (`as_of_utc` is the evaluation time, and the NBP view's `stdev` grows with its age), and such a re-stamp is not an
   own event. It still becomes the condition's latest view, so every wake reads its `as_of_utc` and `stdev`, as rule 1
   treats a book's `as_of_utc`. A producer's `stdev` may change only with its inputs (pinned by `inputs_hash`) and with
   time; a producer contract test pins that for every producer. Also an event's or view's expiry or window boundary.
   **Decided (owner, 2026-10-05): rule 4 = B** (view content excluding `as_of_utc` and `stdev`, exact `p_yes` and
   `inputs_hash`). This also repairs the C1 stale-book effect through rule 4: under "changed payload" every re-stamp
   woke the band at the exporter's re-projection instants, 20 s after the book fetch, where the 10 s freshness gate
   fails. **Scored outputs change against the payload rule.** On the quoting-dense fictional day (40 bands,
   60 minutes, as_of-only re-stamps), `informed-v0` went from 10,026 wakes, 131 quotes, 3 fills and 4,315
   `BOOK_STALE_OR_FUTURE` decisions to 2,972 wakes, 46 quotes, 6 fills and 113, with cash and inventory different;
5. its own timers: book gap (`as_of` + `max_book_gap_seconds`), the last-three-hours boundary, its active-interval
   boundaries, and the policy's own schedule (`clock_only` pull windows, `blind_re1` session ends);
6. a public print that fills one of its resting legs.

Other conditions' events never wake it. Portfolio changes never wake it: it reads the portfolio at its next own event.
The 10 s staleness threshold, the 60 s cooldown end and the `sigma_eff` width crossing are not events. The decision at
each wake is the unchanged `decide()` with the unchanged inputs. Portfolio predicates (`SAFETY_BUDGET`,
`ONE_BAND_ONLY`, grade caps, cash over-commitment) are read from exact running totals that equal a fresh recomputation
at every wake. A debug mode asserts that equality and runs in every test.

Between wakes, a condition's state (legs, covered or uncovered, pulled or quoted) is carried forward unchanged.
Covered, pulled and excluded time is recorded as run-length intervals per condition, so the cost is in state changes,
not in pops × bands. The pull endpoint's "final resting state at t, carried forward" is read from those intervals.

**Cost (ESTIMATED; the gates measure it):** work per pass is O(Σ own events), which is linear in bands. At about
3 own wakes per band-minute and ~115 T+1/T+2 bands, that is about 0.5 M decisions per pass per date. Rule 1 counts
book *changes*, not book records: the exporter re-projects every live band's latest book at each books row, and the
number of rows grows with the band count, so waking on every record made the work per band grow with B (S3, measured
2026-10-04: runtime(250)/runtime(40) = 11.0 under "every record", against 7.5 allowed). Rule 4 counts view *content*, not re-stamps, for the same reason: at real view cadence the payload rule
measured 11.65, and rule 4 = B measured 5.45 with the registered-cadence wakes (S3, 2026-10-05).

The bundle contract's cash-admission and inventory rules apply unchanged, and so do the fill model and settlement
reconciliation.

## 6. Bundle format v0.2 (compact, look-ahead-free)

`maker_core.replay.bundle.v0.2` extends v0.1. The reader admits both formats; v2 manifests require v0.2.

- **Coverage groups.** The manifest lists `coverage_groups: [{group_id, condition_ids}]`. Coverage records carry a
  `group_id` instead of a `condition_id`, and a condition's coverage is its group's latest record. The exporter forms
  groups from the **trade-stream subscriptions** each condition's tokens joined during the day, not from the capture
  connection. One connection carries several subscriptions, and a token subscribed mid-day starts unhealthy, so a
  connection-level group would be refused whenever an event subscribes after the day's first capture. Conditions
  whose tokens joined exactly the same subscriptions share a group. Conditions never subscribed share one
  always-unhealthy group. The day is refused if two members of one group would have had different v0.1 coverage at
  any capture (`coverage_group_mismatch`). Groups are known only at the day's end, so coverage is spooled to disk and
  compacted after the last capture. One record per group per capture replaces one per condition. The saving is the
  number of seen conditions per group (about 15 on the W0 fixture), not 170x.
- **No duplicate elision is relied on.** The format admits omitting a descriptor or outcome-view record whose
  payload is byte-identical to the condition's previous record of that kind. Against real exports this removes
  nothing:
  - The v0.1 exporter already drops every repeated descriptor, terms, outcome-view, info-event and settlement payload
    before writing (`Projection.add(..., changed=True)`).
  - The rows that remain are not rare. 88a records discovery every minute, and the descriptor carries the
    discovery envelope's hash, so a live condition gets a new descriptor every minute. An outcome view's `as_of_utc`
    moves with every book capture.

  The v2 exporter therefore elides nothing, and a v0.2 bundle expands to exactly the v0.1 rows. Books, terms,
  trades, plugin inputs and settlements are never elided.
- **Capture times do not reach decisions.** A capture time must never change a decision, whether it belongs to an
  elided duplicate or to a regrouped coverage record. The frozen v1 engine does not meet this. Its re-entry rule after
  an `INFO_PULL` compares `state.captured["outcome_view"]` with `resume_after`, and its pull-decision digests hash
  `state.captured` (`engine.py:402` and `:264`). The v2 engine reads only payload fields (`as_of_utc`,
  `valid_until_utc`, values). A test pins that its decision digests do not change when coverage records are
  regrouped.
- **Sorted streams.** Each stream is written in `(captured_at, sequence)` order, and the reader refuses an unsorted
  stream. The exporter emits two kinds out of clock order: plugin inputs keep their original capture time, and ledger
  settlements keep their later record time. Those kinds are sorted on disk in bounded runs (32 MiB) and merged. Every
  other kind is written straight through. Raw-byte hashes are verified in a first pass; the second pass parses
  records one at a time and streams them, so one date never has to be in memory as JSON.
- **Look-ahead rule.** Every v0.2 record is emitted at a capture, using only evidence captured at or before it. No
  record states a future confirmation.
- **Equivalence.** Expanding a v0.2 bundle back to per-condition records must reproduce the v0.1 export of the same
  date record for record and byte for byte, because nothing is elided. The exporter checks this itself before
  publishing, by a streaming re-read. It also records `v01_equivalent.sha256`: the SHA-256 of the `events.jsonl`
  the v0.1 exporter would have written from the same inputs. This is proven on fixtures and on the three calibration
  dates (gate E3, compared by hash only).

## 7. Report

- **Scored report** (under the report ceiling). For each market/UTC-date cell × policy × fill bound:
  - status and exclusion reasons;
  - covered and pulled seconds;
  - `reward_k1`, nominal rebate, settled inventory P&L, unresolved fills, quotes, requotes and markouts;
  - `modeled_net_k1`, `modeled_net_k05` and `modeled_net_k03`;
  - excluded seconds by reason, with the interval count and SHA-256 of the full list;
  - the pull endpoint's per-cell counts: common opportunities, large moves, and pulled minutes and removed moves per
    policy.

  It also holds the band-day table (one row per band/UTC-day/policy/bound), the inference results, Clarification 3's
  fields and the Clarification 2 diagnostics.
- **Run binding** (owner T1(a)/T2(a), 2026-10-09): the day-roll refresh flag, the market-to-zone map with its
  SHA-256 and source, the pinned tzdata version with its zone-file SHA-256s, and the SHA-256 of the run's days,
  input hashes, markets, configuration and driven zone map, plus one SHA-256 over all of them (§3, after C13). The report refuses a
  run without it or with another run's binding.
- **Sidecar** (under its own ceiling, hash-bound in the receipt): the merged run-length excluded intervals and a
  decision-stream SHA-256 per engine pass. No estimator reads it.
- Every estimator, bootstrap and hurdle reads only cell sums, which the registration already defines. So the
  decision is a function of the scored report alone.

## 8. Designated host and limits

| Role | Host | Limits (fixed now) |
| --- | --- | --- |
| Panel and calibration **exports** (v0.2 exporter, pinned module hash) | 16 GB capture host | Under `scripts/ops/replay_bundle_export_nightly.ps1` as it is today: 00:30–04:54 start, shared lease, commit < 70%, ≥ 50 GiB free, 2 GiB child memory, 2,700 s. At most three dates a night. |
| **Rehearsal, manifest build/verify, scored look** | the 32 GB workstation, host ID `DESKTOP-RFCD2GH` (31.2 GiB physical, 32 logical CPUs) | Attended run under `scripts/ops/workstation_heavy.ps1`, with the v2 module admitted. Memory ≤ 70% of physical RAM, so ceilings ≤ 16 GiB (power of two). Whole-run wall time ≤ 12 h, so ceilings ≤ 32,768 s. Input ≤ 16 GiB in total, scored report ≤ 1 GiB, sidecar ≤ 8 GiB, ≥ 100 GiB free at start. No other heavy job runs during the look. |

- **Transfer.** Sealed bundles move from the capture host to the workstation by owner `scp` only. First, a transfer
  manifest (each bundle's day, receipt hash and stream hashes) is committed to the repository; the workstation verifies
  it on arrival and refuses any mismatch.
- **Workstation boundary.** The workstation receives sealed panel bundles under this registration only. That is an
  explicit exception to the session preamble's "fixtures only" boundary, granted by the owner's signature, and it is
  not "copying `data/`". It still grants no capture, credential, exchange or order authority.
- **One canonical manifest.** The reservation is logged in the repository before the first policy replay. The
  reservation consumes the look, exactly as in Clarification 2.

## 9. Ceilings (rule fixed now, values from calibration-only rehearsals)

Rehearsal bundles are v0.2 **night-format** exports of 2026-09-27, 09-28 and 09-29: all record kinds, read for cost
and reachability only. On the workstation, run the full v2 scored pipeline score-free:

- once per date;
- once as a single carried 3-date run.

The full pipeline covers every bound and policy, every matched-clock trial, the bootstrap and report rendering.

Record only these outputs: input bytes, records by kind, engine wakes, decisions, span runs, scored-report bytes,
sidecar bytes, runtime, peak memory above the pre-input baseline, and the [reachability fields](#reachability-gate-before-signature).
Also record equivalence and determinism hashes. No fill, P&L, reward, markout, removed-move count or contrast is kept
or shown.

Let N = 16, the bundles in the scored run (14 quote dates and 2 settlement-only).

| Quantity | Ceiling | Host limit |
| --- | --- | --- |
| input bytes, records, wakes, decisions, span runs, report bytes, sidecar bytes | next power of two ≥ N × the largest per-date value | §8; counts ≤ 2^31 |
| runtime | next power of two ≥ N × the largest per-date runtime, in seconds | 32,768 s, so each date ≤ 2,048 s |
| memory | next power of two ≥ 2 × the 3-date run's peak, plus the measured baseline | 16 GiB |

The memory rule assumes v2 streams days. Gate E5 checks that assumption.

If any derived ceiling exceeds its host limit, the gate fails (§10). The panel is never sampled, truncated or split to
fit. Refusals before the first score do not consume the look (Clarification 2's look protection, unchanged).

Values: `[GATE: per-date table and derived ceilings]`.

## 10. Executability gate (before signature)

These all run on calibration dates only, before any panel export. **All must pass**, or this draft is not signed.

| Gate | Pass condition |
| --- | --- |
| E1 export | The v0.2 night-format export of each calibration date completes under the existing nightly wrapper limits (§8): ≤ 2 GiB child memory, ≤ 2,700 s, receipt `SEALED`. |
| E2 input | ≤ 1 GiB per date of v0.2 bundle bytes, so N × the largest date stays within the 16 GiB input limit. |
| E3 equivalence | Each calibration date's v0.2 bundle expands to its v0.1 calibration export (descriptor, coverage and trade kinds) with an identical SHA-256. Hazard counts n_m and x_m are identical from both formats. Only match or no-match is reported. |
| E4 runtime | Each date ≤ 2,048 s for the full pipeline on the workstation. |
| E5 memory | The 3-date run's peak ≤ 1.25 × the largest single-date peak (days do not accumulate), and the derived memory ceiling ≤ 16 GiB. |
| E6 ceilings | Every derived ceiling is within its §8 limit. Pull opportunity candidates for the projected panel are within the derived `max_events`. |
| E7 determinism | Two rehearsals of one date give byte-identical decision-stream hashes and scored-report bytes. |
| E8 correctness | The fixture suite passes: the v2 engine against the reference schedule, running totals against recomputation, linearity in bands, and no Inexact trap. See the engineering plan. |

**Expectations from the fixtures (W0–W2).** These are MEASURED on fictional data, not gate results
([W2 report](../roadmap/agent-report-2026-10-04-mrv2-w2.md)). The W2 fixture is a full fictional sealed 88a day at
170 conditions, run through the real exporters, with books at 8 levels a side.

- **E1.** The v0.2 night export of the fixture day peaked at 0.303 GiB with one BLAS thread, against 11.50 GiB
  for the v0.1 exporter on the same day, and took about 1,000 s on the workstation. numpy's OpenBLAS commits about
  47 MiB per thread at import. That commit counts against the wrapper's 2 GiB private-memory ceiling before any data
  is read: 1.5 GiB on a 32-thread host, where the same export peaked at 1.84 GiB. P1 should therefore run the
  exporter child with `OPENBLAS_NUM_THREADS=1`.
- **E2 is at risk.** The fixture day is 1.09 GiB of v0.2 bytes, over the 1 GiB rule. At real 88a cadence the
  projection writes:
  - a descriptor per live condition every minute (88a records discovery every minute, and the descriptor carries
    its hash);
  - an outcome view at every book capture (its `as_of_utc` moves).

  Books (44%), outcome views (26%), descriptors (19%) and terms (7%) are 97% of the v0.2 bytes. Coverage groups cut
  coverage by 92.5%, to 3% of the bytes. A book record costs about 488 bytes plus 58 bytes per level a side. The W0
  fixture's 0.585 GiB assumed rare descriptors and views refreshed every 10 minutes. Only P1 measures real depth
  and cadence. If E2 fails, the fix is a format change, for example carrying descriptor provenance and view
  freshness without a full record each capture. That needs an amendment to this draft before signature.
- **E3.** No record is elided, so E3 expects exact equality. The v0.2 receipt's `v01_equivalent.sha256` is the
  hash of the `events.jsonl` the v0.1 exporter would write from the same inputs. It compares directly with an
  existing v0.1 calibration export's stream hash when the inputs are unchanged, and any input growth shows in
  `input_hashes`. Hazard counts n_m and x_m read the same rows, so they match by construction.

Before signature, a failed gate may be fixed by engineering and the gate rerun on the same calibration dates. A
rehearsal is score-free, so rerunning it selects nothing. Clarification 2's "do not re-rehearse" bound a signed exam,
not this draft. After signature, the ceilings are frozen and no rehearsal changes them.

## 11. Reachability gate (before signature)

Clarification 3 shows that the pull hurdle (point ratio ≥ 2) is unreachable in expectation when `informed-v0`'s quoted
fraction f is below 0.5. A screen-suppressed run cannot reach MET, so spending the unread panel on one buys only an
economic estimate. Compute these from the §9 3-date rehearsal, with the hazard scalar from the unchanged recipe:

- **f_cal**: `informed-v0` pooled `strictly_through` quoted seconds ÷ eligible seconds over the three calibration
  dates, under the §4 universe rule applied to calibration dates.
- **Screen pass rate**: decisions that reach the net screen and pass it, ÷ decisions that reach it. Reported with
  `informed-v0`'s decision-reason histogram (counts only) and `blind_re1`'s and `clock_only`'s quoted fractions.
- **Pull identifiability (policy-free)**: N_cal common opportunities and L_cal large-move opportunities from
  midpoints alone. With f_cal, the expected clock-removed moves are L × (1 − f) on the panel scale.

**PASS iff f_cal ≥ 0.5.** This is in-sample for the hazard (same three dates), which is acceptable because it is a
feasibility screen, not a hurdle.

On FAIL, this draft is not signed as written. Exactly one variant is pre-declared now, before the gate is read:

- **R1, per-city hazard.** Each city's bands use their own `U_m` (with Clarification 1's pooled fallback) instead of
  `max_m U_m`. The Bonferroni `q = 1 − 0.01/M` is unchanged, so it is still a 99% family bound. Motivation: the
  global maximum imposes the riskiest city's trade rate on every city, which the design never required.

Recompute f_cal under R1. If it passes, R1 becomes change C14 in the signed text. If R1 also fails, the
recommendation is not to spend the panel, and the owner chooses between pausing and signing anyway, with the text
stating that MET is unreachable in expectation. No other screen, hazard or size change may be tried against the
calibration rehearsal.

Values: `[GATE: f_cal, screen pass rate, N_cal, L_cal, R1 if used]`.

## 12. Statistics, hurdles and power

Unchanged from the registration and Clarification 3:

- **Estimand:** mean paired total modelled net per complete market/UTC-day.
- **Bootstrap:** 2,000 replicates, seed 20260926 (seed + 1 for crossed draws), two-sided 90% percentile intervals.
- **Economic hurdle:** all four lower bounds strictly above zero at `strictly_through`, k = 1 — `informed-v0` minus
  `blind_re1` and minus `no_quote`, each under date and crossed date × market inference.
- **Pull hurdle:** point ratio ≥ 2.0, with exposure matching within one minute.
- **Statuses:** UNDERPOWERED, UNIDENTIFIED and UNMATCHED rules, and Clarification 3's MDE and label.

**Power statement (fixed now).** There are G_D = 14 date clusters and G_M market clusters (Clarification 2's set;
expected 12, minimum 10). The binding detectable effect is `MDE_80 ≈ 2.486 × SE` for the worst of the four cells.
Writing the paired cell difference with date, market and residual standard deviations σ_D, σ_M and σ_E:

| Variance structure | Date-cluster SE | Crossed SE (G_M = 12) | Binding MDE_80 |
| --- | --- | --- | --- |
| residual only (σ_E) | σ_E / √168 | σ_E / √168 | ≈ 0.19 σ_E |
| date-dominated (σ_D) | σ_D / √14 | σ_D / √14 | ≈ 0.66 σ_D |
| equal date and market (σ_D = σ_M = σ) | σ / √14 | σ × √(1/14 + 1/12) | ≈ 0.98 σ |

Before signature, production fills `[GATE: σ proxy and projected MDE]` from the desk-study pilot's per-city-day
P&L standard deviation, where that study's signed text allows it. If it does not, the cell says "no proxy" and
nothing else is computed. If the projected MDE exceeds the owner's reference effect δ_ref (set by the owner at
signature, in pUSD per market/UTC-day), the signed text states that the panel is likely UNDERPOWERED for δ_ref.
This changes no hurdle.

Three disclosed biases:

- k = 1 favours a pass (RE-1 measured k ≈ 0.27–0.32; k = 0.3 is reported, Clarification 2).
- A percentile bootstrap at 12–14 clusters is likely too narrow (C10). The report therefore adds a non-decision
  lower bound for each economic cell: estimate − t(0.95, G − 1) × bootstrap SE, with G = G_D for date inference and
  G = min(G_D, G_M) for crossed.
- Public prints bound fills without a queue model. Strictly-through is primary.

## 13. Look, timeline and authorization

- **Signature:** no later than **2026-10-23** America/Toronto. The owner signs these exact bytes after the gate
  values are filled. Signing binds the raw-byte SHA-256 of this file, the registration, the addendum and
  Clarifications 1–3, with the inherited parts read through §3.
- **Order after signature:**
  1. panel and settlement-only exports (three dates a night at most);
  2. transfer manifest, then transfer;
  3. manifest build and verify on the workstation;
  4. one look on any America/Toronto date up to and including **2026-11-15**.

  A reservation consumes the look whatever the date. Authorization ID **`maker-replay-v2-v1`**, expiring
  **2026-11-16T05:00Z**.
- **If unsigned by 10-23**, the draft lapses. The owner then decides whether to keep the panel's 88a retention.
- **Preconditions the owner must confirm now:**
  - a retention hold on 88a sources for UTC 2026-09-27..10-15 (lossless compression only) until the look or lapse;
  - deferral of the T+1 read (§2 item 4);
  - the workstation exception (§8).
- **No live authority.** A MET verdict only qualifies `informed-v0` for the registration's remaining prerequisites
  (Clarification 3 (d)). Candidate 2's code rule then keys on this registration's closure by DECISION_LOG row, not on
  the 10-15 look.

## 14. Owner-signature block (unsigned)

| Binding | Owner attestation |
| --- | --- |
| Decision-log authorization ID | PENDING (`maker-replay-v2-v1`) |
| Gates E1–E8 and reachability | PENDING: values and receipts |
| This file: path, commit, raw-byte SHA-256 | PENDING |
| Inherited files: registration, addendum, Clarifications 1–3 SHA-256 | PENDING |
| Prior-read disclosure complete, panel unread at signature | PENDING (production attestation) |
| T+1 read deferred / retention hold / workstation exception | PENDING |
| δ_ref (pUSD per market/UTC-day) | PENDING |
| Signed at / expiry | PENDING / 2026-11-16T05:00Z |

Do not insert a simulated signature. Writing or pushing this draft authorizes nothing.

## Update this file when

This is a draft. Change it only before signature, by a reviewed commit that says which section changed and why.
After signature it is frozen; changing it needs a new dated registration.
