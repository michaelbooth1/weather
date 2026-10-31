# Forward P0 family on the recorder sources: pre-registration draft (NOT frozen), lane L3, 2026-10-31

Status: DRAFT for the coordinator, who takes it to master. It is not frozen and has no ledger row, because nothing
is computed from data. The power figures below are arithmetic on intervals already in the register, plus date counts.

Data reads behind this draft:
- No outcome, price or label is read.
- Recorder outputs were checked for presence only (directory and file counts, the process list and the logon tasks).
  No recorded value was opened.

MOS-NAM is excluded per master.

## 1. Recorder presence (2026-10-30 22:53 local, counts only)

| Source | Recorder | Output | Presence |
| --- | --- | --- | --- |
| Open-Meteo Previous Runs | L8, `claude/om-prev-runs-recorder-20261030` @ `dd1afc70270c39bb1eb78de48b9a08e326f3c04a` | `C:\t\om_prev_runs\forward` | running; day dirs 20261030, 20261031; 12 files |
| ECCC Datamart HRDPS/RDPS/GDPS/GEPS (CYYZ) | L13, `ac447ebe0650e1c51ffceffe0fafde177d3dc322` | `C:\t\eccc_gem\forward` | running; only `rdps` present (11 files); **HRDPS 0 fetches**; runs from 10-31 00Z |
| DWD MOSMIX L/S | L13, `claude/mosmix-recorder-20261029` @ `e505a3b17cbd8b439f43d2c27e34580d9850284f` | `C:\t\mosmix\forward` | running; 170 files from 10-29 |
| NBM text NBH/NBS/NBE/NBP | L13, `claude/nbm-text-recorder-20261030` @ `c3d0a9499247c62898143607ab76cc45f23b170c` | `C:\t\nbm_text\forward` | running; 61 files from 10-30 |
| ECMWF ENS mx2t3 50 members | L13, `claude/ecmwf-ens-recorder-20261030` @ `4fc2b71198fd06c5e6b9ff5ec48076109f31ca1e` | `C:\t\ecmwf_ens\forward` | running; no run dirs yet (first run 10-31 00Z) |

## 2. Arms: S0 reason and kill check (by name and family)

| Arm | S0 reason (written first) | Kill check | Disposition before power |
| --- | --- | --- | --- |
| **A1 OM-REV**: run-to-run revision of the target-day forecast high, `temperature_2m` − `temperature_2m_previous_day1` (per model, receipt-dated `fetched_at_utc` <= t_c), type D, 07-12, 12 markets | Prices may anchor on the run traders last saw. A revision known by the morning, but not yet absorbed, would predict the market's error. A well-calibrated forecast's revisions are near-martingale, so the **prior is low**. | Not killed by name. **Rows 79/80:** row 79 (X66-X70) is tracking (obs − forecast at the obs time), not revision; it shares the OM HRRR series only. Row 81 could not test drift (no dated run record; this recorder's purpose). Row 80 is the RISE-T3R3 replication: under owner Q3 = no it **claims the first 45 forward T+0 dates** (13-16), with its look after MG-1 and B-1. That is a rule-9 claim on the same calendar, so the counts below assume its look is done by 12-15. Nearest family: S17 NWS revisions TESTED-NO-INCREMENT (vs the model, placebo beat it, T12); S15 OM Previous Runs TESTED-UNDERPOWERED x3 as model inputs (88a/100h/90a, EF §1m). Neither is against the market. | eligible (low prior) |
| **A2 HRDPS/RDPS Toronto** (Datamart point Tmax at CYYZ, 07-12) | The only native Toronto guidance at 2.5/10 km. Would unblock row 90's BLOCKED clause. | X80 (GEM-SEAMLESS via OM, Toronto, wrong-signed) and X81 are the same family on a different feed. **Conditional:** HRDPS has 0 fetches. | conditional |
| **A3 MOSMIX °C markets** (TX/TTT at the station point, 07-12) | Station MOS from DWD, outside the US-centric guidance traders watch. | Not killed by name. The only °C built-in market is Toronto (71624, 1.0 km, good match). | eligible |
| A4 NBM text | none new | NBM all hours closed (row 14, EF §10p); X30 NBH remaining max; X58 NBM-SKEW; X64/X65 Toronto NBM. NBP percentile spread is spread information, COVERED (X5 reopen; X54/X55, X75). **NBM freshness is L8's** (coordinator deconflict). | **DROPPED (no new reason; freshness is L8's)** |
| A5 ECMWF ENS non-spread | none new | The recorder holds only member mx2t3 maxima. Any non-spread field (member quantiles, exceedance probabilities) is a function of their location and scale. The mean is null (X5, EF §10y) and spread is COVERED (X5 reopen). | **DROPPED (no new reason)** |

