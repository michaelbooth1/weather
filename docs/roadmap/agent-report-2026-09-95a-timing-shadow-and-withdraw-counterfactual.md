# 95a — timing shadow and withdraw counterfactual

**DESCRIPTIVE SHADOW DELIVERED; NO LIVE POLICY ADOPTION. METAR ±2 minutes has the best
large-move lift per equal pulled-time budget in this panel, but its advantage is concentrated
on T+0. It loses to the strongest fixed-clock comparator on T+1 and T+2.** Public prints
are not our fills. This answers Q-07's implementation request and supplies descriptive timing
evidence for Q-02/Q-06; own-fill avoidance and reward economics remain unidentified.

Historical mission evidence, measured 2026-09-24. Answers the
[95a handoff](workstation-handoff-2026-09-95a-timing-shadow-and-withdraw-counterfactual.md).
Branch: `codex/timing-shadow-20260924`. Implementation commit:
**`c59e5240a01ca5b91b6006a4691f28594648ef84`**; this report-only completion commit follows it.

## Population and policy table

The offline 94a rebuild validates **838,712 public trade rows**, 5,280 bands and **480 event-days**:
12 market/station clusters × 40 target-date clusters, 2026-08-15 through 2026-09-23. The 4,410
rows outside T+0..T+2 are excluded by the reused 94a loader. There are **19,388,829 band-minutes**,
14,366,822.05 public paid notional, **436,331 eligible condition-second move anchors** and
**128,594 large-move anchors**. Counts and ratios only: no confidence interval, independent-row
standard error, confirmatory claim or significance test. Any later interval must cross date × market.

Each W window is half-open `[-W,+W)` around its clock/object time. T3 thresholds are levels:
withdraw on every minute at or above the threshold, with no sticky latch. Main T3 uses a five-minute
assumed observation delay; lag 0/15 are sensitivity cases. Unknown T3 does not activate that trigger.
The combined policy is METAR 5 OR all-model 5 OR T3 ≥ .95.

| Policy | Band time pulled % | Public notional in window % | Large moves in window % | Best equal-cost clock % | Move lift vs best clock |
| --- | ---: | ---: | ---: | ---: | ---: |
| METAR 2 | 6.676 | 8.328 | 9.653 | 8.169 | 1.182 |
| METAR 5 | 16.705 | 21.933 | 22.461 | 19.234 | 1.168 |
| METAR 10 | 33.404 | 39.677 | 39.125 | 38.793 | 1.009 |
| NBM 5 | 2.776 | 4.044 | 3.526 | 3.331 | 1.058 |
| NBM 15 | 8.239 | 9.516 | 8.909 | 9.839 | 0.906 |
| GFS 5 | 2.861 | 2.379 | 2.782 | 3.531 | 0.788 |
| GFS 15 | 8.576 | 6.972 | 7.869 | 11.144 | 0.706 |
| HRRR 5 | 16.677 | 20.155 | 20.245 | 19.392 | 1.044 |
| HRRR 15 | 49.973 | 55.037 | 54.552 | 56.695 | 0.962 |
| All models 5 | 21.099 | 24.626 | 24.944 | 24.612 | 1.013 |
| T3 .95 | 21.742 | 28.463 | 8.245 | 9.161 | 0.900 |
| T3 .99 | 19.077 | 21.813 | 2.791 | 3.435 | 0.813 |
| T3 .95, lag 0 | 21.874 | 35.303 | 9.282 | 10.420 | 0.891 |
| T3 .95, lag 15 | 21.477 | 23.867 | 7.864 | 8.601 | 0.914 |
| Combined 5/.95 | 41.571 | 51.342 | 35.834 | 36.356 | 0.986 |

Exact counts, notional and each comparator are in the generated
[policy CSV](agent-report-2026-09-95a-timing-shadow-policies.csv).
The complete policy × station × day-ahead × local six-hour block table is in the
[strata CSV](agent-report-2026-09-95a-timing-shadow-strata.csv).

METAR 2 pulls **1,294,360 / 19,388,829 minutes** and covers **12,413 / 128,594 large moves**,
versus 10,505 for its strongest fixed clock. That is 1,908 additional anchors, **1.484 percentage
points** of all large moves, at equal exposure time. It covers 1,196,459.33 public notional
(58,719 trade rows); the phase-0 baseline covers *more* notional, 1,440,619.02. Thus the ranking
is specific to large moves, not universally superior removal of public flow. METAR 5 buys more
coverage at 2.50 times the pulled minutes; its equal-cost lift is slightly smaller.

