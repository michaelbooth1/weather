# Mission 09-84a — attended reward test feasibility handback

**BLOCKED: the required unchanged Python and JavaScript selection/share calculations differ. Handoff section 8 explicitly requires stopping and reporting both numbers. No live script was built.**

## Authority and provenance

The owner confirmed directly in this task on September 21, 2026:
"approved, look at .env.example". That confirmation authorizes the bounded
owner-started implementation described in the
[handoff](workstation-handoff-2026-09-84a-run-the-reward-test-attended.md),
including its stop conditions. It is not an agent-started live command or a
live-session typed confirmation. The
[deviation note](../research/re1m-attended-script-deviation-2026-09-21.md)
records the exception without claiming an unperformed session.

Branch: `codex/reward-test-attended-20260921`.
Stacked base: `origin/codex/stage2-hold-build-20260921`,
`88aa7e43a71d5870575261280b45c9deae667668`.
Requested handoff parent: `origin/codex/reward-test-attended-handoff-20260921`,
`ae9e25bc31e3847f64def2cdd2a3584253e0d861`.
Their merge is `0c5564e7b7325188407da7146d751c5d200ff78e`.
The isolated worktree is
`C:/Users/Michael/Documents/github/weather/scratch/w/reward-test-attended-20260921`.
The main checkout was initially clean and remains untouched.

The requested handoff merge also carries generated changes to
`config/location_market_events.json` and `config/locations.json`. These are
inherited handoff changes, not hand-edited configuration or current event
authority. The mission did not regenerate them or adopt them anywhere.

## Cheapest falsifying check: identical inputs, different answer

The new
[parity audit](../../tests/market/test_re1_attended_parity_audit.py)
invokes the supplied `re1_lib.js` with Node and the unchanged 80b Python
functions on identical inputs. It imports `Clock` and `Venue` from 80b's
`stage2_fakes.py`; it creates no client, reads no credentials and calls no
network endpoint. Its tests intentionally preserve a NO-GO counterexample,
not a claim that an attended trading implementation passes.

### Selection

Input: YES bid 0.40 x 100, YES ask 0.43 x 100; NO bid 0.57 x 100,
NO ask 0.60 x 100; reward minimum 20, rate 45/day, maximum reward spread
4.5 cents, tick 0.01. Both implementations propose YES 0.40 and NO 0.57
at midpoint 0.415, with 20 shares on each leg.

| Output | JavaScript reference | Unchanged Python 80b |
| --- | ---: | ---: |
| Own Q | 8.888888889 | 8.888888889 |
| Competing many Q | 35.555555556 | 44.444444444 |
| `share_many` | 0.20 | 0.1666666667 |
| Predicted 360-minute reward | 2.25 | 1.875 |
| Frozen >= 2.0 eligibility | Eligible | Rejected |

These are source-derived values; executable verification is recorded below.
`re1_select.js` calls `evaluate(..., own)` before any order exists, and
`re1_lib.js:sideScore` subtracts 20 from existing levels at both proposed
prices. `reward_quote.price_reward_quote` calls `side_score` on the full
displayed levels during selection. The difference is economic and changes
eligibility, not just floating-point rounding. This report does not silently
decide which behavior should replace the other.

### Per-minute observation

A second input holds YES at 0.33 and NO at 0.64 with 100 displayed shares at
YES bid 0.33 / YES ask 0.36 and NO bid 0.64 / NO ask 0.67. Adding a
one-share YES bid at 0.34 gives the following source-derived result:

| Output | JavaScript reference | Unchanged Python 80b |
| --- | ---: | ---: |
| Midpoint | 0.350 | 0.345 |
| `share_many` | 25/173 = 0.1445086705 | 0.20 |
| Reward per minute at 45/day | 0.004515895954 | 0.00625 |

JavaScript uses the best displayed bid and ask for midpoint, regardless of
size. Python uses reward-minimum-sized levels for its adjusted midpoint.
`observe_held_quote` recalculates that midpoint before evaluating the resting
prices. Both legs are visible and within the leave-alone window in this
example. A positive control without the one-share touch is included in the
audit. Changing the midpoint rule would change the frozen protocol; this
mission has not done so.

## Limits of the supplied historical selection

The supplied September 21 17:20:47.757Z selection has 40 rows: 4 eligible,
36 rejected, and 15 with recorded midpoint/quote calculations. Its selected
condition is `0xd461d5df262d1247450b11b4be29426a9996d384ae0b5d0a4be0fd3655484666`.

The audit can check the retained ranking, selected first row, tick-rounded
prices, capital and rate-times-share prediction arithmetic. **It cannot
independently reproduce raw-book shares or full selection from that file**:
it contains no level sizes, full YES depth, NO books or raw reward responses.
The earlier 80b selection retains full snapshots and is included as a separate
same-input comparison; it must not be described as the missing 17:20 books.

| Input | Raw-file SHA-256 |
| --- | --- |
| `docs/roadmap/re1-reference/re1_selection_2026-09-22_2026-09-21T172047757Z.json` | `9c34e88550d751ad9849082888400fc15428cb6478a1b2af2a6f3e42ec971738` |
| `docs/roadmap/re1-reference/re1_lib.js` | `a8d011090927897cca83945a474a63eed8fa0789604e3125b84d8ef717e60351` |
| `tests/fixtures/stage2_hold/20260921/selection.json` | `132b27ecc8b4010b1791656f920dd01b2f74937b7ec4119db1d41f8584b84f47` |

No own-account observations, paid epochs, economic market-days or statistical
inference were produced. These deterministic counterexamples have no sampling
interval or market/date cluster estimate.

## SDK capability inspection and unimplemented requirements

