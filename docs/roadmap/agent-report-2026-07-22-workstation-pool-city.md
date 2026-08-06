# Agent Report - 2026-07-22 Pooled vs Per-City Training

## Corrected disposition - 2026-07-23

Generation-002 is the authoritative result for this report. It completed
`350/350` model tasks with zero resumed tasks, passed both its completion-time
source-closure check and an independent checkpoint/artifact verifier, is
marked `research_only=true`, and records `promotion_permission="forbidden"`.

The corrected result supports **retaining pooled training as the research
baseline**. On the fixed 2025 confirmation window, pooled has lower
market-band Brier than per-city and leave-one-city-out (LOCO) training on all
14 fleet dates. This is a corrected rerun of a window whose outcomes had
already been inspected in earlier, invalid generations. It is therefore
robustness evidence, not a new independent first look or prospective
confirmation. It grants no permission to serve, promote, release, trade, or
change an operational route.

## Why the earlier result was ineligible

The original run claimed that `prior_as_of_exclusive=2024-01-01` froze all
feature context before development and confirmation. That was false. The WU
climate prior respected the cutoff, but source-reliability statistics removed
only dates enumerated by the anchored WU cache. Independently loaded METAR,
GHCNh, and reanalysis indexes could therefore retain later dates.

The final `pool_source_cutoff_forensic_v0.4` receipt measured the defect across
the 12 markets:

| Retained by legacy behavior | METAR | GHCNh | Reanalysis | Total |
| --- | ---: | ---: | ---: | ---: |
| on or after 2024-01-01 | 10,414 | 10,300 | 10,378 | 31,092 |
| exactly on 2024-01-01 | 12 | 12 | 12 | 36 |
| strictly after 2024-01-01 | 10,402 | 10,288 | 10,366 | 31,056 |
| retained after corrected filtering | 0 | 0 | 0 | 0 |

The corrected implementation filters every source-index date strictly before
computing overlap/reliability statistics and tests a source-only future date
that is absent from the WU cache. The receipt is research-only and explicitly
grants no serving or release authorization.

Forensic receipt identities:

- receipt self-digest:
  `edd36e3f651284ae9c716aa586ecf83bc9d4470d3a68e936a37bc49ef3410d94`;
- whole-file SHA-256:
  `6c2647c1d2007c92bd8dee645b5e325668ad393e43005b98df6e71d6f5c7cefa`
  over 87,807 bytes;
- data-input manifest:
  `61bba688422757e5fe418bc3f394a18ec06bd0815bd4b1d549143f9e0e459f21`;
- method contract:
  `85d7c00681b543166a57c7b49c77f1aa1e6cf265108fb6e2f4dc690b949ed92a`;
- method source tree:
  `841965b8bd39dbf973fc7a198ff9632f8bcc6ac00b3bc5ec7755b2d710e73b5d`;
- audit script:
  `dc812fcc086ad4bccf147be8ac3b4119fe1053802e7d130029079273a2ef8e59`;
- tracked-worktree status receipt:
  `03055cc524b736b7f2fae91a34bbfb041691fdafd02442ddeaebf7ce958d163a`.

## Corrected generation-002 design

All three regimes use the same canonical continuous-density HGB trainer,
hourly feature contract, hyperparameters, canonical-F density grid, and native
C/F market-band projection. Only geographic fit scope changes. LOCO excludes
the scored market from both training and 2024 density tuning.

- Markets: all 12 built-ins; 11 settle in F and Toronto settles in C.
- Hours: 07 through 20 local.
- Tasks: 14 pooled, 168 per-city, and 168 LOCO; 350 total.
- Balanced panel: 162 complete fleet dates and 12 x 14 rows per date.
- Historical-window anchor: explicitly supplied and bound as `2026-07-22`.
- Feature-context cutoff: `2024-01-01` exclusive for WU climate and every
  independently loaded source-reliability index.

| Split | Date inventory | Fleet dates | Rows | Permitted use |
| --- | --- | ---: | ---: | --- |
| train | July 15-29 in 2015-2023, subject to complete-panel retention | 133 | 22,344 | model fitting |
| development | 2024-07-15 through 2024-07-29 | 15 | 2,520 | density width/shape selection only |
| confirmation | 2025-07-15 through 2025-07-27, plus 2025-07-29 | 14 | 2,352 | scoring only |

Within generation-002, confirmation rows were not used for fitting or density
tuning. Across the research program, however, 2025 results had already been
seen in the invalid runs. "Confirmation" above is the fixed split name and
protocol role, not a claim of analyst-level independence.

## Corrected confirmation metrics

