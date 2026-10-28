# L6_G forward pre-registration (DRAFT for master review)

- **Status:** DRAFT, written 2026-10-28 by lane L2; master's rulings of 2026-10-28 are applied below. **Nothing
  accrues until master has reviewed it and it is bound** (sha256 recorded in DECISION_LOG). The §10 open items were closed on 2026-10-28
  (recorder pins, look scorer, first full receipt day); the only item left for binding is the DECISION_LOG row.
- **Owner decision C-EX (reserved-window exemption), 2026-10-28, relayed by master-agent.** L6_G reads NBM
  guidance, so its forward dates are held out against it (`reserved-confirmation-window.md`; B §10: "Any other
  NBM-reading candidate on 10-15..11-28 needs its own owner decision"). The owner answered, verbatim, "I give my ok."
  to this scope as master put it: outcome-blind accrual from about 10-30, inside 10-15..11-28; N = 45, a SCREEN with
  power about 0.49; a single look after B (≥ 12-13); no selection between MG-2 and L6_G; the result never alters B.
  The exemption covers this test only, within that scope. Its DECISION_LOG row is drafted in
  [decision_log_row_l6g_exemption_DRAFT.md](decision_log_row_l6g_exemption_DRAFT.md) for master to land.
- **Why.** R-O gates 2/3 found L6_G better than L6 at local 07-12 (dR −0.00932 [−0.01939, −0.0000657]), but on the
  dev window, against an in-sample incumbent, with a walk-forward shift fitted on dev outcomes. That is selection
  evidence only. This test is the only route by which it can become evidence. Companion text:
  [mg2_pre13_clarification_ro_DRAFT.md](mg2_pre13_clarification_ro_DRAFT.md) (not applied).
- **Template.** `docs/operations/B_FORWARD_TEST_DESIGN.md` (on `origin/master`; rule B-1, BOUND 2026-10-28): the
  endpoint, interval and pass rule are B §5/§6, with the comparator changed from the market to L6.
- **Written blind.** No outcome, label, price, market, settlement or 88a/panel row dated after 2026-09-29 was read.

## 1. Candidate and comparator

- **Candidate (L6_G):** the bound L6 vector with mu replaced by mu + s, s = a_h + b_h (G − N), as defined in
  `rule_rn.md`, with h = `local_hour` (07..12). (a_h, b_h) are the **frozen state** below; there is no forward refit,
  because a forward walk-forward would need forward outcomes before the look.
- **Frozen state (method (a), accepted by master):** the R-O walk-forward grid minimiser (rule L125-126, same grid
  and tie rule) taken at 2026-09-30, i.e. over every dev fit date 2026-08-01..2026-09-29 (all dev data; L6_G has no
  pre-2026 years). It was fitted on dev data only, with the R-O gates 2/3 pins (fit population loyo, which does
  not touch the L6 side, and hour field `local_hour`).
  - File: `C:\t\l6g\forward\state\l6g_state.json`, sha256 **ae95686b5468bceed0fd33ead0f397dc061d9a5822f56bfb2364814553e8983e**.
  - Values (a_h, b_h): h07 (0.1, 0.2), h08 (0.2, 0.15), h09 (0.1, 0.2), h10 (0.1, 0.15), h11 (0.0, 0.1),
    h12 (−0.1, 0.1). They differ from the pairs scored for 09-29 only at h07 ((0.2, 0.15) there), because 09-29 itself
    now enters the fit. Fit population 28,754 common covered rows at 07-12 over 57 fit dates, all with G and N.
  - Producer: `python -m weather.calibration.pooled_residual_model l6g-freeze-state` at commit
    341acbd2b5d8bef89254a8c92203927d638bc7a6; module `src/weather/calibration/pooled_residual_model.py` git blob
    80a585e8ea19098b8de4da03b4e7996021e87756 (file sha256
    dad00efd385c2108e6dc30142178235dc6da1f6aeea2e496401ee8747fe68f9d). The fitting code is `ro_l6_fit_sums`, shared
    with the gates 2/3 scorer.
  - Controls inside the producer: every one of the 258 scored walk-forward pairs (43 dates × 6 hours) in
    `rn_score.json` reproduced exactly; the fit population equals the result's; s = 0 reproduces both registered
    vectors.
  - Determinism: the producer ran twice through `workstation_heavy.ps1 -Queue` from a clean detached tree at
    341acbd2b (2026-10-28); both outputs are byte-identical, sha256 ae95686b5468bceed0fd33ead0f397dc061d9a5822f56bfb2364814553e8983e (2,327 bytes).
- **Comparator (L6):** MG-2's pre-13 arm as bound in B §1 (L6 part 07a6742595f5…e17e9, season-matched state
  800072c79af6…e2db), on the same snapshot rows.
