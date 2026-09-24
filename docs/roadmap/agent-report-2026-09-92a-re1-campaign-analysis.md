# Mission 92a — RE-1 campaign analysis

**DESCRIPTIVE / SELECTION CHANGE PROPOSED: prefer existing two-sided depth over a near-monopoly reward estimate. No profitable duration or paid reward is proved.** The copy has nine attempts, six with minute samples, and four fills, not only the three fills described in the handoff. A proposed 75-share minimum displayed depth on each side, with at least one local calendar day ahead, retains sessions 1 and 6 and excludes 2–5 and 7–9. It would also discard the longest session, Miami (88 samples), so it is a next-experiment rule, not a validated fill predictor.

## Authority and scope

Owner request on 2026-09-24: execute the 92a handoff from freshly fetched
`origin/codex/reward-test-attended-handoff-20260921`, tip
`5252210ebfccfcd8703105dca7bdf5c0edc34499`, using the owner-made
`C:\Users\Michael\Documents\re1-analysis-copy-20260924`. Owner states no RE-1
session is running. Research branch `codex/re1-campaign-analysis-20260924`
starts at fetched `origin/master` `198f7ccbcd8e80271693462425582097d22b298b`.
The reserved-window contract on that base says **NONE RESERVED**.

The input contains session-1 through session-9. Attempts 2, 3 and 7 have no
minute samples; 3 posted no order and 2 posted one. The other six supply 203
minute samples. There are six selected cities, seven conditions and three
target dates; fills cover four cities and two target dates, on two UTC trade
dates. This is too little independent support for statistical inference. No
p-values, confidence intervals, fitted model or claim of causal separation
is supplied; any future inference must cluster by both date and market.

## Findings and recommendation

The recorded minute-integrated model is much closer to accrual than the
selection-time six-hour extrapolation suggests. Session 1 accrued 0.117375
against 0.105386/0.125205 modelled; session 5's observed increment is 0.438020
against 0.351920/0.447362; session 6 accrued 0.376038 against
0.330020/0.347487. These are **accrual comparisons, not paid/model ratios**.
Session 5 begins with 0.013563 already accrued by session 4 on the same
condition/day. Adding both final balances would count that amount twice.
The latest captured condition balances for September 24 sum to 1.632346,
at different observation times; this is neither a synchronous account total
nor evidence of a wallet credit. Every captured accrual response says
`payment_verified=false`. The owner's observed 1.40 is contextual evidence,
not a figure reproduced by these journals. Session 8's missing earnings row
after two samples does not establish NOT_PAID.

Competition changes rapidly after posting: the selected share halves within
4.23 minutes in NYC, 2.25 in Miami session 5, and 2.25 in Atlanta session 6.
Miami falls from selected 95.4% to 3.55% at its last minute; Atlanta's
day-ahead session falls from 63.1% to 4.07%. Midpoints can remain nearly
unchanged while this happens. The per-minute competition/own-Q ratio in the
tables is inferred from `1/share_many - 1`; it is not an absolute quantity of
new orders or proof of a particular competitor arriving. Own Q changes with
the midpoint and re-quotes. Displayed books cannot identify maker grouping.

Use this concrete **prospective experimental selection rule** for review:

1. Require at least 75 displayed shares on each side of the YES book within
   the reward maximum spread of the adjusted midpoint (at least the proposed
   per-leg size if that exceeds 75). Do not add the complementary NO book;
   it represents the same two sides. Keep at least one local calendar day
   ahead. The empirical gap is weak-side depth at most 74.84 for excluded
   attempts versus at least 85 for the two retained attempts. **75 is an
   exploratory treatment-sized boundary, not an estimated optimum.**
2. Report competing Q below 10 as a thin-book diagnostic. Here Q>=10 produces
   exactly the same partition as the depth rule (excluded maximum 4.5551,
   retained minimum 19.4583); the sample cannot justify treating them as two
   independent predictors. Among the handoff's numbered sessions 1–6 this
   excludes 2–5; among all nine it also excludes 7–9. It retains 98 of 203
   samples and one of four fills. It loses 105 samples, including Miami's 88.
3. Before selection, capture a ten-minute public midpoint/depth window and
   flag a midpoint range above one cent for review. This is an instrumentation
   proposal with **no retrospective pass count**: the copy does not contain
   that pre-pick window. The first five *post-start* samples barely move even
   in the fill sessions, so they do not validate a stability screen.
