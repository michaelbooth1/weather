# 86a - Settlement truth after the source switch

**UNDECIDABLE: the workstation has no post-switch WU/venue panel. Free METAR reproduces all 480 available pre-switch WU degrees and 504/504 recorded venue bands, but that does not qualify it after the source switch. Candidate observations cover all 156 historically missing station-days; verified recovery remains unknown because their winning bands were not supplied.**

Historical measurement, 2026-09-22. Implements the owner's named 86a handoff from `origin/codex/reward-test-attended-handoff-20260921` at `0e47b5d1`. Nothing adopted.

## Evidence boundary

Requested interval: 2026-07-01 through 2026-09-21, 83 local dates x 12 built-in MarketSpecs = 996 possible station-days. The appendix enumerates that superset; it does not claim all were captured. The frozen workstation CSV identifies 504 captured market-days (42 dates x 12 markets), ending August 11: 480 WU daily-summary labels and 24 `local_missing` rows (August 8 and 11). All 504 have recorded venue bands. Its SHA-256 is `73054e9d1f831fc3062d9a033ffb3ce0bf6e78ea19b138bd5001a0426e3fee13`. This is a historical projection, not ledger authority or current production state.

The fetched master's generated event config contains current active events, not the missing historical winner panel. No production access or ledger mutation was attempted. The only individually specified post-switch WU/venue row is the handed-down Miami September 2 control: WU 89 F versus venue band 90-91 F. It is explicitly marked `supplied EF10c audit control` in the appendix, separate from the local CSV.

The [named production audit](audits/full-audit-2026-09-18/dimensions/gap-settlement-truth-source.md) supplies historical 921/921 pre-switch and 131/132 post-switch band agreement and identifies 156 missing WU labels on 13 dates. Those totals were not remeasured here. The subsequently fetched state of play reports backfills, so 156 is not asserted to be the number still missing on production today.

## Method and source limits

Every observation is assigned to MarketSpec's own civil calendar day and native unit; half-up whole-degree rounding uses `weather.units`. WU uses only `daily_summary` labels with a matching settlement unit. No snapshot fallback, band midpoint, or absent value becomes a degree. Observation availability is not a complete-day or promotion-countable label guarantee.

