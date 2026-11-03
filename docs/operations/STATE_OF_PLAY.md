# State of play

**Last updated: 2026-11-03 America/Toronto (evening-fix Stage 1 accepted, R24 first host label run, Denver 107-miss open, rows 106/107/109/113 closed, R-CS/R-P2/K112 PARKED; night 11-02/03 combo landed).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended; at most 95 lines; detail in the linked owner.** Live readings: `status.ps1` (flags age > 3 days), `Get-Volume`.

## Objectives (owner 10-23 hard directive, sharpened by option B 10-25 and 10-30)

Precondition: protect capture and settlement evidence. **The goal is model improvement**: exhaust the model levers and run one
minimal forward edge test (B) against market prices (owner 10-25). **B's single look on 12-13 stays the edge test; a B FAIL ends
this candidate's edge claim, not the project** (owner Q2 10-25, DL); work continues down the [lever inventory](LEVER_INVENTORY_2026-10-26.md).
**CONTINUE/STOP after B** (owner deferred 11-01; master ruling, DL): a successor needs all six criteria; checkpoint, not a kill: no candidate meeting 1-2 by 2027-01-31 → research pauses for an owner reset review; ABORTED → no auto-retry.
Owner, 11-01 (relayed): "maybe we never find any edge, but this is serving as my real first long term project... I want to keep
trying. I want to keep trying smartly." **Iterate fast** (owner 10-30, DL): kill on history and dev in days; rules in
[MODEL_IMPROVEMENT_METHOD](MODEL_IMPROVEMENT_METHOD.md) §5 (rule 17 added 11-02). 88a, bundle B, plugin core and YouTube stay paused.

## Headline

- **Free public data looks already priced:** every free source scored on dev is null or harmful ([register](EXHAUSTION_REGISTER.md) §6 X44-X103).
- **The model adds nothing against the market yet:** MG-1 w ≈ 0.008 (EF §10ad); gap about 1.5 out of sample (EF §10ao); no strong lever left.

## Current authority

- **Live maker pilot POSTPONED** (owner 10-30, DL); no agent places, cancels or signs orders; other live trading paused (owner 09-25).
- Capture host: suites and other heavy work 00:30-09:00 under the lease ([host load policy](HOST_LOAD_POLICY.md)); roll-sensitive merges 01:00-04:00; roll-free merges 00:30-12:00 (QWM); docs-only before 12:00; never 12:00-00:30.
- **Weather data:** paid only per DECISION_LOG-approved source (10-23); free official data needs no ask; ask for packages, logins, payment (10-24).
- **Other venues' public prices** (S31, owner 10-30, DL): read-only structured API endpoints with field allowlists; no account, key or trading; same embargo. International Polymarket stays the only trading venue.
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md)); heavy work via `workstation_heavy.ps1` ([development](../development.md)); every WS task needs the owner's yes there.
- **Owner yeses 11-02 (DL):** a standing yes for host watchdog redeploys with reviewed pins; keep Wi-Fi connected when Ethernet is plugged in;
  torn-journal auto-recovery Stage 2 (startup host task, 15-min poll, core root only), registered by master after Stage 1 lands RF on a CLEAN review.
- **Record and keep every rule-out** (owner 10-25, 10-30): register §6 row plus the never-cleaned archive `C:\archive\ruled-out` (method rule 13); the WS records its own pre-registered kills; master audits.
- **Landed is not running** until its verify has run. Owner decisions are [DECISION_LOG](DECISION_LOG.md) rows; master's rulings are labelled master's.
- **Standing:** International Polymarket only; backups deprioritized; streak contiguity is a diagnostic; pushing never rolls capture; native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Current truth

- **Production source:** read `origin/master` with git.
  **Night 11-02/03 combo `claude/night-combo-20261102` @ `8d10666ed` LANDED 11-03 (merge `cb890e6b3`, quiet-window merge; master):** blook-r3, B-look S0/S1 `d5a254b6c`, #5, items 23/33, CI shard, tests-only fix (DL). First new training_window.ps1 run 04:15, rc checked by master.
- **Outcome embargo:** no outcome, price or label read after 09-29 except under a named, owner-opened test. Dates <= 09-29 are dev.
  **09-30..10-14 released once for weather kill-only/atlas reads** (owner 10-30, DL): local target date; Austin 10-03 out; MG-2/B
  outputs out; **C1/C2 maker-economics reads stay closed**. 10-16..11-13 descriptive reads refused (10-17).