4. Reassess reward expectations after ten elapsed minutes using the observed
   share path and actual daily accrual, rather than extending the selected
   share over six hours. Preserve the approved session ceiling and first-fill
   handling. No fixed profitable holding duration is identified: observed
   fills arrive at 1.83, 12.25, 41.99 and 87.22 minutes; the 56-minute non-fill
   session was censored by a heartbeat failure. A ten-minute checkpoint would
   already be too late for session 8. New duration or stop rules must be a
   prospective experiment, not a claim that these four times optimize one.

Four unique taker wallets match the four terminal trades by transaction hash
in the public trade response; none recurs **among these four fills**. Identifiers
are truncated to eight characters. Public history gives Miami a -0.085/share
five- and thirty-minute price mark (-6.375 on 75 shares), versus +0.015/share
for NYC and Atlanta at five minutes and 0 for Chicago. This does not turn
every quick fill into an informed loss: Atlanta's short-horizon mark is
positive. All settlements are unresolved in the captured market responses.

## Measurement and table definitions

The reducer reads only the five allowlisted filenames under each session.
It verifies every prediction's journal SHA-256, minute count, terminal model
sum and fill flag, matches maker legs to the session's own order IDs, and
deduplicates by trade/order identity. It hashes all inputs before and after
analysis. MATCHED/MINED user-stream updates are not extra fills. Historical
`evidence_complete`, cleanup and inventory flags are preserved in the CSV;
this analysis does not retrospectively repair session receipts.

`minutes` is the recorder's sample count, **not measured continuous wall-clock
exposure**. First samples occur about 15 seconds after opening; interrupted
polls can leave gaps. `half_pick_minutes` is elapsed time from journal open to
the first sample at or below half the selected share. `half_first_minutes`
uses the first recorded share and measures from that sample. NA means absent
or not reached before censoring. Depth counts all displayed sizes in range,
not just reward-qualifying orders; competing Q is the recorded model's Q.
`day_ahead` uses market-local pick date, so the evening picks in sessions 1–5
are **T+2**, despite their UTC trade date being one day before the target.

The accrual comparison subtracts the first captured cumulative balance from
the final one. First reads occur after posting, so increments have imperfect
endpoint alignment with the model; venue polling and credit delays also
remain. Zero with no matching earnings row means **not observed**. Venue
percentage is retained in `accrual.csv`, not treated as an instantaneous
model share.

