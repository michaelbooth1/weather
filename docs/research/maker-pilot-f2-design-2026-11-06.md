# F2 design: one LFC session quoting K bands, plus M and the recording fixes

**Status (2026-11-06 14:1x ET):** master APPROVED this design (sha256 `7f0c1d24…` of the draft below) with the
rulings in §8, which override the sections they name. The next workstation agent implements from this file.

Lane F2, workstation, written 2026-11-06. **This is a design only.** It is for master's approval before any code is
written. Nothing was run, built or committed. Code is cited at pin `124603578`
(`C:\wt\lfc-pinned-124603578\src\weather\market\`) unless a citation says otherwise. P-B is
`C:\t\pilot1109\PB_300_DESIGN.md`; P-A is `C:\t\pilot1109\PA_GAP_LIST.md`. The venue API facts come from the
Data API v2 OpenAPI file, `C:\t\pilot1109\apiprobe\openapi.json` (sha256 `cf4ceff8…8fea`, fetched 2026-11-06).

## 0. Scope (master rulings of 11-06, recorded in the C14 DL row)

- **In scope:**
  - **(b)** one session quotes K bands, one per event, on TOR/DEN today's and tomorrow's events (K ≤ 4).
  - **M**, which splits the cap from the ledger identity.
  - The recording fixes in §4.
  - Clarification F, which sets the per-date cap at K × 19.60 and the daily loss cap.
- **Unchanged:** size 20, per-order cap 15.80 and per-band cap 19.60 (`lfc_constants.py:25`, `:30-33`).
- **Not in F2:** LA, and the R1/R2 international cities. Those are F3.
- **Session 1 (Mon 11-09)** runs on F0 (§1), not on F2. F2 starts at the earliest on a later date, after its own
  review, pregate, signed F and both money yeses.
- **Growth is by breadth:** first K bands on TOR/DEN (F2), then more markets (F3). Size never grows.

## 1. Prerequisite F0: the Data API v2 migration (Monday blocker; F2 builds on F0)

The venue retired Data API v1 on 2026-11-02. The last 200 was at 22:25:05Z and the first 410 at 22:30:04Z, according
to the reader log. CLOB routes are unaffected.

| v1 use at the pin | Where | v2 replacement |
| --- | --- | --- |
| Account positions (t24/t40 baseline, start gates) | `lfc_ledger.py:49` `POSITIONS_URL`; `fetch_account_positions` `:413-433`; `normalize_positions` `:436-443`; callers `lfc_cli.py:579` (`run_baseline`) and `:661` (`start_gates`) | `GET /v2/positions` (see the details below) |
| Owner snapshot positions | `lfc_session_driver.py:830-842` → reader `wallet_reader._position_rows` (reader `:192-210`) | The same change in the reader, plus a reader restart (owner yes) |
| REWARD distribution candidates | `re1_payout_evidence.py:93`, `:200-215` (`list_activity`, v1 `/activity`) | `GET /v2/activity?type=REWARD` (cursor paging, ASC, start/end) |
| Public trade prints (maker shadow) | `maker_core/venue/public_feed.py:18`, `:40`; used by `maker_core/shadow/runner.py:222`, `records.py:180` | `GET /v2/trades?condition=…` (cursor paging) |
| Official current positions | `mm_official_adapter.py:28`, `:32` | `/v2/positions` (not on the LFC path) |

Details of the `/v2/positions` call, which replaces `fetch_account_positions`:

- **Request:** `user`, `limit=100`, a `cursor` loop until `next_cursor` is null, and `include_archived=true`.
  `offset` is gone (sending it gives 400). The response is the `{data, pagination}` envelope.
- **Status set (CORRECTED from the 13:42 message to master).** The OpenAPI text says "`OPEN` is the superset; it
  includes settled-but-unredeemed winners". `REDEEMABLE` and `MERGEABLE` are narrowings of `OPEN`. `REDEEMABLE_LOST`
  is a separate status that needs `user`.
  - **Proposed set:** `OPEN ∪ REDEEMABLE_LOST`, de-duplicated on `token_id`.
  - `CLOSED` (exited positions) is excluded.
  - This replaces v1 `sizeThreshold=0`.
- **Dust floor.** v2 drops holdings under 0.1 shares by default (`filter_type=TOKENS`, `filter_amount` defaults to
  0.1, and "invalid values fall back to the default"). F0 sends `filter_type=TOKENS&filter_amount=0`. One read-only
  probe must show that 0 is accepted. If it is not, the 0.1 floor is recorded as a known deviation: a partial fill
  under 0.1 share is under one cent of exposure.
- **Normalization:** read `token_id` and `current_size`. A row missing either is refused (it is never defaulted to 0;
  the v1 `size` field is absent in v2). Any non-200 reply, a missing envelope, or exceeding the page budget fails
  closed with `positions_unreadable` or `positions_page_budget`, as today.

F0 is a separate pin (current proposal: 124603578 plus one commit, constants unchanged). It carries only the positions
change and its tests. The activity and trades changes ride in F2, or in a separate maker_core fix; the shadow change is
host-side and out of this lane. F2 is branched from F0.

## 2. How the pin enforces one band, and what (b) changes

The pin enforces one band in five places. P-B §7.1 has the full table.

- **One condition and token pair per `Session`.** Leg indices are only 0 and 1 (`re1_attended.py:425-441`). Submit
  and requote limits are per session: `MAX_SUBMITS=10` and `MAX_REQUOTES=4` (`:32-33`, `:436`, `:683`).
- **The first own fill ends the session.** `HoldEnd('fill')` at `re1_attended.py:394`, `:402`, `:416`, `:498`, `:511`.
- **The selector returns one `selected_condition_id`.** `mm_stage2_selection.py:30-130`, used at `lfc_cli.py:667-670`.
  The table is validated by `lfc_pilot.py:475-489`, and the pilot-market check is `:486`.
- **One live start per process** (`lfc_cli.py:618-621`). One session is open at a time (`:287-288`), and each local
  date is used once (`:297-300`).
- **The host mutex** `Global\WeatherProjectHeavyWorkloadV1` (`re1_evidence.py:25-62`, non-blocking wait at `:55`) is
  held for the whole live run (`lfc_cli.py:640`).

**Why (b) rather than N processes (a).** Under (b) one process owns every order, so these stay correct with no change:
the foreign-order check (`lfc_pilot.py:695-730`), the account-wide `cancel_all` (`re1_attended.py:220`), the venue
heartbeat dead-man, the mutex, and the ledger's single-writer guard. The ledger has **no lock**: `append` checks the
file size against `_raw_len` (`lfc_ledger.py:272-300`, `ledger_changed_underneath` `:281`), and there is no OS lock.
Under (a) that would race. Under (b) the single writer is still the only writer, so **F2 adds no ledger lock**, but a
test asserts that a second writer is refused.

### 2.1 Change set for (b)

1. **Session generalised to K bands.** `Session` holds `bands: list[Band]`, each with its condition, token pair,
   prices, active legs, requote counter and freshness state. Leg ids become `(band, leg)` pairs; the `leg not in (0, 1)`
   check (`re1_attended.py:425-441`) becomes per band. `MAX_SUBMITS` and `MAX_REQUOTES` become per band
   (decision D3). The minute loop (`:646-697`) takes one snapshot per band. A stale band ends only that band. Market
   snapshots, the geoblock, the heartbeat and the foreign-order check stay session-wide.
2. **Fill rule per band.** A fill on band i retires band i: cancel its remaining leg, and record the fill and the hold.
   The other bands keep quoting. The session ends when every band is retired, at the fixed end, or on any
   session-wide stop. This replaces `HoldEnd('fill')` as a session end (the five sites above). Decision D2 is the
   owner's.
3. **Reserve summed over bands.** `post_gate` (`lfc_ledger.py:241-254`) receives the sum of every band's
   reserve and resting amount. `BAND_CEILING`/`capital_cap` (`re1_attended.py:153`, `:441`; `lfc_pilot.py:436`)
   stays per band at 19.60. A new `PER_DATE_CAP_PUSD = K_MAX × 19.60` caps the session sum. `pilot_quote`
   (`re1_sizing.py:38`) is called per band against the remaining headroom.
4. **Selector returns the top K, one per event.** The candidates are the TOR/DEN events for local today and tomorrow
   (`PILOT_MARKET_IDS` `lfc_constants.py:37`, unchanged). The selector picks the best eligible band per event, then
   ranks events by the existing order. The confirmation table and go code cover K rows (`lfc_cli.py:539`, `:667-670`).
   The rule held-event → exclude (`lfc_cli.py:495-497`; `mm_stage2_selection.py:76-81`) is applied per event.
5. **Per-condition screens.** The driver's neg-risk, allowance and spender screens run per selected condition
   (`lfc_session_driver.py:62-70`). The fee class runs per condition every minute (`lfc_constants.py` D7 note;
   `lfc_fees.py`). A panel-exclusion row is written per band.
6. **Journal and analysis.** Every journal row carries `band`. `lfc_analysis.py` keys markouts by `(condition, leg)`;
   its 60/300/1800 s horizons are unchanged (`lfc_analysis.py:30`).
7. **Session and date rules are unchanged.** There is still one session per local date (`lfc_cli.py:297-300`) and
   `MAX_SESSIONS` (`lfc_constants.py:50`; D5). The t24 20-30 h window (`lfc_ledger.py:509-511`) is unchanged.

## 3. M: split the cap from the ledger identity

> **Ruled (D4):** a constant `CAP_PUSD`, not the `cap_amend` event below. See §8.

The problem (P-B §0.1): `BUDGET_PUSD` (`lfc_constants.py:49`) is both the cap and the genesis identity check, at
`lfc_ledger.py:103-104` (create) and `:126-127` (`ledger_budget_differs`). The session-0 pass is bound to the existing
ledger (`lfc_cli.py:253`, `:301-302`), and session 0 cannot be re-run (deadline 10-25, `lfc_constants.py:91`).

The design:

- Rename the identity constant to `GENESIS_BUDGET_PUSD = Decimal('100')`, used only at `:103-106` and `:126-127`. The
  existing ledger and the session-0 pass stay valid.
- **The cap becomes a ledger event, not a constant.** Add one new event, `cap_amend {cap_pusd, clarification_sha256,
  previous_cap_pusd}`, appended once through the normal hash chain (`lfc_ledger.py:272-300`). Then
  `Ledger.cap() = latest cap_amend.cap_pusd`, or 100 if none exists. The rules for appending it:
  - only by a new owner-run CLI command `lfc_cli cap-amend --clarification <path>`;
  - the command refuses unless the file's sha equals the constant `CLARIFICATION_F_SHA256`;
  - it also refuses unless the cap is 300 or less, the cap does not fall below L_filled + L_resting, and no session is
    open.

  A constant would bind the cap to the code. The event binds it to the signed text and keeps the audit trail in the
  ledger.
- **Call sites that read `Ledger.cap()` instead of `BUDGET_PUSD`:**
  - `headroom`, `stop_reason` and `post_gate` (`lfc_ledger.py:228`, `:231`, `:241`, `:248`);
  - `lfc_pilot.py:236`, `:412` and `:453`;
  - `mm_stage2_selection.py:88`;
  - `lfc_cli.py:544`;
  - the figures row (`lfc_ledger.py:306`).

  That is about 10 sites.
- **Permanent stop:** "Stop at cap" keeps the PR §6 rule against the new cap, with `MIN_FEASIBLE_RESERVE`
  (`lfc_constants.py:59`) per band.
- **Tests:**
  - an old ledger opens, and the cap is 100 when no event exists;
  - `cap_amend` is refused when a session is open, when the sha is wrong, when the cap exceeds 300, or when the cap is
    below the committed L;
  - the chain still verifies after the event;
  - `ledger_budget_differs` still fires on a genesis that is not 100.

## 4. Recording fixes

| # | Gap at the pin | Fix |
| --- | --- | --- |
| R1 | **Venue settlement winner.** `lfc_analysis.py:9`, `:173-181` takes a `{condition_id: winning_token_id}` map "from the settlement ledger's winner". That ledger is the WU proxy, which agents never read, and it is not the venue's result. | A new read-only recorder, `lfc_settlement_record`, calls `GET /v2/resolutions?condition=<c1,c2,…>` (comma-separated; misses return `{"data": []}`). It writes create-only `settlement/<condition>.json` holding the raw response, its sha256, `observed_at_utc` and the winning token. It is re-read until the resolution is terminal, and is never inferred from price. `lfc_analysis` reads only these files. Run by the LFC analysis lane (master ruling); no ledger.jsonl read. |
| R2 | **Eligibility every 1800 s.** `scoring` and `accrual` are sampled together on `next_accrual` + 1800 (`re1_attended.py:668-672`). | Separate the two. `scoring` (the CLOB order-scoring read through `re1_transport.py:433`) runs every 60 s, inside the minute block, for every active leg of every band. `accrual` stays on 1800 s. Each scoring sample is a journal row `scoring {band, order_id, scoring, observed_at_utc}`. A transient failure records `scoring_missed`, as `minute_missed` does (`:654-657`), and never ends the session. Load is K × 2 order ids per minute on one batched call. |
| R3 | **Paid rewards D+1/D+2 are read by hand.** | A new owner-run command, `lfc_cli rewards-record --date D`, runs on D+1 and again on D+2. It uses the existing `collect_accruals` (`re1_payout_evidence.py:172-195`, CLOB `/rewards/user`, `/rewards/user/total`), plus REWARD distributions via `/v2/activity?type=REWARD` (the F0-style port of `:198-215`). It writes create-only `rewards/<D>-d1.json` and `-d2.json`. It is a scheduled-by-owner reminder, **not** a Scheduler task (any Task Scheduler entry needs the owner's yes in this chat). Master ruling: the owner runs it, or the WS runs it on the owner's yes in this chat. |
| R4 | **Rebate source not identified.** `lfc_fees.py` records only the fee-schedule `rebateRate` (`:181-199`). No credited rebate is read. | Source found: `GET /v2/activity?type=MAKER_REBATE` (accepted type list in the OpenAPI), and the `maker_rebate` field ("Maker-side fee rebates credited") in the v2 user-PnL schema. The recorder reads `MAKER_REBATE` rows for the session's UTC days into `rewards/<D>-rebate.json`, in the same D+1/D+2 pass as R3. Weather markets classify as taker-only/fee-free (D7), so rebates are expected to be 0. A non-zero row is recorded and flagged, never netted silently. |

## 5. Caps, loss terms and the $300

Values below are under F2 with `K_MAX = 4`. The final figures are set by Clarification F (D1).

- **Per band:** 19.60 by the L measure, 15.80 true (unchanged; P-B §5).
- **Per session date:** `PER_DATE_CAP_PUSD = K × 19.60`, which is **78.40** at K = 4, and 39.20 at K = 2. It is
  enforced in the post gate (§2.1 item 3).
- **Daily loss cap.** This is not in code at the pin (P-B §1). F2 puts it in code as `DAILY_LOSS_CAP_PUSD`, checked
  before every post:
  - the worst case for the session date is `L_filled_today + L_resting_today + reserve` ≤ the cap;
  - the worst case for the settlement date counts both lots landing on that date (P-B §5: T+1 from X−1 and T+2 from
    X−2).
  - Proposed: **the cap = the per-date cap**. Master/F to set it. If it is below K × 19.60, it effectively lowers K.
- **Early stop.** P-B §1 shows the $50 realised stop is not in code. F2 adds `REALISED_STOP_PUSD`:
  - start gates refuse once recorded realised loss reaches it;
  - realised loss = Σ over settled lots of (cost − payout), computed from R1 settlement files and ledger fills;
  - an unknown settlement counts as a full loss of that lot;
  - the value is set by F (the 10-26 terms say $50 against $100; the $300 terms need the owner's number).
- **Total:** `L_filled ≤ cap` always (post-gate invariant). With cap 300 and K = 4 the structural maximum is
  min(300, sessions × 78.40). 4 sessions already reach 300.
- **Funding:** wallet cash 920.24 pUSD (11-06 snapshot) covers 300; no deposit is needed.

## 6. Order of work, tests and gates

1. **F0** (Sat 11-07): positions v2, tests, Opus review, pregate, DL row, locked worktree. Owner yeses in this chat.
2. **F2 code** after this design is approved, branched off F0, in this order:
   - M (§3);
   - R1/R2/R3/R4 (§4), which are independent and lower risk, and can land before (b);
   - (b) (§2.1).
3. **Tests**, in focused owner-package files: K = 1 regression (F2 with K = 1 must reproduce the pin's journal shape);
   K = 2..4 posting/requote/cancel; per-band fill retirement; a session-wide stop cancelling all bands; summed reserve
   at the cap edge; per-date and daily-loss refusals; the realised stop; `cap_amend` (§3); the 60 s scoring cadence
   and its failure path; settlement and rebate recorder fixtures; the selector's one-per-event ranking; a
   `test_lfc_clarification_e.py` update (`PILOT_MARKET_IDS` unchanged, so only the new constants are pinned).
   - Run through `scripts\ops\workstation_heavy.ps1 -Queue`, never inside the Mon 08:00-18:00 freeze or from Sun
     11:45.
4. **Gates:** Opus review, bounded suite, pregate on the F2 sha, signed Clarification F (caps, K, daily loss, the
   realised stop, the 60 s scoring, the per-band fill rule), DL pin row, new locked worktree, G13 config copy (owner),
   and both money yeses naming the F2 sha.
5. **Rough size:** (b) is 6-9 files, about 30-50 sites and 20-30 tests (P-B §7.3), M is about 10 sites and 6 tests, and
   R1-R4 is about 4 files and 10 tests. Realistic time is 4-6 working days plus review. So the earliest F2 session
   is about Mon 11-16, with t24 on Sun 11-15. `LAST_START_LOCAL_DATE` is 11-20 (`lfc_constants.py:70`), so F should
   extend it (D5).

## 7. Open decisions for master (and the owner where marked)

- **D0 (F0, urgent):** the status set `OPEN ∪ REDEEMABLE_LOST` + `include_archived=true` + `filter_amount=0`. If 0 is
  refused, accept the 0.1-share dust floor as a deviation?
- **D1:** `K_MAX` (proposed 4; 2 = TOR+DEN tomorrow only), the per-date cap (K × 19.60) and `DAILY_LOSS_CAP_PUSD`
  (proposed equal to the per-date cap). Owner money terms.
- **D2 (owner):** the per-band fill rule. Retire only the filled band, or end the session on the first fill as today?
- **D3:** `MAX_SUBMITS` and `MAX_REQUOTES` per band (proposed 10 and 4 per band) or scaled per session.
- **D4:** the cap mechanism: the `cap_amend` ledger event (proposed) or a constant `L_CAP_PUSD`.
- **D5:** `MAX_SESSIONS` and `LAST_START_LOCAL_DATE` under F. P-B's F1 proposal was 12 sessions, 4 h each, last start
  11-27. Does F fold F1 in?
- **D6:** `REALISED_STOP_PUSD` for the $300 terms (owner). Should an unknown settlement count as a full loss
  (proposed yes)?
- **D7:** whether R1-R4 may land, ahead of (b), on a recording-only pin used by sessions 2+, which would carry the 60 s
  scoring and the recorders sooner.
- **D8:** the WS reader v2 patch and restart window (the owner's yes in this chat, before Sun 11:45). The maker_core
  `/trades` v2 fix is host-side: does that go to the production agent?

## 8. Master rulings (2026-11-06 14:1x ET)

- **D0 (F0): ruled.** `OPEN ∪ REDEEMABLE_LOST`, `include_archived=true`, `filter_type=TOKENS`, `filter_amount=0`,
  de-duplicated on `token_id`; conflicting sizes refuse. The 0.1-share fallback is accepted as a recorded deviation.
  Before the t24, the v2 token set is diffed against the last good v1 read; every v1 token of 0.1 share or more that
  is absent from v2 is explained (redeemed, closed or sold) or flagged. A missing holding would silently disarm the
  held-condition refusal. F0 is commit `12c0507` on `claude/lfc-f0-positions-v2-20261106`.
- **D3: per band.** `MAX_SUBMITS=10` and `MAX_REQUOTES=4` per band, so each band behaves exactly like the pinned
  single band.
- **D4: a constant.** `CAP_PUSD` lives separately from `GENESIS_BUDGET_PUSD = 100`, which stays the identity check.
  The `cap_amend` event and the `cap-amend` command in §3 are dropped. The call sites in §3 read `CAP_PUSD`. Add a
  start-gate test that `CAP_PUSD` is at least the committed L. The money yes binds to the pin sha.
- **D7: yes, conditionally.** A recording-only intermediate pin (R1-R4) for sessions 2+, only if it is ready about
  11-11 without delaying F2; otherwise R1-R4 fold into F2. R3 stays owner-run, never a Scheduler task.
- **D8.** The WS reader v2 patch and restart need the owner's yes in the WS chat before Sun 11:45. The host
  `maker_core` public_feed `/trades` v2 fix is master's, after Monday, in the quiet window (roll-sensitive).
- **Owner decisions pending (D1, D2, D5, D6).** Master brings them to the owner as one money set when F2 nears its
  pregate. Master recommendation, owner decision pending:

  | Decision | Master recommendation |
  | --- | --- |
  | D1 `K_MAX` | 4 |
  | D1 per-date cap and daily loss cap | both $78.40 |
  | D2 fill rule | retire the filled band only |
  | D5 sessions and last start | 12 sessions, last start 11-27 |
  | D6 realised stop | $150; an unknown settlement counts as a full loss |
