# Workstation seasonal-distance two-stratum measurement — 2026-08-06

## Verdict

**NO-GO: the all-row seasonal-distance signal is real and is not explained by
the market, but the predeclared severity-tail endpoint is not powered. Do not
treat this test as authorization that the first retrain will close the market
gap.**

Power is stated before the point estimate, as required. For the all-row B→C
base-HGB contrast, crossed-bootstrap standard error is `0.3087 °C-equivalent`.
At the predeclared `-0.8590 °C-equivalent` reference effect, one-sided
noncentral-t power is `83.17%` (`alpha=0.05`, `df=11`), above the `80%` gate;
the minimum detectable effect at 80% power is `0.8196 °C-equivalent`.

P0 survives. On identical admitted rows, the market's implied-centre error is
`+0.0699 °C-equivalent` in B and `+0.0642` in C. Its C-minus-B contrast is
`-0.0057` with a crossed 95% interval of `[-0.1643, +0.1520]`. The open-tail
proxy sensitivity is also flat: `-0.0145` `[-0.1663, +0.1401]`. The market
therefore does not show an interpretable summer cooldown alongside the model.
The handoff's common-weather falsifier does not fire.

P1 survives. The frozen raw HGB is `-0.1848 °C-equivalent` in B and `-1.0193`
in C. C minus B is `-0.8346` with a crossed 95% interval of
`[-1.4378, -0.2159]`. Subtracting the market control gives `-0.8288`
`[-1.3841, -0.2492]`. The out-of-season base HGB is detectably cooler; the
market does not account for that movement.

P2 controls the final disposition and does not pass. Its crossed-bootstrap
standard error is `0.5081 °C-equivalent`; power at the same reference effect is
only `47.65%`, and the 80%-power minimum detectable effect is `1.3489
°C-equivalent`. The tail estimate is therefore **not interpretable as a
movement**. For completeness, its sealed point is `-0.9515` and its crossed
95% interval is `[-1.9636, +0.0503]`, which includes zero. The seasonal effect
is supported as an all-row centre diagnostic, but this experiment cannot show
that it reaches the small set of rows carrying most loss.

No fit, retrain, candidate score, promotion, collection, provider call, or
serving change was performed.

## Start from this; do not re-derive it

The retained predecessor finding in
[`ESTABLISHED_FINDINGS.md`](../operations/ESTABLISHED_FINDINGS.md) is a frozen
raw-HGB centre error of `-0.6641 °C-equivalent`
`[-1.1164, -0.2482]` on `D=34`, `M=12`, `MD=399`. Its June-to-July contrast is
`-0.8590` `[-1.5581, -0.1359]`. The same retained analysis identified a
severity tail comprising `4.26%` of band rows and carrying `60.2%` of positive
excess squared error. Those values supplied the directional prior and power
reference; they were not re-estimated to select this result.

The corrected handoff also establishes that every 2026 row is out-of-sample
for a 2026-target artifact because the trainer excludes the target year.
Consequently this mission compares only in-season B with out-of-season C and
never uses the void in-sample stratum from `-09-30a`.

## Population and inference contract

**Sign convention:** raw-HGB or market expected centre minus the authoritative
settlement bucket. Negative is cool. Native Fahrenheit differences are
multiplied by `5/9` after subtraction; Toronto remains native Celsius. Pooled
and comparable market results below are C-equivalent.

Settlement authority is each market's verified current
`data/settlements/<market>/ledger.jsonl` row. Admission is
`promotion_countable=True`; `quality_grade` is not a substitute. The exact
streaming ledger verifier re-derived revision IDs, revision numbers,
supersession links, previous hashes, label hashes, and revision changes for all
12 ledgers before any centre calculation. Every ledger proof reports `PASS`.
`data/backtest/market_day_labels.csv` was not read.

The handoff's stated support is the gross current-ledger population, not the
admitted replay population:

| Stratum | Gross D | Gross MD | Promotion-countable MD | Replay-admitted D | Replay-admitted MD | Exclusion |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| B, 2026-05-27–06-30 | 34 | 309 | 208 | 23 | 204 | 101 not countable; 4 lack replay/tape intersection |
| C, 2026-07-01–07-30 | 30 | 360 | 320 | 27 | 320 | 40 not countable |

