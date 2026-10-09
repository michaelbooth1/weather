# Live Fill-Calibration Pre-registration (DRAFT for owner signature)

Status: DRAFT, 2026-10-09. Not signed. It authorizes no order. When it is
signed, it governs only the eight owner-started live fill-calibration
sessions defined here. It is descriptive only and makes no promotion,
edge, or readiness claim. International Polymarket only.

Owns: the estimands, band selection, dates and panel-exclusion rule, hard
limits, loss ledger and pre-declared plan changes for the live
fill-calibration campaign.

Read when: you are building, reviewing, starting or analysing a
live fill-calibration session, or reading any panel whose dates overlap the
campaign.

Update when: never in substance after signature. A change after any session
input is read needs a dated clarification appended at the end, stating
whether data was seen.

Design source: `claude/live-fill-calibration-design-20261009` @ `22112f73`,
`docs/research/live-fill-calibration-design-2026-10-09.md` (owner-approved
2026-10-09 ~14:40, with updates 1 and 2 relayed ~14:50 and ~14:55).
Companion files on this branch:

- [panel clarifications](live-fill-calibration-panel-clarifications-2026-10-09.md),
  which must be signed before any panel read;
- the [session-0 spec](live-fill-calibration-session0-spec-2026-10-09.md).

## 1. Question and estimands

The question is how the replay fill rule maps to the fills our own resting
post-only quotes actually receive. The estimands below are descriptive. No
threshold on them promotes anything.

| Estimand | Definition |
| --- | --- |
| `c_at` | Σ our filled shares attributable to at-price public prints ÷ Σ over at-price prints of min(print size, our remaining size), taken over all prints at exactly our bid while a leg rests. |
| `c_thr` | The same ratio over strictly-through prints, meaning prints below our BUY bid. |
| `q_ahead` | Displayed size at our price level in the last 88a book snapshot before our post acknowledgement. It is reported as a distribution, and `c_at` is also reported by `q_ahead` tercile. |
| Markouts | For each own fill: (two-sided 88a mid at fill + h) − fill price, signed for the leg, at h = 1, 5 and 30 min. The 88a snapshot nearest to t + h must lie within 120 s, otherwise the markout is missing (not imputed). A settlement markout is computed against the ledger winner. |
| `f̂` | Fraction of own fills whose 30-min markout is ≤ −2 c, reported alongside the settlement-markout sign. |

Attribution and sources:

- An own fill is any trade carrying one of this campaign's script order IDs,
  per the venue trade record joined to the session `journal.jsonl`. Nothing
  else counts.
- Public prints, books and `q_ahead` come **after the fact** from 88a passive
  capture. The selected bands enter 88a scope through `--extra-conditions`
  where needed (§4). They are not captured live by the session script, and
  print-level live capture is out of scope.

Reporting: each ratio is reported with its achieved denominator N and an
exact (Clopper–Pearson) 95 % interval treating prints as units. There is no
minimum N and no pooling with replay or shadow results. The first descriptive
read is allowed after session 1. Interim reads change nothing except through
§8.

### N_at prior count (from RE-1 journals ≤ 2026-09-29)

| Item | Value |
| --- | --- |
| Source | `%USERPROFILE%\.weather-re1m-20260921\session-{1..12}\journal.jsonl`. These are 12 attempt folders, all recorded UTC 2026-09-23..09-25. Any record after 2026-09-29T23:59:59Z is skipped by the counter. |
| Signal available | The only public-print signal is the `last_trade_price` field of the per-minute CLOB `/book` payloads. No trade-tape records are journalled. |
| Method | Count changes of `last_trade_price` between consecutive minute snapshots while both legs rest. A change is at-price when the new value equals our bid on that token, and through when it is strictly below our bid. |
| Result | 313 resting minutes, 2 changes, **N_at = 1, N_thr = 1**. |
| Own fills in the same attempts | 5 fills (4 at price, 1 strictly through), ending attempts 1, 5, 8, 9 and 12. |

The counter returns a lower bound that cannot be used as a prior. The field
is minute-sampled and unchanged across several of our own fills; in one
attempt it stayed at 0.410 for 88 minutes while our YES leg filled at 0.35.

