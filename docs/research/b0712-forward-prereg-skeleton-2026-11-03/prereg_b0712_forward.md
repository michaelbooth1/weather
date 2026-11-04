# Stage 4b — separate 07-12 forward test of row-28 candidate B, SKELETON prereg

**CLOSED (master ruling 2026-11-04, not a kill: nothing was frozen).** E1 is DON'T ADD: on five seasons the served
S beats B at 07-12 (EF §10ax; register X107). There is no further skeleton work, no K3 for B and no embargo ask.
This file stays as a record only.

Status: **SKELETON, NOT A DRAFT FOR FREEZE.** Nothing in this file binds. Drafting is approved in principle by master
(2026-11-03); every number that depends on E1 (stage 1) or K3 (stage 3) is a `<PLACEHOLDER: …>` until those report.
`prereg_check --forward` is expected to fail on the placeholders. It freezes only after master fills them, the owner
answers the embargo-line question (§1, open; master carries it), and a freeze commit records its sha256.

Written by lane L16 on the WS (non-capture) on 2026-11-03 from `origin/master` `621d67f0f`, **outcome-blind**: no
input, label, price, outcome or score of any date was read, and no data file was opened. Sources, read as text only:

- template: the row-28b forward draft, `claude/row28b-forward-prereg-draft-20261103` @ `acab59345`
  (`docs/research/row28b-forward-prereg-draft-2026-11-03/prereg_row28b_forward.md`), not edited;
- context: the 07-12 program plan, `claude/b0712-program-plan-20261103` @ `a6dd53c1e`
  (`docs/research/b0712-program-plan-2026-11-03/README.md`), stage 4b;
- field list: the item 343b design note, `claude/item343b-design-20261103` @ `a2548e3fe`, §6.

**Model improvement first.** The primary is B − S at 07-12 (§0). Under MODEL_IMPROVEMENT_METHOD §5 rule 4, a win
against served is not edge progress; the market reading of this test rests on the rule-4 w step (§7a), which is a
pre-D0 gate here, not a by-product of the primary.

## 0. Question and scope

> On forward dates from D0, does arm B at hours 07-12 (a separate 07-12 state of the row-28 B recipe, trained on
> Dec 17 – May 31 rows of 2021-2025) beat **the served pre-13 stack S** (the L6 stack over MG-1) at hours 07-12?

- **B@07-12.** Row-28 arm B's spec fitted per hour for h = 7..12 (program plan stage 2), as its **own** state file
  (343b `--hours` set 7-12, §2). The 13-16 state is not touched.
- **S, as served at 07-12** (program plan stage 1, code-traced there): the L6 stack over MG-1 with frozen
  coefficients `07a67425…ee17e9` on N from the season-L6 state `800072c7…2ee2db`, with no date gate; it falls back
  to MG-1 exactly where N is missing or an hour has no coefficient. Full shas: `<PLACEHOLDER: freeze — the L6
  coefficient and season-L6 state sha256, from the bound files>`.
- Out of scope: any change to MG-2, `release-binding.json`, any B-bound file, `B_FORWARD_TEST_DESIGN.md`,
  `docs/research/mg2-composite-binding-2026-10-25/`, the row-28b 13-16 forward test, or PT-1. Nothing here serves,
  promotes or binds. Hours 13-16 are out of scope (they belong to row 28b).
- Prerequisites (program plan kill points): K1a and K1b pass (S is the served comparison); K2 passes (13-16 state
  sha byte-unchanged, 07-12 emission parity); **K3a and K3b pass** (§7a). If K3 fails, this prereg is not frozen.

## 1. Dates

| Item | Value |
| --- | --- |
| D0 | `<PLACEHOLDER: master>`, after this file's freeze commit and **no later than about 2027-02-15** (program plan stage 4), so that N dates end by 2027-05-31, inside B's coverage |
| Deciding dates | the first **N = `<PLACEHOLDER: K3, 80-100>`** forward dates from D0 that pass §4, in date order |
| Last deciding date | `<PLACEHOLDER: D0 + N − 1 + drops>`, never after 2027-05-31 |
| Hard excluded | every date before D0 for scoring; the sealed panel 2026-05-27..07-30 and 2026-06-01..09-29 are never read |

