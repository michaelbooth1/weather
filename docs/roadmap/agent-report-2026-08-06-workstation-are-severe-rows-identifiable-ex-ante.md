# Workstation severe-tail ex-ante identifiability — 2026-08-06

**YES at the quoted band-row level; NO as a cheap whole-book or whole-day stand-down.** The
retained pre-`2026-07-31` replay reproduces the established tail exactly: **9,032 / 211,915 band
rows (4.262%) carry 60.205% of daily-normalized positive excess Brier**. A rule that flags a quoted
band when its captured model/market probability gap is at least 30 points reaches **100%** of that
tail loss while flagging **1.714%** of non-severe band rows. But the corresponding whole-snapshot
rule flags **40.156%** of snapshots and occurs on **every one of 108 market-days**. The defensive
lever, if the operator later chooses one, is therefore targeted band suppression, not standing down
the book or the day.

This is deliberately a trade-off curve, not an operating-point recommendation. The 30-point rule
is also **definition-adjacent**: the severe label requires a market-right error and an absolute
30-point selected-band gap. Its 100% reach does not discover new weather skill. The useful new fact
is the collateral cost and the evidence that additional captured market structure can trade away
some reach for less collateral without fitting a model.

## Evidence boundary and correction to the handoff's support count

| Field | Value |
| --- | ---: |
| Source branch base | `7ee6890b5e742c47e2ee61db8bacc73cbbdeccba` |
| Provenance stratum | `2026-07-22` through `2026-07-30`; entirely before `2026-07-31` |
| Date clusters | **9** |
| Market clusters | **12** |
| Promotion-countable market-days | **108** |
| Exact non-reconstructed snapshots | **19,265** |
| Band rows | **211,915** |
| Severe band rows / snapshots | **9,032 / 6,125** |
| Retained replay-row SHA-256 | `bc1d4e80d65c98274be6d976ead97a391467124304fba14081e47a11aee5b2e8` |
| Excluded snapshots after admission | **0** |

The handoff's `~2.23M snapshots across 15,174 settled market-days` is not independent support.
Those are the sums across the **append-only physical settlement revisions**:

| Ledger inventory | Physical/current records | Repeated/current reported snapshots | Repeated/current band rows |
| --- | ---: | ---: | ---: |
| Raw physical ledger | **15,174** | **2,227,249** | **24,518,615** |
| Current event labels only | **729** | **111,312** | **1,225,158** |

There are 588 current labels with `promotion_countable=true`. This mission admits the 108 labels in
the retained date window. A settlement revision is not a new market-day or snapshot, and summing
its copied `snapshot_count` / `row_count` again would pseudoreplicate the evidence. The new reader
selects the largest revision number per event with file order as the legacy tie-breaker, matching
the settlement-ledger contract, before it applies `promotion_countable`.

This correction does not change the retained severity result. The exact replay positive control is:

| Measure | Reproduced value |
| --- | ---: |
| Severe row rate | **4.262086%** |
| Severe share of daily-normalized positive excess Brier | **60.204971%** |
| Daily-normalized positive excess Brier | `2.854773260` |
| Severe contribution | `1.718715410` |

The handoff's `~98%` market-mode versus `~24%` model-mode headline does **not** describe the complete
fleet tail on this replay. Across all 9,032 severe rows here, the captured market mode is the winner
**75.266%** of the time and the model mode **17.560%**. The roughly 98/24 geometry belongs to the
previously retained five-band mechanism clusters; it must not be generalized to the other 80.22%
of severe contribution. No result below depends on that generalized headline.

## P0 — is there ex-ante structure?

Yes. The screen used no learned model and excluded the definition-adjacent selected-band gap from
the stop/go decision. Numeric dimensions were split into five bins using quantiles of the **feature
distribution only**, never the outcome. A group was called materially structured for this cheap
descriptive screen when it had at least 1% support and reached at least 1.5× baseline severe-rate
lift or loss-capture lift. This is a triage screen, not an inferential gate.

