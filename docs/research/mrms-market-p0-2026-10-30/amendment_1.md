# MRMS P0 (ledger row 91), amendment 1: clip g_z to [-3, +3]; synthetic sign control

Status: committed before any computation under rule `b0f170a5a69b93c040d3b7092e5c3f2ce2eb9a626978ad77f2b2f69e02fa091e`
(2026-10-30, lane L3; coordinator ruling 2026-10-30). Nothing under the rule has been computed; no outcome, price or
label has been read.

## Why

Ruled from input-only echo counts at 13-16 on 2026-08-01..09-29, read before any outcome: San Francisco has 3 echo
snapshots of 1,699 for MRMS-ECHO35, so its within-market g_z reaches +23.8; Dallas has 25 of 1,673 (g_z up to
+8.1). A handful of snapshots could dominate the pooled statistic.

## Changes (nothing else changes)

- **A1.** For both candidates (MRMS-MAXDBZ25, MRMS-ECHO35) in all markets, g_z is clipped to [-3, +3] after the
  within-market z-score (rule section 4, including the sd < 1e-9 zero-tilt rule). The decision (BH over K = 2,
  Delta lower bound > 0, w gate only for a survivor) is taken on the clipped candidates.
- **A2.** The unclipped versions of the two candidates become a descriptive arm with no decision, beside the 50 km
  descriptive arm (which is unchanged, unclipped).
- **A3.** The run reports the number of clipped snapshots per market and candidate.
- **Implementation note (no change to mr_sweep).** `mr_sweep.band_signal` re-standardises type D values within
  market, which would undo a clip (exactly so for the binary flag). The clipped g_z therefore enters through the
  algebraically identical type C form x = mu_m + sigma * g_z * sigma_m, which gives
  s_b = (x - mu_m)(z_b - mu_m) / sigma_m^2 = sigma * g_z * (z_b - mu_m) / sigma_m, the rule's type D signal, exactly.
  For |g_z| <= 3 everywhere this equals the unclipped type D path.
- **A4. Synthetic sign control (master, 2026-10-30; a standing rule for any P0 on a newly built table or a new tilt
  form).** Before any candidate is scored, two synthetic candidates are injected on MRMS-MAXDBZ25's covered
  snapshots and passed through exactly the candidates' path (within-market z-score, the A1 clip, type D sign -1):
  - r = sum_b (y_b - m_b)(z_b - mu_m) / sigma_m per snapshot (the realised market residual's band position, on the
    fit table), plus Gaussian noise with SD = sd(r) over covered snapshots, seed 20261031 (numpy default_rng);
  - `synthetic_sign_pos` g = -(r + noise), oriented so that under sign -1 it tilts toward the outcome. It must PASS
    under the full rule: testable, p <= 0.10 (BH at K = 1) and Delta 95% lower bound > 0;
  - `synthetic_sign_neg` g = +(r + noise), which must read Delta < 0.
  Both are reported beside the served, MG-1 and w = 0 controls. If either fails, the run is VOID and no candidate
  is scored: fix, disclose, and re-run once under the same rule, with the fix diff to the coordinator first.
