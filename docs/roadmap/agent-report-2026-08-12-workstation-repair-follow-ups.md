# Workstation report 2026-09-49a — close the repair follow-ups before the retrain

## Verdict

**COMPLETE; THE PARITY PROOF NOW EXITS 0; F-MARKET TRAINING NO LONGER SELECTS
STATION PRESSURE; SERVING IS BYTE-IDENTICAL; ROLL-FREE.** The remaining
`wind_group` defect stays asserted in every registered market. Each of the other
eight repaired fields now sits outside that defect declaration, and proof mode
fails on any unexpected blocking finding.

The per-market training policy derives its decision from `MarketSpec.unit`:
the 11 Fahrenheit markets exclude `pressure` and `pressure_trend_3h`, while
Toronto keeps both. The first-retrain preflight applies the same ordered feature
contract. No serving extractor, feature-store schema, artifact, release, floor,
or probability path changed.

This is a real artifact-contract invalidation, not a no-op. Every retained
F-market base HGB, base LR, and late-day LR artifact currently selects both
features. Those incumbent artifacts remain byte-identical and may continue to
serve until replaced, but they are not evidence of compliance with the new
training contract. The next F-market retrain must regenerate them.

Implementation commit: `669ad6bb` on
`codex/workstation-close-the-repair-follow-ups-2026-09-49a`, based on
`origin/master` at `effd66c78b99ba69c64e10e2e065a05bcede0b01`.

## 1. Parity fixture and proof-mode result

The fixture schema and the other three defect ids are unchanged. Only
`nine_empty_base_features_09_to_14` changed:

- `fields` and `required_fields` now contain only `wind_group`;
- `minimum_findings` is 12, one for every registered market;
- `required_market_coverage` remains `all_registered`.

| Gate | Exit | Report status | Blocking | Unexpected blocking | Coverage blockers | Known groups |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Before | **2** | `BLOCK` | 100 | 0 | 0 | 3/4 |
| After | **0** | `BLOCK` | 100 | 0 | 0 | 4/4 |

`BLOCK` is still the honest report status because 100 findings belong to four
declared historical defect groups. Proof mode has a different purpose: it now
returns 0 only when all declared groups are rediscovered, coverage has no
blocker, and unexpected blocking findings equal zero. This is why narrowing
the declaration records the repair without weakening the gate.

The remaining group reports exactly:

- `rediscovered: true`, proving the `wind_group` defect was not deleted;
- `found_fields: [wind_group]`, proving none of the repaired fields was hidden
  inside the declaration;
- the exact 12-market set `atlanta`, `austin`, `chicago`, `dallas`, `denver`,
  `houston`, `los-angeles`, `miami`, `nyc`, `san-francisco`, `seattle`, and
  `toronto`, proving fleet-wide coverage rather than a minimum-count shortcut.

A parameterized regression separately forces each former field back to missing:
`rise_from_7am`, `warming_rate_2h`, `hours_at_peak`, `dewpoint_c`, `humidity`,
`pressure`, `pressure_trend_3h`, and `wind_speed_kmh`. All eight cases create
unexpected blockers and make proof mode exit 2.

The before report hash was
`11c79b4e7ea549729d2d78c5c57bdab867a3689b46f3669da7b2cd740380225a`.
The after verification report hash was
`db348f9ab67d15ad36036ef436f4b83298bf5383af3c33d3db1712ff5200f157`;
the report hash includes its generation timestamp, so the exit and exact
summary fields above are the binding comparison.

## 2. Registry-driven training policy

`weather.calibration.feature_training_policy` owns one order-preserving policy:

| Registry unit | Training exclusions |
| --- | --- |
| `F` | `pressure`, `pressure_trend_3h` |
| `C` | none |
| any other/missing unit | fail closed |

There is no market-id allowlist. A test constructs a future F `MarketSpec` and
gets the same exclusions automatically; Toronto's C spec retains both fields.
Candidate fitting also refuses an unregistered market and refuses a requested
unit that disagrees with the registry.

The policy is applied at all per-market artifact surfaces reached by this
mission:

1. base HGB and base LR candidate fitting;
2. the legacy per-market base trainer;
3. the per-market late-day continuation trainer;
4. first-retrain manifest/preflight feature order, missingness, parity, and
   sidecar checks.

Candidate HGB/LR payloads, fit receipts, fit reports, and retrain plans record
the policy id and exact exclusions. Direct synthetic fits prove F candidates
omit both features and Toronto candidates retain them, including scaler and
feature-order agreement.

Serving behavior is deliberately unchanged. F-market `pressure` remains absent
rather than receiving a false METAR station-pressure alias. Toronto continues
to serve real captured station pressure.

## 3. Artifact invalidation finding

A read-only inventory of retained artifacts found:

| Artifact family | F artifacts selecting both fields | Toronto selecting both |
| --- | ---: | --- |
| Per-market base HGB | **11/11** | yes |
| Per-market base LR | **11/11** | yes |
| Per-market late-day LR | **11/11** | yes |

Therefore all 33 retained F-market files in those three families encode the old
training surface. They are not rewritten here: doing so would be an unrequested
fit/artifact publication and would defeat the requirement that serving remain
unchanged. Toronto's selection is valid and is intentionally preserved.

## 4. Post-anchor serving replay

