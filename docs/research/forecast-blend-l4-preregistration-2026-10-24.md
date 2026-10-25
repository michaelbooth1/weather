# Lever L4 pre-registration: multi-model forecast blend (2026-10-24)

**Status:** frozen pre-registration, committed (with its sha256 recorded in the results record) before any
L4 result exists. Development evidence only (dates <= 2026-09-29). Results go to
[free-source screens](free-source-screens-2026-10-23.md) § L4; this file is never edited after scoring.

## Rule `l4_blend_invmse` (code: `weather.reporting.scorecards.free_source_candidates.l4_blend_candidate`)

- **Members per snapshot (all point in time):**
  - NBM v2 mean as captured (`v2_mean`, usable when `v2_available_at <= captured_at_utc`);
  - Open-Meteo Previous Runs day-1 highs of `gfs_seamless`, `ecmwf_ifs025`, `icon_seamless`: the max over the 24
    station-local hours of `temperature_2m_previous_day1` (each hour from a run issued about 24-48 h before it,
    so all are issued before the day starts). Fetched by `weather.sources.free_screens.openmeteo_previous_runs`
    for 2026-07-30..09-29 (free API, no key).
- **Fit, per walk-forward fold, on that fold's training snapshots only** (scorecard folds: 7 days, gap 1,
  >= 7 training dates):
  - target y = centre of the settled band (eq: (low + high) / 2; lte: high; gte: low);
  - per station and member, bias b = mean(member − y) (>= 20 snapshots, else the member is dropped);
  - per station x local hour h, weight w ∝ 1 / mean((member − b − y)²) over training snapshots at hours
    h−1, h, h+1 (circular), >= 20 snapshots per member.
- **Serve:** mu = Σ w (member − b) / Σ w over available members; sigma = max(v2_stddev, 1); floor and band
  mapping exactly as MG-1. Covered only where MG-1 covers; a snapshot with no weight cell keeps MG-1.
- **Control:** `control_mg1` (MG-1, `r-t5-inc-c1`). One rule.

## Scoring and decision

- `python -m weather.reporting.scorecards.dev_scorecard score --layout C:\swarm\v3layout --from 2026-08-01
  --to 2026-09-29 --candidate-module l4_blend_candidate.py --control-module control_mg1_candidate.py --hourly`
  through `scripts\ops\workstation_heavy.ps1` (scored 08-15..09-29).
- **Headline block 07-12 local** (pooled `ALL` row). **KEEP** only if the 95% crossed date x market interval
  of L4 − served and of L4 − MG-1 both exclude zero below; otherwise **KILL**.
- Reported, not decisive: per-hour rows h00..h23, the other blocks, and date-clustered intervals (asked for by
  master; EF §5 keeps the crossed interval binding). 11 market clusters: unpowered by construction.
- No parameter, member, hour window or threshold is changed after this file is committed.