The tables below reproduce the generation-002 JSON values. "Macro" is
equal-city aggregation; "micro" uses the exact native-band sufficient
statistics. Density log loss and MAE are row-level quantities and consequently
match under these balanced rows.

### Equal-city macro

| Unit | Regime | Markets | Band Brier | Band log loss | Density log loss | Winner Brier | MAE F |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ALL | pooled | 12 | 0.047008521981658995 | 0.18472765949363323 | 1.6358002113146324 | 0.4355243684227121 | 1.0403001297124834 |
| C | pooled | 1 | 0.03928783060018943 | 0.13493061844292434 | 1.1866209215658348 | 0.3594291086912862 | 1.1215489736137128 |
| F | pooled | 11 | 0.04771040301633804 | 0.18925466322551587 | 1.676634692200887 | 0.4424421193073871 | 1.032913871176008 |
| ALL | per-city | 12 | 0.07138937233306601 | 0.3083327573978611 | 2.2331733431086978 | 0.5755923703913127 | 1.3434311150934333 |
| C | per-city | 1 | 0.05830071184332181 | 0.2345364971328893 | 1.7600808222049047 | 0.46432893016883575 | 1.3437142988359425 |
| F | per-city | 11 | 0.0725792505594064 | 0.31504150833104033 | 2.2761817540999516 | 0.5857072285933561 | 1.3434053711168414 |
| ALL | LOCO | 12 | 0.07087913103052351 | 0.3865540959146736 | 2.9289209758921424 | 0.5298893737459419 | 1.7748423612694424 |
| C | LOCO | 1 | 0.05247153512838238 | 0.22634982237914936 | 1.783921961478766 | 0.40937347661675266 | 1.7526952927999522 |
| F | LOCO | 11 | 0.07255254883980906 | 0.4011181207815394 | 3.0330117953842675 | 0.54084536439405 | 1.776855731130305 |

### Native-band micro

| Unit | Regime | Rows | Band rows | Band weight | Band Brier | Band log loss | Density log loss | Winner Brier | MAE F |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ALL | pooled | 2,352 | 220,824 | 496,800 | 0.04759252444114227 | 0.1903207054531178 | 1.6358002113146335 | 0.43552436842271147 | 1.0403001297124834 |
| C | pooled | 196 | 15,524 | 35,996 | 0.03928783060018943 | 0.13493061844292434 | 1.1866209215658348 | 0.3594291086912862 | 1.1215489736137128 |
| F | pooled | 2,156 | 205,300 | 460,804 | 0.048241250926804057 | 0.19464753762475473 | 1.6766346922008883 | 0.4424421193073867 | 1.0329138711760075 |
| ALL | per-city | 2,352 | 220,824 | 496,800 | 0.07213816984223669 | 0.31466907921059334 | 2.233173343108699 | 0.5755923703913118 | 1.3434311150934308 |
| C | per-city | 196 | 15,524 | 35,996 | 0.05830071184332181 | 0.2345364971328893 | 1.7600808222049047 | 0.46432893016883575 | 1.3437142988359425 |
| F | per-city | 2,156 | 205,300 | 460,804 | 0.07321909174857627 | 0.3209286872532079 | 2.2761817540999525 | 0.5857072285933551 | 1.3434053711168394 |
| ALL | LOCO | 2,352 | 220,824 | 496,800 | 0.07134150557537848 | 0.3962686458649768 | 2.9289209758921433 | 0.529889373745941 | 1.7748423612694413 |
| C | LOCO | 196 | 15,524 | 35,996 | 0.05247153512838238 | 0.22634982237914936 | 1.783921961478766 | 0.40937347661675266 | 1.7526952927999522 |
| F | LOCO | 2,156 | 205,300 | 460,804 | 0.07281554541923857 | 0.40954196374024665 | 3.0330117953842683 | 0.5408453643940484 | 1.7768557311303064 |

Pooled reduces all-market macro band Brier by 34.15% relative to per-city and
33.68% relative to LOCO. It also wins the other reported macro and micro
proper scores and MAE. Descriptively, pooled has lower aggregate band Brier
than per-city for all 12 markets and lower aggregate band Brier than LOCO for
11 of 12; Atlanta is the small LOCO exception. These are corrected replay
descriptives, not additional independent tests.

## Corrected paired evidence

Delta is left minus right market-band Brier, so negative favors the left
regime. The bootstrap uses 10,000 fleet-date resamples; the sign test is exact.
The win columns are left/right/tie fleet dates.