- `asos`: all available IEM/NCEI one-minute temperatures, through the existing ASOS normalizer; timestamp header `valid(Etc/UTC)` is normalized explicitly. Toronto is unsupported and KBKF returned no one-minute temperature rows. Gaps can severely depress a maximum. [IEM documentation](https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py?help=) describes its NCEI origin and availability delay.
- `metar`: routine and special reports from IEM (`report_type=3,4`), normalized by `weather.sources.metar_history`. `metar_with_6h` additionally admits US RMK `1snTxTxTx` maxima only when the entire six-hour window ending at the report timestamp lies inside the local date. Boundary-crossing windows and 24-hour standard-time summaries are excluded. This conservative composite can still miss the boundary part of a day's high. [NOAA decoding](https://aviationweather.gov/help/data/) defines the signed tenths-Celsius group.
- `nws`: keyless station observations with bounded pagination and local-day filtering; rejected or missing temperatures are excluded. The returned history reaches only September 15-21 (84 station-days); September 15 begins partway through the day. No NWS observation is available for the historical 13-date gap set.
- `metar_hourly` and `nws_hourly`: separate diagnostics implementing the WRH documented minute filter (51-59 for US NWS/FAA stations; 56-04 for other platforms including Toronto). This does not establish identical feed selection, revisions, or rounding to the binding web page. [WRH help](https://www.weather.gov/wrh/timeseries?site=klga) documents the filter and says displayed data are preliminary.

The [public NWS API repository discussion](https://github.com/weather-gov/api/discussions/854) attributes the Weather and Hazards Viewer to Synoptic and the API to MADIS. This is public support correspondence, not a station-by-station equivalence specification. The WRH help itself does not establish that its entire historical Temp column equals `api.weather.gov`. No undocumented endpoint, Synoptic API, embedded page token, paid source, or access-control workaround was used.

## Agreement counts

Pre: July 1-August 22 (636 possible station-days). Post: August 23-September 21 (360). `Available` includes partial observed maxima. Band and exact-degree comparisons each use their own nonmissing denominator. **Post comparisons with denominator 1 are solely the supplied Miami control, not a post-switch sample.** NWS 0/0 means no comparable reference, not zero accuracy.

| Period | Candidate | Available / possible | Venue matches / pairs | WU exact degrees / pairs | Venue D x M |
| --- | --- | ---: | ---: | ---: | ---: |
| pre | wu | 480/636 | 480/480 | 480/480 | 40 x 12 |
| pre | asos | 504/636 | 125/399 | 31/380 | 42 x 10 |
| pre | metar | 636/636 | 504/504 | 480/480 | 42 x 12 |
| pre | metar_with_6h | 636/636 | 320/504 | 182/480 | 42 x 12 |
| pre | metar_hourly | 636/636 | 497/504 | 471/480 | 42 x 12 |
| pre | nws | 0/636 | 0/0 | 0/0 | 0 x 0 |
| pre | nws_hourly | 0/636 | 0/0 | 0/0 | 0 x 0 |
| post | wu | 1/360 | 0/1 | 1/1 | 1 x 1 |
| post | asos | 265/360 | 1/1 | 0/1 | 1 x 1 |
| post | metar | 360/360 | 0/1 | 1/1 | 1 x 1 |
| post | metar_with_6h | 360/360 | 1/1 | 0/1 | 1 x 1 |
| post | metar_hourly | 360/360 | 0/1 | 1/1 | 1 x 1 |
| post | nws | 84/360 | 0/0 | 0/0 | 0 x 0 |
| post | nws_hourly | 84/360 | 0/0 | 0/0 | 0 x 0 |

Exact-degree signs are candidate minus WU in the native unit; Celsius and Fahrenheit are never averaged together.

| Period | Candidate | Signed degree differences (count) |
| --- | --- | --- |
| pre | asos | F:+0 (31); F:+1 (163); F:+2 (110); F:+3 (19); F:+4 (3); F:+5 (1); F:-1 (2); F:-10 (4); F:-11 (3); F:-12 (3); F:-13 (2); F:-14 (1); F:-15 (1); F:-19 (2); F:-2 (4); F:-3 (2); F:-4 (2); F:-5 (4); F:-6 (8); F:-7 (3); F:-8 (8); F:-9 (4) |
| pre | metar | C:+0 (40); F:+0 (440) |
| pre | metar_with_6h | C:+0 (40); F:+0 (142); F:+1 (234); F:+2 (57); F:+3 (7) |
| pre | metar_hourly | C:+0 (39); C:-1 (1); F:+0 (432); F:-1 (4); F:-2 (4) |
| pre | nws | No pairs |
| pre | nws_hourly | No pairs |
| post | asos | F:+1 (1) |
| post | metar | F:+0 (1) |
| post | metar_with_6h | F:+1 (1) |
| post | metar_hourly | F:+0 (1) |
| post | nws | No pairs |
| post | nws_hourly | No pairs |

## Uncertainty and interpretation

Exploratory paired candidate-minus-WU band agreement uses independent date and market resampling, 2,000 crossed-bootstrap draws, seed 860922. It is paired on available WU and candidate rows; it is not the difference between the unpaired table rates. No model was scored, no candidate fitted, no preregistered decision applied, and no alpha budget spent. Power/MDE for a confirmatory post-switch decision is not estimable from one selected control. A future qualification needs a preregistered estimand and powered panel. No model-artifact regimes are pooled.

| Pre candidate | Paired n; D x M | Delta percentage points | Exploratory crossed 95% interval, pp |
| --- | ---: | ---: | ---: |
| asos | 380; 40 x 10 | -68.421 | [-78.062, -58.398] |
| metar | 480; 40 x 12 | 0.000 | [0.000, 0.000] |
| metar_with_6h | 480; 40 x 12 | -36.875 | [-46.875, -26.875] |
| metar_hourly | 480; 40 x 12 | -1.250 | [-3.125, 0.000] |

METAR's all-success paired rows produce a degenerate [0,0] empirical interval: this cannot prove population equivalence or post-switch non-inferiority. The hourly-only pre-switch difference is **not distinguishable from zero** under this exploratory resampling. Post-switch superiority/equivalence is unidentified, not an observed precise null. The Fahrenheit venue bands generally contain two degrees (or an open tail), so a winning band alone cannot identify the exact venue degree. Candidate-versus-WU degree differences do not prove venue-versus-WU degree errors.

## Recovery count

The handed-down gap set is August 28-September 1, September 4-10, and September 13: 13 dates x 12 markets = 156. Counts below are conditional on that historical audit, not current production missingness. Best observed pre-switch agreement is the routine-plus-SPECI METAR candidate. It supplies an observed maximum on 156/156 gap days; whether those maxima match their venue winners is unknown (0 paired winners available). **Zero recoveries are verified; the true recoverable count is unknown, not zero.** No label was written.

| Candidate | Historical missing days | Observed maximum available | All 24 hours represented | Available venue pairs |
| --- | ---: | ---: | ---: | ---: |
| asos | 156 | 106 | 44 | 0 |
| metar | 156 | 156 | 153 | 0 |
| metar_with_6h | 156 | 156 | 153 | 0 |
| metar_hourly | 156 | 156 | 152 | 0 |
| nws | 156 | 0 | 0 | 0 |
| nws_hourly | 156 | 0 | 0 | 0 |

Hourly coverage is a sampling diagnostic, not proof the physical maximum was observed. The Miami control is informative: METAR and hourly METAR give 89 F, while one-minute ASOS and the six-hour composite give 90 F and land in the supplied 90-91 F winner. One selected disagreement cannot establish a source's overall post-switch agreement.

## Current binding Rules

The public Gamma response for [NYC September 22](https://polymarket.com/event/highest-temperature-in-nyc-on-september-22-2026) names NOAA and the LaGuardia WRH time-series page. Its description includes this exact sentence:

> This market will resolve off of the Hourly Data provided using the "Show Hourly Data" button.

It also specifies WU fallback if NOAA data remain unavailable by 11:59 PM ET the following day, whole-degree Fahrenheit precision, and a revision cutoff when the first following-day datapoint appears. The current sentence does not prove all past events used identical Rules.

Response fetched `2026-09-22T19:25:49.328359+00:00`; raw-byte SHA-256 `b7a3c7f0f01a40283220894bb223900714e6f9c4b37bb1735eb2b97f335fd88e`. The ignored cache retains the original response; the provenance appendix records its URL and digest.

## Complete evidence appendices

- [agent-report-2026-09-86a-settlement-truth-after-the-source-switch-station-days.csv](agent-report-2026-09-86a-settlement-truth-after-the-source-switch-station-days.csv): all 996 named station-days, source degrees, sample/hour coverage, WU values, venue bands and reference origin.
- [agent-report-2026-09-86a-settlement-truth-after-the-source-switch-disagreements.csv](agent-report-2026-09-86a-settlement-truth-after-the-source-switch-disagreements.csv): all 1126 comparison disagreements, each with market, date, candidate, reference, unit and signed exact-degree difference where defined.
- [agent-report-2026-09-86a-settlement-truth-after-the-source-switch-provenance.json](agent-report-2026-09-86a-settlement-truth-after-the-source-switch-provenance.json): source hashes, request statuses/URLs, agreement tables, crossed intervals and recovery counts.

Raw public responses and normalized series remain under ignored `data/settlement_truth_86a/`. HTTP 429 probes were retained, collection paused, then reduced to documented multi-station requests 15 seconds apart. Final batch requests succeeded. Network failures are not weather missingness. No alternate host or credential was used to evade a limit.

## Reproduction and verification

From this branch's repository root, use the project Python interpreter. Inputs and cached responses are local runtime evidence and are not guaranteed in a clean checkout. `inventory` may read a fresh projection on the owner host, but that is a new measurement unless its hash matches the one above. `analyze` and `report` are offline; `fetch`/`fetch-batch` never access the network without `--network`.

```powershell
.\venv\Scripts\python.exe tools/settlement_truth_source_20260922.py --help
.\venv\Scripts\python.exe tools/settlement_truth_source_20260922.py inventory --labels data/backtest/market_day_labels.csv
# Repeat for ranges 07-01..07-28, 07-29..08-25, 08-26..09-21:
.\venv\Scripts\python.exe tools/settlement_truth_source_20260922.py fetch-batch --family metar --markets atlanta,austin,chicago,dallas,denver,houston,los-angeles,miami,nyc,san-francisco,seattle,toronto --start 2026-07-01 --end 2026-07-28 --network
# ASOS groups: atlanta,austin,chicago; dallas,denver,houston; los-angeles,miami,nyc; san-francisco,seattle
.\venv\Scripts\python.exe tools/settlement_truth_source_20260922.py fetch-batch --family asos --markets atlanta,austin,chicago --start 2026-07-01 --end 2026-07-28 --network
# Repeat NWS for each of the 12 markets:
.\venv\Scripts\python.exe tools/settlement_truth_source_20260922.py fetch --family nws --market nyc --start 2026-07-01 --end 2026-09-21 --network
.\venv\Scripts\python.exe tools/settlement_truth_source_20260922.py fetch --family rules --market nyc --network
.\venv\Scripts\python.exe tools/settlement_truth_source_20260922.py analyze
.\venv\Scripts\python.exe tools/settlement_truth_source_20260922.py report
```

Only invoke network commands outside RE-1 live. Interrupt the foreground collection immediately when the owner starts live; the local STOP sentinel also prevents new requests and aborts response streaming. One serial collector per cache is required. No scheduled or unattended collection was installed.

Verification: focused deterministic tests run through `scripts/ops/workstation_heavy.ps1`; full-suite prohibition respected. The exact final test result and roll-verdict result are recorded in the handback below.

## Git handback and what was NOT done

Branch: `codex/settlement-truth-source-20260922`. Base: fetched `origin/master` `3b4232ae8e337c876f5771294914122b28ea5890`. Instrument commit: `1ead63e75802831d82a78844e0d4cd8c96372230`. The final branch tip is returned with this report; its own hash cannot be embedded recursively.

No serving, training, model scoring, label, config, ledger, floor, gate, release, EF/digest or production change; no credentials or `.env` read; no exchange mutation; no registration, restart, merge or full suite. Neither protected RE-1 worktree was accessed or modified. Existing main-checkout changes were untouched. No current capture-health, live-readiness or promotion-countability claim is made.

### Verification handback

- Initial focused suite: **15 passed** in 0.11 s through the workstation wrapper. Its first invocation had 12 passes and 3 temp-directory setup errors; creating the owned temp parent resolved those errors.
- Final expanded suite: **18 passed** in 0.20 s through the same workstation wrapper. The first final-run attempt was refused because another workload held the host-global lease. Network and heavy work stopped; after the owner confirmed RE-1 was neither starting nor running, a normal guarded retry passed. No guard was bypassed.
- Test temp directory was removed after the successful run using an exact resolved-path check. Free disk was 169,606,881,280 bytes before that initial test sequence and 169,593,298,944 afterward; concurrent public-cache growth was also occurring, so the difference is not attributed to pytest. Before the refused final run, free disk was 169,473,384,448 bytes.
- Final test free disk: 169,468,702,720 bytes before and 169,468,661,760 after; the owned pytest temp directory was removed. The two published CSV SHA-256 digests were checked against LF-normalized artifact bytes so Git checkout normalization cannot invalidate them.
- `git diff --cached --check` passed for the instrument commit. No full suite or broad compileall ran. No canonical documentation, roadmap item or generated backlog changed, so their generators were not invoked.
- `scripts/ops/roll_verdict.ps1 -Branch HEAD -Base origin/master -JsonOut data/settlement_truth_86a/roll-verdict.json` returned **UNDECIDABLE: no live closure evidence** (exit 1). This isolated worktree has none of the four required capture status files. No hand-derived roll-free verdict substitutes for that result.

| Changed path | Per-file closure verdict |
| --- | --- |
| `tools/settlement_truth_source_20260922.py` | Unverified: required live closures absent |
| `tools/test_settlement_truth_source_20260922.py` | Unverified: required live closures absent |
| This report and its three adjacent evidence appendices | No runtime behavior introduced; production integration still requires the owning tool's verdict |

The production agent owns current ledger/venue evidence delivery, exact-tip roll qualification, EF/digest updates and any adoption proposal. To finish the measurement, supply the current per-day WU labels and independently resolved venue bands with provenance for the requested interval. The public candidate maxima are already retained for comparison. Two-degree winning bands alone cannot supply exact-degree venue truth.
