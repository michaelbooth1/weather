# K row 112, G1 result: PASS (LOYO, history only) (2026-11-01)

> **X30 caveat.** A LOYO pass is not evidence of information. It may be a bias correction that reverses on 2026.
> Only G2, the dev refutation, can support the candidate, and even a G2 pass is a dev-selection result, not an edge.
> The G0 caveats still stand:
> - only 24 of 60 2026 market-months improved;
> - May over-corrected;
> - the effect was intercept-like.

## Provenance

- **Rule:** `rule_x36_trailing_final.md` sha256 `032c8dc3bf33fd7dc549a5a9e93ed04d86809678a087fc43766e272b99f077f2`.
- **Module:** `tools/research/x36_v5_reopen/x36_trailing_g1.py` sha256
  `7b14c3191bd2651eae4ad72de5b304f3e11af11caf9bb8c9c847d2f56f7e0ecd`.
  - Committed at `d7f818538e2afa066f3dfca23933034abd72ab47` and reported to the coordinator before the run.
  - Run via `workstation_heavy.ps1 -Kind weather_heavy -Queue`.
- **Run environment:** `C:\wt\L47rq`, detached and clean at `558889b13ac7d7165ddb299daa160052862aeb50`.
  - pooled_residual_model sha `04e87406â€¦`
  - spread_information_rung sha `0eedce73â€¦`
- **d series:** `C:\t\L47b\g1\dseries.json` sha `387c1a5005821b3ceaff11b28721597acc44c14fa79875d21c177ad7fa85d2dc`
  (3,297 of 3,300 market-days, 2021-25 Aug 1..Sep 29).
- **Outputs:**
  - `C:\t\L47b\g1\out\g1_result.json` sha `8f3a3e69042b392d392b1c832b20b383fde374a4673a2fd6b8f3a816985ef447`
  - `g1_rows.jsonl` sha `4730eeb5fd27eb063f63333db0efdb4fb8248566e23fdf7de3c2db008eeb240b`

## Positive control

The P3d_N_fix base reproduces R-A's 07-12 LOYO rows exactly:
- reference `C:\t\l2\rung0712\emit\loyo_rows.jsonl`, sha `21cacdaaâ€¦`
- 19,657 / 19,657 rows, same keys, max abs diff 0.0

## Gate: Î” Brier (P3d_T âˆ’ P3d_N_fix), target dates Aug 15..Sep 29, 2021-25

Bootstrap: 2000 date-clustered draws, seed 20261024.

| Group | Î”Brier | 95% CI | base Brier | n |
| --- | ---: | --- | ---: | ---: |
| h07 | âˆ’0.00310 | [âˆ’0.00493, âˆ’0.00124] | 0.8666 | 2,505 |
| h08 | âˆ’0.00291 | [âˆ’0.00461, âˆ’0.00118] | 0.8632 | 2,505 |
| h09 | âˆ’0.00243 | [âˆ’0.00381, âˆ’0.00108] | 0.8594 | 2,506 |
| h10 | âˆ’0.00209 | [âˆ’0.00317, âˆ’0.00092] | 0.8544 | 2,507 |
| h11 | âˆ’0.00207 | [âˆ’0.00394, âˆ’0.00015] | 0.8413 | 2,507 |
| h12 | âˆ’0.00094 | [âˆ’0.00353, +0.00181] | 0.8192 | 2,507 |
| **pooled** | **âˆ’0.00226** | **[âˆ’0.00378, âˆ’0.00079]** | 0.8507 | 15,037 (230 dates) |

- Pooled Î”log: âˆ’0.0202 [âˆ’0.0276, âˆ’0.0131].
- **Verdict:** point âˆ’0.00226 < âˆ’0.0005, so **PASS**. G2 is eligible only on the coordinator's go.

## Picks and shifts

- **Inner-loop picks:** Î» is 0.5 at h07-h08 and early h09, and 0.25 elsewhere. W is mixed between 7 and 14. Î» = 1 was
  never picked, and Î» = 0 was never picked.
- **Shift size:** mean |shift| is 0.34 Â°F.
- **Availability:** a trailing window was available for every one of the 15,037 gate rows.

## Reading

- The rule disclosed that the training-era excess is about 0 by construction. That holds for the seasonal mean
  only. The trailing window still captures within-season, within-year anomalies of the NBM bias, and that is what
  G1 rewards.
- The gain fades with hour (h12's interval spans 0), as the observed running max takes over the centre.
- The shrinkage picks (Î» â‰¤ 0.5) agree with G0: a full correction adds noise.
