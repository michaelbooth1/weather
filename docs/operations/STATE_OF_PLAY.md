# State of play

**Last updated: 2026-10-31 America/Toronto (morning: 09-30..10-14 released and row 80 exported; S31 venue prices approved;
everything ruled out archived; research review; night 10-30/31 landed AIFS and the cold-snapshot fix; Rule B-1 bound 10-28, D0 10-29).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** `status.ps1` flags
> it when its date is over 3 days old. Live readings (free space, commit, capture health) come from `status.ps1` and `Get-Volume`.

## Objectives (owner 10-23 hard directive, sharpened by option B 10-25 and 10-30)

Precondition: protect capture and settlement evidence. **The goal is model improvement**: exhaust the model levers and run one
minimal forward edge test (B) against market prices ("We exhaust all options on model improvements", owner 10-25). **A B FAIL ends
this candidate's edge claim, not the project** (owner Q2 10-25, DL); work continues down the [lever inventory](LEVER_INVENTORY_2026-10-26.md).
**Iterate fast** (owner 10-30, nine decisions, DL): kill on history and dev in days, no serial 45-day forward tests; rules in
[MODEL_IMPROVEMENT_METHOD](MODEL_IMPROVEMENT_METHOD.md) §5. 88a, bundle B, plugin core and YouTube stay paused.

## Headline

- **Free public data looks already priced:** every free source scored against the market on dev is null or harmful ([register](EXHAUSTION_REGISTER.md) §6 X44-X82; mostly "KILL at edge size").
- About two thirds of P3d's 07-12 excess (64%) survives re-centring and tempering (EF §10ag derivation); calling it sharpness is an interpretation.
- **Against the market the model adds nothing yet:** walk-forward log-pool weight on MG-1 w ≈ 0.008 (EF §10ad).
- Independent [research review](../research/research-review-2026-10-31/review.md) (10-31, dated): nothing reversed; untried upside = S31 prices, the atlas, T+1.

## Current authority

- **Live maker pilot POSTPONED** (owner 10-30, DL) until a candidate is worth testing; pin, locked worktree and runbook stay as of
  10-28. Owner sessions only; no agent places, cancels or signs orders. Other live trading paused (owner 09-25).
- Capture host: heavy work 00:30-09:00 under the lease ([host load policy](HOST_LOAD_POLICY.md); a one-off wrapper refuses a `$null`
  lease); roll-sensitive merges 01:00-04:00; roll-free 00:30-09:00; docs-only by the light path before 12:00; never 12:00-00:30.
- Owner decisions are rows in [DECISION_LOG](DECISION_LOG.md); master's rulings are labelled as master's, never as the owner's.
- **Weather data:** paid only per DECISION_LOG-approved source (10-23); free official data needs no ask; ask for packages, logins, payment (10-24).
- **Other venues' public prices** (S31, owner 10-30, DL): read-only research input; metadata endpoints only, no account, key or
  trading; their prices follow the same embargo. International Polymarket stays the only trading venue.
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md)); parallel
  lanes, one branch each; heavy work via `workstation_heavy.ps1`; every WS scheduled task needs the owner's yes there.
- **Record and keep every rule-out** (owner 10-25, 10-30): register §6 row plus the never-cleaned WS archive `C:\archive\ruled-out`
  (method §5 rule 13); the WS records its own pre-registered kills (10-30); master audits.
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** read `origin/master` with git (`5f4d87818` before this batch). Night 10-30/31 landed the AIFS capture-only
  fix and the cold-snapshot resolver (the 10-30 refusal is RESOLVED); its combo failed repo-wide audits and is rebuilt for 10-31/11-01.
- **Outcome embargo:** no outcome, price or label read after 09-29 except under a named, owner-opened test. Dates <= 09-29 are dev.
  **09-30..10-14 released once for kill-only/atlas reads** (owner 10-30, DL): row 80's look first; boundary = local target date;
  Austin 10-03 out; MG-2/B outputs out; maker economics stay closed (embargo code unedited). 10-16..11-13 descriptive reads refused (10-17).