**N_at is therefore declared unknown** for power purposes. The campaign does
not depend on a power target. Pre-campaign 88a prints for dates ≤ 2026-09-29
could give a prior, but the counter is not run here, because that capture is
production-side.

## 2. Quote (RE-1-faithful)

Each session quotes the RE-1 attended maker quote:

- two post-only GTD BUY legs, YES at m − d and NO at (1 − m) − d;
- d = 1.5 c, snapped outward to the 0.01 tick;
- a requote only when a leg leaves [1, 3] c of the mid, at most 4 requotes;
- the first own fill ends the session, and the filled lot is held to
  settlement.

Session length is 360 min, with one band per session.

**Declared deviation: 40 shares per leg instead of 75.** Each leg then costs
at most 32 pUSD (40 × 0.80), so the worst case of a double fill on one band
(64) plus the next band's reserve can never exceed the 100 pUSD L budget
in §6. 40 is also at or above the reward minimum the selection rule requires
(§3), so the quote keeps reward eligibility, and the RE-1 depth filter of 75
is kept. The deviation changes only exposure. `c_at`/`c_thr` are ratios per
offered share and are compared to replay at the same size.

## 3. Band selection (mechanical)

The session script runs selection at T − 30 min. The owner may veto only
the whole session, never a band. The rules:

1. **Universe.** The 12 built-in markets (canonical registry), local T+1 and
   T+2 event dates relative to the session's local quote date, with the
   condition rewarded on CLOB `/rewards/markets` at selection time.
2. **Filters.** A band passes only if every one holds:
   - reward rate ≥ 40 pUSD/day and reward minimum size ≤ 40;
   - reward max spread ≥ 3 c, and displayed spread ≤ 6 c;
   - the book is two-sided and uncrossed;
   - mid ∈ [0.20, 0.80] on the 0.01 tick;
   - displayed depth ≥ 75 shares on each side of the YES book within the max
     spread;
   - predicted `share_many` ∈ [0.15, 0.70];
   - both leg prices ∈ [0.17, 0.80], and each leg cost ≤ 32;
   - the wallet baseline (§5) holds no position in **any** condition of the
     same event;
   - the band can be inside 88a capture scope for the whole session, as a
     configured city (T+1/T+2 is native scope) or through `--extra-conditions`.
3. **Rank.** Bands are ranked by predicted reward at size 40. Ties go by the
   RE-1 location order, then by ascending condition ID. The top band is
   posted.
4. **RE-1's predicted-reward ≥ 2.0 threshold** is (owner ruling **R6**):
   - kept: no session when no band meets it;
   - or dropped: rank only.

   Default if the owner is silent: **kept**.
5. **Record.** The script writes the full candidate table and the selected
   band to `selection.json` before the first post. It records the file's
   SHA-256 in `journal.jsonl`.

## 4. Dates rule and mechanical panel exclusion

**Dates.**

- No campaign order may rest before **2026-10-15T00:00:00Z**. The constant is
  enforced in code and replaces RE-1 `LAST_DAY`.
- The earliest session is the owner's local afternoon of **2026-10-15**, for
  example 13:00–19:00 ET = 17:00–23:00Z. A hard stop at 23:50Z keeps a
  10-15 session inside UTC 10-15.
- Sessions are on distinct local dates. The last session must start by
  2026-10-31, and lots are held to settlement.

**Why UTC 10-15 is clean (from spec text only, no data read).**

- *v2 replay registration.* The quote panel is UTC 09-30..10-13. UTC 10-14
  and 10-15 are settlement-only days with no active intervals or quote minutes
  (registration draft line 47, change C9). Our orders cannot change WU
  settlement facts, and no 10-13 markout horizon reaches 10-15. The export gate
  [09-30, 10-16) is unaffected because no quote interval is defined on 10-15.
- *Desk-study pre-registration.* The decision panel is event dates
  10-17..10-30, extended to 11-13 when N_req is 15–28. A T+1 band quoted on
  local 10-15 (event 10-16) lies outside both panels. A T+2 band (event 10-17)
  lies inside, and the exclusion below covers it.
- *Owner option R4.* Restrict the 10-15 session to T+1 only. That avoids
  removing any desk-panel band-day on 10-15.

