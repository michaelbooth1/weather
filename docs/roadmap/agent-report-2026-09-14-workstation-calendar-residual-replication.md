# Workstation calendar residual replication report

## Disposition

`INCONCLUSIVE_UNDERPOWERED`

The independently precommitted outside-window 2025 replication does not pass
the prospective point-shadow gate. The combined primary MSE and MAE point
directions are favorable, as is the all-leads MSE direction, but the combined
crossed intervals include zero, the February-May 9 primary MSE direction is
adverse, and the maximum single-market contribution exceeds 35%. No
statistically established combined harm appears, so `NO_GO` is not applicable.

This is a research-only point-forecast result. It authorizes no probability
distribution work, production retraining, release, promotion, pointer change,
serving, candidate freeze, alpha allocation, confirmation window, or branch
merge.

## Source and pre-outcome sequence

The mission started from the exact source branch
`origin/codex/workstation-collect-calendar-extension-2026-09-89a`, tip
`7839340f252df3f908aa82dac2b6aaea861f8c0e`, and tree
`262648395c178d41bc869069e4329883f5cc9b02`.

The outcome-isolation harness was committed before P0 at
`1f3374720abe6b6a35683822259dc84a6aeeb7c2` (tree
`29378f107780fb294b58b11cec5d7256a930e19d`). P0 then inspected only
`schema_version`, `local_date`, `temperature_unit`, and `row_count` in the WU
files. It did not invoke the outcome reader. The frozen design was committed at
`5ce4a11a` before either model fitting or any selected 2025 outcome-value
access. The evaluation command also required the design bytes to equal the
version committed in `HEAD`.

## P0 corpus, feature, WU, and ACL proof

| Object | Pre/post result | Bound identity |
|---|---|---|
| Original May-August corpus | PASS; 745 commissioned retained files rehashed; zero integrity errors | manifest `d41bd21efb7a62396851fe016a215db1ac8bea7de97f387333902aba7a35bb00`; inventory `0a92a267d5609950302182c53862d8bab77fd95b207e6805a8a2c968a7566933` |
| Calendar extension | PASS; 581 commissioned files verified (580 retained-inventory entries plus the self-hashed terminal verification envelope); zero integrity errors | manifest `501e5d0e22a0a21c9b0828e28dfa13b9ebc0043ab5c1e9335dda1d619689b448`; inventory `6b0760c3ac178c8eba61332934773d89042511c237bbb47d5a2982be089b2d20` |
| Required feature coverage | PASS | 3,696 complete original 2024 cells; 7,392 complete extension 2024 cells; 7,392 complete extension 2025 cells |
| WU source inventory | PASS; 12 files | `74a291ee764dccc54ca410f3e9d4e271cc7a6a678c7ab351cc6865ad6e270a5d` |
| ACL proof | PASS | original corpus, extension corpus, and mirror ACL objects matched before/after; both corpus roots retained explicit `CodexSandboxOffline` Write/Delete denial |

The eleven fields and leads 1-7 were complete on every commissioned forecast
surface from 2024-02-01 through 2024-12-31 and on both 2025 evaluation
segments. January was excluded symmetrically. `precipitation_probability` was
excluded everywhere. The complete post-run corpus, coverage, WU inventory, and
ACL objects were byte-for-byte equivalent to their pre-run objects.

| Receipt | File SHA-256 | Self-hash |
|---|---|---|
| P0 pre | `a33831e2ba633ff3bcc0bf949822077d36cf1c92ff5aa0bbc767307041678ca2` | `1fca630aa1ffdcbb6c8399957589572ed240c135b9a90a8788ed2805f56182b4` |
| P0 post | `cfe11bd7af58c764aec6b6a383552edfd502b273deea28191f5dacb57980dc9c` | `05740405b9352c8d0c4739f45d3370c7a810e676079e0e807452384552c20e6f` |

## Frozen design and training

