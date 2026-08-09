# Workstation handback 2026-09-46a — quotable-edge search

**VERDICT: NO_ADJUSTED_EDGE / NO-GO for model-skewed quoting.** Across the complete
pre-registered family, **0 of 114 non-empty subsets had even a positive point edge**,
0 won at raw alpha, 0 survived Holm family-wise adjustment, and 0 met the declared
skill or quoteability rule. The repaired served model lost to the market in every
observed quote-time-identifiable cell. This mission therefore found no model edge to
confirm, promote, or use for quoting. It did not consume the untouched confirmation
window.

## Declaration and leakage control

The declaration is
[`quotable-edge-preregistration-2026-09-46a.md`](quotable-edge-preregistration-2026-09-46a.md).
It was committed alone at `f2eb0a85` before any new outcome inspection. Its SHA-256 is:

```text
5afe4027a92def4c7f754f1c4fcdcae00834b2ad3d32b9ed87fd76e5fb503a57
```

The frozen family contains **K=117** hypotheses. Axes are hour, market, season,
forecast-band distance, model/market entropy and their gap, forecast-source
disagreement and source count, market probability, signed model-market probability
gap, three predeclared interaction families, captured book spread, aggregate
liquidity, and volume. Only quote-time fields define cells. The score is market Brier
minus repaired-model Brier, so positive favors the model. All cells use 10,000-draw
crossed target-date × market pigeonhole intervals, seed `20260946`, one-sided raw
p-values, and Holm step-down FWER at 0.05 across all 117 hypotheses. Power is reported
both at raw alpha and conservative `0.05/117`; it uses absolute observed magnitude and
does not license direction.

The chronology is retained because this search had exceptional leakage risk:

1. `f2eb0a85` froze and committed K, partitions, metric, support/stability rules,
   multiplicity, P1 formula, grid, and outcomes before measurement.
2. In the outcome-blind predictor pass, duplicate snapshot IDs across market dates
   required binding the key to date; `84f02e45` made that identity-only correction.
3. After the outcome CSV was opened but before any partition result was emitted, its
   ordinary decimal round trip differed by at most `3.3881317890172014e-21`;
   `880f4835` fixed the quote-evidence comparison tolerance at `1e-15`. No roster,
   partition, score, or decision rule changed.
4. The first analysis stopped before emitting results when a sparse interaction's
   crossed product resample was empty. `33992bcf` deterministically redraws only empty
   products until the predeclared 10,000 valid draws exist and adds a regression test.

No hypothesis was added, removed, merged, or redefined after outcomes. Predictor
preparation explicitly recorded `outcomes_read=false`. Its sidecar, thresholds, and
manifest were frozen before the outcome phase.

## Population, positive control, and inference

The sealed replay corpus is wholly before the forbidden `2026-07-31` provenance
boundary: target dates run through `2026-07-30`. Ledger admission is deduplicated to
`(market, target_date)` before scoring.

| Property | Support |
| --- | ---: |
| Target-date clusters | **50** |
| Market clusters | **12** |
| Market-days | **524** |
| Hourly snapshots | **12,289** |
| Binary band rows | **135,179** |

The pre-repair code was rerun from the disposable `-09-43a` runtime rather than merely
reading its earlier receipt. The mandatory positive control returned **PASS, 840/840
exact**, maximum and mean L1 both zero. The new receipt SHA-256 is
`b35a954a5b6ebd236f55304d73e89a4c149b598689a7f765947b3e3d885ca1b2`;
its internal report hash is
`8afdab2fc11e8f612eafad4b62e55306dcebcdbdd6a22cf4188b0f1ae26caa9c`.

## P0 — every observed subset loses

As an aggregate reference, repaired-model Brier is `0.0575727980`, market Brier is
`0.0384222495`, and edge is **−0.0191505485** with crossed 95% interval
**[−0.0244369853, −0.0144283801]**, crossed SE `0.0025555304`, and one-sided
positive-edge p approximately 1.

Of the 117 declared cells, 114 were non-empty and all 114 had negative point edge.
The empty cells were `liquidity:missing`, `liquidity:lt_25`, and `volume:missing`.
There were:

- **0** positive point cells;
- **0** raw winners and **0** Holm winners;
- **0** skill candidates and **0** quotable candidates;
- 107 support-qualified cells; and
- 78 cells with family-alpha plug-in power at least 0.80 for the *absolute observed
  magnitude*, all in the losing direction.

The 114-cell edge distribution was:

| Quantile | Edge (market Brier − model Brier) |
| --- | ---: |
| Minimum | −0.3228858684 |
| 10th percentile | −0.0791739102 |
| 25th percentile | −0.0412883888 |
| Median | −0.0195107038 |
| 75th percentile | −0.0149056061 |
| 90th percentile | −0.0076531628 |
| Maximum | −0.0000173523 |

The companion
[`agent-report-2026-08-09-workstation-quotable-edge-partitions.csv`](agent-report-2026-08-09-workstation-quotable-edge-partitions.csv)
is the full required 117-row report. For every predeclared cell it gives band rows,
snapshots, D/M/market-day support, model and market Brier, point edge, crossed interval
and SE, raw p and Holm-adjusted p, raw and family power/MDE, leave-one-date/market-out
stability, book/spread coverage, each decision-rule component, and the terminal
candidate flags. Its SHA-256 is
`8ce3d08fca5566489c1262df12987f7d119ba927b31916a4d1995569e3393d69`,
identical to the analysis output.

For orientation, this is the full edge range by declared axis; every maximum is still
negative:

| Axis | K / non-empty | Edge min / median / max | Support-qualified | Family power ≥ 0.80 |
| --- | ---: | --- | ---: | ---: |
| hour | 14 / 14 | −0.025486 / −0.017554 / −0.014492 | 14 | 13 |
| market | 12 / 12 | −0.033845 / −0.017850 / −0.011789 | 12 | 9 |
| season | 2 / 2 | −0.021135 / −0.018505 / −0.015874 | 2 | 2 |
| forecast distance | 8 / 8 | −0.063549 / −0.045422 / −0.002350 | 8 | 4 |
| model entropy | 4 / 4 | −0.028784 / −0.017532 / −0.012755 | 4 | 3 |
| market entropy | 4 / 4 | −0.024134 / −0.019387 / −0.013692 | 4 | 4 |
| entropy gap | 4 / 4 | −0.034264 / −0.017275 / −0.007790 | 4 | 4 |
| forecast disagreement | 5 / 5 | −0.023331 / −0.017241 / −0.011754 | 5 | 2 |
| forecast source count | 4 / 4 | −0.021568 / −0.015903 / −0.010517 | 4 | 1 |
| market probability | 8 / 8 | −0.159380 / −0.065043 / −0.006719 | 6 | 6 |
| signed probability gap | 5 / 5 | −0.162958 / −0.011189 / −0.000146 | 5 | 3 |
| hour × probability gap | 12 / 12 | −0.322886 / −0.076140 / −0.000309 | 10 | 9 |
| season × hour | 8 / 8 | −0.027768 / −0.018588 / −0.011443 | 8 | 5 |
| distance × hour | 12 / 12 | −0.080136 / −0.036723 / −0.005132 | 12 | 4 |
| book spread | 5 / 5 | −0.046115 / −0.033122 / −0.005772 | 5 | 5 |
| liquidity | 5 / 3 | −0.061856 / −0.045889 / −0.016925 | 2 | 2 |
| volume | 5 / 4 | −0.069731 / −0.018757 / −0.000017 | 2 | 2 |

The apparent closest-to-parity cell, `volume:ge_65000`, has only 38 rows, three
dates, and two markets: edge `−0.0000173523`, interval
`[−0.0000265055, +0.0000002500]`, Holm p 1, and family power 0.035. It fails
support and stability. The closest well-supported cell is
`signed_probability_gap:-0.05_to_0.05` with 98,266 rows, D=50, M=12: edge
`−0.0001458031`, interval `[−0.0002508048, −0.0000560251]`, Holm p 1, and
family power 0.359. Even where model and market probabilities nearly agree, the model
is detectably worse.

## P1 — break-even economics

The predeclared analytic sensitivity bound is:

```text
EV(e) = 2 Q phi [h + r(p) - f max(A - e, 0)] + L
r(p) = .25 * .05 * p * (1-p)
e_break_even = max(0, A - [h + r(p) + L/(2 Q phi)] / f)
Brier_break_even = 2 A e_break_even - e_break_even^2
```

