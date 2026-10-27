# Maker pilot: plan and readiness checklist (DRAFT)

> **Repository copy, filed 2026-10-26 in the docs head.** Copied unchanged from the coordinator's draft (raw
> sha256 `f90834fde1158325fe440481ca8b3a377550bd1369cb14d1896bbff63bae228e`) except for this note. **DRAFT, HOLD status; its owner questions are OPEN.** It grants no live, credential or order authority; the gates stay those of the [International MM live pilot](INTERNATIONAL_MM_LIVE_PILOT.md) runbook.
> Answers go to the [decision log](DECISION_LOG.md) (owner) and today's state to the [state of play](STATE_OF_PLAY.md),
> not into this text. Items marked master are master's rulings, not the owner's.

- **Status:** DRAFT for master and the owner, written 2026-10-25 on the workstation. It grants no authority,
  clears no HOLD and adds no gate. Every gate below is quoted from its owning document.
- **Owner basis:** 2026-10-25, verbatim "Yes to all", approving among others item (3) "The maker pilot"
  (relayed by master-agent).
- **Governing documents (read for this draft):**
  - The International MM live pilot runbook (`docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`, identical on `origin/master` @ `46dad240b` and
    `origin/claude/docs-head-20261026` @ `50ea908ee`): envelope, prerequisites 1-9, Stages 0-3, stop
    conditions, decision after the pilot.
  - Item 330 (`docs/roadmap/items/item-330-maker-economics-refocus-master-plan.md`): gates G0-G4, work
    packages W3-W7, parameters (§7).
  - `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md`: the `portable_execution_v1` profile and its Git
    source-authority rule.
  - Also read because they bind a live session: STATE_OF_PLAY (dated 2026-10-24), DECISION_LOG to 10-24,
    `maker-trading-guard.md`, the pilot preregistration
    (`docs/research/INTERNATIONAL_MM_PILOT_PREREGISTRATION.md`), and the signed LFC campaign files
    (`docs/research/live-fill-calibration-*.md`).
- **Hard constraints of this plan:** International Polymarket only. **No agent places, cancels or signs an
  order, ever, and no agent launches a stage wrapper or session script.** The **owner** starts every live
  session. **Credentials are never touched by agents**: no agent opens `.env*`, `*.cred`, `*.key`, `*.pem`,
  `config/local/*`, Credential Manager entries or wallet files.

## 0. The blocking gaps, first

The approval is real but the repository does not yet carry it, and the docs disagree with it. Until these
are closed the runbook's rule applies: "absence of an explicit dated authorization means HOLD".

| # | Gap | Where it shows | What closes it |
| --- | --- | --- | --- |
| G-a | **No DECISION_LOG row for the 10-25 approval.** DL ends at 2026-10-24 on both heads read. | DECISION_LOG | A dated row naming the lane, stage(s), dates, wallet and caps. |
| G-b | **STATE_OF_PLAY says live trading is paused** (owner 09-25), the LFC campaign is backlogged (10-19), and the 10-23 hard directive pauses maker and market-making development. | STATE_OF_PLAY "Current authority" and "Objectives" | An SoP rewrite whose Current-authority line names the authorized stage for a named date, and a DL row saying which part of the 09-25 pause and the 10-23 directive the pilot supersedes. |
| G-c | **Money approvals must come from the owner directly.** DL 10-06 (quoted in LFC prereg P6): relayed approvals are never valid for money. "Yes to all" reached the workstation relayed. | LFC prereg §10 P6; DL 10-06 | The owner confirms the pilot's money terms personally (signature line or own words in DL), not through a relay. |
| G-d | **"The maker pilot" is ambiguous.** The repo has two live maker lanes with different envelopes (§1). | this plan §1 | The owner names the lane. |
| G-e | **The portable branch named by the runbook does not exist on origin.** `git ls-remote origin` (2026-10-25) shows `codex/portable-execution-host-20260827` and `codex/live-gate-provenance-20260831`, but no `codex/portable-execution-host-clean-20260827`, which prerequisite 6 and the portable runbook name as the only allowed portable source. That exception is also recorded as spent. | `PORTABLE_LIVE_EXECUTION_HOST.md`; prereq 6 | A new dated owner authorization naming an exact existing, reviewed, exact-head CI-green branch, or the `capture_colocated_v1` lane on master. |
| G-f | **The pilot's 10 pUSD band cap makes rewards infeasible at 20 shares.** A two-sided 20-share quote costs about 19.60 pUSD, so it is reward-ineligible under the cap (digest, EF §10a). Same-day bands also flip to a 100-share reward minimum during the morning. | FINDINGS_DIGEST "Market making and economics" | Either accept a lifecycle- and rebate-only first cohort (item 330 G1's "separately labelled rebates-only hypothesis"), or the owner amends the envelope by a new dated decision (the runbook allows lowering caps only, never raising them, without one). |
| G-g | **Evidence reads after 09-29 are embargoed.** Agents may read no outcome, price or label after 09-29 (SoP), maker scoring refuses UTC 09-30..11-13 (DL 10-14), and descriptive reads of 10-16..11-13 are refused (owner 10-17). Stage 3 reconciliation needs agents to read the pilot's own orders, fills and balances. | SoP; DL 10-14, 10-17, 10-20 | An owner read clearance like LFC §9 ("agents may read only session 0's own orders, fills and journal"), scoped to the pilot's own order IDs. |
| G-h | **Panel overlap.** A live order on a band-day inside the 88a desk-study panel (event dates 10-17..10-30, possibly 11-13), the MG-1, MG-2, B or PT-1 dates changes the book those tests read. The pilot runbook has no exclusion rule; the LFC prereg §4 has one, for LFC only. | LFC prereg §4; reserved-confirmation-window | Apply the LFC §4 exclusion mechanics to the pilot by a dated owner decision, or schedule sessions outside every panel. |
| G-i | **Live work competes with the workstation's heavy lanes.** A launched live stage takes the host-global mutex and every extra heavy slot; heavy work must finish before sealing. The owner also wants the workstation kept fully busy (DL 10-24). | portable runbook; HOST_LOAD_POLICY | Master schedules a heavy-free block for each session. |

