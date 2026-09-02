# Workstation multiyear NWP residual information test

Date: 2026-09-02
Branch: `codex/workstation-multiyear-nwp-residual-2026-09-88a`
Source: `origin/codex/workstation-collect-multiyear-pit-research-2026-09-87a` at `3f3367b29fee69965935170b32f6cc3b45d3e33a` (tree `3b64e4afee3b3abfafb584aac3355adedcc1ed3c`)

## Verdict

**INCONCLUSIVE_UNDERPOWERED.** The fixed eleven-field challenger improved the
2025 fleet point estimates over the temperature-only residual baseline, but the
precommitted crossed target-date x market 95% interval for squared-error
improvement included zero. The primary improvement was `0.2751 C^2`-equivalent
with 95% interval `[-0.0234, 0.6186]`, achieved power `0.389`, and 80% minimum
detectable effect `0.4595 C^2`. This fails the decisive GO condition while
establishing neither squared-error nor MAE harm.

The result does **not** authorize probability-distribution research, serving
integration, promotion, release work, or live use. A future attempt to resolve
the question would require a new, independently precommitted information test
with more independent date/year support; the spent 2025 terminal evaluation
must not be tuned against or rerun from source.

## P0 gate and pre-outcome freeze

The experiment began from the exact commissioned source tip and tree. Before
any 2025 outcome value was opened:

- all 745 retained corpus files rehashed with zero integrity errors;
- the canonical corpus-manifest hash matched
  `d41bd21efb7a62396851fe016a215db1ac8bea7de97f387333902aba7a35bb00`;
- 7,392 required coverage cells were complete for the exact 11 common fields,
  leads 1-7, 12 markets, both years, and May-August; the 336 absent 2024
  `precipitation_probability` cells were recorded and that field was excluded;
- the WU inventory was hash-bound while reading only `schema_version`,
  `local_date`, `temperature_unit`, and `row_count`, not outcome values;
- WU support admitted all 12 markets and 114 date clusters in each year:
  1,366 market-days for 2024 and 1,365 for 2025;
- explicit `CodexSandboxOffline` deny-Write/Delete ACL evidence was present for
  both the immutable corpus and frozen mirror.

The tracked design was then frozen and committed before training or terminal
evaluation. Its self-hash is
`bd4bdb2ebcdd67a498e461b455f77bc9ca5a88f73bb19dae389e4bb28e26c0fb`.
It binds the corpus, WU inventory, cohorts, feature order, seed, model
configuration, inference method, and decision rules to harness commit
`6558c4c06c2f99054a238045752774878cdabd86`.

## Frozen model contract

The target in both arms was the native-unit settlement high minus the median
target-day NWP maximum-temperature anchor over leads 2-7. The no-refit
sensitivity recomputed every lead-derived input and the anchor over leads 1-7,
then applied the same two fitted estimators.

- Baseline features: one-hot market identity, day-of-year sine/cosine, anchor,
  temperature-max inter-lead population standard deviation, and lead-2 minus
  lead-7 temperature-max change.
- Challenger additions: precommitted per-lead cloud, shortwave, wind speed,
  CAPE, direct radiation, diffuse radiation, gust, precipitation, VPD, and ET0
  summaries, each reduced to a median and population standard deviation across
  leads.
- Estimator: exactly two `HistGradientBoostingRegressor` fits, each with
  squared-error loss, learning rate 0.05, 120 iterations, 31 leaf nodes,
  minimum leaf size 20, no depth limit, no L2 penalty, 255 bins, early stopping
  disabled, and seed 42.
- Weighting and missingness: one equal-weight row per admitted market-day; no
  imputation and no baseline/challenger row mismatch.

Training used only the frozen 2024 cohort: 1,366 rows, 114 dates, and all 12
markets. The training receipt records exactly two fits and zero terminal-2025
outcome access. A create-only terminal-attempt seal was written before the
single 2025 source-outcome read.

## Terminal 2025 results

Errors below are forecast minus WU outcome. Fleet and month metrics are
Celsius-equivalent; market metrics remain in each market's native settlement
unit. Each `S/M/A` cell is signed error / MAE / MSE.

### Fleet aggregate

| Surface | Signed C | MAE C | MSE C^2 |
|---|---:|---:|---:|
| Primary raw anchor | 1.9858 | 2.3907 | 9.5939 |
| Primary baseline | 0.4163 | 1.4791 | 3.9874 |
| Primary challenger | 0.4102 | 1.4300 | 3.7122 |
| Leads 1-7 raw anchor | 1.8322 | 2.2290 | 8.5758 |
| Leads 1-7 baseline | 0.2401 | 1.4121 | 3.7349 |
| Leads 1-7 challenger | 0.2790 | 1.3681 | 3.4643 |

The primary challenger-minus-baseline point comparison therefore gives a
`0.0491 C` MAE improvement and `0.2751 C^2` MSE improvement. The all-leads
no-refit sensitivity remains favorable at `0.0440 C` MAE and `0.2707 C^2` MSE
improvement.

