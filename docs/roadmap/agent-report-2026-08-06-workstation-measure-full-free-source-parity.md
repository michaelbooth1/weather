# Workstation full free-source parity measurement - 2026-08-06

## Verdict

**MEASUREMENT COMPLETE; P0 PASSES; NO-GO FOR ACTIVATION OR A FLEET
RETRAIN.** Correct canonical-JSON verification hydrates all 254 selected Toronto
ECCC snapshot sources with zero integrity rejects. On the 254 eligible Toronto
snapshots, `humidity`, `pressure`, and `pressure_trend_3h` each move from 0.00%
in `-09-22a` to **100.00%** population, D=5, M=1, 5 market-days. P1 is therefore
valid.

With the unchanged predeclared severity rule, full free-source parity reduces
all-severe squared error from `737.065190` to `687.390626`: **6.7395%**, crossed
date x market 95% interval **[0.5208%, 14.3964%]**, D=5, M=12, 55 market-days.
That is only **+0.1629 percentage points** beyond `-09-22a`'s partial-parity
`6.5767%`. The added ECCC fields reduce severe SSE by another `1.200360`, all
in the excluded lane; the qualified lane is numerically unchanged.

This is not activation or retraining evidence. The pooled daily-first
control-minus-full-parity Brier point is `-0.000721`, crossed 95% interval
`[-0.032916, +0.030983]`, D=5, M=12, 60 market-days. The point is a slight
degradation and the interval crosses zero. Toronto's direct moisture/pressure
fields are only 254 of 2,855 fleet snapshots (8.90%), D=5, M=1. A five-day
serving replay does not provide a cutoff-valid fleet training history.

Implementation commit: `3e1f29dc` (`feat: add dark free-source feature
parity`), unchanged from dependency tip `538b5acb`. Required current
`origin/master` tip `f3aeec45c0822b500c433e62134b98f02f5ae9fd` was merged by
commit `ff759f39` on branch
`codex/workstation-measure-full-free-source-parity-2026-09-26a`.

## Scope, reservation, and provenance

- I read `DELEGATION_CONTRACT.md`, `ESTABLISHED_FINDINGS.md`, and
  `RETRACTED_AND_FALSE_LEADS.md` first and accepted their findings without
  re-deriving them.
- The branch starts from `-09-22a` tip `538b5acb2c49090506a4faecad21fc383df514a1`
  and preserves a merge of current `origin/master` at `f3aeec45`.
- `docs/operations/reserved-confirmation-window.md` was checked by the harness
  before both P0 and P1. It said **NONE ARE CURRENTLY RESERVED**. Only the
  frozen July 22-26 corpus and hours 09:00-14:00 were read.
- Frozen manifest SHA256:
  `8cf0d01d222172dadd024b3e55a69494860477785ec100cbe8ae2ed546c1662d`.
- Frozen replay-row SHA256:
  `55fd5104d7aa8240a9714d368ab15dd9bda34d87c4da27d7025b6cdb7c8e9ccd`.
- Frozen floor-trace SHA256:
  `2e9da6e324130494760cd6b2dbe632658f6b29b99615439bab66fa1141519c9b`.
- P0 receipt SHA256:
  `6076717505279db30804a4d9f031784120fa64cd76699747e511f91672ae72d1`.
  It was created at `2026-08-06T15:45:07Z`.
- P1 receipt SHA256:
  `7fa49091c2956f1736080d3311b53191bf8eaec65dcfbb9bf646663739f2bdd7`.
  It was created at `2026-08-06T15:51:15Z`.

The two replay receipts are ignored workstation evidence. They were not copied
to production, committed as sidecars, or treated as live-state evidence.

## P0 - corrected hash verification and population gate

The `-09-22a` evaluator was reused. Its only semantic correction was replacing
`promotion_corpus._hash_json` with the observation CAS writer's exact
`SnapshotStore.canonical_raw_payload_digest` verifier. The evaluator gated on
each selected receipt's declared `payload_hash_algorithm` before comparing its
digest.