## 1. Which lane

| | Lane A: the sealed pilot protocol | Lane B: the LFC campaign |
| --- | --- | --- |
| Owner | `INTERNATIONAL_MM_LIVE_PILOT.md` + item 330 + item 67 | signed LFC prereg (owner signature 2026-10-09T18:09Z) |
| Wallet | Dedicated isolated wallet, ≤ 100 pUSD | Owner's existing wallet (ruling R2, an explicit exception) |
| Shape | Stage 0 no-order proof, Stage 1 far-from-mid smallest-size probes, then Stage 2 one band, one TTL | Two 40-share post-only GTD BUY legs, 360-minute sessions, first fill ends the session |
| Status | Stage 0/1 passed once, 2026-09-06, on unmerged code; **spent, grants nothing**. Stage 2 has never run. | Session 0 **ATTESTED** 2026-10-16 (pass.json `02298021…`); session 1 never ran; campaign backlogged 10-19. |
| Date limit | none in the runbook | "The last session must start by 2026-10-31" (prereg §4); a later start needs a dated clarification |

The brief for this draft says to follow lane A's documents exactly, so §2-§6 are lane A. Lane B is the lane
closest to running; if the owner means lane B, its own signed limits apply instead (§7) and lane A's
Stage 0/1 is not its prerequisite (the LFC lane "imports no sealer or stage-2 entrypoint", DL 10-12).

## 2. Gate-by-gate checklist (lane A)

Status words: **MET**, **NOT MET**, **N/A until session**, or **unknown, verify with master**. "Recorded in"
names where the status lives; nothing here is a live-host reading.

### 2.1 Authority

