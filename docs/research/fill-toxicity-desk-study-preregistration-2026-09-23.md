# Fill-toxicity desk study — pre-registration (2026-09-23)

Status: **FROZEN 2026-09-23, before any run of this study reads the execution tape.** Owner-approved as forward-plan item 5
([forward plan](../operations/forward-plan-2026-09-23.md)). `R` for any net-value computation is the frozen rule in
[fill-toxicity-R-rule-2026-09-23.md](fill-toxicity-R-rule-2026-09-23.md). The only prior read of this tape is the
2026-09-20 markout run (item 330: +0.19 c at 5 min, -0.43 c to settlement, pooled, no event split); this study adds the
event-window split and the simulated slow quote, neither of which has been computed. Changing anything below after a run
reads the tape requires a new dated pre-registration that names this one. Source: the 2026-09-23 quote-timing design
(section 2 of the local audit), with file:line citations kept as written.

## Design

**Question.** For a *slow* two-sided resting quote on a same-day band, is adverse fill loss per quoted minute
concentrated in pre-declared windows around information events, and by how much?

**Unit of analysis: a simulated slow quote, not the public average.** At each 60-s book sample, place a virtual
20-share bid at `mid - d` and ask at `mid + d` (d = 1.5 c; sensitivity 2.5 c). Re-price only at the next book sample.
Hold for at least 60 s, matching a slow quoter. A virtual leg is **filled** when a public trade prints at or through its
price within its life:

- conservative: strictly through the price;
- optimistic: at the price.

Queue position is unknown, so both are reported. Its markout is taken at +1/+5/+30 min against the book-tape midpoint
and at settlement against `polymarket_winning_band`, with WU as flagged fallback. A secondary cut repeats this on the
actual public maker fills using the existing tool with an added "event window" split.

**Event classes (pre-declared; times from our own captures):**

| Class | Event time `t_e` | Window (pre/post) |
| --- | --- | --- |
| E1 routine METAR print | Per station, the modal `metar_report_time` minute measured from our snapshots. Do **not** use the calendar's fixed :52. Toronto (CYYZ, no `metar` source, `market_registry.py:108-111`) uses the WU-history row time. | -3 / +10 min |
| E2 new-high print | `observation_triggers` `wu_history_high_increased` or `metar_temp_bucket_crossed`: use `observed_at`, and separately `current_captured_at_utc` | -10 / +15 min |
| E3 band decided | First observation time at which the running hourly-rule maximum exits the band (YES dead) or the band becomes the only survivor | -15 / +15 min |
| E4 NBM bulletin | First `provider_update_time`/fetch time of each 01/07/13/19Z bulletin | -5 / +30 min |
| E5 NWP cycle proxy | 0/6/12/18Z + 210 min (calendar default) | -10 / +25 min |
| Placebo | Same-length windows shifted to :20-:35 past the hour, same hours of day | — |

**Latency sub-study (no markouts needed).** For E2/E3, measure the midpoint change between the source `observed_at`
and our `current_captured_at_utc`. If ≥ 70% of the eventual 30-min move is already done by our detection time, a
*reactive* pull is useless, and only *scheduled* or *proximity* pulls (§4) can work.

## Frozen rules

- **Estimand (primary):** the concentration ratio
  `CR = (adverse loss per quoted share-minute inside E1∪E2∪E3 windows) / (same outside all windows)`.
  It uses the simulated slow quote, d = 1.5 c, conservative fill rule, 30-min horizon. Adverse loss = −min(markout, 0),
  in dollars.
- **Secondary:**
  - CR at 5 min and at settlement;
  - CR per event class;
  - tail rate P(markout ≤ -5 c) inside vs outside;
  - **net pull value per band-day** = avoided adverse loss − lost reward. Lost reward is priced at the measured
    `k_share` × modelled share × rate, per pulled minute, and uses the same simulation.
- **Data:** every closed same-day event date on the execution tape from 2026-08-15 to the freeze date. All 12 markets.
  One date = one cluster (and market × date as a sensitivity).