| Unit | Comparison | Mean delta | 95% bootstrap CI | Wins | Exact sign p |
| --- | --- | ---: | ---: | ---: | ---: |
| ALL | pooled - per-city | -0.024496520467152377 | [-0.028373462256062097, -0.02072359840482595] | 14/0/0 | 0.0001220703125 |
| ALL | pooled - LOCO | -0.023773579271449678 | [-0.02727358968688195, -0.020234875571390403] | 14/0/0 | 0.0001220703125 |
| ALL | per-city - LOCO | 0.0007229411957027013 | [-0.005476167145680883, 0.006742369732660289] | 6/8/0 | 0.79052734375 |
| C | pooled - per-city | -0.018251357136686592 | [-0.03715587529994161, -0.0020691939282996732] | 10/4/0 | 0.1795654296875 |
| C | pooled - LOCO | -0.012881768352086318 | [-0.0185650699228768, -0.007385331022067558] | 12/2/0 | 0.012939453125 |
| C | per-city - LOCO | 0.0053695887846002665 | [-0.011656429239439506, 0.02436224277630229] | 7/7/0 | 1.0 |
| F | pooled - per-city | -0.02492721354570034 | [-0.02933257839745876, -0.0208066373561665] | 14/0/0 | 0.0001220703125 |
| F | pooled - LOCO | -0.024609824368817017 | [-0.028378083426550814, -0.02071174068532474] | 14/0/0 | 0.0001220703125 |
| F | per-city - LOCO | 0.0003173891768833203 | [-0.006378564633411029, 0.007066283796059209] | 8/6/0 | 0.79052734375 |

The fleet and F-family results are directionally uniform. The C family is only
Toronto: its pooled-versus-per-city bootstrap interval is below zero, but its
10/4 sign result is not conventionally significant. Nothing here establishes
a general multi-city Celsius-family effect.

## Run, corpus, input, and source closure

| Contract or identity | SHA-256 / value |
| --- | --- |
| run ID | `1c50d6b86750c7952463e2d98f97e58d32e8235fdc04a0a2186c3d9be1797ecd` |
| checkpoint run contract | `23514e454f8d8eb22e662e7e357b28c1eb673ab8df9e6dd262d987469b7d8f24` |
| corpus contract | `66d3da432cf57ac6621a8a799108c3c0abc75db10084bc1649faa8f7b941a1c2` |
| input-manifest self-digest | `96b7cb739267fb527ced8275106ac240390b8fd84f603dc45dfd30276c6a3334` |
| execution source contract | `3e3151f10b2edb38f65f538ea7317236178f6ff19a5b986f892863663f9b0220` |
| execution source tree | `80a24d4e3ab9643ac938448237ed6551169b6eb6e7bfc4bdedb95bd0cff8851d` |
| Git HEAD | `8660df3935171c532d7ec8ed7b19c99122e7806e` |
| Git HEAD tree | `80b00baa00db58a8d6156ca05ca344a1fb534158` |
| tracked-worktree status receipt | `03055cc524b736b7f2fae91a34bbfb041691fdafd02442ddeaebf7ce958d163a` |

Completion-time verification was `PASS` with
`exact_initial_completion_match=true`: the source contract, source tree, Git
identity, and tracked status exactly matched the initial closure after all 350
tasks completed.

The input manifest contains 262 path records: 257 files opened and read, five
checked and missing, and 455,940,120 bytes read. Its guard is enabled under
`python_open_and_common_pathname_mutation_v0.2`. During corpus load it blocks
write-capable Python `open` calls and common `pathlib`, `os`, and `shutil`
pathname mutation APIs, including lexical/canonical aliases, reparse entries,
and rename/replace destinations; copy-out to the separate scratch output is
allowed.

The recorded scope is deliberately narrower than an operating-system
sandbox: raw pre-opened descriptors and direct native calls are outside the
guard. The audited loaders use neither, and the real-corpus generation
completed without a guarded mutation attempt. This receipt demonstrates the
audited Python load path, not universal impossibility of writes by arbitrary
native code.

## Checkpoints, runtime, and artifact receipts

The final ledger is `pool_city_checkpoint_status_v0.2` and records `350/350`
completed tasks, zero resumed tasks, and 1,349.268864999991 seconds through
the model loop. Total run time was 1,395.4085952999885 seconds (23.26
minutes), versus a 1,649.9135351999996-second pilot estimate. Reporting-only
finalization reused all 350 authenticated checkpoints, retrained zero models,
and preserved the run ID.

The runtime plan records a 107,646,208-byte private-memory estimate and a
4,294,967,296-byte budget. The corrected generation artifact does not contain
a measured peak-memory sample, so the 107.6 MB value is a planning estimate,
not an observed process ceiling. The run completed without a runtime or
memory stop.

