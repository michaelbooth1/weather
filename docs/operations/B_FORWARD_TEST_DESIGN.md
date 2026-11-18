# Rule B-1: minimal forward edge test, MG-2 against the market (pre-registration)

> **Repository copy, filed 2026-10-26 in the docs head.** Copied from the coordinator's bind-ready draft (raw sha256
> `c0a4f467ff09980396d5b45dc1548f8932ed5e1a0bc4481263348f05d1433446`). Changes: this note; the retrain record pointer
> in §0 (c) now names Appendix A; Appendix A is the coordinator's `retrain_overlap.md` (raw sha256
> `11c1cf581a86cdfb1ad73e97ce40c68678bec385453929281fcb9d1f1e1f6aeb`), text unchanged. The `<FILL@BINDING>` fields stay
> unfilled: **this was a DRAFT until the binding commit (planned 10-27, made 10-28)**, and the sha256 recorded at binding is that of the filled
> rule file, not of this copy. Owner answers in §0 are also rows in the [decision log](DECISION_LOG.md); items marked
> master are master's rulings. The reserved-window side of option 2 is in the
> [reserved confirmation window](reserved-confirmation-window.md); today's state is in the [state of play](STATE_OF_PLAY.md).
>
> **Master rulings 2026-10-26 (to apply at binding; text below unchanged):** (1) MG-2 binds via the C7/C8 line
> (`e40804dfe` or its successor); binding v2 `710f0c672` is superseded and is never landed on its own. (2) B scorer
> design choices (a)-(c) accepted; for (d), verifying `mg2_binding_commit` with `git cat-file` against origin is a
> binding-checklist step, and the scorer code is unchanged. Value to fill at binding (the binding commit fills every
> `<FILL@BINDING>` field): `b_scorer_sha256` = `b25b63f74639e960413ebec185da1e56f3f46363cecf33fe1d077a7b67aadbfd`;
> control receipt `6284af68d72e46bf917acb3da05ec726590a6509d7a57612ffd01ad23e94f4a8`. B and C8 land night 10-26/27.
> **Superseded at binding (2026-10-28):** `b25b63f7…` is the scorer of `cb5a3a7dc` (2026-10-25) and is superseded. The
> bound `b_scorer_sha256` is `module_sha256()` (the file bytes) of `src/weather/calibration/b_scorer.py` at the
> binding commit, `f941628a…`, last moved by `7da85e8cc3e9cecd00ab931cf5eca14ed12eb7a7` (MG-1 look entry sentinel and dev
> nowcast pin; B-1 clarification 2026-10-26 §8), after the 10-26 master-review and Fable fix series.

- **Binding package (2026-10-28, branch `claude/b-binding-package-20261028`, from `origin/master`
  `a8833a465`).** Every `<FILL@BINDING>` field is filled below from verified loads: MG-2's
  `release-binding.json` was written by `mg2_composite bind-release` (no hand edit; bind-release on Windows writes
  CRLF, so the file is LF-normalised by git under `eol=lf` and its sha below is of the LF bytes; master accepted
  this as disclosed), and its shas are copied here. Master approved the package and said GO on 2026-10-28.
- **Status:** BOUND 2026-10-28 (written 2026-10-25 as a bind-ready draft). The binding moved from 10-27 to
  10-28, so by the slip clause of §3 D0 = binding date + 1 = **2026-10-29** (d0_latest stays 2026-11-02). The
  raw sha256 of this filled file is recorded in DECISION_LOG before D0.
- **Written blind.** The author read no outcome, label, price, market, settlement or 88a/panel row dated after
  2026-09-29, and no MG-1 forward outcome. Every number here is a dev-window figure quoted from its record.
  Dev figures size the test and are selection evidence only. None of them can pass or fail B.
