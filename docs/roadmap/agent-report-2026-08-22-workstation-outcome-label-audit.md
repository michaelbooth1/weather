# Workstation report 2026-09-67a — outcome-label provenance audit

## Verdict

**THE GAP IS FLAT ACROSS LABEL-COVERAGE BUCKETS AT THE RESOLUTION OF THIS PANEL. THE LABELS ARE NOT
THE STORY; THE FOUR-MISSION INSTRUMENT AUDIT CLOSES COMPLETELY, AND “WE TRAIL THE MARKET” SURVIVES
ITS LAST DENOMINATOR CHECK.**

In the served out-of-season C stratum, incumbent-minus-market Brier is `0.019948935` on clean
market-days, `0.023865217` with a `(0,30)` minute material-coverage gap, and `0.021818110` with a
`[30,∞)` gap. The material-minus-clean contrast is only **`+0.001869175`**, crossed 95%
**`[-0.011747881, +0.018513884]`**. The market's own Brier is almost perfectly flat there:
`0.038970842`, `0.038912011`, and `0.039086423`; material-minus-clean is
**`+0.000115581 [-0.009124050, +0.008952864]`**.

B says the same thing in the other direction: its material-gap gap is `0.012014494` versus
`0.013811762` clean, contrast **`-0.001797268 [-0.017747638, +0.018109078]`**. There is no monotonic
increase in either our Brier, the market's Brier, or the gap as label coverage weakens. Every
coverage-bucket gap contrast is indistinguishable from zero.

The proposed directional mechanism is also absent. On `[30,∞)` market-days the incumbent centre is
**cool**, not warm: `-0.4302 °C-equivalent` in B and `-0.2471 °C-equivalent` in C. Moving open-tail
representatives one degree outward leaves both signs cool (`-0.4786`, `-0.2894`). These are
descriptive centre signs, not evidence that the labels over-read; their intervals include zero on
the material bucket. They do establish that the point direction is the opposite of a warm model
scored against an under-reading label.

I read C under the handoff's explicit diagnostic authorization. There was no candidate, fitted
parameter, accept rule, endpoint selection, or alpha allocation. This spends **no alpha**: the
campaign remains **7 of 20 spent, 13 available**, and decision 10 remains **CLOSED UNUSED**.

## Gap by material-coverage bucket — B and C kept separate

All intervals below are 10,000-draw crossed target-date × market pigeonhole percentile intervals.
`Centre error` is probability-weighted venue-band centre minus `settlement_high`, converted to
°C-equivalent across the fleet; positive is warm and negative is cool.

### B — D=23, M=12, 204 market-days, 4,636 snapshots

| Material gap | Market-days / snapshots | Incumbent Brier [95%] | Market Brier [95%] | Gap [95%] | Incumbent centre error [95%] |
| --- | ---: | ---: | ---: | ---: | ---: |
| `0` | 59 / 1,374 | `0.051784525 [0.040525046, 0.063718622]` | `0.037972763 [0.030092283, 0.044519534]` | **`0.013811762 [0.003161708, 0.026810233]`** | `-0.6673 [-1.0508, -0.3730]` |
| `(0,30)` | 113 / 2,585 | `0.055417455 [0.046424097, 0.066060937]` | `0.037597250 [0.030116589, 0.045665315]` | **`0.017820205 [0.009445001, 0.028864548]`** | `-0.3847 [-0.7786, -0.0442]` |
| `[30,∞)` | 32 / 677 | `0.048222412 [0.035572188, 0.064050068]` | `0.036207918 [0.023685215, 0.046918437]` | **`0.012014494 [0.003584081, 0.029646557]`** | `-0.4302 [-1.0265, +0.3150]` |

### C — D=27, M=12, 320 market-days, 7,653 snapshots

| Material gap | Market-days / snapshots | Incumbent Brier [95%] | Market Brier [95%] | Gap [95%] | Incumbent centre error [95%] |
| --- | ---: | ---: | ---: | ---: | ---: |
| `0` | 194 / 4,653 | `0.058919777 [0.053056264, 0.064915286]` | `0.038970842 [0.034549942, 0.043412001]` | **`0.019948935 [0.013990213, 0.026830983]`** | `-0.2356 [-0.5402, +0.0481]` |
| `(0,30)` | 71 / 1,696 | `0.062777228 [0.052546257, 0.072801212]` | `0.038912011 [0.031875023, 0.045967259]` | **`0.023865217 [0.012513043, 0.034169754]`** | `-0.3245 [-0.7891, +0.0894]` |
| `[30,∞)` | 55 / 1,304 | `0.060904533 [0.049511620, 0.073554046]` | `0.039086423 [0.029426453, 0.049055207]` | **`0.021818110 [0.008821345, 0.038836629]`** | `-0.2471 [-0.7432, +0.2784]` |

### Paired bucket contrasts against clean days — the decisive control

