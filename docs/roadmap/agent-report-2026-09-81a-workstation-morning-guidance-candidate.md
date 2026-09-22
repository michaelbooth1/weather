# Workstation handback — morning guidance candidate, mission 2026-09-81a

**NO-GO for confirmation this season under the frozen half-effect power rule.
Both candidates improve descriptive morning Brier, but C1 fails the mission's
minimum-effect falsifier in both strata; neither beats the market.**

Branch: `codex/morning-guidance-candidate-20260921`, based exactly on
`c471b1a98536dd4accf6b49a45bc72c25f539768`
(`origin/codex/nbm-candidate-handoff-20260921`). Implementation/evidence commit:
`1ce031213d0811c4d464eb521d3311d32f6c5826`. This report is the following
documentation commit. Issued 2026-09-21 America/Toronto.

## Frozen order and evidence

[Pre-registration](../research/morning-guidance-candidate-preregistration-2026-09-21.md)
SHA-256 **`d9211fc79d2555bf90f87a42b8d02635cf0c5aeac23390bd1441e398777edc79`**;
freeze commit **`e404f7fdc56fa4e780fd2a829054751ac15b1df6`**.

| Event | Timestamp |
| --- | --- |
| P0 coverage-2 began, with no candidate scorer implemented | 2026-09-21 13:09:02.414964 UTC |
| Freeze commit | 2026-09-21 13:12:50 UTC |
| Exact remote freeze SHA verified and retained in push-receipt.json | 2026-09-21 13:16:37.4830042 UTC |
| First candidate score | **2026-09-21 13:17:21.896494 UTC** |

The freeze was committed, pushed and remotely verified before scoring. It is
unchanged. Every subsequent analysis header binds its hash and freeze commit.
The later bookkeeping rerun added changed-cluster counts, and publication
asserted exact equality of every C1/C2 score, interval and planning result to
the first run. No weight, eligibility rule or candidate changed after scoring.

Retained, reviewable [aggregate evidence](../../tools/research/morning_guidance/evidence.json)
contains all tables, full hour/market/date coverage, per-file source hashes,
planning curves, implementation headers and source-output hashes. Row-level
inputs/deltas remain in ignored scratch. All input bytes come from the existing
79a export, snapshot hash
`249a9de0da7b41cb8a2ce1f07944e4007c585f601028b73acaae0dd4bd141c2e`,
plan hash `024dbac70c636e42c4f514d66d79fb955c75362c6534892954c05d0bc9e33a81`.
No new production data was fetched and no frozen mirror was used.

The export admits 503 promotion-countable market-days and 89,354 snapshots,
42 dates and 12 markets. Morning has 499 days (458 US); four admitted days
have no morning snapshot. The existing 79a excluded dates and seven off-date
rows stay excluded; this is not a claim about today's production settlement
inventory. Reservation status was re-read as **NONE RESERVED**.

## P0 — the missingness is mostly the floor filter

This is a code-and-retained-field trace, not an inference from column names:

1. `model_sources.fetch_live_sources` selects the market's sources and adds NBP for US
   markets with NWS-grid or Open-Meteo multimodel. Toronto is unsupported.
2. `fetch_nbm_probabilistic_tmax` tries current through 24-hour-old cycles,
   shares national bulletin fetches, checks semantic cycle, parses the station
   and requested target, and returns the first available payload. Expected
   403/404 responses continue the search. The source has a 120-minute cache TTL.
3. `parse_nbp_station_tmax` selects the first max slot whose valid UTC time
   minus one day has the requested date; absent station/issue/slot has an
   explicit failure reason. This convention is code, not verified historical
   target correctness in this export.
4. `source_data` requires `ok` and discards explicit `target_date_match=False`.
   `us_guidance_features` compares **each** quantile and mean against the
   observed guidance floor, with 0.9 F / 0.5 C tolerance. Low values are omitted;
   stddev can survive. Partial rejection sets physical-valid=0. With no floor,
   numerical guidance can be marked valid even though floor validity is untested.
5. `feature_store` projects the diagnostics and features; `SnapshotStore`
   writes `features_long.csv` only when a feature vector exists. 79a retained
   numeric fields in extracted-1; P0 rejoined the raw CSV's textual
   `guidance_impossible_features` to identify actual field rejections.

