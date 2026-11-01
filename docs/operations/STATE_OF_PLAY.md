# State of play

**Last updated: 2026-11-01 America/Toronto (A closed, B parked, B2 UNTESTABLE, market reliability barred; F8-MH frozen; six code heads to night 11-01/02).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended; at most 95 lines; detail in the linked owner.** Live readings: `status.ps1` (flags age > 3 days), `Get-Volume`.

## Objectives (owner 10-23 hard directive, sharpened by option B 10-25 and 10-30)

Precondition: protect capture and settlement evidence. **The goal is model improvement**: exhaust the model levers and run one
minimal forward edge test (B) against market prices (owner 10-25). **B's single look on 12-13 stays the edge test; a B FAIL ends
this candidate's edge claim, not the project** (owner Q2 10-25, DL); work continues down the [lever inventory](LEVER_INVENTORY_2026-10-26.md).
Owner, 11-01 (relayed): "maybe we never find any edge, but this is serving as my real first long term project... I want to keep
trying. I want to keep trying smartly." **Iterate fast** (owner 10-30, DL): kill on history and dev in days; rules in
[MODEL_IMPROVEMENT_METHOD](MODEL_IMPROVEMENT_METHOD.md) §5 (rule 16 added 11-01). 88a, bundle B, plugin core and YouTube stay paused.

## Headline

- **Free public data looks already priced:** every free source scored on dev is null or harmful ([register](EXHAUSTION_REGISTER.md) §6 X44-X91).
- **The model adds nothing against the market yet:** MG-1 w ≈ 0.008 (EF §10ad); gap about 1.5 out of sample (EF §10ao); no strong lever left.

## Current authority

- **Live maker pilot POSTPONED** (owner 10-30, DL); no agent places, cancels or signs orders; other live trading paused (owner 09-25).
- Capture host: heavy work 00:30-09:00 under the lease ([host load policy](HOST_LOAD_POLICY.md)); roll-sensitive merges 01:00-04:00;
  roll-free 00:30-09:00; docs-only by the light path before 12:00; never 12:00-00:30.
- Owner decisions are rows in [DECISION_LOG](DECISION_LOG.md); master's rulings are labelled as master's, never as the owner's.
- **Weather data:** paid only per DECISION_LOG-approved source (10-23); free official data needs no ask; ask for packages, logins, payment (10-24).
- **Other venues' public prices** (S31, owner 10-30, DL): read-only structured API endpoints with field allowlists; no account, key
  or trading; same embargo. International Polymarket stays the only trading venue.
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md)); heavy work via
  `workstation_heavy.ps1` ([development](../development.md)); every WS task needs the owner's yes there.
- **Record and keep every rule-out** (owner 10-25, 10-30): register §6 row plus the never-cleaned archive `C:\archive\ruled-out`
  (method rule 13); the WS records its own pre-registered kills; master audits.
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.
- **Standing:** International Polymarket only; backups deprioritized; streak contiguity is a diagnostic; pushing never rolls capture;
  native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Current truth

- **Production source:** read `origin/master` with git (`4e0939833` before this batch). **No integration ran on DST night 10-31/11-01**;
  all six code heads plus the UTC ops fix (`claude/ops-freshness-utc-20261101` @ `28d149fe`, ROLL-FREE) land night 11-01/02.
- **Outcome embargo:** no outcome, price or label read after 09-29 except under a named, owner-opened test. Dates <= 09-29 are dev.
  **09-30..10-14 released once for weather kill-only/atlas reads** (owner 10-30, DL): local target date; Austin 10-03 out; MG-2/B
  outputs out; **C1/C2 maker-economics reads stay closed**. 10-16..11-13 descriptive reads refused (10-17).
- **Released reads 10-31:** row 80 NOT REPLICATED, KILL at edge size; atlas P1 descriptive (row 101); C3 BLOCKED (row 100);
  R-ODC-lin KILL at edge, X13 UNTESTABLE (row 103). Export 2 stays staged on the host until its weather reads finish.
- **S31 Kalshi twin:** v1 UNTESTABLE (row 99); v2 KILL at edge size, mean and width (row 102, X83). P5 screens: rows 93-95.
- **11-01 closures (master):** #21 GEFS true mean CLOSED-BY-RULE by X57 (X91); direction A (high_so_far repair cost) closed, cost
  bounded by X14 / row 33 and covered by fix 10 (register §0.2, EF §1k addendum); B (thin markets) PARKED; B2 UNTESTABLE (row 105, X90).