| Stratum | Contrast | Δ incumbent Brier [95%] | Δ market Brier [95%] | Δ gap [95%] |
| --- | --- | ---: | ---: | ---: |
| B | `(0,30) - 0` | `+0.003632930 [-0.009930943, +0.019047205]` | `-0.000375513 [-0.009540415, +0.010239043]` | **`+0.004008443 [-0.011238603, +0.018612602]`** |
| B | `[30,∞) - 0` | `-0.003562112 [-0.020819890, +0.015441863]` | `-0.001764845 [-0.015402658, +0.011123169]` | **`-0.001797268 [-0.017747638, +0.018109078]`** |
| C | `(0,30) - 0` | `+0.003857450 [-0.007577441, +0.015160315]` | `-0.000058831 [-0.007843552, +0.008087337]` | **`+0.003916282 [-0.008478313, +0.015826698]`** |
| C | `[30,∞) - 0` | `+0.001984756 [-0.010486798, +0.015537179]` | **`+0.000115581 [-0.009124050, +0.008952864]`** | **`+0.001869175 [-0.011747881, +0.018513884]`** |

There is no common degradation of both forecasters on gapped days and no incumbent-only
degradation either. In C, where every settlement is `daily_summary`, the market Brier changes by
only `+0.00012` on the material bucket. **The label-noise control is flat.**

## Gap by settlement source

`snapshot_high` occurs only in B: all 37 fallback market-days are confined to four B dates. C has
320 `daily_summary` market-days and **zero** `snapshot_high` rows, so a C source contrast is not
estimable and was not invented.

| Stratum / source | Market-days / snapshots | Incumbent Brier [95%] | Market Brier [95%] | Gap [95%] | Incumbent centre error [95%] |
| --- | ---: | ---: | ---: | ---: | ---: |
| B / `daily_summary` | 167 / 3,748 | `0.053231140 [0.045718513, 0.061043495]` | `0.036166577 [0.030422303, 0.041612486]` | **`0.017064563 [0.009441217, 0.025254594]`** | `-0.5408 [-0.8255, -0.2709]` |
| B / `snapshot_high` | 37 / 888 | `0.053538647 [0.036936818, 0.075435880]` | `0.043157543 [0.029340944, 0.056420362]` | **`0.010381105 [0.002854585, 0.023869428]`** | `-0.1980 [-0.8436, +0.2929]` |
| C / `daily_summary` | 320 / 7,653 | `0.060112820 [0.054869836, 0.065329739]` | `0.038977498 [0.034760962, 0.043147425]` | **`0.021135322 [0.015296804, 0.027571094]`** | `-0.2572 [-0.5361, +0.0106]` |
| C / `snapshot_high` | 0 / 0 | not estimable | not estimable | **not estimable** | not estimable |

Within B, `snapshot_high - daily_summary` is `+0.000307508
[-0.018372790, +0.023449895]` for incumbent Brier, `+0.006990966
[-0.006760122, +0.021626978]` for market Brier, and **`-0.006683458
[-0.018528103, +0.009408452]` for the gap**. All include zero. The source result therefore does not
concentrate our gap on the fallback label either. Because the fallback appears on only four dates,
128 of 10,000 crossed draws had no fallback support; the harness reports and omits those draws from
that sparse subgroup's percentile interval, exactly as pinned in the seed.

## Error direction on gapped days

| Stratum / bucket | Standard band-centre error [95%], °C-eq | Open tails one degree outward [95%], °C-eq | Direction |
| --- | ---: | ---: | --- |
| B / `(0,30)` | `-0.3847 [-0.7786, -0.0442]` | `-0.4062 [-0.8078, -0.0551]` | **Cool** |
| B / `[30,∞)` | `-0.4302 [-1.0265, +0.3150]` | `-0.4786 [-1.0654, +0.1969]` | **Cool point; interval crosses zero** |
| C / `(0,30)` | `-0.3245 [-0.7891, +0.0894]` | `-0.3606 [-0.8448, +0.0669]` | **Cool point** |
| C / `[30,∞)` | `-0.2471 [-0.7432, +0.2784]` | `-0.2894 [-0.8036, +0.2462]` | **Cool point; interval crosses zero** |

The point sign is cool in every gapped cell. **We do not run warm on the days whose label could
have under-read.** The result does not license a claim that those labels are high; it only rejects
the proposed warm-against-low-label signature.

## C attribution counterfactual — DIAGNOSTIC, not a corrected result

The `[30,∞)` bucket supplies 55 C market-days and **17.0391%** of C's band-row weight. Holding the
`(0,30)` bucket and every observed row unchanged, and replacing only the material bucket's gap with
the clean-bucket gap gives:

| Quantity | Diagnostic value [crossed 95%] |
| --- | ---: |
| Observed `G` | `0.021135322 [0.015296804, 0.027571094]` |
| If `[30,∞)` rows had the clean-day gap rate | **`0.020816832 [0.015343286, 0.026891117]`** |
| Difference attributed to the material bucket | `0.000318490 [-0.002265380, +0.002967600]` |
| Share of `G` | **`1.5069% [-11.9246%, +12.9534%]`** |

This is a **DIAGNOSTIC**, not a corrected Brier, corrected label, exclusion rule, or re-scoring of
any spent decision. Its interval includes zero and both signs. The point would leave **98.4931%** of
C's gap untouched.

## Method, support, and integrity

