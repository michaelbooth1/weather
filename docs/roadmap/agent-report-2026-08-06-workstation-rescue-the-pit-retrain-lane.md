# Workstation report 2026-08-06 — rescue the PIT retrain lane

## Verdict

`codex/workstation-consolidate-merge-queue-2026-09-01a` is the surviving
retrain lane, but the handoff's highest-priority falsifier fired before repair.
The held lane did not read `source_payload.covered_years`, yet its PIT selection
was still sized from candidate-supplied `selected_dates` and candidate-supplied
count/minimum fields. The absence of the named defect was accidental rather
than a safe design property. Before this rescue, neither lane was safe.

The rescue now binds the first-retrain population into the self-hashed retrain
plan: years 2021-2025, target month/day +/-7 days, cutoff hours 07-20, and all
12 built-in markets. Candidate evidence can prove that matrix but cannot shrink
it. For target 2026-07-31 the gate requires 75 dates, 1,050 cells per market,
and **12,600 fleet cells**.

The dry-run/no-network corpus planner required 60 market/year staging units.
The empty-staging verifier found **0 complete units**, so no cell is currently
provable and the first retrain **BLOCKS pending separately reviewed
collection**: **0 / 12,600 cells**. This is the correct result. No fit,
candidate, release, promotion, or reservation was created.

`codex/workstation-build-the-first-retrain-2026-09-12a` should be retired as a
retrain implementation. Its branch ref remains untouched. Its one unique
valuable component, the standalone train/serve parity control, was ported
without porting its self-sizing base-retrain orchestration.

## Branch and refresh

- Required branch:
  `codex/workstation-rescue-the-pit-retrain-lane-2026-09-20a`
- Held parent: `450f03c53fad461732039bd879f9cc5f494f28ab`
- Refreshed master: `e802233522f455fe857357ea287384f1999538fa`
- Refresh merge: `5cc53f50` (`Merge origin/master into PIT retrain rescue`)
- Worktree: `scratch/w/rescue-pit-09-20a`
- PR: none
- Integration merge: none

The refresh remained a rescue rather than a re-derivation. It produced three
conflicts:

1. `agent-report-2026-08-02-workstation-build-base-retrain-step.md` was an
   add/add conflict whose only byte difference was a UTF-8 BOM. I kept the
   no-BOM copy; report content was unchanged.
2. `agent-report-2026-08-03-workstation-build-pit-forecast-corpus.md` was the
   same BOM-only add/add conflict. I kept the no-BOM copy; report content was
   unchanged.
3. `schema_registry_recent_data.py` placed the PIT registrations and master's
   maker-input registration at the same tuple position. I retained all eight
   PIT records and master's maker-scoring input binding as separate additive
   entries.

No assertion was silently weakened during the refresh. The only changed test
meaning in the rescue is deliberate: the synthetic exact-PASS base-retrain
fixture now proves the complete fixed 75-date x 14-cutoff x 12-market matrix,
not the former one-date x one-cutoff candidate-sized matrix.

## Lane adjudication

| Component | Survivor | Evidence and disposition |
| --- | --- | --- |
| Base retrain step | `-09-01a`, with the population-policy repair on this branch | It verifies the parent release and 84 base roles, inventories protected state, requires all 12 HGB/LR/calibration triples, rebuilds the semantic graph, and can construct only an inactive research child. `-09-12a` reads `source_payload.covered_years` and lets source evidence size its matrix, so its retrain orchestration is retired. |
| PIT corpus | `-09-01a` | It alone carries the immutable training-only corpus, request-keyed staging, complete materialization, exact 24-hour rows, issue/availability cutoff checks, content-addressed atomic publication, overwrite refusal, and explicit serving/archive separation. Nothing from the withdrawn archive-extension approach survives. |
| Forecast training contract | `-09-01a` | It alone carries the explicit manifest verifier and pooled/base-retrain binding. Ambient `forecast_daily.csv`, target-year rows, empty issue identity, stitched rows, partial builds, and active-archive overlap remain fail-closed. |
| Train/serve parity gate | `-09-12a` standalone control, ported | `train_serve_feature_parity.py`, its deterministic known-defect fixture, tests, and two schema registrations were ported. The control compares values, units, categories, missingness, cutoff availability, and provenance over the full feature/fleet surface. No `-09-12a` evidence manifest or base runner was ported. |
| Candidate manifest handling | `-09-01a` | PIT corpus and preflight hashes are embedded in per-market HGB/LR/calibration artifacts and fit receipts, then carried into the fleet receipt and inactive-release lineage. The complete parent graph is rebound and verified. `-09-12a` omits those PIT hashes and publishes only its separate candidate directory/evidence-manifest lane. |

