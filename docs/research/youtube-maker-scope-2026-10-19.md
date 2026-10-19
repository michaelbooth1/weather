# YouTube-views maker plugin: scoping (2026-10-19)

Status: dated research scoping, docs only. **Outcome-free:** no labels, settlements, market prices or
evidence dated 2026-09-30 or later were read. Nothing was fetched from the internet, and no key was
created or requested.

- **Owns:** what a YouTube-view plugin for `maker_core` would have to implement, which capture and
  data it needs, the YouTube Data API quota plan, and an effort and risk estimate.
- **Read when:** the owner decides whether to move maker work from weather to YouTube-view markets,
  or someone starts that work.
- **Not here:** current authority ([state of play](../operations/STATE_OF_PLAY.md)), the plugin
  contract itself ([maker core contracts](../operations/maker-core-contracts.md)), or evidence that
  any YouTube model has an edge. This repository holds none.

Trigger: on 2026-10-19 the owner said a YouTube view model "is showing a lot more promise". If the
weather model has no edge, the owner wants maker work moved to YouTube-view markets on International
Polymarket.

## 0. What already exists (git, all refs)

| What | Where | State |
| --- | --- | --- |
| Standing rule: new maker code is domain-neutral, with weather and YouTube as plugins | `80647ac23` (09-23); [forward plan](../operations/forward-plan-2026-09-23.md) item 5; DECISION_LOG 2026-09-25 | In force |
| Design: YouTube universe = view-count threshold markets; fair value = P(views >= threshold by deadline); clock = upload (scheduled widen) and count polls (detected); settlement = "the count the venue rules name" | [informed maker design](../operations/informed-maker-design-2026-09-25.md) (Weather/YouTube paragraph and trigger table) | Design text only |
| YouTube model | Owner's **separate repo and PC** (design: "YouTube implements the same four in its own repo"; DECISION_LOG 2026-09-27: read-only, market prices never model inputs, diagnostics-only on its current PC; its capture moves to production after 10-15 once its journal fix has 7 days of measured disk use) | **No code, interface or result in this repo** (design §Unverified) |
| Contract additions motivated by YouTube: `InfoEvent.active_until_utc` (count polls would otherwise pull forever), `group_relation` `nested_ge`/`nested_le` for threshold ladders, `SettlementFact.resolved_value` | [maker contract review](../roadmap/audits/maker-contract-review-2026-09-25.md); on master in `maker_core.contracts` (tag `maker-core-contracts-v0.1`) | Landed |
| YouTube plugin template (provider table, `Unavailable` rules, `valid_until`, replay bundle shape, conformance recipe) | PR #107, `codex/youtube-plugin-template-20260927` @ `5fc4e7d48`, `docs/operations/youtube-plugin-template.md`; W-0034 | **Not merged.** Closed with tag `archive/pr-107-5fc4e7d4` ([landing backlog review](landing-backlog-review-2026-10-05/REPORT.md) A27) |
| Portfolio campaign `youtube-maker` | `config/examples/portfolio_campaigns.json`; [portfolio ledger](../operations/portfolio-ledger.md) | Disabled placeholder; no start or capital |
| Swarm decisions: YouTube plugin **held until after 10-15**; one reward scan including YouTube approved | [swarm audit 09-30](../roadmap/audits/swarm-audit-2026-09-30.md) rows 12-13 | 10-15 hold has lapsed by date; no later decision |
| Reward-terms scan, weather vs YouTube (one public read, 10-01) | [agent report 2026-10-01a](../roadmap/agent-report-2026-10-01a-reward-scan.md) | Single snapshot |
| Expansion desk row: "views counter" at 24 h / 72 h / 7 d, **verbatim rules UNVERIFIED**, counting regime said to change 2026-08-24, counts non-monotone; `videos.list` 1 unit/call; RSS for upload detection; **NO-GO until** #107 merged, API-key placement decided, after 10-15. Owner: no YouTube key on the capture host; capture on the workstation after 10-15 | [exam pre-mortem](../roadmap/audits/exam-premortem-2026-10-02.md) §C and decision 6 | All three NO-GO conditions are still open (#107 archived) |
| Multi-domain capture design (`capture_families.json`, tag/series discovery, per-family budgets, YouTube Data API on the per-domain fetch allowlist) | [swarm expansion](../roadmap/audits/swarm-expansion-2026-10-01.md) §1-3; [data layer v2 plan](../operations/DATA_LAYER_V2_PLAN.md) PL-3, VR-1, VR-3 | Planned; `config/capture_families.json` does not exist on master |
| Weather plugin (the worked example of all four protocols) | `src/weather/market/maker_plugin/` on build line `codex/maker-replay-v2-build-20261003` @ `1fd0c295f`; `maker_plugin_dry_run_v0.1` is its runner's report schema | **Not on master** |

