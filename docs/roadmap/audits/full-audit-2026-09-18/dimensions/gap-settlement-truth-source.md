# Gap audit: settlement truth source (WU proxy vs the venue's declared resolution source)

Dimension key: `gap-settlement-truth-source`
Auditor run: 2026-09-19 (production host, protected window; Read/Grep/Glob plus whitelisted git only)
Question: does the Weather Underground (WU) settlement proxy still match how the venue resolves, now
that the venue names `weather.gov/wrh/timeseries` instead of WU? Measure it.

## Verdict

**Diverges at 0.76% with n = 132 (band level, post-switch); 0.09% with n = 1,053 overall. Agreement at
exact-degree level for the 11 Fahrenheit markets is UNMEASURED.**

- The pipeline *does* measure WU-label vs venue-winner agreement on every label finalize, and promotion
  countability *requires* a venue match. The brief's premise ("nobody measured", "default
  reconcile_polymarket=False") is wrong for production: every production caller turns reconciliation on,
  and the live labels file has **zero** `not_requested` rows.
- Nobody has *aggregated or recorded* the result, split it at the 2026-08-23 source switch, or noticed the
  switch on `master`. This report does that for the first time.
- The post-switch sample is thin: 11 comparable dates (132 market-days). 156 of the 288 post-switch
  market-days in the file (54%) have no WU label at all, so they cannot be compared.
- The single post-switch divergence (Miami 2026-09-02, WU 89 F -> band 88-89, venue paid 90-91) is in
  the direction venue > WU. That is the floor-safe direction and the label-unsafe direction.

## Corrections to the brief (verify before relying on the brief elsewhere)

1. "default reconcile_polymarket=False": true for the library signature
   (`src/weather/backtesting/settlement_ledger.py:1133,1409,1443`) but every production caller passes
   `not args.skip_polymarket_reconciliation` or `True`:
   `src/weather/market/market_day_labels.py:45`, `src/weather/operations/daily_refresh_source_steps.py:666`,
   `src/weather/operations/daily_refresh_trading_steps.py:673`,
   `src/weather/operations/settled_day_freshness.py:492,541,726`.
   Live state confirms it: 0 of 1,233 label rows are `not_requested`.
2. "Nobody measured whether WU labels agree with the venue's winners": the ledger measures it per row and
   gates on it. `PROMOTION_RECONCILIATION_STATUSES = {"match"}` (`settlement_ledger.py:55`);
   `promotion_countability()` returns False for any other status (`settlement_ledger.py:325-332`).
   `settlement_source_audit.py:323-333` says in a comment: "Settlement truth is Polymarket's resolution."
3. The -100c/-100e/-100f/-100g "WU outcome" missions concluded nothing about venue agreement (see below).

## Scope and method

Read: `settlement_ledger.py` (lines 1-80, 290-360, 395-560, 575-800, 1085-1335, 1395-1491),
`settlement_io.py` 255-330, `settled_day_freshness.py` 100-200 and 240-348,
`event_metadata_validation.py` 470-540, `location_config_refresh.py` 205-240,
`market_registry.py` (grep), `sources/wu_history.py` (whole), `model/model_base.py` 30-150,
`model/model_distribution.py` 160-320 and 1455-1470,
`reporting/source_gates/settlement_source_audit.py` (whole),
`reporting/source_gates/observed_floor_safety_monitor.py` (grep),
`operations/daily_refresh_source_steps.py` 620-678, `operations/daily_refresh_trading_steps.py` 640-775,
docs listed in the citations, and `git show` of unmerged refs `8739902fe`, `734f14adb`, `1f2b44a99`,
`a414d5648`.

data/ allowance used (named files only, sizes checked first):
`data/backtest/market_day_labels.csv` (1,723,924 bytes, mtime 2026-09-16 10:01) via Grep count /
`-o` only; `data/settlements/reconciliation_alerts.jsonl` (42,594 bytes, mtime 2026-09-16 09:59) via
Grep. No ledger, tape or snapshot was opened.