| Population / window | Snapshots | Complete valid NBM | Explicit floor-dropped set | No NBM feature evidence | Complete with guidance floor |
| --- | ---: | ---: | ---: | ---: | ---: |
| US, all hours | 81,430 | 25,835 (31.73%) | 55,565 | 30 | 25,291 |
| US, 06:00–09:59 | 13,584 | 6,293 (46.33%) | 7,290 | 1 | 6,268 |
| All 12, 06:00–09:59 | 14,883 | 6,293 (42.28%) | 7,290 | 1,300 | 6,268 |
| US, 10:00–12:59 | 10,707 | 17 (0.159%) | 10,690 | 0 | 1 |
| All 12, 10:00–12:59 | 11,831 | 17 (0.144%) | 10,690 | 1,124 | 1 |

These are census counts of the supplied export, not uncertain estimates of a
future fetch rate. The evidence's coverage tables include D/M/N for every
hour, market and date. Date-specific rows have D=1 and cannot support crossed
date x market inference. All missing US morning sets except one explicitly
record a dropped NBM field: **the conditional 79a lead is heavily selected by
physical validity.** It does not measure how rejected forecasts would score.

All-market fill by hour before/from Aug 23: hour 6 72.7%/72.7%, hour 7
60.2%/60.2%, hour 8 33.3%/34.0%, hour 9 6.2%/7.2%; hours 10–12 each have
only 1–6 complete rows per stratum. Exact counts are retained in the JSON.

**Correction to one P0 sentence in the immutable pre-registration:** its
statement that the 17 later sets have medians 1.08 F above their floor was
overbroad. The reported min/max silently omitted missing floors: **16 have no
captured floor; only one has a finite floor and that 1.08 F gap.** The corrected
coverage-3 counts floor presence explicitly. The frozen candidate already
required a floor and correctly falls back on those 16; no scoring rule changed.
Twenty-five morning complete sets also have no floor and fall back.

This explains the later selection: almost all US rows lose a quantile to the
floor filter; most rare surviving complete sets escaped that check because
the floor was absent. Their lower temperatures and 79a's bad later scores do
**not** identify stale issue versus next-day/slot error. The export lacks
`source_status_long.csv`, `forecast_payloads_long.csv`, referenced NBP payload
bytes, and the station NBP archive with issue/target/receipt times. Thus
proved never-fetched and wrong-target counts are **unavailable**, not zero.
The 30 all-hour US no-feature rows remain unclassified. No missing file was
retrieved to fill this gap.

Smallest proposed capture change: retain raw quantiles, timestamps/target slot,
payload hash and rejection reasons beside the filtered vector. A separately
reviewed full-raw-CDF-plus-hard-floor route could raise usable coverage;
simply relabelling rejected guidance valid would not. No such change was made.

## P2 — development interpretation and confirmation sizing

The tables below use the exact preregistered equal-market-day estimand:
snapshot means within days, then equal days, without equal-hour reweighting.
Brier is mean binary band loss. Independent date and market multinomial
weights, 2,000 draws, seed 20260921, yield descriptive percentile 95% intervals.
Power/MDE use fixed shifts, not the observed effect; half-observed-effect power
appears only in the explicitly labelled planning scenario. No alpha was spent.

US C1 deltas are -0.006630 and -0.006709. Their intervals exclude zero, but
both gains are smaller than the frozen half-79a thresholds 0.00735 and
0.00738. **The minimum-effect falsifier fires in both strata.** The reported
all-row gain is much smaller than the validity-selected matched gain; the
floor convention and snapshot weighting are also explicit differences from
79a, so the difference is not a causal decomposition of missingness alone.

C2 is better than served, so the proposed shared-error falsifier (worse than
both C1 and served) does not fire. Pooled US C2-minus-C1 is +0.000346
[-0.001237, +0.002016], N=458, D=42, M=11, MDE80 .002282 and fixed -.0075
shift power 1.0: **not distinguishable from zero**. Do not choose/tune a new
pool from this comparison. C1/C2 pooled ratios to market are 1.356/1.362;
the ratio intervals also lie above one. There is no market edge claim.