Relevant reward-scan facts (10-01, one read, descriptive terms only): YouTube had 6 open `youtube`-tagged
views events (39 bands) and 12 rewarded bands with an 850/day pool, against 151 bands and 5,200/day for
weather. Two bands of one event carried 500/day with a 20-share floor; the other ten carried 50-share
floors. Scoring rules were identical (4.5 c max spread, c = 3). Ticks were 0.001 or 0.01. The scan
discovered YouTube through Gamma `public-search?q=youtube views` and `events?tag_slug=youtube`.
Event shapes seen: a channel's week-1 views bands, "next video" day-1 and week-1 views, and a long-dated
channel total-views ladder.

## 1. The `maker_core.contracts` interfaces

The authority is `src/maker_core/contracts/__init__.py` (`CONTRACTS_VERSION = "0.1"`, tag
`maker-core-contracts-v0.1`). Changes are additive only. The plugin imports only `maker_core.contracts`
and `maker_core.contracts.conformance`, never quoting, venue or `weather.*`
([package boundaries](../operations/package-boundaries.md)). Acceptance is
`check_conformance(universe, fair_value, information, settlement, clock=FixtureClock(...),
advance_inputs=...)`. Use `tests/maker_core/fixtures/fictional_domain.py` as the template.

There are four required Protocols and one optional Protocol.

### 1.1 `MarketUniverse`: `discover(as_of_utc, horizon_days) -> UniverseSnapshot`, `describe(condition_id, as_of_utc) -> MarketDescriptor`

`MarketDescriptor` has these fields: `domain_id`, `event_id`, `condition_id`, `outcome_tokens` (exactly
`{"YES","NO"}`, distinct), `tick` (0 < tick < 1), `min_order_size` (> 0), `neg_risk_group`,
`close_at_utc`, `settle_at_utc` (None or >= close), `native_unit`, `plugin_version`, `source_hashes`,
and `group_relation` (None, `partition`, `nested_ge` or `nested_le`). `UniverseSnapshot` is
`(markets, as_of_utc, source_hashes)` with no duplicate conditions.

A YouTube plugin must:

- Build descriptors only from **captured** Gamma event rows at or before `as_of_utc`, using the weather
  `WeatherUniverse` pattern. The tick and minimum size must come from both-token CLOB books, never from
  `rewardsMinSize`.
- Set `domain_id="youtube"`, `event_id` = Gamma event slug, and `native_unit="views"`.
- Set `close_at_utc` from the captured rules' measurement instant, not from `endDate` unless the rules
  say they are the same (open question Q1).
- Declare `group_relation` from the rules: `partition` for mutually exclusive range bands such as
  "30-35 M", and `nested_ge` for ">= N views" ladders. Never infer it from a title.
- Read `horizon_days` as an upper bound on time-to-close. YouTube events are keyed on hours after an
  upload or a fixed instant, not on local calendar days (see 1.6).

### 1.2 `FairValueProvider`: `evaluate(market, as_of_utc) -> OutcomeView | Unavailable`

