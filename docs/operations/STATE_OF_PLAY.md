# State of play

**Last updated: 2026-10-30 America/Toronto (evening: live pilot postponed; 31 market-gate screens, 0 survivors; MG-2 input gap
closed; R1 slip found. Rule B-1 bound 10-28, D0 10-29; owner option B 10-25).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** `status.ps1` flags
> it when its date is over 3 days old. Live readings (free space, commit, capture health) come from `status.ps1` and `Get-Volume`.

## Objectives (owner 10-23 hard directive, sharpened by option B 10-25 and 10-30)

Precondition: protect capture and settlement evidence. **The goal is model improvement**: exhaust the model levers and run one
minimal forward edge test (B) against market prices ("We exhaust all options on model improvements", owner 10-25). **A B FAIL ends
this candidate's edge claim, not the project** (owner Q2 10-25, DL); work continues down the [lever inventory](LEVER_INVENTORY_2026-10-26.md).
**Iterate fast** (owner 10-30): kill on history and dev in days, no serial 45-day forward tests; the [iterate-faster
plan](../research/iterate-faster-2026-10-30/plan.md) is a proposal until adopted. 88a, bundle B, plugin core and YouTube stay paused.

## Headline

- **Two thirds of the 07-12 excess loss is sharpness, not centre** (EF §10ag); NBM-published spread closed, GEFS member spread killed as a scale modulator at 07-16 (R-Q A; its 00-06 variant B blocked on parity); 07-12 centre corrections exhausted (L5 KILL).
- **Against the market the model adds nothing yet:** walk-forward log-pool weight on MG-1 w ≈ 0.008 (EF §10ad).
- **Market gate 10-30: 31 screens, 0 survivors** ([register](EXHAUSTION_REGISTER.md) X44-X70; ledger rows 74-81): HRRR died at the w
  gate, the sweep and Toronto NBM at market-residual P0; forecast tracking was a near miss (replication frozen, row 80). Price audit clean.

## Current authority

- **Live maker pilot POSTPONED** (owner 10-30, DL) until a candidate is worth testing; pin, locked worktree and runbook stay as of
  10-28. Owner sessions only; no agent places, cancels or signs orders. Other live trading paused (owner 09-25).
- Capture host: heavy work 00:30-09:00 under the lease ([host load policy](HOST_LOAD_POLICY.md)); roll-sensitive merges
  01:00-04:00; roll-free 00:30-09:00; docs-only by the light path before 12:00; never 12:00-00:30.
- Owner decisions are rows in [DECISION_LOG](DECISION_LOG.md); master's rulings are labelled as master's, never as the owner's.
- **Weather data:** paid only per DECISION_LOG-approved source (10-23); free official data needs no ask; ask for packages, logins, payment (10-24).
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md)); parallel
  lanes, one branch each (owner 10-23); heavy work via `workstation_heavy.ps1`; every WS scheduled task needs the owner's yes there.
- **Record every rule-out** (owner 10-25) in the [exhaustion register](EXHAUSTION_REGISTER.md) §6 with numbers and a "Reopen if" line.
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** read `origin/master` with git (`1a78e1ba0` when written). Night 10-30/31 queues the AIFS capture-only
  fix (roll-sensitive), the cold-snapshot resolver fix and a roll-free combo (WS ping watchdog, MOSMIX recorder, control-char ratchet).
- **Outcome embargo unchanged:** no outcome, price or label read after 09-29 except under a named, owner-opened test. Dates
  <= 09-29 are development only; descriptive reads of 10-16..11-13 stay refused (owner 10-17).
- **MG-1** bound, forward shadow; single look after 11-28 ([reserved window](reserved-confirmation-window.md)); outputs never read before it.
- **MG-2 / Rule B-1 BOUND 10-28** ([design](B_FORWARD_TEST_DESIGN.md); DL 10-28; C7/C8 line, scorer `f941628a…`): D0 = 10-29, N = 45
  countable dates, 45th date 12-12, NI margin +0.0027 (owner Q3/Q4); single look 12-13 after MG-1's; option 2 exempts MG-2 only
  from the reservation, one look, and (Q1) B's capture-time market read travels at that look; share_many = option (i) (master).