Morning differs on 6,268 rows, 443 days, 41 dates, 11 markets; all remaining
rows retain served values. The later extension differs on **one snapshot,
one date and one market**. Its before-stratum interval touches zero, and its
from-stratum delta is identically zero. The latter's zero-width empirical
interval provides no rare-event guarantee; power/MDE are unavailable. Fixed
large-shift power of 1.0 on the one-row later change is a sensitivity artifact,
not evidence of a useful later candidate.

Confirmation would begin **2026-09-22**, the day after freeze, with separate
proposed one-sided family alpha .05 (.025 per fixed candidate). At half the
pooled US effects, 45 new dates give only **22.4% / 36.15%** power; retaining
the market bootstrap while letting date N approach infinity gives only
**37.0% / 43.1%**. These are plug-in empirical planning values, Monte Carlo
SE about 0.9 percentage points near 80%, not calibrated guarantees. Both
strata and all-12 also fail. **No finite powered N or completion date is
established under this fixed-market scenario**; scaling all variance by 1/N
would incorrectly erase market uncertainty.

At 12 countable market-days/day, 45 dates would finish **2026-11-05**, yielding
540 all-market days (495 US). Missing countable dates postpone that date.
The observed P0 fill gives about 5.07 all-market / 5.10 US guidance-bearing
snapshot-equivalent market-days per day. These are not independent clusters.
Do not divide N by fill again: fallback has already diluted effect and variance.
All N=2..45 values and the market-only limit are in the evidence.

Exact proposed reservation disposition, as frozen:

> **No reservation is proposed for this season: the frozen two-candidate family
> cannot reach its 80% half-effect planning target within 45 new dates.**

The reservation file and alpha ledger are unchanged. The cheapest independent
alternative is the already-downloaded IEM NBS historical guidance joined
point-in-time to older served dates, under a new preregistration. NBS is a
different deterministic product: it cannot stand in for the missing older
NBP quantile distribution or confirm these exact candidates. No such join,
new candidate, download or score was performed here.

## P3 — placement and validation

[The one-page design](../../tools/research/morning_guidance/DESIGN.md) proposes
a shared full-band-vector stage after current per-band calibration and before
edges and snapshot persistence, used by display, capture and replay callers.
It covers probability mass, native units, the captured floor/cutoff, identical
train/serve application, captured NBP provenance and immutable release binding.
The pure function and synthetic tests live under `tools/research/morning_guidance/`.
No production import or runtime stage was added.

Final focused verification: **115 passed, 11 expected skips** (platform and
outer-lease conditions). Existing 79a probability/extraction controls are
included. New tests cover fallback, complete band support, mass, floor,
duplicate quantiles, fixed 50/50 weights, native-coordinate translation,
day weighting, negative controls and nonshrinking market uncertainty.
Targeted compileall, final docs audit (18 agent files / 896 Markdown files),
roadmap generated-view check and diff checks passed; no full suite was run
for this research-only change. All heavy commands used `workstation_heavy.ps1`.
Temporary pytest trees were removed. One narrow allowlist test initially
failed because it still named only the 79a tool; its exact expected set was
updated with the hook/wrapper pair. A lease-busy retry and a sandbox-principal
refusal stopped before scoring; no gate was relaxed.

## Roll verdict and boundaries

The repository tool returned **UNDECIDABLE: no live closure evidence**, naming
the four absent snapshot/CLOB/observation-trigger/enrichment status files.
Per-file membership in those closures is consequently **unverified for every
changed file below**. The handoff says production returned ROLL-FREE for 79a;
that is not a fresh closure proof for 81a. Production must rerun the tool at
handback. No new production data was fetched for a verdict and no closure was
derived by hand. There are no `src/`, `config/` or `artifacts/` changes.

