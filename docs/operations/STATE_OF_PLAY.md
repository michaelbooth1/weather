# State of play

**Last updated: 2026-10-26 America/Toronto (owner option B 10-25: one minimal forward edge test, Rule B-1, plus model levers
at full throttle; "Yes to all" to the MG-2 exemption, paper test, maker pilot and venue-label cutover; B questions answered).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner 10-23 hard directive, sharpened by option B 10-25)

Precondition: protect capture and settlement evidence. **The goal is model improvement**: exhaust the model levers, and run
one minimal forward formal edge test (B) against market prices. The owner, verbatim 10-25: "We exhaust all options on model
improvements and we aren't there yet". **A B FAIL ends this candidate's edge claim, not the project** (owner Q2 10-25, DL);
work continues down the [lever inventory](LEVER_INVENTORY_2026-10-26.md). 88a development, bundle B, the plugin core and the
YouTube-maker scoping stay paused; the **small maker pilot is APPROVED** (DL 10-26, both owner confirmations; [plan draft](MAKER_PILOT_PLAN_2026-10.md)).

## Headline

- **About two thirds of the 07-12 excess loss is sharpness, not centre** (R-H atlas, EF §10ag). **NBM-published spread is closed**
  (R-S killed at dev); **GEFS member spread (R-Q) is open**, approved under R9. Centre corrections at 07-12 are exhausted (L5 KILL).
- **Against the market the model adds nothing yet:** the walk-forward log-pool weight on MG-1 is w ≈ 0.008 (EF §10ad); the 13-16
  blend gain is the hard floor, not model information.

## Current authority

- **Small maker pilot APPROVED** (DL 10-26; LFC lane, Toronto+Denver, $100 cap): new pin and t24 go ahead per plan; earliest start **Wed 10-28** if the pin passes before the t24 on 10-27 (~14:00 EDT), else Thu 10-29. Owner sessions only; no agent places, cancels or signs orders. Other live trading stays paused (owner 09-25).
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

- **Production source:** read `origin/master` with git (`c33176cbf` when written): N12 + N13 on host Python 3.11.9, S2+S9, venue
  labels, W3 and split landed. **Night 10-25/26 STACK failed on the host:** STACK, LFS, docs `6596e6f6e` and D did not land; HOSTFIX rebuilds.
- **Outcome embargo unchanged:** no outcome, price or label read after 09-29 except under a named, owner-opened test. Dates
  <= 09-29 are development only; descriptive reads of 10-16..11-13 stay refused (owner 10-17).
- **MG-1** is bound and in forward shadow; its single look comes after its window closes (after 11-28;
  [reserved window](reserved-confirmation-window.md)). MG-1 forward outputs are never read before that look.
- **MG-2 / Rule B-1** ([design](B_FORWARD_TEST_DESIGN.md), DRAFT until master's 10-27 binding): D0 = 10-28 (master), N = 45
  countable dates (owner Q3), NI margin +0.0027 (owner Q4); earliest look ~12-12, strictly after MG-1's. Owner option 2 exempts
  MG-2 only from the reservation, one look, and (Q1) the capture-time market read for B travels at that look.
- **MG-2 binds via the C7/C8 line** (`e40804dfe` or successor; master 10-26); binding v2 `710f0c672` superseded, never lands alone.
  B scorer frozen (`b25b63f7…`). share_many = option (i) (master); (ii) at 0.08 drafted in Clarification E. Not retrain-family.
- **Kill scopes (master R9/R10, 10-25):** R-I closes fitted temperature/scale maps only (spread information: own rule, full ladder,
  no global sharpening, floor never weakened). R-G/R-J cover Aug-Sep only; Oct-Dec rungs need a fresh rule, LOYO Oct-Dec 2021-25.
- **Labels (master ruling 10-25, reading B):** WU before 10-23, venue rule (WU fallback) from it; paid band = WU 626/626, so no
  past evaluation changes (EF §10ai; cutover `28e96a3e7`). **Denver >= 10-23: KDEN, unscored, out of MG-2 and B** (master).
- **Dead-bucket NO buying is closed** (US and Toronto; EF §10ad, §10ah). **Toronto's NBM guidance is not captured** (RF);
  forward NBP CYYZ capture is approved in principle (master ruling 10-26), via the quiet-window merge night 10-26/27.
- **Forward maker shadow ACTIVE** (paper only); stop only with `data\maker_shadow\STOP`; scoring refuses UTC 09-30..11-13 (DL 10-14).
- **More markets** (owner 10-23, DL): R1 pilot cities recorder-only, R2 from 11-01, M1 Europe first; new cities label from IEM METAR.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok. **DST:** OD30 holds 11-01.

## Ordered critical path

1. **Bind Rule B-1** (master, 10-27) with C7 resolved, so MG-2 starts accruing at D0 10-28.
2. **HRRR forward recorder: YES (master); MG-3 = paired D-C on B's dates** (owner 10-26, DL; H1 = MG-3 − MG-2; MG-1 window
   exemption 11-11..11-28): L2 preparing the pre-registration; D0 ~11-10/11; result ~mid-December. Workstation shadow capture; host head via QWM on master's say.
   R-K (13-16, −0.0722), R-R (07-12 vs L6, −0.0402): dev WINs, R 1.22 / 1.112, not edges until forward parity ([plan draft](../research/l2-pooled-residual-2026-10-24/drafts/hrrr_forward_recorder_parity_plan_DRAFT.md); MG-2 Clarifications drafted, not applied).
3. **Running:** R-O (GEFS centre), R-Q (GEFS spread), NBS-TXN anchor diagnostic (input-only). Closed 10-26: R-P, R-PD, R-N, R-L2 (EF §10ak).
4. **Oct-Dec rungs** under R10 and the NBS TXN input (L12), each pre-registered with a ledger row before any scored row.
5. **Cool-season paper test PT-1** ([draft](COOL_SEASON_PAPER_TEST_PREREG.md); owner Q6-Q9 answered 10-25, dates 12-12..01-25) bound before its D0.
6. **Host nights:** pending integrations through the quiet-window merge, one attempt manifest each.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| Rule B-1 bound via the C7/C8 line: `<FILL@BINDING>` fields filled (`b_scorer_sha256` = `b25b63f7…`), `mg2_binding_commit` checked with `git cat-file` against origin | master | 10-27, before D0 10-28 | binding commit; DL or ledger row |
| Coverage field added to the B exporter | master | before D0 | exporter on the binding branch |
| PT-1 bound: PT_D0 set, G = 15 s fixed by the outcome-blind dev check, rule sha pinned (owner Q6-Q9 answered 10-25) | master | before PT_D0 | binding commit; DL row |
| Maker pilot plan owner questions answered; HOLD lifted only through the runbook's gates | owner | open | DL row; runbook prerequisites |
| WU-vs-venue measurement 08-11..09-29 on the host (owner 10-23) | production | open | research doc; DL row |
| Evening-fix scorer read 10-29 `--no-market` (prereg SIGNED; item 337 owns it) | T3 | 10-29 | scorer receipt |
| 91a policy renewal unchanged (owner A 10-15) | production | ~10-27 (expires 10-30) | new policy sha |

## Standing decisions

- International Polymarket only; paid weather sources only per owner-approved source; backups deprioritized; streak contiguity is
  a diagnostic. Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