- **Exclusions (declared):**
  - date-market pairs with tape gap minutes > 5% or book-sample coverage < 90%;
  - minutes with a one-sided or crossed book;
  - midpoints outside [0.10, 0.90] (reported separately);
  - trades after local close;
  - events with no settlement row (settlement horizon only);
  - duplicate trade identities (the existing collapse rule, `execution_tape_markout.py:760-765`).
- **Inference:** date-clustered bootstrap, 90% intervals, seed fixed. Fewer than 10 clusters → `UNDERPOWERED`, which
  forces `INCONCLUSIVE`. That is the existing rule (`execution_tape_markout.py:77`).
- **Decision thresholds:**
  - `PULL_SUPPORTED`: CR lower bound ≥ 2.0 **and** net pull value lower bound > 0. The window set goes into the
    shadow-policy pre-registration (§5 step 4).
  - `PULL_NOT_THE_LEVER`: CR upper bound ≤ 1.5. Stop investing in timing. Test distance/band choice instead.
  - Otherwise `INCONCLUSIVE`: the passive capture adds dates.
- **Kill rule (for the same-day variant of the thesis):** if the simulated slow quote's net
  (reward − adverse loss, *after* the best pre-declared window set) has a 90% upper bound < 0 per band-day, same-day
  quoting at 20 shares is dead. T+1/T+2 is judged only on prospective data (§3). Freeze `R` (reward per filled share)
  from `k_share` before this read, as STATE_OF_PLAY requires (`docs/operations/STATE_OF_PLAY.md:66-72`). The
  2026-09-20 read without `R` is the precedent to avoid (item 330 `:88-91`).
- **Where to run:** the capture host inside 00:30-09:00 under the lease, as one serial bounded job (never the raw book
  tape in bulk: use `order_books_summary.csv` as the existing tool does, `execution_tape_markout.py:16-21`), or the
  workstation after a hashed export (D8-14).

### 2.4 Data gaps (declared in the pre-registration)

1. **Population mismatch:** same-day only. The quoted population (T+1/T+2) has no history (D8-01).
2. **60-s midpoints and a 120-s tolerance** blur the 1-min horizon. Report 1-min as descriptive only.
3. **Detection timing:** we poll observations every 60 s (`observation_trigger.py:95`). Faster participants see
   weather.gov 5-minute rows before the hourly print (INFERRED). Our `t_e` is a late bound.
4. **Cancelled quotes are invisible**, and the L2 stream is discarded (`execution_tape_store.py:159`), so competitor
   pulls around events cannot be seen historically.
5. **Retention of `observation_triggers.jsonl`** (a rotating sidecar) and of per-station METAR times for early tape
   dates is unverified. Check this before freezing. If lost, rebuild E1/E2 from IEM METAR (external, re-fetchable)
   and label it so.
6. Same-day 20-share bands are a morning transient. Same-day 100-share bands need about 98 pUSD per quote, outside
   today's envelope. The same-day result informs *mechanism*, not the target book.

## Clarification 1 (2026-09-23 afternoon, before any read; raised by mission 89a)

Four points the design left open are fixed here. They bind exactly like the rules above.

1. **Placebo placement.** For every event window of total length `L` (pre + post) anchored at event time `t_e`, the placebo
   window is `[HH:20, HH:20 + L)` in the same local clock hour `HH` as `t_e`, on the same date and market. A placebo window
   that overlaps any E1-E5 window on that date and market is dropped; dropped placebos are counted and reported.
2. **Window sets for the kill rule.** Exactly seven eligible sets: each single class E1, E2, E3, E4, E5; the union E1∪E2∪E3;
   and the union of all five. "Best" is the set with the highest **point estimate** of net pull value per band-day. The kill
   rule uses that set's 90% date-clustered **upper** bound of net (reward − adverse loss). Selecting the best of seven
   favours the thesis, so the kill test is conservative; the selected set and all seven estimates are reported.