| Object | SHA-256 |
|---|---|
| Frozen design file | `582e80f459dea40844cf2fb0a780da1c726866b6d569694ec56d1b23e0bf898d` |
| Frozen design self-hash | `5ad194a5d1729ddaf5e42afe53851eab20f7c48621fa4e5fde1764f8f5143b60` |
| Harness module | `6998f6d1b1fd097835bb4eaf687a8d6423bc16ba6902571f1d602bf478347511` |
| Prior frozen design file / self-hash | `0667fdc204360122f44e35f2ef31dad5d6f7f53afd83bfd09ba0f0a50874bc65` / `bd4bdb2ebcdd67a498e461b455f77bc9ca5a88f73bb19dae389e4bb28e26c0fb` |
| Baseline feature order | `4e35fe7e2d44d37e22ff02b2b681c2de840a487d1eeddef7cace58b2852bf603` |
| Challenger feature order | `5839aa7373cdd78d4d54cccfa27d7d8b42ffb8acc5d80e08135561335fa2c3fb` |
| Estimator configuration | `02f56f2f5e67dfe4b85e739777794a66fbd8d2742bed62d6c68df22e132298ea` |
| Training receipt file / self-hash | `0750863a177c9a19fc2ee9005f02f207d0c36b126932cbc9ab4e28ab1ff20de4` / `a487197f96f78372eced8cec453e46dd9aaa0500e64108a75f3dfdf4dcd510a6` |
| Temperature residual baseline model | `4d7390a974bfe35b6c69d72f618a97252a6d2fcb8e7c31659a7949d4625da235` |
| Eleven-field residual challenger model | `39a790d77607899a163086e92196e0458e23bfe516aa3d01d64f577fb3d37f5e` |

The frozen contract retained the prior 17-feature baseline, 39-feature
challenger, native-unit target, one-row/one-weight rule, preprocessing, HGB
configuration, model seed `42`, primary leads 2-7, and no-refit leads 1-7
sensitivity. Exactly two `.fit()` calls occurred. Training admitted 4,003
market-days, 334 date clusters, and all 12 markets from the 335 nominal 2024
dates. The 17 WU exclusions were 2024-03-10 for every market plus Toronto on
2024-04-16, 2024-04-17, 2024-04-18, 2024-06-25, and 2024-07-11. Feature
missingness and arm mismatch were both zero.

## Terminal attempt and support

The create-only terminal-attempt file was created before the selected 2025 WU
values were opened. Its file hash is
`806adc65c6a12640555c4726278ad16b2a6fa299f8d14b984de0c0991e950bea`
and its self-hash is
`e740304adfd0c7b24eee50ea8276c8478f22d9e5efa07dfb577cf85a76a41dc3`.
It authorizes one source evaluation, zero January accesses, zero spent-window
accesses, and no rerun.

| Cohort | Nominal dates | Admitted dates | Markets | Nominal market-days | Admitted market-days | WU exclusions |
|---|---:|---:|---:|---:|---:|---:|
| 2025-02-01 through 2025-05-09 | 98 | 97 | 12 | 1,176 | 1,162 | 14 |
| 2025-09-01 through 2025-12-31 | 122 | 122 | 12 | 1,464 | 1,462 | 2 |
| Combined, never pooled with spent May-August | 220 | 219 | 12 | 2,640 | 2,624 | 16 |

The early exclusions were 2025-03-09 for every market, plus Denver on
2025-03-27 and 2025-05-05. The late exclusions were Denver on 2025-09-01 and
2025-09-02. These were the only evaluation exclusions and were caused by WU
`row_count < 18`. There were zero missing feature rows, arm mismatches,
January rows, spent May 10-August 31 rows, or
`precipitation_probability` rows.

## Point metrics

All fleet values are Celsius-equivalent. Signed error is forecast minus WU;
MSE is in C-equivalent squared units.

### February through May 9

| Lead set / forecast | Signed error | MAE | MSE |
|---|---:|---:|---:|
| Leads 2-7 raw anchor | -0.127486 | 1.834256 | 6.377456 |
| Leads 2-7 baseline | -0.150849 | 1.599086 | 5.088873 |
| Leads 2-7 challenger | -0.146139 | 1.610183 | 5.165609 |
| Leads 1-7 raw anchor | -0.164104 | 1.692197 | 5.391282 |
| Leads 1-7 baseline | -0.243128 | 1.491589 | 4.411434 |
| Leads 1-7 challenger | -0.179248 | 1.488220 | 4.389881 |

### September through December

| Lead set / forecast | Signed error | MAE | MSE |
|---|---:|---:|---:|
| Leads 2-7 raw anchor | 0.576851 | 1.746633 | 5.612382 |
| Leads 2-7 baseline | 0.084583 | 1.477447 | 4.040129 |
| Leads 2-7 challenger | 0.069545 | 1.453321 | 3.898139 |
| Leads 1-7 raw anchor | 0.459302 | 1.601208 | 4.827364 |
| Leads 1-7 baseline | -0.088348 | 1.403039 | 3.642157 |
| Leads 1-7 challenger | -0.029010 | 1.361738 | 3.444538 |

