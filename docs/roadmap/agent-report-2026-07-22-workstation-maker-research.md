# Agent Report - 2026-07-22 Workstation Maker Research

## Outcome

**STOP: NO QUOTING POLICY SURVIVED THE LOCKED HOLDOUT.** The tune-supported
`one_tick_inside` policy lost `-0.857855` USDC per fleet date versus the
`at_touch` control on the untouched July 2-11 holdout (fleet-date bootstrap
95% CI `[-1.754664, -0.144149]`; 4 positive / 6 negative dates). Its 52
30-minute-complete fills lost `-8.525664` USDC after modeled flattening cost.
The negative interval excludes zero.

The approved recorded quote intents provide no countervailing evidence. The
three primary-forward folders contain 24,207 permitted rows and 48,414 quote
legs, but only three market-days overlap the validated WebSocket window and no
recorded quote produced an explicit strict-through fill. Operator drills,
named proofs, and post-settlement proofs remain separate and also produced zero
such fills.

This is evidence against tightening one tick under the tested assumptions. It
does not authorize a serving change, promotion, live quoting, or live capital.

## Provenance and frozen inputs

- Git branch: `codex/workstation-research-2026-07-22`.
- Starting revision: `99c0616419ce75a402e5b752fc87b4f9bebec54c`.
- Read-only mirror root: the explicitly supplied repository-local, ignored
  `data/` mirror. The exact resolved runtime root remains recorded in the
  input manifest; this durable report keeps paths repository-relative.
- Validated book-plus-WS window: 2026-06-21 through 2026-07-11, 21 complete
  fleet dates, 12 markets per date, 252 market-days.
- Explicit books-only window: 2026-07-12 through 2026-07-21, 10 complete fleet
  dates, 12 markets per date, 120 market-days. These folders were excluded
  from fill and toxicity claims.
- Maker runs: the 12 explicitly approved non-quarantine folders recorded in
  `scratch/workstation-research-output/workstream_d/maker/input_manifest.json`:
  3 primary-forward, 5 operator-drill, 1 named-operator-proof, and 3
  post-settlement-proof folders. No discovered folder or quarantine folder was
  admitted.
- Semantic input-manifest hash:
  `7bb52fa0e29c56d6995abb199e4d7b39683c3537163d8bac3cc15cac9da0cd2b`.

Key frozen artifact hashes:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `coverage/clob_coverage_audit.json` | 475,856 | `2e29baa3c9b51cf901312853e26dd1df43c4163669bbe2d0d8a9a2024cc000d2` |
| `input_manifest.json` | 438,899 | `e6f4ea734a8431d7d6ba512df3127cbf8917a117f85016a94a821cbc139af59c` |
| `maker_research_results.json` | 301,151 | `98809bda82206a6f0083ca24dd979f8366054939e3e5f6405766787e0a0404c6` |
| `maker_research_report.md` | 8,067 | `b9d1a68d6b9143b68d6c292a897a74d590c05d6b0cad59bb5b98464a3c59c7f8` |
| `market_day_reconstruction.csv` | 61,263 | `5f6ea65b6439c1e3f17aee2b678184c2256393e338393ae4105cf9235a66b979` |
| `explicit_trade_markouts.csv` | 62,686 | `f937f7e1174dbd6878a14a6b983b5c42e25b24c2eeb7babcec6373233d354309` |
| `synthetic_policy_fills.csv` | 77,383 | `cc6fad453d6e0fe6c04276fe0b1cdd68c31d0589646b7a844b260a3f039aad1b` |
| `synthetic_policy_market_days.csv` | 103,962 | `146cbaf930af7c8cf142af958a0dfb990aaa2f049f40aa983fe6f2625797220d` |
| `quote_run_market_days.csv` | 35,476 | `4599cf5939ed65c5333fc4ac0cf6eac36dbb96f70edf2fcb7a2e9d1040d28786` |

The input manifest binds the coverage audit by content hash, binds every maker
run's config, summary, and quote-intent file by content hash, and records path,
size, and mtime for each admitted snapshot tape. Root `data/` was never an
output target; the harness resolves and rejects any output inside the explicit
read-only root, including symlink/junction aliases.

## Exact trade and fill semantics

The normalized protocol tape contained 4,480,139 rows:

| Event type | Rows | Interpretation |
| --- | ---: | --- |
| `book` | 3,725,223 | book state only |
| `price_change` | 754,502 | book update; never a trade, fill, or toxicity row |
| `last_trade_price` | 411 | the only admissible trade event |
| `tick_size_change` | 3 | market metadata only |

Validation found zero unknown event types, zero event-slug binding errors, and
zero missing receive timestamps. All 411 explicit trade rows had a supported
side; 372 also carried positive recorded size. The implementation does not use
the legacy `load_trade_like_rows` or `load_trade_rows` paths because those
loaders can admit priced `price_change` rows.

For markouts, an explicit `SELL` denotes a passive `YES_BID`; an explicit
`BUY` denotes a passive `YES_ASK`. A trade must bind to a token and prior book.
The mark is the first midpoint at or after +1, +5, or +30 minutes, with at most
five minutes of mark lag. Missing future marks remain missing rather than being
zero-filled.

For conservative fills, the event must additionally carry positive recorded
size and occur while a quote is active. A bid fills only when the explicit sell
price is strictly below the quote; an ask fills only when the explicit buy
price is strictly above it. Touches do not fill. Filled size is capped by both
recorded trade size and remaining displayed quote size. This strict-through
rule removes optimistic touch/queue assumptions, but it is still an offline
bound rather than a queue reconstruction.

## Coverage, spread, depth, and toxicity

The reconstruction loads and releases one market-day folder at a time. It
matched 208 explicit trades to books for at least one markout calculation: 108
in tune and 100 in holdout.

| Split | Fleet dates | Market-days | Equal-date mean spread | Top depth | Depth within 1% |
| --- | ---: | ---: | ---: | ---: | ---: |
| Tune | 11 | 132 | 0.018261 | 2,232.34 | 2,292.72 |
| Holdout | 10 | 120 | 0.020360 | 2,150.07 | 2,194.60 |

Fleet-date-clustered passive-side markouts were mildly positive at one and
five minutes in tune, but did not generalize at 30 minutes. Holdout 30-minute
markout averaged `-0.012801` per share across 10 supported dates, with 95% CI
`[-0.040808, 0.012264]`. Six dates were positive and four negative; the loss
was magnitude-driven and the interval still includes zero. This is not enough
to claim fleet-wide toxicity independently of a concrete quote policy.

## Predeclared tune and untouched holdout

The split was frozen before policy scoring:

- tune: 2026-06-21 through 2026-07-01 (11 fleet dates, 132 market-days);
- holdout: 2026-07-02 through 2026-07-11 (10 fleet dates, 120 market-days).

The fixed policy grid used 60-second quotes and five displayed shares:

- `at_touch`: quote the observed best bid/ask;
- `one_tick_wider`: move one tick away from the touch;
- `one_tick_inside`: improve the touch by one tick without crossing.

Selection used net 30-minute markout less the modeled flattening fee. It did
not use theoretical rebates or liquidity rewards.

| Tune variant vs `at_touch` | 30m fills | Active dates | Mean delta / fleet date | 95% CI | Sign | Disposition |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `one_tick_wider` | 4 | 4 | +0.006738 | `[+0.000476, +0.016446]` | 4 / 0 / 7 | blocked: fewer than 10 complete fills |
| `one_tick_inside` | 43 | 7 | +0.103700 | `[-0.204389, +0.521049]` | 2 / 5 / 4 | selected by positive tune mean and minimum support |

Only `one_tick_inside` entered the holdout. It generated 64 strict-through
fills, of which 52 had complete 30-minute marks:

| Holdout policy | Fills | 30m fills | Gross spread | 30m markout | Adverse loss | All-fill flatten | Net-basis flatten | Net | Theoretical rebate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `at_touch` | 4 | 3 | 0.497500 | 0.155000 | 0.075000 | 0.155588 | 0.102113 | 0.052887 | 0.038897 |
| `one_tick_inside` | 64 | 52 | 3.409466 | -7.368857 | 9.471454 | 1.342706 | 1.156807 | -8.525664 | 0.335676 |