- **Row 80 export done 10-31** under the lease (`C:\xfer\released-0930-1014-20261031\row80`, receipt `6c0f4a1d…`); C1-C3 export follows its receipt.
- **MG-1** bound, forward shadow; single look after 11-28 ([reserved window](reserved-confirmation-window.md)); outputs never read before it.
- **MG-2 / Rule B-1 BOUND 10-28** ([design](B_FORWARD_TEST_DESIGN.md); DL 10-28): D0 10-29, N = 45 countable dates, 45th date 12-12,
  NI margin +0.0027; single look 12-13 after MG-1's. Daily WS pull/receive runs (10-30 verified 10-31 06:30).
- **B's serial correlation** (dev ρ about 0.22): B's verdict stands as bound; a frozen post-look module may only label a PASS
  "fragile" (master ruling (b), `b_post_look_serial` frozen `fa380db09`). B's floor counts SPECI from 10-23; its Brier carries that cost.
- **Kill scopes (master):** R-I fitted temperature/scale maps only; R-G/R-J Aug-Sep only; kill-only dev/history reads need power >= 0.5 at edge size.
- **Labels (master 10-25):** WU before 10-23, venue rule (routine METAR, WU fallback) from it. **Denver >= 10-23: KDEN, out of MG-2 and B.**
- **Evening-fix scoring read postponed** (scorer never landed; prereg §5): lands night 10-31/11-01, host replay after; targets
  10-16..10-27 (+10-28 extension only); two stages, condition 3 after MG-1's look ([Clarification 1](DECISION_LOG.md), master).
- **Defect lane:** fix 10 (high_so_far train/serve parity, row 33 −0.0088) and fix 11 (no SPECI in the floor from 10-23) are built on
  `-after-b` branches; they land only after 12-13 and a byte-identity check of the MG-2 export (master).
- **WS forward recorders** (receipt-dated, owner yes each): ENS and GEM complete from 10-31 00Z; ENS, GEM and IEM MOS run unregistered.
- **No forecast_history / open_meteo_archives / reanalysis cache rebuild until `a399941e` lands (after 12-21)** (master).
- **L6_G forward screen** (owner ok, DL 10-28): outcome-blind, N = 45, one look after B; D0 10-31, WS task from 11-01.
- **More markets** (owner 10-23, DL): R1 pilot cities recorder-only, R2 from 11-01; the R1+R2 config branch lands night 10-31/11-01.
- **91a nightly** policy `eca4064a…` (expires 11-27). **Maker shadow ACTIVE** (paper; `data\maker_shadow\STOP`). **88a hold:** UTC 09-27..10-30. **DST ends 11-01.**

## Ordered critical path

1. **Rule B-1 bound 10-28**; MG-2 accrues from D0 10-29, inputs received daily; no look before 12-13.
2. **Released window:** row 80 look, then the atlas (served-vs-market re-base), C1-C3 kill-only screens; S31 cross-venue P0 (row 99).
3. **T+1 forward prereg:** the C3 88a kill-tier read first; freeze after it or on schedule (WS decides by 11-02). R-ODC P1 (row 72) runs.
4. **MG-1 look after 11-28**, then B 12-13; **PT-1** ([draft](COOL_SEASON_PAPER_TEST_PREREG.md); dates 12-12..01-25) bound before its D0.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| PT-1 bound: PT_D0, G = 15 s, rule sha; decide fixes 10/11 candidate-side; Miami floor | master | before PT_D0 | binding commit; DL row |
| MG-1 look: rulings A1-A14 and b_transfer T1-T5; scorer review; b_transfer/1 writer review | master | 11-03; 11-20; 12-01 | notes |
| Look-chain clarification (closed list: MG-2 score, B look, per-date extraction) | master | before 11-29 | docs landing |
| Evening-fix Stage 1 read after the scorer lands | master + WS | 11-01 | scorer receipt |
| Delete the row 80 staging copy after the WS verifies it | production | after WS check | staging gone |
| WU-vs-venue measurement 08-11..09-29 on the host (owner 10-23) | production | open | research doc; DL row |
| L6_G first daily emission | workstation L2 | 11-01 | first receipt |
| R1+R2 on; 24 h S2+S9 receipts (88a RSS, REST rate, partitions sealed, built-ins unchanged) | master | 11-02 | receipt doc |

## Standing decisions

- International Polymarket only; paid weather sources only per owner-approved source; backups deprioritized; streak contiguity is
  a diagnostic. Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
