# Mission 94a — public cross-band trade clustering

**PARTIAL IDENTIFICATION: public flow can measure clustering; it cannot identify historical touch,
our hypothetical fills at +/-1.5 cents, or a safe cash-overcommit multiplier.** The counterfactual
maker-fill premise is not established by this dataset. The research recommendation is **0% cash
overcommit** pending identified own-fill/queue evidence. This is descriptive research, not live authority.

Observed maxima were **11 bands in one event, 22 in one city, and 88 across cities within a minute**;
the global five-minute maximum was **138**. Given a band-second trade anchor, another band in
the same event traded within the next minute on **52.22%** of eligible anchors. These are public-flow
facts, not hypothetical fills of our quotes.

Answers [handoff 94a](workstation-handoff-2026-09-94a-cross-band-fill-clustering.md), serving Q-06,
Q-12 and Q-13. Read the [findings digest](../operations/FINDINGS_DIGEST.md) and EF sections 8c,
10m and 10n for the distinction between public trades, own fills and reserve enforcement.

## Scope and evidence

Branch: `codex/fill-clustering-20260924`. Implementation commit: `1e61cf60f4453f1402b060d5c1997d6131da34d0`.
Fetched base: `683e8f3afc1bbc6508494e7d23f57ea3dac5cb66` on
`origin/codex/reward-test-attended-handoff-20260921`. The owner's explicit starting-ref instruction
overrides the handoff's `origin/master` default; this is a declared stacked dependency, not an
assertion that the inherited branch is production-adopted. Mission 94b was pushed separately first.

Owner scope addition: the exact module `tools.cross_band_fill_clustering_20260924` in the workstation
and hook allowlists, with their two matching tests. No wildcard or host/principal/attendance/lease
exception was added. The owner confirmed no RE-1 session was running; collection and all Python
verification use the existing workstation wrapper and complete-child-tree cleanup.

All **480/480 event feeds** reached cursor exhaustion (1,088 trade pages). They contain
**843,122 public rows**, of which **838,712** are T+0/T+1/T+2; **4,410** are outside that range.
There were **zero exact repeated rows** under the declared public-row identity. Retained support:
**40 target-date clusters x 12 city/market clusters = 480 event-days**, **5,280 band conditions**
and **681,458 distinct band-second anchors**. Every requested event and band has retained trades.
The retained UTC span is 2026-08-14 00:56:21 through 2026-09-24 06:59:53.
All **170 GFS + 1,020 HRRR** representative publication objects were present; the final
publication day is bounded to cycles before 12Z on September 24 to bracket the last eligible trades.

The fixed requested population is every configured city and local target date 2026-08-15 through
2026-09-23. Day-ahead is recomputed in that city's timezone at each trade, retaining only 0, 1 or 2.
These dates were not reserved when the mission ran. No confidence intervals, significance tests or
independent-minute sample-size claims are made; any later interval must use crossed date x market
clustering, with the 12 cities as market clusters. Event/band conditions are additional support counts,
not thousands of independent market clusters.

