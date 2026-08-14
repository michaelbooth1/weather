# Workstation report 2026-09-74a — price the repair ceiling before spending alpha

## Verdict

**INCUMBENT REPLAY CONTROL FAILED — STOPPED BEFORE THE CANDIDATE; DO NOT
ALLOCATE ALPHA WHILE REPLAY IS BLOCKED.** On the first exact captured runtime,
commit `1dd68a4395bb`, 7 of 8 candidate-unchanged B rows reproduced within the
frozen L1 tolerance of `1e-12`. Toronto
`20260617T000830-0400` did not: distribution L1 was
`0.0070223354971858856`, with maximum per-band error
`0.0023940918264677147`. Both the recorded and replayed paths identify the
active model as HGB.

The handoff says this finding stops the mission, so it did. No candidate
distribution, displacement, oracle ceiling, realized improvement, outcome,
market comparison, or C endpoint was computed. Alpha remains **7 of 20 spent,
13 available**; this mission allocated zero and decision 10 remains **CLOSED
UNUSED, NOT REASSIGNED**.

## Mandatory positive control

The control population is the 163 B decrease-event rows in the frozen `-09-73a`
artifact where `observable_recovered_rows == 0`; the candidate therefore makes
no input change. The artifact was projected onto non-outcome keys only.

Before model execution, the census found that the retained corpus itself is
not uniformly replay-bound:

| Binding | Rows | Share |
| --- | ---: | ---: |
| Captured runtime commit | 99 | 60.74% |
| Model identity but no runtime commit | 41 | 25.15% |
| No model identity and no runtime commit | 23 | 14.11% |
| **Total** | **163** | **100%** |

The 163 rows span 9 empirical v0.3.1 rows, 19 v0.5.0 HGB rows, 4 v0.5.1
HGB rows, 24 v0.5.7 HGB rows, 8 v0.5.8 HGB rows, and 99 v0.5.10 HGB rows.
No guessed runtime was substituted for the 64 unbound rows.

The exact-commit replay then started with the eight rows bound to
`1dd68a4395bb` and stopped on its failure, as required:

| Result | Rows | Rate | Maximum L1 |
| --- | ---: | ---: | ---: |
| Within `1e-12` | 7 | 87.5% | `1.75864635125495e-16` |
| Outside `1e-12` | 1 | 12.5% | `0.0070223354971858856` |

This is not a floating-point boundary miss: the failing L1 is roughly seven
billion times the tolerance. The other seven rows match at machine precision.
The required control match rate is 100%, so the population control is **BLOCK**,
not 87.5% evidence that replay is mostly good enough.

## End-to-end traces

The passing trace is Atlanta `20260617T003036-0400`. Its `-09-73a` receipt has
zero recovered rows, the full captured sources were passed to the model at the
recorded `built_at`, the historical runtime produced HGB, and recorded-versus-
replayed L1 was `6.66098844285344e-17`.

The failing trace is Toronto `20260617T000830-0400`. It likewise has zero
recovered rows and uses the identical captured sources and recorded `built_at`.
The same exact runtime produced HGB, but its vector missed the recorded vector
by L1 `0.0070223354971858856`. This is a model-output trace, not a grep or a
feature recomputation.

Every resolved module came from the intended disposable historical tree under
`scratch/w/repair-ceiling-09-74a-runtime/src`: `toronto_model`, `model_base`,
`model_climatology`, `model_constants`, `model_distribution`, `model_features`,
`feature_store`, `forecast_error_model`, `family_secondary_artifacts`,
`probability_calibration`, `settlement_lag_model`, and `market_registry`.
The receipt SHA-256 is
`10a638818b61ae266fb809fb79fe25dd2e5ac8d964dd433d039ff369a21e9b49`.

## Algebra checked, but not used

For one-hot `y`, expanding the paired Brier difference gives

```text
sum_k[(p_k-y_k)^2-(q_k-y_k)^2]
= sum_k(p_k^2-q_k^2) - 2 sum_k y_k(p_k-q_k)
= (||p||^2-||q||^2) - 2(p_b-q_b).
```

Therefore maximizing over every possible band, without observing `b`, gives

```text
(||p||^2-||q||^2) + 2 max_k(q_k-p_k),
```