### Crossed uncertainty and decision gates

The shared-weight crossed target-date x market pigeonhole bootstrap used
20,000 draws, seed `8802026`, 114 date clusters, 12 market clusters, and 1,365
observed date-market cells. Its draw-matrix hash is
`16c17450153defe9bb896d53aa85658cddc0c991860d678c601f8080cadafb0c`.

| Endpoint (baseline loss minus challenger loss) | Point | Crossed 95% interval | Power | MDE80 |
|---|---:|---:|---:|---:|
| Primary MSE, C^2 | 0.2751 | [-0.0234, 0.6186] | 0.389 | 0.4595 |
| Primary MAE, C | 0.0491 | [-0.0188, 0.1250] | 0.267 | 0.1030 |
| Leads 1-7 MSE, C^2 | 0.2707 | [-0.0460, 0.6270] | 0.354 | 0.4781 |
| Leads 1-7 MAE, C | 0.0440 | [-0.0231, 0.1142] | 0.246 | 0.0970 |

Five of six frozen GO checks passed: MAE tolerance, all-leads favorable
direction, maximum-market contribution, support, and isolation/unit/parity.
The decisive primary-MSE interval check failed because its lower endpoint was
negative. Neither harm interval had an upper endpoint below zero, so the
precommitted NO_GO rule also did not fire.

The maximum single-market share of the positive fleet MSE-improvement sum was
Chicago at `26.42%`, below the `35%` cap. Austin, Denver, and Miami contributed
negative signed shares; the fleet result was not manufactured by discarding
them.

### Per-market native-unit metrics

| Market (unit, n) | Primary raw S/M/A | Primary baseline S/M/A | Primary challenger S/M/A | 1-7 raw S/M/A | 1-7 baseline S/M/A | 1-7 challenger S/M/A |
|---|---:|---:|---:|---:|---:|---:|
| Atlanta (F, 114) | 2.578/3.366/17.200 | 0.098/2.392/10.013 | 0.409/2.406/9.832 | 2.223/3.104/14.865 | -0.024/2.464/11.048 | 0.186/2.293/9.175 |
| Austin (F, 114) | 4.988/5.066/38.353 | 1.335/2.592/14.226 | 1.524/2.590/14.504 | 4.430/4.554/33.682 | 0.667/2.477/14.252 | 1.087/2.463/13.380 |
| Chicago (F, 114) | 1.811/3.315/17.875 | 1.981/2.932/17.657 | 1.619/2.776/14.837 | 1.815/3.148/15.489 | 1.999/2.803/15.901 | 1.633/2.643/13.680 |
| Dallas (F, 114) | 4.872/5.279/37.302 | 2.336/3.086/14.250 | 2.100/2.977/13.348 | 4.465/5.075/34.136 | 1.496/2.637/10.771 | 1.776/2.827/11.974 |
| Denver (F, 111) | 1.338/2.996/19.719 | 0.297/2.839/16.410 | 0.284/2.837/17.194 | 1.300/2.740/17.894 | 0.234/2.621/15.435 | 0.153/2.636/15.948 |
| Houston (F, 114) | 4.861/4.979/32.012 | 2.159/2.696/12.867 | 2.129/2.575/11.310 | 4.635/4.740/29.291 | 1.824/2.478/11.106 | 1.951/2.386/10.823 |
| Los Angeles (F, 114) | 2.352/3.049/13.066 | -0.929/1.953/7.006 | -0.881/1.891/6.253 | 2.227/2.861/11.787 | -1.079/1.894/6.647 | -1.179/1.849/5.761 |
| Miami (F, 114) | 1.836/1.982/7.298 | 0.118/1.395/3.928 | -0.092/1.582/4.278 | 1.664/1.854/6.643 | -0.113/1.469/3.965 | -0.201/1.596/4.419 |
| NYC (F, 114) | 2.945/3.527/18.933 | 0.584/2.501/10.928 | 0.575/2.490/10.115 | 2.612/3.170/15.762 | 0.186/2.321/9.483 | 0.270/2.153/8.001 |
| San Francisco (F, 114) | 9.458/9.480/114.087 | -0.111/3.181/16.407 | 0.551/3.070/14.291 | 8.911/8.961/103.426 | -0.208/3.174/17.051 | 0.474/3.038/14.091 |
| Seattle (F, 114) | 4.082/4.900/37.250 | -0.088/3.226/17.128 | 0.204/3.012/16.049 | 3.618/4.508/33.132 | -0.898/3.232/17.039 | -0.316/3.000/15.517 |
| Toronto (C, 114) | 0.952/2.035/6.054 | 0.667/1.756/4.413 | 0.237/1.493/3.844 | 0.902/1.888/5.266 | 0.609/1.630/3.890 | 0.102/1.485/3.718 |

### Per-month Celsius-equivalent metrics

