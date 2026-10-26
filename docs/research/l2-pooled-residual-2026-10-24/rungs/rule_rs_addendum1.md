# R-S addendum 1: NBM-version (era) check before any fit (guard G-v)

Written 2026-10-26, **before any R-S fit**, on the coordinator's instruction of the same day. No R-S row has been
fitted, emitted or joined to an outcome, label, price or market row.

- **Amends:** rule_rs.md, sha256 `5fb593f4dbfac01fd0c9984ccb29522dbee979f54d27852baadccadcb21d13a2`. Everything there
  stands except where this addendum adds a step.
- **Why:** the R-L2 anchor diagnostic (rungl2/anchor_diag.md) showed that an NBM-derived input can change distribution
  between the v4.x training years and the v5.0 dev year. Under R-S, a scale HGB trained on v4.x `sd` and p10/p90 would
  be served on v5.0 values. The check below is outcome-free and runs before gate 2.

## Step order (per window)

1. Gate 1a (training parity), unchanged.
2. **Guard G-v (new).**
3. Guard G-s, control C-mean, the base-reproduction control and gate 2, unchanged.

Gate 1b, gate 3 and gate 4 are unchanged.

## Reported (outcome-free)

For `nbm_sd` and `nbm_qw` (p90 − p10):
- **Distributions:** n, mean, p10, p25, median, p75 and p90.
- **Training cells:** each training year 2021-25, with the NBM product version of the anchor rows (4.0, 4.1, 4.2, 4.3),
  plus all years pooled.
- **Dev cell:** 2026 (v5.0).
- **Breakdowns:** per window, also per cutoff hour.
- **Populations:**
  - *Training:* the window's training rows that have an anchor, with values exactly as gate 1a attaches them.
  - *Dev:* the gate 1b population. These are layout snapshots at the window's cutoff hours, with `local_hour` ≥ the
    cutoff and a usable captured v2 mean, dated 2026-07-30..09-29. Values are the captured `v2_stddev` and
    `v2_p90 − v2_p10`.

No label, outcome or price is read.

## Guard G-v (stop rule, not a kill)

**Ratios.** For each window:
- r_sd = median(dev `nbm_sd`) / median(pooled training `nbm_sd`);
- r_qw = median(dev `nbm_qw`) / median(pooled training `nbm_qw`).

**Stop rule.**
- If r_sd or r_qw lies outside **[0.8, 1.25]**, that window **stops before LOYO** as "era shift (G-v)".
- A training median of 0 is also a stop.
- **This is not a kill.** Any follow-up (for example a version-normalised column) needs a fresh rule and ruling.

## Outputs

- G-v and the distributions are written into `rs_loyo_audit.json` under `guard_gv`, before any LOYO row exists.
- The code records this addendum's sha256 as `RS_ADDENDUM1_SHA256`.