3. **Reward in net pull value.** Lost reward per pulled minute = `rate(t) / 1440 × share_many(t) × k_share`, with
   **`k_share` = 1.0** for the primary (session 1 measured 0.96-1.09; no constant is fitted). Sensitivities, reported
   beside it and never replacing it: `k_share` = 0.5, and `share_single` in place of `share_many`. `R` is the frozen R rule,
   which is the same expression with `k_share` = 1.0.
4. **Midpoints.** Quote construction uses the **size-adjusted midpoint** of the canonical estimator (levels below the band's
   reward minimum size excluded), as RE-1 quotes and as the venue scores. Markouts at +1/+5/+30 minutes use the **existing
   markout tool's midpoint definition**, for comparability with the 2026-09-20 numbers; the size-adjusted midpoint is a
   reported sensitivity. The settlement markout uses the settled outcome (1 or 0).

## Clarification 2 (2026-09-23 afternoon, before any read; raised by mission 89a)

1. **Book input.** The study reads the **full-depth book tape** (`order_books.jsonl` / `.gz`, per event day), streamed one
   date at a time within the tool's memory bound, for the size-adjusted midpoint and competing reward scores.
   `order_books_summary.csv` is used only for coverage and gap checks. No precomputed input is supplied.
2. **Prices.** The frozen distance is a **target**: each leg is placed at the canonical estimator's price — target distance
   from the size-adjusted midpoint, **snapped outward to the venue tick** — exactly as RE-1 quotes. That snapped price
   governs both simulated fills and reward scoring. The actual distance is recorded per leg.
3. **Fill lifecycle and exposure.**
   - Prints are consumed in venue-timestamp order. A qualifying print (strictly through the price under the conservative
     rule; at or through under the optimistic rule; queue ahead ignored) fills
     `min(printed size, remaining leg size)`. Partial fills are allowed.
   - Filled shares leave the book at the print time; the remaining shares keep resting at the same price.
   - At the next book sample the leg is re-placed at the full 20 shares at the new snapped price (a continuous maker).
   - **Reward exposure** uses the resting size minute by minute. A leg whose resting size is below the band's reward
     minimum earns zero until it is re-placed. **Quoted share-minutes** count resting shares × minutes, so exposure stops
     for filled shares at the fill time.
   - `R`'s denominator is total filled shares under the same rule; the conservative rule is primary, the optimistic one
     a reported sensitivity.

## Clarification 3 (2026-09-23 afternoon, before any read; raised by mission 89a)

1. **Sampling clock.** The book sample clock is the canonical estimator's: the first capture in each UTC minute. Legs are
   (re)placed at each selected sample and rest until the next one; a selected capture less than 30 seconds after the
   previous one is skipped. Across missing samples a leg keeps resting for at most 5 minutes after the last sample; after
   that it is withdrawn (no exposure, no fills, no reward) until the next sample.
2. **Coverage exclusions (per date-market).** Expected span = local 00:00 to the event's local close on the event day, in
   minutes. **Book coverage** = expected minutes with at least one book capture for the event ÷ expected minutes.
   **Tape-gap minutes** = expected minutes inside disconnection or gap intervals recorded by the execution tape's own
   supervisor status/journal; a date-market with no such record for the day is excluded. A date-market is excluded if
   tape-gap minutes exceed 5% of the span or book coverage is below 90%. Every exclusion is listed with its reason.
3. **Reward terms over time.** For each minute, rate, reward minimum size and maximum spread come from the latest captured
   record for that condition at or before the minute: the per-condition reward record where one was captured, otherwise
   the reward configuration embedded in the captured market snapshot. A record older than 60 minutes is treated as missing.
   Minutes with missing terms are excluded from `R`'s numerator **and** their fills from its denominator, and are counted.
