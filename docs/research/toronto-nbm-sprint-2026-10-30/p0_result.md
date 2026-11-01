# Toronto NBM sprint: P0 result, row 77 (lane L8, 2026-10-30)

**Verdict: both arms KILL at P0.** The w gate and the tradability replay were not run; master's condition
(3) runs them only for a P0 pass.

## Run

| Item | Value |
| --- | --- |
| Rules | `rule_toronto_nbm.md`, `clarification_toronto_mr.md`, clarification 2 (price source), clarification 4 (arms), clarification 5 (P0 = L3 §5 exactly), clarification 6/6b (YES last trade = gamma; a missing CLOB side at its bound), `availability_audit.md` (master conditions 1 and 2) |
| Run env | `8bb0f9563582885c4d01d34b67476f2563260e43`, clean (asserted by the driver) |
| Driver | `C:\t\l8tor\p0.py` sha256 `d162bee8e650cc6b2fbe5df86b65c986529b932423cd516c1c587170286721a0` (stages extract, market, arms, score; each under 1 min, run directly) |
| Receipt | `C:\t\l8tor\p0_out\receipt.json` sha256 `6baa2703f144fc8bcf0226d6e5542a2ca11903edef83fee89368290037c7876b` |
| Per-date rows | `p0_out\p0_rows.jsonl` sha256 `7305a65bc5a301e59b806f41ffc9ca057ca0509331a5dc0aa7923de34c902fad`: per (arm, date), n entries, n snapshots, and the six sums for c and for each of the 20 placebos |
| Stage outputs | extract `ccc43aff…8974`, market `584f09ca…8673`, arms `16ba22cf…3126` (full shas in the receipt) |
| Replay inputs | SHA256SUMS `d9c2ed46…8b82`; 4,791 snapshots, hours 07-16; 0 malformed lines |
| Table | Fit table: 4,688 snapshots (08-01..09-29). Score table: 3,584 snapshots on 46 dates (08-15..09-29). Drops: 08-08 has no WU label (100 snapshots); 3 snapshots have no tape group within 10 min. |
| Arm coverage | 4,677 of 4,688 fit snapshots (the 11 missing have no METAR floor at t_c) |
| P0 population | 3,447 snapshots on 46 dates, each covered with every donor covered |
| Serve inputs | NBP V5.0. The newest NBP received by t_c is 07Z on 4,734 snapshots, 19Z (D-1) on 32 and 01Z on 10. NBH V5.0 from `nbs_nbh_2026dev` (manifest `5d2c82ad…752a`). |

## Statistics

L3 §5: 20 disagreement placebos and 10,000 date draws, with draw b paired to derangement b mod 20.

| Arm | ρ_c [95%] | mean ρ_pl [95%] | Δ = ρ_c − mean ρ_pl [95%] | one-sided p | c-deranged diagnostic ρ [95%] | P0 |
| --- | --- | --- | --- | --- | --- | --- |
| A (newest NBP + TXNSD) | +0.0376 [−0.0800, +0.1463] | −0.0011 [−0.0798, +0.0927] | +0.0387 [−0.0762, +0.1502] | 0.249 | −0.0122 [−0.0800, +0.0521], covers 0 | **KILL** |
| B (A + NBH rest-of-day max) | −0.0123 [−0.1194, +0.0968] | −0.0272 [−0.0928, +0.0407] | +0.0149 [−0.0852, +0.1141] | 0.399 | −0.0181 [−0.0877, +0.0476], covers 0 | **KILL** |

- Neither arm's lower bound of ρ_c exceeds 0, and neither arm's lower bound of Δ exceeds 0.
- Arm B, the S2 winner on history (Brier −0.0334 against the incumbent), has a dev residual correlation
  with the market error of about zero.
- Since P0 failed, the following are not computed: w, blend R, blend − placebo, blend − floor-only, and the
  C3 identity.

## Disclosures

- **Version caveat:** training used NBM V4.0-V4.3 and serving used V5.0 (`availability_audit.md` §3).
  This kill cannot separate "no information beyond the market" from "the V4.x-trained model does not
  transfer to V5.0".
- **Price-rule amendments before the outcome read:** clarification 6 and 6b were committed (`f0df61c21`,
  `4ef1cada0`) after the as-built m was found broken on inputs alone. With the CLOB either-token last-trade
  column, the median sum of m was 3.03; dead one-sided tails then dropped 33 of 60 dates. Both amendments
  came before any label or statistic.
- **Score attempt 1:** it crashed at table construction (served-vector keys were strings), before any
  statistic was computed or printed. The fix was one line, and the receipt records the attempt. The
  reported run is the only statistical reading.
- **Multiplicity:** this is the 2nd test of NBM text guidance on the Toronto dev window, after L14. Two
  arms, with no correction across them (clarification 5 §2).