- **Owner embargo-line question: OPEN.** This test needs an owner-OK'd forward embargo line from its D0, as row 28b
  needs one from 12-17. Master carries the question to the owner; this lane does not ask. Freeze waits for it.
- **Rule-9 claimants (method §5 rule 9; look order follows freeze time; to be verified at freeze against the
  CAMPAIGN_LEDGER, the DEV_WINDOW_LEDGER and the reserved window).** A claim whose scope cannot be shown not to
  intersect is treated as intersecting.
  - **F8-MH**: D0 2026-11-02, look 2027-01-26.
  - **T+1**: not yet frozen; its claim `<PLACEHOLDER: freeze — T+1's dates and hours>`.
  - **PT-1**: NOT RUNNABLE (R21), claims no date; receipt
    `docs/research/pt1-not-runnable-2026-11-03/receipt.md` sha256
    `8c45c8d99dabf1e38b21ad3ebd6e1b015a723b54054dd73d72e2373686cf7c35`. Its R21 receipt stands where a PT-1 look
    would.
  - **Row 28b** (B − S at 13-16): scored window 2026-12-17..2027-01-30 (N = 45 if none drops), single read no earlier
    than 2027-01-31; emission 2026-12-17..2027-05-31 (emission only). Whether its scope intersects this test (other
    hours; emission-only dates after 01-30) is `<PLACEHOLDER: master ruling>`; until ruled, it is treated as
    intersecting.
  - Also to verify at freeze, as row 28b lists them: row 72 R-ODC P1, the MG-1 forward shadow, MG-2 / Rule B-1, L6_G.
- **Read rule.** No input-derived score, label or price of any forward date is read before every earlier-frozen or
  bound claimant of that date has looked. All reads happen at one read, after the last deciding date is final (its
  venue-rule label in the R24 frozen copy). Earliest read date: `<PLACEHOLDER: last deciding date + 1>`.
- **Rule B looks** are applied in date order at that single read (§(g)); a look reads a date only when rule 9 allows it
  (method §5 rule 7). They give no early stop in calendar time; a HARM or FUTILE stop is still final for this prereg.

1a. **Pre-D0 requirement.** A DEV_WINDOW_LEDGER K row for B@07-12 on forward dates, as the freeze branch's first
commit and before D0, with verdict pending. No ledger row is added while this file is a skeleton.

## 2. Candidate and comparator

- **B@07-12 (frozen before D0).** The row-28 arm B recipe imported read-only (the B-bound `fit_pooled(train,
  market_id=False, doy=True, raw_columns=False, bias_by="season")`, the NBP mean anchor, the same features, HGB
  `random_state` pinned as in the bound builder), fitted for h = 7..12 through
  `weather.calibration.yearround_refit` (item 343b).
- **343b `--hours` state (as recorded by master, 2026-11-03).** The hour sets are CLOSED: {13-16, 7-12}. One state
  file per set; the default set is 13-16. L56 builds the option after its suite. This test freezes the 7-12 state
  file only; the 13-16 state sha stays byte-unchanged (K2).
- **S.** §0. Dual implementation to 1e-12 on every scored row: `<PLACEHOLDER: freeze — the two S implementations
  (stack and MG-1 fallback), named by module and sha>`.
- **Inputs.** Both arms read the same rows, from as-of-capture inputs only. N (own-observation nowcast) is S's input;
  its coverage at 07-12 is gated by K1b (at least 0.90).
- **NBM v5.0** forward, disclosed as in row 28b §2.
- **Labels.** Venue-rule labels through `read_venue_labels` from the look-morning R24 frozen copy; the mismatch with
  WU-labelled history is disclosed. Denver is excluded from scoring and emission and kept in B's training (as v12).
- **F parity at 07-12.** F (WU-hourly max to the cutoff in training; captured METAR at serve) is a larger share of a
  small F at 07-12 (program plan stage 2). The forward parity control has a 07-12 leg (§4).

## 3. Statistic

d(t) is the mean over the US10 rows at hours 07-12 of [Brier_B − Brier_S] on forward date t; positive means harm.
The point is mean_t d(t). SEs use SD(d)·√κ/√n with κ = max((1+ρ̂)/(1−ρ̂), `<PLACEHOLDER: K3 — block-3 floor>`),
and a block-3 interval is reported beside the date-clustered one.

