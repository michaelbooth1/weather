# Workstation report — restart model-vs-market skill tracking

Status: **IMPLEMENTED; POSITIVE CONTROLS PASS; PRODUCTION BACKFILL DEFERRED BY HOST-LOAD CONTRACT**

Branch: `codex/workstation-restart-skill-tracking-2026-09-19a`

Base: `6030d1f55fd48766d7f52c4825cf880cfdff3bff` (`origin/master`)

Handoff: `docs/roadmap/workstation-handoff-2026-09-19a-restart-skill-tracking.md`

## Outcome

The repository now has a durable, restart-safe model-versus-market skill
series before the first retrain lands. The producer is observational only: it
reads served `snapshots_long.csv` projections and the append-only settlement
ledgers, admits only `promotion_countable` labels, and never fits, promotes,
trades, mutates a release, or rewrites an earlier reported score.

The one-time production backfill was **not** launched. Host preflight at
2026-08-05 16:25 America/Toronto found healthy resources (25.3% committed,
9,417 MiB free RAM in the latest guard receipt, more than 50 GiB disk free),
but the clock was outside the policy's 00:30–09:00 heavy-work window. The
measured input is 741 snapshot tapes / 1,131,727,721 bytes plus 12 ledgers /
200,125,443 bytes. Launching that full scan in the graded 12:00–18:00 capture
window would violate `docs/operations/HOST_LOAD_POLICY.md`. No production
`data/` file was written, no task was registered, and no process was restarted.

The exact quiet-window backfill command is:

```powershell
.\venv\Scripts\python.exe -m weather.reporting.scorecards.model_market_skill_tracker backfill `
  --floor-control-rows tests\fixtures\reporting\model_market_skill_tracker\hard_floor_snapshot_deltas.csv `
  --cool-bias-control-rows tests\fixtures\reporting\model_market_skill_tracker\snapshot-centre-errors.csv
```

`refresh` fails closed without that checkpoint and refuses to reuse a checkpoint
whose positive controls did not pass.

## Why the old history stopped

`model_history.py` was not an operational producer. Its only normal caller was
`app/views/history.py`, where opening the Streamlit History view invoked
`build_history_payload(..., use_cache=True)`. There was no CLI and no scheduled
registration, so `data/backtest/model_history_cache.json` stopped moving when
the view stopped being opened. The cache was therefore dashboard-lazy state,
not a durable score history.

The shared scorer also used Toronto's calendar to choose completed target dates
for every market. Near midnight this could include an incomplete western-market
day or omit a completed one. Capture timestamps themselves were converted to
the market's timezone, so the defect was in date-window selection, not row-hour
assignment. The implementation now derives completed dates independently from
each `MarketSpec.timezone`, records UTC generation time, reads each physical
ledger once per build, and gives the ledger precedence over CSV/folder label
projections. The cache schema is now `model_history_cache_v0.4`.

## Why the live variant scorecard is all failures

The live variant settlement artifact is a release/variant-contract gate, not a
current model-skill series. Its sibling snapshot coverage is complete, but the
served rows on this pre-release host have blank `release_id`,
`release_identity_status=research_unbound_non_countable`, and no active release
pointer. The scorecard correctly requires an explicit immutable release ID for
promotion evidence (`live_variant_settlement_scorecard.py:676-677`).

There is a second, independent mismatch: the expected-variant manifest/registry
is a superset of the variants emitted on the live tape. The scorer deliberately
materializes absent expected partitions as `missing_variant_partition`
(`live_variant_settlement_scorecard.py:872-1012`). The current artifact records
83,434 missing expected variant partitions and 917,774 synthetic missing band
rows, while sibling snapshot coverage is 100%. Full sibling coverage proves
that the snapshot partitions exist; it does not prove that every expected
release variant was captured. Relaxing release identity or deleting expected
variants would turn a valid gate into a misleading skill claim, so this branch
does neither.

## Durable series contract

`weather.reporting.scorecards.model_market_skill_tracker` provides explicit
`backfill` and `refresh` commands.

- It reads `docs/operations/reserved-confirmation-window.md` before enumerating
  any settlement or snapshot evidence. Anything except the explicit current
  “none reserved” posture stops the run.
- The settlement authority is `data/settlements/<market>/ledger.jsonl`. Ledger
  hashes and supersession links are verified, restart checkpoints retain a
  full-ledger hash, and refresh verifies the old byte prefix before accepting an
  append. A disappeared, shortened, or rewritten prefix fails closed.
- Only current `promotion_countable` market-days enter weekly aggregates.
- Every served snapshot must contain exactly one winner and preserve model
  probability mass. An invalid snapshot blocks its tape instead of producing a
  partial score.
- Each market-day revision records model Brier, market Brier, their ratio and
  gap, plus exact bin-free CORP/Murphy reliability, resolution, uncertainty,
  and identity residual for both forecasters.
- Runtime commits are separated on the hard rescued-floor implementation anchor
  `b77cfbed49ee85cc0009a2058e842dda08036272`. Pre-anchor and post-anchor rows are
  never pooled. Dirty, missing, divergent, or unresolvable runtime identities
  receive their own `unclassified_runtime:*` regime.
- All capture hours and market-local 09:00–14:59 are independent series. The
  latter is explicitly a capture-time lane, not an effective WU print cutoff.
- Weekly points use equal market-day weight. Every inference object states its
  effective target-date clusters, market clusters, and market-days. Intervals
  use independent date and market pigeonhole resampling. The Brier-gap lane
  reports a one-sided noncentral-t MDE using the crossed fleet-date-equivalent
  standard deviation.
