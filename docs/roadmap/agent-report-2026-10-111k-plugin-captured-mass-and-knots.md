# 111k — weather plugin: tied NBP knots, identity inside the universe, captured-set mass, forecast gaps

**PASS (fixtures and one tracked public bulletin) for the four asks. The plugin still does not land
until the production re-run below passes the owner's bar. No production data was read here, and no
real-data, economic or live-readiness result is claimed.**

- **(b) `nonincreasing_percentile_knots` was a defect, now fixed.** Traced on a real bulletin: NBP prints
  whole degrees, so adjacent percentiles of a narrow forecast round to the same value (KAUS
  2026-09-17 01Z: P75 = P90 = 100 F). The parser refused every tie. Ties are now atoms of the same CDF.
  No knot in the tracked bulletins decreases.
- **(a) The band-identity check now lives in `WeatherUniverse.bands`.** It covers every caller
  (descriptors, fair value, clock, settlement), not only the runner.
- **(c) The owner's mass bar is computed and shown first in `report.md`.** Mass is judged over the
  band set 88a captures, with the all-band count beside it.
- **(d) The 1,584 missing forecasts are most likely genuine gaps, not a lookup bug.** The size
  matches each NBP cycle being captured about 40 minutes after the pre-registered expiry of the
  previous cycle. This is an inference from arithmetic; the re-run now classifies every instance and
  measures the capture lateness of every cycle, which decides it.

Mission 111k came from the owner's dispatch prompt of 2026-10-01; there is no handoff file. Its
facts come from the production re-run of `ad041d6d` on 2026-09-26 data
(`data/alerts/weather-plugin-111j-20260926/`):

- `end_to_end.lead1` 2,512 and lead2 2,539;
- `band_identity_mismatch` 0;
- partial mass on all 9,268 records, from `descriptor:book_not_captured` 24,615,
  `fair_value:nonincreasing_percentile_knots` 7,325 and `fair_value:missing_point_in_time_forecast` 1,584;
- 0 legs.

Those are the production agent's figures. This workstation did not read them.

## (b) Non-increasing knots: one real instance, bulletin text to knots

Source: `tests/fixtures/nbm_target_fix/20260917T01Z-KAUS.txt`. This is a tracked, byte-pinned
public NOAA bulletin (`sha256.json`), not production data. Its rows, verbatim (first three groups):

```text
KAUS    NBM V5.0 NBP GUIDANCE    9/17/2026  0100 UTC
UTC    00  12| 00  12| 00  12| ...
FHR    23  35| 47  59| 71  83| ...
TXNP1  97  71| 97  66| 97  69| ...
TXNP2  98  72| 98  68| 98  71| ...
TXNP5  99  73| 99  71| 99  72| ...
TXNP7 100  74|100  73| 99  74| ...
TXNP9 100  75|100  74|101  75| ...
```

The trace, step by step:

1. **Issue.** The parser reads `9/17/2026 0100 UTC`. At issue it is 9/16 20:00 CDT, so target 9/17 is T+1.
2. **Slot.** `slot_for_target_v2` picks group 0, token 0, FHR 23. That is valid 9/18 00Z: 9/17 19:00
   CDT, and 07:00 CDT 12 hours earlier, so it is the 9/17 maximum. This slot is correct (82a's fix).
3. **Rows.** `parse_pair_row` splits on `|` and reads at most two numbers per group, so
   `TXNP7 100  74|` gives (100, 74) and `TXNP9 100  75|` gives (100, 75). Fixed-width fusion cannot
   occur: the first field is 3 wide and the second 4 wide.
4. **Knots.** At the slot the knots are (97, 98, 99, 100, 100). The old rule
   `any(a >= b ...)` raised `nonincreasing_percentile_knots`.

So the cause is the refusal rule, not the parse. The rows were read correctly; the values tie because
NBP rounds each percentile to a whole degree. Across all 44 tracked bulletins (4 cycles × 11 stations):

| Set | Strictly increasing | Tied | Decreasing |
| --- | ---: | ---: | ---: |
| All 396 complete 00Z (maximum) columns | 336 | 60 | 0 |
| The T+1 slot of each bulletin | 28 | 16 | 0 |
| The T+2 slot of each bulletin | 31 | 13 | 0 |

So 30-36% of T+1/T+2 reads were refused before this fix. On 09-26, production refused 7,325 of
about 13,960 lead-1/2 fair-value attempts (the 2,512 + 2,539 successes, the 7,325 refusals and the
1,584 missing forecasts). That is a higher share, on a different date and set of stations; it is
consistent with, not a reconciliation of, the same cause.

**Fix.** Ties are atoms of the same piecewise-linear CDF. This is the reading the 79a measurement used
(`tools/research/missing_information/methods.py`: "Equal quantiles represent atoms"):

- `nbp.parse` refuses only a decrease, as `decreasing_percentile_knots`.
- `percentile_cdf` is right-continuous and jumps at a tied knot.
- A tied first or last segment is vertical, so that tail's mass sits on the atom. This is the
  limit of the pre-registered linear tail extension.
- Band edges are half degrees and knots whole degrees, so no edge ever meets an atom.

Strictly increasing knots give exactly the frozen 110b values. A test checks 122 points against the
verbatim 110b function, and those reads keep `model_id` `nbp-v2-piecewise-linear`. Any tie is
labelled `nbp-v2-piecewise-linear-atoms`, counted as `fair_value_model.lead<N>.<id>`.

The T+1 pre-registration forbids editing its frozen text, so the change is
[Amendment 1](../research/t1-fair-value-preregistration-2026-09-25.md#amendment-1--2026-10-01-mission-111k-before-scoring-owner-decision).
It cites the owner's 2026-10-01 decision and was written before any result was read.

**Hand-checked T+1 fair value (this bulletin, by hand, also asserted in a test).** Knots
(97, 98, 99, 100, 100). The CDF at each band edge:

| Edge | Calculation | F |
| --- | --- | ---: |
| 96.5 | .10 − .5 × .15 | .025 |
| 97.5 | .10 + .5 × .15 | .175 |
| 98.5 | .25 + .5 × .25 | .375 |
| 99.5 | .50 + .5 × .25 | .625 |
| 100.5 | the last segment is vertical | 1 |

So the bands get ≤96: .025, 97: .15, 98: .20, 99: .25, 100: .375, ≥101: 0. The sum is 1.

A side effect: `WeatherInformationClock` skipped tied cycles (it swallows parse errors). Those
bulletins now produce their model-cycle `widen` events.

## (a) Identity check moved into `WeatherUniverse`

Before, the runner checked `identity_matches` itself, and the per-pair token check sat in `discover`.
`WeatherFairValue`, `WeatherInformationClock` and `WeatherSettlement` call `universe.bands()` directly,
so any caller other than the runner could use a later token batch unchecked.

Now `bands()` verifies a condition-identity batch on every call. It uses the latest discovery the
universe holds at or before the minute:

- no such discovery → `band_identity_unverified`;
- other contracts → `band_identity_mismatch`;
- a point-in-time band capture still needs no discovery and wins.

`discover`/`describe` verify once per event. `describe` builds only the requested condition, so an
unbooked sibling cannot refuse it. Descriptors are unchanged.

In the runner, one descriptor universe per event-minute replaces one per band. It holds the full
point-in-time event and that minute's books. The shared provider universe receives each event's
replayed discovery through `observe_discovery`: one capture per content change, which gives the same
verdict as keeping every capture, since only the content is compared.

## (c) The owner's bar, computed

A band is in **88a's captured set** when both token books exist at or before the minute
(`captured_by_88a` per band). Each record gets `probability_mass.captured_set`. Its class is
`complete_unit_mass` when all three hold:

- every captured band has a fair value;
- all of those fair values come from one joint over the full event partition;
- that joint sums to one.

Otherwise the class is `partial`, `complete_without_one_joint`, `complete_nonunit_mass` or
`no_captured_bands`. The record also reports the captured bands' marginal sum, which is below one
whenever an unbooked band holds mass.

The summary adds `captured_set_mass` (by lead), `captured_set_reasons` (the reasons on captured bands
only) and, beside them, `all_band_mass` (by lead). `mass_coverage` is unchanged.

`summary.verdict` is the **first section of `report.md`**. It states, for example: "Exam-line plugin
bar: PASS. Captured-set mass: complete with unit mass on X of Y lead-1 records that have captured
bands (Z at lead 2). All-band mass (every listed band, reported beside it): complete on A lead-1
records and B records in total." It then lists each check:

- status COMPLETE;
- `end_to_end.lead1` > 0;
- `band_identity_mismatch` = 0;
- `band_identity_unverified` = 0;
- lead-1 captured-set complete unit mass > 0.

The hand check stays manual, and the verdict says so.

Each NBP fair value now also carries `nbp_read`, outside the input digest: the national blob hash,
issue, slot, knots and band edges. A test recomputes every view from it.

## (d) The 1,584 missing point-in-time forecasts

What the code allows:

- The NBP read requires an issue whose availability window contains the minute:
  `issue <= t < valid_until(issue)`. `valid_until` is the next cycle + 1 hour, capped at 24 hours.
  This is pre-registered: "Already expired issues are not revived by a late fetch."
- The fallback needs a lead-one `forecasts_long` daily-high row in the event's own folder. That folder
  is empty before the event's local day under T+0-only capture (111j). So for T+1/T+2, every minute
  after an issue expires and before the next cycle is captured is `missing_point_in_time_forecast`.

Ruled out as lookup bugs:

- **The pooled lookup finds the T+0-folder copy** (111j test).
- **Every tracked cycle (01/07/13/19Z, 11 stations) holds both the T+1 and T+2 maxima** (88 of 88
  reads above). So "cycle lacks target" cannot explain the count.
- **The 48-hour lookback and run-date bounds cover every eligible issue.**

The size fits capture lateness. 1,584 is about 11% of the ~13,960 lead-1/2 attempts. With four cycles
a day, that is ~40 minutes per cycle in which the previous issue has expired and the next is not yet
captured. In other words, each cycle is captured about 1 h 40 min after its nominal time, against the
1-hour allowance. The snapshot loop fetches the newest published cycle on its own cadence, and the
manifest capture also bounds availability, so this is plausible. **It is an inference from
arithmetic, not a measurement.**

The re-run now decides it. Each missing instance carries `forecast_gap`, counted as
`missing_forecast.lead<N>.<gap>`:

| Gap | Meaning |
| --- | --- |
| `expired_next_cycle_fetched_late` | Genuine: the next cycle arrived late |
| `expired_next_cycle_not_captured` | Genuine: a cycle is missing from capture |
| `fetched_after_expiry` | Genuine |
| `no_cycle_with_target` | Would point at the slot rule or the bulletin |
| `no_bulletin` | Would point at the pool lookup: a bug if any lead-1/2 band shows it while T+0 has bulletins |

Every pooled cycle's earliest capture is also counted against its expected availability
(`nbp_capture_vs_expected_availability.on_time|late_0_15m|late_15_30m|late_30_60m|late_over_60m`).

If the gaps are confirmed genuine, the remedy is an owner choice and is not made here:

- a measured availability allowance, which needs a dated amendment;
- earlier capture.

## Verification

New `tests/market/test_maker_plugin_111k.py` (17 tests). It covers:

- the KAUS bulletin traced to knots and band masses;
- 110b equivalence for strict knots;
- atoms at the first, last and interior segments;
- decreasing knots refused;
- a tied bulletin end to end through the dry run (verdict PASS, `nbp_read` recomputation);
- an unbooked band: captured set complete, all-band partial, verdict PASS with the all-band count 0;
- the verdict failing without lead-1 evaluation;
- the identity check for every caller (unverified without discovery, before discovery's clock,
  mismatch, point-in-time precedence);
- `observe_discovery`;
- all five forecast-gap classes;
- the gap and lateness counters in the dry run.

Against the unfixed source the file fails at collection (the fixed API does not exist there).

Changed existing tests:

- `test_maker_plugin_110c.py`: the parser-differential test asserted that ties refuse. It now asserts
  that only a decrease refuses and that ties parse to the oracle's values.
- `test_maker_plugin_111j.py`: `t1_layout` passes `uncaptured_tokens` through.

The final run results and GitHub CI conclusion are in the handback reply.

## Exact production re-run command

Run it on the production checkout in the admitted 00:30–09:00 window, under the shared lease. Use a new
detached worktree at the pushed head and a new output directory. Fill `$sha` from
`git ls-remote --exit-code origin refs/heads/codex/weather-maker-plugin-20260925`. The production agent
owns verifying local paths.

```powershell
$repo = (Resolve-Path .).Path
$sha = '<pushed head of codex/weather-maker-plugin-20260925>'
$wt = Join-Path $repo 'scratch\w\111k-rerun'
$out = Join-Path $repo 'data\alerts\weather-plugin-111k-20260926'
if (Test-Path -LiteralPath $wt) { throw "worktree path exists: $wt" }
if (Test-Path -LiteralPath $out) { throw "output exists: $out" }
git -C $repo fetch origin codex/weather-maker-plugin-20260925
git -C $repo worktree add --detach $wt $sha
if ((git -C $wt rev-parse HEAD) -ne $sha) { throw 'worktree is not at the pushed head' }
$python = Join-Path $repo 'venv\Scripts\python.exe'
$src = Join-Path $wt 'src'
$priorPythonPath = $env:PYTHONPATH
. (Join-Path $repo 'scripts\ops\workload_admission.ps1')
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload 'WeatherPluginDryRun-111k'
if ($null -eq $lease) { throw 'Dry run not admitted; do not start Python.' }
try {
    $env:PYTHONPATH = $src
    $probe = @(& $python -B -P -c "import weather.market.maker_plugin_runner as r, weather.market.maker_plugin_sources as s, weather.market.maker_plugin.universe as u, weather.market.maker_plugin.fair_value as f, maker_core; [print(m.__file__) for m in (r, s, u, f, maker_core)]")
    if ($LASTEXITCODE -ne 0 -or $probe.Count -ne 5 -or @($probe | Where-Object { -not $_.StartsWith($src + '\') }).Count) {
        throw "Module path probe failed: $probe"
    }
    & $python -B -P -m weather.market.maker_plugin.dry_run `
        --date 2026-09-26 `
        --data-root (Join-Path $repo 'data') `
        --output $out `
        --max-seconds 2700 `
        --max-output-bytes 200000000 `
        --max-input-bytes 4294967296 `
        --max-cache-bytes 536870912 `
        --minute-stride 5
    $dryRunExit = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $priorPythonPath
    Exit-WeatherHeavyWorkloadLease -Lease $lease
}
Write-Output "Dry-run exit code: $dryRunExit (0 complete; 2 inspect partial/coverage/error report)"
git -C $repo worktree remove $wt
```

**Pass bar.** The top of `report.md` (`## Verdict`) must read `Exam-line plugin bar: PASS`, which
requires all of:

- status COMPLETE;
- `end_to_end.lead1` > 0;
- `band_identity_mismatch` 0 (and `band_identity_unverified` 0);
- lead-1 captured-set complete unit mass > 0.

Record the mass statement as written: captured-set count with the all-band count beside it.

Then hand-check one T+1 fair value against its bulletin:

1. In `report.json`, take a record with `lead_days` 1 and an outcome whose `fair_value.model_id` starts
   with `nbp-v2-piecewise-linear`. Its `nbp_read` holds `source_payload`, `issue`, `slot`
   `[group, token, fhr]`, `knots` and `bands`.
2. Open `data\forecast_payload_cas\sha256\<first two hex>\<source_payload>.blob`. Find the station's
   `NBM ... NBP GUIDANCE <issue>` block. Confirm that FHR at `[group][token]` equals `slot[2]` and is
   valid 00Z on the day after the target. Confirm that TXNP1/2/5/7/9 at `[group][token]` equal
   `knots`.
3. Recompute each band's mass from the knots, as in the KAUS example above. A tie is an atom; a tied
   end segment is vertical. Confirm the masses match `fair_value.joint`, and the outcome's band
   matches `p_yes`.

Also expect, and record:

- `fair_value:nonincreasing_percentile_knots` absent;
- `decreasing_percentile_knots` absent or explained;
- `fair_value_model.lead1.nbp-v2-piecewise-linear-atoms` > 0;
- the `missing_forecast.lead*.*` and `nbp_capture_vs_expected_availability.*` counts, which answer (d);
- `book_not_captured` persisting outside the captured set (by design).

## Per-file adoption disposition

No production closure was read. **Actual closure membership is UNDECIDABLE here.** Run
`scripts\ops\roll_verdict.ps1 -Branch origin/codex/weather-maker-plugin-20260925` before integration. From
source, only plugin modules import these files.

| Changed in 111k | Disposition |
| --- | --- |
| `src/weather/market/maker_plugin/{nbp,fair_value,universe}.py` | UNDECIDABLE; plugin-only importers |
| `src/weather/market/maker_plugin_{runner,sources}.py` | UNDECIDABLE; diagnostic runner only |
| `tests/market/test_maker_plugin_{111k,111j,110c}.py`, fixture README | Test code |
| `docs/operations/maker-core-contracts.md`, the T+1 pre-registration amendment, this report, index | Documentation, roll-free |

## Not done

- No production or mirror reads or writes; no credential or `.env` access; no venue calls, Scheduler
  changes, capture changes, scoring, fitting, promotion or live trading; no merge to master.
- The NBP expiry allowance is unchanged. Changing it is an owner decision after the re-run measures
  lateness.
- No `docs/research/maker-replay-*` file was touched.

## Branch and commits

Branch `codex/weather-maker-plugin-20260925` (draft PR #96), fast-forward from `ad041d6d`. Resolve the
final head with `git ls-remote`.