All **3,122** selected fresh observation receipts declare
`sha256-canonical-json`. The corrected verifier hydrated 2,868 METAR and 254
ECCC snapshot sources, rejected none, and bound 941 unique payload hashes.
Their sorted hash-set receipt is
`b5a41024a6b0de486dd1f05acdf65a5a0be17461058d0ff50ae4dad738c4f0cc`.
These are integrity counts, not effect estimates, so interval treatment does
not apply.

Toronto's P0 table is decisive:

| Feature | Full population | `-09-22a` population | Full support |
| --- | ---: | ---: | --- |
| `rise_from_7am` | 254 / 254 (100.00%) | not separately reported | D=5, M=1, 5 market-days |
| `warming_rate_2h` | 254 / 254 (100.00%) | not separately reported | D=5, M=1, 5 market-days |
| `hours_at_peak` | 254 / 254 (100.00%) | not separately reported | D=5, M=1, 5 market-days |
| `dewpoint_c` | 254 / 254 (100.00%) | not separately reported | D=5, M=1, 5 market-days |
| `humidity` | **254 / 254 (100.00%)** | **0 / 254 (0.00%)** | D=5, M=1, 5 market-days |
| `pressure` | **254 / 254 (100.00%)** | **0 / 254 (0.00%)** | D=5, M=1, 5 market-days |
| `pressure_trend_3h` | **254 / 254 (100.00%)** | **0 / 254 (0.00%)** | D=5, M=1, 5 market-days |
| `wind_speed_kmh` | 254 / 254 (100.00%) | not separately reported | D=5, M=1, 5 market-days |
| `wind_group` | 254 / 254 (100.00%) | not separately reported | D=5, M=1, 5 market-days |
| `cloud_group` | 254 / 254 (100.00%) | not separately reported | D=5, M=1, 5 market-days |

The P0 hard gate is **PASS**. No P1 effect metric was computed before this
receipt existed and passed.

## P1 - full free-source parity

### Positive controls and flag-off guarantee

- All 2,868 captured snapshots replayed with maximum absolute incumbent band
  probability error exactly `0.0`, D=5, M=12.
- The unchanged frozen eligible population is 2,855 snapshots, D=5, M=12.
  Its predeclared severe set remains 1,545 band rows with control SSE
  `737.0651897515824`.
- With the flag off, all 2,868 captured feature records retain aggregate SHA256
  `dc184d83164aa2c754820009cae1c52f895acb104bf97fba1455c475905a2bb8`,
  exactly the `-09-22a` receipt. The default-off guarantee is unchanged.
- The severity rule remains exactly: positive model-minus-market squared-error
  excess and absolute model-minus-market probability difference at least
  `0.30` in the frozen blind-control arm. It was not tuned.

### Population of all ten dead features

| Feature | Full parity | `-09-22a` partial parity | Full support |
| --- | ---: | ---: | --- |
| `rise_from_7am` | 2,841 / 2,855 (99.51%) | 2,839 / 2,855 (99.44%) | D=5, M=12, 60 market-days |
| `warming_rate_2h` | 2,837 / 2,855 (99.37%) | 2,829 / 2,855 (99.09%) | D=5, M=12, 60 market-days |
| `hours_at_peak` | 2,845 / 2,855 (99.65%) | 2,843 / 2,855 (99.58%) | D=5, M=12, 60 market-days |
| `dewpoint_c` | 2,845 / 2,855 (99.65%) | 2,843 / 2,855 (99.58%) | D=5, M=12, 60 market-days |
| `humidity` | **254 / 2,855 (8.90%)** | **0 / 2,855 (0.00%)** | D=5, M=1, 5 market-days |
| `pressure` | **254 / 2,855 (8.90%)** | **0 / 2,855 (0.00%)** | D=5, M=1, 5 market-days |
| `pressure_trend_3h` | **254 / 2,855 (8.90%)** | **0 / 2,855 (0.00%)** | D=5, M=1, 5 market-days |
| `wind_speed_kmh` | 2,845 / 2,855 (99.65%) | 2,843 / 2,855 (99.58%) | D=5, M=12, 60 market-days |
| `wind_group` | 2,845 / 2,855 (99.65%) | 2,843 / 2,855 (99.58%) | D=5, M=12, 60 market-days |
| `cloud_group` | 2,845 / 2,855 (99.65%) | 2,843 / 2,855 (99.58%) | D=5, M=12, 60 market-days |