| Gate | Required | Status | Recorded in |
| --- | --- | --- | --- |
| Current authority | SoP names the stage for a named date; absence means HOLD | **NOT MET** (live trading paused) | STATE_OF_PLAY "Current authority" |
| Dated owner authorization for a new session | "A future session needs a new dated owner authorization and a fresh Stage 0/1" | **NOT MET** (gap G-a, G-c) | runbook "Current production disposition"; DECISION_LOG |
| Exact Git source authority | capture profile: `HEAD == master == origin/master == live master`; portable: the exact authorized branch, equality and ancestry proved fresh | **NOT MET** for portable (gap G-e); capture profile unknown, verify with master | runbook "Execution-host preparation"; Git |
| Resealed launchers | Live seals must be RESEALED before any sealed-lane attempt (#229) | **NOT MET** (SoP lists it as outstanding) | STATE_OF_PLAY "Current truth" |

### 2.2 Item 330 gates

| Gate | Required result | Status | Recorded in |
| --- | --- | --- | --- |
| G0 truthful baseline | Integrated source, branch dispositions, host/stage and evidence gaps recorded | unknown, verify with master (item 330's last execution status is 2026-09-05; the four 2026-09-06 control relaxations on the maker candidate still need an owner disposition each) | item 330 §9; item 67 |
| G1 feasible opportunity (W3) | At least one exact condition fits current rules, risk limits, reward eligibility and a plausible after-cost range, chosen by a recorded rule | **NOT MET**: no current exact-condition opportunity table; gap G-f | item 330 W3; digest |
| G2 measurable lifecycle (W4, W5) | Stage 0/1 evidence plus accounting fixture coverage; exact Stage 2 code and host authority identified | **NOT MET**: Stage 0/1 spent; "the portable profile currently authorizes Stage 0/1 only: Stage 2 requires an explicit reviewed host/profile decision or the already authorized canonical host lane"; W4 reward-earnings reader status unknown, verify with master | item 330 W4, W5; runbook Stage 2 |
| G3 measurable economics (W6) | A bounded calibration cohort closes through payout and settlement | **NOT MET** (not started) | item 330 W6 |
| G4 decision (W7) | Frozen forward protocol with hurdle H, uncertainty and risk criteria | **NOT MET** (not frozen; H unset) | item 330 W7 |

### 2.3 Runbook prerequisites (all current for the target date and market)

| # | Prerequisite | Status | Recorded in |
| --- | --- | --- | --- |
| 1 | Continuous execution capture running and producing rows (colocated profile validates it; portable does not claim it) | unknown, verify with master (`status.ps1`) | live host |
| 2 | International economics snapshot passes and matches the platform | N/A until session (fresh on the target date) | runbook |
| 3 | `mm_platform_bootstrap_v0.4` passes, ≤ 1 hour old, for the exact token and condition | N/A until session | runbook Stage 0 |
| 4 | Credential references present outside the repository (`wincred://`) | unknown, **owner only**; agents do not check | owner |
| 5 | Pinned `polymarket-client==0.6.0` via the sealed process-local overlay; `/deployed` proof; user-event and position readers verified; heartbeat ack ≤ 7.5 s; book/fee evidence ≤ 10 s | code on master (`mm_live_*`, `mm_user_stream`, `mm_credentials` present on `origin/master`); host validation N/A until session | runbook prereq 5; Git |
| 6 | Dated Stage 0/1 readiness decision (approved 2026-08-23) plus current SoP authority and exact Git proof | **NOT MET** (SoP; gap G-e) | runbook prereq 6 |
| 7 | Simultaneous one-market paper counterfactual (`market_harvest`) with quote permission, writing artifacts | N/A until session; the 24/7 maker shadow is a different process and does not satisfy it | runbook prereq 7 |
| 8 | One immutable execution-host profile; colocated window inside [00:30, 09:00) Toronto with the 20 s cleanup reserve; portable inside one market-local date | portable assignment on master is `ASSIGNED` (`config/international_live_execution_host.json`); which PC holds it, unknown, verify with master | config; portable runbook |
| 9 | Fresh official geoblock `blocked=false` before credential resolution and submit-adjacent, plus the attended literal; **home file-access tunnel DOWN for the whole session** | N/A until session; owner attestation of physical location recorded 2026-09-19 | runbook prereq 9 |

### 2.4 Stage gates

| Stage | Gate | Status |
| --- | --- | --- |
| 0 | No unknown open orders; exact-condition zero starting position; receipt counts `heartbeat=2` / `cancel_all=1`; v0.2 schema with phases | N/A until session |
| 1 | Two distinct probes (cancel-all mode; heartbeat-lapse mode with automatic cancel observed 10-15 s); zero fills; exact balance/allowance hash equality; `mm_stage1_lifecycle_bundle_v0.3` built offline | N/A until session; the 09-06 pass does not count |
| 2 | Current `mm_platform_verification_v0.6`; one central band passing spread, depth, fee, freshness and current-high gates; 1-2 smallest-valid backed post-only orders for one TTL; plus "the ordinary maker-run live-readiness, target-date data-layer, production release, full risk, and v0.6 platform gates" | NOT MET (never run; requires G2) |
| 3 | Evidence and settlement reconciliation (§5) | N/A until fills or a completed payout cycle |
| maker_core | A future `maker_core` runtime must pass the maker trading guard before every order | applies only if a `maker_core` runtime is used; not the Stage 0-2 path |

## 3. Size and loss limits (as the docs state them)

From the runbook's "Immutable pilot envelope" (may be lowered, never raised, without a new dated owner
decision):
- Dedicated isolated wallet funded with no more than **100 pUSD**.
- First Stage 0/1 request exactly **10 pUSD**; any later run budget ≤ its wallet cap and ≤ 100 pUSD.
- Exactly **one weather market per run**.
- Ceilings: **25 pUSD daily loss**, **25 event notional**, **10 band notional**, **120 s quote TTL**.
- Session envelope: colocated 120 s (120 s public paper proof); portable 240 s (600 s public paper proof,
  which is not an order TTL).
- Smallest exchange-valid share size and current tick, read immediately before the order.
- Post-only limit orders only; no marketable retry; no naked sell; no overnight or unattended first session.
- The adapter clamps per-order notional to **10 pUSD**; capability issuance rechecks the 100 pUSD ceiling.
- Rewards are not assumed; an unpaid or sub-threshold estimate is unrealized.

From item 330:
- W6 planning budget: at most **five attended calibration sessions and two completed payout cycles within
  fourteen calendar days after G2**, inside the operator's smaller envelope (a discovery budget, not a
  sample size).