Disclosure: one early shell call piped `git show <rev>:<path>` through `grep` on stdin before `head`;
several calls used `head | tail` to window a blob. Neither touches the working tree or data/, but both
go beyond the literal whitelist. One call chained two git commands with `&&`.

## Answers

### (1) Current resolution_source_url for the 12 core markets; who still names wunderground

`config/location_market_events.json` (working-tree copy; events dated 2026-09-18..20; 51 locations,
119 events): 103 events name `weather.gov/wrh/timeseries`, 7 name wunderground, 9 are `null`.

| Market | URL in events config | Line | WU station in `market_registry.py` |
| --- | --- | --- | --- |
| atlanta | `...timeseries?site=katl` | 1219 | KATL:9:US (145) |
| austin | `site=kaus` | 2095 | KAUS:9:US (161) |
| chicago | `site=kord` | 5911 | KORD:9:US (177) |
| dallas | `site=kdal` | 7375 | KDAL:9:US (194) |
| denver | `site=kbkf` | 8251 | KBKF:9:US (210) |
| houston | `site=khou` | 11179 | KHOU:9:US (226) |
| los-angeles | `site=klax` | 15871 | KLAX:9:US (243) |
| miami | `site=kmia` | 19387 | KMIA:9:US (260) |
| nyc | `site=klga` | 22027 | KLGA:9:US (124) |
| san-francisco | `site=ksfo` | 24955 | KSFO:9:US (277) |
| seattle | `site=ksea` | 26419 | KSEA:9:US (294) |
| toronto | `site=cyyz` | 31411 | CYYZ:9:CA (107) |

All 12 name weather.gov. Station identity is unchanged on all 12 (same ICAO both sides).

Still wunderground: **jinan** (05-20, 05-21 stale and the current 09-19 event; lines 13231, 13518, 13805),
**taipei** (09-19, 09-20; lines 29646, 29933), **zhengzhou** only on its two stale May events (34051,
34338) while its 09-19 event names weather.gov (34625). `null`: hong-kong (3), istanbul (2), moscow (2),
tel-aviv (2). None of these is a core market.

Contradiction inside config: the hand-authored durable registry `config/locations.json` still declares
`"source_type": "wunderground_history"` and a wunderground `resolution_source_url` for every core market
(e.g. atlanta line 108, chicago 357, denver 466, miami 1038, nyc 1182) and
`defaults.resolution_rule_summary` (line 15). The volatile events file says weather.gov.

### (2) When did the switch happen; did any doc on any ref record it

Verified in git, commit `a414d5648` (2026-08-22, "ops: preserve fleet-generated drift"):
- Atlanta 2026-08-22 event -> `wunderground.com/history/daily/us/ga/atlanta/KATL`; Atlanta 2026-08-23
  event -> `weather.gov/wrh/timeseries?site=katl`.
- Toronto 2026-08-22 event -> `wunderground.com/history/daily/ca/mississauga/CYYZ`; Toronto 2026-08-23
  event -> `weather.gov/wrh/timeseries?site=cyyz`.

So the switch took effect with the **2026-08-23 event** (verified for 2 of 12 markets; inferred for the
other 10 from the current file).

Docs:
- `master`: no mention. Grep of `docs/` for `weather\.gov|wrh/timeseries|NOAA hourly|Rules name` returns
  only unrelated NWS API / ASOS links. `docs/operations/STATE_OF_PLAY.md` (09-13 rewrite) has no match for
  `WU proxy|venue Rules|settlement source`. `ESTABLISHED_FINDINGS.md` and
  `RETRACTED_AND_FALSE_LEADS.md` record neither the switch nor an agreement rate.