The direct moisture/pressure block is empirically repaired for Toronto only.
Calling it fleet-populated would be false.

### Severe-tail SSE

All intervals use the same 2,000-replicate crossed date x market pigeonhole
ratio bootstrap and fixed seeds as `-09-22a`.

| Lane | Full control -> parity SSE | Full reduction (95% interval) | Full support | `-09-22a` reduction | ECCC increment |
| --- | ---: | ---: | --- | ---: | ---: |
| All severe | 737.065190 -> 687.390626 | **6.7395%** [0.5208%, 14.3964%] | D=5, M=12, 55 market-days, 1,041 snapshots, 1,545 bands | 6.5767% [0.4898%, 14.1445%] | +0.1629 pp; 1.200360 SSE |
| Excluded | 434.348864 -> 399.133449 | **8.1076%** [-0.7070%, 17.4711%] | D=5, M=12, 50 market-days, 678 snapshots, 919 bands | 7.8313% [-1.0164%, 17.0440%] | +0.2764 pp; 1.200360 SSE |
| Qualified | 302.716326 -> 288.257176 | **4.7765%** [-17.3569%, 12.4958%] | D=5, M=7, 17 market-days, 363 snapshots, 626 bands | 4.7765% [-17.3569%, 12.4958%] | exactly unchanged |

The all-severe interval excludes zero. The excluded and qualified lane
intervals cross zero.

### Pooled Brier and centre guardrails

Positive control-minus-parity Brier means parity is better. Positive centre
delta means parity moves the band centre warmer than the blind control.

| Metric | Full point (95% interval) | Full support | `-09-22a` point (95% interval) |
| --- | ---: | --- | ---: |
| Pooled daily-first control-minus-parity Brier | `-0.000721` [-0.032916, +0.030983] | D=5, M=12, 60 market-days | `-0.003802` [-0.037219, +0.025389] |
| Excluded parity-minus-control centre delta | `+0.015115` [-0.036062, +0.064457] bands | D=5, M=12, 56 market-days | `+0.019592` [-0.025282, +0.066920] bands |

Both guardrail intervals cross zero. The Brier point is less negative than the
partial result but remains on the degradation side. The centre point has the
expected warm sign, but the replay still does not establish blindness as the
centre mechanism.

### Per-hour heterogeneity

Every row uses D=5 and M=12. The interval is the full-parity crossed interval;
`delta` is full minus `-09-22a` in control-minus-parity Brier.

| Hour | Full point | `-09-22a` point | Delta | Full 95% interval | Market-days |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 09 | -0.012238 | -0.007161 | -0.005078 | [-0.070908, +0.044573] | 60 |
| 10 | +0.006037 | +0.003803 | +0.002233 | [-0.043282, +0.063756] | 60 |
| 11 | +0.020933 | +0.009059 | +0.011874 | [-0.062273, +0.097526] | 60 |
| 12 | +0.005677 | +0.000604 | +0.005073 | [-0.055246, +0.064581] | 60 |
| 13 | -0.021326 | -0.021656 | +0.000330 | [-0.138188, +0.082275] | 59 |
| 14 | -0.011986 | -0.014068 | +0.002082 | [-0.092443, +0.060297] | 59 |

Every hourly interval crosses zero.

### Per-market heterogeneity

Each row uses D=5, M=1, and 5 market-days. The interval is the full-parity
date-bootstrap interval; `delta` is full minus `-09-22a`.