Read-only inspection of the installed `polymarket-client` 0.6.0 source found:

- `SecureClient.create_limit_order(..., post_only=True, expiration=...)` is
  available. Its limit-order builder selects GTD when expiration is present;
  its post builder accepts post-only GTC and GTD. The local expiration
  validator requires at least 180 seconds from signing time.
- `cancel_order(order_id=...)`, `cancel_all()` and `list_open_orders()` exist.
  No authenticated call or signing operation was attempted, so this is
  capability inspection, not a live success or error receipt.
- The existing adapter accepts a heartbeat sender and Stage 0 supplies the
  authenticated REST heartbeat mechanism. The venue documents a five-second
  cadence and cancellation 10–15 seconds after heartbeat loss. Source:
  [official order management](https://docs.polymarket.com/trading/manage-orders#order-heartbeats).
  No heartbeat was sent. Compatibility of a new attended wrapper was not
  qualified after the parity stop.
- The venue documents a 60-second GTD security threshold in addition to the
  minimum expiration horizon. Source:
  [official order placement](https://docs.polymarket.com/trading/place-orders#limit-orders).
  No order expiry was configured or exercised by this mission.

All section 3 limits remain **requirements, not implemented or tested
controls** for a new script: exact venue/proxy refusal; BUY/resting/post-only;
20 shares; 0.17–0.80 and fresh-ask check; 15.8/19.6 cost caps; two open orders;
ten submits; persistent three-session cap; fixed 360-minute same-UTC-day end;
expiry; unconditional cancellation and authenticated reconciliation; fill,
reward, geography and re-quote stops. No test here proves those controls.
The stronger goal of a loss ceiling despite arbitrary bugs/crashes also has
not been established. It must not be claimed from submit limits alone.

Only 80b's selection, quote/observation functions, and fake clock/venue are
reused in the audit. Its journal, frozen-prediction writer, reward readers,
two-token user stream and official adapter remain unchanged and were not
wired into another execution path.

## Verification and reproduction

Four credential-free audit tests were authored. The workstation wrapper was
invoked three times and refused each before pytest started because another
heavy workload held the shared mutex. A read-only inspection identified
`WorkstationOffline-pytest-47232`, started at 17:18:25Z; no process was
interrupted and no lock was changed. **Executed audit tests: zero so far;
there is no passing-test claim.**

From the task worktree, the exact attempted command is:

```powershell
& 'C:\Users\Michael\Documents\github\weather\scratch\w\reward-test-attended-20260921\scripts\ops\workstation_heavy.ps1' -Kind pytest -PythonPath 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe' -ArgumentsBase64 'WyItbSIsInB5dGVzdCIsInRlc3RzL21hcmtldC90ZXN0X3JlMV9hdHRlbmRlZF9wYXJpdHlfYXVkaXQucHkiLCItcSIsIi1zIiwiLS1iYXNldGVtcD1DOi90bXAvd2VhdGhlci1yZTEtODRhLXBhcml0eS0yMDI2MDkyMSIsIi0tanVuaXR4bWw9c2NyYXRjaC9yZTEtODRhLXBhcml0eS54bWwiXQ==' -RepoRoot 'C:\Users\Michael\Documents\github\weather\scratch\w\reward-test-attended-20260921'
```

Decoded arguments: `-m pytest tests/market/test_re1_attended_parity_audit.py
-q -s --basetemp=C:/tmp/weather-re1-84a-parity-20260921
--junitxml=scratch/re1-84a-parity.xml`. Node must be available; a Node-related
skip is not parity proof. Once run, retain the JUnit before deleting only
that exact test temporary directory. No temporary test tree was created by
the refused attempts.

The 360-minute accelerated rehearsal, 15-minute live-public rehearsal and
full suite were not run after the explicit stop. There are no rehearsal
journals, frozen session predictions or payout hashes. The prior 80b suite
is historical evidence and is not this mission's qualification.

`git check-ignore .env` returned `.env` before committing. Only
`.env.example` was read for variable names; `.env` remained unopened.
`git diff --check` passed during preparation.

## Roll verdict and owner run card

`powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File
scripts/ops/roll_verdict.ps1 -Branch codex/reward-test-attended-20260921
-Base origin/codex/stage2-hold-build-20260921` returned exit 1:
`UNDECIDABLE: no live closure evidence`, naming the four absent capture
supervisor status files. No frozen mirror was substituted.

| Mission-authored file | Per-file closure disposition |
| --- | --- |
| `tests/market/test_re1_attended_parity_audit.py` | No runtime source changed; production closure evidence unavailable, so no derived production roll assertion |
| This report | Documentation; no production closure evidence supplied |
| `docs/research/re1m-attended-script-deviation-2026-09-21.md` | Documentation; no production closure evidence supplied |

**Owner run card: DO NOT LAUNCH THIS BRANCH.** The requested `live`,
`cancel-only`, and `collect-payout` entrypoints do not exist. Supplying
plausible-looking commands would falsely imply readiness. No account mutation
occurred here, so this mission created no orders needing a panic cancellation.

To resume, first resolve the two specified parity differences explicitly and
qualify that repair on the same inputs. Do not alter the frozen reference or
80b lane code inside this stopped mission. Then build and verify the complete
requested owner-only command surface and every financial/lifecycle control;
run the required rehearsals/full suite before producing a runnable card.

## What was not done

No signing-capable code, live launch, typed live phrase, account query,
heartbeat, order, cancellation, payout query, credential read/copy/vault write,
production access/write, Scheduler registration, capture change, restart,
promotion, lane-gate edit, or merge to master. The topic merge above is the
explicitly requested handoff merge only. No live session occurred, so there
is no live-session outcome to append.