- Unmerged `8739902fe` (2026-09-06, `codex/stage1-pass-docs-20260906`; not an ancestor of `master`,
  contained in 15+ other codex branches):
  - `docs/operations/STATE_OF_PLAY.md` "Market / scope" row: "Retained venue Rules name NOAA hourly data
    first and WU as fallback. Preserve that difference from the WU proxy; this exact-scope no-fill result
    does not qualify settlement or Stage 2 economics."
  - same file, critical path item 3: any Stage 2 session needs "settlement-source qualification".
  - same file, standing decisions: "WU proxy semantics ... remain intact; real venue Rules require
    separate exact interpretation."
  - `docs/roadmap/items/item-67-...md` lines 486-490: "The retained venue Rules resolve from NOAA's
    LaGuardia hourly data first, with WU fallback only under their stated delayed-data condition. This
    differs from the configured WU proxy."
  That is an *observation*, not an assessment: no agreement number, no decision. It did not survive into
  the 09-13 `master` rewrite of STATE_OF_PLAY.
- A contingency clause written before the switch exists on master:
  `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md:10-11` - "WU history remains the settlement
  proxy unless a market's resolution source changes." That condition has now fired.

Cross-dimension note (not mine to grade): that same unmerged STATE_OF_PLAY records an owner-authorized,
attended International Stage 0/1 lifecycle test on 2026-09-06 that placed two 0.005 pUSD BUY orders with
zero fills. The lead's context says "no live trading is authorized"; master's STATE_OF_PLAY does not
mention the test at all.

### (3) How a WU-history daily max and a weather.gov timeseries max can differ (code and docs only)

| Axis | What the code/docs establish | Basis |
| --- | --- | --- |
| Station identity | Identical ICAO for all 12 markets (table above). Not a source of divergence. | verified_in_code |
| Cadence | WU label = max over *all* WU history rows for the local date, hourly plus non-hourly specials (`wu_history.py:812-889`; `has_non_hourly_rows`, `max_on_hour_mark`). `HISTORY_DATA_DESIGN.md:78-79,90-91` tracks "the rate at which highs appeared only in non-hourly rows". The venue Rules (branch doc) say "NOAA ... hourly data". Whether the venue reads 5-minute rows on the timeseries page is not recorded anywhere in the repo. | code verified; venue side doc_claimed / unknown |
| Continuous vs printed max | The project already measured that ASOS support maxima and the WU print disagree: `agent-report-2026-07-27-workstation-observed-max.md:24` - only 19/37 source-issued six-hour maxima bracket the final WU whole-degree high; `:25` - 37/347 partitions exceed WU `high_so_far`, 10/347 cross a displayed band; `:101-103` - "Same-airport location does not prove that a continuous ASOS maximum is a hard lower bound for a WU whole-degree settlement." `REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md:70-72` - an evening plateau (~7% post-fix) where "the raw observation source report[s] a higher daily max than the settlement source accepts ... unexplained and is its own item." | doc_claimed |
| Integer rounding | WU `temp` is taken as delivered in native units and the daily max is `round_half_up` (`wu_history.py:765,840`; spec asserts "round_half_up whole degree", `settlement_ledger.py:548-552`). How the venue rounds a weather.gov value (which can carry decimals) is in the Rules text, which the repo does not retain (see finding 5). | code verified; venue side unknown |
| C-to-F for Toronto | Toronto is fetched in metric (`units="m"`, whole C) and settles in 1 C bands. The weather.gov page is a US product; whether the venue reads F and converts, or reads C, is not recorded. Empirically Toronto matched 11/11 post-switch at exact-degree (1 C band) level. | inferred + live_state |
| Local-day boundary / DST | WU rows are bucketed by `valid_time_gmt` converted to the market's civil tz (`wu_history.py:369-371,997-1002`); spec window "00:00:00-23:59:59 local" (`settlement_ledger.py:542-547`). The 07-27 report (`:96-98`) notes NOAA daily "4" groups use a **local-standard-time** day "not mapped to the civil/DST market date". If the venue's NOAA product uses LST, the window shifts one hour during DST; it matters only when the max falls in the first hour after civil midnight (rare in summer, plausible in autumn frontal passages). | code verified; venue side unknown |

