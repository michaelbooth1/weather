# Exam plan B swarm — 2026-10-03

- **Owns:** the 19-agent study of why the replay exam's cost explodes with band count, an executable prospective Clarification 4 (A'), alternatives, and Option B governance.
- **Read when:** deciding A/A'/B for maker-replay-2026-10-15 after the real band density is measured.
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)) or decisions in force ([DECISION_LOG](../../operations/DECISION_LOG.md)).

Read-only agents; no exam-blackout data read; numbers are MEASURED only where marked. Owner decisions are in DECISION_LOG.

## Synthesis

**Verdict:** The exam cost grows with the square of the band count because of how the engine is built. The signed text does not require it. The signed text does freeze the basis engine and the count of outputs it produces, so any fix needs a prospective signed document. Code puts the real panel at about 150–250 bands per date (ESTIMATED). Streaming alone stops fitting at about 14. Recommended path: Option A' with a trajectory-identical engine and a compact report under a prospective Clarification 4, go/no-go 10-12. If that fails, Option B, closed so the unread panel can still be reused. The desk study runs in parallel either way.

## (A) Why the exam explodes

**Mechanism (MEASURED in code at 664c8943).**
- `ReplayEngine.run()` keeps one timestamp heap for all bands.
- At every heap pop it writes a Span for every active band (`engine.py:459-470`) and ticks every band (`:484-487`). Each tick records a decision, even a pull that changes nothing (`:258-265`).
- Each band adds about 2 heap pops per minute: its terms record and that record's +1 h expiry (`:296-299`). Book, coverage and book-expiry events add more (`:285-313`).
- So per pass, spans plus decisions ≈ events × bands, which is Θ(minutes·B²). `portfolio()` and the cash over-commitment check add an O(B·F) loop per tick (`:220-240`, `:446-447`), so runtime may be closer to B³. The workstation's "~quadratic" fit is a lower bound (ESTIMATED).

