# Workstation report 2026-08-05 — clear the forecast archive gate

## Sourcing answer and stop-condition verdict

**STOP. The late-July extension cannot be collected under the evidence currently in the
repository.** No provider was called and no archive was built.

The technically intended source is the repository's existing Open-Meteo Previous Runs
integration. It is not a new endpoint, it requires no credential, and current archive manifests
already name it with `start_year=2021`, leads 1–7, and model `best_match`. That establishes technical
reuse, not permission to collect the missing rows. The accepted `-08-28a` scoping report says the
free service is contractually limited to non-commercial use and makes execution conditional on the
repository owner confirming that the existing use qualifies. I found no later canonical operator
decision recording that confirmation. The missing July/August rows are not already captured, and
this handoff explicitly says not to assume that a free tier is acceptable.

There is a second, independent source blocker. The retained `-09-12a` preflight derives its expected
years from the source manifest. Against the real manifests that is 2018–2025, but the accepted PIT
plan is 2021–2025 and the prior provider analysis found no coherent, issue-qualified version of the
current forecast contract for 2018–2020. Clearing the actual retained matrix would therefore require
either a newly approved source/provider or an explicit retrain-population decision plus a preflight
repair. Silently changing `covered_years` would exploit a self-declaration defect; it would not clear
the gate honestly.

Per the handoff's stop condition, I stopped before a feasibility probe, request plan execution,
collection, archive materialization, source edit, retrain, fit, release/PIT change, serving change,
or scheduled-task action. Network use is limited to `git fetch` and the final exact-branch push.

## Scope and safety boundary

This branch starts at refreshed `origin/master @ 7348365b873c4c64810b48efc03352637193078e`
and is `codex/workstation-clear-the-forecast-archive-gate-2026-09-16a`.

The reservation contract was re-read: **no dates are reserved today**; the confirmation window is
armed but undated. No `data/` file was written. The active forecast archive, release pointer, PIT
release path, trusted observed-high floor, promotion gate, model artifacts, candidates, schedules,
capture processes, and live serving inputs are unchanged.

## Prior work reconciled

| Prior evidence | Reused | Superseded, contradicted, or still open |
| --- | --- | --- |
| `agent-report-2026-08-03-workstation-scope-forecast-archive-extension.md` | Reused its provider boundary, 2021–2025 Previous Runs option, rejection of stitched rows, immutable-plan/resume/atomic-publication design, serving-path trace, and separate analog activation gate. | Its “training-only corpus” wording is superseded as a complete system description: `model_features.py` still reads the ambient daily archive on the analog serving path. The separate corpus can be training-only only because it remains unreachable from that path. Its operator-license confirmation remains open, so collection is not authorized by the report itself. |
| `agent-report-2026-08-03-workstation-size-the-forecast-lookahead.md` | Reused the finding that daily scalars, forecast profiles, forecast-relative marine fields, forecast-error rows, late-day continuation, and analog distance must share one cutoff-valid resolver or be explicitly excluded. Reused its rejection of `forecast_daily.csv` as PIT evidence. | Nothing contradicted its measured lookahead. Its recommendation is incomplete until the exact retrain matrix and the serving activation contract are bound together. |
| `agent-report-2026-08-03-workstation-build-pit-forecast-corpus.md` | Reused its content-addressed corpus, raw/request/issue hashes, exact cutoff selection, explicit reader, and no-ambient-fallback contract. | Its 2021–2025 plan is only a proposed request contract, not provider-support or license evidence. It does not satisfy the retained preflight's current 2018–2025 matrix. |
| `agent-report-2026-08-05-workstation-build-the-first-retrain.md` | Reused its six independent fail-closed gates and retained-production evidence. | Its claim that the preflight already specifies the complete matrix is contradicted by the implementation: expected years are taken from the candidate source manifest, and the passing fixture proves a 2025-only declaration is accepted. |

Neither rescued scoping branch clears a retained blocker. `-08-28a` is design evidence only;
`-08-29a` is measurement evidence only. This verifies the `-09-15a` disposition rather than assuming
it.

## P1 — coverage the first retrain actually requires

The explicit retrain alignment target in `-09-12a` is `2026-07-31`. Its preflight applies a ±7-day
seasonal window to every declared prior year and enumerates local cutoff hours 07 through 20.