This is not a hybrid of the two retrain implementations. The complete
`-09-01a` retrain/PIT/candidate lane survives; only the independently useful
parity scorecard component was salvaged from `-09-12a`.

## Highest-priority falsifier and repair

Before repair, `_required_pit_selection_keys()` enumerated dates from each
candidate corpus market's `selected_dates`. The manifest also declared its own
`expected_selected_day_count` and `minimum_selected_day_count`. The existing
exact-PASS synthetic test used one selected date and one cutoff, proving a
candidate could shrink the PIT gate even though the exact
`source_payload.get("covered_years")` expression was absent.

The repair is intentionally outside the PIT corpus format:

- `base_retrain.build_plan()` now embeds a code-owned, self-hashed population
  policy for 2021-2025, target month/day +/-7, cutoff hours 07-20, and the exact
  built-in fleet.
- PIT selection keys are reconstructed from that policy, not from candidate
  evidence or source fields.
- Preflight verifies the plan self-hash and exact population policy.
- Every market must supply the exact 75-date set; candidate counts and minimums
  are evidence checks only.
- The verified parent must expose the fixed 07-20 cutoff set.
- Preflight and fleet receipts state the plan hash, policy identity, and required
  market/date/cutoff count.
- `test_candidate_dates_and_covered_years_cannot_shrink_the_pit_gate` reduces
  both `covered_years` and selected dates to one. The policy gate still requires
  12,600 cells and the run remains `BLOCK`, `fit_authorized=false`.

The PIT corpus schema, immutable publication contract, failure rules, and
serving isolation were not changed or softened.

## Gate receipt

A temporary plan was produced only under `C:\tmp` with:

```text
python -m weather.sources.forecast_training_corpus plan
  --years 2021,2022,2023,2024,2025
  --target-year 2026
  --season-start 07-24
  --season-end 08-07
```

The command returned:

| Field | Result |
| --- | ---: |
| mode | `dry_run_no_network` |
| network authorized | `false` |
| provider probe authorized | `false` |
| markets | 12 |
| years | 5 |
| target-season dates | 75 |
| cutoff hours | 14 |
| expected market/date cells | 900 |
| required market/date/cutoff cells | **12,600** |
| required market/year staging units | 60 |
| complete staging units | **0** |
| all complete | `false` |
| plan self-hash | `24fac736dbf83258d459c0246334fe3595d6f1aa35462acf8017428d10e47660` |
| plan file SHA-256 | `d91f2161f53d7e1265ea6dbd55054363e44cf6bcbf3aa0838aab00b3c7d6c15b` |

The planner remains permanently `dry_run_no_network`. The corpus module has an
endpoint literal and immutable request descriptions but no `requests`, `httpx`,
`urllib`, `aiohttp`, `urlopen`, or other HTTP-client import/call. No provider
was fetched, probed, or contacted.

## Concurrent overlap and additive registry handling

The held branch's cumulative diff retains the previously declared small
overlaps:

- `nightly_retrain.py`: +69 lines, additive explicit base-step command/plan,
  plan receipt, step placement, and parser bindings. I did not restructure it.
  This overlaps `-09-21a` and must be reconciled by the integration owner.
- `model_features.py`: +44 lines, one candidate prior/support reader. I did not
  restructure it. This overlaps `-09-22a` and must be reconciled by the
  integration owner.
- `schema_registry_data.py`: +25 lines, four standalone `SchemaSpec` entries.
  The change remains purely additive.

The revised instruction was obeyed: `forecast_history.py` changes only its
module description to label the existing archive legacy/serving-compatible and
route new training to the explicit PIT corpus. Its season, collector, HTTP
behavior, and archive paths were not extended or changed. No collection was
performed and nothing was written beneath `data/forecast_history`.

## Roll sensitivity from retained import closures

This verdict uses only `runtime_identity.source_scope_files` from the retained
snapshot, observation-trigger, CLOB, and CLOB-enrichment status receipts (77,
85, 23, and 21 files respectively). It does not use `SOURCE_PATTERNS`.