| Market | Full point | `-09-22a` point | Delta | Full 95% interval |
| --- | ---: | ---: | ---: | ---: |
| Atlanta | +0.026481 | +0.026481 | 0.000000 | [-0.017025, +0.078508] |
| Austin | +0.073180 | +0.073180 | 0.000000 | [+0.016935, +0.137391] |
| Chicago | -0.018786 | -0.018786 | 0.000000 | [-0.066580, +0.021846] |
| Dallas | +0.042886 | +0.042886 | 0.000000 | [+0.000357, +0.089648] |
| Denver | +0.003949 | +0.003949 | 0.000000 | [-0.033738, +0.043929] |
| Houston | -0.011503 | -0.011503 | 0.000000 | [-0.046972, +0.026242] |
| Los Angeles | +0.043240 | +0.043240 | 0.000000 | [+0.002371, +0.070600] |
| Miami | +0.002206 | +0.002206 | 0.000000 | [-0.017038, +0.023241] |
| NYC | -0.014469 | -0.014469 | 0.000000 | [-0.071419, +0.042481] |
| San Francisco | -0.033042 | -0.033042 | 0.000000 | [-0.067375, -0.005872] |
| Seattle | -0.055509 | -0.055509 | 0.000000 | [-0.175241, +0.027668] |
| Toronto | **-0.067288** | **-0.104259** | **+0.036970** | [-0.211174, +0.106930] |

Only Toronto changes, which isolates the ECCC contribution. Its full-parity
Brier point remains negative and uncertain even though it is materially less
negative than METAR-only. Austin, Dallas, and Los Angeles have positive
date-bootstrap intervals; San Francisco has a negative interval. These
single-market intervals have only five date clusters and are descriptive, not
a fleet activation argument.

## P2 - evidence required before a fleet retrain

A fleet retrain on these fields would require, at minimum:

1. A cutoff-valid, provider-bound historical feature corpus covering the fit
   window and every intended market, using the same source choice, units,
   station identity, timing, and missingness semantics as serving.
2. Empirical population and drift receipts by market, hour, and season. Direct
   humidity and station pressure need an admitted free source for the U.S.
   markets or must remain explicitly missing there; METAR altimeter/SLP and
   derived RH cannot silently substitute for the training fields.
3. Train/serve parity receipts for all repaired fields, including provenance
   and release binding, before any fit.
4. A separately authorized prelocked fit and daily-first evaluation with
   crossed date x market intervals, per-market heterogeneity, severe-tail and
   pooled Brier guardrails, plus the existing promotion gates.

This mission supplies none of the required training history and was forbidden
to fit. It supplies a trustworthy five-day serving replay showing a modest,
positive severe-tail contribution and an inconclusive pooled guardrail. The
correct P2 decision is **NO-GO for fleet retraining from this evidence alone**.

## Falsification audit

1. **ECCC still does not hydrate:** not falsified. P0 is PASS; 254 of 254
   eligible Toronto snapshots populate all three required fields.
2. **Full parity is no better than METAR-only:** not falsified on the
   predeclared severe-tail point. Full is 6.7395% versus 6.5767%, a +0.1629 pp
   increment. The increment was not given its own predeclared difference
   interval, so it is not claimed to be distinguishable.
3. **The all-severe interval crosses zero:** not falsified. Its lower bound is
   +0.5208% at D=5, M=12. The excluded and qualified lane intervals do cross
   zero and are reported as uncertain.
4. **Repair moves the centre the wrong way:** not falsified. The point is
   +0.015115 bands, the expected warm sign, but its interval crosses zero. The
   prior conclusion that blindness is not an established centre mechanism
   survives.
5. **Populating the fields degrades pooled Brier distinguishably:** not
   falsified. The point is mildly negative (`-0.000721`), but the interval
   `[-0.032916, +0.030983]` crosses zero. This uncertainty is still sufficient
   to refuse activation.

The valuable limiting result is localization: the three newly measurable
fields exist only in Toronto, improve severe SSE only slightly beyond partial
parity, and do not establish a pooled Brier gain.

## Roll-closure verdict

Retained runtime identities, not source globs, produce this verdict. The
snapshot receipt was captured `2026-08-06T05:00:19Z` at `64273c2ed4a9` with 77
loaded files; the observation-trigger receipt was captured
`2026-08-06T08:29:44Z` at `64273c2ed4a9` with 85. CLOB was captured
`2026-08-06T05:00:12Z` with 23 files; CLOB enrichment was captured
`2026-07-27T13:51:33Z` with 21.

