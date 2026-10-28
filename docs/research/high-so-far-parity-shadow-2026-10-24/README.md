# L8: high_so_far train/serve parity, shadow variant (2026-10-24/25)

Status: development record (dates 2026-08-15..09-29 only). It is not confirmation, edge or promotion
evidence. Branch `claude/high-so-far-parity-shadow-20261024`. Do not rewrite this record; add dated addenda.

## What was built

- **Shared definition.** `weather.model.observed_running_max.running_max_since_midnight(station, metar, *,
  target_date, tz, unit, cutoff_hour, now=None) -> (max, first_minute)`. This is the trainer's `high_so_far`:
  the maximum over captured METAR/station rows whose observation instant falls on the target local date, at or
  before `cutoff_hour:00`. The instant is taken from `obsTime` or the raw `DDHHMMZ` group, so the D-1 report
  carried in as the `00:00` row is excluded. The shadow serve path and offline replays (MG-2 arm A, lane L3)
  both call this one function.
- **Shadow switch.** `high_so_far_shadow_variant = "metar_running_max_since_midnight_v1"` lives in
  `weather.model.model_base`.
  - It replaces the HGB feature, and `hours_at_peak` follows it.
  - The floor high becomes `max(served, running max)`.
  - Production keeps `None`, and a test proves the production path never reaches the new code.
- **Scorer.** `weather.calibration.high_so_far_parity_shadow` provides `emit`, `sidestep`, `check` and `score`.
  It is admitted to the workstation offline allowlist and refuses to import on the capture host.

## Pre-registration

The rule is [rule.md](rule.md), sha256 `55cf69892204bc72243cda3a5551a0e90b54dca513541d0c88a2562a779ddcae`.
- It passed `prereg_check`.
- It was committed at `2b4220583` before any score existed.
- The loss atlas it cites is `46a66f7b7727`.

## Outcome-blind checks (before scoring)

- **Replay:** 83,798 snapshots across 11 markets × 46 folders, with 0 errors.
- **Replay positive control:** the fix vector equals the base vector on all **5,333 of 5,333** rows whose
  `high_so_far` features and floor are unchanged (L1 = 0). Separately, 7,673 of 83,798 base replays (9.2%)
  reproduce the recorded vector within 1e-9, as EF 10v expects for current code.
- **Derived features:** across 83,798 rows (`high_so_far` changed on 24,805), there are 0 violations. The
  floor is never weaker, and `forecast_gap` and `live_reading_minus_high` move by exactly −Δhigh_so_far.
- **MG-1 sidestep:** **0 of 83,801** MG-1 snapshots have their floor bucket raised. MG-1's centre is the NBM
  v2 mean, and its rule-4 floor already carries `guidance_physical_floor`, which is at or above the METAR
  running max. So MG-1 does not see the skew, and MG-1+fix is identical to MG-1.

## Result (score `9e7d2c7f94ce`; dR date-clustered, 43 dates × 11 markets, 2,000 draws)

Controls passed:
- served R 1.774 / 1.526;
- the MG-1 reimplementation equals lane G's frame;
- MG-1 − served 00-12 = −0.0153;
- above-settlement floor rows: 15 in base and 15 in fix, so **0 new**.

| block | dR fix − base [95%] | dR fix − served | dR fix − MG-1 |
| --- | --- | --- | --- |
| 00-05 | −0.0115 [−0.0228, −0.0012] | −0.0135 [−0.0254, −0.0025] | +0.2814 [+0.2116, +0.3470] |
| 06-09 | −0.0173 [−0.0327, −0.0020] | −0.0191 [−0.0346, −0.0038] | +0.2778 [+0.2029, +0.3516] |
| 07-12 | −0.0075 [−0.0165, +0.0017] | −0.0080 [−0.0167, +0.0015] | +0.2513 [+0.1784, +0.3222] |
| 10-12 | −0.0008 [−0.0073, +0.0065] | −0.0000 [−0.0078, +0.0089] | +0.2221 [+0.1464, +0.2955] |
| 13-16 | +0.0048 [−0.0018, +0.0117] | −0.0939 [−0.1454, −0.0457] | −0.0575 [−0.2092, +0.0752] |
| **00-16** | **−0.0088 [−0.0171, −0.0008]** | −0.0238 [−0.0357, −0.0113] | +0.2232 [+0.1489, +0.2927] |
| all | −0.0092 [−0.0172, −0.0012] | −0.2358 | −0.0467 [−0.1450, +0.0470] |

**Verdict under the locked rule:**
- The parity fix is **KEEP** against base: the 00-16 interval excludes 0 and no standard block is harmed.
- It is **NOT BOUND** as MG-2: no arm beats MG-1 at 00-16. HGB+fix is +0.22 R worse than MG-1, and
  MG-1+fix equals MG-1.

**Caveats:**
- The crossed interval for 00-16 fix − base is [−0.0232, +0.0058] and crosses 0.
- 00-16 dBrier is −0.00043. Date-clustered MDE80 is 0.0115 at power 0.44.
- The effect is a real but small correction, about 0.6% of R, and smaller than the expected-size ceiling in
  rule (c).

**Hour detail:**
- The gain sits at 05-07 h: h05 −0.029, h06 −0.031, h07 −0.035, all with intervals excluding 0.
- 15-17 h shows harm: h15 +0.017 [+0.007, +0.027], h16 +0.017, h17 +0.022.
- The harm follows from the trainer's definition. At an h:55 snapshot with cutoff h, the h:52 report is
  excluded from `high_so_far`, while the served value included it. Training-exact parity costs a little in
  the afternoon, where the served value carried fresher information.

**Per market (00-16 fix − base):**
- Intervals exclude 0 for Dallas (−0.042) and Denver (−0.023).
- NYC (+0.025) and Chicago (+0.010) lean the other way, with intervals that cross 0.

## Roll class

**ROLL-SENSITIVE.** The closure trace at master `87af8ed8b` and the branch tip puts `model_base.py`,
`model_features.py` and `model_distribution.py` in the capture closure through `weather.collection.
snapshot_tracker` → `weather.model.toronto_model`. Those files run only with the shadow switch off in
production, but the fingerprint is over the files. The new `observed_running_max.py` is imported lazily, only
under the switch. The research module is outside the closure. Master's `roll_verdict.ps1 -Branch` decides;
landing goes through the 01:00-04:00 quiet window (`quiet_window_merge.ps1`).