| Ex-ante dimension | Strongest group | Severe-rate lift | Loss-capture lift | P0 disposition |
| --- | --- | ---: | ---: | --- |
| Model/market total variation | q5 | **3.037×** | **3.420×** | structure |
| Market | Los Angeles | **2.114×** | **2.569×** | structure |
| Model/market modes disagree | true | **1.889×** | **2.069×** | structure |
| Model entropy | q3 | **1.650×** | **1.502×** | structure, non-monotone |
| Forecast disagreement | q5 | 1.341× | 1.472× | below screen |
| Model width | q3 | 1.397× | 1.315× | below screen |
| Cutoff hour | hour 19 | 1.293× | 0.990× | below screen |
| `forecast_high` − `high_so_far` distance | q5 | 1.237× | 1.262× | below screen |
| Forecast-source count | 4 | 1.061× | 1.080× | below screen |
| Market modal probability | q4 | 1.286× | 1.255× | below screen |
| Market top-two gap | q4 | 1.305× | 1.269× | below screen |

The cheap falsifier therefore does not stop the mission. The structure is mainly **captured
model/market disagreement and market identity**, not cutoff hour, source count, forecast spread,
or width alone. This agrees with the earlier conclusion that global sharpening is the wrong axis.

## P1 — reach and collateral, without choosing an operating point

`Tail loss reached` is the share of the fixed severe-tail daily-normalized positive excess inside
the flagged set. `Non-severe flagged` is the share of all non-severe band rows also flagged. The
snapshot and market-day columns show what would happen if a band trigger were escalated to standing
down the entire snapshot or day.

### Selected-band probability gap

| Gap threshold | Tail loss reached [crossed 95%] | Non-severe flagged [crossed 95%] | All band rows flagged | Snapshots touched | Market-days touched |
| ---: | ---: | ---: | ---: | ---: | ---: |
| ≥30 pts | **100.00% [100.00%, 100.00%]** | **1.714% [0.990%, 2.571%]** | 5.903% | 40.156% | 100.000% |
| ≥35 pts | 81.620% [69.907%, 89.051%] | 1.161% [0.559%, 1.888%] | 4.193% | 30.298% | 99.074% |
| ≥40 pts | 66.699% [51.168%, 77.289%] | 0.734% [0.323%, 1.282%] | 2.941% | 22.590% | 93.519% |
| ≥45 pts | 53.972% | 0.410% | 2.097% | 16.802% | 86.111% |
| ≥50 pts | 44.537% [26.589%, 59.691%] | 0.226% [0.057%, 0.545%] | 1.544% | 12.235% | 77.778% |

At 30 points, 72.198% of flagged band rows are severe. This precision is not independent validation:
below 30 points a row cannot satisfy the frozen severe definition. It is nevertheless the exact
answer to the maker-cost question: a band-level suppression rule has low row collateral, while a
book/day stand-down has high collateral.

### Captured market-structure refinements, always conditional on a ≥30-point band gap

| Additional captured condition | Tail loss reached [crossed 95%] | Non-severe flagged [crossed 95%] | All band rows flagged | Snapshots touched |
| --- | ---: | ---: | ---: | ---: |
| Market modal probability ≥0.40 | 95.403% [85.578%, 99.054%] | 1.537% [0.915%, 2.302%] | 5.496% | 37.379% |
| Market top-two gap ≥0.10 | 83.296% [70.353%, 92.265%] | 1.108% [0.590%, 1.812%] | 4.577% | 31.607% |

These refinements provide a real curve but no free separation. The market-top-two rule gives up
16.70% of tail loss to remove 0.607 percentage points of non-severe collateral; the modal-probability
rule gives up 4.60% of tail loss to remove only 0.177 points. Whether either exchange is economic
requires maker opportunity-cost evidence and an operator decision. This mission does not choose.

### Why whole-book stand-down is not the cheap lever

At a 30-point maximum gap, a whole-snapshot rule reaches the complete tail but flags **40.156%** of
snapshots and **37.492% [28.320%, 46.880%]** of non-severe band rows. A total-variation threshold
of 0.40 still touches **33.553%** of snapshots, reaches 88.192% [79.287%, 92.973%] of tail loss, and
flags 31.369% [22.619%, 40.832%] of non-severe rows. The triggering condition appears on virtually
every market-day. That falsifies the premise that the tail supports a cheap **day-level** stand-down.

## P2 — crossed inference and power

Intervals use 2,000 deterministic crossed bootstrap replicates, seed 932. Target dates and markets
are sampled independently with replacement and cell weights are the product of date and market
multiplicities. Support is **D=9 date clusters, M=12 market clusters, 108 crossed cells**. No pooled,
IID, or row bootstrap is reported.