This reconciliation explains the difference between the gross `D=34/30,
MD=309/360` in the handoff and the measured support. No admission bar was
relaxed to recover the gross count.

For every admitted market-day, the replay selects the earliest captured input
in each local clock hour that also exists in `snapshots_long.csv`. It then
replays the frozen market artifact and measures the raw HGB centre, not served
output. The final population is `12,289` hourly snapshots on `D=50`, `M=12`,
`MD=524`; every route is `hgb`. The earliest target is 2026-06-03 and the
latest is 2026-07-30, so no row crosses the 2026-07-31 artifact-provenance
boundary.

All pooled intervals are deterministic 10,000-replicate percentile intervals.
Contrasts draw target dates independently within B and C and use the same
resampled market counts on both sides. This is crossed date × market
pigeonhole resampling, not row bootstrap or market-only clustering. `D`, `M`,
`MD`, and `H` below mean target-date clusters, market clusters, distinct
market-days, and selected hourly snapshots.

## P0 — market control

| Estimand, C-equivalent | B point | C point | C−B [95% crossed interval] | B support D/M/MD/H | C support D/M/MD/H |
| --- | ---: | ---: | ---: | ---: | ---: |
| Market implied centre − settlement | +0.0699 | +0.0642 | -0.0057 [-0.1643, +0.1520] | 23/12/204/4,636 | 27/12/320/7,653 |
| Market, open tails moved outward one native degree | +0.0732 | +0.0586 | -0.0145 [-0.1663, +0.1401] | 23/12/204/4,636 | 27/12/320/7,653 |
| Raw HGB − market | -0.2546 | -1.0835 | -0.8288 [-1.3841, -0.2492] | 23/12/204/4,636 | 27/12/320/7,653 |

The market centre is its normalized market-YES-weighted band centre on the
same snapshot rows. Open tails use the quoted boundary in the primary proxy;
the sensitivity moves each open-tail midpoint outward by one native degree.
Neither market interval excludes zero, and the sensitivity does not change the
disposition. Although the primary market point is slightly negative, section
5 of the handoff forbids presenting a zero-crossing contrast as a movement.
It is also about 146 times smaller in magnitude than the raw-HGB contrast.

Per market, eight of 12 market-control points are negative, but **zero** of 12
market-control intervals is wholly negative. This is not evidence that the
market cooled with the model.

## P1 — base-HGB B→C contrast

| Estimand, C-equivalent | B point | C point | C−B [95% crossed interval] | Crossed SE | Power at -0.8590 | 80%-power MDE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw HGB centre − settlement | -0.1848 | -1.0193 | **-0.8346 [-1.4378, -0.2159]** | 0.3087 | 83.17% | 0.8196 |

B support is `D=23`, `M=12`, `MD=204`, `H=4,636`. C support is `D=27`,
`M=12`, `MD=320`, `H=7,653`. The point is in the predeclared negative
direction, its interval is wholly negative, and the power gate was already
passed before this point was interpreted.

### Per-market P1 results

Each interval below resamples target dates; with one market, the crossed market
draw is degenerate. Values are C-equivalent. For each market, `MD=D` within a
stratum.

| Market | C−B [95% interval] | B D | C D |
| --- | ---: | ---: | ---: |
| Atlanta | -1.4601 [-2.4497, -0.5874] | 17 | 26 |
| Austin | -0.1812 [-0.8780, +0.5750] | 17 | 27 |
| Chicago | -1.0697 [-1.9510, -0.1625] | 16 | 27 |
| Dallas | -1.9897 [-2.8408, -1.2064] | 17 | 27 |
| Denver | -1.6620 [-2.6267, -0.7172] | 18 | 27 |
| Houston | -0.0655 [-0.6735, +0.5602] | 15 | 27 |
| Los Angeles | -1.5738 [-2.1739, -0.9821] | 16 | 27 |
| Miami | +0.0538 [-0.3558, +0.4585] | 16 | 27 |
| NYC | -0.6187 [-1.8918, +0.6027] | 17 | 26 |
| San Francisco | +0.2804 [-0.7817, +1.3721] | 17 | 27 |
| Seattle | -1.3444 [-2.6883, -0.1095] | 18 | 25 |
| Toronto | -0.5072 [-1.3607, +0.3173] | 20 | 27 |

