# Rule L8-HSF-1 (lane L8, 2026-10-24): high_so_far train/serve parity, shadow variant

Written 2026-10-24, before any score of this variant exists. The only outputs read before locking are
outcome-blind (the base/fix replay vectors and features, and the MG-1 sidestep count) and the loss-atlas
served run named in (c). Code: branch `claude/high-so-far-parity-shadow-20261024` @ `ea449e9cc` (variant and scorer), `061c8b5f2` (verdict: MG-1 ledger and floor checks), `f3b49fabb` (the shared `weather.model.observed_running_max.running_max_since_midnight`, emit byte-identical; based on
origin/master `87af8ed8b`), module `weather.calibration.high_so_far_parity_shadow` (`emit`, `sidestep`,
`check`, `score`, `verdict`), run from a local, never-pushed merge with W2 `1a16c6ed3`, the loss-atlas
branch `8a58d9b04` (dev scorecard `4be7c077c` + prereg checker) and `claude/free-source-screens-20261023`
(MG-1 control only).

## The variant (what is scored)

- **Serving (shadow only):** `high_so_far_shadow_variant = "metar_running_max_since_midnight_v1"` on one model
  instance. Production keeps `None`; a test pins that the production path never reaches the new code.
- **Definition (same as training):** training (`feature_store.build_historical_feature_record`; also
  `feature_model.py:990-996`) takes `high_so_far = max(temp of every target-local-date row with minute of day
  <= cutoff_hour * 60)`. The variant takes the same max over the captured METAR / station rows, keyed on the
  observation instant (`lockin_observed_rows`: payload `obsTime`, else the raw `DDHHMMZ` group, never AWC's
  nominal hour), target local date only, so the previous day's 23:5x report that arrives as the `00:00` row
  is excluded. When no target-date row is observed by the cutoff (for example a 00:01 snapshot), or printed WU
  rows exist, or the startup guard quarantined the row, the served value stands.
- **Stated differences from training:** (1) source rounding: METAR carries the T-group (tenths of °C,
  converted to °F, for example 84.02) where WU history rows carry whole °F; (2) before 07:00 serving uses the
  cutoff-07 model but can only see rows observed so far, while the trainer's cutoff-07 row sees rows to 07:00;
  (3) post-cutoff readings stay out of the feature, as in training (they reach the model through
  `live_reading_temp`); the served value, by contrast, included the live reading and the max since 07:00.
- **Derived features move together:** `forecast_gap`, `live_reading_minus_high`, `guidance_physical_floor`,
  the forecast-profile and US-guidance floor features (`observed_floor_native`, the NBM floor gap), the analog
  selection on `round_half_up(high_so_far)` (serving side of `feature_model.py:1356`) and `hours_at_peak`
  (first observation minute reaching the max, as in training) all derive from the new value. `is_extended`
  is a training label only.
- **Floor:** floor high = `max(served floor high, running max)`: it can only get stronger. Tested
  (`tests/model/test_high_so_far_parity_shadow.py::test_floor_only_gets_stronger`) and counted on every
  emitted row (`check`: `floor_weaker` and `floor_high_weaker` must both be 0, else NO CLAIM).

## How this differs from the §4 input repair (a precise null)

EF §4 (`-09-43a`/`-09-44a`) routed 8 dead local-meteorology inputs (`rise_from_7am`, `dewpoint_c`, ...)
from station rows; `high_so_far` was one of the surviving inputs and was not touched. Its null was the gap
ratio on the pre-07-31 sealed panel. This variant changes `high_so_far` itself, the HGB's strongest live
input, whose served value differs from the trained definition on 93.72% of C snapshots (EF §1k `-09-70a`),
and it is aimed at a traced mechanism (L5: skew -> cold HGB centre -> morning catch-up; Atlanta 08-21 HGB
centre 91.96 -> 87.86 F from 00:01 to 08:04). A null here is its own measurement, not a re-read of §4.

## (a) Positive control

1. Served vs market pooled R **1.774** (all hours) and **1.526** (00-16) on the dev scorecard's default folds
   (layout `C:\swarm\v3layout`, scored 2026-08-15..09-29), to three decimals; otherwise NO CLAIM.
2. MG-1 reimplementation equals lane G's `free_source_candidates.mg1.predict` frame exactly, and MG-1 minus
   served 00-12 Brier (crossed) reproduces ledger row 4, **-0.0153**, to four decimals.
3. Replay control (outcome-blind, before scoring): on every emitted row whose `high_so_far` features and
   floor high are unchanged by the variant, the fix vector equals the base vector (L1 = 0.000 on all of
   them); the share of base replays equal to the recorded vector within 1e-9 is reported (EF §10v expects
   0.04-0.22 per market at current code). At the record's runtime commit `a76ec7b55` L5 replayed Atlanta
   08-21 00:01 / 03:58 / 08:04 with L1 = 0.00 against the recorded vectors.