### Combined

| Lead set / forecast | Signed error | MAE | MSE |
|---|---:|---:|---:|
| Leads 2-7 raw anchor | 0.264945 | 1.785436 | 5.951184 |
| Leads 2-7 baseline | -0.019674 | 1.531313 | 4.504550 |
| Leads 2-7 challenger | -0.025967 | 1.522785 | 4.459420 |
| Leads 1-7 raw anchor | 0.183236 | 1.641502 | 5.077087 |
| Leads 1-7 baseline | -0.156890 | 1.442252 | 3.982820 |
| Leads 1-7 challenger | -0.095541 | 1.417749 | 3.863169 |

## Crossed inference and improvements

Every partition used 20,000 shared-weight crossed target-date x market
pigeonhole bootstrap draws with seed `8802026`. Positive values favor the
challenger.

| Cohort / endpoint | Point | Crossed 95% interval | Achieved power | MDE80 |
|---|---:|---:|---:|---:|
| Early primary MAE, C | -0.011097 | [-0.068032, 0.042773] | 0.068220 | 0.078361 |
| Early primary MSE, C^2 | -0.076736 | [-0.432731, 0.258934] | 0.072386 | 0.489372 |
| Early all-leads MAE, C | 0.003369 | [-0.053690, 0.058802] | 0.051602 | 0.079856 |
| Early all-leads MSE, C^2 | 0.021553 | [-0.309737, 0.373610] | 0.051820 | 0.479306 |
| Late primary MAE, C | 0.024126 | [-0.041726, 0.105450] | 0.098475 | 0.105194 |
| Late primary MSE, C^2 | 0.141990 | [-0.209962, 0.595860] | 0.106093 | 0.576416 |
| Late all-leads MAE, C | 0.041302 | [-0.029269, 0.129127] | 0.176281 | 0.112906 |
| Late all-leads MSE, C^2 | 0.197619 | [-0.139796, 0.633143] | 0.170748 | 0.552142 |
| Combined primary MAE, C | 0.008528 | [-0.039539, 0.062213] | 0.062574 | 0.072377 |
| Combined primary MSE, C^2 | 0.045130 | [-0.242193, 0.355152] | 0.060520 | 0.418504 |
| Combined all-leads MAE, C | 0.024504 | [-0.026508, 0.082768] | 0.142597 | 0.077903 |
| Combined all-leads MSE, C^2 | 0.119651 | [-0.159914, 0.434173] | 0.123221 | 0.426478 |

The draw-matrix hashes were
`5cbb3248044741a4899787167826229dfca0cdcf2a58b7703e0c02ba88cc882c`
for the early segment,
`5f7a720850fe3c88afb684f406d5e97c281f9c1e19c615350399f474533851e3`
for the late segment, and
`625db1caa76f77347e0c0fe05634bbb53bc663acdb0ec673c4d4478fafa48ff1`
combined.

## Per-market effects

Values are baseline minus challenger in each market's native unit: MAE in F or
C and MSE in F^2 or C^2. `P` is primary leads 2-7 and `A` is the no-refit
all-leads sensitivity.

### February through May 9

| Market | Unit | N | P dMAE | P dMSE | A dMAE | A dMSE |
|---|---:|---:|---:|---:|---:|---:|
| Atlanta | F | 97 | -0.070444 | -0.957682 | -0.094687 | -0.922284 |
| Austin | F | 97 | -0.008757 | -0.884444 | 0.056407 | -0.627847 |
| Chicago | F | 97 | 0.109688 | 1.487269 | 0.167131 | 2.345221 |
| Dallas | F | 97 | -0.304648 | -3.215850 | -0.208790 | -2.494086 |
| Denver | F | 95 | 0.061623 | 1.300308 | 0.051062 | 1.633114 |
| Houston | F | 97 | -0.012809 | 0.159934 | -0.139169 | -0.700844 |
| Los Angeles | F | 97 | 0.052739 | 1.068887 | 0.148173 | 1.435321 |
| Miami | F | 97 | 0.020484 | -0.049113 | 0.013329 | -0.002939 |
| NYC | F | 97 | -0.021528 | -0.802115 | 0.151819 | 0.374749 |
| San Francisco | F | 97 | -0.103810 | -1.527193 | -0.072839 | -0.812079 |
| Seattle | F | 97 | 0.086280 | 0.827673 | 0.006313 | 0.719248 |
| Toronto | C | 97 | -0.026020 | -0.110875 | -0.002805 | -0.023874 |