- **WS `data\` is a paused mirror** (master 11-02): mirror paused 2026-08-12; last complete WU day in it = 2026-08-10 (manifest `last_date`, all 12 markets); a WS lane needing Aug+ WU uses labels or a host bounded extract and checks store coverage (max date >= need) before use.
- **Market price reliability by bin CLOSED (row 106, X92, EF §10aq):** KILL at edge size on US11 dev (08-01..09-29; ECE 0.0067,
  slope 1.030 [1.014, 1.045]; all three arms below 0.2236). It is not an exploitable lever, and it is silent on the overround.
- **R28a NWS P0 (row 107, X96-X101, EF §10as):** FADE and GAP KILL at edge, W1-0712 UNTESTABLE at edge; NWS adds a little, not a tradable amount. **R28b:** C3 closed untestable (R28b census 0/0/0; design gap, not a kill; A1 unchanged). X86, EF §10at.
- **R-CS coastal specialist PARKED** (master 11-01; no ledger row; register note, two reopen conditions). **L47 2a and lever 2 PARKED** (X102, X103). 11-01 closures (master): #21 GEFS true mean (X91); direction A (register §0.2, EF §1k); B PARKED; B2 UNTESTABLE (row 105, X90). **X36-v5 (row 111 C, EF §10au):** 2026 raw NBM warm +0.74°F equally under v4.3 and v5.0; not a v5.0 artefact; X36 reopen not met.
- **Evening-fix Stage 1 ACCEPTED (master 11-03): CONDITIONS 1-2 MET, condition 3 pending.** Primary -0.04854 [-0.05532, -0.04211], 11/11 markets, 128 market-days; both sensitivities share sign; SAFETY 0 and 0; "Stage 2 after MG-1 look receipt (after 11-28)"; H2 NOT TESTED; 10-28 outside frozen window, extension not triggered; shas and the one-off direct-run disclosure in [item 337](../roadmap/items/item-337-no-metar-observed-floor-gap.md).
- **Row 113** (L52, 3a history-tier market reliability, B12 2025-12..2026-05): UNTESTABLE at the step 2 label-integrity cap (2.82% > 2%), accepted as frozen 11-02; no successor; the lever is covered by row 106's KILL (X93).
- **L52 price history** (owner GO 11-01, DL): International PM public closed-event `/prices-history` at fidelity 1, sealed 11-02 (22 markets, events 2025-01-22..2026-09-29, no guarded dates); the series is the book mid, not last trade. HISTORY-TIER selection evidence only, never an edge claim.
- **R-P (L48 station-pooled corpus) KILLED** at LOYO gate 1 (row 109, X94; Los Angeles CI-worse). **R-P2** (class-matched pooling): screen PASS, confirmation infeasible at size (3-5 seasons); **PARKED** as the default corpus-expansion ingredient (X95, three reopen triggers). L48 GO N=300 (rule 33d5c67a…, rows 108 C / 109 K); R-I scope ruled not covering a rows-only retrain.
- **K112:** dev CONSISTENT (C1.6). History-tier test NOT RUN: Dec-May NBM 07Z and P3d_N_fix inputs absent on WS; power ~0.14 at dev point (MDE80 ~0.009 vs -0.0027); seasonal transfer of b_train unresolved. PARKED, not killed.
- **L47 step 0:** the 07-12 market gap is mostly centre (P3d +0.0049..+0.0077 of +0.0101); width ≤ +0.0038, day-specific scale ≤ +0.0007, skew ~0; 2a and lever 2 PARKED (EF §10ag correction, X27).
- **L50:** captured NBM v2 exists only from target 06-24 (US only), so NBM-dependent arms get at most 06-24..07-30 of the sealed panel (WS bytes 07-14..07-30); power is too low for parity-sized 07-12 steps (L50, `5a805dda7`).
- **Maker-evidence capture gap 11-02 03:36-09:38 EST** (~6 h, host power loss, Kernel-Power 41, no UPS): 5 torn reward journals in segment 2026-11-02/08-b7021b84b0cf quarantined byte-exact (`QUARANTINE_RECEIPT.json`); remaining journals sealed by the store; no data rewritten; capture 10/10 since 09:39 ([runbook](passive-maker-evidence-capture.md) "Torn journal after power loss").
- **F8-MH forward screen FROZEN** (row 104; Clarification 1 `d138f1d92`): D0 11-02, blind, one look 01-26 after PT-1's. MOSMIX-8 HOLD. **Row 72 R-ODC P1** from D0 10-31; Clarification 1 `9f112f3fa` fixes the rounding refusal pre-look; the < 30°F filter is in the candidate.
- **MG-1** forward shadow, single look after 11-28 ([reserved window](reserved-confirmation-window.md)). **MG-2 / Rule B-1 BOUND 10-28**
  ([design](B_FORWARD_TEST_DESIGN.md)): D0 10-29, N = 45, 45th date 12-12, NI margin +0.0027, look 12-13; daily WS pull runs.
- **B's serial correlation** (dev ρ about 0.22): B's verdict stands; a frozen post-look module may only label a PASS "fragile" (master).
- **Kill scopes (master):** R-I maps only; R-G/R-J Aug-Sep only; kill-only reads need power >= 0.5 at edge size on the wider of date-clustered and block-3 bounds, projected on the full population rule (method rule 16).
- **Labels (master 10-25):** WU before 10-23, venue rule (routine METAR, WU fallback) from it. **Denver >= 10-23: KDEN, out of MG-2 and B.** **R24 first host run 11-03 (master; DL):** venue-rule labels are built for 10-23..11-02 on all 12; under the R24 ruling's paragraphs (3) and (5), a look reads only its look-morning frozen copy, through `read_venue_labels` inside its registered entry point, and Stage A stays `wu` (runbook step 4 waits until after B). Fetch 13/13, build 12/12, 0 skipped; shas in the [runbook](venue-rule-labels.md) receipt; no label value read.
- **Denver 107-miss (B2 finding): OPEN INVESTIGATION, cause unexplained** (contiguous hour runs 10-22/25/27/28). Comparer v5 `scratch-transport/denver_miss_names_v5.py` sha256 `8067c8d995fd311cd485e82500d4b6a538d2f730a5914122ae0df64ab9366c6d` @ `ce7abacb55e8d1952e38c25cbac60007633a3672` (transport branch), armed for the host 11-04 about 04:30, `--features-only`; it copies only features.jsonl and replay_inputs.jsonl.
- **After-B list** (after 12-13 and an MG-2 export byte-identity check): fix 10 (high_so_far parity; defect measured, 53.8% of dev 00-12), fix 11 (no SPECI in the floor from 10-23), `claude/ops-freshness-utc-mg2-after-b` @ `3957b9728`.
- **Windows Update (owner 11-01, DL):** host pause to 12-02T12:00Z stays, no patch night; master brings a notify-only / no-auto-restart option before 12-02 if it cannot be extended. **WS pause EXPIRED 10-30T13:58:48Z** (not covering 12-13); owner decides in the WS chat.
- **WS forward recorders:** ENS, GEM and IEM MOS logon tasks plus the 15-min keepalive (owner yes 10-30). All 10 died at once 11-01 22:06-22:08Z under one dead parent (cause unverified, EF §10av); L34 [live-parent design](../research/recorder-live-parent-design-2026-11-01/design.md).
- **Exchange economics refresh:** failed daily since at least 10-08; rc 0 11-01 06:50, accepted snapshot and barrier unverified; fix before any maker work ([runbook](EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md)).
- **No forecast_history / open_meteo_archives / reanalysis cache rebuild until `a399941e` lands (after 12-21)** (master).
- **More markets** (owner 10-23; R1+R2, master D1-7, DL 11-01; receipts 11-03): roll-free config revert if capture < 10/10, RAM < 3.5 GB 3 ticks, commit >= 70%, rising 88a 429s/errors or abnormal partitions.
  **91a nightly** policy `eca4064a…` (expires 11-27). **Maker shadow ACTIVE** (paper; `data\maker_shadow\STOP`). **88a hold:** UTC 09-27..10-30.

## Ordered critical path

1. **Rule B-1 bound 10-28**; MG-2 accrues from D0 10-29, inputs received daily; no look before 12-13.
2. **T+1:** owner-approved WS daily task 'L3 T+1 forward daily emit' (reg. 11-01, `C:\t\t1_emit\forward`, emitter `5d348b75…` @ `6d96d9dab`); prereg freeze awaits P1-P3 receipts. Row 72 and F8-MH accrue blind; L6_G emitting (first emission vectors d1e09134, runs.jsonl 6842d139).
3. **MG-1 look after 11-28**, then B 12-13; **PT-1** ([draft](COOL_SEASON_PAPER_TEST_PREREG.md); 12-12..01-25) bound before D0; F8-MH 01-26.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| PT-1 bound: PT_D0, G = 15 s, rule sha; fixes 10/11 candidate-side; Miami floor | master | before PT_D0 | binding commit; DL row |
| MG-1/B rulings DONE 11-03 (MG-1 Cl. 2, B-1 Cl. 5); owner A1/A5/A12 open; mg1_look scoring head; b_transfer T1/T3/T4 + B label loader; scorer and writer reviews | master (owner A1/A5/A12); WS heads | owner answers before the look; head 11-12/13; 11-20; 12-01 | DL 11-03 row; head tips |
| Look-chain clarification (MG-2 score, B look, per-date extraction) | master | before 11-29 | docs landing |
| Evening-fix Stage 2: gap read after the MG-1 look receipt (Clarification 1 s5); H2 then needs a market-arm replay (owner question) | master + WS | after 11-28 | MG-1 look receipt; Stage 2 receipt |
| F8-MH: forward layout with venue-rule labels; `f8_mh` allowlist admission | WS L16 | before 01-26 | run-branch receipt |
| Economics refresh and rc 2 barrier fixed | production | before maker work | accepted snapshot |
| Host hardening: Ethernet (host on Wi-Fi; owner 11-02 "Ethernet cord is coming"); Wi-Fi stays connected with it (DL 11-02) | owner | OPEN until the cable is in | Get-NetAdapter Up |
| Torn-journal Stage 1 lands RF on a CLEAN review; then master registers Stage 2 on the host | master | open | registration receipt |
| Venue-rule labels for forward looks (R24): host refresh + counts-only audit Mondays; freeze each look morning | master (host); WS module | first run DONE 11-03 (rc 0, runbook receipt); Mondays; module on master by 11-20 | loop-plan manifest shas; look-log freeze shas |
| R1+R2 24 h S2+S9 receipts (88a RSS, REST rate, partitions, built-ins unchanged) | master | 11-03 | receipt doc |

## Update this file when

Rewrite (never append) after an owner decision, a source adoption, a measured storage or settlement outcome, an economic-feasibility
result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