Collection uses public Gamma event discovery and the cursor-paginated Data API v2 taker-only feed.
The API's event shape ignores time bounds, so filtering is local; taker-only avoids the additional
maker-side rows. The default 0.01 minimum trade filter and public-feed retention/availability limit
coverage. Cursor exhaustion means the API returned its complete available history, not that an
independent chain reconciliation proved every execution. Sources:
[trade-feed contract](https://docs.polymarket.com/api-reference/feeds/list-trades),
[v2 migration](https://docs.polymarket.com/migrate/data-api-v1-to-v2).

Raw replies and metadata are cached under ignored `data/fill_clustering_94a/http/`; event manifests
retain page references. Rebuild verifies URL identity, hashes, cursor lineage, event/condition/token
binding, row counts and Gamma metadata. Failed or missing event histories are explicit coverage
failures, never zero-activity observations. Empty retained histories are excluded from exposure.
Exact repeated public rows are collapsed; the API lacks a unique execution ID, so indistinguishable
legitimate fragments may collapse too. Hazards and clocks use unique condition-second anchors.

## Measurements

### Co-occurrence (all trades, no touch identification)

| scope | window_seconds | windows | k_ge2 | k_ge3 | max_k | percent_ge2 | percent_ge3 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| city | 60 | 711575 | 91358 | 43932 | 22 | 12.8388 | 6.17391 |
| city | 300 | 711527 | 371703 | 247295 | 33 | 52.2402 | 34.7555 |
| event | 60 | 1762180 | 79248 | 37055 | 11 | 4.49716 | 2.10279 |
| event | 300 | 1760260 | 370674 | 201692 | 11 | 21.0579 | 11.4581 |
| global | 60 | 59404 | 51694 | 46716 | 88 | 87.0211 | 78.6412 |
| global | 300 | 59400 | 57662 | 57532 | 138 | 97.0741 | 96.8552 |

### Co-occurrence by local day-ahead

| scope | ahead | window_seconds | windows | k_ge2 | max_k | percent_ge2 |
| --- | --- | --- | --- | --- | --- | --- |
| city | 0 | 60 | 691200 | 56232 | 11 | 8.13542 |
| city | 0 | 300 | 689280 | 237553 | 11 | 34.4639 |
| city | 1 | 60 | 680551 | 18929 | 11 | 2.78142 |
| city | 1 | 300 | 678631 | 106256 | 11 | 15.6574 |
| city | 2 | 60 | 390429 | 4087 | 11 | 1.0468 |
| city | 2 | 300 | 388561 | 24834 | 11 | 6.39127 |
| event | 0 | 60 | 691200 | 56232 | 11 | 8.13542 |
| event | 0 | 300 | 689280 | 237553 | 11 | 34.4639 |
| event | 1 | 60 | 680551 | 18929 | 11 | 2.78142 |
| event | 1 | 300 | 678631 | 106256 | 11 | 15.6574 |
| event | 2 | 60 | 390429 | 4087 | 11 | 1.0468 |
| event | 2 | 300 | 388561 | 24834 | 11 | 6.39127 |
| global | 0 | 60 | 57780 | 40920 | 60 | 70.8204 |
| global | 0 | 300 | 57776 | 52950 | 86 | 91.6471 |
| global | 1 | 60 | 56999 | 26011 | 59 | 45.6341 |
| global | 1 | 300 | 56991 | 53148 | 88 | 93.2568 |
| global | 2 | 60 | 39425 | 7117 | 34 | 18.052 |
| global | 2 | 300 | 39346 | 24530 | 59 | 62.3443 |

### Global book by UTC time of day

Direct `scope=global, ahead=all, hour6!=all` projection of the rebuilt
`cooccurrence_summary.csv`; city/event local-hour detail is in the same file.

| UTC hours | Window seconds | Eligible windows | Windows with >=2 bands | Max k |
| --- | --- | --- | --- | --- |
| 00-06 | 60 | 15064 | 11310 | 54 |
| 06-12 | 60 | 14820 | 12676 | 88 |
| 12-18 | 60 | 14760 | 13784 | 68 |
| 18-24 | 60 | 14760 | 13924 | 69 |
| 00-06 | 300 | 15064 | 14385 | 91 |
| 06-12 | 300 | 14816 | 14281 | 96 |
| 12-18 | 300 | 14760 | 14578 | 129 |
| 18-24 | 300 | 14760 | 14418 | 138 |

### Conditional hazard (strictly later, band-second anchors)

| relation | window_seconds | source_anchors | eligible_pairs | hit_pairs | p_pair | anchors_any_hit | p_any |
| --- | --- | --- | --- | --- | --- | --- | --- |
| same_event_other_band | 60 | 681446 | 6814460 | 937089 | 0.137515 | 355829 | 0.522168 |
| same_city_other_date | 60 | 657165 | 11425062 | 269812 | 0.0236158 | 148210 | 0.225529 |
| other_city | 60 | 681457 | 209457089 | 6405221 | 0.0305801 | 668384 | 0.980816 |
| same_event_other_band | 300 | 681395 | 6813950 | 1629906 | 0.239201 | 526333 | 0.772434 |
| same_city_other_date | 300 | 657160 | 11419111 | 907489 | 0.0794711 | 373764 | 0.568756 |
| other_city | 300 | 681457 | 209321921 | 20844046 | 0.0995789 | 681355 | 0.99985 |
| same_event_other_band | 1800 | 681043 | 6810430 | 2876850 | 0.422418 | 655895 | 0.963074 |
| same_city_other_date | 1800 | 657046 | 11372207 | 2975455 | 0.261643 | 626567 | 0.953612 |
| other_city | 1800 | 681457 | 208485206 | 61678654 | 0.295842 | 681433 | 0.999965 |

### Information clock (anchor counts, no causal baseline)

| clock | anchors | clock_available | before_5m | after_5m | outside_5m |
| --- | --- | --- | --- | --- | --- |
| METAR_routine | 681458 | 681458 | 50026 | 69226 | 562206 |
| NBM_cycle | 681458 | 681458 | 9801 | 13966 | 657691 |
| gfs_object_publication | 681458 | 681458 | 8494 | 9526 | 663438 |
| hrrr_object_publication | 681458 | 681458 | 50548 | 62301 | 568609 |

### Publication clock coverage

| model | expected_objects | observed_objects |
| --- | --- | --- |
| gfs | 170 | 170 |
| hrrr | 1020 | 1020 |

### Clock-aligned clustering; phase refers to window start

| clock | window_seconds | phase | windows | k_ge2 | max_k | percent_ge2 | mean_k |
| --- | --- | --- | --- | --- | --- | --- | --- |
| METAR_routine | 60 | after_5m | 59304 | 9247 | 18 | 15.5925 | 0.718113 |
| METAR_routine | 60 | before_5m | 59300 | 6376 | 19 | 10.7521 | 0.547015 |
| METAR_routine | 60 | outside_5m | 592971 | 75735 | 22 | 12.7721 | 0.633869 |
| METAR_routine | 300 | after_5m | 59285 | 33625 | 22 | 56.7176 | 2.53828 |
| METAR_routine | 300 | before_5m | 59294 | 29134 | 22 | 49.1348 | 2.17062 |
| METAR_routine | 300 | outside_5m | 592948 | 308944 | 33 | 52.1031 | 2.31738 |
| NBM_cycle | 60 | after_5m | 825 | 761 | 69 | 92.2424 | 10.8315 |
| NBM_cycle | 60 | before_5m | 829 | 724 | 65 | 87.3341 | 7.41858 |
| NBM_cycle | 60 | outside_5m | 57750 | 50209 | 88 | 86.942 | 7.54649 |
| NBM_cycle | 300 | after_5m | 825 | 805 | 117 | 97.5758 | 32.6982 |
| NBM_cycle | 300 | before_5m | 825 | 799 | 113 | 96.8485 | 34.0097 |
| NBM_cycle | 300 | outside_5m | 57750 | 56058 | 138 | 97.0701 | 27.6755 |
| gfs_object_publication | 60 | after_5m | 825 | 700 | 35 | 84.8485 | 7.4 |
| gfs_object_publication | 60 | before_5m | 825 | 696 | 39 | 84.3636 | 6.82061 |
| gfs_object_publication | 60 | outside_5m | 57754 | 50298 | 88 | 87.0901 | 7.60404 |
| gfs_object_publication | 300 | after_5m | 825 | 804 | 80 | 97.4545 | 27.3442 |
| gfs_object_publication | 300 | before_5m | 825 | 805 | 76 | 97.5758 | 26.4473 |
| gfs_object_publication | 300 | outside_5m | 57750 | 56053 | 138 | 97.0615 | 27.8601 |
| hrrr_object_publication | 60 | after_5m | 4942 | 4294 | 69 | 86.8879 | 7.85714 |
| hrrr_object_publication | 60 | before_5m | 4941 | 4148 | 40 | 83.9506 | 6.70978 |
| hrrr_object_publication | 60 | outside_5m | 49521 | 43252 | 88 | 87.3407 | 7.65156 |
| hrrr_object_publication | 300 | after_5m | 4939 | 4820 | 138 | 97.5906 | 28.4801 |
| hrrr_object_publication | 300 | before_5m | 4941 | 4810 | 113 | 97.3487 | 25.7434 |
| hrrr_object_publication | 300 | outside_5m | 49520 | 48032 | 129 | 96.9952 | 27.9773 |

### Funding scenario on max observed hit-band count; NOT would-fill notional

| scope | window_seconds | max_k | 20_share_full_pair_funding_scenario | 75_share_full_pair_funding_scenario |
| --- | --- | --- | --- | --- |
| city | 60 | 22 | 426.8 | 1600.5 |
| city | 300 | 33 | 640.2 | 2400.75 |
| event | 60 | 11 | 213.4 | 800.25 |
| event | 300 | 11 | 213.4 | 800.25 |
| global | 60 | 88 | 1707.2 | 6402 |
| global | 300 | 138 | 2677.2 | 10039.5 |

### Adjacent NO direct-sale flow scenarios; NOT maker fill probability

| window_seconds | basket_k | eligible_basket_windows | multiple_NO_sale_windows | rate | resolved_scenarios | max_unit_realized_loss | max_unit_reserve | max_unit_basket_loss | 20_share_max_realized_scenario_loss | 75_share_max_realized_scenario_loss |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 60 | 2 | 17621594 | 3355 | 0.000190391 | 3355 | 0.979 | 1.998 | 0.998 | 19.58 | 73.425 |
| 60 | 3 | 15859421 | 5871 | 0.00037019 | 5871 | 0.979 | 2.997 | 0.998 | 19.58 | 73.425 |
| 300 | 2 | 17602394 | 22427 | 0.00127409 | 22427 | 0.98083 | 1.998 | 0.998 | 19.6166 | 73.5622 |
| 300 | 3 | 15842141 | 44292 | 0.00279583 | 44292 | 0.98083 | 2.997 | 0.998 | 19.6166 | 73.5622 |

### Same-event direction compatibility

| window_seconds | classification | windows |
| --- | --- | --- |
| 60 | mixed_within_band | 22715 |
| 60 | multi_band_windows | 79248 |
| 60 | multiple_crossings | 8451 |
| 60 | one_crossing_mixed_sign | 22440 |
| 60 | same_sign_only | 25642 |
| 300 | mixed_within_band | 156313 |
| 300 | multi_band_windows | 370674 |
| 300 | multiple_crossings | 31705 |
| 300 | one_crossing_mixed_sign | 90274 |
| 300 | same_sign_only | 92382 |

The full deterministic output under `data/fill_clustering_94a/tables/` includes the k distribution,
city/event detail, 6-hour time-of-day strata, local day-ahead strata, daily maxima, pair denominators,
publication coverage, and individual overlapping basket scenarios. `report_tables.md` regenerates
the aggregate panels; the UTC time-of-day panel is the direct CSV projection described above.
SHA-256 digests:

- `tables/cache_inventory.json`: `bdd77a4f4eb3c25ce30db9cff859b93b67fe3ef157949fc616d8708698913a8a`.
- `tables/manifest.json`: `f5b610dedd94d45693e186747673074e6bd4bcb901c64e5f6519f0c57cf3c395`.
- Research source bytes: `d84a5bfb61215cf3495a241063f5893dad4af5f2bd2d3cad880f03b50d8a8bc7`.

Raw cache is local ignored evidence and is not part of the pushed branch; copying that cache
preserves exact reproduction, while a fresh public fetch may reflect later upstream changes.

### Estimands and interpretation

Co-occurrence counts distinct conditions in forward half-open windows starting at each eligible
minute. Zero-trade windows remain in the denominator. Event exposure starts at creation or local
T+2 midnight, whichever is later, and ends after T+0; city/global exposure is the union of eligible
events. Target-band creation constrains pair hazards. Six-hour strata use city-local anchor time
(UTC for global windows). Five-minute windows overlap and may cross a local midnight; the daily
maxima use their start date. The city scope includes concurrent target dates, not only one event.
Exposure is a calendar denominator, not captured open-book availability: early closures and
quote-ineligible extreme prices are not reconstructed. Pair eligibility has the same limitation.

Conditional hazards use strictly later prints in `(t, t+delta]`; same-second order is unknown and
excluded. Each source condition-second / eligible target condition is one pair. The target must
exist and remain T+0/1/2 for the full window. `p_pair` is hits / eligible pairs, and `p_any` is the
fraction of source anchors with at least one eligible target hit in that relation. These are different
estimands: adding target bands can raise the latter without raising pairwise risk. Neither is a
maker fill probability or a causal effect. Coverage and event-creation censoring remain material.

METAR anchors use the station routine-minute table from 89b commit
`d059cc78753757cec6cc1a6ba34cbe03a28f508c`; they are observation-clock proxies, not reception
timestamps or observed surprise magnitudes. NBM 01/07/13/19Z are cycle clocks, not availability.
Following 92a's representative-object method, GFS/HRRR anchors use public AWS `LastModified`
for the cycle's GFS 0.25-degree f000 or HRRR surface f00 object. S3 listings retain that metadata
without downloading GRIB files. They do not time the entire release, forecast horizons, venue
participants' receipt, or station extraction. Publication coverage is reported separately.
An object rewrite can also change LastModified; it is not a proof of first public availability.
Before/after counts describe alignment; no matched no-news baseline or information-shock causality
is claimed. The clustering panel uses city-minute exposure (across target dates) for METAR and
global minute exposure for NBM/GFS/HRRR; its phase labels describe the window start, and rates
across those scopes are not directly comparable. Signs are taker pressure (BUY-YES / SELL-NO positive, SELL-YES / BUY-NO negative),
not measured price changes. Positive/negative signs in ordered same-event bands can be compatible
with one temperature shift, but compatibility is weak evidence. Mixed signs within one band or
multiple crossings are explicitly separate; same-sign-only windows are not credited as a shock.

The unadjusted city one-minute multi-band rate is **15.59% after the routine METAR minute**,
**10.75% before**, and **12.77% outside** the five-minute neighborhoods. GFS/HRRR one-minute
after-publication rates are below their respective outside-window rates. This supports neither
a blanket forecast-publication spike claim nor a causal METAR effect; time of day, event maturity
and overlapping information clocks are not controlled.

### Funding scenarios and basket arithmetic

The largest notional that **would have filled** at +/-1.5 cents is **unidentified** for every scope
and both sizes. We have neither historical BBO/depth and queue position nor our orders, cancellations,
balances and fills. Trade size is not our available size. Inferring those quantities from last trades
would silently substitute a different experiment.

For context only, if both equal-size BUY legs are placed 0.015 below complementary common mids,
their full funding is `S[(m-.015)+(1-m-.015)] = .97 S` per band, when both prices are valid.
The funding table applies that identity to the maximum observed number of hit bands. It assumes
both legs on each such band and does not establish that either would execute. Actual initial
reserve and any applicable costs must be computed from the actual quote vector; this table
does not identify a capital quantile, worst future loss or a safe multiplier.

For Q-12, direct taker SELL-NO prints are an acquisition-flow proxy. For each adjacent 2/3-band
basket and minute window, the scenario assumes equal S shares acquired on every band with a
NO sale, at its earliest observed sale second (highest price if tied), ignoring queue and size. Only windows with at least two
such bands enter the scenario file; the rate denominator includes all eligible basket-minutes.
Partially hit baskets include only their hit-leg costs. Initial reserves on unhit quotes are unknown.

For acquired quantities `q_i` at prices `p_i`, cost is `C=sum(q_i p_i)`; if selected band j wins,
NO payout is `sum(q_i)-q_j`. Thus worst settlement loss over possible winners is
`C-sum(q_i)+max(q_i)`, and it is `C-S(m-1)` for m equal filled legs. If the winner is outside
the selected basket, all selected NO legs pay. Realized scenario losses use Gamma's resolved
binary outcomes only when exactly one event band wins and every band is resolved. They are not
realized account P&L. Overlapping windows cannot be summed into a trading return. Comparing
the formula with filled-leg cost does not finance those fills: settlement offsets arrive later,
and one-leg partial fills can remove the apparent diversification.

Paired example from `basket_flow_scenarios.csv`: Los Angeles target 2026-09-08, event
`975654`, window starting **20:52Z** (`start_minute=29815012`), adjacent ranks 9-10.
The two hit NO legs cost **1.9808298755 per S** and pay **1 per S** at the recorded resolution:
for S=20, **39.62 cost versus 19.62 scenario loss**; for S=75, **148.56 versus 73.56**.
The corresponding three-band row has only two hit legs, not a filled three-leg hedge.
The summary's maxima are separate maxima and must not be divided to infer a reserve-discount ratio.

## Recommended caps and open-question disposition

| Scope | Research recommendation | Evidence / limitation |
| --- | --- | --- |
| Global cash overcommit | **0%; maximum open BUY funding 1.00 x unencumbered available cash** | Public flow cannot identify own-fill tails or future failed-reservation behavior |
| Event | **100% funding of the event's actual outstanding BUY vector**; no reserve discount from terminal basket netting | Basket terminal payoff differs from acquisition cash and partial-fill risk |
| Information cluster | **100% funding of the combined outstanding BUY vector** across its events | Clock alignment does not establish independent fills or a numeric diversification credit |
| Absolute pUSD cap / k bands | **Unidentified here**; retain the separately authorized lane's bound | This mission does not grant a new wallet/session size or infer quote availability |

The event/cluster limits are contained within the global available-cash ceiling, not additional
budgets. Existing positions, unavailable balances, pending settlements and other commitments
reduce that available cash. These are conservative funding constraints, not estimated optimal caps.
Q-06 gains descriptive public co-occurrence/hazard evidence; own-fill clustering remains open.
Q-12 gains explicit conditional basket arithmetic and public-flow scenarios; joint maker-fill
probabilities remain open. Q-13's exchange reservation rule is inherited from EF 10n and was not
re-tested. No observed trade-frequency result authorizes oversubscribing cash. Acceptance and
canonical open-question updates belong to the production owner, outside this mission's file scope.

## Reproduction and verification

- Network-free self-checks: PASS, including brute-force rolling-window counts, strict-future
  hazard boundaries, local-midnight day-ahead normalization, wrong-token rejection, cache-tamper
  rejection, offline network exclusion, publication-time bracketing and enumeration of basket outcomes.
- Full cached population rebuilt successfully: `OFFLINE_TABLES_COMPLETE`.
- The two admission test files, `test_codex_host_load_hook.py`, and a temporary adapter invoking
  the actual canonical documentation commands: **76 passed, 11 skipped**, 23.60 seconds.
  The 11 existing cases skip because the outer workstation lease already owns the mutex;
  they were not bypassed or represented as passing.
- `compileall -q app src tests tools/cross_band_fill_clustering_20260924.py`: exit 0.
- Agent documentation audit: PASS; roadmap `--fail-on-lint --check`: no lint issues.
- Staged diff whitespace check: clean. The owned `C:/tmp/f94a` test directory was removed
  after resolving its exact path and confirming it was not a reparse point.

No full local suite is claimed. PR CI and production adoption are separate checks.

On this branch in an attended workstation checkout, resolve the repository and project interpreter,
then run each command through the wrapper. A linked worktree uses the parent checkout's venv.

```powershell
$missionRoot = (Resolve-Path .).Path
$missionCommonGit = (& git rev-parse --path-format=absolute --git-common-dir).Trim()
$missionCheckout = Split-Path $missionCommonGit -Parent
$missionPython = (Resolve-Path (Join-Path $missionCheckout 'venv\Scripts\python.exe')).Path
$missionArgs = '["-m","tools.cross_band_fill_clustering_20260924","collect"]'
$missionEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($missionArgs))
& .\scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -PythonPath $missionPython -ArgumentsBase64 $missionEncoded -RepoRoot $missionRoot
```

Repeat with the final JSON argument changed to `publications`, then `selftest`, then `analyze`.
Only the first two commands make public GETs; `analyze` rebuilds solely from cache and fails on
uncached input. No production-host execution is implied by this workstation command.
For the admission tests, use Kind `pytest` and JSON arguments
`["-m","pytest","tests/operations/test_missing_information_admission.py","tests/operations/test_workload_admission_script.py","-q","--basetemp=C:/tmp/f94a"]`.
Delete only that owned short test directory after the run.

## Integration disposition

| Mission file | Expected closure classification |
| --- | --- |
| `tools/cross_band_fill_clustering_20260924.py` | Research entrypoint; no runtime import added |
| `.codex/hooks/pre_tool_use_host_load.py` | Local agent admission hook; no capture import added |
| `scripts/ops/workload_admission.ps1` | Roll-free PowerShell |
| `tests/operations/test_missing_information_admission.py` | Test only |
| `tests/operations/test_workload_admission_script.py` | Test only |
| This report | Roll-free documentation |

`scripts/ops/roll_verdict.ps1 -Branch codex/fill-clustering-20260924` returned exit 1:
**UNDECIDABLE: no live closure evidence**. All four required local supervisor-status files are
absent on this isolated workstation worktree. Thus the actual adoption verdict for these files
remains **UNDECIDABLE**; the table is an expected source classification, not a derived production
roll-free verdict. Production must run
`scripts/ops/roll_verdict.ps1 -Branch origin/codex/fill-clustering-20260924`
against its retained closures, including the inherited handoff-branch delta, before integration.

No registration, production write, restart, master merge, live command, authenticated exchange
request, credential/.env read, or mirror write occurred. The branch and draft PR hand back source
and descriptive evidence; they do not adopt it or change live trading authority.