| Changed file | Retained closure evidence | Roll verdict |
| --- | --- | --- |
| `src/weather/model/model_features.py` | Present in snapshot and observation-trigger; absent from CLOB and CLOB-enrichment. | **Roll-sensitive:** snapshot and observation-trigger. |
| `src/weather/model/free_source_feature_parity.py` | New direct import of `model_features.py`; enters the same two closures on next import. | **Roll-sensitive:** snapshot and observation-trigger. |
| `README.md` | Documentation only. | Roll-free. |
| `tests/model/test_free_source_feature_parity.py` | Test only. | Roll-free. |
| `docs/roadmap/agent-report-2026-08-06-workstation-build-free-source-parity-dark.md` | Dependency report only. | Roll-free. |
| This report | Documentation only. | Roll-free. |

Any future integration of the two model files must use the 01:00-04:00 quiet
window and prove both affected captures recovered. This mission does not merge.

## Explicitly not done

- The research flag remains off by default and was not enabled in production.
  Its on state existed only inside the isolated captured-input replay process.
- No model, candidate, calibration, or retrain was fitted.
- No artifact or release was created, changed, promoted, or activated.
- No severity rule, floor, distribution width, or gate was changed.
- No paid provider, credential, WU re-enable, or new network fetch was used.
- No production data, mirror, `D:\weather-mirror`, or credential file was read
  or written. In particular, `C:\Users\micha\.weathersync.cred` was not read.
- No collector, loop, scheduled task, registration, restart, or production
  state was mutated.
- None of the concurrent-owner files was edited.
- No PR, integration merge, force-push, or branch deletion was performed. The
  only merge is the handoff-required merge of `origin/master` into this topic
  branch.

## Verification and reproduction

Workstation checks executed:

```powershell
# P0: PASS, 254/254 for all three required Toronto fields
# receipt SHA256 6076717505279db30804a4d9f031784120fa64cd76699747e511f91672ae72d1

# P1: PASS, frozen positive controls reproduce
# receipt SHA256 7fa49091c2956f1736080d3311b53191bf8eaec65dcfbb9bf646663739f2bdd7

$env:PYTHONPATH='C:\Users\Michael\Documents\github\weather\scratch\w\measure-full-free-source-parity-09-26a\src'
& 'C:\Users\Michael\Documents\github\weather\scratch\runs\release-consolidation-2026-08-01b\runtime311\Scripts\python.exe' -m pytest -q tests\model\test_free_source_feature_parity.py tests\model\test_feature_skew.py tests\model\test_feature_store.py
# 53 passed, 686 subtests passed

& 'C:\Users\Michael\Documents\github\weather\scratch\runs\release-consolidation-2026-08-01b\runtime311\Scripts\python.exe' -m pytest -q tests\operations\test_import_architecture.py::test_project_critical_files_are_tracked_or_ignored tests\model\test_free_source_feature_parity.py
# 9 passed, 20 subtests passed

& 'C:\Users\Michael\Documents\github\weather\scratch\runs\release-consolidation-2026-08-01b\runtime311\Scripts\python.exe' -m compileall -q app src tests
# PASS

git diff --check origin/master...HEAD
# PASS
```

The canonical agent-docs audit remains blocked by one unrelated broken link
already reported on `-09-22a`:

```text
docs/roadmap/agent-report-2026-08-02-workstation-spec-contract-repair.md:
../../src/weather/reporting/validation/floor_retrain_gate_harness.py#L1079
```

Production verification must remain read-only. These paths exist on the
production host and do not prescribe the workstation-only frozen replay:

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
git fetch origin codex/workstation-measure-full-free-source-parity-2026-09-26a
git merge-base --is-ancestor 538b5acb origin/codex/workstation-measure-full-free-source-parity-2026-09-26a
git merge-base --is-ancestor f3aeec45 origin/codex/workstation-measure-full-free-source-parity-2026-09-26a
git show --stat --oneline origin/codex/workstation-measure-full-free-source-parity-2026-09-26a
git diff --check f3aeec45...origin/codex/workstation-measure-full-free-source-parity-2026-09-26a
git diff --name-only f3aeec45...origin/codex/workstation-measure-full-free-source-parity-2026-09-26a
.\venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q tests/model/test_free_source_feature_parity.py
```

The frozen replay is workstation-owned evidence and intentionally is not
prescribed on production: its pinned corpus and ignored scratch receipts were
not written into production or committed as a sidecar.
