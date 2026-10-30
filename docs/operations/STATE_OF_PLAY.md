# State of play

**Last updated: 2026-10-28 America/Toronto (evening: pilot pin passed and runbook adopted, session 1 waits on the owner's t24;
L6_G screen exempted; capture-host outage 10-28; 91a policy renewed. Rule B-1 bound 10-28, D0 10-29; owner option B 10-25).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** `status.ps1` flags
> it when its date is over 3 days old. Live readings (free space, commit, capture health) come from `status.ps1` and `Get-Volume`.

## Objectives (owner 10-23 hard directive, sharpened by option B 10-25)

Precondition: protect capture and settlement evidence. **The goal is model improvement**: exhaust the model levers and run one
minimal forward edge test (B) against market prices ("We exhaust all options on model improvements", owner 10-25). **A B FAIL ends
this candidate's edge claim, not the project** (owner Q2 10-25, DL); work continues down the [lever inventory](LEVER_INVENTORY_2026-10-26.md).
88a development, bundle B, the plugin core and YouTube-maker scoping stay paused; the [maker pilot](MAKER_PILOT_PLAN_2026-10.md) is approved.

## Headline

- **Two thirds of the 07-12 excess loss is sharpness, not centre** (EF §10ag); NBM-published spread closed, GEFS member spread killed as a scale modulator at 07-16 (R-Q A; its 00-06 variant B blocked on parity); 07-12 centre corrections exhausted (L5 KILL).
- **Against the market the model adds nothing yet:** walk-forward log-pool weight on MG-1 w ≈ 0.008 (EF §10ad).

## Current authority

- **Small maker pilot APPROVED** (DL 10-26; LFC lane, Toronto+Denver, $100 cap). Pin `124603578` passed; locked pin worktree on the
  workstation, prereq 6 / G-e confirmed by the owner, session-1 runbook adopted with errata (master ruling) — all DL 10-28.
  **No t24 ran 10-28, so session 1 is not 10-29; earliest 10-30 if the owner runs the t24 ~14:00 on 10-29.** Owner sessions
  only; no agent places, cancels or signs orders. Other live trading stays paused (owner 09-25).
- Capture host: heavy work 00:30-09:00 under the lease ([host load policy](HOST_LOAD_POLICY.md)); roll-sensitive merges
  01:00-04:00; roll-free 00:30-09:00; docs-only by the light path before 12:00; never 12:00-00:30.
- Owner decisions are rows in [DECISION_LOG](DECISION_LOG.md); master's rulings are labelled as master's, never as the owner's.
- **Weather data:** paid only per owner-approved source recorded in DECISION_LOG (owner 10-23); free official or reputable data
  needs no ask (owner 10-24); ask for packages, unknown hosts, logins, payment or anything suspicious.
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md)); parallel
  lanes, one branch each (owner 10-23); keep it fully busy, Fable cautiously (owner 10-24); heavy work via `workstation_heavy.ps1`.
- **Record every rule-out** (owner 10-25): each null and kill goes to the [exhaustion register](EXHAUSTION_REGISTER.md) §6 with
  numbers, window, conditions and a "Reopen if" line.
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** read `origin/master` with git (`75792494c` when written): N12 + N13 on host Python 3.11.9, S2+S9, venue
  labels, W3 and split landed. **Night 10-25/26 STACK failed on the host:** STACK, LFS, docs `6596e6f6e` and D did not land; HOSTFIX rebuilds.
- **Outcome embargo unchanged:** no outcome, price or label read after 09-29 except under a named, owner-opened test. Dates
  <= 09-29 are development only; descriptive reads of 10-16..11-13 stay refused (owner 10-17).
- **MG-1** is bound and in forward shadow; its single look comes after its window closes (after 11-28;
  [reserved window](reserved-confirmation-window.md)). MG-1 forward outputs are never read before that look.
- **MG-2 / Rule B-1 BOUND 10-28** ([design](B_FORWARD_TEST_DESIGN.md); DL 10-28): D0 = 10-29 (slip clause), N = 45
  countable dates (owner Q3), 45th date 12-12, NI margin +0.0027 (owner Q4); single look 12-13, strictly after MG-1's. Owner option 2 exempts
  MG-2 only from the reservation, one look, and (Q1) the capture-time market read for B travels at that look.