These columns must not all be added together: future-midpoint markout already
contains entry spread. Net is complete-case: it equals 30-minute markout minus
the flattening cost for the 30-minute-complete fills (`0.155000 - 0.102113 =
0.052887` for `at_touch`; `-7.368857 - 1.156807 = -8.525664` after rounding
for `one_tick_inside`). All-fill flattening cost includes fills without a
30-minute mark and therefore is not the net basis. The theoretical rebate is a
stale repository-default counterfactual, not an observed payout, and was
excluded from selection. Even adding it mechanically would not reverse the
holdout loss.

Post-hoc diagnosis, not a new tuning surface, located the largest holdout
losses in Houston (`-4.101400` USDC), San Francisco (`-2.048070`), Los Angeles
(`-1.097896`), NYC (`-0.840698`), and Denver (`-0.778244`). This concentration
is useful for future preregistration. A second post-hoc split found that
passive `YES_ASK` / explicit `BUY` fills accounted for 36 complete fills and
`-7.437673` USDC net, while passive `YES_BID` / explicit `SELL` fills accounted
for 16 and `-1.087991` USDC. Both sides lost, so the imbalance is diagnostic,
not a same-holdout rescue or retuning surface.

## Recorded quote-run reconciliation

Here a run-market-day row is one admitted run x market x target date. The
unique-market-day columns collapse repeated runs for the same market and date.

| Run class | Runs | Run-market-day rows | Unique market-days | WS-covered run-market-day rows | Unique WS-covered market-days | Permitted rows | Legs | Explicit strict-through fills |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Primary forward | 3 | 27 | 27 | 3 | 3 | 24,207 | 48,414 | 0 |
| Operator drill | 5 | 51 | 36 | 39 | 24 | 4,073 | 8,146 | 0 |
| Named operator proof | 1 | 12 | 12 | 12 | 12 | 3 | 6 | 0 |
| Post-settlement proof | 3 | 36 | 24 | 12 | 12 | 301 | 602 | 0 |

The recorded primary policy has no independent locked holdout and is blocked.
Drills and proofs cannot substitute for forward evidence.

The June 19-22 legacy paper report recorded 33 conservative fills over 11,980
quote legs and reported an open gate. Those counts are not comparable to the
current event-typed result: the legacy tape loader did not require
`event_type=last_trade_price`, so priced book updates were admissible. This
does not prove every historical fill was false; it means that report cannot
establish fill or toxicity evidence under the present contract. The July 21
standard report already recorded zero fills and blocked both fill evidence and
exchange economics.

## Limitations and no-live disposition

- The explicit trade tape is sparse: 411 trade events versus 754,502 price
  changes, and only 372 trades have positive size.
- Strict-through avoids optimistic touch fills but does not reconstruct queue
  position, between-capture cancellation, latency, inventory, capital, hedge,
  or settlement P&L.
- The 120 July 12-21 books-only market-days support no fill or adverse-selection
  inference.
- Actual rebate and liquidity-reward payouts are unavailable. No realized
  incentive claim is made.
- Recorded primary quote evidence overlaps only three validated market-days and
  has no holdout.
- A positive mean with inadequate fills, too few active dates, or an interval
  touching zero remains blocked.

Disposition: retain research/shadow/paper-only operation. Do not promote
`one_tick_inside`, do not reinterpret `price_change` as trade evidence, do not
pool drills/proofs into the primary result, and do not enable live quoting or
live capital from this work.

## Engineering and verification

The research harness lives in
`weather.reporting.research.workstation_maker_research`, with report helpers
split into `workstation_maker_report`; both modules remain below the repository
size ratchet. The harness validates complete 12-market calendars, rejects
quarantine inputs, requires an explicit read-only data root, rejects direct or
symlink/junction-aliased outputs inside that root, and validates protocol event
types before scoring. Maker and taker research share the same fail-closed path
contract rather than relying on a directory's spelling.

Verification:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/reporting/test_workstation_maker_research.py
.\venv\Scripts\python.exe -m compileall -q src/weather/reporting/research/workstation_maker_research.py src/weather/reporting/research/workstation_maker_report.py tests/reporting/test_workstation_maker_research.py
```

Result: 8 maker tests and 7 shared-path/taker tests passed; compile checks
passed. The focused suite
includes an invariant that complete-case net equals 30-minute markout minus
the corresponding complete-case flattening cost while all-fill cost remains a
separate diagnostic.