4. **Latency statistic.** Per E2/E3 event: `f = (mid(t_detect) − mid(t_obs)) / (mid(t_obs + 30 min) − mid(t_obs))`,
   signed, using the markout midpoint. `t_obs` is the source `observed_at`, `t_detect` our `current_captured_at_utc`.
   Events with a 30-minute move under 1 cent in absolute value are excluded and counted. The statistic is the median `f`
   with a date-clustered 90% bootstrap interval. "A reactive pull is useless" is concluded only if that interval's lower
   bound is at least 0.70.

**Default rule for any further gap.** An implementation choice that changes no estimand, threshold, horizon, window,
exclusion or data inclusion is made by the implementer: take the more conservative option (the one that lowers `R` or
raises measured adverse loss), document it in the report, and continue. Stop only for choices that would change one of
those.

## Clarification 4 (2026-09-23 afternoon, before any read; raised by mission 89a)

A minute whose reward terms are missing or older than 60 minutes (Clarification 3, point 3) is **excluded from the entire
simulated-quote panel**: no quote is placed, so there are no fills, no markouts, no exposure and no reward in that minute,
and it enters neither `R`, the concentration ratios, the net pull value nor the kill rule. Legs resting from the previous
sample are withdrawn at the start of such a minute. Excluded minutes are counted per date-market and per event class and
reported; if more than 20% of a date-market's expected minutes are excluded this way, that date-market is excluded
entirely and listed.

## Clarification 5 (2026-09-23 afternoon, before any read; raised by mission 89a)