The harness reads the verified `-09-66a` served-floor band output rather than reopening the floor
audit. It uses `served_floor_probability` for B and C; C's portable baseline and intervention are
checked byte-for-byte identical before any statistic is emitted. The `-09-44a` band file supplies
only band identity/geometry. The shipped provenance is joined one-to-one on
`(stratum, market_id, target_date)` and many-to-one onto the 135,179 band rows.

Every input hash, byte size, population count, one-winner-per-snapshot contract, 11-band simplex
shape, B/C overall Brier reference, and pre-`2026-07-31` boundary is fail-closed. B and C have
separate date resamples and are never pooled. Market-cluster weights are shared within each
replicate, and every within-stratum bucket/source contrast uses the same crossed weights on both
sides. The 10,000-replicate seed is `20260967`.

| Stratum | Dates | Markets | Market-days | Snapshots | Band rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| B | 23 | 12 | 204 | 4,636 | 50,996 |
| C | 27 | 12 | 320 | 7,653 | 84,183 |

The supplied provenance file was verified **before model output was read**: 44,946 bytes, 524 data
rows, SHA-256 `73501415ea8dd31db8816c3fb4b5e8db92eb0d5448b8b5f48e7c57b6c44597cd`.
It reproduces 487 `daily_summary`, 37 `snapshot_high`, and 87 `[30,∞)` market-days. The supplied
2026-06-09 Chicago/Atlanta/San Francisco simultaneous gaps are present in that extract; diagnosing
the production stall is outside this mission and was not attempted.

| Evidence | SHA-256 |
| --- | --- |
| Verified `-09-66a` served-floor band rows | `833ddb80c9ebb1f87161d8380ac12a746bc60a55af3527566d82c768cbd05f39` |
| Retained `-09-44a` band identity | `9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae` |
| Supplied settlement provenance | `73501415ea8dd31db8816c3fb4b5e8db92eb0d5448b8b5f48e7c57b6c44597cd` |
| Committed harness | `74431df7a862dedbbc745328ca10a0c6623aa51aead914fbceff4d066a02f6c9` |
| Committed seed | `dd4267c6f06674839f6872323328771135bf92b94475096626f1685ab15ae2b9` |
| Ignored summary JSON | `0bc108ae9d97d1acd0d9138f0a842deaf5ca70560949e5a7ab0be64f524f93a3` |
| Ignored market-day metrics | `2098d05b95ef205314d7b4430a1d43d902d8056aa272ca896a7892ada803982e` |
| Ignored stratified metrics | `cfeb6d1c7b5885ee2930df2afd4f66f91495ff00d4a21c9b7c40ed7811d61b93` |
| Ignored contrasts | `8dddd838034ad2d28919f63e6c1fe2862f8767e6224c6a4587c12762bceeab3f` |

Two complete runs in separate ignored directories reproduced all four output hashes byte-for-byte.
Runtime: bundled Codex Python `3.12.13`, NumPy `2.3.5`, pandas `3.0.1`. Nothing was installed, and no
provider, exchange, or other network endpoint was called.

## Reproduction

On the workstation holding the retained ignored `-09-44a` and verified `-09-66a` evidence:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
Set-Location $repo
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$out = '.\scratch\runs\outcome-label-audit-reproduction-2026-09-67a'

Get-FileHash -Algorithm SHA256 `
  .\docs\roadmap\settlement-provenance-for-panel-2026-09-67a.csv
& $python .\tools\research\audit_outcome_label_provenance_09_67a.py `
  --output-dir $out
Get-FileHash -Algorithm SHA256 `
  "$out\summary.json", `
  "$out\market-day-metrics.csv", `
  "$out\stratified-metrics.csv", `
  "$out\contrasts.csv"
```

Expected exit is `0`; the four hashes are the last four rows of the evidence table.

Production-host acceptance uses committed paths only; ignored workstation evidence is not claimed
to exist there:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-is-the-outcome-label-sound-2026-09-67a'
$report = 'docs/roadmap/agent-report-2026-08-22-workstation-outcome-label-audit.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:tools/research/audit_outcome_label_provenance_09_67a.py"
git show "${branch}:tools/research/outcome_label_audit_09_67a_seed.json"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

## Branch and roll verdict

Base: `aa8590f19e7609edfb3cd8b904d6caba825bed02` (`origin/master`).

Branch: `codex/workstation-is-the-outcome-label-sound-2026-09-67a`.

The implementation/report commit and authoritative repository roll verdict are bound by the
follow-up report-only commit after the first commit makes the branch diff visible to
`scripts\ops\roll_verdict.ps1`.

## Explicitly not done

- No correction, relabelling, candidate, fitted parameter, exclusion rule, accept rule, alpha
  allocation, promotion, re-decision, or re-scoring of a spent decision was produced.
- No settlement rule, daily-max window, collection schedule, serving floor, model, calibration,
  replay, scoring, or production source was changed. The serving floor was not weakened.
- No production `data/`, mirror, ledger, tape, artifact, scheduled task, collector, supervisor, or
  process was written, registered, started, restarted, or mutated.
- No PR, merge, master update, production checkout change, branch deletion, order, or trade was
  performed.