`OutcomeView` has `condition_id`, `p_yes`, `stdev` (positive, or 0 only when p is exactly 0 or 1),
`joint` (sums to 1 within 1e-9 and agrees with the marginal), `as_of_utc`, `valid_until_utc`
(> as_of), `inputs_hash`, `model_id`, and `calibration_grade` (`none`, `shadow` or `scored`).
`Unavailable` has `reason`, `as_of_utc`, and `kind` (`missing_input`, `out_of_scope`, `corrupt` or
`decided`).

A YouTube plugin must:

- Adapt the owner's external view model through a **captured, hashed prediction record** (model id,
  inputs hash, issue time). The model's code is not imported. The adapter reads only records captured
  at or before `as_of_utc`.
- Map a predicted view-count distribution at the measurement instant to band probabilities. Partition
  bands get `joint`; nested ladders get marginals only.
- Set `valid_until_utc` from the plugin's documented freshness policy, for example the next poll plus
  slack.
- Use grade `none` until a pre-registered score exists.
- Never take a market price as input. The conformance probe injects `market_price` at 0.01 and 0.99.
- Return `Unavailable` rather than 0.5, the market mid, or a zero count when inputs are missing.

### 1.3 `InformationClock`: `upcoming(markets, from_utc, to_utc)`, `observe(markets, as_of_utc)`, both returning `tuple[InfoEvent, ...]`

`InfoEvent` has `kind`, `scheduled_at_utc`, `observed_at_utc`, `detected_at_utc` (at least one is
required, and detection >= observation), `affects`, `severity` in [0,1], `decided`,
`action_hint` (`pull`, `widen`, `recentre` or `observe`), and `active_until_utc`.

A YouTube plugin must:

- Emit `upcoming` events for scheduled uploads or premieres (`widen`) only when a captured schedule
  exists.