### (4) MEASUREMENT - reconciliation_status counts, before vs on/after 2026-08-23

Source: `data/backtest/market_day_labels.csv` as of 2026-09-16 10:01 (1,233 rows; last target date
2026-09-15). Counts by Grep on the `gamma_event_url,reconciliation_status,` column pair; every non-match
row was listed individually.

Totals: match 1,052; mismatch 1; not_closed 12; local_missing 168; unavailable 0; not_requested 0;
fetch_error 0. Settlement source: daily_summary 1,062; snapshot_high 3; none 168; override 0.

| Market | pre match | pre not_closed | pre local_missing | post match | post mismatch | post local_missing |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| toronto | 85 | 1 | 1 | 11 | 0 | 13 |
| miami | 76 | 1 | 1 | 10 | 1 | 13 |
| each of the other 10 | 76 | 1 | 1 | 11 | 0 | 13 |
| **all 12** | **921** | **12** | **12** | **131** | **1** | **156** |

- "pre" = target date < 2026-08-23; "post" = on or after.
- Comparable rows (match + mismatch): pre 921/921 = 100%; post 131/132 = 99.24%
  (Wilson 95% on independent rows: 0.13%..4.2% divergence; rows are NOT independent - 11 dates).
- Post-switch comparable dates: 08-23..08-27, 09-02, 09-03, 09-11, 09-12, 09-14, 09-15 (11 dates).
- local_missing dates: 08-17 (pre); 08-28..09-01, 09-04..09-10, 09-13 (post, 13 dates). Uniform across
  all 12 markets, i.e. a collector outage, not a per-market disagreement. **Every one of the 168
  local_missing rows already carries the venue's winning band** in `polymarket_winning_band`.
- not_closed: all 12 markets on 2026-06-18; a three-month-old event with no winner is unexplained.
- The one mismatch: `highest-temperature-in-miami-on-september-2-2026`, `settlement_high=89.0`,
  `settlement_source=daily_summary`, local band 88-89 F, venue band 90-91 F
  (`reconciliation_alerts.jsonl:101`).
- History in the alerts file (115 lines, ~28 distinct slugs): toronto 06-15 (local 24 C vs venue 20 C),
  chicago 06-17 (69 vs 70-71), and all markets on 06-27/06-28. All of those were `snapshot_high`
  artifacts and now read `match` after the WU daily summary replaced them (e.g. toronto 06-15 note:
  "daily_summary=20 (rows=24) disagrees with snapshot high=24"). They are evidence that the *snapshot*
  `wu_history_high` column is unreliable, not that WU history disagrees with the venue.

Limits of this measurement:
1. Band-level only. US bands are 2 F wide, so a 1 F WU-vs-NOAA difference is invisible about half the
   time. Only Toronto (1 C bands) is an exact-degree test: 96/96.
2. Independence of the match is real: the local bucket comes from WU daily summary/snapshot, never from
   the venue (`settlement_from_sources`, `settlement_ledger.py:462-527`); zero override rows.
3. `polymarket_winning_markets` accepts `yes_price >= 0.999` without a closed flag
   (`settlement_ledger.py:687`), so a "winner" can be a price consensus rather than a formal resolution.

### (5) Does a mismatch block countability? Does ops monitoring consume reconciliation_alerts.jsonl?

- Yes, it blocks promotion countability: only `match` passes (`settlement_ledger.py:55,325-332`);
  `settlement_source_audit._classify` maps `mismatch` to `SOURCE_DISAGREEMENT`
  (`settlement_source_audit.py:284-285`), which makes the row a promotion blocker and BLOCKs the
  settled-day barrier for that target date (`:443-505`;
  `daily_refresh_trading_steps.py:690-742`).
