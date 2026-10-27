# Rule MG3-DC-1: MG-3 against MG-2, paired on B's dates (pre-registration, D-C)

- **Status:** BIND-READY DRAFT, lane L2, 2026-10-26. Nothing is bound until the binding commit fills every
  `<FILL@BINDING>` field and its raw sha256 is recorded in DECISION_LOG before MG3_D0.
- **Written blind.** The author read no outcome, label, price, market, settlement or 88a/panel row dated after
  2026-09-29, and no MG-1 or MG-2 forward outcome. Sizing uses history LOYO rows 2021-25 Aug-Sep only (§6).
- **Decision implemented.** Owner, 2026-10-26, relayed by master through the coordinator, verbatim: "same dates,
  need answers quick as possible". MG-3 runs as option D-C of the MG-3 design draft: a paired test against MG-2
  on B's dates, with the owner's MG-1 reserved-window exemption for MG-3 over about 11-11..11-28.
- **Master rulings (2026-10-26, through the coordinator):** blend_l6_H uses whichever L6 arm MG-2 binds at 07-12
  (§2.2); option 1 accepted (D0 about 11-11, one look ≥ 12-12); the 07-12 drop rule (§2.2a).
- **What this rule does not change:** MG-2, Rule B-1, MG-1, PT-1, L8's branch. MG-3's verdict never alters B's
  and B's never alters MG-3's.

## 1. Shared evidence with B (declared)

MG-3 is scored on B's dates against B's candidate, so the two results are not independent.

| Shared item | Consequence |
| --- | --- |
| Dates: MG-3's dates are a subset of B's 45 countable dates | No new weather days; MG-3's sample is B's later sample |
| Settlements: B's venue-rule labels (master ruling (b)), read once in B's look run | Same label errors hit both arms |
| Comparator: MG-2's bound as-of-capture vectors, the bytes B scores | MG-2's own errors are common to both; the paired difference removes them |
| Arms identical by construction: 00-06, 16, 17-23, SF 13-16 | These hours are excluded from H1 (they add zeros only) |

- **Correlated errors.** Weather regimes, label quirks and MG-1 fallback rows are shared. The paired design
  cancels the common part, which is why it is the test chosen; it also means a B FAIL and an MG-3 WIN can coexist.
- **No borrowing.** MG-3 makes no market claim. B's price transfer is MG-2-only (B §4, owner Q1); reading B's
  prices for MG-3, or combining B's Δ with MG-3's H1 into "MG-3 beats the market", is refused without a new
  owner line. The MG-3 design draft's dR (ratio to market) is therefore replaced by a Brier difference (§4).
- **No selection across candidates.** Neither result is used to pick between MG-2 and MG-3 on these dates.

## 2. The candidate (frozen before MG3_D0)

### 2.1 Arms per local hour (10 markets: B's set, Denver excluded)

| Hours | MG-3 arm | MG-2 as bound |
| --- | --- | --- |
| 00-06 | MG-2's bound arm (identical) | same |
| 07-12 | blend of MG-2's bound 07-12 arm with frozen P3d_H 07-12 (RN-1), MG-1 fallback and rule-4 floor | MG-2's bound 07-12 arm |
| 13-15 | frozen P3d_H 13-16 state (nearest cell), MG-1 fallback and floor, except SF | P3d_N (C5) |
| 13-16 SF, 16, 17-23 | MG-2's bound arm (identical) | same |

### 2.2 The L6 dependency (master ruling)

L3's season-matched L6 rule decides MG-2's 07-12 arm. MG-3's 07-12 blend partner is that arm, whichever it is:

| MG-2's bound 07-12 arm | MG-3's 07-12 arm | Weights |
| --- | --- | --- |
| Aug-Sep L6 stack (no change) | blend_l6_H | frozen `blend_l6_H_weights.json` `c7b8ebc08d31ca30e5289d453ec2260bcc6659b32b379410f58b0d2b9b03530a` |
| season-matched L6 | blend of season-matched L6 with P3d_H | refitted ONCE by the unchanged rule `4fb02a2c…` function on dev 2026-08-01..09-29 with the bound L6 arm's dev vectors; ledger row 40 before the fit |
| MG-1 (from 11-01) | blend of MG-1 with P3d_H | as above, with MG-1's dev vectors; ledger row 40 before the fit |