and replacing `max` with `min` gives the floor. The algebra in the handoff is
correct. The repository pre-registration uses point estimate plus or minus
`q` times bootstrap standard deviation, not a percentile bound. Pointwise
domination would transfer to a percentile bound, but it does not by itself
order two `mean - q·SE` lower bounds because their resample standard errors can
differ. No interval was computed after the control failed.

## Outcome and alpha receipts

- `realized_band_read: false`
- `settlement_consulted_for_ceiling: false`
- `candidate_probabilities_computed: false`
- `displacement_computed: false`
- `ceiling_computed: false`
- `outcome_scored: false`
- `market_compared: false`
- `C_endpoint: false`
- `alpha_allocated_by_mission: 0`

Because the ceiling path was never entered, there is deliberately no
`repair-ceiling-2026-09-74a.csv`. The committed control manifest is the stop
artifact (SHA-256
`7bf040d43391958ccab1623bca9cd7baceb437f5c61e155310ec365d95ab22fc`).
The `-09-73a` point-in-time receipts remain binding: zero future
snapshots consumed, zero blank snapshot receipts, and no pooling across the
2026-07-31 anchor. This mission did not recompute or weaken them.

## Artifacts and verification

The versioned seed freezes the input hashes, `1e-12` tolerance, 100% required
match rate, outcome-free formulas, and fail-closed runtime-binding rule. The
harness extends the `-09-73a` module, projects only B non-outcome columns,
extracts exact replay keys, prints/resolves every imported distribution module,
and refuses to enter candidate work when aggregation is blocked.

The run used the bundled Codex Python 3.12 runtime and an existing local Python
3.12 scientific package directory. Nothing was installed. Verification:

```text
python -m compileall -q tools/research/measure_repair_ceiling_09_74a.py
PASS

python tools/research/measure_repair_ceiling_09_74a.py --help
PASS

git diff --check
PASS
```

## Explicitly not done

- No provider or exchange call; no credential, network collector, or paid
  source.
- No write under production `data/`; no tape, ledger, mirror, trading evidence,
  scheduled task, supervisor, or live process changed.
- No model, calibration, feature, floor, artifact, release, producer, or
  serving code changed. The serving floor was not weakened.
- No fit, promotion, activation, allocation, live trade, merge, or PR.
- No realized band, settlement score, Brier against outcome, CRPS, log loss,
  calibration curve, hit rate, market probability, or C probability.

## Production-host reproduction

After fetching the branch in an isolated worktree, use a disposable historical
runtime and write only ignored `scratch/` evidence:

```powershell
$branch = 'origin/codex/workstation-what-is-the-most-this-can-buy-2026-09-74a'
$runRoot = 'scratch\runs\repair-ceiling-09-74a-production-verify'
$runtimeRoot = 'scratch\w\repair-ceiling-09-74a-runtime'
$python = '<bundled-codex-python-3.12>'
$scientificSite = '<existing-python-3.12-scientific-site>'

git rev-parse $branch
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
git worktree add --detach $runtimeRoot 1dd68a4395bb

& $python tools\research\measure_repair_ceiling_09_74a.py extract `
  --repo-root . `
  --snapshots-root data\snapshots `
  --run-root $runRoot

& $python tools\research\measure_repair_ceiling_09_74a.py replay `
  --records "$runRoot\control-records.jsonl" `
  --runtime-root $runtimeRoot `
  --runtime-commit 1dd68a4395bb `
  --scientific-site $scientificSite `
  --output "$runRoot\receipt-1dd68a4395bb.json"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-what-is-the-most-this-can-buy-2026-09-74a
```

Expected replay exit is 2: 8 rows, 7 matches, maximum L1
`0.0070223354971858856`, with the Toronto row above failing. The expected roll
verdict is recorded below after the repository-owned script inspects the final
commit.

## Roll verdict

The repository-owned `scripts\ops\roll_verdict.ps1 -Branch
codex/workstation-what-is-the-most-this-can-buy-2026-09-74a` inspected the
committed branch and returned exit 0, **ROLL-FREE**. It automatically corrected
the local `master`, which was 70 commits behind and zero ahead, to
`origin/master` at `b230d723`. It found five changed files and zero importable
files. The dormant CLOB-enrichment closure was mechanically subsumed by the
three live closures. No quiet-window merge is required; pushing this branch
cannot roll production.