## 3. (f) power check (rule 9, per date)

### Countable dates

Freeze is about 11-02, so D0 is 11-03. Readable dates under rule 9 (L8's lever map, 10-31):
- at 12-15: **N = 39**, dates 11-03..12-11. PT-1 claims 12-12 onward.
- at 01-26: **N = 84**, dates 11-03..01-25.

Both are upper bounds. A missing recorder day lowers them.

### SE and effect of interest

- **Statistic.** The rule_mr_sweep §5 paired Δ = ρ_c − mean ρ_pl. Survival needs the lower 95% bound > 0, so power
  is Φ(E / SE_N − 1.96).
- **SE_N.** SE_N = SE_dev × √VIF × √(n_dev / N), with VIF floor 1.78. The dev SE is backed out of the sibling's
  recorded interval (width / 3.92):
  - X77 MOS-NAM 07-12, 11 markets: 0.02276. This is the smallest 07-12 sibling, and is generous.
  - X76 MOS-GFS: 0.02883.
  - X80 Toronto GEM, 46 dates: 0.08033.
- **Effect of interest.** None of the arms has a dev point. E = **+0.0378** is the best 07-12 point on this statistic
  (X77, BH-rejected, winner's-cursed), and E/2 is also reported (f4). This is generous to every arm.

### Results

| Arm | SE source | Power at E, N 39 / 84 | Power at E/2, N 39 / 84 | E with power 0.5, N 84 | N80 at E | Result |
| --- | --- | --- | --- | --- | --- | --- |
| A1 OM-REV (12 markets) | X77 | 0.22 / **0.41** | 0.09 / 0.14 | 0.043 | 218 | **DROPPED (< 0.5)** |
| A1 OM-REV | X76 | 0.15 / 0.28 | 0.07 / 0.10 | 0.054 | 349 | DROPPED |
| A1 OM-REV, all hours 00-23 (variant) | X46-X49 OM, SE ≈ 0.0049; E = +0.0046 (X48 OM-NAM, best OM all-hours point) | ≈ 0.10 / 0.16 | — | — | — | DROPPED |
| A2 HRDPS/RDPS Toronto | X80 | 0.05 / 0.07 | 0.04 / 0.04 | 0.155 | 2,903 | **DROPPED (< 0.5; also conditional)** |
| A3 MOSMIX Toronto | X80 | 0.05 / 0.07 | 0.04 / 0.04 | 0.155 | 2,903 | **DROPPED (< 0.5)** |
| A3 variant: MOSMIX on its 8 good-match markets (not briefed; Dallas/Denver/Houston poor, Austin coordinates stale) | X77 × √(11/8) | 0.17 / 0.32 | 0.07 / 0.11 | 0.050 | 299 | DROPPED |

## 4. Result of the draft

**No arm reaches power 0.5 at either readable date, under the most generous SE and effect available. The family is
empty after the pre-freeze drop, so the recommendation is: do not freeze.**

Nothing is lost by not freezing:
- the recorders keep accruing;
- no outcome is read;
- a later rule can still claim these dates blind.

N80 at the generous effect is at least 218 dates for the best arm, a mid-2027 readability.

If master wants a family anyway, the frozen text would carry what the standing rule requires:
- BH q 0.10 over the surviving arms;
- the three-control rule: w = 0 identity, reproduction, and synthetic ± with its negation;
- per-date rows;
- VIF floor 1.78;
- the (g) futility looks.

Its pre-stated verdict would be SCREEN, never POWERED.
