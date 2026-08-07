# Workstation train/serve station-wind parity repair - 2026-08-07

## Verdict

**IMPLEMENTATION COMPLETE; THE 24 UNEXPECTED BLOCKERS ARE CLOSED; CURRENT
INCUMBENT OUTPUT IS EXACTLY UNCHANGED; ROLL-SENSITIVE.** The deterministic
parity gate moves from 220 blockers with 24 unexpected findings to 196 blockers
with zero unexpected findings. All four declared known-defect groups still
reproduce. The known-defects fixture was not edited.

The repair is evidence-supported routing, not synthesis. METAR already carried
gust and direction, but gust was in knots and both fields were discarded with
the station rows. Toronto SWOB XML carried the corresponding measurements, but
the v1 parser omitted them. Serving now preserves cutoff-aligned station rows,
converts METAR gust to the artifact's native settlement unit, and derives the
same three-hour direction delta as training. A provider-reported missing gust
stays missing.

The frozen replay positive control is exact: 31,548 recorded band probabilities
reproduce with maximum absolute error `0.0`. Across 2,868 captured snapshots,
D=5 dates, M=12 markets, and 60 promotion-countable market-days, the repair
changes zero distributions. Centre, width, and Brier deltas are all exactly
`0.0`, with crossed date x market intervals `[0.0, 0.0]`. This is structural:
the captured and currently bound artifacts do not select either field in their
`feature_names`. It is not permission to skip candidate-bound replay after a
future retrain selects them.

Implementation commit: `87ca37cf83fcef5eeb23cbbcd2247956aeb00194` on
`codex/workstation-close-the-train-serve-parity-gap-2026-09-39a`.

## Scope, dependency, and reservation

- Required `origin/master` base: `66156b8d9832f82a6ef102d118c540b1142800cb`.
- The commissioned handoff was on that base, but the parity gate and its frozen
  known-defects fixture were still only on returned branch
  `origin/codex/workstation-produce-the-first-retrained-candidate-2026-09-38a`
  at `701f5ac0d2c514bafe0426c7b94cdc3eb992ae57`. This branch declares that
  dependency through merge commit
  `b216834cb98c0c505e807dc320388ad514f1ca32`; it does not silently copy it.
- `docs/operations/reserved-confirmation-window.md` was checked at run time and
  says no dates are currently reserved.
- Only existing local captured inputs from July 22-26, hours 09:00-14:00 local,
  were read. All dates precede the `2026-07-31` artifact boundary; no regimes
  were pooled.
- The corpus was deduplicated to one `(market_id, target_date)` cell before
  inference, and every admitted settlement had `promotion_countable=true`.

## P0 - why the two features disappeared

The unexpected baseline decomposes exactly as commissioned: 12 markets x two
fields, all `missingness`, all training-present/serving-missing, all in the
`station-surface-contract-<market>` cases.

| Market scope | `wind_gust_kmh` | `wind_shift_3h_degrees` | Classification |
| --- | --- | --- | --- |
| Eleven U.S. markets | Aviation Weather METAR rows already supplied `wind_gust` in knots. Routing kept only station temperature/max and discarded the row sequence. | METAR rows already supplied numeric `wind_dir`; training derives the delta from the row sequence, but serving discarded that sequence. | Gust: produced under another name/unit **and** dropped (3 + 2). Shift: its inputs were produced but dropped (2). |
| Toronto | SWOB XML contains gust, speed, and direction, but the v1 parser omitted them. The station summary then discarded rows. METAR fallback also had raw wind, but a temperature-bearing SWOB row won source priority before wind fallback. | Same parser and row-routing loss. | Never emitted by the selected SWOB adapter, then dropped by routing (1 + 2). |

These two are **additional to**, not members of, section 4's eight dead numeric
inputs. The eight retained artifact findings remain `rise_from_7am`,
`warming_rate_2h`, `hours_at_peak`, `dewpoint_c`, `humidity`, `pressure`,
`pressure_trend_3h`, and `wind_speed_kmh`. The current artifact's historical
8/29 statistic therefore remains exactly what section 4 measured: current HGB
and late-day artifacts do not select gust or shift. The prospective retrain
schema does select both, so leaving the 24 blockers open would have added two
more dead numeric inputs to the next candidate.

All 196 retained blockers are still classified by the four exact fixture
entries. The repaired report rediscovers 4/4; no supposedly known finding was
found to lack a classification.

## P1 - repair

`src/weather/model/model_sources.py` now:

- advances the METAR and ECCC SWOB parser identities to v2;
- converts METAR knots to the trained WU/native contract: `1.1507794480235425`
  mph per knot for Fahrenheit markets and `1.852` km/h per knot for Celsius;
- preserves provider missingness, including calm/no-gust `None`;
- normalizes station row time/direction/gust fields and carries rows plus the
  latest row through `station_observation_data`;