Here `A` is the probability-point adverse move, `f` the informed-fill fraction,
`h` realized spread capture, `phi` fill rate, `Q` shares per side, and `L` daily
liquidity reward per band. The Brier mapping is optimistic: it assumes the model shift
correctly anticipates the informed move. It is a sensitivity bound, not a fitted flow
model or P&L claim. Both decisive inputs—`A` and `f`—remain unmeasured, so a unique
break-even cannot honestly be claimed.

The full Cartesian grid has 21,000 scenarios: five `A`, five `f`, five spread
captures, four fill rates, seven prices, three rewards, and two quote sizes, exactly as
declared. Required optimistic Brier advantage ranges from 0 to `0.0099974600`; its
overall median is zero. The retained grid SHA-256 is
`bc982479d3fd05456948474aad0ebee1904db384e11faeede736d7e58c8992da`.

| Reward L | Scenarios | Zero model edge sufficient | Required probability edge median / max | Required Brier edge median / max |
| ---: | ---: | ---: | --- | --- |
| $0 | 7,000 | 3,216 (45.94%) | 0.002406 / 0.098406 | 0.00003331 / 0.00999746 |
| $0.20 | 7,000 | 5,059 (72.27%) | 0 / 0.096406 | 0 / 0.00998708 |
| $1.00 | 7,000 | 6,229 (88.99%) | 0 / 0.088406 | 0 / 0.00986558 |

For the no-reward case, sensitivity to the unmeasured informed fraction is:

| Informed fraction f | Zero-edge share | Required probability edge median / max | Required Brier edge median / max |
| ---: | ---: | --- | --- |
| 0.10 | 79.43% | 0 / 0.084063 | 0 / 0.00974600 |
| 0.25 | 56.57% | 0 / 0.093625 | 0 / 0.00995936 |
| 0.50 | 42.29% | 0.004813 / 0.096813 | 0.00008194 / 0.00998984 |
| 0.75 | 26.86% | 0.010833 / 0.097875 | 0.00033331 / 0.00999548 |
| 1.00 | 24.57% | 0.013875 / 0.098406 | 0.00036248 / 0.00999746 |

With `L=0`, fill rate and quote size scale dollars and cancel from the break-even
edge. With fixed positive `L`, they determine reward amortization per fill. Scenarios
where zero model edge suffices support only market-centred spread/rebate/reward
harvesting. They do not rescue a model skew; P0 is negative in every cell.

## Quoteability and falsification

A valid captured best bid/ask exists on 51.4052% of rows. A valid book no wider than
4.5 cents exists on 45.8466% of all rows, or 89.1868% of valid-book rows. Every
book-spread cell nevertheless has negative model edge. The sealed tape has no
contemporaneous per-side size, so `rewardsMinSize` eligibility is **ABSENT**; aggregate
liquidity is not a substitute. There was no statistical candidate for these screens to
rescue or reject.

The mission's premise is falsified on the sealed population: it did not find any
quote-time-identifiable conditional window where the repaired distribution beats the
market, much less one that is adjusted, powered, stable, and quoteable. This redirects
model-skew work away from promotion. It does **not** falsify market-centred maker
economics; that depends on measured spread capture and informed flow, which remain the
right operational unknowns.

## Evidence and independent verification

| Evidence | SHA-256 |
| --- | --- |
| Repaired band rows | `9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae` |
| Measurement manifest | `cf21b67e3236395da800176c27e5c3a571a838e8cc28a491ec48e23e497e7c3e` |
| Predictor sidecar | `8d70d1e42022e3b808e320b000a04bcee33b0b8acef95cfcea3a37bba06a2341` |
| Predictor thresholds | `0830c6014353c4a1232162bf2837a964a17cf41a2258af3064d509a69225991f` |
| Predictor manifest | `bca60be854486ab34556f64aa38fa40ab1c100830056c0423664248696cab7a1` |
| Analysis summary | `056587d2b0fc7f80fdf7a74865f6500e97499f6d6e5641fdb9a444b673ef271c` |
| Partition results / committed companion | `8ce3d08fca5566489c1262df12987f7d119ba927b31916a4d1995569e3393d69` |
| P1 grid | `bc982479d3fd05456948474aad0ebee1904db384e11faeede736d7e58c8992da` |
| Fresh positive-control receipt | `b35a954a5b6ebd236f55304d73e89a4c149b598689a7f765947b3e3d885ca1b2` |
| Independent verification receipt | `e1366b374dc10b43b0efd81181585707033c946e2290c2db080c331b58f549ad` |

