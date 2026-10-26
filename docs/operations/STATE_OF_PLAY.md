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
YouTube-maker scoping stay paused; the maker pilot is approved in principle but on HOLD ([plan draft](MAKER_PILOT_PLAN_2026-10.md)).

## Headline

- **About two thirds of the 07-12 excess loss is sharpness, not centre** (R-H atlas, EF §10ag), so **spread-information levers
  come next**. Centre corrections at 07-12 are exhausted (L5 KILL, EF §10ah); no candidate block reaches R ≤ 1 against the market.
- **Against the market the model adds nothing yet:** the walk-forward log-pool weight on MG-1 is w ≈ 0.008 (EF §10ad); the 13-16
  blend gain is the hard floor, not model information.

## Current authority

- **Live trading paused** (owner 09-25); **LFC campaign backlogged** (owner 10-19): no agent places, cancels or signs orders.
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

- **Production source:** read `origin/master` with git (`46dad240b` when written): N12 + N13 landed 10-24 on host Python 3.11.9;
  S2+S9 (`f66252090`), dev scorecard, Stage-A retry, venue-rule labels (chain and incremental) and workstation heavy slots landed.
- **Outcome embargo unchanged:** no outcome, price or label read after 09-29 except under a named, owner-opened test. Dates
  <= 09-29 are development only; descriptive reads of 10-16..11-13 stay refused (owner 10-17).
- **MG-1** is bound and in forward shadow; its single look comes after its window closes (after 11-28;
  [reserved window](reserved-confirmation-window.md)). MG-1 forward outputs are never read before that look.
- **MG-2 / Rule B-1** ([design](B_FORWARD_TEST_DESIGN.md), DRAFT until master's 10-27 binding): D0 = 10-28 (master), N = 45
  countable dates (owner Q3), NI margin +0.0027 (owner Q4); earliest look ~12-12, strictly after MG-1's. Owner option 2 exempts
  MG-2 only from the reservation, one look, and (Q1) the capture-time market read for B travels at that look.
- **Retrain-family (master 10-25):** P3d_N and MG-2 are serving-stage like MG-1; no 13-16 drop on 11-18..12-11.
- **C7 as-of gate** for P3d_N's receipt look-ahead is drafted (`claude/mg2-c7-asof-gate-20261025` @ `525effe62`), not landed;
  the look-ahead is bounded and flips no MG-2 gate (EF §10ag).
- **Kill scopes (master's rulings R9/R10, 10-25):** R-I closes fitted temperature/scale maps only; spread information is a new
  family with its own rule and full ladder, no global sharpening, the floor never weakened. R-G/R-J cover Aug-Sep only; an
  Oct-Dec rung needs a fresh rule plus LOYO on Oct-Dec 2021-25 and promotes only through a forward test.
- **Venue labels** apply from the 10-23 events (owner "Yes to all" item 4; EF §10x); WU before. **Denver >= 10-23 labels KDEN,
  is unsupported for model scoring**, and is excluded from the MG-2 gate and from B (master).
- **Dead-bucket NO buying is closed** (US and Toronto; EF §10ad, §10ah). **Toronto's NBM guidance exists but is not captured** (RF).
- **Forward maker shadow ACTIVE** (paper only); stop only with `data\maker_shadow\STOP`; scoring refuses UTC 09-30..11-13 (DL 10-14).
- **More markets** (owner 10-23, DL): R1 pilot cities recorder-only, R2 from 11-01, M1 Europe first; new cities label from IEM METAR.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok. **DST:** OD30 holds 11-01.

## Ordered critical path

1. **Bind Rule B-1** (master, 10-27) with C7 resolved, so MG-2 starts accruing at D0 10-28.
2. **Spread-information levers** (R9 family, own rule), then the inventory's start-now list: Toronto guidance, pre-dawn 00-06,
   the HRRR 13-16 path (R-K, pre-registered), per-market centre bias on L6/P3d_N at 07-12, the standard-time alignment audit.
3. **Oct-Dec rungs** under R10 and the NBS TXN input (L12), each pre-registered with a ledger row before any scored row.
4. **Cool-season paper test PT-1** ([draft](COOL_SEASON_PAPER_TEST_PREREG.md), owner questions open) bound before its D0.
5. **Host nights:** pending integrations through the quiet-window merge, one attempt manifest each.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| Rule B-1 bound: `<FILL@BINDING>` fields filled, rule sha pinned | master | 10-27, before D0 10-28 | binding commit; DL or ledger row |
| C7 as-of gate Clarification decided (`525effe62`, rule sha `ccb2b82a…`) | master | before 10-28 | landed or rejected on record |
| Coverage field added to the B exporter | master | before D0 | exporter on the binding branch |
| PT-1 owner questions answered; PT_D0 set; rule sha pinned | owner, master | before PT_D0 | DL row; binding commit |
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