The copied book snapshots end at cleanup. True post-fill bid/ask midpoints
are therefore unavailable. Read-only `prices-history` gives a **sampled price
proxy**, kept separate from copied two-sided book mids; it cannot backfill an
exact book path. This distinction follows the venue's
[research API guide](https://institute.polymarket.com/data) and
[display-price rule](https://help.polymarket.com/en/articles/13364488-how-are-prices-calculated),
which permits a last-trade fallback for wide spreads. Nearest samples must
be within 90 seconds; signed offsets are retained. Markout is held-token
price minus our BUY price, gross of any unobserved charges. A negative-horizon
row describes the pre-fill path, not a realized return. The complete sampled
-30 to +120 minute path is in `price_path.csv`. At this first read (~15:54Z),
Atlanta +120 and Chicago +30/+120 are future horizons, hence NA, not zeros.

The 89b station minutes are pinned to `observation_clock.py` at
`d059cc78753757cec6cc1a6ba34cbe03a28f508c`; they are modal report times, not
availability receipts. All four fills occur 17.6–52.8 minutes after the prior
modal METAR minute. NBM 01/07/13/19Z is a cycle clock only. For GFS/HRRR the
script performs HEAD requests for representative f000 objects in the
[NOAA GFS](https://registry.opendata.aws/noaa-gfs-bdp-pds/) and
[NOAA HRRR](https://registry.opendata.aws/noaa-hrrr-pds/) public mirrors.
`Last-Modified` is a mirror publication proxy for that object, **not proof of
when all forecast hours, the relevant station forecast, or a taker received
new information**. Positive minutes-before-fill means the object preceded it.
Chicago's fill follows the 12Z GFS f000 object by 9.98 minutes; Miami follows
00Z GFS by 35.88 and 03Z HRRR by 19.42. NYC precedes the 00Z GFS object;
Atlanta precedes 12Z GFS. No information cause is identified. Actual SPECI,
NBM publication receipts and forecast content changes were not measured.

<!-- BEGIN REBUILT TABLES -->

## sessions

| session | market | day_ahead | minutes | posts | stop | P_many | P_single | venue_final_cumulative |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| session-1 | nyc | 2 | 42 | 2 | fill | 0.1054 | 0.1252 | 0.1174 |
| session-2 | los-angeles | 2 | 0 | 1 | fresh_ask | 0.0000 | 0.0000 | 0 |
| session-3 | san-francisco | 2 | 0 | 0 | fresh_ask_before_post | 0.0000 | 0.0000 | 0 |
| session-4 | miami | 2 | 2 | 2 | cancel_not_terminal | 0.0304 | 0.0368 | 0.0136 |
| session-5 | miami | 2 | 88 | 3 | fill | 0.3519 | 0.4474 | 0.4516 |
| session-6 | atlanta | 2 | 56 | 2 | heartbeat_stale | 0.3300 | 0.3475 | 0.3760 |
| session-7 | atlanta | 0 | 0 | 2 | exception | 0.0000 | 0.0000 | 0 |
| session-8 | atlanta | 0 | 2 | 2 | fill | 0.1064 | 0.1090 | 0 |
| session-9 | chicago | 0 | 13 | 2 | fill | 0.8719 | 0.9038 | 0.8047 |

## selection_features

| session | Q_pick | bid_depth | ask_depth | spread | pick_local | first5_mid_range |
| --- | --- | --- | --- | --- | --- | --- |
| session-1 | 40.1558 | 85.0000 | 264.9300 | 0.0300 | 2026-09-22T21:47:22.813880-04:00 | 0.0000 |
| session-2 | 0.0000 | 10.0000 | 14.0100 | 0.0600 | 2026-09-23T18:46:40.992539-07:00 | NA |
| session-3 | 1.6988 | 70.1700 | 38.8100 | 0.0600 | 2026-09-23T19:02:54.127873-07:00 | NA |
| session-4 | 0.0000 | 15.0000 | 15.0000 | 0.0300 | 2026-09-23T22:11:45.813021-04:00 | 0.0000 |
| session-5 | 1.6047 | 35.0000 | 107.7900 | 0.0200 | 2026-09-23T22:42:20.421167-04:00 | 0.0000 |
| session-6 | 19.4583 | 477.0700 | 397.7900 | 0.0600 | 2026-09-24T09:34:17.896838-04:00 | 0.0050 |
| session-7 | 2.9272 | 35.0000 | 53.8000 | 0.0500 | 2026-09-24T10:49:22.053018-04:00 | NA |
| session-8 | 4.5551 | 20.0000 | 41.6200 | 0.0400 | 2026-09-24T11:08:44.555747-04:00 | 0.0000 |
| session-9 | 2.1630 | 74.8400 | 63.3000 | 0.0500 | 2026-09-24T10:29:19.277679-05:00 | 0.0000 |

## share_decay

| session | share_pick | share_first | share_last | half_pick_minutes | half_first_minutes |
| --- | --- | --- | --- | --- | --- |
| session-1 | 0.1812 | 0.1641 | 0.0481 | 4.2273 | 6.9819 |
| session-2 | 1.0000 | NA | NA | NA | NA |
| session-3 | 0.9515 | NA | NA | NA | NA |
| session-4 | 1.0000 | 0.3064 | 0.5882 | 0.2558 | NA |
| session-5 | 0.9541 | 0.5634 | 0.0355 | 2.2538 | 4.9824 |
| session-6 | 0.6314 | 0.6374 | 0.0407 | 2.2465 | 1.9882 |
| session-7 | 0.8877 | NA | NA | NA | NA |
| session-8 | 0.8798 | 0.8798 | 0.8615 | NA | NA |
| session-9 | 0.9391 | 0.9747 | 0.4232 | 12.2126 | 11.9837 |

## share_checkpoints

| session | sample | elapsed_minutes | share_many | Q_competitor_over_own | mid |
| --- | --- | --- | --- | --- | --- |
| session-1 | 1 | 0.2342 | 0.1641 | 5.0934 | 0.5050 |
| session-1 | 2 | 1.2312 | 0.1118 | 7.9481 | 0.5050 |
| session-1 | 5 | 4.2273 | 0.0839 | 10.9203 | 0.5050 |
| session-1 | 10 | 9.2263 | 0.0615 | 15.2541 | 0.5050 |
| session-1 | 20 | 19.2210 | 0.0668 | 13.9707 | 0.5050 |
| session-1 | 30 | 29.2255 | 0.0619 | 15.1564 | 0.5050 |
| session-4 | 1 | 0.2558 | 0.3064 | 2.2632 | 0.3650 |
| session-4 | 2 | 1.2502 | 0.5882 | 0.7000 | 0.3650 |
| session-5 | 1 | 0.2574 | 0.5634 | 0.7748 | 0.3700 |
| session-5 | 2 | 1.2532 | 0.6109 | 0.6370 | 0.3700 |
| session-5 | 5 | 4.2436 | 0.3317 | 2.0148 | 0.3700 |
| session-5 | 10 | 9.2457 | 0.2303 | 3.3425 | 0.3700 |
| session-5 | 20 | 19.2504 | 0.2051 | 3.8759 | 0.3700 |
| session-5 | 30 | 29.2459 | 0.2453 | 3.0759 | 0.3700 |
| session-5 | 60 | 59.2432 | 0.0840 | 10.9095 | 0.3700 |
| session-5 | 88 | 87.2424 | 0.0355 | 27.1684 | 0.3650 |
| session-6 | 1 | 0.2583 | 0.6374 | 0.5688 | 0.4500 |
| session-6 | 2 | 1.2530 | 0.3361 | 1.9756 | 0.4450 |
| session-6 | 5 | 5.2433 | 0.1701 | 4.8790 | 0.4450 |
| session-6 | 10 | 10.2462 | 0.1778 | 4.6243 | 0.4450 |
| session-6 | 20 | 20.2492 | 0.1880 | 4.3203 | 0.4450 |
| session-6 | 30 | 30.2507 | 0.1740 | 4.7459 | 0.4450 |
| session-8 | 1 | 0.2480 | 0.8798 | 0.1367 | 0.3950 |
| session-8 | 2 | 1.2413 | 0.8615 | 0.1607 | 0.3950 |
| session-9 | 1 | 0.2289 | 0.9747 | 0.0260 | 0.5850 |
| session-9 | 2 | 1.2250 | 0.9747 | 0.0260 | 0.5850 |
| session-9 | 5 | 4.2188 | 0.9031 | 0.1073 | 0.5850 |
| session-9 | 10 | 9.2216 | 0.9031 | 0.1073 | 0.5850 |

## accrual_comparison

| session | venue_observed_delta | delta_over_P_many | delta_over_P_single |
| --- | --- | --- | --- |
| session-1 | 0.1174 | 1.1138 | 0.9375 |
| session-2 | 0 | NA | NA |
| session-3 | 0 | NA | NA |
| session-4 | 0.0136 | 0.4455 | 0.3689 |
| session-5 | 0.4380 | 1.2447 | 0.9791 |
| session-6 | 0.3760 | 1.1394 | 1.0822 |
| session-7 | 0 | NA | NA |
| session-8 | 0 | 0.0000 | 0.0000 |
| session-9 | 0.8047 | 0.9230 | 0.8904 |

## fills

| session | utc | outcome | price | size | minutes_to_fill | taker_wallet_prefix | settlement_markout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| session-1 | 2026-09-23T02:30:06Z | No | 0.4800 | 5.5700 | 41.9894 | 0x4248a6 | NA |
| session-5 | 2026-09-24T04:10:37Z | Yes | 0.3500 | 75.0000 | 87.2190 | 0xfd557e | NA |
| session-8 | 2026-09-24T15:12:59Z | No | 0.5900 | 18.4146 | 1.8341 | 0x0484bf | NA |
| session-9 | 2026-09-24T15:43:48Z | No | 0.4000 | 10.0000 | 12.2523 | 0x8aa6da | NA |

## markouts

| session | horizon_minutes | yes_mid | yes_history_price | history_offset_seconds | sampled_price_markout_per_share |
| --- | --- | --- | --- | --- | --- |
| session-1 | -30 | 0.5050 | 0.5050 | 14.0000 | 0.0150 |
| session-1 | 0 | 0.5050 | 0.5050 | 12.0000 | 0.0150 |
| session-1 | 5 | NA | 0.5050 | 7.0000 | 0.0150 |
| session-1 | 30 | NA | 0.5050 | 16.0000 | 0.0150 |
| session-1 | 120 | NA | 0.5150 | 9.0000 | 0.0050 |
| session-5 | -30 | 0.3700 | 0.3700 | 46.0000 | 0.0200 |
| session-5 | 0 | 0.3650 | 0.3650 | -20.0000 | 0.0150 |
| session-5 | 5 | NA | 0.2650 | -19.0000 | -0.0850 |
| session-5 | 30 | NA | 0.2650 | -7.0000 | -0.0850 |
| session-5 | 120 | NA | 0.3050 | -12.0000 | -0.0450 |
| session-8 | -30 | NA | 0.3600 | 16.0000 | 0.0500 |
| session-8 | 0 | 0.3950 | 0.4000 | 16.0000 | 0.0100 |
| session-8 | 5 | NA | 0.3950 | 16.0000 | 0.0150 |
| session-8 | 30 | NA | 0.3900 | 17.0000 | 0.0200 |
| session-8 | 120 | NA | NA | NA | NA |
| session-9 | -30 | NA | 0.5450 | 26.0000 | 0.0550 |
| session-9 | 0 | 0.5900 | 0.6100 | 26.0000 | -0.0100 |
| session-9 | 5 | NA | 0.6000 | 26.0000 | 0.0000 |
| session-9 | 30 | NA | NA | NA | NA |
| session-9 | 120 | NA | NA | NA | NA |

## information_clock

| session | station | METAR_lag_minutes | prior_NBM_cycle | NBM_lag_minutes |
| --- | --- | --- | --- | --- |
| session-1 | KLGA | 39.1000 | 2026-09-23T01:00:00+00:00 | 90.1000 |
| session-5 | KMIA | 17.6167 | 2026-09-24T01:00:00+00:00 | 190.6167 |
| session-8 | KATL | 20.9833 | 2026-09-24T13:00:00+00:00 | 132.9833 |
| session-9 | KORD | 52.8000 | 2026-09-24T13:00:00+00:00 | 163.8000 |

## publications

| session | model | cycle_utc | mirror_last_modified_utc | minutes_before_fill |
| --- | --- | --- | --- | --- |
| session-1 | gfs | 2026-09-23T00:00:00+00:00 | 2026-09-23T03:35:06+00:00 | -65.0000 |
| session-1 | hrrr | 2026-09-23T02:00:00+00:00 | 2026-09-23T02:51:40+00:00 | -21.5667 |
| session-1 | hrrr | 2026-09-23T01:00:00+00:00 | 2026-09-23T01:52:12+00:00 | 37.9000 |
| session-1 | hrrr | 2026-09-23T00:00:00+00:00 | 2026-09-23T00:52:46+00:00 | 97.3333 |
| session-5 | gfs | 2026-09-24T00:00:00+00:00 | 2026-09-24T03:34:44+00:00 | 35.8833 |
| session-5 | hrrr | 2026-09-24T04:00:00+00:00 | 2026-09-24T04:52:04+00:00 | -41.4500 |
| session-5 | hrrr | 2026-09-24T03:00:00+00:00 | 2026-09-24T03:51:12+00:00 | 19.4167 |
| session-5 | hrrr | 2026-09-24T02:00:00+00:00 | 2026-09-24T02:51:09+00:00 | 79.4667 |
| session-8 | gfs | 2026-09-24T12:00:00+00:00 | 2026-09-24T15:33:49+00:00 | -20.8333 |
| session-8 | hrrr | 2026-09-24T15:00:00+00:00 | 2026-09-24T15:50:48+00:00 | -37.8167 |
| session-8 | hrrr | 2026-09-24T14:00:00+00:00 | 2026-09-24T14:50:44+00:00 | 22.2500 |
| session-8 | hrrr | 2026-09-24T13:00:00+00:00 | 2026-09-24T13:50:40+00:00 | 82.3167 |
| session-9 | gfs | 2026-09-24T12:00:00+00:00 | 2026-09-24T15:33:49+00:00 | 9.9833 |
| session-9 | hrrr | 2026-09-24T15:00:00+00:00 | 2026-09-24T15:50:48+00:00 | -7.0000 |
| session-9 | hrrr | 2026-09-24T14:00:00+00:00 | 2026-09-24T14:50:44+00:00 | 53.0667 |
| session-9 | hrrr | 2026-09-24T13:00:00+00:00 | 2026-09-24T13:50:40+00:00 | 113.1333 |

## thresholds

| rule | keep | exclude | fill_sessions_kept | minute_samples_kept |
| --- | --- | --- | --- | --- |
| Q>=10 | session-1, session-6 | session-2, session-3, session-4, session-5, session-7, session-8, session-9 | 1 | 98 |
| depth>=75_each | session-1, session-6 | session-2, session-3, session-4, session-5, session-7, session-8, session-9 | 1 | 98 |
| day_ahead>=1 | session-1, session-2, session-3, session-4, session-5, session-6 | session-7, session-8, session-9 | 2 | 188 |
| Q>=10_and_day_ahead>=1 | session-1, session-6 | session-2, session-3, session-4, session-5, session-7, session-8, session-9 | 1 | 98 |

<!-- END REBUILT TABLES -->

## Reproduction and retained evidence

Implementation commit: `4c87df390309ce99164de0b2bd1f1c4193ffbdd0` on
`codex/re1-campaign-analysis-20260924`. The report is a following commit;
`git rev-parse origin/codex/re1-campaign-analysis-20260924` identifies its
published tip. Handoff tip: `5252210ebfccfcd8703105dca7bdf5c0edc34499`.

From the branch checkout, with the project interpreter, using absolute input
and output paths appropriate to the host:

```powershell
& $projectPython tools/re1_campaign_analysis_20260924.py `
  --copy-root $ownerAnalysisCopy --output $analysisOutput --fetch-public
```

`$ownerAnalysisCopy` is the exact copy named above on this workstation, never
the live campaign. `$analysisOutput` is a new scratch directory outside it.
The script refuses input roots without `analysis-copy` in their name, accepts
at most twenty numbered session folders and at most 16 MiB per allowlisted
file, and rechecks input hashes on completion. It imports only the standard
library. Public requests are credential-free GET/HEAD, capped at 8 MiB each,
with a 25-second timeout and at least 1.05 seconds between starts per host.
No GRIB body is downloaded.

For exact reproduction, transfer the owner copy and the retained public
response cache together. Restore the cache as `$analysisOutput/public` and
**omit `--fetch-public`**. This reproduces the frozen tables without network
access. Re-fetching into a new directory is a later evidence snapshot, not an
exact replay: future horizons and settlement responses may then differ.
The portable evidence bundle is `scratch/re1-92a-evidence-20260924.zip` in
this worktree. It contains generated CSV/JSON/Markdown and public response
cache only; it does not contain the private campaign copy. `input_manifest.csv`
binds all 40 consumed source files. Bundle SHA-256:
`61a986980e143faac2d0bbc300eae62ad22a4e7d43d9a99f4ad5979a4be0abf8`.
Workstation scratch paths are not presumed
to exist on production; the owner must transfer the bundle before exact replay.

Verification: two offline reductions after the public fetch completed with
nine sessions, four deduplicated own-order fills and 203 minute samples.
All prediction/journal hashes, sample counts, final cumulative model values,
fill flags and input before/after hashes passed. `git diff --check` passed.
The table block above is the reducer's `tables.md` output. No paid/model `k`,
settlement P&L, optimal duration, exact post-fill midpoint, or causal weather
trigger has been inferred from missing evidence.

## Per-file roll disposition and handback

- `tools/re1_campaign_analysis_20260924.py`: standalone research script,
  standard-library imports only, no application/capture import added. Expected
  roll-free; the production owner must obtain the binding per-closure verdict
  with `scripts/ops/roll_verdict.ps1 -Branch codex/re1-campaign-analysis-20260924`.
  No current production closure was read from the frozen workstation mirror.
- This report: Markdown, roll-free under the delegation contract.

No production or mirror read/write, live-root access, credential access,
RE-1 code change, live command, venue mutation, capture, Scheduler registration,
restart, merge, training or promotion was performed. The only exchange calls
were the explicitly authorized public historical reads. The owner retains
production qualification, adoption and any next-session decision.