- The branch is read from MG-2's release binding, never chosen by MG-3.
- If the branch is not known by `<FILL@BINDING>` (MG3_D0 − 1), MG-3 does not bind and D0 moves later (§3).
- **Stated limitation.** In the two refit branches the weights are fitted on Aug-Sep dev dates for a partner
  built for Oct-Dec; nothing makes them season-matched. They are a fixed, pre-declared choice, not tuned.
### 2.2a The 07-12 drop rule (master ruling 10-26; written and hashed before the backfill is opened)

P3d_H was fitted on Aug-Sep 2021-25 only. L13's cool-season HRRR 07-12 backfill (`C:\t\l13\hrrr_cool0712`,
Oct-Dec 2024 and 2025) gives a history transfer check before binding. It is read once, after this rule's sha is
pushed, and decides one thing only:

- **Statistic.** ΔB_cool = mean over equal (date, market) cells of [Brier(MG-3 07-12 arm) − Brier(MG-2's bound
  07-12 arm)], local hours 07-12, on history dates 2024-10-01..12-31 and 2025-10-01..12-31, the 10 markets.
  - MG-3's 07-12 arm is exactly §2.1-§2.3: the bound partner, the frozen P3d_H 07-12 state `e9276477…` under
    RN-1, and the bound weights (§2.2 branch), with the MG-1 fallback and rule-4 floor. Nothing is refitted.
  - **The partner is the TRUE bound partner** (master ruling 10-26 (a)): MG-2's bound 07-12 arm, whichever it is.
    - season-matched L6 stack: L3's Oct-Dec LOYO vectors for it;
    - MG-1: computed on Oct-Dec history from the NBM PIT corpus;
    - Aug-Sep L6 stack: L3's frozen history builder (cool-season audit part 1a), as frozen at binding.
    Labels come from the same builder as the partner's vectors.
  - **Proxy P3d_H 07-12 − P3d_N_fix 07-12** (both frozen, same rows) is allowed ONLY if the true partner's Oct-Dec
    history vectors are provably unavailable at binding. If it is used, it is recorded in the binding as a stated
    deviation, with the reason.
- **Interval.** Date-clustered percentile bootstrap, 2,000 draws, seed 20260921, 95%; U is its upper bound.
- **Rule.**

| Result | Effect on this rule |
| --- | --- |
| U < 0 | MG-3's 07-12 arm stays as in §2.1 |
| U ≥ 0 | MG-3's 07-12 arm reverts to MG-2's bound 07-12 arm (identical; Δ = 0); H1 narrows to 13-15; the WIN block condition applies to 13-15 only; N, dates, α and the look are unchanged |
| not computable before binding (backfill or partner history missing, or < 90% of history cells covered) | treated as U ≥ 0: the 07-12 arm reverts |

- The check is history only (no 2026 row, nothing after 2026-09-29). It never refits, re-weights or re-selects
  anything, and no other reading of the backfill can change this rule.
- Its result, file sha and the branch taken are filled at binding (`drop_0712` below).

### 2.3 Frozen artifacts