| Month (n) | Primary raw S/M/A | Primary baseline S/M/A | Primary challenger S/M/A | 1-7 raw S/M/A | 1-7 baseline S/M/A | 1-7 challenger S/M/A |
|---|---:|---:|---:|---:|---:|---:|
| May (264) | 1.114/2.021/7.305 | 0.198/1.533/4.211 | 0.330/1.551/4.275 | 0.986/1.894/6.570 | 0.071/1.471/3.910 | 0.179/1.488/3.928 |
| June (360) | 1.822/2.245/8.699 | 0.722/1.490/4.233 | 0.674/1.457/4.092 | 1.665/2.055/7.690 | 0.574/1.419/3.911 | 0.525/1.388/3.785 |
| July (371) | 2.427/2.628/11.133 | 0.443/1.381/3.368 | 0.471/1.364/3.297 | 2.278/2.459/9.967 | 0.244/1.299/3.151 | 0.334/1.278/3.019 |
| August (370) | 2.325/2.558/10.555 | 0.248/1.529/4.209 | 0.149/1.383/3.358 | 2.152/2.407/9.473 | 0.032/1.476/4.024 | 0.057/1.354/3.269 |

## Missingness, isolation, and immutability

- 1,365 terminal rows were evaluated with zero feature-missing rows and zero
  baseline/challenger cohort mismatches.
- Three of the nominal 1,368 market-days were excluded solely by the frozen WU
  `row_count < 18` rule; Denver retained 111 rows and every other market 114.
- No `precipitation_probability` value was used.
- Native-unit handling, matched-row parity, outcome isolation, and corpus parity
  all passed.
- The run made zero provider calls, market-data reads, 2026 data/outcome reads,
  production or Scheduler accesses, corpus/mirror writes, and release,
  promotion, pointer, alpha, confirmation-window, distribution, or serving
  actions.
- Post-run P0 repeated the full 745-file rehash with zero errors. Corpus
  manifest, retained inventory, WU file inventory, corpus ACL proof, and mirror
  ACL proof all matched their pre-run values exactly.

## Durable and scratch evidence

Tracked:

- design: `docs/roadmap/multiyear-nwp-residual-design-2026-09-88a.json`
  (`0667fdc204360122f44e35f2ef31dad5d6f7f53afd83bfd09ba0f0a50874bc65` file hash);
- harness: `src/weather/calibration/multiyear_nwp_residual.py`;
- focused tests: `tests/calibration/test_multiyear_nwp_residual.py`.

Large and outcome-bearing evidence remains under the ignored scratch root
`C:\Users\Michael\Documents\github\weather\scratch\runs\multiyear-nwp-residual-09-88a`:

| Artifact | SHA-256 |
|---|---|
| `p0-pre.json` | `d997534449f60ffd27b5f21688cfc2f4fec78f0338eeab57ea3362ffeb5f2d95` |
| `p0-post.json` | `be25eab1e4ca4199022183b3e1c1709cbf8f3af1cb559303e6c3a9ef389d9ee1` |
| `training/training-receipt.json` | `5581c517e8a76399e7e0bdbac1c31ec059d67be977a0f7b54057d602018571b8` |
| `training/temperature-residual-baseline.pkl` | `c1ee07eef33016633ebf1ffdf847c7b55d90a2420b198eac7fb07ee88f5c2797` |
| `training/eleven-field-residual-challenger.pkl` | `0ae3e67cfcda420a9c0103959b2c79cac6438d7fadf162b41f36a47919862ab5` |
| `terminal/terminal-evaluation-attempt.json` | `c596d921ebeb3c37b44a3d49989813d53289057bba02f8896aadd82fbe92b8cd` |
| `terminal/evaluation-records.csv` | `6888cdf6655448defd5b46b811ecd9bcf36b397b425b8322f37d083619a9b876` |
| `terminal/result.json` | `1bb76d52daadecc2a4f978af56a0476c9ee43ae9ac097a8162630b51c803a656` |
| `result-verification.json` | `049488d4ad679f80226471ae424f8dcb6555cab13e219181e656a9a433b3f5d9` |

The terminal result self-hash is
`87cbece04a259cb4dc6f439ee19dd411ef6957b0d52b2b4136fe1aa1aed6c63c`.
Independent verification reproduced evaluation hash
`274e9859bac410803d69fbc72850b376b8da921a3f277e2e12cd5077ad7e3161`
from the sealed evaluation record with zero model refits and without reopening
source outcomes.

## Verification

All heavy commands ran under `scripts/ops/workstation_heavy.ps1` with the
`workstation_offline_v1` lease and repository-owned kill-on-close job.

- Focused calibration, schema-registry, unit-conversion, isolation, seed,
  decision-rule, and bootstrap tests: **25 passed**.
- Focused `compileall` over the new module, dispatch, and tests: **passed**.
- Deterministic sealed-result reproduction: **passed**; same bootstrap result,
  zero refits, no source-outcome reopen.
- Pre/post corpus rehash and ACL comparison: **passed**.
- Repository agent-docs audit: **passed** (18 agent files, 834 Markdown
  files).
- `git diff --check`: **passed** before the report; repeated in final branch
  verification.