The best policy was selected descriptively from these 15 policies by largest move lift versus
the strongest of four clocks, among policies pulling less than half the time. There is no held-out
policy-selection result. The panel already informed 94a; reuse is explicitly exploratory.

## Best policy by station, horizon and time

These are marginal summaries of the same cells, not independent experiments. Every row compares
against its own strongest phase; that phase can differ across rows. The strata CSV retains counts
and pulled minutes for all policies and joint strata, including notional.

| Station | Large moves covered / total | Coverage % | Best clock % | Lift |
| --- | ---: | ---: | ---: | ---: |
| KATL | 965 / 8,995 | 10.728 | 8.282 | 1.295 |
| KAUS | 876 / 6,932 | 12.637 | 7.804 | 1.619 |
| KORD | 821 / 7,291 | 11.261 | 8.339 | 1.350 |
| KDAL | 991 / 8,557 | 11.581 | 7.900 | 1.466 |
| KBKF | 277 / 5,500 | 5.036 | 8.582 | 0.587 |
| KHOU | 883 / 9,708 | 9.096 | 8.642 | 1.052 |
| KLAX | 1,427 / 16,520 | 8.638 | 7.482 | 1.155 |
| KMIA | 1,259 / 15,518 | 8.113 | 7.475 | 1.085 |
| KLGA | 1,915 / 18,803 | 10.184 | 6.850 | 1.487 |
| KSFO | 769 / 9,460 | 8.129 | 7.600 | 1.070 |
| KSEA | 817 / 9,761 | 8.370 | 6.977 | 1.200 |
| CYYZ | 1,413 / 11,549 | 12.235 | 14.902 | 0.821 |

| Horizon / local block | Band-minutes pulled / total | Large moves covered / total | Coverage % | Best clock % | Lift |
| --- | ---: | ---: | ---: | ---: | ---: |
| T+0 | 506,880 / 7,603,200 | 11,207 / 107,303 | 10.444 | 8.277 | 1.262 |
| T+1 | 499,081 / 7,486,178 | 933 / 15,517 | 6.013 | 7.463 | 0.806 |
| T+2 | 288,399 / 4,299,451 | 273 / 5,774 | 4.728 | 8.053 | 0.587 |
| 00:00–06:00 | 280,478 / 4,196,049 | 1,321 / 22,007 | 6.003 | 7.788 | 0.771 |
| 06:00–12:00 | 322,135 / 4,825,141 | 2,391 / 30,212 | 7.914 | 7.464 | 1.060 |
| 12:00–18:00 | 331,001 / 4,964,109 | 8,224 / 68,735 | 11.965 | 9.451 | 1.266 |
| 18:00–24:00 | 360,746 / 5,403,530 | 477 / 7,640 | 6.243 | 8.861 | 0.705 |

The aggregate result does **not** validate routine-METAR withdrawal for the current T+1/T+2 maker
lane. Denver and Toronto also lose to a clock comparator. Afternoon and T+0 concentration are
plausible timing hypotheses for a prospective shadow protocol, not instructions to change RE-1.

## Measurement and shadow contracts

- The pure `weather.market.timing_shadow` library accepts an aware clock, station, native-unit band,
  caller-supplied running maximum/cutoff and model-object proxies. It emits minutes to/since routine
  METAR, NBM cycle and GFS/HRRR proxies, per-band decidedness, estimator sample size and explicit
  `shadow_only` / `counts_toward_trading_readiness=false`. No runtime consumer was changed to use it.
- `tools.timing_shadow_20260924` reads only owned public-cache copies. It validates 94a URL/hash,
  cursor, event/token identity and outcome mappings before rebuilding the population. The shadow
  export has **190,080 unique rows = 132 configured cached bands × 1,440 T+0 minutes**, Sep 22,
  12 stations. Every exported risk was asserted equal to the pure-library calculation.
- 89b's remaining-rise estimator is refit strictly before **2026-08-13**, preceding even T+2
  exposure in the evaluation panel. Training has **65–73 complete days per station**, with minimum
  quarter-hour N in that range. All 12 pre-cutoff modal METAR minutes reproduce 89b. Training
  empirical decidedness Brier beats the station's constant training base rate; this is an
  in-sample plumbing positive control, not new calibration evidence. Full values and conflict
  counts are in the [training record](agent-report-2026-09-95a-timing-shadow-training.json).
- T3 uses the preceding quarter's empirical remaining whole-degree rise. It estimates staying on
  the current side of the nearest band boundary. An already-exceeded upper bound or reached open
  upper tail is locked under a monotone recorded maximum; other risks require at least 20 days.
  Below a finite band, it conservatively excludes paths crossing both boundaries. It is not a
  direct final-settlement probability. Negative/zero bounds and native C/F units use 95b's parser.