| Artifact | sha256 |
| --- | --- |
| State rule | `9e63899ddcfcbd795f10f0437c7bd9f9b6fc9740767b8d824818ef0f7f95cc5d` |
| P3d_H 07-12 state (control: re-emits `a2dc30e2…` byte-identical) | `e92764773e1614aae548ccfd74b3a60740f25105578abd045b0808fe6dd159c0` |
| P3d_H 13-16 state (control: re-emits `e5195945…` byte-identical) | `e891d884e06164a6925f6b2bbf1c7756529cb35222ab0c8c863552cfa7457db7` |
| Weight rule | `4fb02a2cec9a6c5c4fc06e811bd69d3ba35721d0650475c8584de313765ef6e8` |
| Weights (branch per §2.2) | `<FILL@BINDING>` |
| RN-1 rule / land 3x3 | `e4869491a8480f302c0bb4c33b0d55d4110ef98551f0db26e59d3441e204004b` / `22069beebb5609755b35621bac05e91a1b35e434670c993a93a8aca9434fd7d6` |
| MG-3 `release-binding.json` (`mg3-release-binding`, verified by `mg3_verify_release`) | `<FILL@BINDING>` |
| Forward parity rule | `2c6e6045dca379854c281195e0a51a61f0de400bc517ed7faa444b2900a6593e` |
| MG-3 emitter / serve module (neutral host-importable module, design draft §b.0) | `<FILL@BINDING>` |
| MG-2 rule, binding commit, `release-binding.json` | `<FILL@BINDING>` (as bound 10-27) |
| B scorer and dev scorecard code | `<FILL@BINDING>` (B's bound values) |
| This rule, raw sha256 | recorded in DECISION_LOG at binding |

## 3. Dates

- **MG3_D0** is the first local date after the latest of:
  1. the recorder's 14-day clock (10-27..11-09 complete days) and a PASS of `mg3-forward-parity` over those days
     under rule `2c6e6045…` (F0-F4; F3 against the archive when L13's archive covers them);
  2. the MG-3 binding commit (every §2.3 field filled);
  3. MG-2's 07-12 branch known (§2.2).
- Expected MG3_D0 is 2026-11-11 if all three hold on 11-10.
- **Countable dates:** every B countable date (B §3, including B's market-coverage drop) that is ≥ MG3_D0 and on
  which ≥ 9 of the 10 markets are recorder-countable (design draft §e.3). Non-countable MG-3 cells on a counted date
  are dropped, not imputed.
- **N is not chosen.** N is the number of countable dates from MG3_D0 through B's 45th date. If every date counts
  and D0 is 11-11, N = 31 (11-11..12-11). If B's 45th date moves later, MG-3's last date moves with it. MG-3 never
  scores a date outside B's 45.
- **Latest D0:** 2026-11-20 (N ≥ 22, the full-effect 80% size, §6). Later than that, this rule does not start and
  MG-3 goes back to disjoint dates (design draft D-B).
- **Minimum:** fewer than 22 surviving dates at the look is VOID.

## 4. Estimand, interval, verdict

- **H1:** ΔB = mean over equal (date, market) cells of [Brier(MG-3) − Brier(MG-2)], local hours 07-15, on
  snapshots both arms cover; equal snapshot weights within a cell. Computed by B's dev-scorecard code (`score_rows`)
  at B's bound code sha, against B's venue-rule labels. No market column is read.
- **Blocks:** ΔB(07-12) and ΔB(13-15) with the same machinery.
- **Interval:** fixed-market, date-clustered percentile bootstrap, 2,000 draws, seed 20260921, 95%; each bound one-
  sided at α 0.025. The crossed date × market interval is reported and does not decide.
- **α:** one test, one look, α 0.025 one-sided. It does not spend from CAMPAIGN_LEDGER and is separate from B's α.

| Verdict | Condition on ΔB(07-15) [L, U] |
| --- | --- |
| WIN | U < 0, and neither block has L > 0 |
| HARM | L > 0 |
| NULL | anything else |

- **WIN** earns a serving-parity and readiness discussion; never a promotion or an order.
- **NULL or HARM** closes "HRRR as frozen from Aug-Sep 2021-25, as an MG-2 input, in Oct-Dec". It is recorded in
  ESTABLISHED_FINDINGS / RETRACTED_AND_FALSE_LEADS and the digest and is never rescued by re-cutting.
- **One look, no interim** (§7 explains why an interim is not available on B's dates).
- **Reported, no α:** per hour, per block, per market with Holm HARM check, blend partner identity, `k_miss` rate,
  parity F0-F4 over the counted dates.

## 5. The look

In this order, all in one session:
1. MG-1's look receipt exists and MG-1's recorded window has closed.
2. B's look receipt exists (MG-2 + B computed, B §9). MG-3 reads nothing about a B date before this.
3. `mg3_verify_release` passes on every bound hash; `mg3-forward-parity` PASSES over the counted dates.
4. MG-3's H1 is computed from MG-3's daily receipted vectors and MG-2's bound vectors, with the labels from B's
   one-time transfer manifest (labels only; no price column is opened).
5. One MG-3 look receipt with every hash above.

Earliest read: B's look day, ≥ 2026-12-12.

## 6. Size and power (planning; history only)

Per-date SD of the date-mean paired Brier difference, from L2's LOYO rows 2021-25 Aug-Sep (298 dates; R-R rows
`170c61e3…`, R-K rows `bb0bf494…`); 07-12 uses B_H − B_N as the closest history analogue of blend − L6, 13-15 uses
P3d_H − P3d_N_fix with SF = 0. Scripts `size_paired.py` `51979e27…`, `size_pooled.py` `5b6019cd…`.

| Block | mean ΔB/date | SD/date | SNR | lag-1 autocorr |
| --- | --- | --- | --- | --- |
| 07-15 pooled | −0.0103 | 0.0169 | 0.61 | — |
| 07-12 (B_H − B_N) | −0.0081 | 0.0180 | 0.45 | 0.19 |
| 13-15 (P3d_H − P3d_N_fix, SF 0) | −0.0148 | 0.0278 | 0.53 | 0.01 |

Power = Φ(SNR·f·√N − 1.96), f = fraction of the history effect that transfers:

| N | f = 1 | f = ½ | f = ¼ |
| --- | --- | --- | --- |
| 22 | 0.82 | 0.30 | 0.11 |
| **31 (D0 11-11)** | **0.92** | **0.40** | 0.13 |
| 36 | 0.96 | 0.45 | 0.15 |
| 45 | 0.98 | 0.53 | 0.17 |
| 85 | 1.00 | 0.80 | 0.29 |

- **Assumptions:** the Aug-Sep history SNR transfers to Oct-Dec forward; the LOYO Brier scale and the dev
  scorecard's Brier scale differ, so only SNR (scale-free) is carried over; the lag-1 autocorrelation (0.19 at
  07-12) inflates the variance by about 1.4 on that block, not applied above.
- **Realistic planning row is f = ½:** the history effects are LOYO, not best-of, but L3's cool-season audit shows
  the Aug-Sep L6 stack does not transfer to Oct-Dec, and P3d_H is also Aug-Sep-fitted.

## 7. Void conditions

1. Any bound hash differs at the look, or `mg3_verify_release` raises.
2. The §2.3 identity controls fail.
3. `mg3-forward-parity` fails over the counted dates, or an HRRR version or grid change.
4. Fewer than 22 surviving dates.
5. Any outcome, label or price for an MG-3 date read before step 2 of §5.
6. A price column opened in MG-3's run.
7. MG-2 or B VOID for a reason that touches the shared vectors or labels.

## 8. Ledger

- Row 40 (DEV_WINDOW_LEDGER, PENDING, drafted before any fit): the §2.2 weight refit, only if a refit branch binds.
- Row 41 (PENDING): MG-3's positive control on the dev window before the look — reproduce R-R `rr_score.json`
  `577b689b…` gate 4 and R-K `rk_score.json` gate 3 from the frozen states and weights through the MG-3 emitter, to
  1e-9.

```mg3_dc_rule_v1
rule_id: MG3-DC-1
candidate: mg3_asof_capture
comparator: mg2_asof_capture_as_bound
dates: b_rule_v1_countable_dates_from_mg3_d0
mg3_d0_earliest: 2026-11-11
mg3_d0_latest: 2026-11-20
min_surviving_dates: 22
markets: atlanta,austin,chicago,dallas,houston,los-angeles,miami,nyc,san-francisco,seattle
hours_primary: 07-15
identical_hours_excluded: 00-06,16,17-23,san-francisco_13-16
metric: brier_difference_mg3_minus_mg2
interval: date_clustered_w_date_2000_seed_20260921
alpha_one_sided: 0.025
looks: 1
look_after: b_look_receipt
p3d_h_state_0712_sha256: e92764773e1614aae548ccfd74b3a60740f25105578abd045b0808fe6dd159c0
p3d_h_state_1316_sha256: e891d884e06164a6925f6b2bbf1c7756529cb35222ab0c8c863552cfa7457db7
weights_sha256: <FILL@BINDING>
l6_partner: <FILL@BINDING>
drop_0712_rule: U_cool_ge_0_or_not_computable_or_coverage_lt_0.90_reverts_0712_to_mg2_arm
drop_0712_partner: true_bound_partner_proxy_only_if_provably_unavailable_stated_deviation
drop_0712: <FILL@BINDING>
release_binding_sha256: <FILL@BINDING>
parity_rule_sha256: 2c6e6045dca379854c281195e0a51a61f0de400bc517ed7faa444b2900a6593e
mg2_release_binding_sha256: <FILL@BINDING>
b_scorer_sha256: <FILL@BINDING>
```