- Emit `observe` events for:
  - a detected upload (`pull`: the information shock for "next video" markets);
  - each count poll that moves a band's distance-to-threshold materially (`widen` or `observe`, each
    with an `active_until_utc` so they expire);
  - a count crossing a `nested_ge` threshold (`decided` with that condition's probability).
- Gate `decided` conservatively, because counts can fall (Q3). Weather's `decided` gate uses the WU
  printed high. The YouTube counterpart is "the count crossed and stayed crossed for k polls, or the
  settlement-source count crossed".
- Report detection times from local receipt, never from the API's own timestamps alone.

### 1.4 `SettlementResolver`: `resolve(market, as_of_utc) -> SettlementFact | Pending`

`SettlementFact` has `condition_id`, `p_yes` (payout fraction, which may be fractional), `as_of_utc`,
`source_hashes` (non-empty), `reconciliation_status`, and `resolved_value` (for example
`"36,412,118 views"`). `Pending` has `reason` and `as_of_utc`.

A YouTube plugin must:

- Resolve only from a **YouTube settlement ledger**, a new and owner-approved artefact that mirrors the
  weather `settlement_ledger` revision chain. Each ledger row binds:
  - the measured count from the rules' named source at the rules' instant;
  - the venue's resolved winner, reconciled.
- Return `Pending` until the ledger row and the venue resolution agree.
- Never settle from the plugin's own count poll alone. That is a forecast input, not a settlement.

### 1.5 `ExposureModel` (optional): `factors(market) -> Mapping[str, float]`

Factors would be `youtube:channel:<id>` (every band of one channel's events moves together), plus
`youtube:video:<id>`. Omitting it does not remove event or wallet caps.

### 1.6 Weather assumptions that leak into `maker_core` (master)

The WU proxy, station, METAR clock, lock-in and native-unit handling all live in the weather plugin
(`maker_plugin/clock.py`, `settlement.py`) and the weather shadow composition, not in `maker_core`.
`maker_core` imports nothing from `weather`. The leaks are calibration constants and calendar-day
semantics:

| Leak | Location | Why it is weather-shaped | Generalisation (additive) |
| --- | --- | --- | --- |
| `DecisionInputs.horizon_days` ("plugin-owned LOCAL date calculation") and `informed_v0.eligible_horizons=(1, 2)` (`HORIZON_NOT_ELIGIBLE`) | `quoting/policy.py`; `shadow/runner.py` `ShadowMarket.horizon_days` | Weather T+1/T+2 local dates. A 24 h "next video" market has no meaningful local-date lead. | YouTube profile with `eligible_horizons=None`, or a new optional `Profile.eligible_time_to_close` window. Field names must not change under v0.1. |
| `LAST_THREE_HOURS`: no quoting when `close_at_utc - now <= 3 h` | `quoting/policy.py`, hard-coded in `decide()` | Weather's last hours are when the WU high locks. For a 24 h video market, 3 h is 12.5% of its life, and the right cutoff is unmeasured. | Optional `Profile.last_quote_before_close` defaulting to 3 h (needs a roll verdict; see 4.3) |
| `adverse_markout` floor 0.0043 (refuses lower values) | `quoting/policy.py` `DecisionInputs`, `MISSING_CONSERVATIVE_FILL_BOUND` | Measured on the weather tape | Keep it as a floor. The YouTube value needs its own measurement and may be higher. |
| `stale_sigma_per_hour=0.01`, `grade_size_caps=(30, 50, 75)`, `sizes=(20, 30, 50, 75)` | `quoting/policy.py` `Profile` | Offline weather defaults. With grade `none` capped at 30 shares, a 50-share reward floor (10 of 12 YouTube bands on 10-01) cannot score. | A YouTube profile. Grade `none` would score only on 20-floor bands. |
| Per-band-minute trade hazard is required ("no hazard means no quote") | `quoting/policy.py` | The only hazard figures are weather (88a) | A YouTube trade-tape measurement before informed quoting |
| `discover(as_of_utc, horizon_days: int)`, called with 2 by conformance | `contracts/__init__.py`, `conformance.py` | Days, not hours | Usable as is (treat it as a ceil(days) bound). Document it in the plugin. |
| Public reads allow only Gamma `/events?slug=` (<= 20 slugs) | `venue/public_feed.py` `public_url` | Weather slugs are derivable (`highest-temperature-in-<city>-on-<date>`). YouTube slugs are not and need tag or series discovery. | Add `events?tag_slug=` (or series) to the allowlist. This is a maker_core venue change and rolls the shadow runner (see 4.3). |
| Gamma provenance allowlist omits `description`/`resolutionSource` | `shadow/records.py` `GAMMA_MARKET_KEYS` | The weather rules are known out-of-band. YouTube settlement depends on rule text. | VR-3 rules journal (data layer v2) or an additive key |
| Record sizing "24 bands", "12-band day" | `shadow/records.py` `SHADOW_REPLAY_LIMITS` | Weather band count | Fits YouTube (12 rewarded bands on 10-01) |
| Shadow selection, local-midnight rediscovery, slug building | `weather/market/maker_shadow.py` (weather composition, not core) | Weather-only | A new `youtube` composition module that reuses `maker_core.shadow.runner` |
| 88a recorder universe | `weather/market/maker_evidence_capture.py` `build_universe`; `--extra-conditions` <= 32 ids, active only inside at most two 30-minute UTC update windows | Weather slug-prefix universe | Not continuous YouTube capture; needs VR-1 generic universe / `capture_families.json` |

Settlement unit: `native_unit` is a free string, and the core does no arithmetic in it. "views" is
fine. `MID_OUTSIDE_RANGE` [0.2, 0.8] and the reward kernels are domain-neutral. The 10-01 scan found
identical reward rules across both domains.

## 2. Capture needed

Every request below is a public International Polymarket or Google read. None were made for this
document.

1. **Discovery.** Gamma `events?tag_slug=youtube` (and/or a series id), hourly, with change-only
   storage of the full event object, including `description`, `resolutionSource`, `negRisk`,
   `endDate`, `clobRewards` and market `groupItemThreshold`. This is DATA_LAYER_V2 VR-3 plus a
   `capture_families.json` row: `domain_id=youtube`, `discovery=tag_slug`.
   - Venue-wide `clob /rewards/markets/current` every 15 minutes (the expansion design) finds rewarded
     YouTube conditions without guessing slugs.
   - Polymarket US hosts stay refused.
2. **Order books and trades.** Reuse the venue recorder rather than writing a new one:
   - one POST `/books` per 100 tokens per minute;
   - the market-channel websocket (or data-api `/trades?market=`) for prints;
   - per-condition `/rewards/markets/<id>` for the quote-candidate set.

   The `maker_core.shadow` runner already reads books, terms and trades for any condition id. A
   YouTube shadow can start from discovered condition ids with blind fair value
   (`Unavailable` -> grade `none`), exactly as the weather shadow does today. Replay bundles already
   carry `domain_id` per condition. Volume is small: about 39 conditions and 78 tokens were open on
   10-01, which is one `/books` POST per minute.
3. **View-count observation stream.**
   - Data API v3 `videos.list part=statistics` (`viewCount`) for each video named by an open event,
     batched up to 50 ids per call.
   - `channels.list part=statistics` for channel-total ladders.
   - Upload detection from the channel uploads feed. The RSS feed needs no key;
     `playlistItems.list` costs 1 unit.
   - Proposed starting cadence: 30 s for videos inside the last 24 h before a measurement instant or
     within 2 h of upload, 5 min otherwise, and 60 s for channel totals. The right cadence depends on
     how often YouTube refreshes `viewCount` (Q4). Polling faster than the refresh buys nothing.
   - Each poll writes `{video_id, viewCount, local receipt UTC, HTTP status, response sha256}` with the
     key redacted, as the free-registration rule requires.
4. **Settlement source: open question.** No YouTube rule text exists in any repository fixture or doc.
   The only description is second-hand: a "views counter" at 24 h / 72 h / 7 d, marked **UNVERIFIED** in
   the exam pre-mortem. It is unknown whether the venue resolves on the watch-page counter, the API
   `viewCount`, a screenshot by a resolver, or a third-party tracker. It is also unknown at what instant
   and timezone, and with what treatment of later downward revisions. The 10-01 scan raw replies outside
   git (`scratch/reward-scan-20261001-final/`) probably contain the Gamma `description` field. They were
   **not** opened here (brief: repository fixtures/docs only; those files also carry 10-01 prices). A
   description-only projection of them, or the VR-3 rules journal, answers Q1-Q2 without reading any
   price.

## 3. API key and data plan (YouTube Data API v3, free tier only)

Quota facts below come from Google's published documentation as known to the author (not fetched). The
owner must verify them at sign-up:

- default 10,000 units per day per Google Cloud project, reset at midnight Pacific time;
- `videos.list`, `channels.list` and `playlistItems.list` cost 1 unit per call;
- `videos.list` accepts up to 50 ids per call;
- `search.list` costs 100 units and must not be used for polling.

**Quota math.** Units/day = ceil(N / 50) x 86,400 / C for N videos at cadence C seconds, plus channel
and upload-detection calls. Budget 80% of quota (8,000 units) so retries and backfills never hit HTTP
403 `quotaExceeded`.

| N videos | C = 10 s | C = 30 s | C = 60 s | C = 300 s |
| --- | ---: | ---: | ---: | ---: |
| <= 50 (1 batch) | 8,640 (over budget) | 2,880 | 1,440 | 288 |
| 51-100 (2 batches) | 17,280 (over quota) | 5,760 | 2,880 | 576 |
| 101-200 (4 batches) | 34,560 | 11,520 (over quota) | 5,760 | 1,152 |

Example day: one batch at 30 s (2,880) + one `channels.list` batch at 60 s (1,440) + `playlistItems`
for 3 channels at 5 min (864) = **5,184 units, about 52% of quota**. If the uploads RSS feed carries
upload detection, the cost is 4,320 units. The 10-01 universe (6 events) fits in one batch. The binding
constraint is cadence, not N. A two-tier cadence (30 s near the measurement instant, 5 min otherwise)
keeps a 100-video universe under 3,000 units.

**Key storage.** The [free-registration sign-up list](../operations/free-registration-signup-list.md)
key storage rule applies, as does the AGENTS rule against required credentials:

- The key lives only in git-ignored `config/local/` or the process environment. Suggested name:
  `WEATHER_YOUTUBE_DATA_API_KEY`.
- It is never in git, logs, status files, captured payloads or URLs written to disk (redact `key=`).
- One loader returns "absent", and the family writes "not captured, key absent" heartbeat rows rather
  than failing.
- No test or capture requires it.
- The owner already decided no YouTube key on the capture host (exam pre-mortem decision 6). This
  conflicts with DECISION_LOG 2026-09-27 ("capture moves to production after 10-15"), so placement is
  an owner decision (O3).
- Restrict the key in the Google console to the YouTube Data API v3 only.

**Fallbacks without a key or paid plan:**

- Channel uploads RSS for upload detection. It is believed to carry a `media:statistics views`
  attribute; check whether it is fresh enough to be a coarse count.
- The owner's existing model capture on its own PC, exported as hashed closed-day records.
- Without a key, the family degrades to Polymarket-only capture (books, trades, terms, rules) and grade
  `none` blind shadow quoting, which needs no YouTube data at all.

Excluded:

- paid trackers;
- scraping watch pages (terms risk);
- several Cloud projects or keys used to multiply quota (believed to breach the API terms).

The owner may request a free quota extension through Google's audit form instead.

**Terms risk to verify (owner action O2).** The YouTube API Services developer policies are believed to
limit how long API data may be stored without refresh (about 30 days for some data). That conflicts with
the repo's "evidence is never thinned" retention for settlement-grade capture. Read the current terms
before capture starts, and decide the retention class.

## 4. Effort, risks and integration with ops

### 4.1 Effort (one workstation agent; calendar time assumes the existing review/landing cadence)

| Step | Work | Build | Elapsed |
| --- | --- | --- | --- |
| Y0 rules desk study | Verbatim rules and resolution source for each YouTube event type (VR-3 or a description-only projection); counter-vs-API basis; `viewCount` refresh cadence trial (needs O1 key); answer Q1-Q5 | 1-2 d | 3-5 d |
| Y1 capture family | `capture_families.json` row; tag discovery and rules journal; view-count poller (new provider bucket, redaction, absent-key heartbeat); books/trades through the venue recorder; 7-day disk measurement (DECISION_LOG 09-27) | 3-5 d | +7 d |
| Y2 blind YouTube shadow | `youtube` composition reusing `maker_core.shadow.runner` with `Unavailable` fair value; registrar + `config/scheduled_tasks.json` row; owner activation | 2-3 d | +14 d of tapes |
| Y3 plugin | universe, clock, settlement (plus a YouTube settlement ledger), exposure; fair-value adapter over hashed external-model records; conformance + rule-join tests | 4-7 d | — |
| Y4 core generalisation | additive `Profile` fields (time-to-close eligibility, last-quote cutoff), Gamma tag read on the allowlist; roll verdict | 1-2 d | quiet-window merge |
| Y5 evidence | pre-registered fair-value score of the external model vs market on fresh dates; YouTube hazard/markout measurement; replay v2 over YouTube bundles | 3-5 d | 2-4 weeks of settled events |

Total is about **14-24 agent-days of build and 5-8 weeks before any scored YouTube maker evidence**.
That assumes replay v2 lands on its current plan; YouTube reuses it and does not fork it.

### 4.2 Risks

- **The edge claim is unevidenced here.** "More promise" has no artefact, pre-registration or score in
  this repo. The weather lesson applies: a plausible forecast is not edge over market prices (EF §1,
  §1b). The external model needs the same pre-registered market-relative score before it gets a grade
  above `none`.
- **Small universe, few clusters.** 6 events and 12 rewarded bands on 10-01, with 850/day against
  5,200/day for weather. Events cluster by channel, so power is lower than weather's 11-12 market
  clusters, which already cap power near 40% (EF §10j).
- **Concentrated informed flow.** The richest bands sit on near-resolution events, where informed
  traders (including the channel's own audience) are heaviest. The adverse markout is unmeasured and
  probably above weather's 0.0043.
- **Settlement basis risk.** Counter vs API value, refresh lag, a reported 2026-08-24 counting-regime
  change, and non-monotone counts (spam-view removal) are all UNVERIFIED. A `decided` signal could be
  wrong.
- **Size floors vs caps.** 50-share floors on most YouTube bands exceed grade-`none` caps and the
  existing per-band cash caps (EF §10a finding on 20-share quotes already binds).
- **Venue cadence.** "Next video" markets appear when a channel announces or uploads. Discovery
  latency and the rush at upload are the main operating hazard.
- **Terms and retention.** API terms on stored data and quota circumvention (O2).
- **Embargo interaction.** YouTube capture is a new family and must not read or score 88a or panel
  data in the embargoed windows. Its own evidence starts at capture start.

### 4.3 Integration with existing ops

- **Capture families:** one `youtube` family under data layer v2. It declares a RAM cap, a per-hour
  byte budget, a disk-band brake, and a request budget against the host-wide Polymarket bucket plus a
  separate Google-provider bucket. Retention:
  - class A for rules, books, trades, terms and the settlement ledger;
  - view polls follow the O2 terms decision.

  It gets no model-evidence lane until the desk study earns it (swarm expansion §2).
- **Host:** run it on the workstation or a capture-only third box, per owner decision O3 and the
  standing "no YouTube key on the capture host" answer. Any capture-host placement is time-gated and
  leased under the [host load policy](../operations/HOST_LOAD_POLICY.md). Workstation heavy work
  (replay, scoring, focused suites) goes through `scripts/ops/workstation_heavy.ps1`.
- **Scheduled tasks:** each new task gets a repository registrar in `scripts/ops/`, a row in
  `config/scheduled_tasks.json` with its owner doc, and an owner-approved activation block, as
  `WeatherMakerShadowRunner` / `register_maker_shadow_runner.ps1` did. "Landed is not running" applies
  until the Open-commitments verify runs.
- **Roll:**
  - A new `weather.market.youtube_*` module is loaded only by its own new task, so it should not roll
    capture.
  - Edits to `maker_core/venue/public_feed.py`, `maker_core/quoting/policy.py` or
    `maker_core/shadow/*` are imported by the live shadow runner and may roll it.
  - Always take the verdict from `scripts\ops\roll_verdict.ps1 -Branch <b>`.
- **Portfolio and guard:** enable the existing `youtube-maker` campaign only for an attended live
  session the owner authorises. The shadow uses `shadow-maker` and refuses the real wallet book.

## 5. Owner actions and open questions

- **O1:** create a free Google Cloud project, enable the YouTube Data API v3, issue a key restricted to
  that API, and place it in `config/local/` on the chosen host. Agents do not do this.
- **O2:** read the current YouTube API Services terms (storage and refresh limits, quota) and set the
  retention class for view polls.
- **O3:** choose the capture host (workstation, third box, or production), resolving DECISION_LOG
  09-27 against the exam pre-mortem decision 6.
- **O4:** decide whether to revive the #107 template (`archive/pr-107-5fc4e7d4`) as the canonical
  plugin guide.
- **O5:** provide or point to the external model's interface and its record format. Any edge claim
  needs a pre-registration before it is scored here.
- **Q1:** the exact measurement instant and timezone for each event type, and whether it equals Gamma
  `endDate`.
- **Q2:** the named resolution source (watch-page counter, API, other) and the dispute and revision
  policy.
- **Q3:** whether counts can decrease after a threshold is crossed, and how the venue treats that.
- **Q4:** how often `viewCount` refreshes through the API compared with the page counter.
- **Q5:** how long after an upload or announcement Gamma lists "next video" markets, and when rewards
  attach.

## Update when

Dated scoping. Do not modernise it. Supersede it with a numbered roadmap item if the owner starts the
work, and record Q1-Q5 answers in that item.