- **MG-2 forward inputs:** the WS pull/receive (binding plan §9.7) was never scheduled; found 10-30, 10-29 verified by hand before
  its 23:59 D+1 deadline, daily WS task registered (owner yes). Build, emit and check wait for master to name the inputs (§11).
- **Kill scopes (master R9/R10, 10-25):** R-I closes fitted temperature/scale maps only (spread information: own rule, full ladder,
  no global sharpening, floor never weakened). R-G/R-J cover Aug-Sep only; Oct-Dec rungs need a fresh rule, LOYO Oct-Dec 2021-25.
- **Labels (master ruling 10-25, reading B):** WU before 10-23, venue rule (WU fallback) from it; paid band = WU 626/626, so no
  past evaluation changes (EF §10ai; cutover `28e96a3e7`). **Denver >= 10-23: KDEN, unscored, out of MG-2 and B** (master).
- **Dead-bucket NO buying is closed** (EF §10ad, §10ah). Production does not capture Toronto NBM (forward NBP CYYZ approved, master 10-26).
- **Workstation forward recorders** (receipt-dated; owner yes each): ECMWF ENS, ECCC GEM, NBM text, MOSMIX, IEM MOS, GEFS x4,
  HRRR, T+1/T+2 prices, Open-Meteo Previous Runs. Day-ahead tests are forward-only: no receipt-dated history exists.
- **Open-Meteo retired its AIFS and GraphCast ids** (all-null columns); `ecmwf_aifs025_single` is captured, not served, from night
  10-30/31. **No forecast_history / open_meteo_archives / reanalysis cache rebuild until `a399941e` lands (after 12-21)** (master).
- **L6_G forward screen** (owner ok, DL 10-28): outcome-blind, N = 45, one look after B, never alters B; D0 10-31, WS task from 11-01.
- **91a nightly** re-registered 10-30 on policy `eca4064a…` (expires 11-27); a tool fix landing night 10-30/31 clears the old policy's childless 10-30 refusal.
- **Forward maker shadow ACTIVE** (paper only); stop only with `data\maker_shadow\STOP`; scoring refuses UTC 09-30..11-13 (DL 10-14).
- **More markets** (owner 10-23, DL): R1 pilot cities recorder-only, R2 from 11-01; new cities label from IEM METAR. **R1 slipped:**
  the S2+S9 `pilot` switch was never turned on; the R1+R2 config branch lands night 10-31/11-01 (master).
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok. **DST:** OD30 holds 11-01.

## Ordered critical path

1. **Rule B-1 bound 10-28**; MG-2 accrues from D0 10-29, inputs received daily; no look before 12-13.
2. **MG-3 PAUSED pending the owner** (master recommends dropping it after X44/X45); the HRRR forward recorder keeps running.
3. **Running:** R-O, NBS-TXN diagnostic; **R-ODC P1** frozen, D0 10-31 (row 72); **RISE-T3R3 replication** (row 80) reads
   10-01..10-14 if the owner opens them, else 45 forward dates; a T+1 forward prereg is drafted, frozen only on owner answers.
4. **Cool-season paper test PT-1** ([draft](COOL_SEASON_PAPER_TEST_PREREG.md); owner Q6-Q9 answered 10-25, dates 12-12..01-25) bound before its D0.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| PT-1 bound: PT_D0 set, G = 15 s fixed by the outcome-blind dev check, rule sha pinned | master | before PT_D0 | binding commit; DL row |
| Seven iterate-faster decisions (pipeline, accrual, 09-30..10-14 read, dates to dev, WS kills, keepalive, MG-3) | owner | open | DL rows |
| WU-vs-venue measurement 08-11..09-29 on the host (owner 10-23) | production | open | research doc; DL row |
| Resolve the childless 10-30 nightly attempt once its tool fix lands | production | before 10-31 06:50 | `resolved-nightly` record |
| MG-2 10-30 bundle received by the WS daily task | workstation L2 | 10-31 23:59 | `verified` receipt line |
| L6_G first daily emission | workstation L2 | 11-01 | first receipt |
| R1+R2 on; 24 h S2+S9 receipts (88a RSS, REST rate, partitions sealed, built-ins unchanged) | master | 11-02 | receipt doc |

## Standing decisions

- International Polymarket only; paid weather sources only per owner-approved source; backups deprioritized; streak contiguity is
  a diagnostic. Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
