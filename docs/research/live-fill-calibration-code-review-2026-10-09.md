# Independent code review: live fill-calibration (LFC) before session 0

Reviewed tip: `origin/claude/live-fill-calibration-code-m-20261009` @ `45000b66b` (merge `8d3192c1d` of RE-1
`2b9a0ca9e` + LFC `e98cd6a7a` onto master `915b1167b`; then `ed785003e` wallet-verify; then `45000b66b` post-merge
fixes). Signed spec read from `origin/claude/live-fill-calibration-prereg-20261009` @ `c57a6d075` (signed bytes at
`82936d68a`). Method: code and git diffs only (no pytest, no worktree, no live command, no `.env`/`config/local`, no
`data\` files). Line numbers are `git show 45000b66b:<path>` line numbers.

## Verdict: PASS-WITH-REQUIRED-FIXES

The order path is tight (post-only, GTD, size pinned at 40, one sign/submit boundary, account-wide cancel-all on every
end path, heartbeat stopped *before* cancel so the venue dead-man runs even if the cancel API fails), and the L ledger
is a sound upper bound on filled cost: every POST is preceded by a fsynced `leg_intent` at full size x price, and cost
is only released by a venue terminal read. Nothing I found can lose money beyond L (fees aside, see L-6). What is not
yet proven is the single assumption the unattended model rests on: that the **`/v1/heartbeats` rotating-ID dead-man
actually cancels orders when the process dies**. RE-1's own build report says it was never exercised, the 10.4 s
measurement came from the Stage-1 bodyless sender, and session-0 run 0d as built cannot discriminate venue cancel from
the script's own 8 s cleanup. Session-0 run 0c is therefore the gate for everything, and the code's mechanical
"session 0 passed" check does not require it. Fixes below are small; none changes the signed quote or limits.

---

## 1. Hard-limit completeness (signed §6 -> code)

| §6 limit | Enforcing code | Status |
| --- | --- | --- |
| Order shape: BUY, post-only, GTD, size exactly 40, price in [0.17, 0.80] on 0.01 tick, no crossing | `re1_attended.py:424-426` (`submit_shape`), `434-436` (`submit_price`), `467-472` (`market_rules`, `fresh_ask`), `314-328` (opening check both legs); `re1_transport.py:448-463` (signed-order binding: maker, signer, token, BUY, GTD, post_only, expiration, amounts, 0.79 cap) and `467-472` (post-sign fresh-ask re-read); `lfc_pilot.py:94-96,98-113` (`SIZES == (40,)`) | Enforced, twice (controller + transport) |
| Capital: order cap 31.6, band cap 39.2 | `lfc_pilot.py:397-401` (`caps`), `388` (`BAND_CEILING`); `re1_attended.py:437-438`; `re1_transport.py:304-306,462` | Enforced |
| <= 10 submits, <= 4 requotes, 5th requote ends | `re1_attended.py:32-33,432-433,677-680` (`submit_budget`, `fifth_requote`) | Enforced |
| Open orders exactly ours and <= 2; any foreign open order ends the session; preflight requires zero | At submit: `re1_attended.py:439-452` (`exact_open_orders` + `open_order_cap`). Runtime: `lfc_pilot.py:541-557` (account-wide read every 30 s, `foreign_open_order`); user stream: `re1_transport.py:256-258,380-386` (foreign-token event -> stream FAILED -> `user_stream_invalid_event`). Start: `re1_attended.py:624-626` (`initial_open_orders`), `lfc_cli.py:103-130` + `lfc_ledger.py:496-499`. Preflight: `re1_owner_checks.py:152-158` (`AccountNotEmpty`), `lfc_cli.py:7-8` | Enforced; see F-2 for the end-reason label |
| Freshness: snapshot <= 10 s at submit; stale 300 s; stream silent 30 s; geoblock 30 s cadence / 45 s budget | `re1_attended.py:455-458`, `355-359`, `346-350,357`, `367-371` | Enforced |
| Venue terms: reward min size > 40, rate < 40, tick != 0.01, min order size > 40 | Submit: `re1_attended.py:462-469`. Per minute (hold): `re1_attended.py:89-92` via `observe` (reward min/rate only) | Enforced at submit; tick/min-order-size are **not** re-checked per minute during the hold (LOW, F-11) |
| Events: fill, unknown user event, order no longer resting, cancel ack, cancel not terminal, journal write failure | `re1_attended.py:374-401,409-415`, `500-517`, `360-361` + `GuardedJournal.record` raising into `run()` | Enforced |
| Campaign: <= 8 counted sessions, <= 360 min, GTD = end + 60 s, no submit under 180 s | `lfc_pilot.py:407-412` + `lfc_cli.py:113-115` (session cap); `re1_attended.py:427-431` (duration/UTC day/180 s), `476-477` (expiration) ; `lfc_constants.py:27-28` | Enforced |
| L gate: L_after_cancel + reserve <= 100 at post and every requote; cash >= L_resting + reserve | `lfc_pilot.py:428-434,443-454,478-490`; `lfc_ledger.py:236-249`; cash `lfc_pilot.py:436-441` (fresh balance on requote `484-487`) | Enforced; requote path has a spurious-refusal defect (F-3) |
| Stop at 100 / reconciliation mismatch halts for good | `lfc_ledger.py:226-234`, `lfc_pilot.py:541-544`, `lfc_cli.py:106-108,159-160` | Enforced |
| L recomputed from journal + venue reads at preflight, after every fill/cancel, at cleanup | After fill/cancel/cleanup: `re1_attended.py:518-519,587-590` -> `lfc_pilot.py:518-519`; trades at cleanup `lfc_pilot.py:590-617`. **At preflight: no venue read** (`lfc_cli.py:285-294` only checks `stop_reason`); instead `start_gates` refuses while any acknowledged leg is unresolved (`lfc_cli.py:109-112`) and the owner runs `reconcile` | Partial by design; acceptable because an unreconciled ledger cannot start a session (LOW, F-12) |
| Dates: none before 2026-10-15T00:00Z, 23:50Z hard stop, last start local 10-31, one per local date | `lfc_pilot.py:63-81,403-405`; `re1_attended.py:430,622`; `lfc_cli.py:105,116-119,310-312` | Enforced (mechanical) |

Bypass analysis: no CLI flag, config, or environment variable widens a limit. Session-0 test flags (`0d`, `0e`, `0f`)
are gated on `profile.run` (`lfc_pilot.py:444-448,559-573`) and `PilotProfile` refuses a run without `--session0`
(`lfc_pilot.py:87-88`); the counted path cannot reach them (test `test_test_flags_never_fire_in_a_counted_session`).

## 2. Dead-man

Mechanism in code: `HeartbeatLoop` thread (`re1_resilience.py:76-158`) sends every 2 s; no ack within 8 s ->
`heartbeat_stale`; main loop silent 20 s -> `main_loop_stalled` and **sends stop** (`95-98`). `Session.control`
(`re1_attended.py:351-355`) raises on either. `cleanup()` (`537-610`) **stops the heartbeat thread first** (`543-547`),
then cancels each order, then account-wide `cancel_all`, polls `open_orders` up to 10 s, reads terminal orders,
positions and trades, prints `PANIC` if not clean. `atexit` registered in `run()` (`618`). Every GTD expires at
`end + 60 s` (`476-477`). The heartbeat is live before the first POST: `submit` calls `control(force=True)` which loops
until `last_ack` is not None (`363-365`).

| Scenario | What the code does | Orders cancelled? |
| --- | --- | --- |
| Python exception / HoldEnd / Ctrl-C | `run()` catches `BaseException` -> `cleanup()`; signal handlers map SIGINT/SIGTERM/SIGBREAK to KeyboardInterrupt (`lfc_cli.py:369-374`) | Yes, explicit cancel + cancel-all, verified by poll |
| `taskkill /F` / power loss / console closed | No atexit. Thread dies with the process. Venue dead-man (10 s + 5 s buffer) then GTD backstop | **Only if the venue's `/v1/heartbeats` dead-man works** (see below); otherwise orders rest until GTD (up to 6 h + 60 s) |
| Network loss | Heartbeat send raises transient -> no `failure` set but `last_ack` ages -> `heartbeat_stale` at 8 s -> cleanup; cancel calls fail (3 x 0.5 s retries, `527-535`) -> `cleanup_ok=False`, PANIC, legs stay open in L; venue dead-man cancels server-side | Venue-side yes; script cannot confirm; `reconcile` required before the next session (`lfc_cli.py:109-112`) |
| Venue 429 / 5xx | `transient()` (`re1_resilience.py:9-24`) treats 408/429/>=500 as transient; same path as network loss if it persists 8 s. Heartbeat 400 `Invalid Heartbeat ID` is a resync, never an ack (`re1_transport.py:65-80`) | As above |
| Laptop sleep | Frozen process: venue cancels at ~10 s. On wake: `main_loop_stalled` or `order_no_longer_resting` -> cleanup; terminal reads show CANCELED | Venue-side |
| Workstation dies mid-session (worst case) | Resting legs: cancelled by the venue in ~15 s, or filled in that window (<= 2 x 32 = 64, already inside L's reserve), or if the dead-man does not work, rest up to the GTD and may fill at the limit (still <= reserve). No path loses more than the reserve already counted in L | Bounded by L in all cases |

**Heartbeat semantics verified in code**: `Re1Heartbeat.send` (`re1_transport.py:49-85`) POSTs `/v1/heartbeats` with a
rotating `heartbeat_id` body under L2 HMAC; acknowledgment requires a `heartbeat_id` string and no `error_msg`. It
differs from the Stage-1 `OfficialHeartbeatSender` (`mm_official_transport.py:181-241`, bodyless `/heartbeats`, expects
`{"status":"ok"}`). Evidence for the venue-side cancel: EF §10i measured 10.359 s on 2026-09-06 **with the bodyless
sender**; the RE-1 build report (`agent-report-2026-09-84a...md:282-286`) states "These prove requests/control
behavior, not actual venue cancellation after a killed process or lost network. No authenticated heartbeat or expiry
was exercised"; the pilot doc (`INTERNATIONAL_MM_LIVE_PILOT.md:684-688`) notes the official endpoint "omits a
cancellation timeout" and calls the heartbeat-ID examples obsolete. RE-1's 12 live attempts acknowledged v1
heartbeats but no record shows the venue cancelling on a v1 lapse. **The v1 dead-man is unproven; session-0 run 0c is
the proof and must pass S0-2 before any counted session** (F-1).

## 3. L ledger

Formula (`lfc_ledger.py:69-74,207-212`): L = sum(terminal legs: size_matched x limit) + sum(non-terminal legs: size x
limit). Intent persisted before the raw POST (`lfc_pilot.py:492-501` inside `OwnerVenue.submit`'s `before_post`,
`re1_transport.py:474-476`); a failed intent write raises before anything is posted.

- **Partial fills**: `filled()` triggers on `size_matched > 0`; cleanup cancels the remainder and the terminal read's
  `size_matched` is what L records (`re1_attended.py:582-590`); trades cross-check (`lfc_pilot.py:598-617`). Correct.
- **Unacknowledged orders**: intent stays at full cost (correct upper bound) but can never be resolved: `leg_terminal`
  needs an order id (`lfc_ledger.py:336-338`), `reconcile` only lists them (`lfc_cli.py:545`), `start_gates` ignores
  them (`111`). A lost-ack order that actually rests is classified **foreign** by `reconcile`/`verify`/`cancel-ours`
  (`lfc_cli.py:149-151`), its fills are not attributed, and wallet-verify's venue_L excludes it (S0-6 FAIL). L stays
  conservative (never under-counts), but up to 32 pUSD is consumed for good (F-5).
- **Requotes**: replaced leg is cancelled and must be terminal before the replacement is gated (`cancel_leg` ->
  `leg_terminal`; `authorize_post` subtracts the sibling's own resting cost, `lfc_pilot.py:479-480`). Defect: the row
  handed to `leg_terminal` is the read taken **before** the 10 s open-orders poll (`re1_attended.py:504,519`); when it
  still says `LIVE` (the documented sub-second read lag), `Ledger.terminal` records nothing (`lfc_ledger.py:334-335`)
  and the cancelled leg keeps full resting cost until cleanup. Over-count only, but the requote L gate can then refuse
  spuriously and end the session (F-3).
- **Cancel vs fill race**: cancel ack -> order read `filled()` -> `check_fills(canceling=oid)` -> poll; a `not_canceled`
  response raises in `cancel_ack_ids` and lands in cleanup, where the terminal read sets the fill. Correct.
- **Both legs filling**: two terminal legs, L_filled <= 39.2; stop-at-100 uses filled + 38.4 (`lfc_constants.py:35-36`;
  the 0.96 floor is right for a 0.005-grid mid). Correct.
- **Fees**: none, "exactly as signed". Weather makers pay 0 (EF §10o). Session-0 markets are not weather markets and
  `submit` only refuses `fee_rate_bps < 0` (`re1_attended.py:468`), so a non-zero maker fee would be a loss outside L
  (F-9, LOW).
- **Reserve vs cash on a shared wallet**: `available_collateral` is the CLOB collateral balance
  (`re1_transport.py:442-445`), allowance >= reserve_cap checked (`443-444`); cash >= L_resting + reserve at band and at
  every requote with a fresh read. The owner's positions do not reserve cash and open orders must be zero, so the
  reading is the conservative one in §6. Correct.
- **Reconciliation halts**: a mismatch is permanent with no owner override (by spec). At cleanup it is retried 5 x 2 s
  (`lfc_pilot.py:598-617`); the `reconcile` command does **not** retry (`lfc_cli.py:535`) and reads the owner's whole
  trade history (`re1_transport.py:409-410` with `condition=None`, `bounded_rows` 50 pages / 25 000 rows) (F-6).

## 4. Foreign-order and shared-wallet safety

- Owner positions: `initial_positions_ok` is event-level (`lfc_pilot.py:575-588`), `positions_mean_fill` is False
  (`521-523`), baselines pin everything outside our tokens (`lfc_ledger.py:480-508`, T-40 is the comparison, T-24 a
  record). `cleanup()` never cancels before the empty-account read proved zero open orders and nothing was submitted
  (`re1_attended.py:549-555`). `cancel-ours` cancels ledger ids only (`lfc_cli.py:576-580`).
- Detection timing at runtime: the account-wide WS user channel fires first (a foreign `order` event raises
  `unknown_account_event` -> stream FAILED -> `RuntimeError('user_stream_invalid_event')`, `re1_transport.py:256-258,
  380-386`), ending the session within seconds with reason `exception` / `RuntimeError`; the 30 s REST poll
  (`foreign_open_order`) is the slower backstop. EF §10m session 9 confirms this is what happens live. Safe, but S0-3
  expects `foreign_open_order` for run 0b (F-2).
- Preflight and start: `AccountNotEmpty` in preflight, `baseline_foreign_open_orders` / `foreign_open_orders_at_start`
  in `start_gates`, `initial_open_orders` in `run()`. S0-4 holds.
- wallet-verify (`lfc_cli.py:435-521`): reads only `open-orders`, `trades --since genesis`, `positions
  --include-resolved` through `wallet_reader_client.read_account` (no credential); S0-1 is `len(open_orders)==0`; S0-6
  recomputes venue_L from reader fills for our ids at limit price (FAILED trades ignored), requires the l_ledger.json
  snapshot to match the verified chain, and diffs positions outside our tokens against T-40. Defect: the positions
  check requires reader `status == 'OBSERVED'` (`475`); the reader reports `PARTIAL` whenever any live position has a
  deferred mark or missing reward terms (`wallet_reader.py:311-312`), which is likely on the owner's real wallet, so
  S0-6 may be structurally un-passable (F-4).

## 5. Merge risk

- **Live-path semantics across the merge**: `git diff e98cd6a7a 45000b66b` on `re1_attended.py`, `re1_transport.py`,
  `re1_resilience.py`, `re1_owner_checks.py`, `re1_sizing.py`, `reward_quote.py`, `mm_stage2_hold.py`, `lfc_*.py` is
  **renames only** (`_value`->`sdk_field_value`, `_plain_sdk_value`->`plain_sdk_value`, `_cancel_ack_ids`,
  `_exact_open_orders`, `_user_agent`->`re1_user_agent`). `mm_official_adapter.py`, `mm_user_stream.py`,
  `mm_official_transport.py` vs the RE-1 tip differ only by those renames plus the import home of
  `MAX_OPERATOR_PILOT_BUDGET_USDC`; `mm_stage2_rewards.py`, `exchange_economics_sources.py`, `live_path_security.py`,
  `live_sdk_overlay.py`, `market_registry.py`, `market_config.py`, `paths.py` are byte-identical to the RE-1 tip.
  `execution_host.py` gained `current_execution_session_id` and an optional Stage-2 grant key (master -> tip); neither is
  on the LFC path. No silent semantic change found on the live path.
- **The "lost rule" restored in `45000b66b`** is `observation_status.evidence_age_seconds` (the *capture watcher*
  heartbeat: a future timestamp is not fresh) plus Control-Room naive-time handling. Neither is the venue heartbeat and
  neither is on the LFC path; the RE-1 `HeartbeatLoop` rule was never lost.
- **Policy defaults** (`clob_recon_policy_enabled` True->False, `POLICY_VERSION` v0.2 -> `schema_version("mm_policy")`,
  STAGE1_V1 caps) live in `quote_policy_defaults.py` / `mm_policy.py`. They **are** transitively imported by the LFC
  path (`mm_official_adapter` -> `mm_pilot_capital` -> `market_making_run_constants` -> `mm_policy`, already so at the
  RE-1 tip), but only `QUOTE_COLUMNS` is referenced; `config_with_clob_recon` / `policy_overrides_from_recon` have no
  caller on the path. "Reconcile off" is irrelevant to LFC (and it is the safer default for the paper quoter). Note:
  this "CLOB reconcile" is unrelated to LFC's `reconcile` command.
- **P2 econ-gate scan (grep-based, this review)**: the import closure of `lfc_cli`/`lfc_pilot` reaches
  `exchange_economics_sources` (helpers) and, through the chain above, `mm_policy`, `clob_recon`,
  `observation_status`, `info_event_calendar`, `mm_risk`, `snapshot_cadence_quality`, `market_microstructure_features`;
  **no module in the closure imports `weather.market.exchange_economics`**, `market_making_live_pilot`,
  `market_making_preflight` or any `taker_*` module. P2 still asks for a runtime scan on the tip; run it on the
  workstation before session 0 and record the count.
- The merge also changes production replay / collection modules (`backtesting/replay.py`, `replay_backtest.py` 309
  lines, `snapshot_store.py`, `settlement_ledger.py`, `location_config.py`, `execution_host.py`): roll-sensitive on
  the capture host and entirely unnecessary for LFC (section 8).

## 6. Order-path invariants

post-only (controller `425`, transport `459`); price snapped by floor to 0.01 (`replacement_price`, `135-137`) and
checked `price % 0.01` (`435`); size 40 from `PilotProfile.SIZES`, checked in `submit` (`424`) and again in
`OwnerVenue.submit` against `profile.SIZES` and `venue.size` (`452-454`); no taker path: the httpx request hook allows
only `POST /order`, `POST /orders-scoring`, `DELETE /order`, `DELETE /cancel-all` and GETs (`re1_transport.py:190-199`),
and both the pre-sign and post-sign fresh-ask checks refuse a crossing price; account/market: signer != funder,
signature type 2/3, pinned SDK endpoints, wallet deployed (`161-189`), `book['market'] == condition` at signing (`470`),
`exact_open_orders` binds maker/condition/side/price/size; geoblock at start (`lfc_cli.py:314-315`), every 30 s with a
45 s budget, forced at every submit; dates and the panel exclusion are mechanical (`lfc_pilot.py:72-81`, exclusions
appended and hashed before the first post `456-476`, write failure posts nothing). Session 0: slug rule 1 is
mechanical against the registry prefixes, every built-in band slug +/- 60 days and "youtube" (`117-130`); rules 2-5
in `session0_candidate` (`158-204`); the table must reproduce from its inputs (`241-255`).

One soft spot: `start_allowed(now)` inside `submit` uses `self.start` for the date rules and `now` only for the 23:50Z
stop (`403-405`); correct because the session cannot cross a UTC day (`428`).

## 7. Workstation open questions, with recommendations

1. **Session-0 requote window** (`lfc_constants.py:70`, [4.5, 6.5] c = d - 0.5 / d + 1.5, RE-1's shape around d = 5 c).
   Keep it, by dated clarification to the S0 spec. Session 0 is the only live exercise of the requote L gate, the
   cancel-read-lag path (F-3) and `cancel_acknowledgment` before money-at-size sessions; disabling requotes would
   leave those untested.
2. **Owner-supplied candidate markets** (`--event-slug`, repeatable; `lfc_cli.py:63-64,218-222`). Accept with a dated
   clarification: the spec's "lists the markets" is read as "evaluates the owner-listed events"; rules 1-5 stay
   mechanical and the full table with every supplied slug is written to `session0/selection.json` and hashed. Require
   at least three distinct events so the depth pick is a real pick.
3. **Depth rule**. Counted sessions implement §3 exactly (`mm_stage2_selection.py:85-95`, max(75, size) each side
   within max spread of the adjusted mid). Session 0 ranks by min(bid, ask) displayed depth within 3 c; no minimum is
   needed beyond a two-sided uncrossed book, but add `fee_rate_bps == 0` to the candidate filter (F-9).
4. **Mechanical session-0 pass gate**. `session0_passed` (`lfc_cli.py:92-100`) accepts a single 0a `fixed_end` with
   clean cleanup. Not enough: it must require ledger evidence of every sub-run (F-1).
5. **Unacknowledged orders in L until reconcile**. Yes, keep them at full cost (that is what makes L an upper bound),
   but give `reconcile` an adoption path so they can be resolved and their fills attributed (F-5).
6. **5 x 2 s retry before a trades mismatch**. Keep it (cleanup, `lfc_pilot.py:598`); the retry should also re-read the
   order's `size_matched` since the order read is authoritative, and the same retry belongs in `reconcile_ledger` (F-6).
7. **Econ gate in the LFC preflight**. No. The signed P2 says reward terms are read live from `/rewards/markets` and
   #271 does not gate this path; the closure does not import `exchange_economics`. Record the runtime scan result
   instead.

## 8. Deployment

Run session 0 and the counted sessions from a **pinned detached worktree on the workstation at a reviewed tip** (this
tip plus the fixes below, re-reviewed by diff). Do **not** land the branch on master before session 1:

- The code already binds itself to a tip: `code_identity()` requires a clean tree and `clean_preflight` requires a
  same-day receipt with the same commit (`re1_owner_checks.py:20-26,219-235`); `pilot_root()` is user-profile-fixed,
  so the ledger does not move with the checkout. A worktree is the designed deployment (the design doc §5 said
  "from a pinned worktree").
- Landing brings 236 files / 39.7k lines including loop-imported production modules (replay, snapshot_store,
  settlement_ledger, execution_host): roll-sensitive, needs the quiet window and the bounded suite, and buys nothing
  for LFC, which runs only on the workstation against the production wallet-reader over LAN.
- Worktree caveats: `.env` is read from the *common* git dir's parent (`re1_transport.py:88-100`) so it works from a
  worktree; `config/local/wallet_reader_client.json` is read relative to the worktree's `config/local`
  (`wallet_reader_client.py:45`), so it must be present there (ignored file, copy it); `config/
  international_live_execution_host.json` is tracked and `ASSIGNED`; `live_mutex` takes the workstation's
  `Global\WeatherProjectHeavyWorkloadV1` mutex (`re1_evidence.py:51`, shared with `workstation_pregate.ps1`), so no
  heavy job may run during a session and a running heavy job refuses the start; the pinned SDK (`require_official_clob
  _version`, 0.6.0) must be in the worktree's interpreter environment.

Safer and faster: the worktree. Land on master later, through the normal roll-sensitive process, once the sessions
are done.

---

## Findings

**F-1 HIGH - The venue dead-man is unproven for `/v1/heartbeats`, run 0d cannot prove it, and the mechanical gate
lets session 1 start on 0a alone.**
`re1_transport.py:49-85` (v1 sender), `re1_resilience.py:99-102,141-147` (script cleanup at 8 s), `lfc_pilot.py:559-567`
(0d drops sends; the stale check still fires at 8 s and the script cancels before the venue's ~10 s), `lfc_cli.py:92-100`
(`session0_passed` needs only 0a). Fix: (a) `session0_passed` must require, in the ledger, ended sessions with
`session0_run` 0a (`fixed_end`), 0b (`foreign_open_order` or the F-2 label), 0c (`reconciled_after_crash`), 0d
(`heartbeat_stale`/`order_no_longer_resting`), 0e (`l_budget_refused`), each with `cleanup_ok` true (0c via
reconcile), plus an owner attestation file `session0/pass.json` whose phrase is bound to `ledger.previous` and that
records S0-2's measured seconds; (b) in run 0d record, in the journal, the first terminal order read and the
`cleanup_cancel_response` for each leg so the owner can tell venue-cancelled (already CANCELED / `not_canceled`) from
script-cancelled; (c) treat S0-2 on **0c** as the gate for every unattended session: if time-to-zero > 20 s, session 1
may not start and the attendance model must be re-signed.

**F-2 MED - Run 0b will end with reason `exception` (`RuntimeError`), not `foreign_open_order`, so S0-3 fails as
written.** `re1_transport.py:256-258,380-386` (foreign-token WS event -> `user_stream_invalid_event`), `re1_attended.py:
694-696` (reason `exception`), EF §10m session 9 (observed live). The 30 s REST check (`lfc_pilot.py:548-557`) is the
slower path. Fix: in `OwnerVenue.events`, when `stream.failed_event` is an order event on a non-session token whose
`maker_address` is ours, return a synthetic event that `check_fills` maps to `HoldEnd('foreign_open_order')` (or have
`PilotSession.extra_checks` force the account read when the stream fails); alternatively a dated S0 clarification
accepting `exception/RuntimeError` for 0b. Prefer the code fix: the label is what the owner reads at 02:00.

**F-3 MED - `cancel_leg` records the pre-poll order row; a `LIVE` lag read leaves the cancelled leg in L_resting for the
rest of the session.** `re1_attended.py:504,510-519`, `lfc_ledger.py:333-335`. Effect: L over-counts by up to 32 until
cleanup; the requote gate `authorize_post` (`lfc_pilot.py:478-480`) then refuses spuriously once L_filled is above
roughly 30, ending a session (`l_budget_refused`) on the second requote of the campaign's later sessions. Fix: after
the open-orders poll proves the order gone, re-read it (`required('cancel_terminal_read', ...)`) and pass that row to
`leg_terminal`; if it is still `LIVE` after the poll, raise `HoldEnd('cancel_not_terminal')`. Untested today: the
rehearsal fake cancels synchronously (`re1_rehearsal.py:78-80`); add a fake that returns `LIVE` once.

**F-4 MED - wallet-verify S0-6 requires reader `status == 'OBSERVED'`; the owner's wallet will often read `PARTIAL`.**
`lfc_cli.py:475`, `wallet_reader.py:296-312` (any deferred mark or missing reward terms -> `PARTIAL`). Fix: key on
`positions['inventory_complete'] is True` and `unclassified_positions == []`, compare sizes only (marks are
irrelevant to S0-6), and report the reader status separately.

**F-5 MED - A lost submit acknowledgment leaves an order the ledger cannot name.** `lfc_ledger.py:336-338`,
`lfc_cli.py:149-151,524-546` (classified foreign), `lfc_cli.py:111` (does not block a new session), S0-6 venue_L
excludes it. Fix: in `reconcile_ledger`, for each intent without an order id, adopt a venue order (open or terminal)
that matches token, side BUY, price, original_size and `expiration == session end + 60` (a strong fingerprint), using
the journal's `sdk_response` rows for `POST /order` (`re1_transport.py:337-348`) as the first source; record it as a
new `leg_adopt` event (schema bump) and then resolve it like any leg. Until then, document the manual procedure and
make `start_gates` refuse while an intent is unresolved (`unknown_submit` is already a RE-1 blocker).

**F-6 MED - `reconcile` can halt the campaign on a lagging or over-long trade read.** `lfc_cli.py:535` (no retry),
`re1_transport.py:409-410` (`market=None`, whole account), `284-293` (50 pages / 25 000 rows -> `pagination_budget`).
Fix: pass the ledger genesis epoch as the SDK `after`/since bound, retry the mismatch comparison 5 x 2 s as cleanup
does, and re-read `size_matched` from the order before recording a `mismatch`.

**F-7 LOW - First account-wide foreign read is budgeted from `freshness.started`.** `lfc_pilot.py:548-549` (budget 90 s)
with `freshness.started` reset before `opening_check` (`re1_attended.py:632`); in a slow network the first read can
already be "stale" after the two opening submits (`account_open_orders_stale` ends the session, safe but wasteful).
Fix: pass `initial=self.posted_at` (or the first submit time).

**F-8 LOW - Session 0 does not pin `fee_rate_bps == 0`.** `lfc_pilot.py:158-204`, `re1_attended.py:468`. A non-zero
maker fee on a non-weather market is a loss outside L. Fix: refuse `fee_rate_bps != 0` in `session0_candidate` (and
record the rule in the counted path too; weather markets are 0).

**F-9 LOW - Tick size and min order size are checked only at submit, not per minute.** `re1_attended.py:467-469` vs
`658-659` (reward terms only). A mid-session tick change would not end the session until the next requote. Fix: compare
`snapshot['rules']` to `initial` rules in the minute loop and raise `HoldEnd('market_rules')` on change.

**F-10 LOW - "L recomputed at preflight" is delegated to `reconcile` + start-gate refusals.** `lfc_cli.py:285-294,
109-112`. Acceptable; say so in the runbook so the owner runs `reconcile` after any non-clean end, and have `preflight`
print `unresolved_legs` and `open_sessions` so the refusal is visible before the owner reaches `live`.

**F-11 LOW - The preflight commit binding is to `REPO_ROOT`'s HEAD, which in a worktree is the worktree's HEAD.**
`re1_owner_checks.py:20-26`. Correct, but record in the runbook that the worktree must be at the reviewed tip and
clean, and that the receipt commit printed by `preflight` must equal that tip.

**F-12 LOW - Notification toast uses PowerShell's AppUserModelId and `-ExecutionPolicy Bypass`.** `lfc_pilot.py:302-313,
337-339`. Fine on the workstation; the failure path is recorded (`343-353`). Verify once by hand (S0-8) that a toast
actually shows with Focus Assist off.

No BLOCKER: nothing found can lose more than L or leave an order resting past the GTD; F-1 is a proof obligation
the signed plan already assigns to session 0, made binding here.

## What must be true before session 0

1. Code: F-1(a)(b), F-2, F-3, F-4, F-6 landed on the branch and re-reviewed by diff (small, test-covered with fakes);
   F-5 either landed or documented as a manual procedure with `start_gates` refusing on an unresolved intent.
2. Dated S0 clarifications signed by the owner: requote window [4.5, 6.5] c; owner-listed candidate events (>= 3);
   0b end label; the mechanical pass gate and 0c as the dead-man proof; `fee_rate_bps == 0` for session 0.
3. Workstation: detached worktree at the reviewed tip, clean (`git status --porcelain` empty, untracked included);
   interpreter with the pinned `polymarket` 0.6.0; `config/local/wallet_reader_client.json` present in the worktree;
   wallet-reader server reachable on the LAN; no heavy job (the live mutex is the heavy-work mutex); laptop sleep off.
4. P2 runtime import scan re-run on the tip and recorded (expected: `exchange_economics` absent).
5. Owner: manual trading paused from session 0's T-40 min; `init-ledger` once; `baseline --label t40` within 90 min of
   start (T-24 is not required for session 0); `preflight --session0 --run 0a ...` PASS same UTC day; `.env` topology
   unchanged (signer != funder, CLOB host, chain 137).
6. 88a `--extra-conditions` and shadow-scope files in force supplied to the session-0 selector; the owner checks
   rules 1-2 by eye before `go <6 hex>`.
7. The S0 verify commands rehearsed once with no orders (open-order helper prints `0`).
8. Session 1 may not start until `session0_passed` (as fixed) is true and S0-2 on 0c measured <= 20 s.