The 20% rule in Clarification 4 counts **band-minutes**, the panel's own unit. For a date-market, the denominator is the sum
over its panel bands of expected minutes; the numerator is the band-minutes excluded for missing or stale terms. Panel bands
are the date-market's bands with at least one captured reward record or reward configuration on that date. Missing-term
exclusions otherwise act band by band (a minute excluded for one band does not remove other bands' same minute).

## Clarification 6 (2026-09-23 afternoon, before any read; raised by mission 89a)

**E3 source and rule.** The running maximum is built from the **routine hourly METAR stream as captured in our own market
snapshots** (the METAR report time and temperature fields the collectors store), keeping only reports whose minute falls in
the weather.gov WRH documented hourly filter — **:51-:59 for US NWS/FAA stations** — which is what the current Rules
resolve on ("Hourly Data") and what mission 86a implemented as `metar_hourly`. Temperatures are converted to the market's
native unit and rounded half-up with `weather.units`, as 86a did. **Toronto (CYYZ)** has no METAR source in our snapshots,
so it uses the captured WU history rows (the same fields, time and value), unfiltered. SPECI and non-routine reports do not
enter E3 (they remain in E2 through the observation triggers).

**E3 event time** is the source report time of the first report at which the running maximum exceeds the band's upper edge
(the band's YES is dead); open-top bands have no E3 event. The design's second clause ("the band becomes the only survivor")
is **dropped**: it cannot be observed without a forecast of the remaining rise — that is the T3 estimate mission 89b builds,
and it may enter a later, separately pre-registered study. Our detection time for the same report is recorded for the
latency sub-study.

## Clarification 7 (2026-09-23 afternoon, before any read; raised by mission 89a)

**Missing markouts are handled per horizon, removing loss and exposure together.** For each non-settlement horizon `h`
(1, 5, 30 minutes), a leg-minute belongs to the horizon-`h` panel only if a markout midpoint exists within the inherited
120-second tolerance of both its start + `h` and its end + `h`. Leg-minutes outside the panel contribute neither exposure
nor fills at that horizon. Inside the panel, a fill whose own markout at fill time + `h` is still missing removes that whole
leg-minute (its exposure and all its fills) from the horizon-`h` panel. Removed leg-minutes and fills are counted per
horizon, event class and date-market, and reported. Each horizon's panel stands alone: a leg-minute missing at +30 can still
count at +1 and +5. The settlement horizon keeps its existing rule (events without a settlement row leave the settlement
panel only). `R` is **not** horizon-restricted: it follows the frozen R rule over all panel leg-minutes (Clarifications 3-5
exclusions only). Net pull value uses the 30-minute panel for both the avoided adverse loss and the lost reward of the same
leg-minutes.

## Clarification 8 (2026-09-23 afternoon, before any read; raised by mission 89a)

Reward is scored jointly on both legs, so **net pull value uses the two-leg quote-minute as its unit**. A quote-minute enters
the net-pull-value panel only if **both** of its leg-minutes are in the 30-minute panel of Clarification 7; otherwise the
whole quote-minute (both legs' losses and its joint reward) leaves the net-pull-value panel, and is counted. Its lost reward
is the canonical joint reward of that quote-minute, never recomputed for one leg and never split between legs. The
concentration ratios keep the leg-minute unit of Clarification 7; `R` keeps the frozen R rule.

## Clarification 9 (2026-09-24 01:15 ET, before any scoring output; raised by the first production run)

The first production run (tip `947d96935`, 2026-09-24 00:48) refused before producing any estimate: a record in
`highest-temperature-in-seattle-on-august-16-2026/replay_inputs.jsonl` (line 123) is not valid JSON. A read-only scan of all
3,317 dry-run inputs (77.7 GiB) found **13 undecodable records in 13 files**: 11 zero-byte (NUL) blocks in
`order_books.jsonl.gz` on event days 2026-09-02/03 (one per market, consistent with a single interrupted write), one record
with an invalid control character, and the Seattle record. No other record failed.

**Rule:** a record that cannot be decoded (JSON error, NUL block, invalid control character, truncated line) is a
**capture defect, not data**. It is skipped; the interval from the last valid record before it to the next valid record
after it in the same file is a **coverage gap** for that market-date under the Clarification 3/4 coverage rules (its minutes
leave the panel and count toward the 20% band-minute rule), and each such record is counted in the exclusions table by
file, line and market-date. The run still refuses if more than 1% of a file's records fail, if a settlement-ledger row fails,
or if a failing record cannot be located to a market-date. No estimand, threshold or other exclusion changes.

## Clarification 10 (2026-09-24, before any scoring output; recorded from the 89c handback)

For an undecodable record under Clarification 9, when there is no valid record before it (or after it) in the same file, the
missing neighbour is replaced by the **event-day boundary** (the start or end of that market-date's window). The owner
answered this in the 89c workstation session; it is recorded here so the rule lives in the pre-registration, not only in the
report. A decoded neighbour without an interpretable time still refuses the run.

## Clarification 11 (2026-09-25, mission 100b; before any 88a-backed scoring)

**Data inclusion changes:** captured per-condition reward terms may also come from 88a's sealed
`data/maker_evidence/<UTC-day>/<hh>-<seg>/reward-<hash>.jsonl.gz` journals. Decode each response's
`body_utf8` JSON `data[]`, match its `event_slug` and condition identity, and resolve `payload_ref`
against the named file's **uncompressed** byte offset within the sealed segment. A deduplicated
unchanged response is a new observation at its own outer `captured_at_utc`, not at the stored body's
older capture time. Never read an unsealed segment.

These are per-condition captured records under Clarification 3.3, with the same precedence and the
same at-or-before-minute, **60-minute freshness** rule. Rate, minimum size and maximum spread feed
the existing terms parser; no daily snapshot fallback is added. All analysis, panel exclusions,
estimands, thresholds, horizons, windows and the frozen date range remain unchanged. This addition
does not authorize scoring later dates: 88a began after the frozen panel ended, so a future rerun
needs a separately recorded date-range decision as well as sufficient captured dates.

Implementation plans overlapping UTC-hour reward files (including the one-hour lookback) and their
seals, streams bounded gzip records into each event's SQLite store, and filters by event/condition.
Shared malformed evidence that cannot be located to a market-date still refuses under Clarification 9.
`--maker-evidence-root` selects an offline capture root; by default it is `maker_evidence` beside the
snapshot root. `--dry-run` lists files and sizes without opening journal or manifest content.
Mission 100b verifies only synthetic fixtures; the production agent owns the later leased rerun
after about ten UTC dates of capture (earliest approximately 2026-10-05).