An independent ignored verifier returned **PASS** for: 840/840 exact positive
control; outcome-blind predictor phase; exact population and roster; 117 unique
hypotheses; all 114 non-empty points negative; direct hour, market, and season score
recomputation; exact axis coverage; and all 21,000 P1 formulas. Its bound analysis hash
is `056587d2b0fc7f80fdf7a74865f6500e97499f6d6e5641fdb9a444b673ef271c`.

Ignored workstation evidence lives at
`C:\Users\Michael\Documents\github\weather\scratch\runs\quotable-edge-2026-09-46a`.
It is local research evidence and is not represented as a production-host path.

## Mechanical roll verdict

`scripts\ops\roll_verdict.ps1 -Branch codex/workstation-does-a-quotable-edge-exist-2026-09-46a`
returned exit 0,
**ROLL-FREE**. The script retained the snapshot, CLOB, and observation-trigger
closures and mechanically subsumed the dormant CLOB-enrichment closure. The local
`master` ref is older than this branch's required `origin/master` base, so its printed
cumulative counts include intervening upstream changes; none entered a retained
closure. Production must rerun the command against its current master before
acceptance.

| Mission file | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/roadmap/quotable-edge-preregistration-2026-09-46a.md` | none | none | none | none | Roll-free documentation |
| `src/weather/reporting/research/quotable_edge.py` | none | none | none | none | Roll-free additive research module |
| `tests/reporting/test_quotable_edge.py` | none | none | none | none | Roll-free test |
| `docs/roadmap/agent-report-2026-08-09-workstation-quotable-edge.md` | none | none | none | none | Roll-free documentation |
| `docs/roadmap/agent-report-2026-08-09-workstation-quotable-edge-partitions.csv` | none | none | none | none | Roll-free report evidence |

All mission files are additive-only. Pushing this branch rolls nothing.

## Explicitly not done

- No candidate, calibration, artifact, release, partition, or confirmation window was
  fitted, generated, frozen, or promoted.
- No order was placed; no live or paper trading, market endpoint, provider, collector,
  paid source, credential, or network weather call was used.
- No production `data/`, workstation mirror, tape, ledger, settlement, trading
  evidence, scheduled task, collector, supervisor, or process was written or restarted.
- No gate, threshold, settlement authority, probability-mass rule, or known-defect
  fixture was weakened.
- No merge, production checkout, registration, master update, or branch deletion was
  performed.

## Production-host acceptance commands

The raw measurement is intentionally workstation-owned ignored evidence. The following
commands use paths that exist on production to verify the committed handback, full
117-row evidence, tests, documentation audit, and mechanical roll classification:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-does-a-quotable-edge-exist-2026-09-46a'
$report = 'docs/roadmap/agent-report-2026-08-09-workstation-quotable-edge.md'
$partitions = 'docs/roadmap/agent-report-2026-08-09-workstation-quotable-edge-partitions.csv'

git rev-parse $branch
git show "$($branch):$report"
git show "$($branch):$partitions" | Measure-Object -Line
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
git ls-tree -r --name-only $branch | Select-String 'agent-report-2026-08-09-workstation-quotable-edge'
.\venv\Scripts\python.exe -m pytest -q tests\reporting\test_quotable_edge.py
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Expected focused tests: 6 passed. Expected companion line count: 118 including the
header, with SHA-256
`8ce3d08fca5566489c1262df12987f7d119ba927b31916a4d1995569e3393d69`.
Expected roll result: `ROLL-FREE` (exit 0), subject to the required production rerun.

Branch:
`codex/workstation-does-a-quotable-edge-exist-2026-09-46a`.

Report-content commit: `fc0ea8601c3425f0a2c4c87c855b7236a26cc8e8`.