- W7 outer budget: **thirty calendar days of new exposure** after the freeze, then closeout.

Scale check from the runbook: at p = 0.50 the weather fee curve and 25% rebate give about 0.003125 pUSD per
filled maker share, so about 160 pUSD of maker fill notional accrues the 1 pUSD payout minimum. One tiny
session will usually pay nothing.

## 4. Sessions plan (lane A)

Every step is owner-attended and owner-launched. Agents prepare public, offline inputs and review receipts.

| Step | What | Gate to enter | Ends with |
| --- | --- | --- | --- |
| P0 (offline) | Master records G0; resolves gaps G-a..G-i with the owner; names the profile and exact branch; reseals launchers (#229); W3 opportunity table for candidate dates from public reads; W4 reader readiness | none | G0 recorded; G1 table or a bounded infeasibility result |
| S1 | **Stage 0 then Stage 1** (both modes), one market, 10 pUSD request, fresh attempt namespaces | §2.1 all MET; prereqs 1-9 | Plumbing PASS or FAIL. A plumbing pass is evidence, not standing direction. |
| S2 | **Stage 2, one band, one TTL** (1-2 smallest-valid backed post-only orders) | a **new** dated owner authorization after S1; G2 MET (including the Stage 2 host/profile decision) | Orders cancelled at TTL; Stage 3 begins |
| S3 | **Stage 3** reconciliation, including the next completed UTC payout cycle | S2 ran | Reconciled cash identity, or "incomplete" |
| W6 cohort | Up to 5 attended sessions, 2 payout cycles, 14 days. W6 notes the one-TTL gate cannot produce reward exposure; repeated TTLs need "a bounded successor with exact order-count, duration, loss and inventory budgets for review", which does not exist yet | G1, G2, W4, exact authorization for the economic stage | W6 report |
| W7 | Freeze the forward decision protocol (H agreed with the owner before any confirmation outcome is seen); ≤ 30 exposure days | W6 report | G4 verdict: continue, redesign, stop or inconclusive |

Timing: a colocated session must fit inside [00:30, 09:00) Toronto (08:59:40 latest cutoff) with no heavy
job overlapping. A portable session stays inside one market-local execution date, target date that date or
the next. No session runs the night before a host cutover (DL 10-18 ruling on G7).

## 5. Kill switches and stop conditions

From the runbook "Stop conditions" (they may be added to, never weakened). **Cancel all and do not resume**
on:
- book, source, watcher, execution-capture, user-stream or heartbeat stale;
- market fee eligibility, min size, tick, wallet, allowance or platform drift;
- any order accepted as taker or without post-only protection;
- open orders, positions, reserves or local lifecycle disagreeing with exchange truth;
- unknown order, unexpected partial fill, unbacked sell or risk-cap breach;
- cancel-all not followed by zero open orders;
- colocated: leaving the target date or [00:30, 09:00), a protected window, or capture health degrading;
- portable: crossing the market-local execution date, or execution-only status, host binding, clock,
  reboot, capture-host exclusion or exclusive lease failing;
- geoblock unavailable or blocked, physical eligibility unconfirmed, or endpoint and attestation
  disagreeing (and the home tunnel coming up mid-session).

Mechanisms:
- Exchange dead-man: acknowledged 5 s heartbeat cadence; a malformed or > 7.5 s acknowledgment disarms
  placement; venue cancel-on-disconnect observed at 10-15 s (a fail-closed probe, not a venue SLA);
  explicit acknowledged cancel is primary (EF §10i).
- Post-only cross rejection is stop-and-refresh, never a chase.
- One-submit capability, consumed before the SDK call; no retry after an ambiguous response.
- Daily loss ceiling 25 pUSD; band notional 10; event notional 25.
- For a `maker_core` runtime only: the maker trading guard (owner pause file, campaign bleed limit, HALT
  latch that only the owner clears, cancel-all intent).
- The owner may stop at any time; every end path ends with cancel-all and an authenticated zero-open-order
  query.

## 6. Evidence to record

Per accepted order (runbook Stage 3): intent, signed-request hash (never the secret or key), exchange order
ID, stream events, REST reconciliation, fill and trade IDs, transaction hashes when available, balances,
positions, markouts, fees, rebate estimate, paid rebate, redemption and final settlement P&L.

Accounting (runbook Stage 3 and item 330 §3):
- only `CONFIRMED` fills create fill rows; `MATCHED`, `MINED`, `RETRYING` are pending; `FAILED` none;
- zero positions only from the exact-scope `data-api` positions query with its response hash;
- rebates only from the exact `/rebates/current` query on a later UTC date, asset address checked against
  the pUSD proxy, and the wallet balance delta;
- fees derived from the complete confirmed-trade set, bound by sha256, recomputed per taker or flattening
  fill;
- the cash identity closes to 0.00001 pUSD with starting and ending balances, zero ending positions and
  explicit external cash flows; otherwise "incomplete";
- four views: trading only; plus paid rebates; plus both paid incentives; after operating costs; with
  capital-hours, maximum collateral, operator minutes.

Records: an item 67 attempt row in the same change that reports any attempt, pass or fail; every receipt
(geoblock, bootstrap, command, execution, session-run, lifecycle journals, bundle) retained with its sha256;
the economics interpretation under the pilot preregistration's unit (`maker address x condition x UTC
payout day`).

## 7. If the owner means lane B (LFC) instead

Its signed limits replace §3: post-only GTD BUY legs of exactly 40 shares at prices in [0.17, 0.80]; order
cap 31.6 and band cap 39.2 pUSD; ≤ 10 submits and ≤ 4 requotes per session; ≤ 2 open orders, all ours, and
any foreign open order ends the session; ≤ 8 counted sessions of ≤ 360 minutes; campaign worst-case L ≤
100 pUSD, after which the campaign ends permanently; a manual-trading pause from session 1 until the last
lot settles; the §4 panel-exclusion file written before the first post; the §7 dead-man layers (2 s
heartbeat, 20 s main-loop watchdog, venue cancel-on-disconnect, GTD backstop at session end + 60 s).

Before its session 1 (from the prereg and DL): a dated clarification moving the "last session must start
by 2026-10-31" limit if session 1 cannot start by then; t24 and T-40 wallet-reader baselines (owner-run);
the pin `21cf1ed42` recorded for session 1 or a new pin row; 88a scope confirmed for the session date (P5);
the owner's direct (not relayed) confirmation that the campaign resumes.

## 8. Before session 1: who does what

**Owner (only the owner can do these):**
1. Decide the lane (A or B) and confirm the money terms personally (gaps G-c, G-d).
2. Authorize in DECISION_LOG the named stage, date and profile; state what the pilot supersedes in the
   09-25 pause and the 10-23 directive (G-a, G-b).
3. Lane A: fund the dedicated isolated wallet at ≤ 100 pUSD; place the credentials in Credential Manager
   outside the repository. Lane B: the wallet baselines and the manual-trading pause.
4. Name the exact source branch for a portable session, or choose the colocated lane (G-e).
5. Rule on the agent read clearance for the pilot's own orders and fills (G-g) and on panel exclusion
   (G-h).
6. Accept or reject the economics snapshot baseline at the session (a human decision in the runbook).
7. Agree the hurdle H before any W7 confirmation outcome is read.
8. On the day: tunnel down, attended geography literal, launch every stage, attend the whole session.

**Master:**
1. Rewrite STATE_OF_PLAY's Current-authority line once the DL row exists.
2. Record G0 in item 330 and item 67: integrated source, branch dispositions, the four 2026-09-06 control
   relaxations (each needs an owner disposition), host assignment.
3. Prove Git authority fresh at action time; reseal launchers under #229.
4. Produce the W3 exact-condition opportunity table from public reads for the candidate dates, or a bounded
   infeasibility result (G1), and say how the 10 pUSD band cap interacts with reward minimums (G-f).
5. Confirm W4 reader readiness (rebates, reward earnings, positions) and capture health.
6. Clear the workstation of heavy work for the session block (G-i); keep the maker shadow running.
7. Prepare the item 67 attempt-row template and the Stage 3 reconciliation checklist.

**Agents (workstation):** offline preparation from public data only; receipt review after the owner
shares them; no order, cancel, signature, launcher or credential access at any point.