The inferential contrast is severe-row risk inside the flagged set minus risk outside it. For the
illustrative rules above, every crossed interval excludes zero. Examples:

| Rule | Risk difference [crossed 95%] | Retrospective plug-in power |
| --- | ---: | ---: |
| Selected band gap ≥30 | `+0.721982` [`+0.617903`, `+0.822946`] | ~100% |
| Selected band gap ≥35 | `+0.722623` [`+0.599504`, `+0.837756`] | ~100% |
| Selected band gap ≥40 | `+0.740263` [`+0.608341`, `+0.851979`] | ~100% |
| Gap ≥30 and market top-two gap ≥0.10 | `+0.760513` [`+0.639544`, `+0.863281`] | ~100% |
| Gap ≥30 and market modal probability ≥0.40 | `+0.729689` [`+0.621549`, `+0.819441`] | ~100% |
| Whole-snapshot maximum gap ≥30 | `+0.106139` [`+0.087575`, `+0.124017`] | ~100% |

Power is the two-sided α=0.05 normal approximation using the observed risk difference and its
crossed-bootstrap standard error. It is a descriptive, retrospective plug-in calculation, not a
prospective confirmation design. The huge definition-adjacent contrast makes these rules powered;
it does not turn the nine already-used dates into unseen evidence. None of the reported illustrative
contrasts is “not distinguishable from zero.”

## Leakage controls, signal by signal

| Signal | Information cutoff | Enforcement |
| --- | --- | --- |
| Market and cutoff hour | Effective WU-print cutoff on a row captured at `captured_at_local` | Timestamp is timezone-aware and maps to `target_date` in the canonical market timezone. The effective cutoff may lag host wall clock, as required by contract. |
| Forecast disagreement / source count | Captured serving input at row timestamp | Exact replay rows only; `reconstructed=false` for all 19,265 admitted snapshots. |
| `high_so_far` to `forecast_high` distance | Both values in the same captured serving input | Computed only when both captured fields are present. No realized high enters. |
| Model entropy / width | Replayed distribution from the captured serving input | Computed over the complete band partition before settlement is used. |
| Market quote structure | Same-snapshot `market_yes` band quotes | Computed across one timestamped band partition. |

Settlement, realized winner, and Brier loss are used only after the captured signals are assembled,
to assign the retrospective severe label and measure reach. The implementation excludes settlement
high/bucket, `settlement_distance`, winner-midpoint distances, same-day aggregates not retained in
the captured serving input, undated inputs, and reconstructed rows from every rule. Every candidate
signal has a stated cutoff; no undated signal is silently retained.

The dates are already-used retrospective engineering evidence. No fitting, threshold selection by
outcome, candidate scoring, promotion, or unseen-day claim occurred. Quantile boundaries in P0 use
only the marginal feature distribution. P1 reports fixed threshold grids and selects no operating
point.

## Evidence artifacts

The ignored workstation packet is rooted at
`C:\tmp\weather-severe-rows-09-32a\scratch\runs\severe-tail-ex-ante-09-32a`.

| Artifact | SHA-256 |
| --- | --- |
| `analysis.json` | `fb933a93ad350a7eee3af24db7b78e128c27e50e07e06963d584d1f59322ca8c` |
| `analysis.md` | `2ec7c04153e2e4c1298ef7c3a65dec2010a647d5ab02375027006fa165ad8dc1` |
| Retained input `current-window-replay-rows.csv` | `bc1d4e80d65c98274be6d976ead97a391467124304fba14081e47a11aee5b2e8` |

## Production-host reproduction

The replay covers 108 market-days, so run it only inside the production heavy-work window
(`00:30–09:00`). It reads canonical production `data/` and writes derived output only under
`C:\tmp`; it does not write production state.