## 4. Integrity (HALT before any label is joined)

- S dual-implementation check (1e-12); B 7-12 state and training manifest shas equal the freeze commit.
- Input availability: every scored row's inputs were available by the row's cutoff (as_of_capture).
- N coverage on the scored rows at least 0.90; below it S is mostly MG-1 and the test HALTs.
- Parity control with a 07-12 leg: `<PLACEHOLDER: master — MG-2 fallback log counts and sha (row 28b Q6 (a)) or a
  host bounded extract, counts only>`.
- The spring-DST day 2027-03-14: `<PLACEHOLDER: master — excluded as in row 28b §4, or kept with the 23-hour rule>`.
- A HALT before any score allows a reviewed amendment; after any score exists, no re-run.

## 5. Decision

- **PASS** iff all N dates are scored, no (g) look stopped the test, the point is ≤ `<PLACEHOLDER: K3 — the G floor
  at 07-12>`, and the 95% upper bound is < 0 on both the date-clustered and the block-3 interval.
- **FAIL** otherwise, including a (g) HARM or FUTILE stop. **HALTED** if §4 fires.
- A PASS claims model improvement at 07-12. Its market reading is §7a's, not this verdict's.

## 6. Power and futility (method §5 rules 6, 7, 16, 19)

- **SD source (rule 19).** `<PLACEHOLDER: E1 — the same-contrast 07-12 B − S per-date SD from history, with its
  score-result sha256; else the stated bound from row 82's 07-12 projection>`.
- **Planning bound.** `<PLACEHOLDER: K3 — the bound multiple>`.
- **Futility inflation.** The MDE uses the ×1.07 futility-look inflation (method §5 rule 7).
- **Effect.** delta = `<PLACEHOLDER: E1 — half the history point>`.
- Power table: `<PLACEHOLDER: E1/K3 — SD basis × N in {80, 90, 100}>`.

## (a) Positive control

`<PLACEHOLDER: freeze — S dual-implementation agreement 1e-12 on every scored row and on 50 fixed synthetic rows;
the frozen B 7-12 state reproducing its training-time predictions on 50 fixed rows to 1e-12>`.

## (b) Comparator fairness

S gets the same rule-4 floor and the same calibration (none beyond the shared band/Brier scorer) as B, on identical
rows: paired per (market, date, hour), the same build function, the same label copy.

## (c) Targeted loss slice

`<PLACEHOLDER: master — the slice (expected: the scored population itself, h07-12, US10, the scored window, as
row 28b's Q7 ruling) and its size source>`.

## (d) MDE and clusters

`<PLACEHOLDER: E1/K3 — MDE80>` at `<PLACEHOLDER: N>` date clusters and 10 market clusters.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md: reuse count `<PLACEHOLDER: freeze — the count on the freeze date>` plus one for this row.

## (f) Power gate
- sigma_d: <PLACEHOLDER: E1/K3 — one source block, history or dev, with its sha256>
- rho: <PLACEHOLDER: E1>
- block3 ratio: <PLACEHOLDER: E1>
- VIF: <PLACEHOLDER: E1>
- delta: <PLACEHOLDER: E1>
- N: <PLACEHOLDER: K3, 80-100>
- MDE80: <PLACEHOLDER: 2.802 x sigma_d x sqrt(VIF) / sqrt(N), inflated 7%>
- power: <PLACEHOLDER: E1/K3>
- class: <PLACEHOLDER: POWERED or SCREEN>
- intervals: date-clustered (verdict) and block-3 (reported beside it; the more conservative verdict holds)

## (g) Futility
- look 7: HARM if t > 3.143
- look 14: FUTILE if z > +0.5
- look 21: FUTILE if z > 0
- look 31: FUTILE if z > -0.5
- final N: <PLACEHOLDER: K3, equal to the power gate's N>
- interim PASS: never

z_k = mean_k / (s_k × √VIF / √k) on the first k deciding dates, positive meaning harm. The looks are applied in date
order at the single read (§1). No look produces a PASS, changes N or the estimand, or starts a refit.

## 7. Descriptive only (decides nothing)

- Per-market and per-hour d, per-month d, and the realised/projected SD ratio (rule 19).

## 7a. Where the rule-4 w step sits

