# T+1/T+2 fair-value scoring

Status: canonical scorer interface and evidence contract.
Read when executing or reviewing `weather.market.maker_plugin.fair_value_score`.
The [frozen pre-registration](../research/t1-fair-value-preregistration-2026-09-25.md)
owns all estimator and statistical choices. This document supplies no scoring authority.

## Inputs and execution

Supply explicit [sealed replay bundle](maker-replay-bundle.md) directories, including
later settlement-only carry bundles. The scorer uses the 110l/110s envelope and
preserves additive `release_calibration_method` source-row evidence. T+0 is excluded.
It reads no production tree, mirror, provider endpoint, release artifact or credential.

The command refuses before 2026-10-09 UTC (the first day after the registered panel
closes), before opening any supplied bundle. There is no CLI clock override. The
owner-approved handoff 110u schedules the single real scored read for **2026-10-15**,
from the replay's same sealed exports and disclosed in its execution manifest.
Passing the calendar check alone is not permission for an earlier or repeated look.

**MG-1 refusal.** The [reserved confirmation window](reserved-confirmation-window.md)
holds plugin fair-value views out of every view-vs-outcome metric on MG-1 reserved
local target dates (every date from 2026-10-15 until D0 and its last date are recorded
in `maker_core.mg1_window`). `weather.market.mg1_metric_guard` is called first in
`score`, `main`, `Panel.settle` and the statistics tables. Before argument parsing,
`main` checks the registered panel's target dates; a refusal prints one stderr line
(`fair-value score refused: MG1Reserved: ...`) and exits 2 with no traceback. The
registered panel (09-25..10-08) lies wholly before the window, so the guard changes no
scored value and needs no pre-registration amendment. Bundle capture days are not
checked: a later settlement-only carry bundle captured on a reserved day is still
admitted for pre-window targets. `report.json` binds the guard's bytes through
`implementation_hashes`. MM paper scoring of fills is governed separately, by the
OD3 switch in `maker_core.mg1_window`.

From the qualified checkout, with caller-supplied paths (example names only):

```powershell
.\venv\Scripts\python.exe -B -m weather.market.maker_plugin.fair_value_score --bundle C:\sealed\capture-day-city --bundle C:\sealed\settlement-day-city --out C:\reports\t1-fair-value-once
```

`--bundle` repeats; `--out` must be a new directory under an existing parent and
must not overlap inputs. Inputs are opened read-only; output is create-only
`report.json` and `report.md`. Apply the [host load policy](HOST_LOAD_POLICY.md):
the scorer is heavy work, and this implementation does not add it to a host
admission allowlist. Its future real execution needs the execution manifest's
qualified host/admission path; fixture tests run through the existing pytest wrapper.
The entrypoint delegates local IO to `weather.market.maker_fair_value_score`,
outside the pure provider package, following the existing dry-run entrypoint pattern.

## Admission and sampling

The neutral reader verifies stream and payload hashes, seals, sizes, bounds and
paths. The scorer also rejects duplicate/overlapping condition exports, mismatched
registered market/event/native-unit/close identities, redirected paths, mixed
synthetic and captured provenance, and support clocks inconsistent with the export.
Fixed bundle, total-byte, record and time ceilings are in the scorer; overflow
refuses instead of truncating the panel.

Only local leads 1 and 2 on the frozen target dates enter sampling. A complete
capture must have an entire nonoverlapping open-tailed event partition, descriptors,
contemporaneous two-sided YES books and fair values for every sibling. Books from
different capture instants are never stitched together. Within each UTC hour the
first complete capture supplies that minute's observation; later captures do not
change it. Missing/invalid captures are counted by reason. Captured mids are used
unchanged, without probability renormalization across bands.

The unchanged weather estimator is evaluated solely from export-retained inputs
available by that capture, including provider issue/target validation. Its entire
view must match the captured view, including probability, declared stdev, joint
mass, input hash, source, expiry and grade. This validates retained provenance;
it does not fit or repair an estimator or substitute a newly served value.

Hourly selection is completed before joining labels. The latest supplied
reconciled settlement at scoring time must be after event close, have binary
payouts summing to one and share an event-wide ledger/revision binding. Missing or
conflicting facts exclude that selected hour; they never choose a later minute.
Hash-bound settlement projections rely on the bounded producer's ledger checks:
bundle hashes establish byte identity, not producer authenticity.

## Output and interpretation

The JSON records code tip, implementation and pre-registration hashes, every
manifest/stream hash, chosen captures and input/settlement bindings, coverage,
exclusions, target dates without scores, and per-market-day losses. Coverage is
conditional on supplied exports; an absent export is not proof of no activity.

Four primary source-by-lead tables (plain NBP and fallback) and one pooled
descriptive table over those two sources report paired mean band Brier. Tied-knot
NBP reads ([Amendment 2](../research/t1-fair-value-preregistration-2026-09-25.md#amendment-2--2026-10-01-mission-111l-before-any-panel-export-owner-decision):
`nbp-v2-piecewise-linear-atoms` and `-atoms-resolution-tails`) are scored in their own
`nbp_atoms_lead_<N>` and `nbp_resolution_tails_lead_<N>` tables and never pooled into
the primary or pooled tables. Brier is first averaged over hours per market-day and then equally over
market-days. Reliability bins count selected band-hours and report mean probability,
YES frequency and declared stdev. Independent date and market multiplicities are
multiplied on observed cells for 10,000 replicates, seed 110, with two-sided 90%
percentile intervals. Date-only sensitivity uses the same date draws. Undefined
sparse draws and empty-bin intervals remain unavailable, with their counts retained;
they never become zero losses. Cluster counts and UNDERPOWERED status apply to
each table separately. The Markdown includes both interval types and limitations.

There is no established numeric detectable effect or power from this descriptive
look, no significance/promotion gate and no live authority. Fallback spread is the
frozen zero-fit engineering prior, not measured climatological forecast error.
An interval crossing zero is not evidence of improvement.

## Update when

Update when the scorer's CLI or bundle admission/output contract changes. Any
estimator or scoring change requires a dated amendment before reading results;
never modify the frozen pre-registration to match a result.
