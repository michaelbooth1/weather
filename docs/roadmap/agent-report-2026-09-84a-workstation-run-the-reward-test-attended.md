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

**READY FOR OWNER PREFLIGHT: implementation and offline qualification passed. Live remains NO-GO until the owner runs a clean preflight on the published final tip. No authenticated preflight or live session has run.**

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

**Correction to 84b's bootstrap claim:** tracing installed SDK
`clients/secure.py:2826` showed that `_create(validate_credentials=True)`
can fall back to `POST /auth/api-key` when supplied credentials are inactive
or rejected with 401. It was not a validation-only path. RE-1M now supplies
the existing credentials with that fallback disabled, installs its transport
guards, then mandatorily calls authenticated `fetch_api_keys()` and requires
the supplied key to be present. Failure closes the client; it never creates,
derives or replaces credentials. That private response is not journaled.
`test_pinned_bootstrap_cannot_create_or_derive_credentials` executes the
SDK's own bootstrap helper with mutation paths trapped, while the transport
guard test proves inactive credentials are refused. This preserves credential
validation and adds no order authority.

The installed post serializer also binds `owner` to `owner_api_key`
(`_internal/actions/orders/post.py:78`). SDK order/trade models retain that
field, so journaling a credential-bearing owner would trip the secret guard
after a successful POST. The guard now removes an `owner` field only when
its exact value is a loaded secret, then performs the unchanged refusal scan.
Maker address, token, order ID, price, size and fill/status evidence remain.
`test_sdk_credential_owner_is_redacted_without_losing_order_binding` proves
this with a real SDK `OpenOrder` model and still refuses the same secret in
an unexpected field.

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

Keep this execution worktree clean between preflight and live. The binding
is to the exact Git commit, including documentation commits. Review the
receipt without editing this worktree; append the actual latency table and
FAIL lines after the attended session, or in a separate correspondence
worktree, so reporting alone does not invalidate the execution receipt.

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

That last focused run passed **26 tests in 78.46 seconds** (JUnit
`scratch/re1-84c-final-focus.xml`, SHA-256
`a9ac7297d16c1f3421313b83a6acdd6d43745d27540797fb520bff99e26ca8f1`).
The first full-suite launch on `3a449362e35a8c143947a20581e7176a5dc00cae`
was deliberately stopped at 31%, with no observed failures, after the SDK
bootstrap fallback above was discovered. Only its verified interpreter child
was stopped; the wrapper exited and completed teardown. That aborted launch
is not counted as a full-suite qualification. The corrected final tip receives
its own focused checks and one completed full-suite run.

Bootstrap repair `05ae28692307a69d95f995d14d66d47a05864542` passed **37
focused tests in 3.12 seconds**, plus compileall. Its full-suite launch was
also deliberately stopped, at 28% with no observed failures, to add the
credential-owner redaction regression above. That aborted run likewise does
not count as full qualification; verified child-only termination allowed
the wrapper to finish cleanup. Final qualification below supersedes both.

The credential-owner repair at
`ee5a02bd38ef51ddc485dfd250d98103b9dd6bd9` passed **71 focused tests in
62.81 seconds**; final compileall passed. This is the source commit used by
the completed full-suite qualification recorded below. The only later
commit closes this report; it changes no source, test, or configuration.

| Additional focused receipt | SHA-256 |
| --- | --- |
| `scratch/re1-84c-bootstrap.xml` | `4bbdf81fae633ff1e9dcd524b2decccd3b44226dcdb4b377433a9761b6976ddc` |
| `scratch/re1-84c-owner-redaction.xml` | `ae965726243470e62ff589545c6f0e0005936e9622c00cf239a6349b5928a4e7` |

The completed full suite on that final source passed **7,162 tests, 34
skipped, 991 subtests passed, 13 warnings, zero failures/errors**, in
**3,623.46 seconds (1:00:23)** through `workstation_heavy.ps1`. The JUnit
receipt is `scratch/re1-84c-full-verified.xml`, SHA-256
`31f60a1d30d1b0caecf57b7b254a454161a14e66656260a14997b2fd72fcdb9c`.
Its 8,187 cases include the subtests and skips. Warnings were from missing
fixture features in sklearn and a NumPy/netCDF binary-size warning.
The admitted wrapper exited successfully before temporary-tree cleanup.
This is the one completed full-suite qualification of 84c's final source;
the two earlier aborted launches remain disclosed above.

Final compilation, six-mode CLI help, the agent documentation audit and
generated-backlog check passed. The closing documentation receives its own
audit/backlog checks and cumulative diff check before publication. No source,
test or configuration changes follow the qualified source commit.

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

The full suite on `ee5a02bd` repeated this seeded test and produced the
**same journal and prediction hashes byte for byte**. That exact-source
case, including its selection and both submit intent/acknowledgment pairs,
was copied before temporary-tree cleanup to
`scratch/re1-84c-seeded-ee5a02bd`. Both retained proof directories remain;
the final-source receipt also ends at the fixed time with 351 credited
minutes, clean cleanup, proven inventory and no unknown submit.

Reproduction, from this worktree: use `scripts/ops/workstation_heavy.ps1`
with `-Kind pytest`, the main checkout's `venv/Scripts/python.exe`, explicit
`-RepoRoot`, and `-ArgumentsBase64` holding UTF-8 JSON. The durable offline
test is `tests/market/test_re1_resilience.py::test_seeded_two_percent_six_hour_rehearsal`.
The ignored retention harness `scratch/re1_84c_retained_proof.py` invokes
that same test with the retained directory above; use a new directory for
another retained run. Full-suite arguments are `-m pytest -q` with explicit
`--basetemp=C:/tmp/weather-re1-84c-full-verified` and
`--junitxml=scratch/re1-84c-full-verified.xml`. Completed pytest temporary trees are
removed only after the admitted process exits; receipts and journals remain.

### Roll disposition and publication boundary

The required repository verdict was obtained with
`scripts/ops/roll_verdict.ps1 -Branch codex/reward-test-attended-20260921 -Base origin/codex/stage2-hold-build-20260921`:
**UNDECIDABLE**, exit 1. The workstation has no live snapshot, CLOB,
observation-trigger or CLOB-enrichment closure evidence. The retained output
is `scratch/re1-84c-roll-verdict.txt`, SHA-256
`9259f6be9d32028d609f5eb2f3a41f7f7970af6045ba92f0436b41316a0bf8a0`.
The script exits before producing JSON when no live closure exists.

| 84c path (`src/weather/market/` unless stated) | Disposition |
| --- | --- |
| `re1_attended.py` | Live closure membership unavailable; no roll-free claim |
| `re1_attended_cli.py` | Live closure membership unavailable; no roll-free claim |
| `re1_evidence.py` | Live closure membership unavailable; no roll-free claim |
| `re1_owner_checks.py` | New module; live closure membership unavailable |
| `re1_rehearsal.py` | Live closure membership unavailable; no roll-free claim |
| `re1_resilience.py` | New module; live closure membership unavailable |
| `re1_transport.py` | Live closure membership unavailable; no roll-free claim |
| Five changed/new `tests/market/test_re1_*.py` files | Offline regression evidence; no live closure measurement |
| This report | Documentation; no runtime adoption |

The complete stacked diff was reviewed against the declared base. The
inherited handoff/reference files and generated location configuration are
preserved; 84c changes only the seven RE-1 modules, five test files and this
report. Branch publication and draft PR 78 are the handback boundary.
Integration/adoption remains with the operations owner after a fresh verdict;
no production evidence was accessed to manufacture one here.

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

## 85a — payout evidence collector, 2026-09-21

**BLOCKED FOR A PAID RE-1 VERDICT: the read-only collector is implemented,
but the inspected venue surfaces do not supply an earned-period-to-payment
link. Its actual output is INCONCLUSIVE, not PAID or NOT_PAID.** This is the
85a source-unavailable disposition, not a request to weaken the matcher.

Branch `codex/re1-payout-evidence-20260921` is stacked on
`7e6e1709c243cf88aa7799bf4486a9af821abbf5`, in the new worktree
`scratch/w/re1-payout-evidence-20260921`. The mission specification was read
from `codex/reward-test-attended-handoff-20260921` at `6ab3f63a7`.
The execution worktree `scratch/w/reward-test-attended-20260921` was not
opened for editing, checked out, tested from, or otherwise modified.

### Sources inspected and implemented

The pinned installed `polymarket-client==0.6.0` owns the following SDK
methods, request builders and reply models. Tests construct those actual
models and execute the SDK facade against closed HTTP transports. No owner
credentials, real account, live earnings or real RPC were queried here.

| Source | Exact read/query | Meaning and limitation |
| --- | --- | --- |
| Accrual rows | `SecureClient.list_user_earnings_for_day(date=D)` → `GET https://clob.polymarket.com/rewards/user?date=D&signature_type=S`, plus `next_cursor` on subsequent pages | `UserEarning`: maker, condition, asset, date, native earnings, asset rate. All returned accounts/days/assets and duplicate identities are checked. |
| Configuration cross-check | `list_user_earnings_and_markets_config(date=D)` → `GET /rewards/user/markets?date=D&signature_type=S&page_size=100`, plus cursor | `UserRewardsEarning` and nested `EarningBreakdown`/`UserRewardsConfig`; nonzero condition/asset earnings must agree with the first read. |
| Account totals | `get_total_earnings_for_user_for_day(date=D)` → `GET /rewards/user/total?date=D&signature_type=S` | `TotalUserEarning`; explicit per-asset totals must agree with account-wide rows. Omitted assets are unknown, not zero. |
| Distribution candidates | `list_activity(user=maker, activity_types=['REWARD','MAKER_REBATE'], start=A, end=min(C,now)-1, sort_by='TIMESTAMP', sort_direction='ASC', page_size=500)` → `GET https://data-api.polymarket.com/activity?user=maker&type=REWARD,MAKER_REBATE&excludeDepositsWithdrawals=false&start=A&end=E&sortBy=TIMESTAMP&sortDirection=ASC&limit=500&offset=O` | Address-scoped activity exists; a day-linked distribution read was not found. `RewardActivity`/`MakerRebateActivity` expose wallet, activity timestamp, transaction hash and amount, not earned day, accrual reference, asset contract or transfer log index. Retained as candidates; `distributions=[]`, source `UNSUPPORTED`. |
| Wallet credits | `POST https://polygon.drpc.org` JSON-RPC reads: `eth_chainId []`, `eth_getBlockByNumber ["finalized",false]`, numeric block reads, then `eth_getLogs [{address:[USDC.e,pUSD],fromBlock:hex(first),toBlock:hex(last),topics:[Transfer,null,padded_maker]}]` | Only chain 137, configured contract addresses and recipient match. Binary search establishes half-open timestamp bounds. Initial 1,000-block chunks split on explicit provider range limits. Failed chunks remain gaps. No signing/broadcast RPC method exists here. |

`D` is the frozen reward UTC day; `S` comes from the SDK's existing wallet
type, not a new override. `A` is that day's 00:00Z epoch; `C` is its end
plus 48 hours. Offset starts at zero. Exact URLs, cursor/offset values,
RPC request bodies, response hashes and observation times remain in the
produced file. All three `request_scope` objects use the reconciler's exact
maker, pUSD marker, account condition scope and required period keys. The
wallet query additionally covers USDC.e and retains it separately.