| Changed path | Tool-derived per-file disposition |
| --- | --- |
| `.codex/hooks/pre_tool_use_host_load.py` | UNDECIDABLE; all live closure memberships unverified |
| `scripts/ops/workload_admission.ps1` | UNDECIDABLE; same |
| `tests/operations/test_codex_host_load_hook.py` | UNDECIDABLE; same |
| `tests/operations/test_missing_information_admission.py` | UNDECIDABLE; same |
| `tests/operations/test_morning_guidance_admission.py` | UNDECIDABLE; same |
| `tests/operations/test_workload_admission_script.py` | UNDECIDABLE; same |
| `tests/reporting/test_morning_guidance.py` | UNDECIDABLE; same |
| `tools/research/morning_guidance/__init__.py` | UNDECIDABLE; same |
| `tools/research/morning_guidance/run.py` | UNDECIDABLE; same |
| `tools/research/morning_guidance/candidate.py` | UNDECIDABLE; same |
| `tools/research/morning_guidance/statistics.py` | UNDECIDABLE; same |
| `tools/research/morning_guidance/score.py` | UNDECIDABLE; same |
| `tools/research/morning_guidance/publish.py` | UNDECIDABLE; same |
| `tools/research/morning_guidance/test_morning_guidance.py` | UNDECIDABLE; same |
| `tools/research/morning_guidance/README.md` | UNDECIDABLE; same |
| `tools/research/morning_guidance/DESIGN.md` | UNDECIDABLE; same |
| `tools/research/morning_guidance/evidence.json` | UNDECIDABLE; same |
| `docs/research/morning-guidance-candidate-preregistration-2026-09-21.md` | UNDECIDABLE; same |
| This report | UNDECIDABLE; same |

**Not done:** no registration, production write, restart, master merge,
Scheduler/capture change, model fit, serving/config/artifact change, alpha
allocation, reservation edit, credential read, exchange call, authenticated
Polymarket access, live order, release promotion or new production fetch.
The explicit handoff exception was used only to admit the exact offline
`tools.research.morning_guidance.run` entry point in the hook and wrapper with
their associated tests. The original checkout and other tasks were preserved.

## Exact workstation reproduction

The following paths exist on this workstation. Outputs are new directories;
use fresh suffixes if a command has already been reproduced. Do not re-extract
or fetch. The original 79a input and every earlier output remain preserved.

```powershell
$repo = 'C:/Users/Michael/Documents/github/weather/scratch/w/morning-guidance-candidate-20260921'
$python = 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe'
$input79 = 'C:/Users/Michael/Documents/github/weather/scratch/missing-information-20260921'
$evidence81 = 'C:/Users/Michael/Documents/github/weather/scratch/morning-guidance-20260921'
function Invoke-MorningResearch([string[]]$Tokens) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
        (ConvertTo-Json -InputObject $Tokens -Compress)))
    & "$repo/scripts/ops/workstation_heavy.ps1" -Kind weather_heavy `
        -PythonPath $python -ArgumentsBase64 $encoded -RepoRoot $repo
    if ($LASTEXITCODE -ne 0) { throw 'Guarded mission command failed' }
}
Invoke-MorningResearch @('-m','tools.research.morning_guidance.run','coverage',
    '--input',"$input79/extracted-1",'--raw',"$input79/unpacked",
    '--output',"$evidence81/reproduce-coverage-1")
Invoke-MorningResearch @('-m','tools.research.morning_guidance.run','score',
    '--input',"$input79/extracted-1",'--raw',"$input79/unpacked",
    '--output',"$evidence81/reproduce-development-1",
    '--push-receipt',"$evidence81/push-receipt.json")
Invoke-MorningResearch @('-m','tools.research.morning_guidance.run','publish',
    '--input',$evidence81,'--output',"$evidence81/reproduce-publication-1")