- **Before D0, as a gate.** The rule-4 w step is program-plan stage 3: a walk-forward log pool of market and B at
  07-12 against the date-deranged placebo and the floor-only control (method §3 rung 4, §5 rule 4), on L52 history
  prices for season-year 2026 (2025-12-17..2026-05-26), under its **own** frozen prereg. K3a (projected power at
  least 0.5) and K3b (w beats both controls) must pass before this file freezes. K3b failing kills B's 07-12 market
  path, and this prereg is not frozen.
- **In this test.** The forward walk-forward w at 07-12 against the same two controls is
  `<PLACEHOLDER: master — a fixed-sequence secondary behind the B − S primary, or descriptive only>`. Prices are
  read only under the §1 read rule.

## 8. Open questions (for master; none asked of the owner by this lane)

1. The owner embargo-line question for D0 (§1): OPEN, carried by master.
2. D0 and N (§1), after K3.
3. Whether row 28b's scope intersects this test under rule 9 (§1).
4. The forward w: secondary or descriptive (§7a).
5. Parity-control option and the 2027-03-14 handling (§4).
6. The (c) slice wording (§(c)).

## 8a. Freeze record fields (item 343b §6 field names, hours 7-12; PLACEHOLDER = unknown until freeze)

- candidate_id: <PLACEHOLDER: freeze — e.g. row28_B_0712>
- module: weather.calibration.yearround_refit
- module_source_sha256: <PLACEHOLDER: freeze>
- fit_manifest_sha256: <PLACEHOLDER: freeze>
- state_sha256: <PLACEHOLDER: freeze — the 7-12 state file>
- state_sidecar_sha256: <PLACEHOLDER: freeze>
- state_schema: mg2_p3d_n_state/1
- arm: B (season-matched, Dec 17 - May 31 rows of 2021-2025)
- centres: <PLACEHOLDER: freeze — B's 11 centres>
- season_of: <PLACEHOLDER: freeze — the month to season map>
- hours: 7, 8, 9, 10, 11, 12
- training_window: Dec 17 - May 31 of season-years 2021-2025 (target dates at or before 2025-12-16)
- training_rows_sha256: <PLACEHOLDER: freeze>
- bucket_space_sha256: <PLACEHOLDER: freeze>
- upstream_sha256: {pooled_residual_model: <PLACEHOLDER>, mg2_p3d_n: <PLACEHOLDER>, mg_serve_core: <PLACEHOLDER>, feature_model: <PLACEHOLDER>, ols_floor_ladder: <PLACEHOLDER>, r0_ols_floor_devfit: <PLACEHOLDER>}
- sklearn_version: <PLACEHOLDER: freeze>
- conversion: <PLACEHOLDER: freeze — copied from the bound state>
- late_report: <PLACEHOLDER: freeze — copied from the bound state>
- train_F_source: wu_hourly
- serve_F_source: captured_metar
- shadow_first: <PLACEHOLDER: D0>
- shadow_last: <PLACEHOLDER: at or before 2027-05-31>
- coverage_window: <PLACEHOLDER: D0..2027-05-31>
- input_modes: as_of_capture
- forward_receipt_sha256: <PLACEHOLDER: the owner's embargo-line record (§1, open)>
- shadow_rows_sha256: <PLACEHOLDER: per emission run>
- emit_receipt_sha256: <PLACEHOLDER: per emission run>
- equivalence_report_sha256: <PLACEHOLDER: freeze>
- frozen_before_utc: <PLACEHOLDER: before D0>
- markets: training: 11 R0 markets incl. Denver (as v12); scored/emitted: US10
- scored_window: <PLACEHOLDER: D0..last deciding date (the N deciding dates)>
- emission_window: <PLACEHOLDER: D0..2027-05-31 (emission only; named separately from the scored window)>
- fit_kind: forward
- state_archive_path: <PLACEHOLDER: master — an archive path for the 7-12 state>

## 9. Related

Program plan stages 1-4 and kill points (`a6dd53c1e`); row-28b forward draft (`acab59345`); item 343b design §6
(`a2548e3fe`); method §5 rules 4, 6, 7, 9, 16, 19;
[pre-registration checklist](../../operations/PREREGISTRATION_CHECKLIST.md).