- Only target-day observations no later than `now - lag` enter the running maximum. A latest report
  older than 90 minutes, ambiguous revision day, missing history or future target yields unknown.
  T3 is known for **7,087,601 / 19,388,829 = 36.555%** of minutes; 63.445% is unknown. Sep 23 has
  no 89b history. The hourly-rule archive filter is a research proxy, including unverified KBKF
  mapping; neither WU nor the venue's exact final truth is established by these risk values.
- A five-minute assumed delay is **not captured receipt time**. Historical archives can revise.
  NBM 01/07/13/19Z are cycle anchors, not publication times. The **1,190** GFS/HRRR cached object
  LastModified proxies are not first-seen arrivals; pulling before those observed future times
  is hindsight and cannot be used as an implementable predictive trigger without a new protocol.
- YES prices and `1 - NO price` form a share-weighted YES-equivalent price per condition-second.
  A large move is an absolute excursion ≥ .03 to any strictly later print within 300 seconds.
  Same-second prints are aggregated, not sequenced. An anchor needs a future print and a full
  five-minute window inside the retained band interval; it belongs to its **start minute**.
  Overlapping anchors remain overlapping. Print bounce, irregular trading and complementary
  outcome mixing can create moves with no corresponding executable mid-price opportunity.
- Public notional is raw asset price × size, summed once per retained public trade. Exposure is
  any-overlap calendar band-minutes from creation/T+2 cutoff through local target-day end. It
  includes intervals without prints and does not establish open books, reward eligibility or
  actual quoting time. Pulled time is a **reward-cost proxy**, not measured rewards forfeited.
- Fixed clocks start at phases 0, 15, 30 or 45 each hour, ranking eligible minutes cyclically.
  Each matches the policy's exact pulled-minute count **within each band/date/hour**, including
  partial creation hours. This controls band and hour composition, using no print outcomes.
  The matched hour budget is retrospective, not an independently deployable fixed-duration rule.
  All four baseline costs equal policy costs at every saved cell, stratum and aggregate.

## Rebuild, evidence and verification

The [manifest](agent-report-2026-09-95a-timing-shadow-manifest.json) binds source-code hashes,
counts and all output SHA-256 values for this Windows run. Tracked policy/strata CSVs normalize
CRLF to Git's LF without changing values; the tracked CSV hashes therefore differ from the raw
runtime hashes in the manifest. The training JSON is a byte copy. Ignored `data/timing_shadow_95a` holds the raw cache inventory,
date × market cells and full gzip shadow output; these are local evidence, not clean-checkout files.
The shadow gzip SHA-256 is `409148ad7f9c74c7b10d0f43d170a187de9c6d47628f6b19d96b03913e4fa7ef`.
The inventory hash is `f7233582f8b00a9f5a38ec2bcf71e232efcb77df0271636f320cf331ac91f9f0`.

In an attended workstation checkout of this branch, use its exact installed project interpreter:

```powershell
$missionRoot = (Resolve-Path .).Path
$missionGit = (& git rev-parse --path-format=absolute --git-common-dir).Trim()
$missionPython = (Resolve-Path (Join-Path (Split-Path $missionGit -Parent) 'venv/Scripts/python.exe')).Path
$missionArgs = '["-m","tools.timing_shadow_20260924","analyze"]'
$missionEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($missionArgs))
& .\scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -PythonPath $missionPython -ArgumentsBase64 $missionEncoded -RepoRoot $missionRoot
```

The analyzed root must first contain the validated public caches. On a clean checkout, transfer
the retained 89b public research cache into `data/observation_clock_89b/cache` (verify its hashes
against the retained inventory). The old 89b collector has an expired network deadline and is not
an admitted 95a entrypoint; this report does not authorize restarting it. Populate the default
94a cache using the same wrapper, then prepare and analyze with these argument arrays, sequentially:

```json
["-m","tools.cross_band_fill_clustering_20260924","collect"]
["-m","tools.cross_band_fill_clustering_20260924","publications"]
["-m","tools.timing_shadow_20260924","prepare","--trade-cache","data/fill_clustering_94a","--observation-cache","data/observation_clock_89b"]
["-m","tools.timing_shadow_20260924","analyze","--shadow-date","2026-09-22"]
```

Only the first two commands fetch public inputs. A fresh fetch may reflect upstream revisions;
exact historical reproduction requires the hash-bound research caches, transferred as evidence.
`prepare` is create-only and refuses an existing destination; do not rerun it over retained evidence.
`--root` selects a separate owned output directory for prepare/analyze. No production execution
is implied: the capture host must use its own admitted, bounded workload policy.