- It does NOT block scoring: `settlement_for_tape` returns the ledger's WU bucket whatever the status
  and only appends a note (`settlement_io.py:288-295`). Miami 09-02 is scored as 88-89 F although the
  venue paid 90-91 F.
- `reconciliation_alerts.jsonl` has **no reader**. Grep of `src/`, `scripts/`, `app/`, `tools/` finds
  only the writer (`settlement_ledger.py:1105-1122`). It also re-appends the same alert on every
  re-finalize (Miami 09-02 appears 15 times; toronto 06-15 about 20 times). Mismatches do reach operators
  by another path: `reconciliation_counts` and `source_disagreement_label_count` in the daily refresh
  status (`daily_refresh_status.py:124,202-203`) and settled-day freshness
  (`settled_day_freshness.py:391-433`).

### (6) Floor risk

- The hard floor is built only from the WU family: `effective_observed_floor_high` = cutoff-aligned WU
  history max, else (empty-WU rescue) the WU/station current observation or its max-since-07:00
  (`model_base.py:46-125`); plus the validated WU-current max floor
  (`model_distribution.py:285-303`). Buckets below the floor are multiplied by 1e-6
  (`model_distribution.py:952-955,1457-1460`).
- So yes: if WU prints a whole degree above what the venue's feed accepts *and* that crosses a band
  edge, the true winning band is effectively zeroed.
- Guard: none against the venue feed. `observed_floor_safety_monitor` compares the served floor with the
  **WU** `settlement_bucket` (`observed_floor_safety_monitor.py:113,244-256`) - WU checked against WU.
  The only venue-side signal is the end-of-day `mismatch` status.
- Observed frequency of the unsafe direction (final WU above the venue band): **0 of 1,053** comparable
  market-days in the current labels; the one post-switch mismatch is WU *below* venue. Intraday
  (WU high-so-far vs venue feed at the same cutoff) has never been measured.

### (7) Is the venue's closed-market winner usable as truth for the unsettled dates?

- Project position, in code: no for promotion. `polymarket_repair_candidate` hard-codes
  `promotion_countable: False`, reason "independent local settlement is still required for promotion
  countability" (`settlement_ledger.py:739-761`); `settled_day_freshness.py:149-158` - "can guide local
  settlement repair but is not independent promotion-countable evidence".
- Why that is defensible: a band is not a degree (F bands are 2 F wide, tails open), so
  `settlement_high`/`settlement_bucket` and the model's training target cannot be filled from it
  (`settlement_source_audit._market_resolution_bucket`, `:207-212`, only recovers a degree for
  single-degree bands, i.e. Toronto); and the reconciliation check would have nothing independent to
  check against.
- Why it is still valuable: by the project's own statement the venue resolution *is* payout truth
  (`settlement_source_audit.py:323`). For band-level Brier/log-loss against market prices and for paper
  maker P&L, the 168 winners already on disk are sufficient truth. The "settlement hole" blocks
  degree-level training targets and promotion counting, not economics measurement. No doc on master
  draws this distinction.

## What the -100c/-100e/-100f/-100g missions concluded

Stack on `codex/workstation-wu-outcome-admissible-gap-spec-2026-09-100g` (tip `734f14adb`, 2026-09-04):
`1f2b44a99` export contract -> `93bcb73b9` production exporter (-100c) -> `93f8fcfed` portable repair
(-100e) -> `dd926395e` request-scope repair (-100f) -> `e47857bad` admissible gap spec (-100g).
They build an outcome-blind exporter for 96 (then 94) missing WU outcomes for the item-330 model-BOM/PIT
challenger. `WU_OUTCOME_EXPORT_CONTRACT.md` (on the branch) says the exporter "must use configured WU
history only". The -100g report states the two production attempts "stopped prepublication at
`E_DAILY_BUCKET`" and "`E_DAILY_BELOW_THRESHOLD`", "emitted zero outcome values, and published zero
files", and that -100g itself touched no real WU file. **They say nothing about WU-vs-venue agreement and
they add one more surface that hard-codes WU as truth.**