- reparses retained raw SWOB XML from v1 captured envelopes when available;
- emits SWOB direction, speed, and gust directly for new live captures.

`src/weather/model/model_features.py` uses station rows only when the canonical
WU surface path did not produce the field. Both station gust and the
three-hour direction comparison are cutoff-aligned. No forecast or other
provider value is substituted, and the observed serving floor is untouched.

Tests prove Fahrenheit unit conversion, rejection of a future post-cutoff
row, direction-delta equality, raw v1 SWOB reparsing, and missing-gust
preservation. The gate expectation was tightened to zero unexpected findings
and exactly 196 retained blockers; the fixture itself is byte-unchanged.

### Gate receipts

| Run | Status | Blockers | Unexpected | Known groups | Self-hash |
| --- | --- | ---: | ---: | ---: | --- |
| Pre-repair | BLOCK | 220 | 24 | 4/4 | `e2f7a13430072a9d6008f10b05f3adb18aefac674d6eb4ea51decfaf8e0c11e6` |
| Repaired | BLOCK | 196 | 0 | 4/4 | `c9cefe50f676de5f7e6eee0276f6bdde6ca87350e1b054b2f2940d8ad65529d5` |

The remaining BLOCK is intentional and belongs to the pre-existing classified
defects; this mission did not weaken the standing control.

## P2 - paired captured-input replay

### Population and method

- Captured runtime positive-control commit:
  `641f71337f9279c579a743bbd605fc1c54d5a391`.
- Treatment: that exact runtime plus only the two-file serving repair.
- Dates: July 22-26, 2026; hours 09:00-14:00 local.
- Support: 2,868 snapshots, D=5, M=12, 60 market-days.
- Positive control: 31,548 band probabilities; maximum absolute recorded error
  `0.0`.
- Daily-first paired deltas, followed by a 10,000-replicate crossed pigeonhole
  bootstrap with independent date- and market-cluster resampling, seed
  `20260939`.
- Centre and width deltas are converted to Celsius-equivalent scale before
  pooling. Brier is repair minus control; positive would be degradation.
- Selected replay-key hash:
  `08d5297fb92d9e43ab9f414ef781f817c9b23fd2c0fc8a83247711412e00ee48`.
- Ignored workstation receipt SHA-256:
  `04d4bf96730c08b04886e9377e0c9eb1ecaf23c04e26797ef8d554e3b45cdf13`.

### Feature support in the captured corpus

| Market | Snapshots | Gust populated | Shift populated |
| --- | ---: | ---: | ---: |
| Atlanta | 245 | 24 | 237 |
| Austin | 241 | 76 | 217 |
| Chicago | 237 | 48 | 208 |
| Dallas | 239 | 63 | 208 |
| Denver | 234 | 49 | 199 |
| Houston | 238 | 24 | 237 |
| Los Angeles | 232 | 7 | 231 |
| Miami | 233 | 61 | 206 |
| NYC | 231 | 7 | 211 |
| San Francisco | 247 | 176 | 244 |
| Seattle | 237 | 46 | 229 |
| Toronto | 254 | 0 | 0 |
| **Fleet** | **2,868** | **581 (20.26%)** | **2,427 (84.62%)** |

Toronto's old replay envelopes do not retain the raw SWOB XML needed to recover
the v1-omitted wind fields. That is honest missing replay support, not a
manufactured value. The raw-envelope regression test proves the backward path
when XML is retained, while v2 live parsing supplies the fields directly.

### Served-output result and power

| Metric | Daily-first point | Crossed 95% interval | Crossed SE | 80%-power MDE | Support |
| --- | ---: | ---: | ---: | ---: | --- |
| Centre delta, C-equivalent | `0.0` | `[0.0, 0.0]` | `0.0` | `0.0` | D=5, M=12, 60 days |
| Width delta, C-equivalent | `0.0` | `[0.0, 0.0]` | `0.0` | `0.0` | D=5, M=12, 60 days |
| Brier delta, repair-control | `0.0` | `[0.0, 0.0]` | `0.0` | `0.0` | D=5, M=12, 60 days |

All 2,868 distribution L1 distances are exactly zero. The standard `0.003`
Brier materiality tolerance contains the entire degenerate interval.
Conventional plug-in power at an observed zero effect is not informative; the
receipt records zero variance and a mathematical MDE of zero. The substantive
power disposition is stronger and mechanical for this incumbent: all captured
and current HGB/late-day artifact-hour bundles exclude both names, so the
repaired values cannot enter their predictions. The exact positive-control
replay confirms that invariant over every admitted snapshot.

This does **not** establish equivalence for a future retrained artifact that
binds the fields. That candidate must rerun parity and candidate-bound replay;
no claim from this incumbent receipt transfers to it.

## Verification

Executed with the repository's pinned Python 3.11 environment:

```text
pytest -q tests/model/test_feature_skew.py tests/reporting/test_train_serve_feature_parity.py
25 passed, 666 subtests passed

python -m compileall -q app src tests
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 712 Markdown files)

git diff --check
PASS
```