**Exclusion rule (applies to every registration whose panel overlaps the
campaign).**

Exclude every band-day (C′, D) where:

- C′ is any condition in the same event as a condition that carried a
  campaign order, and
- D is a local quote date on which a campaign order rested.

This includes the desk-study panel, any v2 or shadow-parity panel, and any
later candidate exam, for example a deferred candidate-2 exam with panel
10-16..10-29.

Mechanics:

- Before the first post, the session script appends the would-be exclusions
  for the selected band and date to `panel_exclusions.jsonl` in the campaign
  root, with fields `event_slug`, `condition_ids`, `local_quote_date`,
  `session_id` and `appended_utc`.
- It records the line's SHA-256 in `journal.jsonl`.
- Panel selectors read this file and drop those rows **before** any outcome
  is read.
- The exclusion is unconditional: it applies whether or not the session
  filled.
- Shadow fills on excluded conditions are reported separately and never
  pooled.

Session 0 (§9) adds no exclusion, because its market is outside every panel
by construction.

## 5. Wallet, attendance and notification

**Wallet.**

- The owner's existing wallet is used; it is not a fresh wallet.
- The owner pauses all manual trading from the start of session 1 until the
  last campaign lot settles.
- Pre-existing positions and orders are excluded from every campaign figure.

**Baselines.** The owner runs a wallet-reader snapshot at T − 24 h and at
T − 40 min:

```powershell
.\venv\Scripts\python.exe -m weather.market.wallet_reader_client summary
.\venv\Scripts\python.exe -m weather.market.wallet_reader_client open-orders
.\venv\Scripts\python.exe -m weather.market.wallet_reader_client positions
```

The session preflight hashes both baselines into `journal.jsonl`.

**Attendance.**

- The owner starts each session (`go <6 hex>` confirmation, as in RE-1).
- Sessions run unattended after start. Only the hard limits (§6) end a
  session.
- Every end path does cancel-all and reconcile with no human present.

**Notification.**

- At session end, the script writes `session_end.json` (reason, L, open
  orders, fills) and raises an owner notification on the channel the owner
  names (prerequisite P8).
- When the notification fails, the session still ends cleanly, and the
  failure is recorded.

## 6. Hard limits

All RE-1 hard limits stay in force, adapted only for size 40 and the
existing wallet (prerequisite P4). A breach of any limit ends the session
through the dead-man cleanup in §7.

| Limit | Rule |
| --- | --- |
| Order shape | BUY, post-only, GTD, size exactly 40; price ∈ [0.17, 0.80] on the 0.01 tick. A crossing leg against a fresh ask is refused. |
| Capital | Order cap 0.79 × 40 = 31.6 pUSD; band cap 0.98 × 40 = 39.2 pUSD. |
| Submits | ≤ 10 submits and ≤ 4 requotes per session. The 5th requote ends the session. |
| Open orders | Open orders must be exactly ours and ≤ 2. **Any foreign open order on the account ends the session**, whether found by the preflight or at runtime. The preflight requires zero foreign open orders. |
| Freshness | Submit needs a market snapshot ≤ 10 s old. Market snapshot stale at 300 s, user stream silent at 30 s, or geoblock check failed (30 s cadence, 45 s budget): the session ends. |
| Venue terms | Reward min size > 40, rate < 40, tick ≠ 0.01 or min order size > 40: the session ends. |
| Events | A fill, an unknown user event, an order no longer resting, a cancel acknowledgement, a cancel not terminal, or a journal write failure: the session ends. |
| Campaign | ≤ 8 counted sessions (session 0 is separate), each ≤ 360 min, with GTD expiry = session end + 60 s and no submit under 180 s remaining. |
| L ledger | See below. |

**L ledger (campaign-wide worst-case loss, pUSD).** Only orders and fills
carrying this campaign's script order IDs count; session 0 counts. At any
instant:

```text
L = Σ_{own filled legs} filled_shares × fill_price        (recovery counted as zero)
  + Σ_{own resting legs} remaining_shares × limit_price
```

- Filled cost is never released, whether by settlement, payout or anything
  else. Resting cost is released only by a terminal cancel confirmed by the
  venue.
