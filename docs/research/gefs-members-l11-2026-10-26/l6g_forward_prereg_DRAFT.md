# L6_G forward pre-registration (DRAFT for master review)

- **Status:** DRAFT, written 2026-10-28 by lane L2. **Nothing accrues until master has reviewed it and it is bound**
  (sha256 recorded in DECISION_LOG). Every `<FILL@BINDING>` field stays unfilled until then.
- **Why.** R-O gates 2/3 found L6_G better than L6 at local 07-12 (dR −0.00932 [−0.01939, −0.0000657]), but on the
  dev window, against an in-sample incumbent, with a walk-forward shift fitted on dev outcomes. That is selection
  evidence only. This test is the only route by which it can become evidence. Companion text:
  [mg2_pre13_clarification_ro_DRAFT.md](mg2_pre13_clarification_ro_DRAFT.md) (not applied).
- **Template.** `docs/operations/B_FORWARD_TEST_DESIGN.md` (on `origin/master`) (rule B-1, BOUND 2026-10-28):
  the endpoint, interval and pass rule are B §5/§6, with the comparator changed from the market to L6.
- **Written blind.** No outcome, label, price, market, settlement or 88a/panel row dated after 2026-09-29 was read.

## 1. Candidate and comparator

- **Candidate (L6_G):** the bound L6 vector with mu replaced by mu + s, s = a_h + b_h (G − N), as defined in
  `rule_rn.md` and scored by `rung-o-score` (`--dev-hour-field local_hour`). (a_h, b_h) for h07..h12 are **frozen**
  (open point 1); no forward refit, because a forward walk-forward would need forward outcomes before the look.
- **Comparator (L6):** MG-2's pre-13 arm as bound in B §1 (L6 part 07a6742595f5…e17e9, season-matched state
  800072c79af6…e2db), on the same snapshot rows.
- **Paired.** Both arms are computed from the same as-of-capture snapshot, the same N and the same nowcast; the only
  difference is s. If G is absent for a snapshot, that snapshot is not covered for this test (it is not scored as
  s = 0).

## 2. Population and dates

- **Markets (10, fixed):** B's 10 (atlanta, austin, chicago, dallas, houston, los-angeles, miami, nyc,
  san-francisco, seattle). Denver is excluded, as in B.
- **Hours:** `local_hour` 07..12 only.
- **D0 (placeholder rule):** D0 = landing date of the bound file + 1. Every date before D0 is excluded, including
  any date whose inputs were captured before landing.
- **N = 45 countable dates** from D0 with no skipping. Countable = input-countable under B's definition (MG-2
  binding plan §9.4) **and** G-countable (§3). Each non-countable date moves the 45th one day later.
- **Coverage drop (fixed daily, outcome-blind):** a countable date on which fewer than 90% of its 07-12 snapshots are
  covered by both arms (G present with ≥ 25 of 30 members available by h:00 local) is dropped and not replaced. The
  drop list is final before the look.
- **Void floor:** fewer than 40 of the 45 dates survive the drop → VOID.

## 3. Daily receipt channel (outcome-blind)

- A **separate ledger** `C:\t\l6g\forward\input_receipts.jsonl` (path `<FILL@BINDING>`). It never writes to, and
  is never read from, B's `C:\t\mg2\forward\input_receipts.jsonl`.
- One row per local date: date, per-market snapshot count at 07-12, count with G present, member count
  distribution, latest GEFS message availability time versus h:00 local (PIT), N present, recorder parser version,
  the frozen-state sha256 check, and a replay-to-1e-12 check of both arms on a fixed sample.
- **No market column, no label column, no price column, no Brier, no s-by-outcome field.** The vectors themselves
  may be written (they are inputs), but nothing derived from an outcome.

## 4. Pins (`<FILL@BINDING>`; any mismatch at the look → VOID)

| Field | Value |
| --- | --- |
| Scoring module `src/weather/calibration/pooled_residual_model.py` | dev pin bfe756de82cf085da5cca5a0d494ecb106de3a6cdababc7fa720989249a01b60 (abd048f98); forward scorer sha `<FILL@BINDING>` |
| Frozen (a_h, b_h) state file sha256 | `<FILL@BINDING>` (open point 1) |
| L6 part / season-matched L6 state | as B §1 (07a6742595f5…e17e9 / 800072c79af6…e2db) |
| `observed_running_max` function | as B §1 (8cc4d8ec13a6…c224a) |
| Dev scorecard code | f69071ac5612f022ade56ada764f813c28da79cd0265848c58041115439005c5 |
| Forward GEFS recorder module and parser version | `<FILL@BINDING>` (open point 2) |
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

## 6. Keep/kill rule (fixed sample, one look)

On Δ(07-12) with its 95% date-clustered interval [L, U]:

| Outcome | Condition | What it triggers |
| --- | --- | --- |
| **PASS** | U < 0, and no hour h07..h12 has its lower bound > 0 | The Clarification draft may go to owner/master for a decision. Never a promotion, a live order, or a release-gate bypass; it does not alter B. |
| **FAIL** | L > 0 | KILL: the GEFS member-mean centre shift is closed for the L6 arm, under `rule_rn.md`'s "closed" wording. |
| **INCONCLUSIVE** | anything else | No gain shown; the dates are spent; L6_G is not re-run on them. |
| **VOID** | §7 | No verdict; the dates are spent. |

- No peeking, no interim look, no sample-size re-estimation; N, markets, hours, the frozen state and the candidate
  are frozen at D0. No rescue by re-cutting hours, markets or dates.
- **Secondary (no α):** per hour, per market signs, Δ by G − N tercile (reported only), the excess of each arm over
  the capture-time market (only if a price read is separately authorised; open point 4).

## 7. Void conditions

1. any §4 pin differs at the look;
2. any outcome, label or price for a forward date was read before the look;
3. the positive control fails (s = 0 must reproduce L6 to 1e-12 on the forward rows; mass preserved to 1e-9);
4. the look ran before the receipts in §9 existed;
5. fewer than 40 dates survive the §2 drop;
6. a receipt row is missing or altered for a countable date.

## 8. Power (stated up front)

From the dev interval: SE = 0.00493 over 43 dates, σ_d ≈ 0.0323. At N = 45, MDE80 ≈ 0.0135 date-clustered. Power at
the dev point (−0.0093) ≈ 0.49; at half of it ≈ 0.16. 80% power at the dev point needs about 95 dates. The dev point
is in-sample and likely optimistic. These assume Oct-Jan variance equals Aug-Sep and the 11-market dev σ transfers to
10 markets.

## 9. Embargo, look and coexistence with B

- **No look before 2026-12-13**, and none until (i) the 45th date has settled, (ii) MG-1's look receipt exists and
  (iii) B's look receipt exists. The look is strictly after B's.
- **Separate ledger, separate look.** This test has its own receipt ledger (§3), its own look receipt and its own
  label read. It never reuses B's look, B's transfer inbox, B's receipts or B's control receipts, and B's verdict is
  never pooled with this one.
- **No price read is needed** for the primary: the comparator is L6, not the market.
- **Multiplicity, disclosed.** L6 is MG-2's pre-13 arm, so these dates may overlap B's 45 dates and MG-3's paired test.
  This is a second hypothesis (L6_G − L6) on shared dates. It is a different question from B (MG-2 − market) and
  MG-3 (MG-3 − MG-2) and does not select among them. It is reported with its own α 0.025 one-sided, unadjusted,
  and the overlap is stated beside every result. No best-of selection across candidates on shared dates.
- **Lane rule.** No lane reads any forward date's outcomes before this look; dev work stays on dates ≤ 09-29.

## 10. Open points for master

1. **Frozen state.** Either (a) the last walk-forward pairs (fit on [08-01, 09-29)), or (b) one refit on all dev
   08-01..09-29 (uses the 09-29 outcomes, still inside the dev window). Lane recommendation: (a), the pairs the
   R-O result actually scored for its last date; no new fit.
2. **Forward G source.** No live GEFS recorder exists. A history download after the fact cannot prove h:00
   availability. Options: a new live recorder of GEFS 06Z members (NOAA, free; whether the history-corpus
   ingest can be reused without new deps is unchecked) with availability-time receipts; or the Open-Meteo
   capture `rule_rn.md` discloses, which would
   need its own parity check against the dev node definition. Accrual cannot start until one is chosen and pinned.
3. **Reserved window.** L6_G reads NBM guidance, so its dates on 2026-10-15..11-28 are held out against it unless an
   owner exemption like MG-3's is granted (B §10: "Any other NBM-reading candidate on 10-15..11-28 needs its own
   owner decision"; B §10 also bars lanes from B's dates). Without an exemption, D0 becomes the first date after
   `MG1_LAST` (today 11-29, 45th ≈ 2027-01-12), and the 12-13 floor is moot.
4. **Market excess.** Whether a capture-time price read for a secondary market comparison is wanted. Default: no.
5. **Power.** N = 45 gives ≈ 0.49 power at the in-sample dev point. Master may prefer N ≈ 95 or accept 45 as an
   honest kill-or-keep screen.
6. **Hour field and hours.** `local_hour` 07..12 is proposed (as ruled for R-O). h11-h12 contributed little on dev;
   they are kept, not trimmed, to avoid a post-hoc cut.
7. **Ledger path and owner of the recorder** (`C:\t\l6g\forward\`, lane assignment), and whether Denver stays out
   (proposed: out, as B).