The early primary fleet improvement sum was -89.167346 C-equivalent squared;
therefore no positive-fleet contribution share exists for this adverse
partition.

### September through December

| Market | Unit | N | P dMAE | P dMSE | A dMAE | A dMSE |
|---|---:|---:|---:|---:|---:|---:|
| Atlanta | F | 122 | -0.120040 | -1.417707 | -0.073419 | -1.210042 |
| Austin | F | 122 | -0.043806 | 0.047465 | -0.013434 | -0.011396 |
| Chicago | F | 122 | 0.049740 | 0.467303 | 0.081926 | 1.047913 |
| Dallas | F | 122 | -0.132423 | -1.721827 | -0.133090 | -1.345630 |
| Denver | F | 120 | -0.092081 | -0.371178 | -0.040035 | 1.335817 |
| Houston | F | 122 | 0.054035 | -0.192874 | -0.056878 | -0.669167 |
| Los Angeles | F | 122 | 0.503633 | 5.185971 | 0.565465 | 5.655810 |
| Miami | F | 122 | -0.055903 | -0.196809 | -0.054162 | -0.365957 |
| NYC | F | 122 | -0.103817 | -0.542077 | -0.034796 | -0.287599 |
| San Francisco | F | 122 | 0.340228 | 4.129022 | 0.438192 | 2.603849 |
| Seattle | F | 122 | 0.195261 | 0.716970 | 0.149913 | 0.552037 |
| Toronto | C | 122 | -0.042181 | -0.184362 | 0.033643 | 0.120119 |

The late maximum signed contribution was Los Angeles at `0.940679` of the
positive fleet sum.

### Combined

| Market | Unit | N | P dMAE | P dMSE | A dMAE | A dMSE |
|---|---:|---:|---:|---:|---:|---:|
| Atlanta | F | 219 | -0.098073 | -1.213952 | -0.082839 | -1.082587 |
| Austin | F | 219 | -0.028282 | -0.365298 | 0.017500 | -0.284436 |
| Chicago | F | 219 | 0.076292 | 0.919068 | 0.119665 | 1.622520 |
| Dallas | F | 219 | -0.208705 | -2.383563 | -0.166619 | -1.854307 |
| Denver | F | 215 | -0.024165 | 0.367385 | 0.000217 | 1.467181 |
| Houston | F | 219 | 0.024428 | -0.036607 | -0.093326 | -0.683197 |
| Los Angeles | F | 219 | 0.303922 | 3.362422 | 0.380637 | 3.786461 |
| Miami | F | 219 | -0.022070 | -0.131392 | -0.024269 | -0.205168 |
| NYC | F | 219 | -0.067369 | -0.657254 | 0.047860 | 0.005770 |
| San Francisco | F | 219 | 0.143554 | 1.623758 | 0.211845 | 1.090858 |
| Seattle | F | 219 | 0.146991 | 0.766003 | 0.086309 | 0.626099 |
| Toronto | C | 219 | -0.035023 | -0.151813 | 0.017500 | 0.056341 |

The combined positive fleet sum was 118.421306 C-equivalent squared. Los
Angeles supplied the maximum signed share, `1.919206`, which exceeds the
precommitted 0.35 limit.

## Per-month effects

Because the two seasonal segments do not overlap in month, this table is also
the complete per-month view for each segment and for the combined result.
Values are C-equivalent baseline-minus-challenger improvements.

| Month | N | P dMAE | P dMSE | A dMAE | A dMSE |
|---:|---:|---:|---:|---:|---:|
| 2 | 336 | -0.035471 | -0.313682 | -0.010141 | -0.141069 |
| 3 | 359 | 0.007635 | 0.051611 | 0.020333 | 0.143131 |
| 4 | 360 | 0.016386 | 0.113310 | 0.015157 | 0.146923 |
| 5 | 107 | -0.089878 | -0.402711 | -0.050780 | -0.297499 |
| 9 | 358 | 0.062896 | 0.357391 | 0.107042 | 0.442156 |
| 10 | 372 | 0.017238 | 0.020398 | 0.025295 | 0.103379 |
| 11 | 360 | 0.004789 | 0.123612 | -0.004007 | 0.094303 |
| 12 | 372 | 0.012416 | 0.074070 | 0.037889 | 0.156508 |