- **Paired.** Both arms are computed from the same as-of-capture snapshot, the same N and the same nowcast; the only
  difference is s. If G is absent for a snapshot, that snapshot is not covered for this test (it is not scored as
  s = 0).

## 2. Population and dates

- **Markets (10, fixed):** B's 10 (atlanta, austin, chicago, dallas, houston, los-angeles, miami, nyc,
  san-francisco, seattle). Denver is excluded, as in B.
- **Hours:** `local_hour` 07..12, **untrimmed** (h11-h12 added little on dev; they stay, to avoid a post-hoc cut).
- **D0 (master's rule):** D0 = the latest of
  1. the landing date of the bound file + 1;
  2. the GEFS recorder's first full receipt day (all 10 markets, 06Z cycle, h07..h12 recorded under §3);
  3. the day after the owner's C-EX yes (given 2026-10-28, so 2026-10-29).

  **Recorder's first full receipt day: 2026-10-28** (read from the per-day manifest by counts only, no values:
  schema `l6g_gefs_forward_points/1`, 217 of 217 member-node rows ok, LastModified-rule table 60 of 60 market-hour
  cells non-null over 10 markets × h07..h12; the fetched-rule table 23 of 60, because the recorder started mid-day,
  reported only). **Derived D0 = the bound file's landing date + 1**, since the other two terms are 10-28 and 10-29:
  D0 = 2026-10-29 if it lands on 2026-10-28, and so on, up to the 11-02 cap.

  **D0 is capped at 2026-11-02** (as B: 45 dates from 11-02 end inside P3d_N's and the L6 state's training coverage,
  08-01..12-16). If the latest of the three would fall after 11-02, this rule does not start; any later version needs
  a new pre-registration. Never backdated: every date before D0 is excluded, including any date whose inputs were
  captured earlier.
- **N = 45 countable dates** from D0 with no skipping. Countable = input-countable under B's definition (MG-2
  binding plan §9.4) **and** G-countable (§3). Each non-countable date moves the 45th one day later.
- **Coverage drop (fixed daily, outcome-blind):** a countable date on which fewer than 90% of its 07-12 snapshots are
  covered by both arms (G present with ≥ 25 of 30 members available by h:00 local) is dropped and not replaced. The
  drop list is final before the look.
- **Void floor:** fewer than 40 of the 45 dates survive the drop → VOID.

## 3. G source and daily receipt channel (outcome-blind)

