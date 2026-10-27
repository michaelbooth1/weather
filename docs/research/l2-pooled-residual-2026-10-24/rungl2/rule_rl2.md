# L2 rung R-L2 pre-registration: NBS TXN at 07-12, with a format-defined cycle choice

Written 2026-10-26, **before any R-L2 fit**. No R-L2 row has been joined to an outcome, label, price or market row.

- **Authority:** master's YES to R-L2, relayed by the coordinator on 2026-10-26. The coordinator's wording: "the
  newest cycle available at the cutoff that still carries the target-day TXN, in practice ≤12Z".
- **Evidence class:** development evidence only. No edge claim.
- **Data limits:**
  - Nothing dated after 2026-09-29 is read.
  - Nothing touches MG-2 or L8's branch.
  - L12's corpora are read only.
- **Parent rule:** R-L, `docs/research/l2-pooled-residual-2026-10-24/rungl/rule_rl.md`, sha256
  `3ce9a6f2403c68b543c13be2ea36d4b92cd711b3e9e544a92e79744db53ca9b8`.
  - Where this rule is silent, R-L applies verbatim.
  - Its gates, thresholds, arms, seeds, controls and outputs layout are reused unchanged, except where the cycle
    choice below changes them.

## Why R-L2 exists (R-L's gate-1a stop)

R-L stopped at gate 1a, which is not a kill.
- **Audit:** `C:\t\l2\rungl\loyo\rl_loyo_audit.json`, sha256
  `adcc8b2ad73e3ce1c1b10fda5d3130efd644d00c877407bb12c1e48bd25d1c23`.
- **Summary:** `rungl/rl_summary.md`, sha256 `03b5554f3b3725ecf00a2dbb0f62712e7525235e4e6f58d29bb11ad9df49687a`.
- **Coverage:** 8,517/19,657 = 0.433 against the 0.95 threshold. 11,140 rows were `column_absent`.
- **Cause:** a structural product-format fact. NBS omits the day's TXN (the 00 UTC d+1 daytime-maximum column) from
  cycles issued after the maximum period has begun, about 13Z and later.
  - R-L's rule took the newest cycle, then failed closed when it lacked the column.
  - At late-morning cutoffs, the newest cycle is often one of those.
- **Other checks passed:** the column check passed (median |n_txn − nbm| = 1.0 °F), and so did block integrity.

## The cost, stated before any row exists

1. **The centre is staler after about 12Z.** At cutoffs whose newest available cycle is 13Z or later, R-L2 uses an
   older cycle (in practice ≤12Z), so its TXN can be several hours older than the newest NBS issuance.
   - R-L2 therefore tests "NBS TXN as of the last TXN-bearing cycle", not "the freshest NBS".
   - Its selected-cycle age is reported per hour (below).
2. **It cannot test R-H hypothesis 2's freshness claim.** R-H's hypothesis 2 ranked NBS TXN above HRRR on freshness
   grounds.
   - A positive result here does not show that a fresher NBS centre helps.
   - A negative result does not show that freshness is worthless.
   - Either way, R-L2 does not adjudicate that claim, and it must not be cited as having done so.
