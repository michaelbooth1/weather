# Agent report - 2026-07-27 workstation market-making gate

Status: **MISSION 1 AUDIT COMPLETE; HONEST PRIZE CEILING
INCONCLUSIVE; QUEUE STOPPED AT THE MISSION 1 EVIDENCE GATE; MISSIONS 2 AND 3
NOT DONE.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-28b-market-making-gate.md`,
file SHA-256
`8f29f4e4350d0aaa6e34a2ae950effcb2a049ec5492c42e9cee561cad2daa631`,
from exact `origin/master`
`5c004c4554d87a5052fae4acef6ece931a00dd38` on topic branch
`codex/workstation-mm-gate-2026-07-28b`.

## Executive verdict

The retained evidence does **not** establish an honest
`<= $99/day` ceiling. It establishes three narrower facts:

1. The selected maker policy realized `$0` because it produced zero quote legs,
   but that result is vacuous rather than an opportunity ceiling.
2. The configured five-contract quote is ineligible for the captured global
   markets' 20/50/100-contract liquidity-reward minimums.
3. The latest 12-market file-present fallback is far too sparse to size
   achievable fills: it has 12 explicit trade messages. Its compact snapshots'
   cumulative Gamma `volume` field increased by `479,464.833865` in aggregate,
   but those units and coverage are not reconciled to the 12 messages.

An initial scratch calculation produced `$0.164861/day` of spread plus rebate
under an arbitrary at-least-one-percent sparse-tape sensitivity, taking the
larger of 1% and the dimensionally invalid `5 / (liquidity + 5)` proxy for
each print, or `$16.164861/day` after adding a June `$16/day` reward prior.
Independent review blocked that terminal conclusion. The share is not a queue
model, the June reward amount is not a dated July allocation, and the frozen
protocol expressly says an unbounded event-day reward pool prevents a terminal
negative.

The corrected classification is
`INCONCLUSIVE_NOT_DECISION_GRADE`, not
`TENS_OF_DOLLARS_PER_DAY_STOP`.

The resource-allocation decision is still to **stop this queue at Mission 1**.
The frozen continuation rule allowed Mission 2 only after Mission 1 established
a realistic prize materially above `$99/day` with passing fill and economics
evidence. It did not. Missions 2 and 3 therefore cannot rescue, dilute, or
overrule Mission 1; both are `NOT_DONE`.

| Mission | Result | Queue action |
| :--- | :--- | :--- |
| 1. Size the prize | Audit complete, but no decision-grade dollar ceiling can be recovered from the retained tape. | Stop at the evidence gate. Do not relabel `$0`, `$0.164861`, or `$16.164861` as the opportunity ceiling. |
| 2. Audit the known-edge gate | `NOT_DONE` | Not authorized by the Mission 1 continuation rule. |
| 3. Counterfactual fill and adverse selection | `NOT_DONE` | Not authorized by the Mission 1 continuation rule. |

Apart from the requested fast-forward of local `master` to the exact base, no
production code, collector, data, scheduler, trading, sizing, quoting, model,
serving, promotion, release, pointer, pull request, merge, `master` commit, or
`master` push was made.

## Safety, exact base, and host admission

The declared output root was:

```text
C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\mm-gate-20260728b
```

At the final 09:20 ET admission check, memory commit was `45.52%`, available
`C:` space was `67.93 GiB`, and no local `robocopy` process existed. The
training log records the nightly child exiting at 01:00:07, capture restore
finishing at 01:00:20, and the restore-only backstop finishing at 04:15:02.
The `data\` ACL owner was `DESKTOP-RFCD2GH\weathersync`; both
`DESKTOP-RFCD2GH\Michael` and
`DESKTOP-RFCD2GH\CodexSandboxOffline` had explicit
`DeleteSubdirectoriesAndFiles, Write, Delete` denies.

The bounded run read 52 manifest-bound inputs totaling `81,648,368` bytes,
well below the predeclared 512 MiB cap. It did not materialize the 5.45 GiB
current book-summary corpus. Pre- and post-analysis manifests contained the
same identities and every input remained stable.

The project `venv` referred to a removed Python 3.11 executable. The
standard-library-only harness used the bundled Python 3.12.13 interpreter
instead. Both `--self-test` and `--analyze` exited successfully.

## Frozen protocol

The protocol was frozen before inspecting the fallback economics:

| Protocol artifact | SHA-256 |
| :--- | :--- |
| `predeclaration.md` | `d748456b869bca0a2d2fcfa2326fe5cf4b89fb946e098c737167b56fae5b05ae` |
| `predeclaration-amendment-1.md` | `1ee776682f763eaf831d69dfb37fdba01852bf0ba07ad9953d40d6357997433d` |
| `predeclaration-amendment-2.md` | `6fb3ff0f31fb3ce2969ef78048bf30f943692d4cfaf47944490a0546bf9ed0f1` |

Amendment 1 was triggered by a structural inventory:

- the selected nine active-day runs cover 108 market/event-day cells from
  2026-07-17 through 2026-07-25;
- all 108 have `order_books_summary.csv`;
- none has `trades_long.csv`, `market_trades.csv`,
  `market_ws_events.csv`, or `market_ws.jsonl` available to the scorer; and
- the summaries alone total 5,450,799,135 bytes.

Before looking at spread, volume, rebate, reward, or P&L, the amendment selected
the latest earlier day with compact snapshot and WebSocket files for all 12
markets: 2026-07-11.

Amendment 2 was triggered by schema inspection. The current generic loader in
`src/weather/market/mm_paper_scoring.py::load_trade_rows` admits any row with a
timestamp, token, price, and positive size. The WebSocket CSV interleaves
`book`, `price_change`, and `last_trade_price`; an order-book price change is
not an executed trade. This audit therefore admitted only exact
`event_type=last_trade_price` rows. No production fix was authorized or made.

## Primary current packet: realized zero is vacuous

The exact selected runs are the nine runs already bound by
`data/backtest/mm_paper_report.json`, SHA-256
`c30e33470304831739cd5f2c1f8a99f1ae20c429d1c68ed2b6b1f6550e66ddd6`.

| Evidence | Result |
| :--- | ---: |
| Active-day runs | 9 |
| Market/event-day cells | 108 |
| Quote intents | 174,504 |
| Quote permissions | 0 |
| Quote legs | 0 |
| Conservative fills | 0 |
| Filled shares | 0 |
| Net P&L | `$0.00` |
| Actual payout evidence | false |
| Fill evidence | `BLOCK`, vacuous, `no_quote_legs` |
| Model-review credits | 63/108 |
| Paper-trading credits | 47/108 |
| Live-permission credits | 0/108 |

The mutually exclusive no-quote causes were:

| Cause | Rows | Share |
| :--- | ---: | ---: |
| Stale input | 81,961 | 46.9680% |
| Known-edge permission | 63,272 | 36.2582% |
| Missing preflight | 26,752 | 15.3303% |
| Promotion | 2,519 | 1.4435% |

This proves what happened under the gates: nothing was quoted and no P&L was
earned. It does not prove what a safe two-sided maker could have captured.
There is no bound CLOB reconstruction, current trade tape, queue position,
passive markout, or actual reward payout in this packet.

## Applicable exchange economics

The captured event links point to the global `polymarket.com` CLOB, while all
nine run configurations declare `polymarket_us`. The repository's US exchange
snapshot therefore cannot supply economics for these global tapes. In
particular, its generic `$1,000/day` category reward default and tick-decay
formula were not used.

A bounded official Gamma recheck covered 108 event slugs and 1,188 band markets
without an error. Its raw response bodies were not retained, so the result is a
derived point-in-time economics audit, not a byte-for-byte source receipt or a
substitute for event-day trade or reward evidence:

- all 1,188 band markets had weather fees enabled;
- makers pay zero maker fee;
- the weather maker rebate pool is 25% of taker fees, with pre-rounding
  per-fill economic equivalent
  `0.0125 * contracts * p * (1 - p)`;
- reward maximum spread was 4.5 cents;
- reward minimum order sizes were 20, 50, or 100 contracts; and
- 0/1,188 bands admitted the configured five-contract quote.

Under that point-in-time derived Gamma audit, the selected policy's
liquidity-reward eligibility is consequently zero at its configured size. That
is a policy finding, not a proof that a differently sized policy could not earn
rewards.

The actual July 17–25 `rate_per_day` reward allocations were not retained. The
official raw-rewards endpoint returns present and future configurations and
returned no historical rows after settlement. Empty current output cannot turn
the historical pool into zero. The closest local measurement is the June 13
research note: roughly `$1/event/day`, with Dallas at `$5`, or `$16/day` for
the fleet. Its July applicability is `NOT_PROVEN`.

For scale only, awarding the entire market its mathematically maximum
rebate/notional ratio to the Gamma event volume gives loose whole-estate upper
bounds of `$6,335.89` to `$11,868.49` per selected day, mean
`$9,336.90/day`. Those are competitor-wide pools, not this maker's attainable
share. They demonstrate why the missing queue/fill denominator matters.
Rebate alone needs at least `$7,920` of daily maker fill notional to reach
`$99` at the mathematical best ratio, `$8,800` at `p=0.10`, or `$15,840` at
`p=0.50`.

Official source contracts:

- [Polymarket Maker Rebates](https://docs.polymarket.com/programs/maker-rebates)
- [Polymarket Liquidity Rewards](https://docs.polymarket.com/programs/liquidity-rewards)
- [Raw rewards for a specific market](https://docs.polymarket.com/api-reference/rewards/get-raw-rewards-for-a-specific-market)
- [Gamma event by slug](https://docs.polymarket.com/api-reference/events/get-event-by-slug)

## Deterministic July 11 file-present fallback

The compact fallback contains only 12 strict trade messages across 12 markets.
All 12 have a same-token snapshot at or before receipt time, but snapshot lag
reaches 966.504338 seconds. That preserves ordering but does not satisfy the
original contemporaneous/stale-tape rule.

| Market | Strict trade rows | Recorded shares | At-least-1% sparse-tape sensitivity |
| :--- | ---: | ---: | ---: |
| Atlanta | 1 | 15.730000 | `$0.015005` |
| Austin | 0 | 0 | `$0.000000` |
| Chicago | 1 | 0.020000 | `$0.000000` |
| Dallas | 0 | 0 | `$0.000000` |
| Denver | 3 | 62.514443 | `$0.033681` |
| Houston | 0 | 0 | `$0.000000` |
| Los Angeles | 2 | 30.228200 | `$0.018109` |
| Miami | 0 | 0 | `$0.000000` |
| New York City | 3 | 371.447131 | `$0.097793` |
| San Francisco | 0 | 0 | `$0.000000` |
| Seattle | 2 | 52.932930 | `$0.000271` |
| Toronto | 0 | 0 | `$0.000000` |
| **Total** | **12** | **532.872704** | **`$0.164861`** |

The generic loader would have admitted 25,080 price-and-size rows, mostly
`price_change` book updates. The strict filter admits 12. This is a
simulator-validity finding, not authority to edit the collector or scorer in
this task.

The `$0.164861` total uses the larger of 1% and
`5 contracts / (Gamma dollar liquidity + 5 contracts)` for each retained
print, captures half the most recent displayed spread at or before that message
(up to 966.5 seconds old), suffers zero adverse selection, and pairs inventory
for free. The floor is arbitrary and the second term mixes units; neither is
measured price-time priority. The scenario is retained as a diagnostic, not an
estimate or ceiling.

## Why the terminal negative was rejected

The independent review checked the manifests and arithmetic, then blocked the
original result for two decisive reasons:

1. 12 retained prints cannot bound the executions omitted from a tape whose
   Gamma volume delta is `479,464.833865`, and the current nine-day packet has
   no scorer-supported trade rows at all.
2. The July reward pool is `UNKNOWN_NOT_ZERO`. Predeclaration amendment 1 says
   that if actual event-level rewards are not bounded, Mission 1 is
   inconclusive and a terminal negative must not fire.

The scratch harness and outputs were corrected before this report was written.
The final receipt has:

```json
{
  "classification": "INCONCLUSIVE_NOT_DECISION_GRADE",
  "terminal": false,
  "queue_stop": true,
  "mission_2": "NOT_DONE",
  "mission_3": "NOT_DONE"
}
```

This correction matters. The honest handback is not “the prize is
`$16.16/day`.” It is: **the retained packet cannot size the prize, supplies no
decision-grade positive case for further platform work, and fails the frozen
gate required to continue this queue.**

## Receipts and reproducibility

| Artifact | SHA-256 |
| :--- | :--- |
| Host-admission receipt | `5765c5b5a2c5b01e36e07408afebd67ce7347cd108b9eb77ec61a9208ede3262` |
| Independent blocking review | `674925d5d3d87959365eac214fb40e73c745b5fa31d5977fda6ead161500a42f` |
| Independent economics audit | `6e230fbab16992a8e1e7976fb4a38daa188db1264cbaaa5cdac93156d74b8f28` |
| Final standalone harness | `69290b115182921be5393bb3d8f38dce1cd08244e202e8dd352c5bbe42da418f` |
| Machine-readable results | `715e5d815345b316bb8baef4a1fd0458c22fe38f50d9f22ccc54efac1de93bd2` |
| Per-market CSV | `90b33e84eae9d99f9db1cd5980de3d401035caada8e313300a0d2373d178a37e` |
| Scratch Markdown report | `9a24e6f7c1d42c73c2dbc00b5f184de355c5f31179e982845a01818d01453d36` |
| Pre-input manifest | `643359c76d3f36ed2c3df2af17c7b118d538f56f29936728eb83cb838e8a5e28` |
| Post-input manifest | `bbb2d756bb3db1cc0f7e1e22ee8685e5a85792fd77dff0adc4d23262e9b66e53` |
| Final command receipt | `b8a2c33a50391e49e854244b817310be1f4c099ec5fc776ea84bf8271bdcf07b` |

The final command was:

```powershell
C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe `
  C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\mm-gate-20260728b\mm_gate_mission1.py `
  --analyze `
  --repo-root C:\Users\Michael\Documents\github\weather `
  --output-root C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\mm-gate-20260728b
```

It ran from `2026-07-27T13:22:37.558129Z` through
`2026-07-27T13:22:38.738682Z`, recorded 52 stable inputs, and emitted receipt
schema `mm_gate_mission1_receipt_v0.2`.

## Limitations and NOT-DONE

- There is no current price-time queue reconstruction, side-correct complete
  trade tape, or captured queue-ahead depth.
- There is no dated July liquidity-reward allocation or payout receipt.
- The July 11 fallback is six days before the first primary day and is
  demonstrably sparse.
- No realistic paired fill volume, adverse selection, cancellation, latency,
  inventory cost, or settlement cost was measured.
- The current `price_change`/trade-loader issue was documented but not fixed.
- The known-edge gate's historical rationale and alternatives were not audited.
- No spread-and-rebate-only policy was designed.
- No counterfactual fill simulation was run.
- No collector change was made or recommended by this result.
- No production surface was exercised or changed.

If this question is ever reopened, an honest ceiling requires event-day reward
allocation receipts plus sequence-complete, side-correct trades and best-level
queue depth bound to the same event/token clocks. That describes the missing
proof; it is not a recommendation to reopen this stopped queue.