The same retained-input replay was run before and after the implementation over
2026-07-31 through 2026-08-07 with
`post_2026_07_31_artifact` provenance. Both runs returned `PASS` with verdict
`paired_replay_valid` and report hash
`8afdab2fc11e8f612eafad4b62e55306dcebcdbdd6a22cf4188b0f1ae26caa9c`.

Both emitted artifacts are byte-identical:

| Artifact | Before/after bytes | Before/after SHA-256 |
| --- | ---: | --- |
| `blind-feature-repair-replay.json` | 27,824 | `b35a954a5b6ebd236f55304d73e89a4c149b598689a7f765947b3e3d885ca1b2` |
| `blind-feature-repair-replay.md` | 7,815 | `e01a7d204c2adbfbb16ad8d526b3fee86a498582ea0f7b9a107f583530734088` |

The receipt retains the published 840/840 exact positive control, 821 changed
repair-versus-control distributions, D=5 countable dates, M=12 markets, and 60
market-days. The relevant comparison for this mission is before-versus-after
the training-policy code: every output byte is identical.

No candidate was fitted and no served number moved, so crossed intervals,
power, and market-gap movement are **not applicable**. This work must not be
costed as gap closure; the `-09-44a` paired result remains the current
measurement.

## 5. Verification

Owner-file verification under Python 3.11:

```text
112 passed, 44 subtests passed
```

The set covers the parity reporter/fixture, all eight regression falsifiers,
base candidate fitting, feature-model ablation and calibration, first-retrain
preflight, and pooled-builder compatibility. Additional checks:

```text
python -m compileall -q app src tests
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files)

git diff --check
PASS
```

The project `venv` points to a removed Python 3.11 installation on this
workstation. Verification used the retained official Python 3.11.9 embeddable
runtime against the repository's existing pinned site-packages. No tracked
environment or dependency file changed.

## 6. Roll verdict

The production checkout's local `master` was behind the declared handoff base,
and the script is intentionally hardcoded to compare against local `master`.
Its first 81-file cumulative output was rejected as the wrong comparison. The
same repository-owned script was then run in a disposable local clone with
`master` pinned to `effd66c7`, the branch commit present, and copies of the same
production closure-status files. It returned exit 0, **ROLL-FREE**. The dormant
CLOB-enrichment closure was mechanically subsumed by the live closures.

| Changed importable file | Live closure hit | Verdict |
| --- | --- | --- |
| `src/weather/calibration/base_model_candidate.py` | none | Roll-free |
| `src/weather/calibration/feature_model.py` | none | Roll-free |
| `src/weather/calibration/feature_training_policy.py` | none | Roll-free |
| `src/weather/operations/base_retrain.py` | none | Roll-free |
| `src/weather/reporting/scorecards/train_serve_feature_parity.py` | none | Roll-free |

Changed tests and Markdown are non-importable and roll-free by the script's
contract. No quiet-window merge is required. Pushing this branch cannot roll
production; this mission does not merge it.

## 7. Explicitly not done

- No real candidate, calibration, artifact, release, or manifest was fitted,
  generated, frozen, promoted, registered, or activated. Tiny synthetic unit
  fits wrote only pytest temporary files.
- No provider or exchange endpoint was called; no paid source or credential was
  introduced.
- No production `data/`, tape, ledger, mirror, scheduled task, collector,
  supervisor, or live process was written or restarted.
- No serving floor, probability-mass invariant, release gate, feature-store
  schema, or live feature route changed.
- No confirmation dates were used; the reserved window remains armed but
  undated.
- No PR, merge, production checkout update, or runtime adoption was performed.

## 8. Production-host reproduction

After fetching the branch into an isolated worktree, these repository-owned
paths reproduce the binding checks and write only ignored `scratch/` evidence:

```powershell
$branch = 'origin/codex/workstation-close-the-repair-follow-ups-2026-09-49a'
git rev-parse $branch

$runRoot = 'scratch\runs\weather-repair-follow-ups-09-49a-production-verify'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

.\venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q `
  --basetemp "$runRoot\pytest" `
  tests\reporting\test_train_serve_feature_parity.py `
  tests\calibration\test_base_model_candidate.py `
  tests\model\test_feature_model_ablation.py `
  tests\model\test_feature_model_calibration.py `
  tests\operations\test_base_retrain.py `
  tests\calibration\test_pooled_feature_model.py

.\venv\Scripts\python.exe -B -m weather.reporting.scorecards.train_serve_feature_parity `
  --input tests\fixtures\train_serve_feature_parity_known_defects_v0.1.json `
  --run-root "$runRoot\parity" `
  --proof-mode

.\venv\Scripts\python.exe -B -m weather.reporting.research.blind_feature_repair `
  --snapshots-root data\snapshots `
  --settlements-root data\settlements `
  --output-root "$runRoot\post-anchor" `
  --start-date 2026-07-31 `
  --end-date 2026-08-07 `
  --provenance-regime post_2026_07_31_artifact

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch $branch
```

Expected parity result: exit 0, report status `BLOCK`, 100 declared blockers,
zero unexpected blockers, zero coverage blockers, and 4/4 known groups. Expected
replay result: `PASS`, report hash `8afdab2f...a9c`, with the JSON and Markdown
file hashes listed above. Expected roll result against the declared base:
`ROLL-FREE` (exit 0), with the five importable files listed in the table.