## (b) Comparator fairness

The primary comparator for the variant's own effect is **base** = the same current-code serving pipeline
replayed on the same captured inputs and the same snapshots, variant off: the same hard floor, late-day
stages and overconfidence calibration as the candidate (one switch differs). Both get the scorecard's rule-4
floor mask and served fallback on identical rows; a snapshot without both a base and a fix vector falls back
to served in both. Served (the vector of record) and MG-1 (rule `r-t5-inc-c1`, zero parameters, its own
floor B from the rule-4 floor, no calibration stage) are scored the same way. MG-1+fix is MG-1 with
F' = max(F, fix floor high): same calibration (none) and only the floor raised. EF §10v: fix minus served
mixes code drift with the variant, so the variant's effect is read on fix minus base only.

## (c) Targeted loss slice

Loss atlas `46a66f7b77271373024a50e3d7882ab11585c16b1c995d442bf14a66dc735184` (served, window 00-16, positive control PASS 1.774 / 1.526): served 00-16 excess over market 0.0256 Brier, centre share (Shapley) 76.1%, so the centre slice is about 0.0195; served centre bias -1.14 F. Expected size of what this variant can close: at most 0.0040 of the 0.0256 excess (a warm HGB-centre shift of roughly 1 F on about a third of market-days, concentrated in 02-10 h, and diluted by the later serving stages that pass the HGB centre through within about 0.6 F). The variant targets the
centre component of the 00-12 served excess on market-days where the served `high_so_far` sits below its
running maximum (L5: mean deficit 3.96 F at 06 h; served drift -0.92 F 00->08 h where the 08 h deficit is
>= 3 F, 166 of 473 market-days).

## (d) MDE and clusters

Reference MDE80 0.0099 Brier (atlas `46a66f7b7727`, served minus MG-1 00-16, crossed; about 0.20 in R at the 00-16 market Brier of 0.0486). The paired fix minus base MDE80 (date-clustered, 00-16 and 07-12) is computed by the scorer's centred bootstrap and reported with every result; a null below it is 'no increment demonstrated'. Clusters: 43 date clusters and 11 market clusters (473 market-days). The primary interval
is date-clustered (43 clusters); the crossed interval is reported beside it. 2,000 draws, seed 20260921.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md (`8a58d9b04`): this is ledger row 19 on 2026-07-31..09-29 and candidate (K) number 14
there, after the pre-ledger block (134 swarm rules, 79a, 81a, 111h). Two arms are scored against MG-1 (fix,
MG-1+fix); that is stated with every result.

## Keep/kill rule (variant as a serving parity fix)

KEEP only if pooled 00-16 dR(fix - base) has a date-clustered 95% CI upper bound < 0 **and** no standard
block (00-05, 06-09, 10-12, 13-16, 17-23, 00-16, all) has dR(fix - base) with CI lower bound > 0; otherwise
KILL as a scoring lever (the parity defect stays documented as correctness). dR = mean_cell(Brier_a -
Brier_b) / mean_cell(Brier_market) on the same cells. Reported, not part of the verdict: 07-12, every hour
00-23, per market (00-16, 07-12, all), dBrier, crossed intervals, fix - served.

## Binding (MG-2)

An arm in {fix, MG-1+fix} **beats MG-1** only if pooled 00-16 dR(arm - MG-1) has a date-clustered 95% CI
upper bound < 0 and no standard block has dR(arm - MG-1) with CI lower bound > 0. If one or both beat
MG-1 **and** the variant creates no new above-settlement floor row (floor bucket > settled high where base's
is not; census over every scored emitted row), the arm with the lower 00-16 point is bound as MG-2 and a
binding plan is written; master gets one Fable review before landing. If an arm beats MG-1 but the census is
non-zero, nothing is bound and a ruling is asked. Otherwise NOT BOUND.

MG-1 sidestep (answered before scoring, outcome-blind): MG-1's centre is the NBM v2 mean and never the HGB,
so the cold-centre mechanism cannot reach it; only its floor B reads `high_so_far`, and the layout's rule-4
floor already carries `guidance_physical_floor`. The `sidestep` count of MG-1-covered snapshots whose B is
raised by the fix is **0 of 83,801** (sidestep run 2026-10-25, every block 0; the fix floor high never exceeds the layout rule-4 floor, which already carries `guidance_physical_floor`). MG-1 therefore sidesteps the skew entirely: MG-1+fix is identical to MG-1 by construction, its contrast is exactly 0 and it cannot be bound. It is still scored, as declared. Outcome-blind checks run before locking: `check` gives 0 floor-weaker and 0 derived-feature violations on 83,798 rows; the fix vector equals the base vector on all 5,333 rows with unchanged inputs (L1 = 0); 7,673 of 83,798 base replays (9.2%) equal the recorded vector within 1e-9.

No date after 2026-09-29 and no MG-1 forward outcome is read.