A broader station/source selection produced 67 passes and three subtest passes;
two `test_source_cache_ttl` cases failed before model execution because the
protected local `data/wunderground/cyyz` ACL denies their attempted cache write.

The complete pinned suite executed rather than being inferred:

```text
3365 passed, 4 skipped, 830 subtests passed, 22 failed
```

The documented master baseline named four failures. This stacked branch's
observed failure set overlaps it on
`test_trainer_fits_market_afternoon_residual_contexts`; it does not reproduce
the same four-test shape. The other failures decompose into two protected-data
ACL cache writes, thirteen experiment-executor/sandbox process cases, two
Windows scheduled-action token cases, two delegated producer-provenance cases,
and one each in the paid-provider prose ratchet and schema registry. The last
two point to documentation/schema content already present on the base or
stacked dependency. No failure asserts the repaired fields, unit conversion,
cutoff behavior, SWOB parser values, or parity result. Because the exact suite
shape is not master-equivalent, this report does not mislabel the 22 as the
four known failures; the owner-focused green controls are the change evidence.

## Roll verdict

The required `scripts\ops\roll_verdict.ps1` command inspected 44 changed files
and 19 importable files after implementation commit `87ca37cf`. It used the live
snapshot, CLOB, and observation-trigger closures and returned
**ROLL-SENSITIVE**. The dormant CLOB-enrichment closure was mechanically
subsumed by live closure evidence. Receipt SHA-256:
`9c0c2226f19783824901d94f6bf8635a183bcd7c4a19afdb2c86c1f8beadb38e`.

| Mission file | Live closures | Verdict |
| --- | --- | --- |
| `src/weather/model/model_features.py` | snapshot (`loop`), observation-trigger | **Roll-sensitive** |
| `src/weather/model/model_sources.py` | snapshot (`loop`), observation-trigger | **Roll-sensitive** |
| `tests/model/test_feature_skew.py` | none by contract | Roll-free |
| `tests/reporting/test_train_serve_feature_parity.py` | none by contract | Roll-free |
| This report | none by contract | Roll-free |

The stacked `-09-38a` dependency also carries its already-reported
roll-sensitive model/schema/history files. Integration must use
`scripts\ops\quiet_window_merge.ps1` during 01:00-04:00 and prove capture
recovered before pushing master. Pushing this branch does not roll production.

## Explicitly not done

- No candidate, model, calibration, or artifact was fitted or generated.
- No release was frozen, promoted, registered, or activated.
- No serving floor, probability mass, known-defects fixture, or promotion gate
  was weakened.
- No provider call, paid source, credential, new collection, or training-corpus
  materialization was used.
- No production data, mirror, tape, ledger, or trading evidence was written.
- No scheduled task, collector, supervisor, registration, or live process was
  restarted or mutated.
- No PR or merge to master was created. The only merge is the declared topic
  dependency on returned `-09-38a`.

The disposable detached worktree used for the captured-runtime positive
control was removed after the ignored receipt was finalized; it contained no
unique evidence or user work.

## Production-host verification

Run read-only verification from the production repository path. These commands
do not merge, restart, collect, fit, or write production `data/`:

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
git fetch origin codex/workstation-close-the-train-serve-parity-gap-2026-09-39a
git merge-base --is-ancestor 66156b8d9832f82a6ef102d118c540b1142800cb origin/codex/workstation-close-the-train-serve-parity-gap-2026-09-39a
git merge-base --is-ancestor 701f5ac0d2c514bafe0426c7b94cdc3eb992ae57 origin/codex/workstation-close-the-train-serve-parity-gap-2026-09-39a
git show --stat --oneline origin/codex/workstation-close-the-train-serve-parity-gap-2026-09-39a
git diff --check origin/master...origin/codex/workstation-close-the-train-serve-parity-gap-2026-09-39a

.\venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q `
  tests/model/test_feature_skew.py `
  tests/reporting/test_train_serve_feature_parity.py

.\venv\Scripts\python.exe -B -m weather.reporting.scorecards.train_serve_feature_parity `
  --input tests\fixtures\train_serve_feature_parity_known_defects_v0.1.json `
  --run-root scratch\runs\weather-parity-09-39a-production-verify `
  --proof-mode

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch origin/codex/workstation-close-the-train-serve-parity-gap-2026-09-39a
```

Expected parity verification: `BLOCK`, 196 blockers, zero unexpected, 4/4
known defects, report hash
`c9cefe50f676de5f7e6eee0276f6bdde6ca87350e1b054b2f2940d8ad65529d5`.
Expected roll result: `ROLL-SENSITIVE`.

The frozen replay is workstation-owned evidence and is intentionally not
prescribed on production. Its captured-runtime worktree and ignored receipt
were not copied to production or committed as live-state sidecars.
