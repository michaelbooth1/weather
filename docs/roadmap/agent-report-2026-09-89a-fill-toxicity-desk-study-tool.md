# Mission 89a — fill-toxicity desk-study implementation

**PASS — synthetic implementation and verification. No production study was run and no empirical trading verdict is claimed.**

This is the workstation handback for mission 89a. It records the executable input contract, verification and reproduction commands. Research authority remains the frozen handoff, pre-registration and R rule on `origin/codex/reward-test-attended-handoff-20260921`, through Clarification 8 at `c203ff8d23538b57a2558b70bb01945e6003f1be`.

Branch: `codex/fill-toxicity-desk-study-20260923`. Tested implementation commit: **`9e36246b694b3664911638e818fb2471bc23e4c0`**. This report is a separate documentation commit on that implementation. Base: `origin/master` at `198f7ccbcd8e80271693462425582097d22b298b`; the required markout tip `6556baa72e7830f0778cd22288b837db5a940ff8` is already an ancestor.

## Production reproduction

The production operations agent owns execution, after checking current reserved-window and host-load policy. Run serially inside **00:30–09:00**, holding the repository's shared heavy-work lease; verify the production memory/disk admission requirements and end the child before 09:00. These commands are the CLI payload for that admitted job, run from the reviewed study checkout. They were not executed against production or the workstation mirror.

```powershell
$studyRepo = (git rev-parse --show-toplevel).Trim()
$studyProductionRepo = Split-Path -Parent ((git rev-parse --path-format=absolute --git-common-dir).Trim())
$studyPython = Join-Path $studyProductionRepo 'venv\Scripts\python.exe'
$studySnapshots = Join-Path $studyProductionRepo 'data\snapshots'
$studySettlements = Join-Path $studyProductionRepo 'data\settlements'
$studyOutput = Join-Path $studyProductionRepo 'scratch\fill-toxicity-89a-20260923'
$studyArguments = @(
    '-m', 'weather.market.fill_toxicity_desk_study',
    '--snapshots-root', $studySnapshots,
    '--settlement-root', $studySettlements,
    '--max-dates', '40',
    '--output-dir', $studyOutput
)
& $studyPython @studyArguments --dry-run
if ($LASTEXITCODE -ne 0) { throw 'Study inventory refused' }
# Review the named inventory and retention before the first scoring read.
& $studyPython @studyArguments
if ($LASTEXITCODE -ne 0) { throw 'Study refused; retain its partial output namespace' }
```

The output directory must be new or empty and outside every `data` directory. A refused attempt does not overwrite old evidence; use a new named directory for a repaired attempt. `--max-dates N` selects the first N dates starting 2026-08-15, not the first N usable dates. A smaller bound is a partial run and is not the full frozen study. Open local event days are omitted. Forty covers the inclusive frozen date range through 2026-09-23.

If the retained economics or trigger records live elsewhere, add `--support-manifest <absolute JSON path>` to **both** commands. This is a map of event slugs to exact captured file paths, not a precomputed scientific panel. For example, each event entry can contain `weather`, `rewards`, `triggers`, `gaps`, and `iem` path lists, an optional `ledger` path, and `reconstruct_e2: true` when trigger retention is known to have been lost. There is no search of campaign roots, worktrees, archives, or arbitrary data directories. Do not point it at RE-1 evidence.

## Inputs and outputs

- The planner names each built-in market/date folder from the registry. It lists only that event's `execution_tape` directory. It selects `order_books.jsonl` or `.gz`, `order_books_summary.csv` or `.gz`, `replay_inputs.jsonl` or `.gz`, captured reward records/configurations, execution trade partitions, the tape's gap/status records, the named observation-trigger sidecar, and the per-market settlement ledger. Dry-run stats these exact paths without opening tape content.
- Reward adapters accept timestamped per-condition records, captured economics snapshots (`markets` with `liquidity_rewards`), and embedded snapshot configurations. There is no current-rate backfill. Missing values remain missing; numeric zero is usable. A stale preferred per-condition record remains missing rather than falling through to a different source. No captured term/configuration means no panel band; unusable captured terms still establish a panel band for the frozen band-minute denominator.
- Book and trade records stream into a temporary SQLite store for one event-date. Venue timestamps determine print order; duplicate identities use the inherited markout rule. YES and complementary NO prints feed the same virtual YES-equivalent quote. Raw depth constructs adjusted midpoints and competing scores; summary CSV is used for coverage only.
- Normalized snapshot temperatures retain native units, including legacy `temp_c` fields. E3 uses the captured routine hourly stream and WRH :51–:59 filter, rejects explicit SPECI reports, and applies native half-up rounding. Toronto uses unfiltered captured WU rows. Open-top bands have no E3 event. Detection times remain distinct from report times.
- E1 modal minutes are measured over distinct captured routine reports in the named date range. A tied modal minute refuses the run. Missing own-snapshot observations cannot be replaced with IEM for E3 under Clarification 6. The declared external E2 reconstruction accepts named offline IEM CSVs (`station`, UTC `valid`, Celsius `tmpc`, optional `metar`), reconstructs running-high increases/native bucket changes, labels the result `IEM_RECONSTRUCTION`, and never invents detection times. The tool performs no network fetch.
- Settlement follows the canonical ledger revision selection and canonical label normalization. `polymarket_winning_band` wins; the WU bucket fallback is explicitly flagged. A missing settlement row removes only that horizon.
- Outputs are `fill_toxicity_desk_study.json`, its Markdown verdict/limitations summary, `date_market_sums.sqlite`, and compressed `intermediates.jsonl.gz`. Intermediates include quote prices and distances, terms, exposure/reward segments, fills and markouts, event windows, and removed leg/quote minutes. Exclusions and removed fills are counted by date-market, band, scenario, horizon and event group.