## Precommitted decision checks

| Condition | Result |
|---|---|
| Combined MSE positive with crossed lower 95% above zero | FAIL: point 0.045130; lower -0.242193 |
| Combined MAE nonnegative with lower 95% at least -0.02 C | FAIL: point 0.008528; lower -0.039539 |
| Leads 1-7 favorable MSE direction | PASS: 0.119651 |
| Both seasonal segments favorable primary MSE direction | FAIL: early -0.076736; late 0.141990 |
| Maximum single-market contribution at most 0.35 | FAIL: 1.919206 |
| At least 200 dates and all 12 markets | PASS: 219 dates; 12 markets |
| Isolation, native units, corpora, and matched rows | PASS |

The combined primary MSE achieved power was `0.060520`; its MDE80 was
`0.418504 C^2`. Neither combined harm endpoint had an upper 95% bound below
zero, so the terminal rule returns `INCONCLUSIVE_UNDERPOWERED`.

## Reproduction and prohibited-actions audit

| Artifact or assertion | Result |
|---|---|
| Evaluation records | `573dd50a2391ed826be640b15921b6902482d8d3577252e629b71492b4d28eb8` |
| Result file / self-hash | `3ed44a969e7cb66b1c760cb6f722fe969194fa0f493fb16078c7a17deefe1d11` / `dadd2baa00c3ec9ece8e157a9b37d113d8ef7f695368561635fa713a842557cb` |
| Deterministically reproduced evaluation | `d0bcc1da3dee05551b403a8a5cd1dd50a9e0048dc1bb9fd231694e2c025985be` |
| Verification file / self-hash | `4ea06d53fc72eca489b214df4896d0e87723d6970bfcf9393429b7f8c2e61e26` / `f30b161898033efb4fed7dddb9bd133a47bc837aff8b3d9bdb810b15b763f546` |
| Source outcomes reopened during reproduction | PASS: false |
| Models refitted during reproduction | PASS: 0 |
| Bootstrap reproduced | PASS: true |

Verification commands ran through `scripts/ops/workstation_heavy.ps1`:

| Verification | Result |
|---|---|
| Focused replication, schema, wrapper, and hook suites | PASS: 81 passed, 11 skipped |
| Compileall (`app`, `src`, `tests`, `.codex/hooks`) | PASS, exit 0 |
| Agent-document audit | PASS: 18 agent files, 836 Markdown files |
| Roadmap lint/generated-view check | PASS: generated report matches sources |
| Complete repository suite | Honest non-PASS: 4,350 passed, 23 skipped, 13 warnings, 866 subtests passed, 12 failed in 645.71 seconds |
| `git diff --check` | PASS, exit 0 |
| Canonical roll verdict | `UNDECIDABLE: no live closure evidence`, exit 1 |

All 12 complete-suite failures are the unchanged source-branch failures in
`tests/operations/test_experiment_executor.py`; each fails when its temporary
staged result parent has already disappeared before the atomic JSON write. The
first complete run also found the new module missing from the Codex host-load
hook allowlist. That mission-caused ratchet was repaired, the expanded focused
suite passed, and the final complete run contains no failure outside the same
12-test source baseline.

The roll verdict was obtained from `scripts/ops/roll_verdict.ps1`; no manual
classification was substituted. This isolated workstation worktree has none of
the four required live supervisor closure files, so the canonical command
failed closed as `UNDECIDABLE`.

The run made zero provider calls, 2026 data or outcome reads, January outcome
value accesses, spent May-August 2025 outcome value accesses or evaluation-row
reuse, market-data reads, production or Scheduler accesses, corpus or mirror
writes, probability-distribution work, hyperparameter or feature searches,
release/promotion/pointer/serving/candidate-freeze/alpha/confirmation actions,
and branch merges. The only fits were the exact two precommitted 2024 models;
the only terminal source evaluation was the single sealed outside-window 2025
attempt.

Large artifacts remain under
`C:\Users\Michael\Documents\github\weather\scratch\runs\calendar-residual-replication-09-90a`.
