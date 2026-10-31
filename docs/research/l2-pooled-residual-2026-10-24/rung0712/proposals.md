# L2 proposals: next ladder rung at 07-12 (P3d_N and the composite)

Written 2026-10-25 before any rung result exists. The composite serves MG-1 + L6 before 13:00. Run 2 at 07-12
was inconclusive against the market (R 0.9998); P3d_N alone at 07-12 is R 1.19 (descriptive). Every rung starts
from a pooled OLS / NBM baseline and must beat it on the dev scorecard before a complex model is admitted.
Ranking = expected gain per unit of work. Dev data only (2026-08-01..09-29); training 2021-25.

| # | Rung | Baseline it must beat | Data source | Cost | Kill condition |
| --- | --- | --- | --- | --- | --- |
| 1 | **R-A: NBM-anchored pooled baseline B_N, then P3d_N_fix, per hour 07-12.** B_N = per-cutoff pooled OLS of y - (nbm_mean + bias) on [1, g, max(g,0)], constant per-hour scale from inner leave-one-year-out errors, same kernel, floor and 2% climatology mix. P3d_N_fix = P3d_N with the L11 look-ahead fixed (each dev row uses the latest replay snapshot captured at or before its own capture time) and the frozen WU whole-F conversion. | B_N vs MG-1 (the 07-12 composite); P3d_N_fix vs B_N, then vs MG-1 | No download: records 744289be, NBM 1ae4bf52, layout v3, replay le0929 | ~1.5 h code, 1 emit + 1 score job | B_N - MG-1 07-12 date-clustered CI lower > 0 kills the NBM-anchored family at 07-12; P3d_N_fix not beating B_N (CI upper >= 0) kills the HGB layer at 07-12 |
| 2 | **R-D: hour-wise linear pool of MG-1 and the best of R-A**, walk-forward weight per hour fitted on prior dev dates only (burn-in 08-01..08-14). | MG-1 (w = 0) | No download: R-A vectors + builtin MG-1 | ~1.5 h, 1 score job | 07-12 dR vs MG-1 CI spans 0, or mean w < 0.05; run only if R-A's best is within 0.02 Brier-ratio of MG-1 at some hour (otherwise w ~ 0 by construction) |
| 3 | **R-B: morning ingredients on top of B_N** (overnight min, dewpoint depression, wind, cloud, 3-METAR trend), OLS terms only. | B_N | WU hourly history (training) + captured METAR (serve); parity work needed for cloud and wind | ~4 h + parity test | dR vs B_N CI spans 0 at 07-12. Prior: L5's overnight-low anomaly (A2) was null vs MG-1, so expected gain is small |
| 4 | **R-E: loss decomposition of P3d_N vs MG-1 at 07-12** (calibration, sharpness, floor-mass, per market) - descriptive, folded into R-A's report, decides whether R-B or a scale fix is worth it. | - | R-A outputs | ~0.5 h | none (descriptive) |
| 5 | **R-C: later NBM cycles.** The NBP bulletin (the L9 fetcher's product) is issued only at 01/07/13/19Z, and 13Z/19Z hold no maximum for the current local date (EF section 10l), so a 09Z/11Z/13Z NBP max does not exist. The only route is the hourly NBS/NBH text bulletins: a large 2021-25 archive pull and a new production capture path before serve parity exists. | B_N on 07Z | noaa-nbm-grib2-pds NBS/NBH (free, official, large) | days; new capture path | defer; kill if the archive lacks point-in-time LastModified for 2021-25 |

**Run now (no download):** R-A, then R-D if its precondition holds. Pre-registration in
C:\t\l2\rung0712\rule.md (sha recorded before any result).