- **Market price reliability by bin on our 12:** never measured; BARRED by the 10-23 model-only scope; **owner question pending**.
- **F8-MH forward screen FROZEN** (row 104; Clarification 1 `d138f1d92`): D0 11-02, blind, one look 01-26 after PT-1's. MOSMIX-8 HOLD.
- **Row 72 R-ODC P1** runs from D0 10-31; Clarification 1 (`9f112f3fa`, pinned 10-31 before the P1 window closed) corrects the
  rounding refusal pre-look; the < 30°F filter is part of the candidate (ledger row 72 notes).
- **MG-1** forward shadow, single look after 11-28 ([reserved window](reserved-confirmation-window.md)). **MG-2 / Rule B-1 BOUND 10-28**
  ([design](B_FORWARD_TEST_DESIGN.md)): D0 10-29, N = 45, 45th date 12-12, NI margin +0.0027, look 12-13; daily WS pull runs.
- **B's serial correlation** (dev ρ about 0.22): B's verdict stands; a frozen post-look module may only label a PASS "fragile" (master).
- **Kill scopes (master):** R-I maps only; R-G/R-J Aug-Sep only; kill-only reads need power >= 0.5 at edge size on the wider of
  date-clustered and block-3 bounds, projected on the full population rule (method rule 16).
- **Labels (master 10-25):** WU before 10-23, venue rule (routine METAR, WU fallback) from it. **Denver >= 10-23: KDEN, out of MG-2 and B.**
- **Evening-fix scoring read** (prereg §5): scorer lands night 11-01/02, Stage 1 read after; targets 10-16..10-27 (+10-28 only).
- **After-B list** (after 12-13 and an MG-2 export byte-identity check): fix 10 (high_so_far parity; defect measured, 53.8% of dev
  00-12), fix 11 (no SPECI in the floor from 10-23), `claude/ops-freshness-utc-mg2-after-b` @ `3957b9728`.
- **WS forward recorders:** ENS, GEM and IEM MOS: registered logon tasks plus the 15-min keepalive (owner yes 10-30), verified 11-01 04:00Z.
- **Exchange economics refresh failing:** last accepted snapshot 09-26; rc 2 promotion-lane barrier since about 10-20; fix before
  any maker work ([runbook](EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md)).
- **No forecast_history / open_meteo_archives / reanalysis cache rebuild until `a399941e` lands (after 12-21)** (master).
- **More markets** (owner 10-23): R1+R2 recorder-only, config lands night 11-01/02. **91a nightly** policy `eca4064a…` (expires 11-27).
  **Maker shadow ACTIVE** (paper; `data\maker_shadow\STOP`). **88a hold:** UTC 09-27..10-30.

## Ordered critical path

1. **Rule B-1 bound 10-28**; MG-2 accrues from D0 10-29, inputs received daily; no look before 12-13.
2. **Night 11-01/02 integration** (six code heads plus the UTC fix), then the evening-fix Stage 1 read; R1/R2 receipts 11-03.
3. **T+1 forward prereg** (WS decides by 11-02); forward arms accrue blind (row 72; F8-MH; L6_G, DL 10-28, N = 45, look after B).
4. **MG-1 look after 11-28**, then B 12-13; **PT-1** ([draft](COOL_SEASON_PAPER_TEST_PREREG.md); 12-12..01-25) bound before D0; F8-MH 01-26.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| PT-1 bound: PT_D0, G = 15 s, rule sha; fixes 10/11 candidate-side; Miami floor | master | before PT_D0 | binding commit; DL row |
| MG-1 look rulings A1-A14, b_transfer T1-T5; scorer and writer reviews | master | 11-03; 11-20; 12-01 | notes |
| Look-chain clarification (MG-2 score, B look, per-date extraction) | master | before 11-29 | docs landing |
| Evening-fix Stage 1 read after the scorer lands | master + WS | 11-02 | scorer receipt |
| Market reliability by bin: scope ruling | owner | open | DL row |
| F8-MH: forward layout with venue-rule labels; `f8_mh` allowlist admission | WS L16 | before 01-26 | run-branch receipt |
| Economics refresh and rc 2 barrier fixed | production | before maker work | accepted snapshot |
| WU-vs-venue measurement 08-11..09-29 on the host (owner 10-23) | production | open | research doc; DL row |
| R1+R2 24 h S2+S9 receipts (88a RSS, REST rate, partitions, built-ins unchanged) | master | 11-03 | receipt doc |

## Update this file when

Rewrite (never append) after an owner decision, a source adoption, a measured storage or settlement outcome, an economic-feasibility
result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