- A band may be posted (and a requote submitted) only if both hold:
  - L_after_cancel_of_replaced_leg + reserve ≤ **100**, where reserve =
    40 × (p_yes + p_no) for the band being posted;
  - available pUSD cash (wallet-reader `summary`) ≥ L_resting + reserve.
    This is the conservative reading of "cash must be at least that".
- L is recomputed from the journal plus venue terminal-order and trade reads
  at preflight, after every fill or cancel, and at cleanup. It is persisted to
  `l_ledger.json` with an append-only history.
- **Stop at 100:** the campaign ends permanently once L_filled + the minimum
  feasible reserve exceeds 100, or on any reconciliation mismatch in L. No
  new session may start after that.

## 7. Dead-man and unattended cleanup (RE-1 pattern, exact)

These are the RE-1 layers at `codex/re1-wallet-200-20260923` @ `2b9a0ca9`
(`re1_resilience.py`, `re1_attended.py`), kept unchanged except for the
noted additions.

1. **Heartbeat thread.** It sends the venue heartbeat every 2 s. When no
   heartbeat succeeds within 8 s, the session ends.
2. **Main-loop watchdog.** The main loop stamps progress. When it is stale for
   20 s, the heartbeat thread *stops sending* (`main_loop_stalled`), so the
   venue cancels server-side.
3. **Venue cancel-on-disconnect.** A missed heartbeat makes the venue cancel
   all orders after 10 s. The design allows a 5 s buffer (EF §10i), so the
   expected time to zero resting orders is 15 s at most.
4. **GTD backstop.** Every order expires at session end + 60 s, so even total
   loss of the host leaves no order alive past the session.
5. **atexit / end-path cleanup.**
   - Cancel each order, then `cancel_all`.
   - Poll `open_orders` until it is empty, for up to 10 s.
   - Read the terminal orders, positions and trades; recompute L; write
     `session_end.json`.
   - If cleanup is not clean, print `PANIC` and notify.
6. **Changes from RE-1:**
   - Cleanup attributes fills by our order IDs, not by "any terminal
     position", because the wallet is not fresh.
   - The end-of-session notification is added.

**A heartbeat failure or script crash must leave zero resting orders.**

- A crash (including `taskkill /F`) skips atexit. Layers 1–3 then cancel
  within ≈ 15 s, and layer 4 bounds the residual.
- Session 0 forces both paths and verifies them independently (§9).

## 8. Pre-declared plan changes

| Trigger (read after any session) | Change |
| --- | --- |
| `c_at` ≥ 0.7 with N_at ≥ 10 | Read the replay at-price fill rule as the primary candidate. A replay rerun needs its own registration. |
| `c_at` ≤ 0.3 and `c_thr` ≈ 1 | The strictly-through rule stays primary. |
| 30-min markout ≤ −3 c on ≥ 5 own fills | K3: pause the campaign and re-derive the quote offset before any further session. |
| Zero own fills after 8 sessions | Revisit the shadow fill hazard. No size or offset change inside this campaign. |
| Any hard-limit breach that left a resting order past cleanup | Stop the campaign and audit before resuming. |

No other change to the estimands, selection, size or limits is allowed
without a dated clarification.

## 9. Session 0 (excluded from every estimand)

Session 0 is defined in the
[session-0 spec](live-fill-calibration-session0-spec-2026-10-09.md).

- It exercises the limits, the dead-man, the foreign-order check and the L
  ledger on a market outside every panel.
- It counts toward L. It is not one of the 8 sessions, and no session-0
  order, fill or markout enters `c_at`, `c_thr`, `q_ahead`, any markout or
  `f̂`.
- Session 1 may not start until session 0 has passed.

## 10. Prerequisites and owners