3. **The prior stays low.** The register lists NBS as S4 TESTED-NO-INCREMENT at 00-16 (R-L's disclosure, unchanged).

## The one change: cycle selection

For a row (market m, its registry station, local target date d, cutoff hour h ∈ {7, …, 12}, t = h:00 local):

1. **Eligible cycles:** L12's `nbs` manifest rows with `status` ok, a station block with `status` ok,
   `last_modified` + 10 min ≤ t, and cycle ≤ t. This is R-L's eligibility, unchanged.
2. **Walk the eligible cycles from newest to oldest**, stopping at cycles older than t − 12 h (R-L's age bound).
   For each cycle:
   - Verify the block (sha256 against the manifest, parse, station and issue-time identity). **If verification
     fails, the row fails closed** with that reason (`sha_mismatch`, `parse_failed` or `identity_mismatch`). It
     counts against parity and does not skip to an older cycle.
   - If the verified block **carries the target-day TXN**, meaning both `TXN` and `XND` are present and numeric in
     the 00 UTC d+1 column, select it and stop.
   - Otherwise (`column_absent`), continue to the next older cycle.
3. **If no cycle is selected,** the row has `n_miss` = 1 with reason `no_txn_cycle`.
4. **The ≤12Z wording is descriptive, not coded.** The rule is defined by the product format (does the block carry
   the column?). The selected cycle's UTC hour distribution is reported, so the ≤12Z description can be checked.

Everything else is R-L's, unchanged:
- the columns `n_txn`, `n_gap`, `n_xnd` and `n_miss`;
- the anchors (L9 `nbm_at_cutoff` in training, captured `usable_v2_mean` on dev);
- the TXN range [−40, 130] °F;
- NaN handling;
- the arms **B_L** = B_N + `extra_ols` (`n_gap`, `n_miss`) and **P3d_L** = P3d_N_fix + `extra_hgb` (`n_txn`,
  `n_gap`, `n_xnd`);
- per-hour fits on Aug-Sep 2021-25;
- no other NBS element and no NBH.

## Data (L12's sealed corpora; the sha256 of each SHA256SUMS is pinned in code and refused on mismatch)

| Use | Corpus | SHA256SUMS sha256 | manifest sha256 |
| --- | --- | --- | --- |
| Training | `C:\t\l12\nbs_nbh\` | `2c5fc33a62a72b8d5b7aab7f44c4924571b96c9f4b15e1da5731a452c4867b86` | `f7aee19b…7e71` |
| Dev | `C:\t\l12\nbs_nbh_2026dev\` | `dd2b7ac4227ee3b9d3345f1e84b81e0f8fcbe4648688e54f0b09e92e6ade7887` | `5d2c82ad…752a` |

## Gates (in order; each stops the rung if it fails)

### Gate 1: parity (R-L2's own, under the new cycle rule)

**1a, before gate 2, on the h07-12 training rows:**
- coverage (`n_miss` = 0) **≥ 0.95**;
- zero `sha_mismatch`, `parse_failed` and `identity_mismatch` rows;
- zero `txn_out_of_range`;
- column check: median |`n_txn` − nbm_mean| ≤ 3 °F.

**1b, before gate 3, on the dev h07-12 layout rows:** the same checks.

Failing either half stops R-L2 as "parity failed" (not a kill). No further cycle rule follows from that without a new
owner ruling.

### Gate 2: LOYO 2021-25, B_L beats B_N at 07-12

This is R-L's gate 2, unchanged:
- **Statistic:** pooled h07-12 mean of Brier(B_L) − Brier(B_N), with a date-clustered bootstrap (2,000 draws, seed
  20261024).
- **PASS** if the upper 95% bound is below 0.
- **Control (refused otherwise):** R-A's `C:\t\l2\rung0712\emit\loyo_rows.jsonl` (sha `21cacdaa…f54d`) must be
  reproduced exactly.
- **Reported:** each hour, and P3d_L − P3d_N_fix.

### Gate 3: dev, P3d_L beats P3d_N_fix at 07-12

This is R-L's gate 3, unchanged:
- **Statistic:** dR, ALL markets, h07-12, on snapshots covered by all four arms, with date-clustered 95% intervals
  (2,000 draws, seed 20260921).
- **PASS** if the upper bound is below 0.
- **Controls (refused otherwise):**
  - B_N and P3d_N_fix dev files byte-identical to R-A's (`83cf9bbe…`, `cd0034b9…`);
  - MG-1 07-12 control 0.012.

### Gate 4: against the MG-2 pre-13 arm (MG-1 + L6)

This is R-L's gate 4, unchanged: P3d_L − L6 on gate 3's statistic, read as WIN, HARM or NULL exactly as in R-L, with
R-F's in-sample caveat. If WIN, L2 drafts, but does not apply, the Clarification and the forward-parity plan.

### Reported only (never a gate)

- Each hour and each market.
- B_L − B_N on dev.
- `n_miss` rates and reasons.
- **Staleness, per cutoff hour:** the selected cycle's age, its UTC-hour distribution, and the share of rows where
  the newest eligible cycle was skipped for lacking the column.

## PRE-REGISTERED KILL

If gate 2 or gate 3 fails, **NBS TXN is closed as a 07-12 centre input**, under R-L's and R-L2's cycle rules alike.
Concretely, no other TXN or XND transform, cycle rule, margin, column or age bound is run as a centre input at 07-12
on B_N, P3d_N_fix or any NBM-anchored arm under any rung name. Other NBS elements and NBH stay as R-L left them: they
need an owner ruling.

A gate 1 failure, a refused control, or a missing corpus stops R-L2 without a kill.

## Outputs

- `C:\t\l2\rungl2\loyo\`, `C:\t\l2\rungl2\emit\` and `C:\t\l2\rungl2\score\rl2_score.json`.
- This rule, its `.sha256` sidecar and the summary go in `docs/research/l2-pooled-residual-2026-10-24/rungl2/`.
- The code records this rule's sha256 (`RL2_RULE_SHA256`) before any R-L2 row exists.