```powershell
$productionRepo09x32 = 'C:\Users\micha\Desktop\github\weather'
$verifyWorktree09x32 = 'C:\tmp\weather-severe-tail-09-32a'
$runRoot09x32 = 'C:\tmp\severe-tail-ex-ante-09-32a'
$branch09x32 = 'codex/workstation-are-severe-rows-identifiable-ex-ante-2026-09-32a'
$python09x32 = Join-Path $productionRepo09x32 'venv\Scripts\python.exe'

git -C $productionRepo09x32 fetch origin $branch09x32
if (-not (Test-Path -LiteralPath $verifyWorktree09x32)) {
    git -C $productionRepo09x32 worktree add --detach $verifyWorktree09x32 "origin/$branch09x32"
}
New-Item -ItemType Directory -Force -Path $runRoot09x32 | Out-Null
Set-Location $verifyWorktree09x32

& $python09x32 -m weather.reporting.casebooks.severe_tail_ex_ante `
    --snapshots-root (Join-Path $productionRepo09x32 'data\snapshots') `
    --data-root (Join-Path $productionRepo09x32 'data') `
    --settlements-root (Join-Path $productionRepo09x32 'data\settlements') `
    --start-date 2026-07-22 `
    --end-date 2026-07-30 `
    --provenance-stratum before_2026_07_31 `
    --out-json (Join-Path $runRoot09x32 'analysis.json') `
    --out-report (Join-Path $runRoot09x32 'analysis.md') `
    --bootstrap-replicates 2000 `
    --bootstrap-seed 932

$result09x32 = Get-Content -Raw (Join-Path $runRoot09x32 'analysis.json') | ConvertFrom-Json
if ($result09x32.support.row_count -ne 211915) { throw 'band-row reproduction failed' }
if ($result09x32.support.snapshot_count -ne 19265) { throw 'snapshot reproduction failed' }
if ($result09x32.support.market_day_count -ne 108) { throw 'market-day reproduction failed' }
if ($result09x32.support.severe_row_count -ne 9032) { throw 'severe-tail reproduction failed' }
if ([math]::Abs($result09x32.support.severe_loss_share_of_positive_excess - 0.6020497088951711) -gt 1e-12) {
    throw 'severe-loss-share reproduction failed'
}

& $python09x32 -m pytest tests\reporting\test_severe_tail_ex_ante.py -q
& $python09x32 -m pytest tests\operations\test_import_architecture.py -q
```

## Verification

| Check | Result |
| --- | --- |
| `tests/reporting/test_severe_tail_ex_ante.py` | **6 passed** |
| `tests/operations/test_import_architecture.py` | **21 passed** |
| `python -m compileall -q app src tests` | **PASS** |
| Full `tests/reporting` package | **WORKSTATION-BLOCKED at collection** — bundled Python is 3.12 while the broken project venv contains CPython 3.11 NumPy extensions |
| `weather.operations.agent_docs_audit` | **BASELINE FAIL** — unrelated pre-existing broken link in `agent-report-2026-08-02-workstation-spec-contract-repair.md` |
| Full retained replay / severity positive control | **PASS**, exact 211,915 / 9,032 / 60.204971% |
| Crossed bootstrap | **2,000 replicates**, seed 932, D=9, M=12 |
| Current ledger admission | **PASS**, 108/108 selected market-days promotion-countable |
| Reconstructed/undated exclusions | **PASS**, 0 admitted exceptions |

## Per-file roll verdict

| File | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `src/weather/reporting/casebooks/severe_tail_ex_ante.py` | not in closure | not in closure | not in closure | not in closure | **ROLL-FREE** — additive module, imported only by its CLI/test |
| `tests/reporting/test_severe_tail_ex_ante.py` | not runtime code | not runtime code | not runtime code | not runtime code | **ROLL-FREE** |
| `docs/roadmap/agent-report-2026-08-06-workstation-are-severe-rows-identifiable-ex-ante.md` | docs excluded | docs excluded | docs excluded | docs excluded | **ROLL-FREE** |

No existing runtime module imports the new casebook. No schema-registry file changed. The production
agent should still rederive the closure before merge as required by the delegation contract.

## Explicit non-actions and handback identity

No model was fitted; no candidate or artifact was produced; no global sharpening was attempted; no
maker configuration, quote, trade, or market file was touched; the observed-high floor was not
changed. There was no production write, mirror write, registration, scheduled-task mutation,
restart, pointer change, promotion, PR, merge, master push, or branch deletion.

- Branch: `codex/workstation-are-severe-rows-identifiable-ex-ante-2026-09-32a`
- Base: `7ee6890b5e742c47e2ee61db8bacc73cbbdeccba`
- Implementation commit: `a81fc963e0d337db2e12b7b2c34d13ba9f268c7e`
- Report path: `docs/roadmap/agent-report-2026-08-06-workstation-are-severe-rows-identifiable-ex-ante.md`