Verification: **98 passed, 11 skipped**, including 96 focused library/admission/architecture tests
and two temporary evidence/docs adapters. The skips are existing nested-mutex cases under the
outer lease. Artifact checks verified every manifest hash, exact costs in all cells/strata,
aggregate reconciliation, population counts and all 190,080 unique shadow rows. Canonical docs
audit and generated backlog check passed. The earlier focused run had 96 passed/11 skipped;
these overlapping runs are not an aggregate test count. No full local suite is claimed.
`compileall -q src/weather tests tools/timing_shadow_20260924.py` passed using Kind `compileall`.
The initial invocation used the wrong Kind `weather_heavy` and was correctly refused before a
child launched; correcting the Kind required no control changes. Diff whitespace checks passed.

For repeatable focused tests, use Kind `pytest` with the wrapper and:

```json
["-m","pytest","tests/market/test_timing_shadow.py","tests/market/test_observation_clock.py","tests/operations/test_missing_information_admission.py","tests/operations/test_workload_admission_script.py","tests/operations/test_import_architecture.py","-q","--basetemp=C:/tmp/p95a-review"]
```

Remove only that owned test directory after resolving its exact path and checking for reparse points.

## Source lineage and integration disposition

The user explicitly selected fetched handoff base **`69c5a325342b99fa03655883436e169159b7756d`**,
overriding the handoff's master default. Explicit dependency merges preserve:

| Dependency | Exact tip | Reason |
| --- | --- | --- |
| `codex/observation-clock-20260923` | `d059cc78753757cec6cc1a6ba34cbe03a28f508c` | 89b pure estimator and cache loader |
| `codex/fill-clustering-20260924` | `b0a5d9a5f45444e2d9eb8a23ad033ec5a4be6940` | 94a validated public population and object proxies |
| `codex/signed-band-parser-20260924` | `2c40077a21f0b779f23666137be7a8d5d580b142` | Canonical native signed-band parsing |

The 95a-only diff starts at dependency merge **`88ac81a4c05f224f0f923e1849e4a7c3f55ffd7e`**.
95c is independent and is not merged here. Review/adopt dependencies before the 95a delta;
the full branch includes 95b runtime changes, so the handoff's “no roll” expectation cannot be
treated as a verdict on the full stacked branch. No live-host facts were inferred from a mirror.

`scripts/ops/roll_verdict.ps1 -Branch codex/timing-shadow-20260924 -Base origin/master` returned
exit 1, **UNDECIDABLE: no live closure evidence**: snapshot, CLOB, observation-trigger and
enrichment status files are all absent in this isolated worktree. There are no retained live
closures from which to derive a more specific per-file verdict. Production must re-run the tool
against its actual closures before integration, including the dependency and handoff-base deltas.

| 95a-owned file | Source role | Actual closure verdict here |
| --- | --- | --- |
| `src/weather/market/timing_shadow.py` | New pure shadow library, no serving consumer added | UNDECIDABLE |
| `tools/timing_shadow_20260924.py` | Offline research entrypoint | UNDECIDABLE |
| `tests/market/test_timing_shadow.py` | Deterministic fixtures | UNDECIDABLE |
| `.codex/hooks/pre_tool_use_host_load.py` | Exact module admission only | UNDECIDABLE |
| `scripts/ops/workload_admission.ps1` | Exact module admission only | UNDECIDABLE |
| `tests/operations/test_missing_information_admission.py` | Matching admission regression | UNDECIDABLE |
| `tests/operations/test_workload_admission_script.py` | Matching wrapper regression | UNDECIDABLE |
| This report and its four adjacent CSV/JSON artifacts | Research evidence | UNDECIDABLE |

The owner explicitly approved the four admission-file scope additions for exactly
`tools.timing_shadow_20260924`; host, attendance, lease and child-tree controls remain intact.
All heavy work held the workstation lease; no RE-1 session was running. **No registration,
production write, restart, master merge, serving change, order, credential/.env read, RE-1
worktree access or mirror write occurred.** Acceptance and canonical question/findings updates
belong to the production owner, outside this mission's assigned files.

Final handback verification: the committed implementation's roll tool again returned the same
UNDECIDABLE result. Post-report canonical docs/backlog checks passed (one additional temporary
adapter test); compileall and staged whitespace checks passed. The three owned short pytest
directories were removed after exact absolute-path and reparse-point checks. Raw public research
caches and measured output remain intact. The final branch tip is the report-only commit following
the implementation hash above; its push is verified against the exact remote branch ref.
