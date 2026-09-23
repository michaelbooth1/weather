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