**Report bytes (MEASURED share on the fixture).**
- The bytes are almost all `traces[*].excluded_intervals`, one row per uncovered span, never merged (`report.py:71-72`; #168 report:74; #175 §2).
- `git grep` finds it written only at `report.py:71`. No estimator, hurdle or receipt check reads it.
- It is, however, the only place the engine's coverage reason codes are emitted. A compact report must keep per-cell reasons to satisfy "publish the excluded cells and reasons" (prereg:50).

**Correction on scale (MEASURED in code).** The bundle re-describes every band 88a captured at any point that UTC day, every minute, all day.
- Book records are not deduplicated (`bundle.py:166-195`), and conditions are active for the whole day (`:410-411`).
- So engine events track the daily union N_d, not the ≤120 bands captured per minute (the 10-per-city × 12 rule, `maker_evidence_public.py:194-213`).
- Cost multiplier versus the 12-band fixture ≈ (N_d/12)². At N_d of 150–250 that is about 156–434× (ESTIMATED).

**Required by the signed text, or an artifact?** Mostly an artifact.
- No clause sets span granularity, requires `decision_sha256` or `excluded_intervals`, or requires ticking band j at band i's events.
- But prereg:57-58 freezes "the policy semantics of the harness basis" (8ee7b8ad has the same loop).
- Clarification 2 (C2:30-37) derives ceilings from the decisions + spans count and the report bytes of the pinned pipeline.
- Consequences:
  - An engine that reproduces the same trajectory, and a compact report, are operational changes. They are still hashed and must be declared before the rehearsal.
  - Changing who gets ticked when is a semantic change.

**Cross-band coupling (MEASURED path; size UNVERIFIED).**
- informed-v0 checks the 10 s book-freshness gate before its hold path (`policy.py:231`). A band with resting legs is cancelled with no replacement at the first event from any band landing 10–60 s after its own book. The 60 s cooldown is never scheduled as an event.
- blind_re1 returns before that gate (`policy.py:213-230`). The asymmetry is real.
- The earlier "~0.17 quoted fraction" figure was REFUTED: in the fixture, coverage expiry and trade rate T drive this, not B.
- The gate is a signed rule ("ten-second submit freshness still applies at every decision", bundle contract:161-162). Removing it is a new registration, not a fix.

**Byte identity.** Any engine that keeps `decision_sha256` and `excluded_intervals` byte-identical has a Θ(E·B) floor (MEASURED). Streaming saves memory, not work (#175).

## (B) Decision tree after tonight's calibration exports

**Measure first (score-free, calibration dates only; no panel export):**
- Per date: N_d = `len(bundle.json.conditions)`.
- `counts.book` and `counts.coverage` divided by (N_d × 1440). If this ratio is near 1, events track the union.
- Distinct `captured_at` values per minute, and the terms cadence per band (per minute or on change; the design doc says on change, `informed-maker-design-2026-09-25.md:177`).
- Use the #166 precheck to project `engine_events` and spans + decisions per date.
- Do not run `derive_ceilings` on the current code yet. The 12-band fixture already gives 2.5 GiB × 15 → 64 GiB > 11.2 GiB, so it will exit 3. The runbook (:236-238) says exit 3 "ends the exam … Do not re-rehearse". Recording it now would turn any Clarification 4 into a retroactive rescue.

Thresholds use R = projected (spans + decisions) per pass per date ÷ the fixture's 884,952. Under ×15 rounded to a power of two, runtime needs per-date time ≤ 546 s, report bytes ≤ 546 MiB, and memory ≤ 546 MiB above baseline (C2:36).

**Option A: streaming only, the current Clarification 4 draft.**
- Runtime fits only if 373 s × R ≤ 546 s, so R ≤ 1.46 (N_d ≲ 14).
- Report fits only if R ≲ 2.5.
- Streaming must also bring the 1-date peak to ≤ 546 MiB.
- Expect it to fail. Take Option A only if the real cadence is far sparser than the fixture (UNVERIFIED).

**Option A': trajectory-identical engine plus compact report, as Clarification 4 (operational).** Take it if 1.46 < R and the workstation prototype (Mission 1) shows a per-date runtime ≤ 546 s at the measured N_d with differential equivalence passing. Contents:
1. **Wake-set engine.** Keep the frozen global heap. Wake band i only at:
   - its own records and expiries;
   - the first pop after one of its local thresholds (book + 10 s, quote/requote + 60 s, the `sigma_eff` tick-width crossing found by binary search on real `decide()`);
   - any change in a portfolio predicate.
   Use running totals for reserve, inventory, cash, events and factors, with a Decimal Inexact trap that falls back to the frozen loop. Keep the in-timestamp sorted ordering. Equivalence is UNVERIFIED and must be proven.
2. **Compact report.** Decision count plus a hash of the wake-set stream. `excluded_intervals` becomes `{count, sha256, seconds_by_reason}` per market/UTC-date cell, policy and bound. The `traces` key stays non-empty (`execution_receipt.py:90`). The full list goes to a hash-bound sidecar outside the scored-report ceiling.
3. **Exact `reward_k1` arithmetic.** Integer microseconds per band-day, divided once. This is declared as an arithmetic convention, because it changes hurdle digits at about 1e-25 (ESTIMATED). Cash-hours are outside the hurdle (`score.py:135-136`).
4. **Memory-ceiling rule.** Only if needed. GO requires a measured 1-date streamed peak ≤ 4 GiB and a 3-date peak ≤ 8 GiB (the earlier "~8 GiB fits" claim was CORRECTED). This edits C2, so it needs explicit owner classification.
5. **Authorization.**
   - An explicit statement that a fresh calibration rehearsal is authorized.
   - v4 bound to registration, addendum and C1–C4. Verifier changes in `authorization.py`: CLARIFIED_IDS, SIGNED_BINDINGS, EXPIRES ≤ 2026-11-01T04:00Z, LATE_LOOK_UNTIL 10-31.
   - Re-pin `source_hashes()` (all of `maker_core/**`) and the exporter hash, then re-export calibration 09-27..29. That 88a source data is still readable is UNVERIFIED.

**Option A'-ws: add designated-host execution.** Only if the capture host fails on input bytes alone; streaming already shows input at 1.09× the limit on the fixture.
- A Clarification names the workstation by host ID, with limits of 70% of 32 GiB and a pre-declared runtime cap of ≤ 24 h.
- Rehearsal and look run on that host only, under an attended `workstation_heavy.ps1` run. Unattended mode is archive-only (`workstation_heavy.ps1:101-106`). `maker_core.replay` is already admitted.
- Hash-bound bundle transfer, with the manifest committed before the copy.
- One canonical manifest, with the reservation logged externally (`maker-replay-bundle.md:431-433`).
- Owner line needed: sealed bundles are not "copying `data/`".

**A' timeline to a look by 10-31 (ESTIMATED, tight):**

| Dates | Step |
| --- | --- |
| 10-03..10-08 | Mission 1 prototype and differential test |
| 10-09..10-10 | Mission 2 Clarification 4 text against measured numbers |
| 10-12 | Owner go/no-go and byte-exact signature; DECISION_LOG REVOKE v1 |
| 10-13..10-15 | Review and land; `roll_verdict` decides quiet window; re-pin; calibration re-export |
| 10-16 | Rehearsal (exit 0 required) |
| 10-17..10-23 | 15 panel exports at 2–3 a night, only after exit 0 |
| 10-24..10-30 | APPROVE v4 and look; 1–2 days of slack |

**Semantic variants (A'') need a new prospective registration on the unread panel, not a Clarification:**
- per-band or minute-grid ticks (breaks addendum:87-90 "No extra policy tick"; changes fills);
- freshness checked at submit only;
- active windows limited to selected minutes (cuts both events and candidates);
- band subset;
- daily portfolio reset.

Any of these must be signed before any panel export and before the 10-15 T+1 read, disclosing #166/#168/#175 and the calibration counts.

**Option B: not executable.** Take it if Mission 1 misses 546 s per date, equivalence fails, or 10-12 passes without a signature.
1. Run `derive_ceilings` once on the signed code, or record that it was never run. On exit 3, keep `ceiling-measurement.json` and the rehearsal JSONs. That writes nothing under `attempts\` and consumes no look (`pack_cli.py:160-178`; C2:43-47).
2. Owner rows, governance draft corrected:
   - "Option B: maker-replay-2026-10-15 closed NOT EXECUTED (C2:41-42 'not executable on this host'), ceiling SHA …, binding …; not a scored BLOCKED; no panel export, build or read; look unspent; panel 09-30..10-13 (10-14 settlement-only) UNREAD, reusable by a future prospective registration signed before any export of it; v3 never written; C4 not signed; 88a 09-30..10-14 retained (lossless compression only)."
   - "REVOKE_MAKER_REPLAY v1."
   - C3:111 offers a successor on new dates or a pause. The owner classification "NOT EXECUTED, not BLOCKED" removes any reading that would bar reuse.
3. Rewrite STATE_OF_PLAY: exam closed. The critical path becomes the successor decision. The T+1 read goes ahead independently. The exam-period merge policy lapses or is renewed.
4. Amend the candidate 2 draft (#137):
   - inherit C2 (and C4 if signed);
   - run its own calibration rehearsal;
   - change its code rule from "after the 10-15 look executed", which never clears under B, to "after candidate 1 is closed by a DECISION_LOG row".

## (C) Ranked alternative paths to the maker decision

1. **A' on the signed exam.** Same estimand as signed (informed vs blind vs no-quote at both fill bounds). Decision by 10-31. Risk: engineering against a 9-day build window.
2. **Desk study (frozen prereg, read-only), in parallel regardless.**
   - The pilot (09-24..09-29) gives σ_d and N_req by about 10-06..10-08, once the owner copies the pilot export over with scp.
   - Verdict about 11-01..11-03. If N_req is 15–28 it slips to mid-November; if N_req > 28 the result is UNDECIDABLE.
   - It cannot value the informed policy.
3. **New prospective lighter registration on the unread panel (A'').** Per-event or city-day partitions, selected-minute windows, compact statistics, run on the workstation. Verdict about 10-20..10-31 (ESTIMATED). Must be signed before 10-15 and before any panel export.
4. **Shadow runner (#115).** A parity gate, no economics. Start once reviewed, so its ≥7-day gate runs in parallel.
5. **RE-2 parameter run** (k(τ), fill rate, queue depth). Needs bleed enforcement in the quoting loop first: `ledger.py:192-197` only labels it. Owner-started and paused. It cannot decide the sign at δ.

**Power caveats for any path (ESTIMATED):**
- There are 14 quote-date clusters, and the market floor (≤ 12) caps the minimum detectable effect.
- The percentile bootstrap at G ≈ 12–14 is likely too narrow.
- k = 1 favours a pass (RE-1 measured k ≈ 0.27–0.32).
- A screen-suppressed run cannot reach MET. Add a pre-look reachability gate (calibration-only screen pass rate) to any new registration.

## (D) Paste-ready workstation prompts

**Mission 1: trajectory-identical replay engine and scaling measurement**

Start from docs/operations/WORKSTATION_SESSION_PREAMBLE.md. Branch `codex/replay-wakeset-20261003` from `origin/codex/integration-exam-20261002` @664c8943. Do not modify the exam tree's existing modules in place: add `src/maker_core/replay/engine_wakeset.py` plus tests. Run every heavy command through `scripts/ops/workstation_heavy.ps1`. Use only synthetic fixtures (`tools/research/replay_memory/fixture.py`, #166 precheck). Never touch panel, settlement or `data/` content.
(1) Build a wake-set engine. Keep the frozen global heap. Wake a condition only at its own records and expiries; at the first pop after its local thresholds (book+10 s, last_quote/last_requote+60 s, the `sigma_eff` tick-width crossing, found by binary search on real `decide()`); or when a portfolio predicate it depends on changes (SAFETY_BUDGET, ONE_BAND_ONLY, GRADE_SIZE_CAP, cash over-commitment). Use running totals for reserve, inventory, cash, event and factor exposure, with a decimal Inexact trap that falls back to the frozen loop. Keep the in-timestamp sorted-cid ordering. Emit spans run-length, and accrue reward in integer microseconds per band-day.
(2) Differential test against the frozen `ReplayEngine` for all four policies, both bounds and every clock-bisection trial, at D = 12/40/120 and two trade rates T. Require identical fills, settlements, final cash, legs, covered state at every minute start, score seconds, pull counts and clock matches. Report every divergence.
(3) Measure per-date runtime, peak memory, spans/decisions and report bytes for both engines at D ∈ {12, 40, 60, 120, 200}, on a full-day fixture. Also measure informed-v0 quoted fraction against both B and T (cross-band freshness-cancel hypothesis).
(4) Write `docs/roadmap/agent-report-2026-10-0X-replay-wakeset.md`, marking MEASURED vs ESTIMATED: the per-date ×15 projection against the 546 s / 546 MiB budgets, and whether equivalence holds. Open a draft PR. Merge origin/master and regenerate the correspondence index after the commit. Hand back the head sha.
No auto-fix, thanks.

**Mission 2: Clarification 4 and Option B packet (docs only)**

Start from docs/operations/WORKSTATION_SESSION_PREAMBLE.md. Branch `codex/clarification-4-draft-20261003` from `origin/codex/integration-exam-20261002` @664c8943. Docs only. Read the registration, addendum, Clarifications 1–3, `docs/operations/maker-replay-bundle.md`, the runbook `docs/roadmap/agent-report-2026-10-111e-followup.md`, and reports #166/#168/#175. Do not read panel or settlement data.
(1) Draft `docs/research/maker-replay-clarification-4-DRAFT.md` (unsigned) with separately classified sections:
- (a) operational: a trajectory-identical engine proven by differential test;
- (b) compact report: per-cell × policy × bound `{count, sha256, seconds_by_reason}` replacing `excluded_intervals`, a full-list sidecar, `traces` kept non-empty;
- (c) arithmetic convention: `reward_k1` accrued in exact microseconds and divided once;
- (d) optional memory-ceiling rule (GO only if 1-date peak ≤ 4 GiB and 3-date peak ≤ 8 GiB), flagged as an edit to C2;
- (e) explicit authorization of a fresh calibration rehearsal;
- (f) optional designated workstation host: limits, attended run, hash-bound transfer, one canonical manifest with an externally logged reservation;
- (g) v4 binding with exact `authorization.py` changes (CLARIFIED_IDS, SIGNED_BINDINGS, EXPIRES ≤ 2026-11-01T04:00Z, LATE_LOOK_UNTIL 10-31) and a re-pin/re-export list.
State that semantic changes (tick routing, freshness-at-submit, selected-minute windows, band subset) are out of scope and need a new registration.
(2) Draft `docs/research/maker-replay-option-b-packet-DRAFT.md`: the exact DECISION_LOG rows (Option B NOT EXECUTED, citing C2:41-42; REVOKE v1), the STATE_OF_PLAY rewrite text, and the #137 code-rule amendment.
(3) Run the agent docs audit. Merge origin/master and regenerate the correspondence index after the commit. Draft PR. Hand back the head sha.
No auto-fix, thanks.

**Mission 3: desk-study pilot analysis**

Start from docs/operations/WORKSTATION_SESSION_PREAMBLE.md. Branch from the desk-study branch carrying `docs/research/maker-pnl-adverse-selection-preregistration-2026-10-01.md` (commits 574f8369b, 67e44273b). Implement the frozen estimand as new modules under `tools/research/` or `src/maker_core/`, linear in band-days, with deterministic tests on synthetic data. Run heavy commands through `workstation_heavy.ps1`. When the owner-supplied pilot export (09-24..09-29) is present, compute only what the prereg allows on the pilot: σ_d, σ_up, N_req and the power branch. Read no decision-panel date (10-17..10-30). Report a +120-min markout variance only if a signed desk-study Clarification allows it; otherwise list it as a proposal. Write `docs/roadmap/agent-report-2026-10-0X-desk-pilot.md` (MEASURED/ESTIMATED). Merge origin/master and regenerate the index after the commit. Draft PR. Hand back the head sha.
No auto-fix, thanks.

## (E) Owner decisions

1. **Tonight: run calibration exports and the density precheck only; hold `derive_ceilings` and all panel exports.** Recommend yes. This avoids recording an exit 3 that would end the exam as signed.
2. **A' (trajectory-identical engine plus compact report) rather than streaming-only A.** Recommend yes. Streaming-only needs N_d ≲ 14; code implies about 150–250.
3. **Classify compact report and exact accrual as a Clarification and tick-routing/freshness changes as a new registration.** Recommend yes; this follows prereg:57-58 and :141-142.
4. **Keep the 10-12 go/no-go, keyed to Mission 1's measured per-date runtime ≤ 546 s and equivalence passing.** Recommend yes; otherwise Option B.
5. **Under B, classify as NOT EXECUTED (not BLOCKED), revoke v1, never write v3.** Recommend yes; this keeps the panel reusable.
6. **Retention hold on 88a UTC 09-30..10-14.** Recommend yes, now (only lossless compression).
7. **Allow workstation execution with sealed-bundle transfer.** Recommend deferring; sign only if the capture host fails on input bytes alone.
8. **Copy the desk-study pilot export over (scp) now.** Recommend yes; N_req is the most decision-relevant number this week.
9. **Successor semantics (freshness-at-submit, selected-minute windows) as a new registration on the unread panel.** Recommend drafting it only if A' fails, and signing before 10-15.
10. **Build bleed enforcement in the quoting loop before any RE-2.** Recommend yes, but it is not on the critical path.

Everything here comes from reading the pinned exam tree (664c8943) and the workstation report branches. Nothing was executed or changed.

## Critic

**Verdict:** Do not adopt the synthesis as written. Its exam-law reasoning is mostly sound. But it misses the input-bytes ceiling, a host-memory hazard and a contamination path, and it carries two unflagged conflicts with the signed text.

1. **Input bytes probably bind at real scale, and A' does not fix that.** (ESTIMATED from MEASURED inputs.)
   - The fixture's `input_bytes` is 33,188,280 per date (`origin/codex/replay-memory-20261003:docs/roadmap/agent-report-2026-10-03-replay-memory.json:13`).
   - The host limit is 70% of 16 GiB (`bundle.py:37`), so after power-of-two rounding the input ceiling must be ≤ 8 GiB. That allows ≤ 546 MiB per date, about 17× the fixture.
   - If bundle size grows linearly with N_d, input fails at N_d ≈ 200, which is inside the synthesis's own 150–250 estimate. The wake-set engine and the compact report do not reduce input.
   - The "1.09× the limit" figure is UNVERIFIED; I found it in no report.
   - Proposal: report projected input bytes as a fourth threshold, next to runtime, report bytes and memory, before choosing A' or A'-ws.

2. **Running `rehearse` on real calibration bundles could hurt the capture host.**
   - `rehearse` has a 4 h deadline (`pack_cli.py:115`, `bundle.py:39`) but only measures memory; it does not cap it (`:114,137`).
   - At (N_d/12)² over a 2.5 GiB fixture peak, one run could exhaust commit during the night window (ESTIMATED).
   - E1 holds only `derive_ceilings`. It must also explicitly forbid `rehearse` (and any `quote_markets`/build step) on the capture host until a C4 engine exists.

3. **C4 conflicts with signed text that the synthesis does not name.**
   - C2:56 says "No other change is permitted."
   - The runbook (followup:236) says "Do not re-rehearse to make it fit."
   - A' is a re-rehearsal designed to fit. The owner must explicitly supersede both lines, and C4 must disclose the fixture projection that motivated it. Calling A' "operational" does not make it so.

4. **The Inexact fallback can spend the look.**
   - Falling back to the frozen loop mid-run brings back B² cost during the scored run.
   - A ceiling refusal after the first score consumes the look (C2:45-47).
   - Proposal: in the scored run, a fallback must refuse before any score, or the rehearsal must prove the fallback never fires on the calibration dates.

5. **Equivalence on real data cannot be shown as written.**
   - Mission 1 uses synthetic data only. Comparing fills or cash on calibration dates would breach C2's rehearsal rule ("no score, fill … kept or shown", C2:30-31).
   - Proposal: on a calibration date, compare only a blinded hash of the decision and fill stream from each engine (match or no match).

6. **The T+1 read may contaminate a panel meant for reuse** (UNVERIFIED).
   - The synthesis says it "goes ahead independently". C3:98 makes the T+1 fair-value reliability table a prerequisite.
   - If that table reads 09-30..10-14 settlements, a future registration on "the unread panel" (Option B, A'') is no longer clean.
   - Confirm that its date range excludes the panel dates, or record that it read them.

7. **Option B's reuse claim goes beyond C3.**
   - C3:111 offers only "a successor registration on new dates" or a pause.
   - Classifying the exam "NOT EXECUTED" is an owner reinterpretation, not something the signed text grants. It must be signed as such, together with the #166/#168/#175 disclosures, before any panel export.

8. **Several claims are already true or rest on unchecked assumptions.**
   - `authorization.py:40-44` already gives v2 and v3 EXPIRES 2026-11-01T04Z and LATE_LOOK_UNTIL 10-31. Only v4 entries are new.
   - The cross-band coupling path is MEASURED (`policy.py:231` comes after the blind return at `:213-230`). That a stale-book refusal cancels resting legs depends on engine handling, and I did not trace it (UNVERIFIED).
   - The timeline needs 15 panel exports at night on the capture host by 10-23. Exporter memory and IO at real N_d were never measured. Add an export-cost precheck on one calibration date to tonight's work.

**Missing:** a cheap kill-test tonight. `len(conditions)` and the export size of one calibration date would settle findings 1 and 2 and the A'-versus-B choice before any engineering is spent.

Read only at 664c8943 and `origin/codex/replay-memory-20261003`; nothing was executed or changed.