Ten of 12 point estimates are negative and six intervals are wholly negative.
The effect is heterogeneous, so the pooled estimate is not a claim that every
market moved by one common constant.

## P2 — severity tail

Tail membership was frozen from the unchanged served-control replay, not from
the raw-HGB outcome being tested. A snapshot is included when at least one
band has both positive served-versus-market excess squared error and an
absolute served-minus-market probability gap of at least `0.30`.

| Estimand, C-equivalent | B point | C point | C−B [95% crossed interval] | B support D/M/MD/H | C support D/M/MD/H |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw HGB centre − settlement | -0.7870 | -1.7385 | -0.9515 [-1.9636, +0.0503] | 22/12/186/1,193 | 27/12/299/2,713 |
| Market centre − settlement | +0.0455 | -0.0249 | -0.0704 [-0.3266, +0.1816] | 22/12/186/1,193 | 27/12/299/2,713 |
| Raw HGB − market | -0.8325 | -1.7135 | -0.8810 [-1.8360, +0.0583] | 22/12/186/1,193 | 27/12/299/2,713 |

The 5,910 severe band rows are `4.372%` of 135,179 band rows and carry
`64.168%` of positive served-versus-market excess squared error. This closely
reproduces the retained tail concentration without using the retained panel to
select rows. The tail contains 3,906 hourly snapshots on `D=49`, `M=12`,
`MD=485`.

The tail estimate cannot pass or fail seasonal movement on its point. Its
power is `47.65%`, not `80%`, and its interval includes zero. The final
`NO_GO_SEVERE_TAIL_NOT_POWERED` verdict therefore follows before any economic
interpretation of the point.

## Decision

This measurement separates two claims that should not be collapsed:

1. **Centre mechanism:** supported on all admitted rows. The frozen raw HGB is
   materially cooler outside its May 10–June 30 archive season, and the market
   control is flat.
2. **Loss-lever claim:** not established. The only endpoint tied directly to
   the concentrated loss is underpowered and crosses zero.

Accordingly, seasonal distance remains a plausible mechanism to address in
the first retrain, but this test does not establish that doing so closes the
market gap. It does not authorize collection spend, fitting, a serving-side
offset, a retrain candidate, or promotion. A future claim that the retrain is
the lever needs a predeclared, adequately powered severity-tail or proper-score
confirmation under the same settlement, replay, native-unit, and crossed-
cluster contracts.

## What would falsify this mission

- **Market control:** a market C-minus-B interval wholly negative and moving
  materially with raw HGB would mean the test measured summer weather. It did
  not occur, including under the open-tail sensitivity.
- **P1 movement:** an adequately powered raw-HGB interval including zero, or a
  non-negative point, would reject the seasonal-distance centre mechanism. It
  did not occur.
- **P1 power:** power below 80% at the predeclared reference effect would end
  interpretation before the point. It did not occur.
- **Replay validity:** any non-HGB route, source/artifact hash mismatch,
  probability-mass failure, post-2026-07-30 row, or inability to hold artifact
  and code constant would invalidate the contrast. None occurred.
- **Decision endpoint:** an underpowered severity-tail contrast ends the
  mission without a loss-lever claim. **This occurred and is the controlling
  no-go.**

## Evidence and independent verification