The independent verifier reloaded all 350 exact task contracts and
checkpoints, checked each checkpoint self-digest against the authoritative
ledger, checked the complete task inventory and input-manifest bindings, and
rechecked the final source verification. It returned `PASS` with no
verification errors, 350 checkpoint files, 350 unique task IDs, and zero
resumed tasks.

Whole-file hashes are distinct from JSON self-digests:

| Artifact | Bytes | Whole-file SHA-256 | Embedded/content identity |
| --- | ---: | --- | --- |
| `pool_city_training_benchmark.json` | 571,873 | `478ce996b2c2ff85d9ab4af29c643a35388c4c70025da20e6b9d815a18a31429` | run ID above |
| `pool_city_training_benchmark.md` | 6,107 | `177b69f205189ed17b107d961db4f2d239f8e8b5f316b47770b0aac8406e7eb1` | rendered result |
| `predictions.csv` | 3,146,201 | `ee2ea4ffe31d0e6b2839f49c2a994515c81fcb8907f8706ea70e0cd7dc6da600` | bound by checkpoint results |
| `checkpoint_status.json` | 44,652 | `901f2cdf7ea8eb01fe272611004d780a4d5680b1eeb89d1fc26a3b1f69c70050` | status self-digest `087310c421f6f3e329d582c154501b2114dc6e51880f1edd6ad4385f5ee16e0f` |
| `input_manifest.json` | 74,128 | `bc8c8f9696e7f4c83e9ba837cef4e6d2d0f685651230f1107ff322c169a1cc84` | manifest self-digest `96b7cb739267fb527ced8275106ac240390b8fd84f603dc45dfd30276c6a3334` |
| `runtime_plan.json` | 1,219 | `302a2c82d757a30878d7c3f0d81044b4fd5dc93ee6d74570568d24ac80b95822` | run ID above |
| sorted checkpoint inventory | 43,036 | `b6c1a09577ee5f6344fbe2d56f191f4da12ff29427492e5023ed1cd5271169e6` | 350 `<path><TAB><size><TAB><sha256><LF>` rows |

Primary output directory:
`scratch/workstation-research-output/followup-assurance/pool-city-hardened-generation-002/`.

## Invalidated run chronology

Three earlier result paths must not be combined with generation-002:

1. The original completed run
   (`df853773dfea2af3e1f1bb1227248ac34d640d99f907ea173ee8f838adc30f1b`)
   used the future-informed source-reliability context. Its pooled/per-city/LOCO
   macro Briers (`0.047053`, `0.071389`, `0.070298`) and all derived
   hour/city, hybrid, bias, and blend narratives are historical diagnostics
   only.
2. Hardened generation-001
   (`4a7207a274ca710aab3e2b74a27e20df2ab62def6a83bd7c701f3d2ab302ecc0`)
   corrected the historical calendar-window anchor, but still leaked
   post-cutoff source-reliability dates. Its macro Briers (`0.048173463175389473`,
   `0.07381471568118318`, `0.07166716172707004`) remain future-informed and
   ineligible.
3. The first attempt to produce generation-002
   (`e7c92c1bdb5b809b60bf59a5f1cfe1e180125717533f4e122eb9fee167f24905`)
   was declared invalid when source-closure drift was detected at the
   22-checkpoint observation. Stop/worker teardown was not instantaneous; its
   preserved final ledger contains 59/350 checkpoints, last task
   `per_city__miami__h09`. The directory was renamed
   `pool-city-hardened-generation-002-invalidated-source-closure`, produced no
   final benchmark result, and contributed no checkpoint to the authoritative
   fresh run.

Generation-002 started from an empty output directory only after source
closure stabilized. Its zero-resume ledger and independent 350-checkpoint
inventory prove that none of the invalidated checkpoints were reused.

An even earlier identity-debug attempt stopped after 40 tasks because
non-contractual corpus load time had been included in the corpus identity.
Those checkpoints were quarantined and likewise never reused. This remains a
harness-development incident, not evidence about topology.

## Limits and next step

The corrected score covers only 14 complete July fleet dates. Complete-panel
filtering can select for cleaner days, the C family is one market, and the
2025 outcomes are already exposed to the research program. This is not
release-bound captured-input replay, and forecast skill is not evidence of
edge over market prices.

The defensible disposition is narrow: preserve pooled training as the
research baseline; reject pure per-city and pure LOCO as replacements on this
corrected replay; and require genuinely new, predeclared dates or seasonal
windows for hierarchical or partial-pooling research. Promotion remains
forbidden. No serving, release, collector, scheduler, paper/live trading, or
operational change follows from this report.