| Cumulative changed source file | Retained closure result |
| --- | --- |
| `src/weather/model/model_distribution.py` | Roll-sensitive: snapshot and observation-trigger closures. |
| `src/weather/model/model_features.py` | Roll-sensitive: snapshot and observation-trigger closures. |
| `src/weather/schema_registry_data.py` | Roll-sensitive: all four retained closures. |
| `src/weather/schema_registry_recent_data.py` | Roll-sensitive: all four retained closures. |
| `src/weather/sources/forecast_history.py` | Roll-sensitive: snapshot and observation-trigger closures. |
| `src/weather/calibration/base_model_candidate.py` | Not present in any retained closure. |
| `src/weather/calibration/forecast_training_contract.py` | Not present in any retained closure. |
| `src/weather/calibration/pooled_feature_assembly.py` | Not present in any retained closure. |
| `src/weather/calibration/pooled_feature_cli.py` | Not present in any retained closure. |
| `src/weather/market/taker_bot_cli.py` | Not present in any retained closure. |
| `src/weather/market/taker_bot_finalization.py` | Not present in any retained closure. |
| `src/weather/operations/agent_docs_audit.py` | Not present in any retained closure. |
| `src/weather/operations/base_retrain.py` | Not present in any retained closure. |
| `src/weather/operations/nightly_retrain.py` | Not present in any retained closure. |
| `src/weather/operations/storage_classes.py` | Not present in any retained closure. |
| `src/weather/operations/taker_bot_daily_roll.py` | Not present in any retained closure. |
| `src/weather/reporting/scorecards/train_serve_feature_parity.py` | Not present in any retained closure. |
| `src/weather/sources/forecast_training_corpus.py` | Not present in any retained closure. |

The branch is roll-sensitive when eventually integrated. This report does not
authorize or perform that integration.

## Verification

Focused verification:

```text
PIT corpus + forecast contract + base retrain + nightly + schema registry
+ import architecture + standalone parity
106 passed

tests/operations/test_base_retrain.py
14 passed

tests/operations/test_experiment_executor.py
24 passed
```

Full verification used the already-documented Windows process execution-policy
bypass and an extended-length pytest base path for the executor sandbox:

```text
python -m pytest -q --basetemp \\?\C:\tmp\pf
3350 passed, 4 skipped, 821 subtests passed

python -m compileall -q app src tests
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 679 Markdown files)
```

The master refresh exposed one pre-existing agent-doc audit failure: an
immutable historical report links to a research module that now exists only in
Git history. The report was not edited. The audit now has one exact
path-and-target historical exclusion plus a regression proving ordinary missing
links still fail.

Key final file hashes:

| File | SHA-256 |
| --- | --- |
| `src/weather/operations/base_retrain.py` | `8433ea855871084ba8d3fd012144a53e7350b033d5d4d7c17c762340749f6899` |
| `src/weather/sources/forecast_training_corpus.py` | `444c76ac37c88f523c36d7bb068ff01c8e3a470bf9f9f1a52a3be612c495f417` |
| `src/weather/calibration/forecast_training_contract.py` | `9f9f96a434ab84a2d7cdc32b831307a6fe8f63ead3e7dc4ae9f4b62ff24205ab` |
| `src/weather/reporting/scorecards/train_serve_feature_parity.py` | `2db3226ded4d5a06837ffba334c600414b0c79aa1004dc9af06e12e0e15178c4` |
| `tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json` | `0e967f16f98a084f9f8d3f465a40d6a3e12fa8b20c2eb427b83977464ef90867` |

## Safety and production disposition

- Reserved-window policy was checked before work and again before the dry plan:
  no dates are reserved; the window remains armed but undated. No reserved date
  was declared, consumed, or read.
- No provider call, fetch, collection, probe, or paid-source action occurred.
- No HTTP client was added to `forecast_training_corpus.py`.
- No model fit, candidate creation, release construction, promotion, pointer
  mutation, or settlement/confirmation scoring occurred.
- No scheduler/task was registered or changed and no loop was started,
  restarted, or stopped.
- No production `data/` path, mirror path, or `D:\weather-mirror` path was
  written. Retained loop status receipts were read only for the required roll
  verdict.
- `C:\Users\micha\.weathersync.cred` was never read.
- No PR or integration merge was created. Only the exact rescue branch is to be
  pushed.