The sealed workstation evidence root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\seasonal-distance-two-stratum-2026-09-31a`.
It is ignored local research state, not a production-host command path and not
an input assumed to exist in a clean checkout.

Final evidence-manifest SHA-256:
`b65810a907ed9ab0dcbff553d4b12557fcd84e5c325afedaf484c5b6247fe576`.
The manifest seals 37 files, including all 12 full ledger extracts and all 12
lightweight projections.

| Evidence | Bytes | SHA-256 |
| --- | ---: | --- |
| Declaration | 6,901 | `f19e01f81f8837511521f99ad579c23c72a218e19a9ec9a3f921200166de55a5` |
| Measurement script | 47,516 | `b0628297422e5ec8444510e5a4a0a77534a5bdce9677620894293028f280cd8b` |
| Measurement manifest | 725,795 | `05be988275e124a3886b9aa81ab36f2a2bc4cdb3b23d39cb899e73f999fa0e81` |
| Snapshot rows | 5,244,494 | `a88b5bb863f28526c247d10ec06934f1cc88b00245284b05d9b35233a6d8c8ec` |
| Per-market results | 9,067 | `5a6cb9e53e9d4c0cdda5607f3018cfc107a9b1fb6436b5800f49b8718a0a499d` |
| Bootstrap draws | 1,468,964 | `f5dcebbf2f698833dc7faa6cffdd6303c448ffa73c0c81756e01a5e20f587b0c` |
| Summary | 9,723 | `50ec07c4432a6568c23c4d54abcfb3e5093e4e8cc871cdf3e532f7cc12f6a825` |
| Independent verifier | 16,936 | `e7b98dc87787629ee94e6f115cdebed127cba0b962746d9f62b570aa449bb88f` |
| Independent verification | 1,822 | `0ac84bdce2065b54409fef2bbc1fee5bad8db971e13d5e10fab55e3abfeeb769` |

The independent verifier passed 11 groups of checks: sealed output hashes;
frozen source and artifact hashes; all 12 authority-ledger hashes and exact
integrity receipts; ledger-derived gross and admitted populations; pre-boundary
HGB-only rows; replay-availability reconciliation; row arithmetic, native-to-C
conversion, probability mass, and severity membership; pooled points and
crossed intervals; all 12 per-market points and supports; tail loss
concentration; and P0/P1/P2 power and decision logic.

Maximum raw native, raw band, and served band probability-sum errors are each
at most `6.66e-16`. The verifier passed without changing any sealed measurement
file.

## Repository verification

`git diff --check` passes. The canonical agent-doc audit reaches the new report
without finding an issue in it, but the command remains red on the unchanged
`origin/master` baseline because
`docs/roadmap/agent-report-2026-08-02-workstation-spec-contract-repair.md`
links to the retired
`../../src/weather/reporting/validation/floor_retrain_gate_harness.py#L1079`.
The exact audit result is `FAIL (1 issue)` for that pre-existing target. The
historical report was not edited and the missing module was not reintroduced.

No application or source test was warranted for this report-only branch. The
measurement and independent verification checks described above both passed.

## Safety, roll verdict, and actions not taken

The reserved confirmation window was checked at run time and reported no
reserved dates. No reserved window was opened or consumed.

Only this report is changed in the branch:

| Changed file | Retained capture closures | Roll verdict |
| --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-06-workstation-seasonal-distance-two-stratum.md` | None; Markdown is outside snapshot, CLOB, observation-trigger, and CLOB-enrichment closures | Roll-free |

No source, test, config, artifact, ledger, tape, release, pointer, scheduler,
task, or production `data/` file was changed. No model was fit or retrained. No
provider, network collector, paid source, fresh observation, or market endpoint
was called. No production write, registration, capture restart, PR, merge, or
master action was performed.

## Production-host reproduction and acceptance commands

These commands use paths present on the production host. They reproduce the
committed handback, verify its exact changed-file scope, and run the canonical
documentation audit. The sealed raw measurement remains ignored workstation
evidence by repository policy; the commands do not pretend that a workstation
scratch path exists on production.

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-seasonal-distance-two-stratum-2026-09-31a'
$report = 'docs/roadmap/agent-report-2026-08-06-workstation-seasonal-distance-two-stratum.md'

git rev-parse $branch
git show "${branch}:$report"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
```

Expected changed-file scope is exactly the one Markdown report above. The
final command is expected to reproduce the single unchanged historical-link
failure documented under Repository verification; no new audit failure is
expected. The
branch starts at `origin/master @ 0cb9a03b7c25662278c23a3abbee962e518b439f`.

Branch:
`codex/workstation-seasonal-distance-two-stratum-2026-09-31a`.

Report-content commit: `087301fe3520745562a1a0f8c30f1df6ab19a42f`.

No PR was opened and no merge was performed.
