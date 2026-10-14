# State of play

**Last updated: 2026-10-14 16:30 America/Toronto (owner 16:22: LFC session 0 locked in Fri 10-16; logistics need no signature;
owner 18:30: evening-fix prereg signed, item 337 yes after replay, v2 §4 whole minute, #162 from 10-19; A' PASS 10-14 05:23).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows. **B. An
informed, domain-neutral market maker** (weather first, YouTube views next) that widens, pulls and — only where evidence
supports it — takes a side. Going in blind is ruled out. Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **Live trading paused** (owner 09-25) except owner-attended LFC sessions; no agent places, cancels or signs orders.
- Capture host: heavy work 00:30-09:00 under the lease ([host load policy](HOST_LOAD_POLICY.md)); roll-sensitive merges
  01:00-04:00; roll-free 00:30-09:00; docs-only by the light path before 12:00; never 12:00-00:30.
- **88a freeze** (owner 10-07): `maker_evidence_capture.py`, `maker_evidence_store.py`, the 88a schema record and 88a
  capture behaviour wait until after 2026-10-14. Owner decisions since 09-30 are rows in [DECISION_LOG](DECISION_LOG.md).
- **Testing (owner 10-04, PR #205):** focused + affected tests, PR CI (Windows lane #262 on 3.11.0) as full-suite evidence;
  every night head pre-gated on its stacked base; host-only behaviour needs a host run.
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md));
  relayed owner approvals bind it for serving-model and merges, never money or credentials; credentials never committed.
- **Workstation tracks** (owner 10-13 ~10:50): T1 shadow MM / replay v2 (critical path), T2 88a 10-15 head, T3 model, T4
  engineering. **Heavy freeze** 10-16 10:00 EDT until LFC session 0 is done (none 10-14); after it, a **second `workstation_heavy` slot**
  for focused runs < 5 min (owner 10-13 ~14:35; workstation only, never capture PC or live; script change separate).
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** `origin/master` `a99423120` (read it with git). N8 landed 10-13 as `67cedeb67`; then the pyup parse
  fix `eb745a5fc` and the A4 NuGet runbook revision (docs/.ps1 only).
- **Forward maker shadow ACTIVE** (`WeatherMakerShadowRunner`, 24/7, 12 bands, paper only); stop only with
  `data\maker_shadow\STOP`. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13 (end stays 11-13: #263 N_req 706, DL 10-14).
- **Journal pin:** `WeatherManualOrderJournal` pins five files incl. `wallet_reader_client.py`; a merge touching one makes it
  exit 3 until re-registered ([runbook](manual-order-journal.md)).
- **Wallet reader (8765)** restarted by the owner 10-13 10:21 on `a1014edab` (any-LAN code); LFC client config in the pinned worktree.
- **Host Python: A' PASS 10-14 05:23.** 3.11.9 (NuGet) sits side by side in `C:\Program Files\Python311-cp3119`; the
  production venv is still 3.11.0, PATH and PEP 514 unchanged, capture 10/10 ([runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md)).
- Freeze compares mask the weather editable line's sha (A' r1 false NO-GO on a merge; runbook revision 2026-10-14).
- The 10-12 calendar stands: §T + T-R 00:30 10-15, B 00:30 10-16, cutover C 00:30 10-17 (runbook §7a).
- Owner 10-13 08:53 (relayed): C advance GO if every C0 check is clean; G4 amended (auto rollback; a failed rollback waits for the owner). DECISION_LOG row.
- Calendar-shift branch `claude/decisions-pyup-shift-20261013` `84c723ae2` (C 10-18) is **ON HOLD**; not a decision.
- **DST:** DST-H3 landed; DST-M2 lands in N9; OD30 (the 11-01 night rule) stays until the owner retires it.
- **LFC session 0: Fri 10-16 from 11:00 EDT (~3 h) on the workstation**, owner-attended, locked in (owner 10-14 16:22);
  guard: Phase B clean by 09:00 10-16, reader + capture re-checked, else it slips. Code deadline 10-25 00:00Z; new pin by master.
- Logistics (dates, times, session day) take the owner's chat yes in DECISION_LOG, no signature (owner 10-13 ~22:00). init-ledger done 10-13.
- **LFC no-trade window:** 10-16 T-40 (10:20 EDT) to F2; all T-40 steps re-made 10-16 (scope `--date 2026-10-16`).
- LFC session 1: >= 10-18 after a session-0 PASS, never 10-17; t24 the day before (20-30 h old at start).
- **Build line** `codex/maker-replay-v2-build-20261003` = `1fd0c295f` (W1/W2/F3, T1-T3, Q2 #269, F4; owner-approved); the
  export nightly stays unregistered until a separate owner yes (>= 10-16).
- **Maker replay v2** (panel UTC 09-30..10-14 never read): spec v3.4 is the frozen oracle basis; handout r1 signed 10-12
  (H-11 r2, erratum 1, H-12 r1, I-1..I-8); fresh oracle author on the host. Signature target 10-22..23;
  look by 11-15. Lapse 10-23 moves out (owner 10-13): **PROPOSED 10-30, to confirm**; §4 window start: whole minute (no amendment).
- **Model:** MG-1 `b044e0f1` (scored >= 10-15) needs #190; 10-18: #190, then stage (roll verdict + parity); #162 on #190 >= 10-19.
- **Live seals** must be RESEALED before any sealed-lane attempt (#229); the LFC re1 lane consumes none. C3 rehearsal deferred.
- **Pinned deployments:** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`), exam U6 `89618c30`; paths in the task actions.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2 (T1):** oracle author on handout r1; P1-P4 on calibration dates only; gates; signature target 10-22..23.
2. **N9, 10-14 01:00-04:00:** RS `claude/integration-20261014-n9-rs-r2` `dae4c96da` (DST-M2); RF stacked `...-n9-rf-r2`
   `48becd401` (I-6 wrapper); oc `...-n9-oc` `051d8aa64` (roll-free, after rf or rf-alone); fallback `...-n9-rf-alone-r2` `f870a759d`.
3. **Host Python:** A' PASS 10-14 05:23; §T + T-R 00:30 10-15; B 00:30 10-16; cutover C 00:30 10-17.
4. **10-15 night: #177 (T2, owner yes)**; §T holds the lease 00:30-02:00, suite ~02:45, merge start by 03:40; owner accepts
   the capture restart ~03:40-04:00 EDT in the UTC 10-15 panel day. 10-16/10-17 G5 no-merge; #182 + #172 10-18; #118 >= 10-18.
5. **Item 337:** host no-METAR replay >= 10-15; on PASS flip, bump, quiet window (owner yes). NBS/NBH; NWP timing (#263 done 10-14, EF §10r).

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| A' at A3; then delete the workstation W0 temp tree | owner at host, production | 10-14 09:00 | A' receipts GO |
| LFC session 0 re-pin (deadline 10-25 + scope-date guard, Fable-reviewed) and runbook re-date to 10-16 | master; workstation | 10-15 | new pinned tip in DL |
| Policy: roll-free heads land on workstation pre-gate + Windows CI (T4 draft) | owner | after C | DECISION_LOG row |
| Evening-fix scorer `8cdcb62ec` lands (prereg SIGNED 10-13, sha256 in DL; read 10-29); OD30 retirement | T3; owner | 10-28; open | scorer on master; DL row |
| Pinned watchdog redeploy + re-register (DRIFT since #273, DST-H3) | owner scope, production | before 11-01 | watchdog CURRENT |
| 91a policy renewal (expires 10-30) | owner (production prepares) | week of 10-26 | new policy sha |

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