- **MG-2 bound via the C7/C8 line** (`claude/b-binding-package-20261028`); B scorer frozen `f941628a…`; share_many = option (i) (master).
- **Kill scopes (master R9/R10, 10-25):** R-I closes fitted temperature/scale maps only (spread information: own rule, full ladder,
  no global sharpening, floor never weakened). R-G/R-J cover Aug-Sep only; Oct-Dec rungs need a fresh rule, LOYO Oct-Dec 2021-25.
- **Labels (master ruling 10-25, reading B):** WU before 10-23, venue rule (WU fallback) from it; paid band = WU 626/626, so no
  past evaluation changes (EF §10ai; cutover `28e96a3e7`). **Denver >= 10-23: KDEN, unscored, out of MG-2 and B** (master).
- **Dead-bucket NO buying is closed** (US and Toronto; EF §10ad, §10ah). **Toronto's NBM guidance is not captured** (RF);
  forward NBP CYYZ capture is approved in principle (master ruling 10-26), via the quiet-window merge night 10-26/27.
- **L6_G forward screen exempted** (owner "I give my ok.", DL 10-28): outcome-blind, N = 45 screen, one look after B (>= 12-13), never alters B.
- **Capture-host outage 10-28** 11:47-12:54, ~67 graded-window min lost; fixed, Ethernet pending ([record](capture-host-wifi-outage-2026-10-28.md)).
- **91a cold-snapshot nightly** was blocked 10-27/28 by the refused 10-26 attempt, resolved 10-28; policy renewed (`eca4064a…`, expires 11-27).
- **Forward maker shadow ACTIVE** (paper only); stop only with `data\maker_shadow\STOP`; scoring refuses UTC 09-30..11-13 (DL 10-14).
- **More markets** (owner 10-23, DL): R1 pilot cities recorder-only, R2 from 11-01, M1 Europe first; new cities label from IEM METAR.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok. **DST:** OD30 holds 11-01.

## Ordered critical path

1. **Rule B-1 bound 10-28**; MG-2 accrues from D0 10-29; no look before 12-13.
2. **HRRR forward recorder: YES (master); MG-3 = paired D-C on B's dates** (owner 10-26, DL; H1 = MG-3 − MG-2; MG-1 exemption
   11-11..11-28): pre-registration in preparation; D0 ~11-10/11; result ~mid-December. R-K/R-R dev WINs are not edges until forward parity ([plan](../research/l2-pooled-residual-2026-10-24/drafts/hrrr_forward_recorder_parity_plan_DRAFT.md)).
3. **Running:** R-O, NBS-TXN diagnostic. **R-Q closed 10-29** (ledger row 71, register X43): A KILLED, B BLOCKED on P_B. **Oct-Dec rungs** under R10, each with a ledger row first: R-ODC G1 and G2 PASS on history (rows 65, 69; G2 small), next serve parity, then a forward prereg.
4. **Cool-season paper test PT-1** ([draft](COOL_SEASON_PAPER_TEST_PREREG.md); owner Q6-Q9 answered 10-25, dates 12-12..01-25) bound before its D0.
5. **Host nights:** pending integrations through the quiet-window merge, one attempt manifest each.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| Rule B-1 §(a) control read (ledger row 68, pending) | master | per B §"At binding" | ledger row 68 |
| Coverage field added to the B exporter | master | before D0 | exporter on the binding branch |
| PT-1 bound: PT_D0 set, G = 15 s fixed by the outcome-blind dev check, rule sha pinned (owner Q6-Q9 answered 10-25) | master | before PT_D0 | binding commit; DL row |
| Maker pilot plan owner questions answered; HOLD lifted only through the runbook's gates | owner | open | DL row; runbook prerequisites |
| WU-vs-venue measurement 08-11..09-29 on the host (owner 10-23) | production | open | research doc; DL row |
| Evening-fix scorer read 10-29 `--no-market` (prereg SIGNED; item 337 owns it) | T3 | 10-29 | scorer receipt |
| 91a renewed policy `eca4064a…` registered after its dry run | production | 10-29 | scheduled action carries the new policy sha |
| L6_G frame builder pinned in a dated clarification, with a positive refusal test for label/outcome/price columns | workstation L2 | before the first emission | clarification commit + blob |

## Standing decisions

- International Polymarket only; paid weather sources only per owner-approved source; backups deprioritized; streak contiguity is
  a diagnostic. Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