| # | Prerequisite | Owner | Blocks |
| --- | --- | --- | --- |
| P1 | **#180 OBSERVED config values** for the cross-check report. The owner supplies them; agents may not open `config/local/`. The values are `account_id`; campaign `id`, for example `lfc-2026-10`; `start_utc` (the session-0 T − 24 h snapshot time); `contributions` [{`id`, `at_utc`, `amount_pusd`: 100}]; `bleed_limit_pusd`: 100; `rules` by `condition_id` (appended per selected band); and `lot_overrides` for any pre-existing lot in a campaign condition. #180 is a reporting cross-check only. The guard is L in the script (owner: do not wire #180 first). Expect `INCOMPLETE` (exit 2) if pre-start lots touch campaign rules (`acquisition_before_campaign_start`). | Owner | the cross-check report only |
| P2 | **Econ gate (#271).** A transitive import scan of `weather.market.re1_attended_cli` at `2b9a0ca9` covers 161 modules: of the econ modules, only `exchange_economics_sources` (helpers) and `mm_stage2_selection` are imported, never `weather.market.exchange_economics`. Reward terms are read live from CLOB `/rewards/markets`, so #271 does not gate this path. **The scan must be re-run on the rebased code branch** before session 0. | Code-branch author, verified by reviewer | session 0 |
| P3 | **#263 N_req.** Whether the desk panel extends to 11-13 depends on N_req. `N_req` comes from the Part 1 pilot and is not changed by the exclusion. However, the §4 exclusion removes desk band-days within each date, so #263 (or the desk-study reader) must apply `panel_exclusions.jsonl` before the date means. If N_req ≥ 15, the extension to 11-13 overlaps every later session date. | #263 owner | desk-study read, not the sessions |
| P4 | **RE-1 code changes:** `SIZES` += 40; drop the `testing_wallet_cap` (wallet > 200) and `min(wallet − 10, 75)` sizing in favour of the L rule; replace the `initial_positions` refusal with the event-level position exclusion; attribute the cleanup fill by order ID; `LAST_DAY` → earliest 2026-10-15T00:00Z, last start 2026-10-31; `MAX_SESSIONS` 30 → 8; write `selection.json`, `panel_exclusions.jsonl` and `l_ledger.json`; add the session-0 mode (§9 spec); add the notification; rebase onto master. The RE-1 code lives only on `codex/re1-wallet-200-20260923`. All of it must pass fakes and tests before session 0. | Code-branch author | session 0 |
| P5 | **88a scope.** The selected bands must be inside 88a capture for the whole session. Raw-update windows for `--extra-conditions` are ≤ 1800 s each. The owner or ops agent confirms 88a is running on each session date. | Ops (capture host) | the after-the-fact estimands |
| P6 | **Signatures.** This document and both panel clarifications are signed by the **owner directly**: the 10-06 rule says relayed approvals are never valid for money. | Owner | everything |
| P7 | **Contract deviations acknowledged** (see R1–R3): SoP critical path 4; DECISION_LOG 09-25 (d); the pilot's isolated-wallet envelope; the OD11 first-live cap. | Owner | session 0 |
| P8 | **Notification channel.** Phone alerts were deferred on 09-27, so the owner names the channel, for example a local toast plus an e-mail draft or a file watch. | Owner | session 0 |

## 11. Owner rulings to sign

| Ruling | Choice |
| --- | --- |
| R1 | This campaign runs live before the v2 look and the ≥ 7-day parity milestone, as an explicit exception to SoP critical path 4 (relying on DECISION_LOG 10-07 row 78, which allows live prerequisites in parallel). ☐ yes ☐ no |
| R2 | The existing wallet is used, an exception to the pilot's dedicated isolated wallet ≤ 100. Containment is L ≤ 100 by script order IDs, plus a manual-trading pause. ☐ yes ☐ no |
| R3 | The DECISION_LOG 09-25 (d) "bleed limit in code before any RE-1 resumption" is satisfied by the in-script L ledger (§6), not by #180. ☐ yes ☐ no |
| R4 | The 10-15 session is restricted to T+1 only. ☐ yes ☐ no (default: no) |
| R5 | 40 shares per leg (deviation from 75). ☐ yes |
| R6 | RE-1 predicted-reward ≥ 2.0 threshold. ☐ kept ☐ dropped (default: kept) |
| R7 | The OD11 first-live cap (one band, minimum size, while real fills < 10) is read as satisfied by one band per session at 40, or the owner rules otherwise. ☐ yes ☐ no |

## 12. Signature

Signed before any session input, panel row or 88a row dated on or after
2026-09-30 is read for this campaign.

- Owner: ______________________  Date (UTC): ____________
- Data seen at signature: ______ (expected: none)
- Rulings R1–R7 as marked above.