```

Authoritative run directories are `coverage-2` (pre-freeze P0), `coverage-3`
(floor-count correction), `development-1` (first score), `development-2`
(unchanged scores plus changed-cluster counts) and `publication-1` (aggregate
export). Publication intentionally binds those retained directory names;
the new reproduction score can be compared separately. The scorer verifies
the pinned input bytes, freeze commit/hash and retained pre-score push receipt.

## Complete development tables

Pre-registration SHA-256: `d9211fc79d2555bf90f87a42b8d02635cf0c5aeac23390bd1441e398777edc79`; freeze `e404f7fdc56fa4e780fd2a829054751ac15b1df6`.

All intervals are 95% crossed date x market, 2,000 draws. N = market-days; D/M = date/market clusters.

### morning_06_10

| Population / stratum | Rows; N; D/M | Candidate | Delta [95%] | MDE80; power at -0.0075 | Ratio to market [95%] | Ratio MDE80; power at -0.10 | Changed rows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| US11 / before_20260823 | 6532; 216; 20/11 | C1 | -0.006630 [-0.012544, -0.001806] | 0.007625; 0.781 | 1.3753 [1.2089, 1.5753] | 0.2680; 0.184 | 2967 (45.4225%) |
| US11 / before_20260823 | 6532; 216; 20/11 | C2 | -0.006064 [-0.010084, -0.002942] | 0.005206; 0.992 | 1.3859 [1.2132, 1.5979] | 0.2839; 0.177 | 2967 (45.4225%) |
| US11 / from_20260823 | 7052; 242; 22/11 | C1 | -0.006709 [-0.014069, -0.000971] | 0.009253; 0.588 | 1.3399 [1.1738, 1.5576] | 0.2736; 0.179 | 3301 (46.8094%) |
| US11 / from_20260823 | 7052; 242; 22/11 | C2 | -0.006560 [-0.011503, -0.002741] | 0.006143; 0.948 | 1.3425 [1.1695, 1.5608] | 0.2745; 0.192 | 3301 (46.8094%) |
| US11 / pooled | 13584; 458; 42/11 | C1 | -0.006672 [-0.011525, -0.002373] | 0.006772; 0.882 | 1.3561 [1.2249, 1.5281] | 0.2180; 0.248 | 6268 (46.1425%) |
| US11 / pooled | 13584; 458; 42/11 | C2 | -0.006326 [-0.009902, -0.003145] | 0.004951; 0.997 | 1.3624 [1.2202, 1.5406] | 0.2321; 0.207 | 6268 (46.1425%) |
| all12 / before_20260823 | 7156; 235; 20/12 | C1 | -0.006094 [-0.011670, -0.001630] | 0.007066; 0.851 | 1.3678 [1.2194, 1.5675] | 0.2529; 0.193 | 2967 (41.4617%) |
| all12 / before_20260823 | 7156; 235; 20/12 | C2 | -0.005573 [-0.009319, -0.002556] | 0.004767; 0.999 | 1.3775 [1.2197, 1.5900] | 0.2689; 0.177 | 2967 (41.4617%) |
| all12 / from_20260823 | 7727; 264; 22/12 | C1 | -0.006150 [-0.012847, -0.000909] | 0.008525; 0.676 | 1.3324 [1.1689, 1.5254] | 0.2558; 0.183 | 3301 (42.7203%) |
| all12 / from_20260823 | 7727; 264; 22/12 | C2 | -0.006013 [-0.010295, -0.002431] | 0.005691; 0.976 | 1.3348 [1.1668, 1.5312] | 0.2641; 0.173 | 3301 (42.7203%) |
| all12 / pooled | 14883; 499; 42/12 | C1 | -0.006123 [-0.010990, -0.002203] | 0.006154; 0.941 | 1.3486 [1.2224, 1.5149] | 0.2022; 0.272 | 6268 (42.1152%) |
| all12 / pooled | 14883; 499; 42/12 | C2 | -0.005806 [-0.009351, -0.002800] | 0.004643; 1.000 | 1.3544 [1.2237, 1.5256] | 0.2136; 0.246 | 6268 (42.1152%) |

### secondary_10_13

| Population / stratum | Rows; N; D/M | Candidate | Delta [95%] | MDE80; power at -0.0075 | Ratio to market [95%] | Ratio MDE80; power at -0.10 | Changed rows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| US11 / before_20260823 | 5144; 219; 20/11 | C1 | -0.000010 [-0.000058, 0.000000] | 0.000038; 1.000 | 1.4925 [1.2846, 1.7723] | 0.3435; 0.112 | 1 (0.0194%) |
| US11 / before_20260823 | 5144; 219; 20/11 | C2 | -0.000007 [-0.000043, 0.000000] | 0.000029; 1.000 | 1.4926 [1.2846, 1.7723] | 0.3434; 0.112 | 1 (0.0194%) |
| US11 / from_20260823 | 5563; 242; 22/11 | C1 | 0.000000 [0.000000, 0.000000] | unavailable; unavailable | 1.4489 [1.2892, 1.6410] | 0.2554; 0.195 | 0 (0.0000%) |
| US11 / from_20260823 | 5563; 242; 22/11 | C2 | 0.000000 [0.000000, 0.000000] | unavailable; unavailable | 1.4489 [1.2892, 1.6410] | 0.2554; 0.195 | 0 (0.0000%) |
| US11 / pooled | 10707; 461; 42/11 | C1 | -0.000005 [-0.000027, 0.000000] | 0.000018; 1.000 | 1.4693 [1.3240, 1.6571] | 0.2376; 0.201 | 1 (0.0093%) |
| US11 / pooled | 10707; 461; 42/11 | C2 | -0.000003 [-0.000021, 0.000000] | 0.000014; 1.000 | 1.4693 [1.3241, 1.6571] | 0.2375; 0.201 | 1 (0.0093%) |
| all12 / before_20260823 | 5699; 239; 20/12 | C1 | -0.000009 [-0.000053, 0.000000] | 0.000035; 1.000 | 1.4833 [1.2929, 1.7538] | 0.3275; 0.115 | 1 (0.0175%) |
| all12 / before_20260823 | 5699; 239; 20/12 | C2 | -0.000007 [-0.000040, 0.000000] | 0.000026; 1.000 | 1.4834 [1.2929, 1.7538] | 0.3272; 0.116 | 1 (0.0175%) |
| all12 / from_20260823 | 6132; 264; 22/12 | C1 | 0.000000 [0.000000, 0.000000] | unavailable; unavailable | 1.4352 [1.2756, 1.6120] | 0.2405; 0.222 | 0 (0.0000%) |
| all12 / from_20260823 | 6132; 264; 22/12 | C2 | 0.000000 [0.000000, 0.000000] | unavailable; unavailable | 1.4352 [1.2756, 1.6120] | 0.2405; 0.222 | 0 (0.0000%) |
| all12 / pooled | 11831; 503; 42/12 | C1 | -0.000004 [-0.000025, 0.000000] | 0.000017; 1.000 | 1.4577 [1.3259, 1.6369] | 0.2184; 0.226 | 1 (0.0085%) |
| all12 / pooled | 11831; 503; 42/12 | C2 | -0.000003 [-0.000019, 0.000000] | 0.000013; 1.000 | 1.4578 [1.3259, 1.6369] | 0.2185; 0.226 | 1 (0.0085%) |

### Absolute Brier and changed-share intervals

The changed-share estimand below equally weights market-days; the raw snapshot share above is a finite-export count.

| Window / population / stratum | Served Brier [95%] | Market Brier [95%] | C1 Brier [95%] | C2 Brier [95%] | Changed day-weighted share [95%] | Share MDE80; power at +.10 | Changed N; D/M |
| --- | --- | --- | --- | --- | --- | --- | --- |
| morning_06_10 / US11 / before_20260823 | 0.079613 [0.072274, 0.086894] | 0.053068 [0.045727, 0.060702] | 0.072983 [0.065472, 0.080213] | 0.073549 [0.066125, 0.080853] | 0.44969 [0.28845, 0.61653] | 0.23119; 0.237 | 206; 19/11 |
| morning_06_10 / US11 / from_20260823 | 0.081841 [0.073376, 0.090123] | 0.056075 [0.049507, 0.063333] | 0.075132 [0.067506, 0.083590] | 0.075281 [0.067702, 0.083335] | 0.47001 [0.29926, 0.62978] | 0.23357; 0.223 | 237; 22/11 |
| morning_06_10 / US11 / pooled | 0.080790 [0.074713, 0.087545] | 0.054657 [0.049414, 0.060026] | 0.074118 [0.068039, 0.081474] | 0.074464 [0.068419, 0.081809] | 0.46043 [0.28580, 0.61547] | 0.23505; 0.215 | 443; 41/11 |
| morning_06_10 / all12 / before_20260823 | 0.079166 [0.072502, 0.086237] | 0.053423 [0.046610, 0.060697] | 0.073072 [0.066656, 0.079876] | 0.073593 [0.067101, 0.080556] | 0.41334 [0.24640, 0.57784] | 0.23672; 0.224 | 206; 19/11 |
| morning_06_10 / all12 / from_20260823 | 0.080817 [0.072963, 0.088593] | 0.056041 [0.050051, 0.062751] | 0.074667 [0.067296, 0.082586] | 0.074803 [0.067666, 0.082340] | 0.43084 [0.25939, 0.59100] | 0.23904; 0.209 | 237; 22/11 |
| morning_06_10 / all12 / pooled | 0.080039 [0.074219, 0.086599] | 0.054808 [0.049616, 0.059612] | 0.073916 [0.068032, 0.080393] | 0.074233 [0.068542, 0.080819] | 0.42260 [0.25523, 0.58203] | 0.23747; 0.210 | 443; 41/11 |
| secondary_10_13 / US11 / before_20260823 | 0.075098 [0.068395, 0.081220] | 0.050309 [0.042530, 0.058470] | 0.075088 [0.068395, 0.081216] | 0.075090 [0.068395, 0.081218] | 0.00019 [0.00000, 0.00114] | 0.00076; 1.000 | 1; 1/1 |
| secondary_10_13 / US11 / from_20260823 | 0.075290 [0.067682, 0.081961] | 0.051964 [0.045391, 0.058597] | 0.075290 [0.067682, 0.081961] | 0.075290 [0.067682, 0.081961] | 0.00000 [0.00000, 0.00000] | unavailable; unavailable | 0; 0/0 |
| secondary_10_13 / US11 / pooled | 0.075199 [0.070396, 0.080001] | 0.051178 [0.045349, 0.056592] | 0.075194 [0.070387, 0.080001] | 0.075195 [0.070389, 0.080001] | 0.00009 [0.00000, 0.00054] | 0.00036; 1.000 | 1; 1/1 |
| secondary_10_13 / all12 / before_20260823 | 0.075647 [0.069555, 0.081399] | 0.050993 [0.042979, 0.058748] | 0.075638 [0.069550, 0.081399] | 0.075640 [0.069551, 0.081399] | 0.00017 [0.00000, 0.00104] | 0.00069; 1.000 | 1; 1/1 |
| secondary_10_13 / all12 / from_20260823 | 0.075297 [0.069102, 0.081352] | 0.052464 [0.046454, 0.058402] | 0.075297 [0.069102, 0.081352] | 0.075297 [0.069102, 0.081352] | 0.00000 [0.00000, 0.00000] | unavailable; unavailable | 0; 0/0 |
| secondary_10_13 / all12 / pooled | 0.075463 [0.070648, 0.079945] | 0.051765 [0.046064, 0.056766] | 0.075459 [0.070644, 0.079945] | 0.075460 [0.070645, 0.079945] | 0.00008 [0.00000, 0.00050] | 0.00033; 1.000 | 1; 1/1 |

### Half-effect planning, morning

No cell below attains 80% in the frozen planning scenario. Alpha .025 one-sided per candidate; not a spend.

| Population / stratum | Candidate | Half effect | Power at 45 dates | Infinite-date market-only power | N / end date |
| --- | --- | --- | --- | --- | --- |
| US11 / before_20260823 | C1 | 0.003315 | 0.259 | 0.508 | unavailable / no finite date established |
| US11 / before_20260823 | C2 | 0.003032 | 0.366 | 0.569 | unavailable / no finite date established |
| US11 / from_20260823 | C1 | 0.003354 | 0.139 | 0.190 | unavailable / no finite date established |
| US11 / from_20260823 | C2 | 0.003280 | 0.281 | 0.327 | unavailable / no finite date established |
| US11 / pooled | C1 | 0.003336 | 0.224 | 0.370 | unavailable / no finite date established |
| US11 / pooled | C2 | 0.003163 | 0.361 | 0.431 | unavailable / no finite date established |
| all12 / before_20260823 | C1 | 0.003047 | 0.244 | 0.469 | unavailable / no finite date established |
| all12 / before_20260823 | C2 | 0.002787 | 0.363 | 0.494 | unavailable / no finite date established |
| all12 / from_20260823 | C1 | 0.003075 | 0.146 | 0.206 | unavailable / no finite date established |
| all12 / from_20260823 | C2 | 0.003007 | 0.264 | 0.328 | unavailable / no finite date established |
| all12 / pooled | C1 | 0.003062 | 0.190 | 0.399 | unavailable / no finite date established |
| all12 / pooled | C2 | 0.002903 | 0.326 | 0.451 | unavailable / no finite date established |
