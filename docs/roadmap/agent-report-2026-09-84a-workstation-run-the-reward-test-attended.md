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

## September 21, 2026 — mission 84b handback

**READY FOR THE OWNER TO RUN: corrected parity, four modes, both rehearsals and qualification are complete. No live session has run.**

This appendix preserves the original 84a text. Corrected handoff `b39b43b6`
was merged into the same branch as `a6f247fa429b1f5753c8b0c2118cb990016846a1`.
Implementation commits are `a53176838e8dac8e7eaeca24b2cf17a69a405b61`,
`46dafd3dffb7cb47ddea6d0d872ce8a893441942`,
`16699b8ff6423dc0c1f3171b758ab2f097409d6d` and final source
`74d337bc77b0fcdace278a46b33a5080b64fcae1`. Qualification scope is recorded below.
The worktree and stacked 80b base remain those recorded above. Inherited
fleet configuration was left as merged. The main checkout is untouched.

### Parity, implementation and boundaries

All five corrected-reference parity tests pass: selection share 1/6 and
prediction 1.875; held adjusted midpoint 0.345, share 0.20 and reward
0.006250/minute; full retained 80b books; historical-table arithmetic; and
the old-defect regression pin at 2.25. The minute sensitivity test also
pins plain midpoint 0.350 and share 25/173. The 17:20Z file lacks raw depth
and cannot prove raw-book parity or qualify a current selection.

The `re1_attended_cli` modes are `rehearse`, `live`, `cancel-only` and
`collect-payout`. They reuse unchanged 80b selection/validation, estimator
formulas, `HoldJournal`, immutable writers, scoring readers, official
adapter read/cancel normalization, user-stream transport and fake exchange.
RE-1M owns its re-quote controller and exact-pair stream validation. No
sealed-lane module imports it; no lane module, gate, grant, sealer, template
or test changed. The [deviation note](../research/re1m-attended-script-deviation-2026-09-21.md)
records the two outcome-blind corrections and the owner's direct permission
for read-only credential loading by the payout collector.

### Hard limits and proof

Tests named below live in `tests/market/test_re1_attended.py`,
`test_re1_transport.py` and `test_re1_evidence.py`.

| Requirement | Enforcement and executable evidence |
| --- | --- |
| Exact International host; no proxies | Fixed host and repeated proxy checks; submit-boundary `host/proxy` cases |
| BUY, post-only GTD, size exactly 20 and reward minimum 20 | Single submit boundary plus signed-payload binding; `side/size/post_only/type/minimum_not_twenty` cases and `test_corrupt_signed_order_never_posts` |
| Computed tick price 0.17–0.80, below actual ask | Fresh exact-token reads before and after signing; `price/ask` cases and `test_ask_moves_after_signing_refuses_raw_post` |
| One leg <=15.8, pair <=19.6 | Decimal assertions; `one_leg_cost/both_cost` cases |
| Initially empty account; only known orders; at most two | Exact account-wide order reconciliation; `third` case and foreign-order preservation test |
| Ten submits and four re-quotes | Budget consumed before signing; `eleventh` case and re-quote test |
| One session/process; three persisted attempts; September 30 cutoff | Process guard, fixed campaign root, exclusive attempt markers, prior-result checks; full-flow re-entry, persistent-cap and unfinished/expired-attempt tests |
| Fixed 360-minute same-UTC-day session | Wall and monotonic deadlines; `utc_day/duration/too_late/session_four` cases and full-flow test; only inert rehearsal permits 15 minutes |
| Any partial fill ends; never sell or re-enter | User stream, matched-size polling, cancel-race and terminal-order reads; fill end-condition, racing-cancel and deadline-fill tests |
| Minimum/rate, one-sided book, blocked/unreadable geography | Fresh terms and 30-second geography checks; parameterized end-condition and cadence tests |
| Exception, Ctrl-C, normal end, broken journal | Independent ID cancels, cancel-all and zero-open-order read; between-submit, end-condition and journal-failure tests |
| Cancellation unproved | Loud PANIC and `cleanup_ok=false`; cleanup-failure test |
| Submit acknowledgement lost | Terminal inventory read, incomplete evidence, and blocked subsequent attempt; lost-ack and incomplete-attempt regression tests |
| Secrets and confirmation | In-memory owner-only loading, recursive redaction and loaded-secret output guard; secret-guard, rehearsal credential refusal, redirected-prompt and CLI-override tests |
| Frozen payout interpretation | Prior-day chain replay before credentials, read-only transport/method guards, unchanged thresholds; tamper, collect-before-credentials, read-only and verdict-table tests |

