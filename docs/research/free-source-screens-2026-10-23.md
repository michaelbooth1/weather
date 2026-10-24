# Free-source screens on the development scorecard (lane G, 2026-10-23)

**Status:** dated research record. Each section's pre-declaration was committed **before** that source
was scored; results are appended below it. Every number is **development** evidence (dates <= 2026-09-29,
already read by earlier lanes); nothing here is confirmation, edge or promotion evidence. A KEEP earns a
pre-registration on new dates (EF §5), nothing more.

- **Owns:** the pre-declared rules, fetch receipts, keep/kill verdicts and unscoreable reasons for the
  free sources screened by lane G (F1-F5 of the
  [information-gap proposal](https://github.com/michaelbooth1/weather/blob/claude/research-information-gap-20261023/docs/research/information-gap-sources-2026-10-23.md)).
- **Read when:** proposing a new free source, the MADIS sign-up, or any paid observation feed.
- **Do not use for:** the scorecard design ([dev scorecard record](dev-scorecard-2026-10-23.md)); measured
  conclusions once landed belong to the findings digest and EF.
- **Owner direction (2026-10-23, via master):** test all free sources now, dev scorecard only, F1 first;
  MADIS sign-up only after F1 shows a gain, and the owner creates that account.

## Common protocol (every source)

- **Scorer:** `python -m weather.reporting.scorecards.dev_scorecard score --layout C:\swarm\v3layout
  --from 2026-08-01 --to 2026-09-29` with the default folds (7-day, gap 1, min 7 train dates; scoring
  starts 08-15), run through `scripts\ops\workstation_heavy.ps1 -Kind weather_heavy` from this worktree.
- **Paired control.** This branch adds `--control-module` / `--control-vectors` to the scorecard: the
  control is scored on the same rows with the same crossed weights (2,000 draws, seed 20260921), so
  `model_minus_control` is the paired increment of the source over its no-source rule. Scoring a source
  only against `served` would credit it with the control's own gain (t3-r3 alone already beats served at
  13-16, EF §10q).
- **Keep/kill bar (pre-declared, owner wording made paired):** KEEP only if, for the targeted block on the
  pooled `ALL` row, the 95% crossed date x market interval of **model − served excludes zero below**
  **and** the interval of **model − control excludes zero below**. Otherwise KILL. The proposal's 5% bar
  (about −0.0012 at 13-16) and MDE80 are reported, not used to keep.
- **Power caveat:** 11 US market clusters (< 12) mean no pooled row is `powered` (EF §10j); a KILL at a
  small effect is "no increment demonstrated", not "no effect".
- **Parity:** a source counts only if a point-in-time equivalent exists at serve. Latency is recorded
  per source; an archive that arrives late is a training proxy and is scored only after degrading it to
  the live product.

## F1: high-frequency ASOS (IEM 1-minute archive), block 13-16

### Pre-declaration (committed before scoring)

- **Control `control_t3r3_metar`** = t3-r3 (EF §10q, `docs/research/model-parity-swarm-2026-10-04/t3.md`):
  R = PIT running max of routine non-COR METAR (half-up T-group F; available = valid + 10 min) on the
  station-local date; P(high = R + e) from the history pmf of e = dmax − R at local H:30 by station x
  target month x local hour; history = local dates <= 2026-07-31 (Aug and Sep of 2024 and 2025);
  complete day >= 20 routine rows; discrete Gaussian smoothing sd 1 F; cells with < 30 days are absent.
  Absent snapshots fall back to served (scorecard rule).
- **Candidate `f1_onemin_hf5c_lat10` (primary)** = the control with R replaced by the fresh running high
  R* = max(R, R_hf). R_hf = running max of the IEM 1-minute archive **degraded to the live product**:
  minutes divisible by 5 only, rounded to whole °C and back to integer F, available = valid + 10 min.
  The history pmf is of e* = dmax − R* built identically (train/serve parity), may be negative, and mass
  below R is folded onto R. A station-day without 1-minute data uses R* = R.
- **Sensitivity `f1u_onemin_m1f_lat2`** (information upper bound, not a serve candidate): every 1-minute
  row, whole F, available = valid + 2 min. Reported only; the verdict is on the primary.
- **Denver:** KBKF publishes no 1-minute archive, so Denver gets R* = R (the control) in both variants.
  KDEN is fetched for the record but is not the settlement station and is not used.
- **Targeted block:** 13-16 local. Other blocks are reported, not decided.
- **Multiplicity:** two rules (primary and sensitivity); one decision (primary).
- **Latency and parity:** the NCEI 1-minute archive arrives 18-36 h late, so **F1 is a training proxy for
  live MADIS 1-/5-minute ASOS**, whose real-time latency and distribution category are unverified. A
  KEEP would justify the owner's MADIS sign-up and a 14-day latency/fill measurement, not serving.

## F3: 12Z soundings (IEM RAOB, nearest upper-air site), block 13-16

### Pre-declaration (committed before scoring)

- **Control:** `control_t3r3_metar` (as F1).
- **Candidate `f3_sounding_cap_gap`:** T_cap = the nearest site's 12Z 850 hPa temperature (700 hPa at
  KDNR) brought dry-adiabatically to the sounding's surface pressure (a full-mixing afternoon cap), in F.
  Gap g = T_cap − R (R = PIT METAR running max) in bins (−inf, 0], (0, 4], (4, 8], (8, inf) F, fixed a
  priori. The t3-r3 pmf is taken from the (station, month, hour, bin) history cell when it has >= 30
  days, otherwise the unconditioned t3-r3 cell. The sounding is used only from valid + 2 h (14:00Z), in
  history and at serve (before 13:00 local in every US market).
- **Sites and distances** (`python -m weather.sources.free_screens.iem_raob sites`): KATL-FFC 32 km,
  KAUS-CRP 268, KORD-DVN 223, KDAL-FWD 43, KBKF-DNR 12, KHOU-LCH 206, KLAX-NKX 169, KMIA-MFL 8,
  KLGA-OKX 86, KSFO-OAK 18, KSEA-UIL 177. Far sites dilute the signal; no site is re-chosen after scoring.
- **Latency/parity:** RAOB is public within about 1-2 h of launch at no cost; the 14:00Z bound is used
  in history and at serve, so parity holds.
- **Targeted block 13-16; one rule; keep/kill bar as in the common protocol.**