Against the 12 real source manifests, all of which declare covered years 2018–2026, the exact
retained-production matrix is:

| Dimension | Exact value |
| --- | --- |
| Markets | all 12 live registry markets |
| Training years selected by the current preflight | 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 |
| Dates in each year | July 24 through August 7 inclusive |
| Dates per market | 8 years × 15 dates = **120** |
| Cutoffs | local hours **07, 08, …, 20** |
| Cells per market | 120 × 14 = **1,680** |
| Fleet cells | 12 × 1,680 = **20,160** |
| Current archive dates in that matrix | **0** |

Every real manifest ends its season on June 30. The first required date is July 24, so none of the
120 target-aligned dates per market is admitted by the current season window. This agrees with the
handoff's expected zero-row result.

### Second defect: the matrix is not immutable

The preflight does not take required training years from the explicit retrain plan. It computes them
from `source_payload.covered_years`. Its passing synthetic control declares only `[2025, 2026]` and
therefore passes with 15 dates and 210 cells per market (2,520 fleet cells). The held PIT plan instead
predeclares 2021–2025, which would require 75 dates and 1,050 cells per market (12,600 fleet cells)
for this target-aligned slice.

Therefore three matrices currently exist:

| Contract | Years | Fleet cells |
| --- | ---: | ---: |
| Retained production manifests + `-09-12a` preflight | 2018–2025 | **20,160** |
| Held PIT request plan | 2021–2025 | **12,600** |
| `-09-12a` passing synthetic fixture | 2025 | **2,520** |

Per the handoff, the preflight wins for today's blocker count: the required matrix is 20,160 cells.
But the variability is itself a defect. Before a future build, required years must move into the
explicit, hash-bound retrain plan (or an equally authoritative policy object); the source manifest
may prove coverage of that matrix but may not choose its size.

## P2 — manifest binding and why no extension was published

The gate requires all of the following for each market:

1. a hash-bound source manifest covering every required date;
2. an exact market/date/cutoff coverage manifest with issue identity, issue time,
   conservative availability time, cutoff time, PIT status, verified provenance,
   source-manifest hash, and cell hash;
3. a hash-bound feature-record JSONL with exactly the same keys and source/cell hashes; and
4. immutable file identity verified before and after reading, with duplicates, extras, omissions,
   stitched identities, post-cutoff availability, and provenance mismatch all blocking.

The held PIT implementation adds the necessary lower-level request, raw-response, issue, hourly
profile, daily selection, and publication hashes. Those are compatible requirements, but no real
corpus exists and the requested years disagree.

`data/forecast_history/*/forecast_daily.csv` remains unreachable from the retrain evidence and fit
paths. It was not read as a substitute, extended, overwritten, or rebound. No coverage declaration
was changed because changing the declaration without the exact hashed bytes would reproduce the
defect this mission exists to prevent.

## P3 — seam with `point_in_time_forecast_binding`

The gates are two views of one contract:

- `forecast_archive_coverage` asks whether the exact expected cell exists and is bound through the
  source manifest into the feature record;
- `point_in_time_forecast_binding` asks whether that same cell has a non-stitched issue identity and
  was issued and available no later than the row cutoff.

A correct corpus would make gate 2 **easier and satisfiable**, because one coverage cell, selection
hash, and feature-record provenance chain would answer both gates. Widening the legacy stitched
archive or merely changing its season declaration would leave gate 2 blocked and would contradict
the shared contract.

The present 2018–2025 preflight versus 2021–2025 PIT-plan disagreement makes the seam harder: the
PIT builder cannot supply the first three years under its approved technical design, while the
preflight can be made to forget those years by self-declaration. The repair must bind one explicit
year set into both implementations and prove that mutating a raw hash, coverage cell, selection, or
feature-record binding makes the retrain refuse before fit.

## P4 — blocker proof

The retained `current-preflight.json` is SHA-256
`732f3ea96b3b859589ea326b76b2d1f389e1bdd093e8258a4bfcf5f9143e1d20`, status **BLOCK**,
`fit_authorized=false`, with 97 blockers. Because the source stop condition fired before any valid
new evidence could be built, the before/after counts are intentionally identical:

| Gate | Before | After | Movement |
| --- | ---: | ---: | ---: |
| `forecast_archive_coverage` | **36 BLOCK** | **36 BLOCK** | 0 |
| `point_in_time_forecast_binding` | **24 BLOCK** | **24 BLOCK** | 0 |
| `train_serve_feature_parity` | **1 BLOCK** | **1 BLOCK** | 0 |
| `class_support` | **12 BLOCK** | **12 BLOCK** | 0 |
| `candidate_specific_calibration` | **12 BLOCK** | **12 BLOCK** | 0 |
| `artifact_regime_boundary` | **12 BLOCK** | **12 BLOCK** | 0 |
| **Total** | **97 BLOCK** | **97 BLOCK** | **0** |

All other five gates still block, as required. A forecast-only PASS was not fabricated from a
license assumption, a reduced self-declared year set, stitched data, or synthetic evidence.

## Live-serving effect, separate enable, and revert

**This mission changes nothing for live serving.** The active analog path still resolves
`daily_path_for(spec)` and reads the existing May 10–June 30 `forecast_daily.csv`. The new PIT corpus
path was not merged, collected, published, or made discoverable.

The eventual safe enable must be a separate, named **release-bound analog-v2 activation** after the
training corpus has been accepted. It must bind one content-addressed corpus ID into a reviewed
serving release and pass that explicit resolver to analog construction; it must never widen or
replace the ambient daily file in place. Based on the traced current call graph, this activation may
change historical analog forecast gaps, neighbor identities/order/distances/similarities,
settlement-bucket composition, and explanatory UI. It must not change the base feature vector,
probability distribution, top temperature, boundary transition, or late-day output; any such change
is a hard block.

Revert is selecting the prior reviewed release/corpus binding and re-adopting the normal serving
processes. Because publication is content-addressed and the ambient archive is never overwritten,
rollback does not require reconstructing deleted bytes or reversing a mutable archive backfill.

## Per-file roll-safety verdict

Roll safety is by the retained capture-loop import closures, not `SOURCE_PATTERNS`.

| Changed file | In snapshot, CLOB, observation-trigger, or enrichment import closure? | Verdict |
| --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-05-workstation-clear-the-forecast-archive-gate.md` | No; dated documentation is not imported by a runtime loop. | **Roll-free.** No capture-loop or worker restart is required. |

No source, schema registry, config, artifact, script, test, or runtime file changed. The branch is
therefore roll-free.

## Merge-order placement

This report is a roll-free decision record and can be reviewed independently; it does not occupy a
quiet-window code slot. The implementation must not become a standalone archive change ahead of its
consumer.

The existing program remains `-09-11a` → `-09-14a` → refreshed `-09-01a` alone → `-09-04a` →
refreshed `-09-12a` plus the PIT seam. The explicit required-year repair, approved source contract,
real content-addressed corpus, and exact PIT-to-feature binding belong in the final refreshed
`-09-12a` + PIT seam. The source/license and 2018–2020 population decision must be closed before the
real collection portion of that step begins.

## What would falsify this

- A canonical operator record confirming that the repository's intended Open-Meteo Previous Runs
  collection is licensed for this use would falsify the licensing stop, but not the 2018–2020
  support or matrix defects.
- Hash-verified, already captured July 24–August 7 issue-qualified rows for every required market,
  year, field, and cutoff would falsify the “new collection required” finding. The inspected archive
  manifests instead end June 30 and report zero Previous Runs rows for 2018–2020.
- Provider evidence proving one approved non-stitched contract covers the complete required
  2018–2025 field matrix would falsify the source-support blocker.
- An explicit hash-bound retrain policy fixing required years independently of the source manifest,
  plus a test showing that reducing `covered_years` cannot reduce expected cells, would falsify the
  self-declaration defect.
- A real exact-manifest corpus whose 20,160 coverage cells and matching feature records make only
  `forecast_archive_coverage` move from 36 to zero would falsify the unchanged gate result. Any
  unintended movement in another gate would remain a finding.
- Finding a current serving path that cannot reach `load_forecast_daily(daily_path_for(spec))` would
  falsify the activation boundary. The inspected analog path still reaches it.
- Any source, artifact, release pointer, PIT release, active archive, or live output changed by this
  branch would falsify its safety verdict. The branch changes only this report.

No PR was opened and no merge was performed.