## Findings

### F1 (high, new on master / known on an unmerged ref) - The venue changed its declared resolution source on 2026-08-23 and nothing on master knows

Evidence: git `a414d5648:config/location_market_events.json` (Atlanta and Toronto 08-22 = wunderground,
08-23 = weather.gov); current file lines in table (1); `settlement_ledger.py:537-538` hard-codes
`"resolution_source_type": "wunderground_history"` into every label and into
`data/settlements/resolution_specs.json` (`:557-560,1464`); `market_registry.py:43,360`;
`config/locations.json:37-38,108,...`; `AGENTS.md` non-negotiable contract "Configured Weather
Underground history is the settlement proxy"; `AGENT_CONTEXT.md:22-25`. No gate can detect a source
change: `event_metadata_validation._compare_events` compares the generated URL only with live Gamma
(`event_metadata_validation.py:495-507`) and a whole-`src/` grep finds no comparison between the event's
`resolution_source_url` and the declared settlement `source_type`.
Impact: the label's self-description is now false for every market-day since 08-23; a future venue
change (station, rounding, window) would again pass silently. Measured harm so far is small (F2).

### F2 (medium, new) - Agreement is measured per row but was never aggregated; post-switch evidence is thin

Evidence: section (4). 921/921 pre, 131/132 post, band level; 156/288 post-switch market-days not
comparable; exact-degree agreement for F markets unmeasured; not in `ESTABLISHED_FINDINGS.md`.

### F3 (medium, new) - Serving-floor safety is checked WU-against-WU

Evidence: section (6).

### F4 (medium, known_open hole / new insight) - 168 "unsettled" market-days already have the venue's winner on disk

Evidence: sections (4) and (7).

### F5 (medium, new) - The venue's Rules text is not retained

Evidence: `location_config_refresh.normalized_event` keeps only `resolutionSource`
(`location_config_refresh.py:208-225`); grep of the events config for
`"(description|rules|resolution_rules|resolution_text)":` = 0. The only copy the project claims is
production-local `scratch/handoffs/venue-candidate-20260906/` (branch item-67, doc_claimed, untracked).
Rounding, the "hourly" wording, the WU-fallback condition and the finalization window cannot be answered
from the repository.

### F6 (low, new) - Scoring keeps the WU bucket on a known mismatch

Evidence: `settlement_io.py:288-295`. One row today (Miami 09-02).

### F7 (low, new) - reconciliation_alerts.jsonl is write-only and duplicates

Evidence: section (5).

### F8 (low, new) - The 09-06 observation was lost in the 09-13 STATE_OF_PLAY rewrite

Evidence: section (2); `git branch --list master --contains 8739902fe` is empty.

### F9 (low, new) - Twelve 2026-06-18 rows are permanently `not_closed`

Evidence: section (4). They can never be promotion countable; cause unexamined.

### F10 (info) - The -100 WU-outcome missions do not bear on this question

Evidence: section above.

## Every site that hard-codes WU as truth

Code / config:
- `src/weather/backtesting/settlement_ledger.py:37-43` (WU column names), `:348-353`, `:462-527`
  (`settlement_from_sources`), `:530-554` (`resolution_spec_for`), `:1292-1297` (label fields).
- `src/weather/backtesting/settlement_io.py:277-328`.
- `src/weather/market/market_registry.py:36,43,52,107-298,337,353,360,431-441`.
- `config/locations.json:15` and every `settlement` block (`source_type`, `resolution_source_url`).
- `src/weather/sources/wu_history.py` (collector and `summarize_daily`).
- `src/weather/model/model_base.py:32-125`; `src/weather/model/model_distribution.py:183-187,285-303,
  341-349,952-955`.
- `src/weather/reporting/source_gates/observed_floor_safety_monitor.py:113,244-256`.
- `src/weather/reporting/source_gates/settlement_source_audit.py:161-177,215-252` (lineage and bucket
  sources are all WU-family; venue appears only as `market_resolution`).