- **What B is.** The minimal forward formal test the owner chose on 2026-10-25 ("ok lets go option B. Stop
  being such a quiter. We exhaust all options on model improvements and we aren't there yet"). It runs
  alongside continued model work. Under the owner's answer to Q1 below, B is "that test", the real edge test
  for which the 10-23 embargo row reserves the post-09-29 window.

## 0. Decisions this rule implements

**Owner (2026-10-25, relayed by the coordinator; option labels verbatim):**

| # | Question | Owner's answer | Effect in this rule |
| --- | --- | --- | --- |
| E | MG-2 reservation exemption, option 2 as drafted (MG-2 rule §4.3), MG-2 only | "Yes to all" | B's dates are MG-2's Branch 2 dates (§3) |
| Q1 | B is the 10-23 edge test, with one capture-time price read for its 45 dates at MG-2's single look; "MG-2 only" covers scoring MG-2 against the market as well as against MG-1 | "Yes to both (Recommended)" | §4, §9 |
| Q2 | What a FAIL triggers | "This model only (Recommended)" | §6: a FAIL kills this candidate's edge claim, not the project, and model work continues |
| Q3 | N | "45 days (Recommended)" | N = 45 countable dates (§3, §(d)) |
| Q4 | Non-inferiority margin | "Confirm +0.0027 (Recommended)" | m = +0.0027 (§6) |

**Master (2026-10-25, master's rulings, not owner decisions):**
- **(a) Denver** is excluded from the MG-2 gate and from B, leaving 10 markets.
- **(b) Labels** are venue-rule labels from 10-23.
- **(c) Retrain window:** P3d_N and MG-2 are NOT retrain-family; they are serving-stage candidates. B drops
  no 13-16 cell (record: Appendix A).
- **(d) Coverage field:** master adds a counts-only market-coverage field to the exporter.
- **D0:** 2026-10-28 was accepted; the binding moved to 10-28, so D0 is 2026-10-29 by the §3 slip clause.

## 1. The candidate (frozen at binding)

B tests **MG-2**, the composite, through its gate vectors `mg2_vectors_asof_capture.parquet`. These are the
same bytes MG-2's gate scores under its Clarification C7:
- before 13:00 local, the L6 own-obs stack;
- from 13:00, P3d_N;
- the MG-1 fallback and the rule-4 floor throughout.

Each row reads only the latest replay snapshot captured at or before its own `captured_at_utc`.

| Binding field | Value |
| --- | --- |
| MG-2 rule raw sha256 (as bound; draft C6+C7 was `ccb2b82a415056ddfe1edc6fe2ca7192b82e8d940db96eb61101d99b19914f3b`) | `e761cc4eef097b80ae95fa03245871e8689a50125f4ad11ad00286218b17cdec` |
| MG-2 binding commit | `a8833a4658c914efc83a42edb2079becfcd3c7fd` (`origin/master` base of the binding branch; every bound file's blob there has the bound sha. The release binding's `built_at_commit` is `a0443c2bf152c5efbf4805b5dd2197173a4f29da`, a docs-only child with identical bound files) |
| MG-2 `release-binding.json` sha256 | `4e4dd97d0b2aa0eae920d6ee5406160ca8f0c16a001ba1615446702554a812fa` (`docs/research/mg2-composite-binding-2026-10-25/release-binding.json`) |
| MG-2 `owner_decision_id` (§4.3 Clarification) | `OD-2026-10-25-option-b-dl271-dl274` (MG-2 Clarification C10: DECISION_LOG 2026-10-25 "Option B: minimal forward formal test plus model levers at full throttle" and "B forward test questions", master-confirmed) |
| L6 part sha256 (expected `07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9`) | `07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9` |
| Season-matched L6 own-model state sha256 (MG-2 C9 §3; B-1 clarification 2026-10-26 §6) | `800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db` |
| P3d_N state sha256 (expected `c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780`) | `c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780` |
| `observed_running_max` function sha256 (expected `8cc4d8ec13a64419961d96b3f648420fcd55f2c4cd3da7ca431b773c8bfc224a`) | `8cc4d8ec13a64419961d96b3f648420fcd55f2c4cd3da7ca431b773c8bfc224a` |
| B scorer module and its sha256 | `src/weather/calibration/b_scorer.py` `f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439` (S0; replaces the earlier `b25b63f7…`, see the B-1 clarification 2026-10-26 §4 for S0→S1) |
| Dev scorecard code sha256 used by the B scorer (R-H used `f69071ac5612f022…`) | `f69071ac5612f022ade56ada764f813c28da79cd0265848c58041115439005c5` (`dev_scorecard.code_sha256()` at the binding commit; equals R-H's) |

The binding rules:
- An expected value that differs at binding, for example after a Fable fix, is replaced by the bound value
  and noted beside it. It can never change after D0.
- **The vectors file is checked at the look.** Its sha256 must equal `asof_capture.vectors_sha256` in the
  forward `mg2_emit_audit.json` beside it. The B scorer refuses `mg2_vectors.parquet` (`last_in_hour`) as
  the primary input. That file may appear only in a section labelled descriptive.
- **Not candidates:**
  - blend_l6, the L6/P3d_N walk-forward blend, which was NULL against L6 at 07-12 (R-F);
  - P3d_N alone at 07-12 (+0.0101 against L6's +0.0081);
  - any candidate chosen after binding.
- **If MG-2 is not bound on 10-28 (planned 10-27),** this rule does not start. B then re-binds under the §11 fallback, and
  never backdates.

## 2. The comparator

The comparator is the market: the captured `p_market_yes` on the same snapshot row, at that row's capture
time. It is normalised exactly as the dev scorecard's market arm does it, at the scorecard code sha bound
above, which is R-H's reference. It is never a `last_in_hour` price.

## 3. Population and dates

- **Markets (10, fixed):** atlanta, austin, chicago, dallas, houston, los-angeles, miami, nyc, san-francisco
  and seattle. Denver is excluded (master ruling (a)).
- **Hours:** local 07-16 for the primary.
- **D0:** 2026-10-29, the first local target date after the binding commit. The binding was planned for 10-27
  and moved to 10-28, so D0 is the binding date + 1 under this slip rule: if the commit slips, D0 is
  the binding date + 1, and D0 must be ≤ 2026-11-02 so that all 45 dates lie inside P3d_N's training
  coverage, 08-01..12-16 (MG-2 C5). If D0 would fall after 11-02, B re-binds under §11.
- **Countable dates:** exactly MG-2's look date set, the first 45 countable dates from D0 with no skipping.
  - **Countable** means input-countable (MG-2 binding plan §9.4, over the 10 markets, under MG-2's pre-D0
    Clarification for ruling (a)) and promotion-countable.
  - **Moving the 45th date:** each non-countable date moves the 45th one day later.
  - **If every date is countable,** the 45th date is 2026-12-12.
- **B market coverage (fixed daily, outcome-blind):**
  - The counts come from master's counts-only manifest field (ruling (d)), logged in the receipt ledger.
  - A countable date with fewer than 90% of its 07-16 snapshots carrying a capture-time market price is
    dropped from B. It is not replaced.
  - The drop list is final before the look.
- **N = 45 dates**, about 450 market-days (owner Q3). B scores at most 45 dates and never more.

## 4. The MG-1 reserved window and permissions

- **The scope row** (`reserved-confirmation-window.md`) reserves the window against "any other candidate that
  reads NBM station guidance into band probabilities ... without a new explicit owner decision". MG-2 is in
  that family (MG-2 rule §4.2).
- **Option 2** (owner: "Yes to all") exempts MG-2's dates: "Single look, strictly after MG-1's" (MG-2 rule
  §4.3).
- **Q1** (owner: "Yes to both (Recommended)") extends the exemption to two further things:
  - scoring MG-2 against the market;
  - one capture-time price read for B's 45 dates, at that single look.
- **What stays refused.** Everything else under the post-09-29 embargo stays refused, including any other
  candidate, any other date, and any price outside the one transfer (STATE_OF_PLAY; DECISION_LOG 10-23).
- **Before the look,** B runs only the outcome-blind checks the scope row permits: coverage, PIT, replay
  reproduction and parser version. It never scores MG-1 and never reads an MG-1 outcome.
- **MG-1 §5 and §6** ("One look ... No interim outcome look"; window leakage) are respected. B's read happens
  inside MG-2's look run, after an MG-1 look receipt exists and the recorded MG-1 window has closed.
- **Retrain window:** no overlap rule applies (master ruling (c)).

## 5. Estimand and inference

- **Primary:** Δ = mean over equal (date, market) cells of [Brier(MG-2, as-of-capture) −
  Brier(market, capture-time)] on local hours 07-16, on snapshots both arms cover.
  - Per-snapshot band Brier, with equal snapshot weights within a cell and then equal cells.
  - The dev scorecard's `score_rows` computes it.
- **Labels:** venue-rule labels for dates from 10-23 (highest routine METAR, SPECI excluded, tenths °C
  half-up to °F), from the venue-rule label path (master ruling (b)).
- **Interval:** fixed-market, date-clustered percentile 95%, 2,000 draws, seed 20260921. Each bound is
  one-sided at α 0.025.
- **Crossed interval:** the crossed date × market interval is reported beside it and does not decide.
- **α:** this forward instrument does not spend from CAMPAIGN_LEDGER, which governs the sealed pre-boundary
  panel.

## 6. Keep/kill rule (fixed sample, one look)

This is decided on Δ(07-16) with its 95% date-clustered interval [L, U].

| Outcome | Condition | What it triggers |
| --- | --- | --- |
| **PASS (edge)** | U < 0, and neither Δ(07-12) nor Δ(13-16) has its lower bound > 0 | KEEP. Reported to the owner. It earns a forward economics confirmation (the cool-season paper test, §10) and a readiness discussion. It is never a promotion, a live order, or a bypass of the release or readiness gates. |
| **FAIL** | L > 0 | KILL this candidate's edge claim: MG-2 as bound (owner Q2: "This model only (Recommended)"). The project is not killed, and model work continues. Recorded in ESTABLISHED_FINDINGS / RETRACTED_AND_FALSE_LEADS and the digest. |
| **INCONCLUSIVE** | anything else; labelled **NOT-WORSE** when U < +0.0027 (owner Q4) | No edge is demonstrated. B's dates are spent. The next frozen candidate needs its own pre-registration on dates after B's 45th date, sized from B's forward variance (readable after the look). |
| **VOID** | any §8 condition | No verdict. The dates are spent and are not re-run. |

- **No peeking.** There is no interim look and no sample-size re-estimation.
- **Frozen after D0:** N, m, the window, the markets and the candidate.
- **No double use.** B's verdict is never pooled with MG-2's gate, the paper test or any later look. It can
  never be rescued by re-cutting hours, markets or dates.

## 7. Secondary measures (no α; reported beside the verdict)

- Δ(07-12), Δ(13-16), and per hour 07-16.
- Per-market signs.
- R = Brier(MG-2) / Brier(market) per hour.
- The crossed interval.
- The walk-forward log-pool weight w, with the w = 0 identity, a placebo (vectors deranged across dates) and
  the floor-only control (market plus hard floor), per MODEL_IMPROVEMENT_METHOD §3 rung 4.
- `last_in_hour` Δ, labelled descriptive.

## 8. Void conditions

The look is VOID if any of these holds:
1. any MG-2 void condition (MG-2 rule §7);
2. any bound hash in §1 differs at the look;
3. the positive control (§(a)) fails;
4. any outcome, label or price for a B date was read before the look;
5. the B read ran before the MG-1 look receipt existed;
6. the one-time transfer manifest (§9) is missing, altered or covers other dates;
7. fewer than 40 of the 45 dates survive the §3 market-coverage drop.

## 9. Artifacts, integrity and embargo

**At binding (10-28, before D0):**
- this file filled, with its raw sha256 recorded in DECISION_LOG;
- MG-2's binding commit and `release-binding.json`;
- `prereg_check` passing on this file;
- a `pending` row in DEV_WINDOW_LEDGER for the §(a) control read.

**Daily, outcome-blind:**
- MG-2's verified input bundle (binding plan §9.3, receiver checks 1-8);
- the row in `C:\t\mg2\forward\input_receipts.jsonl`;
- `check`: coverage ≥ 90% of 00-16, PIT, replay to 1e-12, parser version 2;
- the as-of invariant: no METAR row received after a row's own capture (C7 tests);
- the counts-only market-coverage field, logged in the same ledger.

No market column travels in the daily channel (binding plan §9.2).

**Before the look:**
- B scorer sha frozen;
- §(a) positive control passed and receipted;
- the §3 drop list final.

**The look, in this order:**
1. MG-1's look receipt exists and the recorded MG-1 window has closed.
2. The one-time transfer: venue-rule winner, `promotion_countable` and capture-time `p_market_yes` for the
   input-countable dates in order, until 45 countable dates are found. It goes to a separate inbox with its
   own manifest sha256.
3. MG-2's gate and B are computed in one run, with one look receipt holding both results and every hash
   above.

**Embargo:**
- Nothing about a B date is read until the 45th date has settled and step 1 holds.
- The earliest look is 2026-12-13, if every date is countable, and no earlier than MG-1's look.
- The B scorer refuses otherwise.

## 10. Coexistence

**The cool-season paper test** (approved, drafted separately). Its design is not read here; these terms bind
B's side of it.
- **Different question.** B is forecast quality: Brier against price. The paper test is economics: P&L under
  a frozen trading rule. Neither verdict counts toward the other.
- **Shared dates.** If it uses B's dates, it uses the same bound MG-2 as-of vectors. It reads nothing before
  B's look, and is not used to select, re-cut or override B.
- **Other candidates.** Any other NBM-reading candidate on 10-15..11-28 needs its own owner decision.
- **Disjoint dates.** Otherwise it takes disjoint dates.
- **Order of reads:** MG-1's look, then MG-2 + B, then the paper test.

**Model lanes:**
- Lanes keep working on dev dates ≤ 09-29 and never read B's dates.
- No lane result changes B after binding.
- A new candidate gets its own pre-registration on fresh dates after its own freeze, with no best-of
  selection across candidates on shared dates.

## 11. Fallback (only if §1 or §3 cannot bind)

- **Dates:** the first 45 countable dates after `weather.mg1_reserved_window.MG1_LAST`. Today that is from
  2026-11-29, with the 45th date 2027-01-12 and the look on or after 01-13; all move later with MG1_LAST.
- **Candidate:** MG-2, if it binds late. Otherwise the same composite under B's own release binding, at the
  hashes in §1.
- **Primary window:** narrows to 07-12. From 12-17, the 13-16 slot is MG-1 (C5).
- **Unchanged:** N, m, interval and keep/kill rule.
- **No price read without a new owner line.** Q1 covered MG-2 at MG-2's look.

## (a) Positive control

Before the look, on the dev window (layout manifest `4d53fdbdc551…`, R-H's files), the B scorer must
reproduce three values:
- R-H's `mg1_excess_07_12` = 0.011957 (to 1e-6);
- the L6 07-12 excess +0.0081 [+0.0062, +0.0101];
- served vs market pooled R 1.774 (all hours) and 1.526 (00-16) on the dev scorecard's default folds.

Failure makes the result NOT INTERPRETABLE (VOID, §8).

## (b) Comparator fairness

The market and MG-2 are scored on identical snapshot rows and cells. If the dev scorecard applies the
rule-4 floor mask and served fallback, both arms get them identically. Calibration is none for both: MG-2
has no calibration stage, and the market is used as captured. MG-2's inputs are as-of-capture, the same
instant as the price.

## (c) Targeted loss slice

Loss atlas R-H `ff7ee23179be2beceb9c7b883ffb3ae37fb9966e1aee7f8ee6df0744ab9fb814`, the market-relative
excess:
- 07-12: L6 +0.0081;
- 13-16: P3d_N_fix +0.0083;
- 07-16 composite: about +0.0082, hour-weighted 6:4.

The market's 07-12 Brier is about 0.053. At 07-12 the loss is the market's sharper mass on the winning bucket.

## (d) MDE and clusters

**Clusters:** 45 date clusters × 10 market clusters, fixed-market date-clustered.

**Variance.** σ_d is the between-date SD of the date-mean excess, taken from R-H's 57-date intervals as
SE = half-width / 1.96 and σ_d = SE × √57:
- L6 07-12: 0.00751;
- P3d_N_fix 07-12: 0.00828;
- P3d_N_fix 13-16: 0.00578.

The planning value is σ_d = 0.00751 × √(11/10) = 0.0079. The crossed σ is ×1.28 (MG-2 dev width ratio).

**MDE80** = 2.802 × σ_d / √45 = **0.0033** date-clustered (0.0042 crossed).

**Power at N = 45, date-clustered / crossed:**

| Scenario | Outcome | Power |
| --- | --- | --- |
| dev excess +0.0082 | FAIL | 1.00 / 1.00 |
| half the dev excess (+0.0041) | FAIL | 0.94 / 0.78 |
| Δ = 0 | NOT-WORSE | 0.63 / 0.43 |
| Δ = −0.0027 (R ≈ 0.95) | PASS | 0.63 / 0.43 |
| Δ = −0.0016 (R ≈ 0.97) | PASS | 0.27 / 0.18 |
| null (Δ = 0) | false PASS | 0.025 |

80% power for an R ≈ 0.95 edge needs 67 / 110 dates. The owner chose 45 (Q3), and this limitation is stated
up front.

**MG-2 gate MDE at binding (N = 45; MG-2 vs MG-1, not B's market comparator; selection evidence only).**

| Source | Population | G1 Δ(00-16) SE / MDE80 | G2 Δ(13-16) SE / MDE80 |
| --- | --- | --- | --- |
| dev_c8 `dev_composite.json` sha256 `c4aaa6a542a5960080028b467cd847d69f37513bb718e193e7ec67fd90f9e7b1` (`C:/t/mg2/dev_c8`) | 11 markets, 473 cells, 43 dates | 0.000741 / 0.0021 | 0.001939 / 0.0054 |
| (iii) `mde_c8.json` sha256 `9aa7afa0be8e9afa067cbe567cad9fbd8ed88aa4e67d56f498d26aff71170226` (`C:/t/l16odc/mde_c8.json`) | exact 10 markets (no Denver, C8), 430 cells, 43 dates | 0.000753 / 0.0021 | 0.001911 / 0.0054 |

- **Caveat on dev_c8:** its `sizing` block is over the 11-market groups, Denver included. The C8 gate is 10
  markets, so the gate's own figures are (iii); dev_c8 is quoted only for continuity.
- **(iii):** recomputed on the exact 10-market `gate_groups` cells. Its point equals the gate-groups estimate
  (G1 −0.0049, G2 −0.0150), and the 11-market control reproduced. Power at the dev point is ≈ 1.00 for both
  gates; G1 non-inferiority power at Δ = 0 is 0.26.

**Assumptions:**
- Oct-Dec variance equals Aug-Sep;
- the 57-date σ_d transfers to MG-2's 43-date / 473-market-day population.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md holds 33 rows on `origin/claude/mg2-c7-asof-gate-20261025`, and lane L2's rung rows
are pending merge. The integer at binding is 60 (rows on `origin/master` `a8833a465`, numbered 1-62, rows 34-35 not on master), entered as an integer. B scores no dev date;
the only dev read is the §(a) control, logged as its own row.

```b_rule_v1
rule_id: B-1
candidate: mg2_asof_capture
mg2_rule_sha256: e761cc4eef097b80ae95fa03245871e8689a50125f4ad11ad00286218b17cdec
mg2_binding_commit: a8833a4658c914efc83a42edb2079becfcd3c7fd
mg2_release_binding_sha256: 4e4dd97d0b2aa0eae920d6ee5406160ca8f0c16a001ba1615446702554a812fa
mg2_owner_decision_id: OD-2026-10-25-option-b-dl271-dl274
l6_coefficients_sha256: 07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9
l6_state_sha256: 800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db
p3d_n_state_sha256: c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780
function_sha256: 8cc4d8ec13a64419961d96b3f648420fcd55f2c4cd3da7ca431b773c8bfc224a
b_scorer_sha256: f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439
scorecard_code_sha256: f69071ac5612f022ade56ada764f813c28da79cd0265848c58041115439005c5
d0: 2026-10-29
d0_latest: 2026-11-02
n_dates: 45
markets: atlanta,austin,chicago,dallas,houston,los-angeles,miami,nyc,san-francisco,seattle
hours_primary: 07-16
interval: date_clustered_w_date_2000_seed_20260921
alpha_one_sided: 0.025
noninferiority_margin: 0.0027
market_coverage_min: 0.90
min_surviving_dates: 40
labels: venue_rule_from_2026-10-23
look_after: mg1_look_receipt_and_window_closed
```

## Appendix A. Is P3d_N retrain-family? (drafter's analysis before master's ruling (c))

Not on the text as written, but the term is undefined, so a one-line ruling is still needed. No document defines "retrain-family": `docs/operations/reserved-confirmation-window.md` (on `origin/claude/mg2-c7-asof-gate-20261025` and `origin/claude/docs-head-20261026`) uses the term only at lines 8-9 ("holds its dates ONLY against retrain-family candidates"), in the scope row at line 26 (quoting DECISION_LOG 2026-10-21 (k)) and in binding rule 3 at lines 77-79. Every concrete referent is the served per-market feature-model retrain. Lines 39-42 say "Release #1 *freezes* the June per-market HGBs — it does not retrain". The trigger at line 27 is the "first retrain candidate ... fitted and frozen (earliest R0 start 11-17)". Lines 58-60 name "the model-edge programme's retrain arm R0", and DECISION_LOG row 250 ties its prerequisite to the per-model column allowlist in `weather.calibration.feature_model`. The MG-1 pre-registration (lines 331-333) treats a non-retrain candidate as outside that trigger, calling MG-1 "a serving-stage candidate". P3d_N is neither a refit of the served HGB artifact nor served at all: it is lane L2's pooled residual model, fitted on Aug-Dec 2021-25 history from the NBM 07Z mean, and nothing in serving imports MG-2 (MG-2 rule §1). MG-2's rule leaves the question open at lines 525-527 ("If that window is declared and P3d_N is ruled to be in the retrain family, the overlap needs an owner ruling"). If it is ruled retrain-family, the window begins on the first target date after R0 is frozen (line 27); with the earliest freeze on 11-17, the first held date is 2026-11-18. Against B's dates of 2026-10-28..2026-12-11 (all countable), the overlap is then the 24 dates 2026-11-18..2026-12-11 inclusive (13 in November, 11 in December). The window's size is set only at freeze, and each non-countable B date moves B's last date later, so either can widen the overlap; a later R0 freeze narrows it. On those dates the overlap covers MG-2's post-13 P3d_N half, local hours 13-23. B scores it at hours **13-16**, in its primary Δ(07-16) and its secondary Δ(13-16), and MG-2's G1 (00-16) and G2 (13-16) are hit on the same dates and hours. The pre-13 L6 half is untouched. Under rule 3 those cells could not be "read ... enumerated ... evaluated" for P3d_N: B and MG-2 would have to drop hours 13-16 on those dates, or the ruling would have to exempt MG-2 the way the window already exempts EDGE-1 and MG-1. Recommended ruling, before D0: P3d_N, and MG-2 as a whole, is not retrain-family, and the family is the served feature-model refit (R0 and its successors).