## Accounting and inference

The implementation keeps the three frozen populations separate:

1. **CR:** each non-settlement horizon has its own leg-minute panel. Both endpoint markouts must exist within 120 seconds. A missing fill markout removes that leg-minute's complete exposure and every fill. Settlement keeps its separate settlement-row rule.
2. **Net pull and kill:** a UTC quote-minute enters only when both legs survive the 30-minute panel. Both losses and the original canonical joint reward enter together. Reward is neither split nor recomputed for a surviving leg. All seven predeclared window sets are reported; the highest point net pull selects the kill-test set.
3. **R:** one full-panel computation for each distance/fill-rule/population scenario, with its date bootstrap and `share_single` sensitivity. Horizon markout availability never trims its reward or filled-share denominator. Valid zero-reward minutes remain in this population.

The primary CR uses 1.5 cents, conservative fills, ordinary book midpoints, 30 minutes and E1/E2/E3 union against outside all E1–E5. One minute is descriptive. Outputs retain 2.5 cents, optimistic fills, adjusted markouts, each event class, placebo and detection-time E2 sensitivities; net pull includes k_share 0.5 and share_single sensitivities. Rebates are zero.

Bootstrap resamples complete dates, with the inherited seed 20260919, 2,000 replicates and 90% intervals. The mandatory crossed date × market sensitivity independently samples each dimension and multiplies weights; it does not replace the frozen primary. Reports expose date clusters, market clusters and market-days. Under ten dates forces the primary INCONCLUSIVE/UNDERPOWERED result. Undefined ratios remain null. Real-data cluster counts are unknown: only synthetic inputs were used here.

Implementation conventions under Clarification 3's default rule: UTC calendar minute identifiers, half-open event windows, actual elapsed resting-share exposure, any gap overlap marking that expected minute dark, and equal-timestamp prints consuming the old quote before replacement. Missing-term withdrawal and five-minute expiry precede such prints. Equal best-set point estimates use a stable name tie-break. The quote population stays tied to its selected adjusted midpoint. These conventions are visible in retained intermediates; no scientific threshold was fitted or changed.

## Verification and resource profile

All heavy verification used `scripts/ops/workstation_heavy.ps1`, its unchanged workstation admission profile and an explicit owned pytest `--basetemp`. The attending principal was required; no admission controls were altered. Verification finished before 19:00 ET on 2026-09-23.

- Expanded run: **149 passed in 217.62 seconds**, covering the study, inherited execution markouts, canonical reward estimator and import architecture. It included both large synthetic controls.
- Final run after adding the crossed-cluster and real CLI-inventory controls: **149 passed, 2 deselected in 17.14 seconds**. The two unchanged large synthetic controls had already passed. This is **151 distinct passing checks** across the two runs, not a claim of a full repository suite.
- Focused `compileall` of all five study modules and the test file: exit 0. Staged diff whitespace check: clean.
- Large end-to-end synthetic date: **100,000 trades, 1,440 depth captures, one date, one market, one band; 184.563 seconds**. Peak traced Python allocation **6,174,971 bytes**; process-lifetime peak working set **125,665,280 bytes**, including the test interpreter and imports. This is a synthetic resource measurement, not a production throughput promise.
- Separate 100,000-trade ingestion/sort/iteration control: **31,420 peak traced Python bytes**. Individual JSONL records are bounded at 16 MiB. SQLite caches are 4 MiB per connection; temporary sorting uses disk, and only one event-date is staged at a time. The Python allocation budget is 256 MiB, with refusal rather than a truncated verdict if exceeded; explicit observation/band bounds also refuse instead of dropping records.

The verified test payload was:

```powershell
python -m pytest tests/market/test_fill_toxicity_desk_study.py tests/market/test_execution_tape_markout.py tests/market/test_reward_share_estimate.py tests/operations/test_import_architecture.py -q -s --basetemp <owned-absolute-test-directory>
```

On the workstation this payload must be passed through `workstation_heavy.ps1 -Kind pytest`; on production it remains subject to the bounded-suite and admission contract. Synthetic controls cover partial fills, sample-only repricing, expiry, missing terms, both horizon endpoints, whole-leg fill removal, joint quote-minute removal, full-panel R, all event classes, placebo overlap, native Toronto data, IEM labelling, settlement authority, exact decision/kill boundaries, fixed-seed inference, crossed clustering and dry-run content isolation.

## Roll verdict and boundaries

Per-file production roll verdict is **not measured on this workstation**. Production must run `scripts/ops/roll_verdict.ps1 -Branch codex/fill-toxicity-desk-study-20260923` against its retained live closures before integration. No import-closure verdict was derived by hand.

| Files | Roll evidence |
| --- | --- |
| `src/weather/market/fill_toxicity_desk_study.py` | Production tool verdict required |
| `src/weather/market/fill_toxicity_inputs.py` | Production tool verdict required |
| `src/weather/market/fill_toxicity_model.py` | Production tool verdict required |
| `src/weather/market/fill_toxicity_panels.py` | Production tool verdict required |
| `src/weather/market/fill_toxicity_statistics.py` | Production tool verdict required |
| `tests/market/test_fill_toxicity_desk_study.py` | Included in production branch verdict |
| This report | Markdown is roll-free by the standing contract |

No real execution/book/weather tape was read; no `.env`, credentials, RE-1 worktree or campaign root was accessed. No production writes, registration, Scheduler changes, live orders, worker restarts, master merge, or runtime adoption occurred. The worktree and topic history are retained for review. Pushing this branch is authorized and does not adopt it on production.