The SDK evidence is corroborated by the official
[earnings](https://docs.polymarket.com/api-reference/rewards/get-earnings-for-user-by-date),
[total earnings](https://docs.polymarket.com/api-reference/rewards/get-total-earnings-for-user-by-date),
[configuration](https://docs.polymarket.com/api-reference/rewards/get-user-earnings-and-markets-configuration)
and [activity](https://docs.polymarket.com/api-reference/core/get-user-activity)
references. The current public [v2 activity reference](https://docs.polymarket.com/api-reference/feeds/list-account-activity)
also lacks an earned-period/accrual link; its payment timestamp is not an
earned date. No invented endpoint or private UI route was tried. This agrees
with the repository's pre-existing
[activity-to-credit contract](../operations/paid-credit-activity-evidence.md#output-limits).
An address-scoped credit/activity read must not be described as absent;
the absent capability is authoritative linkage to this reward day and band.

### Evidence rules and unavoidable gaps

`re1_payout_evidence.py` attaches an in-memory sink to the existing
`OwnerVenue.set_journal` response hook; the session journal is never appended.
Response SHA-256 values cover the bytes actually received, not reserialized
SDK models. The additional request hook hashes method, raw request target
and body with LF separators, excluding credentials/headers. RPC request
hashes cover the actual serialized JSON sent. Source-level hashes bind the
ordered lists of these hashes and are explicitly labelled with that basis.
Every retained/printed structure passes the loaded secret guard.

Accruals preserve venue precision and rates. Positive closed-day rows map
to `ACCRUED`, open-day rows to `ESTIMATED`, explicit closed zero rows to
`COMPLETED_ZERO`. An explicit zero account total can establish zero for the
selected condition; an omitted total cannot. CLI prediction validation
still requires the following UTC day, so open-day mapping is tested offline.

Wallet coverage records start predecessor, first block, end successor,
finalized anchor, every queried chunk and the headers used to validate logs.
It rechecks the finalized anchor at its numeric height. Removed logs,
wrong recipient/contract/block hash, malformed quantities and duplicate
credits fail closed. Credit identity is `137:transaction_hash:log_index`;
the transaction hash is retained separately, so multiple logs are not
collapsed into one credit. No wallet credit is declared externally funded
or allocated to a distribution by inference.

Three limits remain outside this mission's authorized consumer changes:

1. Neither inspected API provides the authoritative day-to-payment link.
   The collector's distribution source stays `UNSUPPORTED`, including on
   empty queries after the cash deadline. `payout_cycle_complete` records
   deadline passage only; it does not change source status or completeness.
2. `mm_paid_incentive_evidence` accepts only native pUSD. The collector keeps
   both assets in `asset_observations`, with only pUSD in the existing matcher
   rows. It never relabels USDC.e. Sub-micro-unit venue estimates remain
   unrounded and can be refused by the exact-micro-unit consumer.
3. The matcher requires `cash_end_utc <= as_of_utc` and complete coverage
   through cash end. For reward day September 22, the requested cash window
   ends September 25 at 00:00Z; a September 23 observation cannot satisfy
   this unchanged contract even if a real payment has appeared.

There has been no authoritative day-linked distribution observation, so the
window is not extended beyond end plus 48 hours. Future support needs an
actual venue-earned-period reference, then a reviewed producer mapping;
the collector supplies no manual bypass or fabricated substitute.

### Tests and owner run card

The focused source/SDK/evidence tests pass **58 tests**. The positive
round-trip control uses real SDK earnings models and raw hex `eth_getLogs`
replies, then **explicitly supplies a synthetic normalized distribution in
the test only**. The real reconciler returns paid `1.25`, and the unchanged
RE-1 verdict returns `k=0.625`, `PAID_AS_MODELLED`. Removing block chunk
coverage returns paid/k unknown and `INCONCLUSIVE`, never zero or NOT_PAID.
Without that synthetic missing source, the actual collector output refuses
in both cases. This is conditional matcher qualification, **not** the
unavailable all-real-SDK positive round trip requested by 85a.

Other tests cover adaptive range caps, finalized boundaries, future blocks,
scope/total mismatches, repeated cursors, read failures, omitted asset totals,
sub-micro precision, malformed/removed/duplicate logs, guard refusal, exact
wire hashes, immutable output in the fixed campaign and `collect-payout`'s
printed raw-file hash. The fake client raises on every non-read method;
closed HTTP transports reject all non-GET venue requests. Public RPC POSTs
are restricted to the three read methods above.

The owner runs these commands from the **new evidence worktree** after the
session's prediction is frozen. Replace the paths with the exact prediction
and evidence filenames printed by the two commands; do not guess an attempt
number or use an earlier session's evidence.

```powershell
Set-Location 'C:\Users\Michael\Documents\github\weather\scratch\w\re1-payout-evidence-20260921'
$re1Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
$re1Prediction = Read-Host 'Paste the exact frozen prediction.json path'
& $re1Python -m weather.market.re1_attended_cli collect-evidence $re1Prediction
$re1Evidence = Read-Host 'Paste the printed payment_evidence_path'
& $re1Python -m weather.market.re1_attended_cli collect-payout $re1Prediction --payment-evidence $re1Evidence
```

The fixed campaign root is resolved from the attending Windows token, not
the execution worktree or a caller-supplied directory. `collect-evidence`
loads credentials only after validating the prediction/journal and campaign
path, writes exactly one new timestamped file with `write_new`, closes the
client, prints its path/hash and currently exits **2** for incomplete evidence.
Each rerun produces a new file. There is presently **no complete file to
choose** from this collector; repeated collection alone cannot resolve the
distribution limitation. `collect-payout` prints the exact input path/hash
and remains inconclusive. Neither command changes the frozen prediction.

Qualification completion, source commit and repository roll-verdict output
are appended below after the final checks. Full-suite work uses the shared
workstation wrapper and must finish outside September 22 09:00–19:00 Eastern.

What was not done: no owner `.env` read, secret export, vault access,
authenticated account call, live public-account query, real RPC, heartbeat,
signature, order, cancel, stream, session, production-host access, capture or
Scheduler change, restart, merge, gate change or live authority change.
`re1_attended.py`, `re1_resilience.py`, `re1_owner_checks.py`,
`re1_transport.py`, `re1_evidence.py` and the reconciler are unchanged.
Measured economic sample: **zero real dates, zero real markets, zero real
payments**; no interval, profitability claim or campaign decision is made.

### 85a final qualification and handback

Qualified source commit: `ba219032fee00c76f375cf12a94c3dc158c617f1` on
`codex/re1-payout-evidence-20260921`, based exactly on `7e6e1709c`.
The final follow-up commit appends documentation only; source and tests stay
at this qualified commit. Draft [PR 82](https://github.com/michaelbooth1/weather/pull/82)
targets the declared parent branch/PR 78, not master.

The full workstation suite passed **7,191 tests, 991 subtests; 34 skipped,
13 warnings**, in **3,963.09s (1:06:03)**. The workload wrapper returned exit 0.
It ran on the clean source commit above from September 21 **21:08:06 Eastern**;
the JUnit receipt was written at **22:14:09 Eastern**, with successful wrapper
exit observed by **22:14:45 Eastern**. Thus the entire run finished the night
before September 22's excluded 09:00–19:00 interval. Warnings concerned empty
imputation features and a NumPy binary-size warning in an existing source test.
The three mission-owned pytest temporary trees were removed after completion;
the JUnit and CI receipts remain in this worktree's ignored `scratch/` directory.

The focused run passed **58 tests in 4.78s**; the expanded evidence,
transport, payment-activity, import-boundary and module-size selection passed
**306 tests in 26.78s**. Compilation of `app src tests`, the agent documentation
audit, generated-backlog check, both collection CLI help commands and
`git diff --check` passed. No owner credentials are loaded by the help commands.

Retained local JUnit receipts (paths relative to this evidence worktree):

| Receipt | SHA-256 |
| --- | --- |
| `scratch/re1-85a-focus1.xml` | `cb33c8114201e27710268ffd62c9dacbb720eae006d18f280ebb5ae50733e7f5` |
| `scratch/re1-85a-architecture.xml` | `5f89a8ceb0df3361ff6fade13fb485951bf31683101013186ce2bcef8a77ee7c` |
| `scratch/re1-85a-full.xml` | `24a8e2177497fe32ab19d5fb9b60207d89566559b883f71cec1e9db86e60e73a` |

The full-suite reproduction command below is for this workstation only.
The production host must use its own admitted bounded-suite procedure.
The September 22 09:00–19:00 Eastern full-suite exclusion remains binding.

```powershell
Set-Location 'C:\Users\Michael\Documents\github\weather\scratch\w\re1-payout-evidence-20260921'
$re1Repo = (Get-Location).Path
$re1Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
$re1TestArgs = @('-m', 'pytest', '-q', '--basetemp=C:/tmp/weather-re1-85a-full', '--junitxml=scratch/re1-85a-full.xml')
$re1EncodedArgs = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $re1TestArgs -Compress)))
& "$re1Repo\scripts\ops\workstation_heavy.ps1" -Kind pytest -PythonPath $re1Python -ArgumentsBase64 $re1EncodedArgs -RepoRoot $re1Repo
& $re1Python -m weather.operations.agent_docs_audit
& $re1Python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
```

**CI is not green.** Source commit `ba219032` passed Windows
[native-launch qualification](https://github.com/michaelbooth1/weather/actions/runs/35674788378).
Its [Linux CI run](https://github.com/michaelbooth1/weather/actions/runs/35674788384)
reported **30 failed, 6,626 passed, 529 skipped, 989 subtests passed**.
The 30 failed test node IDs exactly match the
[parent run at `7e6e1709c`](https://github.com/michaelbooth1/weather/actions/runs/35668138811):
missing optional `httpx`/`polymarket` dependencies, with a cascading cleanup
assertion. Comparing the sorted failed-node lists produced no differences.
The failing tests, dependency declarations and CI workflow are byte-unchanged
from the parent. The new SDK-only tests skip in that Linux environment and
are exercised locally against installed SDK 0.6.0. Repairing the inherited CI
dependency setup requires its owning mission; those files were not taken.

Retained failed-job logs: `scratch/re1-85a-parent-ci.txt`, SHA-256
`d5d4921aa4e8fd06b0d5796cbc1746a821689fee8b4b5c9cd57f49e5503ebcee`;
`scratch/re1-85a-source-ci.txt`, SHA-256
`1e614f825812ff58712405a4d58e5f401f06b1b30d9970580521840c45136e79`.
The linked runs qualify the source commit, not the later documentation-only tip.

The repository-owned roll check was run read-only:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/ops/roll_verdict.ps1 -Branch codex/re1-payout-evidence-20260921 -Base 7e6e1709c -JsonOut scratch/re1-85a-roll-verdict.json *> scratch/re1-85a-roll-verdict.txt
```

It returned **exit 1, UNDECIDABLE: no live closure evidence** for snapshot,
CLOB, observation-trigger or enrichment. It did not emit the JSON file.
The text receipt has SHA-256
`9259f6be9d32028d609f5eb2f3a41f7f7970af6045ba92f0436b41316a0bf8a0`.
No frozen mirror or production evidence was read to manufacture a verdict.

| Changed file | Per-file disposition |
| --- | --- |
| `src/weather/market/re1_payout_evidence.py` | Live closure membership unavailable; no roll-free claim |
| `src/weather/market/re1_attended_cli.py` | Live closure membership unavailable; no roll-free claim |
| `tests/market/test_re1_payout_evidence.py` | Offline regression evidence; no live closure measurement |
| `tests/market/test_re1_sdk_shapes.py` | Offline SDK-shape evidence; no live closure measurement |
| `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` | Documentation; no runtime adoption |
| `docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md` | Documentation; no runtime adoption |

No schema-registry file changed. The complete six-file stacked diff was
reviewed against the refreshed declared parent. Branch publication and the
draft PR are the handback boundary; adoption needs the operations owner's
fresh closure verdict. The missing authoritative distribution source remains
the reason an actual paid RE-1 verdict cannot be produced.

## 85b — reviewed reward-day linkage, 2026-09-21 (night)

**IMPLEMENTED: the real collector now produces paid or closed-window unpaid
evidence under the explicitly reviewed RE-1 rule; 332 focused and regression
tests pass. No real payout or profit is proved.** Final full-suite qualification,
source commit, CI and roll-verdict receipts are appended below when complete.
This supersedes 85a's producer limitation for RE-1 only, not the pure bridge's
refusal to invent an authoritative earned-period reference.

Task source: `workstation-handoff-2026-09-85b-link-the-reward-payment-to-its-day.md`
at `91b29bda89382c8f6796f87b267962729893df87`. New branch
`codex/re1-payout-link-20260922` starts exactly at
`045a100edc44f4c241ed384cb0c7e74d422d3aec` in
`scratch/w/re1-payout-link-20260922`; its draft PR targets PR 82. The execution
worktree `scratch/w/reward-test-attended-20260921` was not edited, checked out,
tested from or otherwise changed. Its `7e6e1709c` authority remains separate.

### Producer rule and diagnostics

The implementation records
`linkage_basis: exact_amount_single_condition_unique_credit_v0.1` and
`venue_earned_period_reference: false`. It is the reviewed producer decision
specified by 85b, not a newly discovered endpoint or venue-issued day reference.
No source/API research or owner-account collection was repeated for this task.

Final earnings require `accruals.status == OBSERVED`, `complete == true`, both
asset totals and only `ACCRUED`/`COMPLETED_ZERO` pUSD rows. Nonzero earnings in
any other condition, including sub-micro amounts in either asset, refuse the
rule. Native rows and totals must agree before rounding. `amount` uses
`ROUND_HALF_EVEN` at six decimals; `venue_amount` preserves the unrounded value.
`A` is the integer sum of quantized pUSD rows and must be positive.

`list_activity` now requests `type=REWARD` only, maker-scoped over
`[D+1 00:00Z, min(D+3 00:00Z, collection time))`; the integer API end is the
exclusive bound minus one second. Other pagination/query parameters and raw
request/response hashing are unchanged. `activity_request_scope` records
these actual bounds separately from the reconciler's normalized `request_scope`
for the reward-day/cash period. No source scope validator was altered.

Each activity transaction must join exactly one confirmed pUSD wallet credit.
Candidates retain `join_status` and `matching_credit_ids`; zero or multiple
matches retain `unjoined` and refuse with `activity_credit_join_failed`.
Exactly one candidate may satisfy `abs(C-A) <= 1` micro-unit. Every pUSD credit
must then be accounted for; unexplained credits are never automatically
excluded. Even another REWARD-joined candidate is not silently assigned to
another day. It remains in the file and the existing
`wallet_credit_unattributed` check keeps the verdict inconclusive.

On success the positive selected-condition accrual receives one distribution
with its `accrual_id`, the credit's actual `amount` and
`credit_id=137:<transaction_hash>:<log_index>`. `distribution_id` is `reward-`
plus the first 48 hex characters of the digest of day, transaction and log
index. Extra fields are `linkage_basis`, `activity_sha256`,
`activity_timestamp_utc` and `matched_amount_delta_units`. The distribution's
`source_record_sha256` binds the retained activity response bytes; it does not
pretend the venue supplied the derived distribution. Zero rows in other
conditions receive no fabricated distribution.

The distribution source becomes `OBSERVED`, complete, pagination-complete and
payout-cycle-complete, with coverage through the lesser of cash end and the
activity observation. The composed source's observation time also follows the
wallet read; `activity_observed_at_utc` retains the actual activity observation.
Incomplete wallet coverage, invalid activity scope or failed reads cannot
establish payment or absence. `NOT_PAID` additionally requires cash-window
closure, positive `A`, no REWARD rows and no credits in either asset.

`payout_diagnostics` is retained by `collect-evidence` and included in both
the saved and printed `collect-payout` result for every verdict. Its fields are
`reward_day`, `accrual_total_venue`, `accrual_total_units`,
`other_condition_accruals` (`count`, `total` by native asset),
`reward_activity_rows` (`timestamp_utc`, `transaction_hash`, `amount`),
`pusd_credits_in_window` / `usdc_e_credits_in_window` (`credited_at_utc`,
`transaction_hash`, `log_index`, `amount`), `linkage_rule_outcome` and
`cash_window_closed`. Missing totals remain unknown. The outcome names the
first failed check, `matched`, or the completed absence result `not_paid`.
All output still passes the loaded secret guard.

### Observed offline round trips

The positive distribution fixture from 85a is removed. These tests use actual
SDK 0.6.0 reply models through closed SDK transports and hex-shaped Polygon
RPC replies, then call the real collector, reconciler and RE-1 verdict. The
test inputs are synthetic account evidence; no distribution row is inserted
by a fixture.

| Required case | Observed output |
| --- | --- |
| 1. One REWARD/credit of A=1.250000 | `paid=1.25`, `k=0.625`, `PAID_AS_MODELLED`; linkage basis retained |
| 1. C=A-1 micro-unit | Complete reconciliation, `PARTIALLY_PAID`, `paid=1.249999`, `k=0.6249995`, `PAID_AS_MODELLED` |
| 2. C=A+1 | `PAID`, `paid=1.250001`, `k=0.6250005`, `PAID_AS_MODELLED` |
| 2. C=A+2 | `no_amount_match`, `INCONCLUSIVE`, paid/k unknown; diagnostics retain A=1250000 units and C=1.250002 |
| 3. Two matching REWARD credits | `ambiguous_amount_match`, `INCONCLUSIVE` |
| 4. Nonzero second condition in either asset | `other_condition_accruals`, `INCONCLUSIVE`; even 0.0000001 is not discarded |
| 5. Closed, empty activity and both credit sources | `not_paid`, reconciler `UNPAID`, `paid=0.0`, `NOT_PAID` |
| 6. USDC.e credit with no pUSD/activity | `non_pusd_credit_present`, `INCONCLUSIVE`; USDC.e diagnostic row retained |
| 7. REWARD transaction has zero or two credits | `activity_credit_join_failed`, `unjoined`, `INCONCLUSIVE` |
| 8. One missing block chunk | `wallet_coverage_incomplete`, `INCONCLUSIVE`, paid/k unknown |
| 9. Read-only surface | Fake client rejects every non-read method; closed venue transports reject non-GET requests; RPC remains limited to three reads |

Additional checks preserve 85a's wire hashes, range splitting, finality,
malformed logs, scope failures, exclusive campaign output and secret guards.
They also cover half-even ties, a total mismatch that would disappear after
rounding, wrong activity programme/window, incomplete empty reads, unexplained
credits (including extra REWARD candidates), and guarded diagnostics even on
an inconclusive result. Native totals and diagnostic sums also preserve
precision beyond Decimal's default context. The final expanded run passed
**332 tests in 13.00s**; `scratch/re1-85b-focus3.xml` SHA-256 is
`2cd3214c04852551118758752a9a7b6fba23f4d87274c8f68ba6cb9277c371f5`.

### Entire consumer diff

This is the only edit to `mm_exchange_reports.py`. The one-unit allowance is
per accrual's cumulative payments, not per distribution. Overpayment within
that bound cannot make unpaid accrued cash negative. The explicit 85b A-1
test controls the lower boundary: it remains PARTIALLY_PAID, as requested.

```diff
@@ -806,6 +806,7 @@ def reconcile_incentive_payments(evidence):
         "excluded_external_credit_ids": [], "duplicate_record_count": 0,
         "unresolved": [], "accrual_unresolved": [], "accruals_fully_paid": False,
         "blockers": [], "network_reads_performed": False,
+        "rounding_tolerance_units": 1,
     }
     unresolved = set()
     try:
@@ -880,7 +881,7 @@ def reconcile_incentive_payments(evidence):
                                "incentive_credit_precedes_accrual")
             amount = credit["amount_units"]
             paid_by_accrual[distribution["accrual_id"]] += amount
-            _incentive_require(paid_by_accrual[distribution["accrual_id"]] <= accrual["amount_units"],
+            _incentive_require(paid_by_accrual[distribution["accrual_id"]] <= accrual["amount_units"] + 1,
                                "incentive_distribution_exceeds_accrual")
             allocated_credits.add(distribution["credit_id"])
             bucket = ("portfolio_paid" if accrual["condition_id"] is None else
@@ -920,9 +921,9 @@ def reconcile_incentive_payments(evidence):
                 else:
                     amount = accrual["amount_units"]
                     totals[programme]["accrued"] += amount
-                    totals[programme]["unpaid_accrued"] += amount - paid
-                    state = "PAID" if paid == amount else "PARTIALLY_PAID" if paid else "UNPAID"
-                    if paid != amount:
+                    totals[programme]["unpaid_accrued"] += max(0, amount - paid)
+                    state = "PAID" if amount <= paid <= amount + 1 else "PARTIALLY_PAID" if paid else "UNPAID"
+                    if not amount <= paid <= amount + 1:
                         fully_paid = False
             result["accrual_states"].append({
                 "accrual_id": accrual_id, "programme": programme, "condition_id": condition,
```

### Owner run card and boundaries

For reward day September 22, collect on or after **September 25 00:00Z**;
the morning of September 25 Eastern is within that bound. Run from the new
evidence worktree after source qualification. Do not switch or edit the
attended execution worktree. Use the exact session prediction and the exact
new evidence path printed by the collector.

```powershell
Set-Location 'C:\Users\Michael\Documents\github\weather\scratch\w\re1-payout-link-20260922'
$re1Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
$re1Prediction = Read-Host 'Paste the exact frozen prediction.json path'
& $re1Python -m weather.market.re1_attended_cli collect-evidence $re1Prediction
$re1Evidence = Read-Host 'Paste the printed payment_evidence_path'
& $re1Python -m weather.market.re1_attended_cli collect-payout $re1Prediction --payment-evidence $re1Evidence
```

Each collection remains one new immutable file. An incomplete collection exits
2 and preserves its diagnostics; it cannot authorize payment or live action.
No owner `.env` read, credential export/vault access, authenticated account
call, real RPC, live session, heartbeat, order, cancel, stream, Scheduler or
production write, restart, promotion, adoption or merge was performed.
`re1_attended.py`, `re1_resilience.py`, `re1_owner_checks.py`,
`re1_transport.py`, `re1_evidence.py` and `mm_paid_credit_activity.py` are
unchanged. The bridge contract gains only the requested pointer sentence.
Measured economic sample: **zero real dates, zero real markets, zero real
payments**; no economic interval, profit estimate or campaign decision follows.

### 85b activity-query coverage refinement

Review identified a boundary case: a query launched just before cash end can
return afterward. Linkage now requires the actual `activity_request_scope`
end to reach cash end; the later response timestamp cannot extend its coverage.
Both paid and empty-window variants pass. The existing accrual payout-cycle
gate also keeps this pre-deadline scenario inconclusive; the added check
prevents the activity source itself from claiming full coverage.

The initial full run on `ce8afe372b33efdc55c875bee0a7c60ab0fa2bac` was stopped
at 33% without reported test failures to incorporate this refinement. Only
its identified pytest child was stopped; the still-running repository wrapper
performed its normal teardown and lease release, and the next wrapper admitted
successfully. That interrupted run is not a qualification receipt.
The revised focused selection passed **334 tests in 13.41s**;
`scratch/re1-85b-focus4.xml` SHA-256 is
`f4409fecfec8c4a8b79d60c06453bacc6ff935c03662cd618f06a804bcb10e44`.
The revised committed source receives a new, complete full-suite run.

### 85b strict-audit correction and approved scope extension

Linux CI on `f4407cb54810e1ca1cd6b9d2b1f63e17d200f8b6` reported the
parent's same 30 failing test nodes plus one new failure:
`tests/operations/test_schema_registry.py::TestSchemaRegistry::test_source_tree_strict_audit_has_only_explicit_exclusions`.
The required versioned linkage label was unclassified. This new failure was
not inherited and was not accepted as a baseline exception. Windows CI passed
on that source.

The owner explicitly approved the proposed additive registry entry in this
task on September 21 Eastern. `schema_registry_data.py` now classifies
`exact_amount_single_condition_unique_credit_v0.1` as a
`payout_linkage_policy_id` owned by `weather.market.re1_payout_evidence`;
it is not a serialized artifact schema. The change is **additive-only**:
one `SchemaLiteralExclusion`, no existing registration or scanner changes.
The delegation contract places the whole registry family in all four capture
closures, so this addition makes production adoption **roll-sensitive**.
Pushing this draft branch grants no integration or live authority.

The full run on `f4407cb` was deliberately stopped at 64% after CI identified
this new failure. Its verified pytest child was stopped, the wrapper completed
normal teardown, and subsequent wrapped tests admitted successfully. Neither
interrupted full run counts as qualification. The revised focused selection,
now including the strict registry audit, passed **342 tests in 12.70s**;
`scratch/re1-85b-focus5.xml` SHA-256 is
`8c052b433b33313dcdddf7f2ff17543d2eef3eb57b9a5405b5fc7d5b7ff5e93a`.
The corrected committed source receives a new complete full run.

### 85b final qualification and publication

**85b is implemented and locally qualified for operations review. The real collector-to-verdict tests produce paid or not-paid answers only under the labelled reviewed rule; no real payout or profit is proved. Production adoption is roll-sensitive, and Linux CI retains the fixed parent's 30 failures.**

Qualified source: `4bb010306bd6726ef134bf1375d96d2aebb7b734` on
`codex/re1-payout-link-20260922`, stacked exactly on
`045a100edc44f4c241ed384cb0c7e74d422d3aec`. The source and tests remained
unchanged during the complete full run. The final publication commit appends
this report only. Draft [PR 83](https://github.com/michaelbooth1/weather/pull/83)
targets `codex/re1-payout-evidence-20260921` / PR 82.

The complete full suite passed **7,219 tests, 34 skipped, 991 subtests passed,
1 warning**, in **2,872.35s (47m 52s)**. The repository wrapper returned exit 0.
The run started September 21 at **23:30:22 Eastern**; its JUnit receipt was
written September 22 at **00:18:14 Eastern**, and successful wrapper exit
was observed by **00:18:37 Eastern**. The entire run finished before the
September 22 09:00-19:00 Eastern exclusion. JUnit records zero failures and
zero errors; its 8,244 entries include the subtests and skips. The warning
was the cached-NetCDF test's NumPy binary-size RuntimeWarning; it did not fail.

The final focused selection passed **342 tests in 12.70s**, including the
strict schema audit. Compilation of
`app src tests`, the agent documentation audit, generated-backlog check, both
collection CLI help commands and cumulative diff checks passed. No protected
live-control or bridge implementation file changed. The bridge contract's
only addition is its one pointer sentence. The owner-approved registry addition
is the single policy classification recorded above; it is additive-only.

Retained local receipts (relative to this evidence worktree):

| Receipt | SHA-256 |
| --- | --- |
| `scratch/re1-85b-focus5.xml` | `8c052b433b33313dcdddf7f2ff17543d2eef3eb57b9a5405b5fc7d5b7ff5e93a` |
| `scratch/re1-85b-full3.xml` | `54128312fd223d3b1ecda2c99badf435dd20481da2505c125f65c0955630f0e5` |
| `scratch/re1-85b-approved-roll-verdict.txt` | `9259f6be9d32028d609f5eb2f3a41f7f7970af6045ba92f0436b41316a0bf8a0` |

The full run used the workstation wrapper with these arguments. These are
workstation reproduction commands; the production host must use its own
admitted bounded-suite procedure. Preserve retained receipts by choosing a
new output name for a later replay. Do not run the full suite during September
22's 09:00–19:00 Eastern exclusion interval.

```powershell
Set-Location 'C:\Users\Michael\Documents\github\weather\scratch\w\re1-payout-link-20260922'
$re1Repo = (Get-Location).Path
$re1Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
$re1TestArgs = @('-m', 'pytest', '-q', '--basetemp=C:/tmp/weather-re1-85b-full3', '--junitxml=scratch/re1-85b-full3.xml')
$re1EncodedArgs = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $re1TestArgs -Compress)))
& "$re1Repo\scripts\ops\workstation_heavy.ps1" -Kind pytest -PythonPath $re1Python -ArgumentsBase64 $re1EncodedArgs -RepoRoot $re1Repo
& $re1Python -m weather.operations.agent_docs_audit
& $re1Python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
```

CI on the qualified source: [Windows Qualification](https://github.com/michaelbooth1/weather/actions/runs/35683378868)
passed. [Linux CI](https://github.com/michaelbooth1/weather/actions/runs/35683378805)
reported **30 failed, 6,628 passed, 529 skipped, 989 subtests passed**, in
500.09s. The sorted failing-node set is exactly equal to the fixed parent's
30 failures ([parent run](https://github.com/michaelbooth1/weather/actions/runs/35679011323));
`Compare-Object` returned no differences. Those logs show missing `httpx` /
`polymarket` dependencies and their cascades. The newly introduced strict-audit
failure is fixed. This is **not a green Linux CI claim** or permission to alter
unrelated dependency configuration.

CI receipts retained locally:

| Receipt | SHA-256 |
| --- | --- |
| `scratch/re1-85b-parent-ci.txt` | `4e5e1438480953caeaafc0e98c56e7fe735780af9c886196d091f3a7028f2ec0` |
| `scratch/re1-85b-source-ci.txt` (superseded source with new audit failure) | `2f881c8d50e06425288e842b236b4a68775c9041806cb32a1ef9bbb7cc5013e6` |
| `scratch/re1-85b-corrected-ci.txt` | `db51237a377d49ce3558970e6058c0adda9c89de0618ad1e377d5de6d9af8f4f` |

The sorted `*-ci-failed-nodes.txt` files beside the logs preserve the exact
comparison. Final docs-only publication retains these source-commit CI
receipts; it does not substitute a different source qualification.

The repository-owned roll check was rerun for the revised source:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/ops/roll_verdict.ps1 -Branch codex/re1-payout-link-20260922 -Base 045a100ed -JsonOut scratch/re1-85b-approved-roll-verdict.json *> scratch/re1-85b-approved-roll-verdict.txt
```

It returned **exit 1, UNDECIDABLE: no live closure evidence** for snapshot,
CLOB, observation-trigger and enrichment; no JSON receipt was emitted.
No frozen mirror or production state was read to manufacture a verdict.

| Changed file | Per-file disposition |
| --- | --- |
| `src/weather/market/re1_payout_evidence.py` | Live closure membership unavailable; no roll-free claim |
| `src/weather/market/re1_attended_cli.py` | Live closure membership unavailable; no roll-free claim |
| `src/weather/market/mm_exchange_reports.py` | Shared consumer; live closure membership unavailable; no roll-free claim |
| `src/weather/schema_registry_data.py` | Additive-only policy classification; all four closures under delegation contract section 3; roll-sensitive |
| `tests/market/test_re1_payout_evidence.py` | Offline regression evidence; no live closure measurement |
| `tests/market/test_mm_paid_incentive_reconciliation.py` | Offline consumer boundary tests; no live closure measurement |
| `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` | Documentation; no runtime adoption |
| `docs/operations/paid-credit-activity-evidence.md` | One documentation pointer; no bridge behavior change |
| `docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md` | Documentation; no runtime adoption |

The complete nine-file stacked diff was reviewed against the refreshed
declared parent. Branch publication and the draft PR are the handback boundary;
roll-sensitive integration/adoption remains with the operations owner in the
quiet window after a fresh closure verdict. No owner credentials or real
payout evidence were read, and no
production write, registration, restart, live action or merge occurred.

## 84d — September 22, 2026: first-owner-run preflight hardening

**IMPLEMENTED; FOCUSED TESTS PASS. Full workstation qualification is pending the
owner's 19:00 Eastern boundary on September 22. No adoption or live-readiness
claim is made.**

Handoff: `workstation-handoff-2026-09-84d-preflight-hardening-from-the-first-owner-run.md`
at `827aa6a07` on `origin/codex/reward-test-attended-handoff-20260921`.
Implementation commit: `874ce5313eeecb18c300a8ba4553ace234b3d680` on
`codex/re1-preflight-hardening-20260922`, stacked exactly on
`4bb04b686cc54a78745dd1a094717f007488cca3` (85b / PR 83).
The separate implementation worktree is
`C:\Users\Michael\Documents\github\weather\scratch\w\re1-preflight-hardening-20260922`.
The draft PR targets `codex/re1-payout-link-20260922`; the following report-only
commit preserves the qualified implementation. The attended execution worktree
was not accessed or changed.

### Five bounded changes

The exact host-identity spawn argument list is:

```python
['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command, str(REPO_ROOT)]
```

`command` remains unchanged. `capture_output=True`, `text=True` and the
20-second timeout remain; `check=True` is replaced with an explicit return-code
and JSON-object/key check. Nonzero rc, empty/whitespace/non-JSON stdout,
non-object JSON or either missing identity key raises
`host_identity_query_failed: rc=<rc> stderr=<first 200 child stderr characters>`.
The host/principal assignment, Global mutex and poison-file behavior are
unchanged; the valid-query capture-host rejection is also tested.

The exact dependency line, added to both dependency declarations, is:

```text
python-dotenv==1.2.3
```

This is the version returned by `venv/Scripts/python.exe -m pip show
python-dotenv` in the RE-1 interpreter. No package was installed, and the dotenv
reader was not replaced or changed. The AST dependency audit visits imports at
every scope in `src/weather/market/re1_*.py`, resolves their top-level packages
using `importlib.metadata.packages_distributions()`, and requires a distribution
in the declared core/live dependency graph, including required transitive
dependencies of the pinned SDK. It does not accept unrelated ambient packages.
Both files must retain the exact dotenv pin. The complete audit requires the
declared live SDK environment used for this qualification.

Failure rows retain their existing keys and add the guarded, at-most-200-character
message to terminal, individual journal events, terminal journal and receipt.
`SecretGuard.clean` refuses rather than redacts secrets: if it refuses exception
text, the diagnostic is the fixed `secret_output_refused` and the receipt stays
FAIL. Close and AccountNotEmpty diagnostics use fixed strings. The pre-existing
PASS/FAIL tokens and `clean_preflight` comparison are unchanged.

No-band output is computed only from the retained selection table; it names the
highest prediction, handles unscored rows and an empty table, prints before the
public-selection failure and journals `preflight_step` / `NO_BAND` with the same
message and location/date/prediction/refusal. The receipt remains FAIL with
`public_selection` / `no_qualifying_band`, and `clean_preflight` rejects it.
The derivative heartbeat-budget failure is emitted only when `'heartbeat' in
stats` or no earlier failure exists, retaining the original eight-second gate.

These are actual captured output strings asserted and printed by the injected
no-band test, **not output from an owner/account preflight**:

```text
NO QUALIFYING BAND at 12:00Z — best austin 2026-09-23 predicted_360_minutes=1.34 (predicted_below_two); retry at the next quarter hour
{'status': 'FAIL', 'step': 'public_selection', 'exception_type': 'RuntimeError', 'message': 'no_qualifying_band'}
```

### Verification and reproduction

- Handoff-focused evidence, owner-check and parity files: **47 passed in 5.53s**.
- All eight RE-1 test files plus import architecture: **214 passed in 146.33s**;
  no failures or skips. This includes the same 47 tests, not 261 distinct tests.
- Compilation of the four changed Python files: PASS through the workstation wrapper.
- Agent documentation audit: PASS; generated-backlog `--check`: PASS;
  cumulative diff checks: PASS.
- Full suite and full-tree compilation: **not run yet**. The September 22
  09:00–19:00 Eastern exclusion remains in force. Parent full-suite counts are
  not claimed as qualification of this change.

Both pytest runs used the repository-owned workstation mutex/Job wrapper,
the main project's RE-1 interpreter, explicit temporary roots outside `data`,
and JUnit receipts. Completed task-owned temporary roots were removed after
terminal wrapper exit. Free space was 174,000,877,568 bytes before the first
run and 173,995,606,016 bytes after both cleanups; other host activity can also
affect those volume measurements.

Retained receipts relative to this implementation worktree:

| Receipt | SHA-256 |
| --- | --- |
| `scratch/84d-focused.xml` | `dc95a9685c30b7d2a26c4d26aae0d536b45877ba866d223b9431269263224ffb` |
| `scratch/84d-regression.xml` | `9721f48e883fbc299df4cf31bd1f75967fcc9ab899f24ffd3b3110cf192ff53c` |
| `scratch/84d-roll-verdict.txt` | `9259f6be9d32028d609f5eb2f3a41f7f7970af6045ba92f0436b41316a0bf8a0` |

Reproduce the focused selection from the implementation worktree with its
`scripts/ops/workstation_heavy.ps1`, `-Kind pytest`, the absolute RE-1
`-PythonPath`, and that worktree's absolute `-RepoRoot`. Encode this JSON array
as UTF-8 base64 for `-ArgumentsBase64`; choose fresh task-owned receipt/temp names
instead of overwriting retained evidence:

```json
["-m", "pytest", "tests/market/test_re1_attended.py", "tests/market/test_re1_evidence.py", "tests/market/test_re1_owner_checks.py", "tests/market/test_re1_resilience.py", "tests/market/test_re1_transport.py", "tests/market/test_re1_sdk_shapes.py", "tests/market/test_re1_attended_parity_audit.py", "tests/market/test_re1_payout_evidence.py", "tests/operations/test_import_architecture.py", "-q", "--basetemp=C:/Users/Michael/Documents/github/weather/scratch/84d-regression-temp", "--junitxml=scratch/84d-regression.xml"]
```

Use the capture host's admitted bounded-suite path for any production-host
verification; these commands qualify only the non-capture workstation.

### Roll disposition and exclusions

The repository-owned check was run against the exact stacked base:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/ops/roll_verdict.ps1 -Branch codex/re1-preflight-hardening-20260922 -Base 4bb04b686 -JsonOut scratch/84d-roll-verdict.json
```

It returned **exit 1, UNDECIDABLE: no live closure evidence** for snapshot,
CLOB, observation-trigger and enrichment. No JSON receipt was emitted. No
production or frozen-mirror closure evidence was accessed; operations must
obtain a fresh production verdict before any integration.

| Changed file | Per-file disposition |
| --- | --- |
| `src/weather/market/re1_evidence.py` | Live closure membership unavailable; no roll-free claim |
| `src/weather/market/re1_owner_checks.py` | Live closure membership unavailable; no roll-free claim |
| `requirements.txt` | Dependency declaration only; runtime adoption not performed |
| `pyproject.toml` | Dependency declaration only; runtime adoption not performed |
| `tests/market/test_re1_evidence.py` | Offline regression evidence; no live closure measurement |
| `tests/market/test_re1_owner_checks.py` | Offline regression evidence; no live closure measurement |
| `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` | Run-card documentation; roll-free by standing contract |
| `docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md` | Append-only handback; roll-free by standing contract |

**Not done:** no real `preflight`, `live`, account or payout collection; no owner
`.env` read, credential loading or package/environment installation; no persistent
execution-policy change; no change or command in
`scratch\w\reward-test-attended-20260921`; no controller, resilience, public-book,
selection, sizing, payout, reconciler, schema-registry or attempt-accounting
change; no production write, Scheduler registration, restart, merge or adoption;
no full suite before 19:00 Eastern. Adoption remains the owner's decision and
requires a fresh same-day preflight at any newly approved execution tip.

## 84e — September 22, 2026: identify public reads and stop blocked preflight early

**IMPLEMENTED; REAL PUBLIC PROBES PASS WITH THE DESCRIPTIVE USER-AGENT; 69 FOCUSED
TESTS PASS. No real preflight or live session was run. Full-suite qualification
is not claimed; the owner's no-full-suite-before-19:00-Eastern boundary remains.**

Owner instruction: Mission 84e in this task. Branch
`codex/re1-public-reads-ua-20260922` is stacked exactly on
`7010a0b585e1d6f31787a34e84bbf11d80939bd3` (84d), in the existing 84d worktree
`C:\Users\Michael\Documents\github\weather\scratch\w\re1-preflight-hardening-20260922`.
The owner explicitly requested reuse of that worktree and this append-only
section; 84d's branch, commits, prior report and changes remain intact.
Implementation commit: `5b01a80b922b1342e4b7db878fb85ea6a76e1a2d`.
The following report-only commit is the handback tip; resolve it from the exact
published branch. The draft PR targets `codex/re1-preflight-hardening-20260922`.

### Public probe evidence, before publication

The initial clean-base comparison ran at **2026-09-22 17:06:09 UTC / 13:06:09
Eastern** on this workstation with CPython 3.11.9. It called the existing
`json_read` with only the Request User-Agent changed for the new-header arm.
The committed implementation comparison ran at **17:11:08 UTC / 13:11:08
Eastern**. It called the committed `json_read` unchanged for the new-header
arm; the old-header control removed only User-Agent immediately before real
`urllib.request.urlopen`. Both comparisons retained `Accept: application/json`,
`Content-Type: application/json`, the two-second timeout, JSON encoding, response
size limit, exact-final-URL check and status/JSON checks.

| Clean commit / User-Agent | GET `https://polymarket.com/api/geoblock` | POST `https://polygon.drpc.org` (`eth_blockNumber`) |
| --- | ---: | ---: |
| 84d `7010a0b58`; old implicit `Python-urllib/3.11` | HTTP 403 | HTTP 403 |
| 84d `7010a0b58`; `weather-re1-attended/7010a0b58` | HTTP 200; `json_read` PASS | HTTP 200; `json_read` PASS |
| 84e source `5b01a80b9`; old implicit `Python-urllib/3.11` | HTTP 403 | HTTP 403 |
| 84e source `5b01a80b9`; `weather-re1-attended/5b01a80b9` | HTTP 200; `json_read` PASS | HTTP 200; `json_read` PASS |

Exact header line measured on the implementation commit:

```text
User-Agent: weather-re1-attended/5b01a80b9
```

Exact implementation expression:

```python
'User-Agent': 'weather-re1-attended/' + code_identity()[:9]
```

The suffix follows the current clean commit, including a subsequent report-only
tip; it is not hard-coded to the source commit. The RPC body in every POST was:

```json
{"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
```

The Mozilla-compatible fallback was **not needed or tried** because the first
descriptive form succeeded on both URLs. No provider, key, proxy, tunnel or TLS
setting was changed. HTTP 200 here establishes public transport access only;
it does not claim geographic eligibility, account readiness or permission to trade.

### Failure behavior and verification

After the existing host/proxy/clean-tip gate and before loading credentials,
building a client, selecting a band, opening a stream or entering any 20-read
loop, `run_preflight` probes geoblock once, then the fixed Polygon RPC once.
The first HTTP error stops the sequence immediately, closes the error response,
and records one `public_read_probe` failure with the message
`public_read_blocked: <url> -> HTTP <code>`. The terminal prints exactly one
message-bearing FAIL row, including the receipt path. The journal and receipt
retain the same cause; latency/timeout maps remain empty and `clean_preflight`
rejects the receipt. 84d's no-band, guarded-message and heartbeat-budget behavior
is preserved, as are later geography and repeated-read gates.

- **69 passed in 10.63s**, no failures or skips: transport, owner-check,
  attended parity-audit and import-architecture files. New coverage inspects
  actual Request objects via monkeypatched `urlopen` for both GET and POST;
  six injected failures cover both URLs at HTTP 403, 429 and 503. The success
  path proves two probes precede the existing read counts. No test uses real auth.
- Compilation of the four edited Python files: PASS through the workstation
  wrapper. Full suite and full-tree compilation: not run.
- Agent docs audit: PASS (18 agent files, 912 Markdown files); generated-backlog
  `--check`: PASS; cumulative diff check and exact-base ancestry: PASS.
- Tests and compilation used `scripts/ops/workstation_heavy.ps1` with its
  host/principal, shared mutex and Job checks. The explicit task-owned pytest
  temporary directory was removed after the wrapper's terminal exit.

Focused reproduction: use the implementation worktree's workstation wrapper
with `-Kind pytest`, absolute RE-1 `-PythonPath` and absolute `-RepoRoot`, encoding
the following array as UTF-8 base64 for `-ArgumentsBase64`; use fresh receipt
and temporary names on repeat runs:

```json
["-m", "pytest", "tests/market/test_re1_owner_checks.py", "tests/market/test_re1_transport.py", "tests/market/test_re1_attended_parity_audit.py", "tests/operations/test_import_architecture.py", "-q", "--basetemp=scratch/84e-focused-temp", "--junitxml=scratch/84e-focused.xml"]
```

Public-only reproduction from a clean approved checkout is `json_read(GEOBLOCK)`
and `json_read(RPC, body={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber",
"params": []})` from `weather.market.re1_transport`. The retained scratch probe
script also compares the old header and prints only request identity/status,
never response bodies. The actual workstation command was:

```powershell
Get-Content -Raw scratch/84e_public_probe.py | C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe -
```

Retained local receipts, relative to the implementation worktree (not assumed
to exist in a clean checkout):

| Receipt | SHA-256 |
| --- | --- |
| `scratch/84e-public-probes-base.jsonl` | `514ed6b1c7f3472364b8577db1390d3574f290978cbe57826d972588ab1b46bb` |
| `scratch/84e-public-probes-implementation.jsonl` | `ced15c12747977b66fb2cf55128a30603fae455289db9a1bd0f77bb3b39cf8c2` |
| `scratch/84e_public_probe.py` | `4733897c4857e6991bee5e5334139cd9c2a647073c11cbe93b617b9da398e5df` |
| `scratch/84e-focused.xml` | `2afa2836ca0a5377ba6a23f79612ba5bf06f3092bd8957023ef399fc46b750fd` |
| `scratch/84e-roll-verdict.txt` | `9259f6be9d32028d609f5eb2f3a41f7f7970af6045ba92f0436b41316a0bf8a0` |

### Roll disposition and exclusions

`scripts/ops/roll_verdict.ps1 -Branch codex/re1-public-reads-ua-20260922
-Base 7010a0b58 -JsonOut scratch/84e-roll-verdict.json` returned **exit 1,
UNDECIDABLE: no live closure evidence** for all four supervisors; no JSON
receipt was emitted. No production or frozen-mirror evidence was consulted.

| Changed file | Per-file disposition |
| --- | --- |
| `src/weather/market/re1_transport.py` | Live closure membership unavailable; no roll-free claim |
| `src/weather/market/re1_owner_checks.py` | Live closure membership unavailable; no roll-free claim |
| `tests/market/test_re1_transport.py` | Offline regression evidence; no live closure measurement |
| `tests/market/test_re1_owner_checks.py` | Offline regression evidence; no live closure measurement |
| `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` | Run-card documentation; roll-free by standing contract |
| `docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md` | Append-only handback; roll-free by standing contract |

**Not done:** no real preflight, live, credential/account/payout read, `.env`
access, provider switch, API key, order, heartbeat or cancel request; no command
or edit in `scratch\w\reward-test-attended-20260921`; no full suite, production
write, Scheduler registration, restart, merge or adoption. The owner runs the
fresh preflight tomorrow morning on the newly approved tip. Production
integration still needs a fresh closure verdict from operations.

## 84f — September 22, 2026: selected-condition accrual and cached User-Agent

**IMPLEMENTED; 180 FOCUSED TESTS PASS. Full suite is pending one run after
19:00 Eastern on the published 84f tip, with its result reported separately.
No real preflight or live session was run.**

Executed the owner's pinned handoff
`workstation-handoff-2026-09-84f-selected-condition-accrual-and-a-cached-user-agent.md`
from `origin/codex/reward-test-attended-handoff-20260921` at `472856011`.
Implementation commit: `20b73c3a95e9b8e4729bd88332d88a06df7b5cfb`, an additive
commit on `c190fb10bfeb615b3f8f5ba27d9b5a0fdeba1e31`. Branch remains
`codex/re1-public-reads-ua-20260922`; existing draft PR 85 remains stacked on
`codex/re1-preflight-hardening-20260922` (`7010a0b58`). The report-only commit
containing this section is the handback tip; its exact hash is returned to the
owner after normal push and remote-ref verification. No history was rewritten.

### Implemented behavior and reader trace

- `re1_transport.py:142` validates one public GET to exactly
  `https://clob.polymarket.com/rewards/markets/<condition>`, using `json_read`.
  `data` must be a list with zero or one row, `count == len(data)`,
  `next_cursor == 'LTE='`, and `limit` an integer (not bool) in 1..500.
  Invalid envelopes raise `RuntimeError('condition_config_unreadable')`.
  `OwnerVenue.accrual` at line 359 refuses `condition=None` with
  `RuntimeError('condition_required')` before any read, retains the list under
  `market_configurations`, and preserves earnings rows, totals, percentages,
  day and `payment_verified=False`.
- Only `collect_accruals` changed in `re1_payout_evidence.py` (line 170).
  It uses the same helper once for `scope['condition_id']` and keeps
  `retained['market_configurations']` as the public row list. The removed
  universe-configuration earnings cross-check depended on the retired
  user-specific response; account earnings and native-precision totals still
  undergo the unchanged `normalize_earnings` checks. `read_pages`, row budgets,
  pagination budgets, activity and wallet reads are unchanged.
- Optional `json_read` journaling retains the header-free GET request hash and
  the SHA-256 of the actual response bytes under
  `/rewards/markets/<condition>`. The existing `sdk_response` event contract
  keeps `ReadJournal.last_response_hash` and source summaries binding those
  bytes. Regression coverage compares both hashes to mock transport bytes,
  checks exactly one selected-condition request, and retains malformed
  configuration envelopes while refusing complete accrual evidence.
- `link_reward_payment` (`re1_payout_evidence.py:225`) reads
  `raw_earnings.get('rows')` at line 231; it does not consume
  `market_configurations`. The pure `reconcile_incentive_payments`
  (`mm_exchange_reports.py:793`) loads normalized `accruals`, `distributions`
  and `wallet_credits` at lines 828-832, plus scope/source provenance.
  It does not interpret configurations for payment decisions; its whole-input
  JSON hash/size check at lines 817-821 naturally includes retained evidence.
  Neither reader nor the reviewed 85b linkage rule was modified.
- `_user_agent` (`re1_transport.py:114`) caches the first successful
  `code_identity()` using `lru_cache(maxsize=1)`. Format stays
  `weather-re1-attended/<first-nine-of-HEAD>`. The first read still enforces
  clean identity; later reads reuse it. The ten-read regression at
  `test_re1_transport.py:106` proves **10 requests, 1 identity call**, with an
  identity stub that would raise `preflight_requires_clean_tip` if called again.
  The separate first-read test proves dirty identity prevents any request.

### Focused verification and deferred qualification

**180 passed in 15.26s; zero failures, errors or skips**, through this worktree's
`scripts/ops/workstation_heavy.ps1`, wrapper exit 0. The fake preflight fixture
retains its fake accrual implementation and proves 20/20 accrual reads plus a
20-read latency receipt. `test_re1_attended_parity_audit.py` is unchanged and
passed. SDK-shape, payout round-trip, downstream evidence and import-architecture
coverage also passed. Test transports are closed mocks; no venue/account call
was made. The task-owned temporary tree was removed after terminal wrapper exit.
C: free bytes before/after: 172982558720 / 172983324672.

Focused reproduction from the implementation checkout: use its
`scripts/ops/workstation_heavy.ps1 -Kind pytest`, the absolute project
`venv/Scripts/python.exe` as `-PythonPath`, and the absolute checkout as
`-RepoRoot`. Encode this JSON array as UTF-8 base64 for `-ArgumentsBase64`:

```json
["-m","pytest","tests/market/test_re1_transport.py","tests/market/test_re1_payout_evidence.py","tests/market/test_re1_owner_checks.py","tests/market/test_re1_attended_parity_audit.py","tests/market/test_re1_sdk_shapes.py","tests/market/test_re1_evidence.py","tests/operations/test_import_architecture.py","-q","--basetemp=scratch/84f-focused-temp","--junitxml=scratch/84f-focused.xml"]
```

Retained JUnit: `scratch/84f-focused.xml`, SHA-256
`5f873c518ef663dbbc7b7571e925526759a7369a858288009155ff5342577c59`.
The full-suite count is **pending**, not inferred from focused tests or CI.
The obsolete 19:05 run on `7010a0b58` was paused in Codex. One replacement
follow-up will run the full suite on the exact published 84f tip after 19:00
Eastern on September 22 and append its separate result here. No second suite
or automatic repair is authorized by that follow-up.

### Roll disposition and exclusions

`scripts/ops/roll_verdict.ps1 -Branch codex/re1-public-reads-ua-20260922
-Base c190fb10b -JsonOut scratch/84f-roll-verdict.json` returned exit 1:
**UNDECIDABLE: no live closure evidence**. No JSON receipt was emitted.
`scratch/84f-roll-verdict.txt` SHA-256:
`9259f6be9d32028d609f5eb2f3a41f7f7970af6045ba92f0436b41316a0bf8a0`.
Production operations must obtain a fresh verdict before integration.

| Changed file | Per-file disposition |
| --- | --- |
| `src/weather/market/re1_transport.py` | Live closure membership unavailable; no roll-free claim |
| `src/weather/market/re1_payout_evidence.py` | Live closure membership unavailable; no roll-free claim |
| `tests/market/test_re1_transport.py` | Offline regression evidence; no live closure measurement |
| `tests/market/test_re1_payout_evidence.py` | Offline regression evidence; no live closure measurement |
| `tests/market/test_re1_owner_checks.py` | Offline regression evidence; no live closure measurement |
| `docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md` | Append-only handback; roll-free by standing contract |

**Not done:** no real preflight, live, public probe, account/payout collection,
`.env` or credential access, RPC/provider/key change, order, heartbeat or cancel
request; no selection, sizing, attempt accounting, controller, resilience,
public-book, reconciler or 85b-rule change; no execution-worktree access/change,
production write, frozen-mirror evidence access, Scheduler registration, restart,
merge or adoption; no full suite before 19:00 Eastern. The implementation
worktree remains `scratch/w/re1-preflight-hardening-20260922`; the 09-21
execution worktree remains untouched.

## 84f — September 22, 2026, evening: one full-suite result

**FULL-SUITE QUALIFICATION FAILED: 360 failed, 6904 passed, 33 skipped,
991 subtests passed, 1 warning, zero collection/runtime errors reported by
JUnit. Wrapper exit 1. No second run or repair was performed.**

This is the separately reported single full-suite run authorized after 19:00
Eastern. Tested commit: `475a626e4abd1c4f5824544078d0eccbf2156116`;
tree: `b4e00b4e5e29380f1b6adc57835bf7d866bdfe12`; branch:
`codex/re1-public-reads-ua-20260922`, still attached to draft PR 85.
HEAD, branch, local date/time and clean tracked/untracked status were verified
before launching. HEAD and clean status remained unchanged after the run and
temporary-directory cleanup. This report-only follow-up does not change the
tested implementation.

### Timing, command and containment

- Started: **2026-09-22 19:02:35.5844414 Eastern / 23:02:35.5844414 UTC**.
- Wrapper terminal exit: **19:38:24.5163009 Eastern / 23:38:24.5163009 UTC**.
- Pytest summary time: **2138.72 seconds (35m 38s)**. Wrapper wall time:
  **2148.9318595 seconds**. JUnit records 8288 cases, including the 991 passing
  subtests, 360 failures, 33 skips and 0 errors.
- Exactly one full pytest invocation ran through this worktree's
  `scripts/ops/workstation_heavy.ps1`, with `-Kind pytest`, the project
  `C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe`, and
  absolute `-RepoRoot`
  `C:/Users/Michael/Documents/github/weather/scratch/w/re1-preflight-hardening-20260922`.
  Its host/principal, shared mutex, poison and kill-on-close Job controls were
  retained. No admission bypass or recovery was performed.
- A create-only `scratch/84f-full-attempted.json` was flushed before invoking
  the wrapper. The log, result receipt and JUnit are retained. The executor
  session was polled to terminal exit before cleanup.
- Only the resolved, non-reparse task-owned `scratch/84f-full-temp` root was
  recursively removed. Removal was verified at **23:41:14.8427667 UTC**.
  C: free bytes: **170956365824 before**, **160815882240 after wrapper exit**,
  **168336728064 after cleanup**. These are volume observations, not an
  attribution of every concurrent disk change.

Exact pytest arguments executed:

```json
["-m","pytest","-q","--basetemp=scratch/84f-full-temp","--junitxml=scratch/84f-full.xml"]
```

Literal `-ArgumentsBase64` passed to the wrapper:

```text
WyItbSIsInB5dGVzdCIsIi1xIiwiLS1iYXNldGVtcD1zY3JhdGNoLzg0Zi1mdWxsLXRlbXAiLCItLWp1bml0eG1sPXNjcmF0Y2gvODRmLWZ1bGwueG1sIl0=
```

This records the command that ran; it is not authorization for another run.

### Observed failures and limits of the result

The scheduled follow-up specified a deeply nested, in-repository temporary
root. That choice was made by the workstation agent when saving the follow-up,
not by the implementation. It made this a poor full-suite qualification
environment. Direct diagnostics include Git `Filename too long`,
`WinError 206`, an experiment claim exceeding the Windows path budget
(**270 UTF-16 units versus 259**), recovery publication requiring shorter
Windows paths, and SDK portability rejecting a bundle root inside the
repository. Many other failures report missing deeply nested fixture files or
failed fixture renames. There is also a readiness assertion comparing a
repository-relative path with an expected absolute path.

These observations establish concrete test-environment limitations; no
short-path control or baseline comparison was authorized or run, so the
report does not assert that every failure is explained by them or that the
whole implementation is qualified. No code was changed to make a gate pass.

Failure counts by module, from the retained JUnit:

| Module under `tests/` | Failures |
| --- | ---: |
| `operations/test_production_baseline_reconciler_execution.py` | 70 |
| `operations/test_cold_archive_reclaim.py` | 50 |
| `operations/test_status_script.py` | 40 |
| `operations/test_replay_cache_retention.py` | 27 |
| `operations/test_verified_cold_archive.py` | 24 |
| `operations/test_cold_archive_catalog.py` | 23 |
| `operations/test_experiment_executor.py` | 23 |
| `operations/test_documentation_transaction.py` | 16 |
| `market/test_live_sdk_portability.py` | 16 |
| `collection/test_forecast_payload_cross_process_fanout.py` | 15 |
| `operations/test_forecast_payload_cas_migration.py` | 13 |
| `sources/test_forecast_training_corpus.py` | 11 |
| `operations/test_production_baseline_reconciliation.py` | 8 |
| `calibration/test_residual_distribution_corpus.py` | 7 |
| `collection/test_shared_forecast_payload_cas.py` | 6 |
| `operations/test_storage_recovery_night_wrapper.py` | 4 |
| `operations/test_cold_archive_recovery_publication.py` | 4 |
| `market/test_market_making_readiness.py` | 1 |
| `operations/test_production_cold_archive_wrapper.py` | 1 |
| `backtesting/test_replay_cache.py` | 1 |
| **Total** | **360** |

All **217 RE-1 tests passed within this full run**, with no failures or skips:
attended 40, parity audit 5, evidence 26, owner checks 22, payout evidence 57,
resilience 19, SDK shapes 15 and transport 33. This is a subset result, not
a substitute for full-suite qualification.

The one warning was in
`tests/sources/test_reanalysis_synoptic.py::TestReanalysisSynoptic::test_load_pressure_level_daily_metrics_reads_cached_netcdf4`:
a `RuntimeWarning` reporting `numpy.ndarray size changed`, expected 16 from
the C header versus 96 from the Python object. No dependency change was made.

### Retained receipts

Paths below are relative to the implementation worktree and are ignored local
receipts, not assumed present in a clean checkout. Raw logs are not published
to Git; the report preserves their hashes and results.

| Receipt | SHA-256 |
| --- | --- |
| `scratch/84f-full-attempted.json` | `496536395eded912ecc70e4b426439739c8b66dba09f92cc54ff9cd1fdeb27bd` |
| `scratch/84f-full.log` | `44b5ed1447c727c409a5da5af2e236705f0293cb367331681750fc4fe8a49937` |
| `scratch/84f-full.xml` | `803d78835aadb6a5771df7328d661f870e2511ff4303651c6caf0388d2e30d94` |
| `scratch/84f-full-result.json` | `825361fd4cf31aa6a5c231b004d22e5c184ccfd2c9916265be4383306a600707` |
| `scratch/84f-full-cleanup.json` | `a26b748f5e5baba512fac56c011d51a2d5de408d6cb90216da787fac847784a5` |

### Disposition and exclusions

The one-time 84f automation is **PAUSED**. The cancelled 19:05 run on
`7010a0b58` was not run. The one-run allowance is consumed; a further run
requires a new owner instruction. PR 85 stays; no review was requested and
nothing was merged or adopted.

Only this report receives a tracked change, roll-free documentation by the
standing contract. The earlier UNDECIDABLE production roll disposition is not
upgraded by this run. No real preflight/live, owner `.env` or credential
access, account/public probe, production write, Windows Scheduler change,
execution-policy configuration change, execution-worktree access/change,
repair, dependency installation, focused rerun, second full suite, compileall,
audit or CI investigation was performed.

## 84g — September 23, 2026: complementary fills and the payout addendum

**PASS — all 255 focused RE-1 tests pass; complementary maker trades end as
`fill` with proven cleanup, and the frozen and amended payout verdicts are
reported side by side. No real payout was read and no live action was run.**

Authority: the owner-requested 84g handoff and September 23 payout addendum,
read with `git show` from fetched handoff commit
`48ea0144` on `origin/codex/reward-test-attended-handoff-20260921`.
Implementation stays on `codex/re1-public-reads-ua-20260922`, stacked directly
on `0a7531baf007d41ae8d34015bdf9cfaf01c30244`, in the existing clean
`scratch/w/re1-preflight-hardening-20260922` worktree. PR 85 retains its
existing base, `codex/re1-preflight-hardening-20260922` at `7010a0b585e1d6f31787a34e84bbf11d80939bd3`.

### Confirmed trade shape and failure path

Read-only, allowlisted inspection of session-1 `journal.jsonl` confirms that
the retained SDK trade uses **`token_id`**, not `asset_id`: top-level
`trader_side=MAKER`, `outcome=Yes`, `side=BUY`, `price=0.52`, `size=25.57`.
The two `maker_orders` entries have the complementary NO token, `outcome=No`,
`side=BUY`, `price=0.48`, and `matched_amount` 20 and **5.57** respectively.
The 5.57 row's `order_id` equals our NO terminal order; the terminal YES order
has `size_matched=0`, and the NO order has `size_matched=5.57`; both are cancelled.
The inspected field names were `token_id`, `outcome`, `side`, `maker_address`,
`order_id`, `matched_amount`, and `price`. Identities in tests are synthetic;
no owner, API key, or other credential field was copied into a fixture or report.

Session-1 `user-stream.jsonl` confirms `stream_failed`, `RuntimeError`, at
2026-09-23 02:30:07.439464 UTC. It contains no failing raw message. Consequently
the complementary relationship is confirmed, while the exact lost WS payload
and originating exception remain inferred. At the assigned base,
`PairStream._normalize_event` passes top-level `asset_id` into
`normalize_official_user_event`; its maker-row filter requires that same token
and raises `official maker trade event does not identify the pilot maker order`
when our maker is on the complement. `OwnerVenue.events` then raises
`user_stream_invalid_event` for the non-network stream failure. The new fixture
uses the WS `asset_id` alias and the confirmed complementary relationship;
the SDK `token_id` alias is covered too.

### Changes

- RE-1 selects maker rows by known order ID, or funder plus either pair token,
  independently of the top-level token. Unmatched trades for this condition
  retain a recursively credential-stripped, guard-cleaned payload and original
  canonical-message SHA-256. Failed normalization retains the cleaned message
  on `stream_failed`. Other-market trades and other invalid events fail closed.
- Matched, unmatched and failed-normalization trade signals force REST reads
  of both active legs, journal `fill`, and end with `HoldEnd('fill')`. Cleanup
  still runs. The Stage 2 normalizer, quotes, sizes, budgets and money gates
  are unchanged.
- Historical prediction bytes stay untouched. `load_prediction` derives
  elapsed-minute coverage, unchanged minimum size/maximum spread and scoring
  minutes from the verified journal, without changing its prediction hash.
  The amended verdict accepts at least 95% sampled minutes and proven cleanup;
  rate changes remain integrated. `SHORT` is reported below 180 two-sided minutes.
- Both CLI report paths print `verdict_frozen` and `verdict_amended`, accrual
  band and flags. The session-1-shaped synthetic case (P_many 0.105, accrual
  0.12, paid 0, 42 visible minutes) gives frozen `INCONCLUSIVE`, amended
  `BELOW_PAYOUT_MINIMUM`, `ACCRUED_AS_MODELLED`, and `SHORT`.
- The frozen linker and shared reconciliation behavior are preserved. The
  RE-1 amended replay validates account/day, both asset queries, complete
  coverage, native earnings, unique transaction/log credit identity and the
  unchanged exact-amount/single-condition rule. USDC.e and pUSD retain their
  actual asset labels; native distributions live in `reward_distributions`.
  Incomplete or ambiguous cash evidence stays unknown, never zero.
- `close_track` only marks adequate `NOT_PAID`; `counts_as_low_accrual_session`
  identifies adequate low-accrual results for the owner's two-session rule.
  There is no automatic October 31 closure or campaign aggregation. The owner
  reviews absent adequate evidence on that date, as the addendum requires.

### Verification and publication

Full focused run: **255 passed, zero failures/errors/skips**, in 139.88 seconds.
Receipt: `scratch/84g-re1-green.xml`, SHA-256 `c6e4cf817c512ae26ff6c2ce60a20605dea8001f49ed1ffb7524ef383bd2ab8c`.
After the final adjustment to persist partial payout receipts before interpretation,
both affected suites passed again: **95 passed in 6.64 seconds**, zero failures
or skips (`scratch/84g-payout-final.xml`, SHA-256 `a0d1fabeac5ab3ba56af97eb1307434db044c4e64f9f6d58bfb0671a987c4b13`).
The first regression run exposed superseded single-verdict/asset assumptions;
the next left only two equivalent-decimal-string assertions. Both are corrected
and the complete focused run above is green. No full repository suite was run.

Reproduce from the branch root on the assigned workstation, using its canonical
project interpreter and shared-lock wrapper (create `C:/pt` first):

```powershell
$re1Repo = (Get-Location).Path
$re1Python = 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe'
New-Item -ItemType Directory -Path C:/pt -Force | Out-Null
$re1Args = @('-m','pytest') + @(Get-ChildItem tests/market/test_re1*.py | ForEach-Object { 'tests/market/' + $_.Name }) + @('-q','--basetemp=C:/pt/re184g-d','--junitxml=scratch/84g-re1-green.xml')
$re1Encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($re1Args | ConvertTo-Json -Compress)))
& "$re1Repo/scripts/ops/workstation_heavy.ps1" -Kind pytest -PythonPath $re1Python -ArgumentsBase64 $re1Encoded -RepoRoot $re1Repo
```

Each run used the repository-owned host/principal, shared mutex and child-tree
Job wrapper. Admission succeeded; no competing full suite or sampler was
stopped. Task-owned `C:/pt/re184g-*` temporary trees were removed after exit.
No campaign-root file or execution worktree was written.

Published implementation tip: **`58c2aea3f12c3a964f7f4684f475c3130f81ad9a`** on
`codex/re1-public-reads-ua-20260922`; its report-only successor is the final
handback tip. The branch is published without rewriting history.

`roll_verdict.ps1 -Branch codex/re1-public-reads-ua-20260922 -Base 0a7531baf`
returned **UNDECIDABLE, exit 1: no live closure evidence**. Per-file disposition:
the five RE-1 Python owners (`re1_attended.py`, `re1_attended_cli.py`,
`re1_evidence.py`, `re1_payout_evidence.py`, `re1_transport.py`) and three test
files (`test_re1_addendum.py`, `test_re1_evidence.py`,
`test_re1_payout_evidence.py`) have no workstation proof of production closure
membership; none is asserted roll-free. This appended report is roll-free
documentation by contract. Production must obtain its own current mechanical
verdict before integration; no merge/adoption occurred here.

Explicit exclusions: no `.env` read, credential access/export, real preflight,
live, cancel-only or collect command; no public/account/payout probe; no write
under the campaign root; no access/change to the session-1 or 09-21 execution
worktrees; no production write, registration, Scheduler change, restart, merge,
promotion, model change, dependency change or full-suite interruption. The
owner alone moves the session worktree, runs preflight and starts session 2 on
a clean reward day.

## 2026-09-23 — overnight full-suite requalification at 0a7531baf

**PASS at the exact owner-requested commit: zero failures and zero errors.**
One full repository suite ran on the non-capture workstation in the new detached
worktree `scratch/w/pr85-fullsuite-20260923-0400`, at
`0a7531baf007d41ae8d34015bdf9cfaf01c30244`. This qualifies that frozen PR 85
revision only; it does not qualify the later 84g commits already on this report
branch. The owner explicitly requested this appended section. Existing report
content and newer branch work were preserved.

The RE-1 process gate found no matching process before launch. The canonical
`workstation_heavy.ps1` admitted the single suite with its shared host lease and
child-tree containment. Pytest began at **04:03:45 ET**, ran **2743.211 seconds**
(45m43s), and the wrapper exited **0** at **04:49:34 ET**. No suite was rerun.

| JUnit result | Count |
| --- | ---: |
| Test-case elements | 7,297 |
| Passed test-case elements | 7,263 |
| Skipped test-case elements | 34 |
| Failures | 0 |
| Errors | 0 |
| Aggregate JUnit tests, including subtest accounting | 8,288 |
| Aggregate passing outcomes, including subtest accounting | 8,254 |

**Failures by module: none.** The XML has no `failure` or `error` nodes.
Its aggregate count includes 991 additional passing subtest outcomes; these
are distinguished from the 7,297 test-case elements rather than double-counted
as separately collected tests.

Retained outside-repository evidence:

- `C:/pt/pr85-0a7531baf-20260923.xml`, SHA-256
  `8ed4629907fcd32a03b5ffd625b13c36306b78983cdad6f2a54ed446d640e773`.
- `C:/pt/pr85-0a7531baf-20260923-start.json` binds commit, worktree,
  arguments and start time; the corresponding `-exit.json` records exit 0.
- `C:/pt/fs` was removed after exit after validating the exact resolved path;
  absence was verified. The detached qualification worktree remains clean.

Exact invocation, from the fresh worktree, with the common project interpreter:

```powershell
$qualificationRepo = (Get-Location).Path
$qualificationPython = 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe'
New-Item -ItemType Directory -Path C:/pt -Force | Out-Null
$qualificationArgs = @('-m','pytest','-q','--basetemp=C:/pt/fs','--junitxml=C:/pt/pr85-0a7531baf-20260923.xml')
$qualificationEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($qualificationArgs | ConvertTo-Json -Compress)))
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$qualificationRepo/scripts/ops/workstation_heavy.ps1" -Kind pytest -PythonPath $qualificationPython -ArgumentsBase64 $qualificationEncoded -RepoRoot $qualificationRepo
```

This command records the completed one-shot run; it is not authority to rerun it.
Only this Markdown report is changed, roll-free documentation by the delegation
contract. No code change, `.env` read, access to either excluded session worktree,
live/preflight action, order/account probe, production write, Scheduler change,
merge or runtime adoption occurred. Workstation qualification does not replace
production-host qualification. The separately authorized 86b public sampler
starts only after this suite and cleanup have exited; its measurement handback
belongs to the 86b report.

## 2026-09-23 — 84h larger-size payment session

**PASS for the focused implementation handback; owner preflight and session 3
remain pending.** No full suite was launched: the direct task instruction was
to hand back the tip as soon as focused tests passed. All verification ended
before 12:00 ET, well before the 19:00 ET ceiling. This does not qualify a live
session or change session 2's frozen `c771cbb42` / 20-share treatment.

The exact handoff and forward plan were read from fetched
`origin/codex/reward-test-attended-handoff-20260921` at `cc028cda`.
Implementation is stacked on PR 85's fetched
`cd66451a56d798afea879ea754bfe95bbdbd4575`, with fetched master recorded as
`198f7ccbcd8e80271693462425582097d22b298b`.
Branch: **`codex/re1-larger-size-payment-20260923`**. Isolated worktree:
`scratch/w/re1-size-84h`. The required
[pre-registration](../research/liquidity-reward-epoch-addendum-2026-09-23b-size.md)
was committed as **`0942f0a1` before any code change**. Implementation tip:
**`ada167a83ffb6038076cce9855f8631e9408c37c`**; the report-only successor is the
final published handback tip. No history was rewritten.

For each band, choose the largest of 20, 30, 50 or 75 shares whose two-sided
reserve is at most `min(available_collateral - 10, 75)`. The table, confirmation
block and phrase digest bind size, reserve and the selection-time wallet
reading. A fresh wallet and allowance check precedes orders; a balance drop
can refuse the session and never silently changes the confirmed size. The
per-order ceiling scales from 15.8/20 to `0.79 * size`, and the pair ceiling
from 19.6/20 to `0.98 * size`, also bounded by wallet minus 10 and 75 pUSD.
Both open orders, signed integer amounts and subsequent re-quotes retain the
chosen size. There is no size/reserve override flag.

Illustrative price sum 0.97 pUSD per YES/NO pair:

| Wallet reading | Reserve budget | Selected shares per leg | Initial pair reserve |
| ---: | ---: | ---: | ---: |
| 97 | 75 | 75 | 72.75 |
| 60 | 50 | 50 | 48.50 |
| 40 | 30 | 30 | 29.10 |
| 25 | 15 | Refuse | Even 20 needs 19.40 |

All configured local T+0/T+1/T+2 bands are considered, with the reward minimum
at most the affordable chosen size. The canonical estimator, full competing
depth at selection, frozen ranking and 2.0 prediction gate are retained. Held
observation and prediction replay use the bound size; old evidence defaults to
20. The parity audit changes only its size input. The sealed lane retains its
20-share proposer and rejects a sized table unless the attended RE-1 controller
explicitly opts in. Fill handling, UTC-day and six-hour limits, heartbeat,
verdict tables, three-session cap and September 30 end date are unchanged.
Public-read failure still fails closed; no incomplete universe is promoted.

Verification (all synthetic/inert exchange fixtures, under
`scripts/ops/workstation_heavy.ps1`):

- All ten RE-1 suites: **314 passed**. Four affected shared pricing/selection/
  hold/rehearsal suites: **104 passed**. Combined: **418 passed in 138.75 s**,
  zero failures/errors/skips.
- After the final explicit sealed-lane rejection and parity-input change,
  sizing/parity/selection rechecks: **73 passed**. The same invocation also
  ran the architecture suite: 21 passed and its untracked-file check failed
  because the two new source/test files were not staged yet. No code defect
  was involved; after staging, all **22 architecture checks passed in 5.68 s**.
- Documentation audit: **PASS**, 18 agent files / 913 Markdown files.
  Staged and cumulative whitespace/diff checks passed. No full-suite or
  live-readiness claim is made.

Retained local JUnit receipts (under this isolated worktree):
`scratch/84h-focused-a.xml`, SHA-256
`e0d3a8fa7221a39bf9cb8c98f322fdf69ca2bf043ca534ce31d4a7efbf9a3c38`;
`scratch/84h-focused-b.xml`, SHA-256
`70e8aa29cb7b37d9ad4b4f9f01e66fc026b80eec61abec8198de16f508cbff72`;
`scratch/84h-architecture.xml`, SHA-256
`07b7d026794238bf1f44a1e73b6dd6a0e1c4ffb06c94f5e4724755f70a2d95de`.
The middle receipt deliberately retains the pre-staging architecture failure.

Reproduce focused checks from this branch root on the assigned workstation:

```powershell
$re1Repo = (Get-Location).Path
$re1Python = 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe'
$re1Args = @('-m','pytest') + @(Get-ChildItem tests/market/test_re1*.py | ForEach-Object { 'tests/market/' + $_.Name }) + @('tests/market/test_reward_quote.py','tests/market/test_mm_stage2_selection.py','tests/market/test_mm_stage2_hold.py','tests/market/test_mm_stage2_rehearsal.py','tests/operations/test_import_architecture.py','-q','--basetemp=C:/pt/re184h-repro')
$re1Encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($re1Args | ConvertTo-Json -Compress)))
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$re1Repo/scripts/ops/workstation_heavy.ps1" -Kind pytest -PythonPath $re1Python -ArgumentsBase64 $re1Encoded -RepoRoot $re1Repo
```

The mechanical `roll_verdict.ps1 -Branch codex/re1-larger-size-payment-20260923
-Base cd66451a56d798afea879ea754bfe95bbdbd4575` returned **UNDECIDABLE, exit 1:
no live closure evidence**. Per-file roll disposition:

| Changed file | Capture closure membership / verdict |
| --- | --- |
| `src/weather/market/mm_stage2_selection.py` | Unknown; no retained live closures |
| `src/weather/market/reward_quote.py` | Unknown; no retained live closures |
| `src/weather/market/re1_sizing.py` | Unknown; new module, imported by changed owners |
| `src/weather/market/re1_attended.py` | Unknown; no retained live closures |
| `src/weather/market/re1_attended_cli.py` | Unknown; no retained live closures |
| `src/weather/market/re1_evidence.py` | Unknown; no retained live closures |
| `src/weather/market/re1_owner_checks.py` | Unknown; no retained live closures |
| `src/weather/market/re1_transport.py` | Unknown; no retained live closures |
| `tests/market/test_re1_sizing.py` | Unknown; no retained live closures |
| `tests/market/test_re1_attended_parity_audit.py` | Unknown; no retained live closures |
| `tests/market/test_re1_owner_checks.py` | Unknown; no retained live closures |
| `tests/market/test_re1_transport.py` | Unknown; no retained live closures |
| This appended report and the dated size addendum | Roll-free documentation by contract |

Production must obtain its current mechanical verdict before integration.
No schema registry, host assignment, scheduler or release gate changed. No
production write, registration, restart, merge, promotion, real preflight,
live, cancel-only or collect command occurred. No `.env`, campaign root or
`scratch/w/re1-session1-20260923` access occurred. Session evidence was not read
or rewritten. The owner alone preflights the reviewed tip for session 3.

## 2026-09-23 — one full-suite qualification at 1310ca6b

**PASS: 7,360 passed, zero failures, zero errors, 34 skipped, and 991 passing
subtests.** This is the single full suite explicitly requested after the 84h
focused handback. No code change or rerun occurred.

The new detached qualification worktree was
`scratch/w/re1-84h-fullsuite-20260923`, at exact commit
**`1310ca6bf230f6a520f3ee4ff364943cc3b480f1`**. Its tracked and untracked Git
status was clean before launch and after the wrapper exited. Only after the
suite finished was this worktree put on the report-only branch
**`codex/re1-84h-fullsuite-report-20260923`**.

The repository-owned `scripts/ops/workstation_heavy.ps1` admitted the run with
its host/principal, shared lease and child-tree containment. The pre-launch
process check found no RE-1 live process. Pytest started at **11:50:38 ET**,
reported **3,605.06 seconds (1:00:05)**, and the wrapper's **exit 0** was
recorded at **12:51:31 ET**. Both the 18:15 start cutoff and the strict 19:00
finish deadline were met.

| Result | Count |
| --- | ---: |
| Passing test cases | 7,360 |
| Failed test cases | 0 |
| Error test cases | 0 |
| Skipped test cases | 34 |
| JUnit test-case elements | 7,394 |
| Additional passing subtest outcomes | 991 |
| Aggregate JUnit tests including subtests | 8,385 |

**Failures by module: none.** Thirteen warnings were emitted: twelve sklearn
imputation warnings for fixture features without observed values, and one
NumPy binary-size warning in the cached NetCDF4 source test. They were retained
as warnings; no failure was suppressed or repaired.

The JUnit XML is outside the repository at
`C:/pt/re1-84h-1310ca6b-20260923.xml`, SHA-256
`a01debd21f18e53cfe7d44203c03b7e936ba348b5a11c9a2637afbca685dd9c7`.
The adjacent `-start.json`, `-exit.json` and `-cleanup.json` receipts retain the
commit/worktree/arguments, timing and counts, and temporary-directory cleanup.
JUnit's internal elapsed field is 3,604.967 seconds; its aggregate includes
the 991 subtests, so they are not counted again as separately collected cases.

`C:/pt` was created/verified before launch. `C:/pt/fs4` was absent then,
created by this one suite, and deleted after exit after verifying its exact
absolute path and non-reparse parent/root. Absence was checked after deletion.

Exact invocation, from the new qualification worktree (record of the completed
run, not authority for another run):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Users/Michael/Documents/github/weather/scratch/w/re1-84h-fullsuite-20260923/scripts/ops/workstation_heavy.ps1 -Kind pytest -PythonPath C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe -ArgumentsBase64 WyItbSIsInB5dGVzdCIsIi1xIiwiLS1iYXNldGVtcD1DOi9wdC9mczQiLCItLWp1bml0eG1sPUM6L3B0L3JlMS04NGgtMTMxMGNhNmItMjAyNjA5MjMueG1sIl0= -RepoRoot C:/Users/Michael/Documents/github/weather/scratch/w/re1-84h-fullsuite-20260923
```

Decoded Python arguments: `-m pytest -q --basetemp=C:/pt/fs4
--junitxml=C:/pt/re1-84h-1310ca6b-20260923.xml`.

The sole changed file is this appended report, roll-free documentation by
contract. No code, config, dependency or generated artifact changed. No access
to the protected session worktree or campaign root, agent credential read,
real preflight/live/cancel-only/collect action, production write, registration,
restart, merge or runtime adoption occurred. This qualifies the exact tested
code; the owner's separate session-3 preflight remains required.