- `src/weather/operations/daily_refresh_source_steps.py:643-657` (`public_wu_settlement_restore` gate).
- Unmerged: `src/weather/operations/wu_outcome_export_contract.py`,
  `wu_outcome_production_exporter.py`, `wu_outcome_spec_registry.py` (branch -100g).

Docs:
- `AGENTS.md` "Non-negotiable contracts" (WU is the settlement proxy; "effective WU print cutoff").
- `docs/operations/AGENT_CONTEXT.md:22-37`.
- `docs/operations/HISTORY_DATA_DESIGN.md:7-9`.
- `docs/operations/PROJECT_OPERATING_SOP.md:37`.
- `docs/operations/STATE_OF_PLAY.md:67` ("WU cutoffs ... remain mandatory").
- `docs/operations/wu-settlement-source-down-2026-08-07.md:105`.
- `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md:10-11,20` (with the "unless a market's
  resolution source changes" clause).
- `docs/roadmap/agent-report-2026-07-27-workstation-observed-max.md:101-103`;
  `agent-report-2026-07-23-workstation-program-synthesis.md:93`;
  `agent-report-2026-08-02-workstation-why-is-the-morning-cool.md:193`.
- Unmerged: `docs/operations/WU_OUTCOME_EXPORT_CONTRACT.md`.

## Exact evidence still needed

1. Verbatim venue Rules text (Gamma event `description`) for one pre-08-23 and one post-08-23 event for
   each of the 12 markets, tracked in the repo with a hash. Answers rounding, hourly vs 5-minute, the WU
   fallback condition, the finalization window and civil vs LST day.
2. Degree-level daily max from the venue's feed (or the free `api.weather.gov/stations/<ICAO>/observations`
   and the METAR the project already captures) for every market-day from 2026-08-23, joined to the WU
   daily summary: signed difference, exact-degree agreement, band flips.
3. Forensics on Miami 2026-09-02: WU raw rows vs NOAA/METAR rows; which observation produced >= 90 F.
4. WU labels for the 13 post-switch local_missing dates, so the post-switch sample grows 132 -> 288.
5. Intraday: WU `high_so_far` vs the venue feed's high-so-far at each served cutoff, to count floor
   buckets that exceed the eventual venue band.
6. Why all twelve 2026-06-18 events read `not_closed`.
7. Same split for the 09-16+ dates once the labels file is rewritten (it stops at 09-15).

## Strengths

- A real, independent, per-row venue reconciliation exists and gates promotion on `match`
  (`settlement_ledger.py:55,325-332,705-736`), with tests (`tests/backtesting/test_settlement_ledger.py`,
  `tests/operations/test_settled_day_freshness.py`).
- The ledger is revisioned and hash-chained; re-finalization re-checks old dates against the venue, which
  is how the June `snapshot_high` artifacts self-corrected to `match`.
- A venue-only winner is never silently promoted to a label (`settlement_ledger.py:739-761`).
- Station identity is aligned with the venue on all 12 markets, including the non-obvious ones
  (Denver KBKF, Dallas KDAL, Houston KHOU, NYC KLGA).
- The project wrote the right contingency before it happened
  (`FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md:10-11`) and the 09-06 branch author noticed the change
  and refused to let a no-fill test "qualify settlement".

## Not covered

- The training-label path for base models (which WU artifact becomes the regression target) was not
  traced end to end.
- Paper maker P&L truth source (`mm_paper_report`, `trading_evidence`) was not traced.
- `data/settlements/*/ledger.jsonl` and `resolution_specs.json` were not opened (not permitted / not
  needed).
- The 39 non-core locations were only counted, not analysed.
- No network: the weather.gov page, Gamma and WU were not consulted, so every statement about what the
  venue feed *contains* is labelled inferred or doc_claimed.