The persistent campaign path comes from the Windows token profile, ignoring
`HOME`/`USERPROFILE` overrides; its regression exercises the native getter.
An externally cancelled or otherwise non-resting active order stops minute
credit. Raw minute observations and changed reward terms are journalled
before a stop; unexpected exceptions mark evidence incomplete and cannot
produce a passing payout verdict. Fresh pre-submit books, post-signing ask
reads, and SDK send timestamps are retained. The final guard regressions
cover these cases. SDK 0.6.0 initialization uses its credential-validation
factory with supplied credentials and an existing-wallet check; a test
refuses use of its deployment-capable public factory. Collection also blocks
every non-GET SDK request and every order/heartbeat mutation method.

Every GTD expires at fixed end plus 60 seconds; no replacement with under
180 seconds left. The pinned SDK additionally enforces its signing horizon.
The heartbeat uses documented `/v1/heartbeats`, rotating `heartbeat_id`,
five-second cadence and fail-closed acknowledgement. Its synthetic HMAC
test binds the exact body and rotation. Stage 1's heartbeat is unchanged.
Sources: [official order placement](https://docs.polymarket.com/trading/place-orders)
and [heartbeat contract](https://docs.polymarket.com/trading/manage-orders#order-heartbeats).
These prove requests/control behavior, not actual venue cancellation after
a killed process or lost network. No authenticated heartbeat or expiry was
exercised. The listed tests do not establish an unconditional 15.8-dollar
ceiling against arbitrary bugs, racing fills or exchange faults; only the
controlled account balance supplies that ceiling.

### Qualification receipts

The full suite on `46dafd3d` passed: **7,116 passed, 34 skipped, 13 warnings,
991 subtests passed, 3,035.21 seconds**. Warnings were existing feature
imputation and netCDF/NumPy ABI warnings. Final guard changes on `16699b8f`
passed **158 tests, zero skips, 97.58 seconds**, including the four RE-1M
files, unchanged 80b hold/reward/selection tests, SDK overlay and architecture
checks, and a fresh accelerated rehearsal. The last SDK initialization
change passed **32 transport/evidence tests, zero skips, 1.39 seconds**.
The full suite preceded those scoped fixes; it was not rerun on the final
source tip. Final `compileall -q app src tests` passed, as did CLI help.
The public rehearsal plus evidence/transport/architecture checks passed
**54 tests, zero skips, 954.52 seconds**.

| Retained JUnit receipt | SHA-256 |
| --- | --- |
| `scratch/re1-84b-full2.xml` | `55301efe7ca011900c47f192b5ea3f7bd6326cadf6d7846e159ebeebe1ed578f` |
| `scratch/re1-84b-final-guards.xml` | `565ee5a975b693d919262ad1c650f942a916ea9cf1920c693b02897140a83169` |
| `scratch/re1-84b-sdk-bootstrap.xml` | `68297a64c7b3cc197b3c4940b1c9081797eb5d4355847c19d3d6bdc8f5bbf6e2` |

All heavy runs used the repository's workstation wrapper and shared lease,
serially; no mission 83c process was interrupted. The last regression launch
first recovered a stale ACTIVE marker after proving zero residual heavy
processes, then passed on the wrapper-directed identical retry. All completed
pytest temporary directories were removed after their processes ended;
JUnit receipts and rehearsal evidence remain.

Evidence is retained outside the checkout at
`C:/tmp/weather-re1-84b-rehearsals`. `realtime-1` found no qualifying band
at 18:34Z and placed no simulated orders. Its selection is retained unchanged;
later attempts use fresh directories. Rehearsal account, orders, geography
and heartbeat are simulated; real-time books and rewards are public reads.
No rehearsal establishes account readiness or geographic eligibility.

| Attempt | Result | Journal SHA-256 | Frozen prediction SHA-256 |
| --- | --- | --- | --- |
| `accelerated-4` | Final controller, 360 samples and visible two-sided minutes, two simulated submits, no re-quotes/fills, clean fixed end | `400b46920e70f4873e5c1920536b932013acddb3762f2fd1b5eb3203db4f4912` | `d2c135d205613f135ad505a802661846c923ec206d2de015571a922c8798a7be` |
| `realtime-2` | September 21 18:41:31–18:56:31Z; 15 samples and visible minutes; two simulated submits, no re-quotes/fills, clean fixed end | `5356583ed9e6048eeea153fcee686216420ac6300307607d3a6ccd2248203be6` | `b0450f921c7818daafc0b5a544b17834c6cc2f4abc0db1672a8311034019d44a` |

The real-time condition was
`0x1238f985b95f1ac281ccb0b893ed5cc45534ef5edf33a16e244e8f9bb109aaf5`;
`P_many=0.07717601745886175`, `P_single=0.09416177285745216`.
Reward settings changed during that window, correctly setting
`reward_terms_changed=true`; this is rehearsal success, not an economically
conclusive session. Final accelerated `P_many=6.644751876527154` and
`P_single=8.012888455505117`, with plain-mid sensitivity
`P_many_plain_mid=5.833884311296041`. The real-time proof preceded final
re-quote ordering, ambiguous-ack, terminal-order, profile, logging and SDK
startup safeguards. Its session had no re-quote, fill or failure path;
final regressions and the fresh accelerated rehearsal cover the changes.
`accelerated-1`, `accelerated-2` and `accelerated-3` are also retained;
the first no-survivor selection SHA-256 is
`5cec33953d867a1ea3fb7b0103e0cc009da2c0c653c83ffdb3a4887322df5217`.

Earlier receipts remain in `scratch/`: parity 5 passed; initial controller
38 passed; focused2 145 passed/2 failed (test clock and strict-decimal
fixtures corrected); focused3 185 passed/2 failed (immutable SDK test model
and Git-tracked architecture inventory corrected); first combined rehearsal
1 passed/1 failed (no qualifying public band); focused final 142 passed;
ambiguous-ack focused final 144 passed in 92.68 seconds.
The first full-suite attempt on `a5317683` was deliberately stopped at 35%
to add the ambiguous-submit fix, with no observed failure; it is not counted
as a completed suite. Only its identified interpreter child was stopped;
the wrapper completed cleanup before the next admitted run.

Reproduction uses the worktree's `scripts/ops/workstation_heavy.ps1`,
`-RepoRoot` set to this worktree, the main project's `venv/Scripts/python.exe`,
and `-ArgumentsBase64` containing UTF-8 JSON arguments. Full-suite arguments:
`["-m","pytest","-q","--basetemp=C:/tmp/weather-re1-84b-full2",
"--junitxml=scratch/re1-84b-full2.xml"]`. Focused arguments additionally
select the four `test_re1_*` files, the three `test_mm_stage2_*` files named
above, import/module-size architecture checks and the explicit ignored
`scratch/re1_84b_rehearsal_proof.py::test_accelerated` harness. That harness
calls `rehearse --selection tests/fixtures/stage2_hold/20260921/selection.json`
for accelerated mode and `rehearse --realtime` for public mode, each with a
fresh external output directory. It is outside the offline test suite.

Documentation audit passed (18 agent files, 912 Markdown files); the generated
backlog check passed. The required `roll_verdict.ps1` returns
**UNDECIDABLE: no live closure evidence**, naming the four absent production
supervisor status files. No closure mirror or hand-derived roll verdict was
substituted. The five new runtime modules have no measured production closure
intersection available here; all other authored paths are tests or dated
documentation. [Draft PR 78](https://github.com/michaelbooth1/weather/pull/78)
remains stacked on `codex/stage2-hold-build-20260921` at
`88aa7e43a71d5870575261280b45c9deae667668`. Production adoption remains the
operations owner's job.

Accrued earnings are separate from paid cash. Without independently
reconciled distribution/wallet evidence via `--payment-evidence`, `paid`
and `k` are null and the verdict is `INCONCLUSIVE`. Both candidate asset
balances, condition/day earnings, total earnings and percentages are retained.
Per-asset earnings and the venue's `asset_rate` are preserved; `k_accrued`
uses their rate-weighted sum, with duplicate/unknown assets refused. The
[official CLOB schema](https://docs.polymarket.com/api-spec/clob-openapi.yaml)
describes this field as the asset's exchange rate. The existing independent
payment reconciler supports pUSD receipts; USDC.e cash evidence is not silently
relabelled as pUSD. A pUSD-only zero observation does not establish no payment
in both candidate assets; cash provenance must cover the actual reward asset
before interpreting a supplied reconciliation as an epoch verdict.
Raw orders/trades retain fill facts; later 1/5/30-minute and settlement
markout reconciliation uses public capture/account history. There is no
automatic inventory sale or paid/profitable claim from accrual alone.

### Owner run card

1. Use the assigned workstation and owner Windows account; finish heavy
   work first (the same host-global mutex excludes live). Keep the home
   file-access tunnel down. Check the official geoblock page in the browser
   says not blocked. Have zero account-wide open orders, no earlier rewarded
   activity today, zero selected-token positions, at least $25 available,
   and remain within reach for six hours. A dedicated account holding about
   **$50** is recommended. Only its balance is an unconditional loss ceiling;
   the account choice is the owner's.
2. In the owner's terminal:

   ```powershell
   Set-Location 'C:\Users\Michael\Documents\github\weather\scratch\w\reward-test-attended-20260921'
   $re1Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
   & $re1Python -m weather.market.re1_attended_cli live
   ```

   Target September 22 at 17:00Z; the six-hour end must be before 00:00Z.
   No qualifying band means no orders; the owner may retry after 15 minutes
   while time remains. Inspect the selected band/prices/hash and personally
   type the displayed confirmation. There is no skip flag. The agent never
   runs live or types this phrase.
3. `fill` ends quoting: retain inventory to settlement. Reward, geography,
   heartbeat or read failure, a fifth re-quote, limits or deadline cancel.
   `REFUSED` means execution stopped: inspect its journal. If orders may
   remain, or PANIC appears, run from this worktree in a second terminal:

   ```powershell
   & 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe' -m weather.market.re1_attended_cli cancel-only
   ```

   Panic needs no phrase or mutex; it cancels the whole account and prints
   remaining orders. If zero cannot be proved, cancel in the browser. An
   incomplete or filled previous attempt blocks a fresh live session.
4. Save the printed prediction path/hash. Permanent attempts and journals
   live under the Windows token profile's `.weather-re1m-20260921` directory
   (normally `%USERPROFILE%`); environment overrides cannot relocate it.
   Never reset the count.
   On a later UTC date, substituting the actual printed session path:

   ```powershell
   & $re1Python -m weather.market.re1_attended_cli collect-payout "$env:USERPROFILE\.weather-re1m-20260921\session-1\prediction.json"
   ```

   This reads credentials in memory under the owner's explicit permission,
   makes read-only queries and writes a new receipt. Independent payment
   evidence is needed for `k`; accrual alone remains inconclusive. Report
   every actual session, including aborted ones and later payouts.

### What was not done

No `.env` read, credential copy/export/vault write, live launch, typed live
phrase, authenticated account query, signing, order, cancellation, payment
collection, production access, Scheduler/capture change, host reassignment,
lane edit, promotion or merge to master. No live prediction or payout exists.

## September 21, 2026 — mission 84c handback

**IMPLEMENTED; qualification in progress. Live remains NO-GO until the owner runs a clean preflight on the final tip. No authenticated preflight or live session has run.**

This appendix supersedes 84b's readiness and campaign-retry instructions while
preserving its historical evidence. The owner directly confirmed implementation
authority in this task: "Authorize implementation; I run the owner commands."
The unchanged three submitted sessions, September 30 end, International-only
venue, BUY/post-only/GTD, twenty shares, ten submit attempts, four re-quotes,
15.8 per-leg and 19.6 pair caps still apply. No sealed-lane source changed.
Work continues on `codex/reward-test-attended-20260921`, in the existing
`scratch/w/reward-test-attended-20260921` worktree, from reviewed `54b56d21b`;
the declared stacked base remains `codex/stage2-hold-build-20260921` at
`88aa7e43a71d5870575261280b45c9deae667668`. PR 78 remains a draft.

### SDK reply-shape audit

Paths below are relative to the installed `polymarket` directory in
`venv/Lib/site-packages`, distribution `polymarket-client==0.6.0`.
`_plain_sdk_value` is the existing official adapter function; submit success
and identity alternatives now use that adapter's existing `_value` helper.
The tests construct the SDK's own models, rather than asserting only against
invented controller dictionaries. These are offline contract tests, not proof
of an authenticated exchange response.

| Call / controller fields | Installed SDK model, source and field | Executable test |
| --- | --- | --- |
| `post_order`: success, ID, status, immediate fills | `clients/secure.py:1885`; `models/clob/order_response.py:60` `AcceptedOrder.ok`, `order_id`, `status`, `trade_ids`; raw `RawOrderResponse` at line 44 supplies `success`, `order_id` (`orderID` validation alias), `status`, `trade_ids` (`tradeIDs`) | `test_sdk_accepted_and_raw_post_models_pass_controller` constructs raw and normalized models, passes each through `_plain_sdk_value` and the controller |
| `cancel_order`: canceled IDs and failures | `clients/secure.py:1929`; `models/clob/cancel.py:9` `CancelOrdersResponse.canceled`, `not_canceled` | `test_sdk_cancel_models_and_open_order_model_normalization` |
| `cancel_all`: canceled IDs and failures | `clients/secure.py:1943`; same `CancelOrdersResponse` | Same test, both cancellation boundaries |
| `get_order`: ID, token, condition, maker, side, price, size, matched size, trades, status | `clients/secure.py:1615`; `models/clob/account.py:44` `OpenOrder.id`, `token_id`, `market`/`condition_id`, `maker_address`, `side`, `price`, `original_size`, `size_matched` (61), `associate_trades` (65), `status` (64) | Same test uses official adapter `get_order`; `test_nonresting_sdk_status_ends_and_cancels` |
| `list_open_orders`: exact same identity/size/status fields | `clients/secure.py:1593`; paginated `OpenOrder` objects | Same test passes model instances through `bounded_rows` and `_exact_open_orders` |
| `list_account_trades`: retained fill facts | `clients/secure.py:1622`; `models/clob/account.py:118` `ClobTrade`, including `status`, `token_id`, `maker_orders`, nested `MakerOrder.order_id`/`matched_amount` | `test_sdk_trade_model_retains_fill_facts` |
| Scoring: known ID → boolean | **No model class exists.** `clients/secure.py:2032` returns `dict[str,bool]`; `_internal/actions/rewards.py:145` parses it. Empty lists are refused at line 135 before network access. | `test_sdk_scoring_parser_has_no_model_and_empty_list_is_rejected` uses the actual SDK client/parser through a closed mock transport; preflight records SKIP for empty scoring |
| Heartbeat: rotating `heartbeat_id`, optional `error_msg` | **No CLOB heartbeat reply model or method exists in SDK 0.6.0.** The existing separate sender uses the [official v1 contract](https://docs.polymarket.com/trading/manage-orders#order-heartbeats). | `test_v1_heartbeat_binds_exact_body_and_rotates_id`; `test_rotating_heartbeat_resynchronizes_without_claiming_ack` |

Resting REST orders are `LIVE`; a successful resting submit is `live`.
Cancellation is `CANCELED`, with stream transition `CANCELLATION` normalized
to `canceled`; fills are `MATCHED` / submit `matched`, nonzero matched size,
associated trades, or authenticated trade events. All terminate quoting;
fills also set the campaign's fill flag. The pinned REST model declares
`status: str`, not an expiry enum. The [official REST reference](https://docs.polymarket.com/api-reference/trade/get-single-order-by-id)
lists `LIVE`, `INVALID`, `CANCELED_MARKET_RESOLVED`, `CANCELED`, `MATCHED`;
it supplies **no separate expired status**. Thus no exact expiry wire string
is claimed here. An `EXPIRED` response, either cancellation spelling, and
every other non-`LIVE` status stop safely in `check_fills`; tests pin that
behavior. GTD expiry remains fixed end plus 60 seconds. Real expiry behavior
has not been exercised by this mission.

### Freshness budgets and recovery

`re1_resilience` owns transport-error classification and monotonic freshness;
`re1_attended` owns the safety decisions. Successful reads alone refresh a
fact. A late response cannot revive an exhausted budget. Retrying a read
never retries a submit or substitutes a stale public book for the fresh ask.

| Fact | Implemented cadence / deadline | Test |
| --- | --- | --- |
| Geography | 30-second cadence; retry after 1 second; stop on any successful non-false blocked value or 45 seconds without success | `test_persistent_outage_exhausts_own_budget[geography]`, existing geography end-condition and cadence tests |
| Heartbeat | Independent daemon, 5-second cadence, 1-second retry; 8-second ack deadline; no sends after 20 seconds without a main-loop tick | Heartbeat outage case; `test_heartbeat_daemon_and_main_stall_stop`; rotating-ID recovery test |
| Each active order | Independent 10-second REST cadence and 30-second success deadline; fills/non-resting facts terminate immediately | Order outage case; `test_nonresting_sdk_status_ends_and_cancels`; existing cancellation-race and deadline-fill tests |
| User stream | Continuous reader; reconnect into a new retained journal; 30 seconds from last inbound proof; REST polling remains active while down | Stream outage case; `test_stream_down_uses_rest_fill_detector`; owner-stream configuration test |
| Minute market observation | 60-second cadence, 300-second success deadline; a failed observation writes `minute_missed`, gets no credit and cannot extend the fixed end | Snapshot outage case; seeded six-hour rehearsal |
| Scoring / accrual | 30-minute cadence; exceptions record `missing_sample`, mark evidence incomplete and never terminate quoting | `test_noncritical_samples_can_fail_forever`; safe-next-session test |
| Initial/account/submit-adjacent reads | Bounded 30-second retry; all original empty-account, balance and fresh-book assertions still run | `test_initial_read_budget_is_named_and_sends_no_orders`; `test_one_timeout_per_read_at_each_phase_survives`; existing money-boundary tests |
| Cleanup | Three bounded attempts for idempotent cancels and terminal reads; no submit retry; PANIC if acknowledged cancel-all plus empty account cannot be proven | Phase timeout matrix and existing cleanup-failure test |

The response hook never raises. Non-JSON and oversized bodies retain length
and SHA-256; a journal/secret-guard failure sets a flag that stops the main
controller while preserving the raw POST outcome. Journal records share a
lock with the heartbeat thread. A documented HTTP 400 rotating-ID challenge
updates the next heartbeat ID but **does not** reset the ack deadline.

Preflight measures min, median, nearest-rank p95 and max for twenty reads per
step (six heartbeats, at five-second cadence). It records every exception by
step/type, every heartbeat acknowledgment, stream readiness, both asset
balances and allowance. Only the separate heartbeat sender may mutate; the
SDK client retains its GET-only guard, and heartbeat mode rechecks the empty
account before every send. Scoring's empty-list SKIP is an installed-SDK
limitation, not an authenticated scoring proof. The fixed SDK bootstrap has
no caller timeout parameter; after bootstrap every SDK transport uses
`max(2 seconds, 3 × measured p95)` from the preflight table, conservatively
using its largest measured timeout. Geography, positions, asset-balance and
heartbeat reads use their own entries. A heartbeat timeout reaching the
8-second safety budget makes preflight FAIL. These are network inactivity
timeouts; the separate freshness clocks and main-loop watchdog still apply.

### Campaign and owner run card

There are at most six immutable attempt markers and at most three attempts
that reached the raw POST boundary. A durable intent is flushed immediately
before that POST; signing/pre-submit failures still consume the ten-attempt
in-process budget, but zero POSTs do not consume a campaign session. A crash
after an intent conservatively counts as submitted. Marker, journal, intent,
acknowledgment and prediction files are retained. Incomplete measurement
evidence remains INCONCLUSIVE and by itself no longer blocks the campaign.
Unknown submit IDs, a fill, unproven cleanup or unproven terminal inventory
require owner reconciliation. That receipt never resets the session count
or authorizes selling inventory; a later reservation also reads the account
again and requires zero open orders.

From the assigned workstation and Windows principal, keep the tunnel down,
complete heavy work, maintain zero open orders and the required selected-token
positions/balance, and use the same terminal setup as 84b:

```powershell
Set-Location 'C:\Users\Michael\Documents\github\weather\scratch\w\reward-test-attended-20260921'
$re1Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
& $re1Python -m weather.market.re1_attended_cli preflight
```

The owner alone runs this credential-loading command. Target the morning of
September 22. Send back its printed receipt path for review and repairs. The
agent must not run it. A clean final-tip, same-UTC-date PASS is required by
`live`; a newer failed or incomplete preflight invalidates an earlier PASS.
Any code-tip change requires another owner preflight.

```powershell
& $re1Python -m weather.market.re1_attended_cli live
```

Target 13:00 Eastern September 22 only after clean preflight; last possible
start is 13:59 Eastern so the fixed six hours finish before 00:00Z. Otherwise
move to September 23. Personally inspect the selected treatment and type the
unchanged attendance/eligibility/tunnel-down phrase. No check is shortened.
For PANIC or uncertain open orders, run in a second terminal:

```powershell
& $re1Python -m weather.market.re1_attended_cli cancel-only
```

For a blocked attempt, substitute its actual marker number (1 through 6):

```powershell
& $re1Python -m weather.market.re1_attended_cli reconcile 1
```

This owner-terminal command prints current account-wide open orders, positions
in the attempt condition and known order IDs, then requires the displayed
attempt-bound phrase. It reads the empty account again after the phrase and
writes `reconciliation.json` beside the attempt, exclusively. It never cancels
or sells; use panic first if needed, and hold filled inventory to settlement.
Collection remains the prior-day `collect-payout <printed-prediction-path>`
command; independently reconciled payment evidence remains required for `k`.

### Qualification and remaining evidence

Initial focused run: 71 passed, one obsolete zero-submit expectation failed.
After updating the regression and adding fault injection/SDK models: 100
passed, including the seeded 360-minute run. The next owner-command and
architecture run passed 137 tests; two architecture failures identified
unstaged new files and an optional-import pattern, both repaired. Final
qualification receipts and retained rehearsal hashes are recorded below
after completion; none of these runs used credentials or authenticated APIs.

Final broad focus: **144 passed, zero skips, 222.33 seconds** including all
RE-1 tests, architecture/module-size checks and an explicitly retained
accelerated rehearsal. JUnit `scratch/re1-84c-focused4.xml` SHA-256:
`088232551ef6cff8decb5d04235fec4018f6b7069c5387b9ffd5d4c8c796794b`.
The final main-thread checkpoint adjustment receives an additional focused
run before the full suite. Checkpoints between bounded reads count as main
progress; a blocked read cannot refresh that watchdog.

Retained seeded rehearsal: `scratch/re1-84c-seeded-1`, seed **84003**, fixed
360-minute end reached, **351** successful/visible minute samples, nine
missed minutes, two simulated POSTs, zero re-quotes/fills, acknowledged
cleanup and zero remaining simulated orders. It injected **644 failures**:
452 user-stream reads, 98 heartbeats, 75 order reads, nine geography reads,
nine snapshots and one scoring read, from an independent 2% Bernoulli draw
on each read. Missing evidence correctly leaves `evidence_complete=false`.
`P_many=P_single=2.46488764044945`; this is synthetic prediction, not income.

| Retained evidence | SHA-256 |
| --- | --- |
| `scratch/re1-84c-seeded-1/journal.jsonl` | `bb4ddec19bc5a1283949b2c3cc00c385260b93726d29b2cfc8cbf18be4248f24` |
| `scratch/re1-84c-seeded-1/prediction.json` | `905393a8c826ba5f7dff420a55ea6f6234f221801adb164794294c8098f7cfd2` |

Reproduction, from this worktree: use `scripts/ops/workstation_heavy.ps1`
with `-Kind pytest`, the main checkout's `venv/Scripts/python.exe`, explicit
`-RepoRoot`, and `-ArgumentsBase64` holding UTF-8 JSON. The durable offline
test is `tests/market/test_re1_resilience.py::test_seeded_two_percent_six_hour_rehearsal`.
The ignored retention harness `scratch/re1_84c_retained_proof.py` invokes
that same test with the retained directory above; use a new directory for
another retained run. Full-suite arguments are `-m pytest -q` with explicit
`--basetemp=C:/tmp/weather-re1-84c-full` and
`--junitxml=scratch/re1-84c-full.xml`. Completed pytest temporary trees are
removed only after the admitted process exits; receipts and journals remain.

**Owner preflight latency table: NOT RUN. Authenticated FAIL lines: none
available.** Fake timings are not presented as account-path evidence. The
owner's actual table and every FAIL line must be appended after that run;
until then the authenticated path remains unproven and `live` refuses.

What was not done: no `.env` read, credential export/copy/vault access, real
signing, authenticated account query, heartbeat, order, cancellation,
reconciliation, payout collection or live session; no production access,
capture/Scheduler change, restart, host reassignment, promotion, sealed-lane
edit or merge to master. The simulated six-hour outcome proves the tested
fault model only; it proves neither profit nor future venue/network behavior.