- **G source (master's ruling):** the GEFS 06Z forward recorder (live since 2026-10-28, writing
  `C:\t\l6g\forward\gefs\`, launched from code at a31fef9bacff32bd4e27f674e6cbdaadb0b18d99 on
  `claude/gefs-forward-recorder-20261028`). **G is read from the recorder's LastModified-rule table**, the table
  built under the dev availability rule (a member message counts at h by its source LastModified time).
  The recorder's fetched-rule table (counted by the recorder's own fetch time) is **reported only** and never decides
  coverage or G.
- **Ledger:** `C:\t\l6g\forward\`, **owned by lane L2**. Receipts go to `C:\t\l6g\forward\input_receipts.jsonl`. It
  never writes to, and is never read from, B's `C:\t\mg2\forward\input_receipts.jsonl`.
- One receipt row per local date: date; per-market snapshot count at 07-12; count with G present (LastModified rule);
  the same count under the fetched rule (reported only); member-count distribution; latest member LastModified time
  versus h:00 local (PIT); N present; recorder parser version; frozen-state sha256 check; and a replay-to-1e-12 check
  of both arms on a fixed sample.
- **No market column, no label column, no price column, no Brier, no s-by-outcome field.** The vectors themselves
  may be written (they are inputs), but nothing derived from an outcome. **No price reads at any point**, including
  the look.

## 4. Pins (any mismatch at the look → VOID)

| Field | Value |
| --- | --- |
| Frozen (a_h, b_h) state `l6g_state.json` sha256 | ae95686b5468bceed0fd33ead0f397dc061d9a5822f56bfb2364814553e8983e |
| State producer | commit 341acbd2b5d8bef89254a8c92203927d638bc7a6; `pooled_residual_model.py` blob 80a585e8ea19098b8de4da03b4e7996021e87756 |
| Forward look scorer (module and sha256) | `src/weather/calibration/l6g_forward_look.py` blob 17539ca496d32d935a80461859d555243a9a317e, file sha256 788e9508bd35f3d435fe057c6498bc9a32c11a0892853c8932bbc416ae692078 (the look receipt records it); tests `tests/calibration/test_l6g_forward_look.py`, 13, synthetic data only |
| L6 part / season-matched L6 state | as B §1 (07a6742595f5…e17e9 / 800072c79af6…e2db) |
| `observed_running_max` function | as B §1 (8cc4d8ec13a6…c224a) |
| Dev scorecard code | f69071ac5612f022ade56ada764f813c28da79cd0265848c58041115439005c5 |
| GEFS forward recorder code | commit a31fef9bacff32bd4e27f674e6cbdaadb0b18d99: `tools/research/gefs_forward_recorder.py` blob 9cb7f3056c0170128b85bf51473ff5513432f120 (file sha256 3328e1a0c3421ec3f98e3291cc5d8fddb0d88e835f95e8ae1a3eeff54407afc9); `tools/research/gefs_member_point_fetch.py` blob 5094c74ed9292942ffa8e28cb65096c68fc53ca2 (file sha256 c898d94ae10264839cdddab5072b72c7821411acb402e03c262a7106206680a8, equal to the dev corpus manifest's); launcher `gefs_forward_recorder_launch.ps1` file sha256 730aaa6c7cd2111e61ee5bf27b03a02d89c99c8e2811978d31c88dc7f228938e |
| Recorder parser version | manifest `schema` = `l6g_gefs_forward_points/1` |
| Deciding G table | manifest key `g_lastmodified_rule`, schema `{market: {"h07".."h12": float or null}}` (null = fewer than 25 of 30 perturbed members available by h:00 local); `g_fetched_rule` has the same shape and is reported only |
| Recorder parity (lane L13, at a31fef9ba) | all 217 rows per date and the G tables identical to the dev corpus on 2023-08-20, 2026-08-15 and 2026-09-29; `ro_gefs_value` cross-check 0 mismatches over 396 cells |
| Forward N (NBM `v2_mean`) input and nowcast inputs | MG-2's bound forward input bundle (no new N source) |
| Rule `rule_rn.md` C1 | b25f36cf6e08b4ac69db548163f7f374d5906538224a453f4e5e1f92b075ad24 |
| Dev result `rn_score.json` | 35e0c93b4e4331647a613e54365cb91b3ac9f57d07bb44021604756d95ba1162 |

## 5. Estimand and inference (B §5, comparator adapted)

- **Primary:** Δ = mean over equal (date, market) cells of [Brier(L6_G) − Brier(L6)] on local 07-12, on snapshots
  both arms cover. Per-snapshot band Brier, equal snapshot weights within a cell, then equal cells, computed by the
  dev scorecard's `score_rows` at the pinned scorecard code.
- **Labels:** venue-rule labels (as B §5), read once at the look.
- **Interval:** fixed-market, date-clustered percentile 95%, 2,000 draws, seed 20260921; each bound one-sided at
  α 0.025. The crossed interval is reported and does not decide.
- **α:** no CAMPAIGN_LEDGER spend (as B).

## 6. Keep/kill rule (fixed sample, one look; a SCREEN)

**N = 45 is a screen, not a powered test** (power ≈ 0.49 at the in-sample dev point; §8). This is disclosed with
every result.

On Δ(07-12) with its 95% date-clustered interval [L, U]:

| Outcome | Condition | What it triggers |
| --- | --- | --- |
| **PASS** | U < 0, and no hour h07..h12 has its lower bound > 0 | Screen passed. It earns a **powered confirmation on a refit state**, under its own pre-registration on fresh dates. It is not by itself grounds to apply the Clarification draft. Never a promotion, a live order or a release-gate bypass, and it never alters B. |
| **FAIL** | L > 0 | KILL **this frozen Oct-Dec state shift** (the state pinned in §4). The GEFS member-mean G feature itself is **not** closed. |
| **INCONCLUSIVE** | anything else | No gain shown; the dates are spent; this state is not re-run on them. |
| **VOID** | §7 | No verdict; the dates are spent. |

- No peeking, no interim look, no sample-size re-estimation; N, markets, hours, the frozen state and the candidate
  are frozen at D0. No rescue by re-cutting hours, markets or dates.
- **Secondary (no α, reported only):** per hour, per-market signs, Δ by G − N tercile, and the fetched-rule G
  coverage beside the LastModified-rule coverage. There is no market comparison (no price reads).

## 7. Void conditions

1. any §4 pin differs at the look;
2. any outcome, label or price for a forward date was read before the look;
3. the positive control fails (s = 0 must reproduce L6 to 1e-12 on the forward rows; mass preserved to 1e-9);
4. the look ran before the receipts in §3 existed, or before B's look receipt existed;
5. fewer than 40 dates survive the §2 drop;
6. a receipt row is missing or altered for a countable date;
7. accrual or the look falls outside the C-EX scope (§ Status).

## 8. Power (stated up front)

From the dev interval: SE = 0.00493 over 43 dates, σ_d ≈ 0.0323. At N = 45, MDE80 ≈ 0.0135 date-clustered. Power at
the dev point (−0.0093) ≈ 0.49; at half of it ≈ 0.16. 80% power at the dev point needs about 95 dates, which is the
order of size for the powered confirmation a PASS would earn. The dev point is in-sample and likely optimistic.
These assume Oct-Dec variance equals Aug-Sep and the 11-market dev σ transfers to 10 markets.

## 9. Embargo, look and coexistence with B

- **Nothing about a forward date is read before B's look** (earliest 2026-12-13). The look is not before 12-13, and
  not until (i) the 45th date has settled, (ii) MG-1's look receipt exists and (iii) B's look receipt exists. The
  look is strictly after B's.
- **The result never alters B.** B's verdict, dates, drop list and receipts are unaffected by anything here.
- **No best-of selection between MG-2 and L6_G.** Neither result is used to choose between them or to re-cut the
  other.
- **Separate ledger, separate look.** This test has its own receipt ledger (§3), its own look receipt and its own
  label read. It never reuses B's look, B's transfer inbox, B's receipts or B's control receipts, and B's verdict is
  never pooled with this one.
- **No price reads.** The comparator is L6, not the market.
- **Multiplicity, disclosed.** L6 is MG-2's pre-13 arm, so these dates may overlap B's 45 dates and MG-3's paired
  test. This is a second hypothesis (L6_G − L6) on shared dates, a different question from B (MG-2 − market) and
  MG-3 (MG-3 − MG-2). It is reported with its own α 0.025 one-sided, unadjusted, and the overlap is stated beside
  every result.
- **Lane rule.** No lane reads any forward date's outcomes before this look; dev work stays on dates ≤ 09-29.

## 10. Rulings applied and what stays open

**Ruled by master (2026-10-28):** frozen state method (a); N = 45 as a disclosed screen; PASS → powered confirmation
on a refit state, FAIL closes the Oct-Dec state shift, not the G feature; D0 = latest of landing + 1, the recorder's
first full receipt day and the owner's exemption yes, capped at 11-02; no best-of selection between MG-2 and L6_G;
nothing read before B's look; the result never alters B; ledger `C:\t\l6g\forward\` owned by L2; no price reads;
h07-h12 untrimmed; G from the recorder's LastModified-rule table, the fetched-rule table reported only; Denver out.

**Owner (2026-10-28, relayed by master-agent):** C-EX granted, "I give my ok." (scope in § Status).

**Open:**
1. **DECISION_LOG row:** drafted, for master to land.
2. **Daily vector emitter (accrual side):** the outcome-blind job that writes the per-snapshot L6/L6_G vectors and the
   §3 receipt rows is not yet written; it must be pinned before D0 like the scorer.

**Closed 2026-10-28:**
- Recorder pins and parity: §4 (L13's parity at a31fef9ba is cited, not re-run).
- Forward look scorer: written and pinned (§4). It refuses before 12-13, before the 45th date has passed, without
  MG-1's and B's look receipts, with an existing look receipt (exclusive create: one look), with a D0 after 11-02,
  and with any price or market-quote column; it reads the label file only after every guard passes. Only
  `g_lastmodified_rule` decides G presence; `g_fetched_rule` is counted and reported only. It uses the dev
  scorecard's `ratio_interval` and B's date-clustered weights, and it does not use `sc.Table` (which loads prices).
- Recorder first full receipt day: 2026-10-28 (§2).