- Week-over-week Brier-gap contrasts resample dates independently inside each
  week with a shared market draw. If zero is in the interval, the report says
  exactly: “This week-over-week delta is not statistically distinguishable
  from zero.”
- The JSONL is hash-linked and append-only. Changed evidence appends a revision
  with `supersedes_revision_id`; withdrawn countability/regime/week support also
  appends a withdrawal revision. The JSON/Markdown files are replaceable current
  projections and restart checkpoints.

## Positive controls

The controls were rerun read-only from committed fixtures with 2,000
crossed-bootstrap replicates and seed `3215258335`. Both passed. The fixtures
retain every control row and only the five floor / three cool-bias columns read
by the tracker, reducing the two workstation exports from 7.0 MB to 1.5 MB
without changing any parsed input. Vendoring was chosen over regeneration from
production tapes because the compact fixtures are sensible to commit and make
the gate independent of both host-local scratch and mutable tape availability.

| Control | Reproduced point | Crossed 95% interval | Support | Source SHA-256 |
| --- | ---: | ---: | --- | --- |
| Observed hard-floor fix | ratio `1.6639158425` → `1.4979600580`; delta `-0.1659557845` | delta `[-0.3552671491, -0.0697874559]` | D=8, M=11, 85 market-days, 11,661 snapshots | `8ac77c0840b0ad6dd581cb0ecfc2449ffc5db53d788d715861c7411b07291405` |
| Raw cool HGB bias | `-0.6640809099` C-equivalent | `[-1.1164176910, -0.2481808356]` | D=34, M=12, 399 market-days, 9,360 selected-hour rows | `6505596010a3e8bba4c3475391f28becb2d3f594b3639414ca56b35822bfb298` |

The controls are mandatory for the first checkpoint. Later incremental runs
may reuse only the prior recorded `PASS`.

## Scheduling and estimated host cost

`scripts/ops/register_model_market_skill_tracker.ps1` defines, but this mission
did not register, `WeatherModelMarketSkillTracker` at 13:00 with a 30-minute
limit. It invokes `refresh`, never `backfill`.

The explicit first run reads approximately 1.33 GB of source files, plus one
streaming hash pass over each ledger, and materializes only one physical ledger
or one snapshot CSV at a time. The largest current ledger is 19,292,333 bytes;
the largest tape is 3,571,714 bytes. Routine refresh stats the known 741 tape
paths, reuses compact current labels for unchanged ledgers, and fully reads and
hashes only a changed ledger/tape. A normal newly settled day should therefore
be tens of MiB of reads, not a 1.33 GB historical rescan.

## Storage and schemas

- `data/backtest/model_market_skill_history.jsonl` is registered as
  `canonical_evidence`: originally reported revisions cannot be recreated
  honestly after code or settlement evolution.
- `model_market_skill_summary.json` and `model_market_skill_report.md` are
  operator caches/current projections.
- Public schemas `model_market_skill_history_v0.1`,
  `model_market_skill_summary_v0.1`, and `model_history_cache_v0.4` are in the
  registry.

## Roll safety by retained import closure

The verdict used the exact `runtime_identity.source_scope_files` arrays in the
four retained status files. They currently contain 77 snapshot, 23 CLOB, 85
observation-trigger, and 21 CLOB-enrichment files.

| Changed file | Recorded closure verdict |
| --- | --- |
| `src/weather/schema_registry_data.py` | Present in snapshot, CLOB, observation-trigger, and CLOB-enrichment closures. **Rolls every capture process; quiet-window integration required.** |
| `src/weather/reporting/scorecards/model_history.py` | Absent from all four closures. Capture-roll-free. |
| `src/weather/reporting/scorecards/model_market_skill_tracker.py` | New and absent from all retained closures; static ownership is reporting-only. Capture-roll-free. |
| `src/weather/operations/storage_classes.py` | Absent from all four closures. Capture-roll-free. |
| `scripts/ops/register_model_market_skill_tracker.ps1` | Status closures contain Python source only; script is roll-free and was not executed. |
| `README.md`, `docs/**`, and all changed tests | Not runtime module inputs. Roll-free. |

The branch is nonetheless **roll-sensitive** because the registry edit is in
all four captured closures. Integrate only through the 01:00–04:00 quiet-window
procedure. No adoption roll is authorized by this branch.

## Verification

```text
Focused scorecard, tracker, schema, storage, and staged import-architecture tests:
43 passed, 35 subtests passed

Complete repository suite:
3,290 passed, 823 subtests passed, 4 skipped; 18 unrelated failures. One is the
pre-existing historical-doc link below, four are Windows PowerShell contract
tests blocked because this host disables script loading, and thirteen are
experiment-executor fixtures exceeding the Windows path limit in the isolated
worktree. Retrying the executor file under C:\tmp reduced that group to 12
path-length failures and 12 passes; the changed files do not touch that owner.

PowerShell parser:
scripts/ops/register_model_market_skill_tracker.ps1 — PASS

compileall app src tests — PASS
git diff --check — PASS
```

`weather.operations.agent_docs_audit` also ran. It is blocked by one pre-existing
broken line link in
`docs/roadmap/agent-report-2026-08-02-workstation-spec-contract-repair.md` to the
retired `floor_retrain_gate_harness.py#L1079`; this branch does not edit that
historical report or reintroduce the retired file.

## Remaining operator action

1. Integrate this roll-sensitive branch only in the quiet-window deployment
   procedure.
2. During 00:30–09:00, re-run resource preflight and execute the exact backfill
   command above. Retain its summary/report and confirm both positive controls
   remain `PASS`.
3. Review the measured backfill host-cost receipt.
4. If desired, separately authorize and run the registration script. This
   report and branch do not grant that stateful authority.
