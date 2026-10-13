# State of play

**Last updated: 2026-10-13 12:00 America/Toronto (N8 + pyup NuGet runbook landed; Phase A NO-GO at A4, A' 10-14 07:00;
LFC T-24h done, session 0 10-14; N9 heads set; four workstation tracks).**
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
- **Workstation tracks** (owner 10-13 ~10:50, "stay ambitious ... keep going"): T1 shadow MM / replay v2 (critical path),
  T2 the 88a 10-15 roll-sensitive head, T3 model improvements, T4 core engineering throughput. **Heavy freeze** on the
  workstation from 10-14 10:00 EDT until LFC session 0 is declared done.
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** `origin/master` `a99423120` (read it with git). N8 landed 10-13 as `67cedeb67`; then the pyup parse
  fix `eb745a5fc` and the A4 NuGet runbook revision (docs/.ps1 only).
- **Forward maker shadow ACTIVE** (`WeatherMakerShadowRunner`, 24/7, 12 bands, paper only); stop only with
  `data\maker_shadow\STOP`. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13.
- **Journal pin:** `WeatherManualOrderJournal` pins five files incl. `wallet_reader_client.py`; a merge touching one makes it
  exit 3 until re-registered ([runbook](manual-order-journal.md)).
- **Wallet reader (8765)** restarted by the owner 10-13 10:21 on `a1014edab` (any-LAN code); LFC client config in the pinned worktree.
- **Host Python is 3.11.0.** Phase A ran 10-13 08:54 and stopped NO-GO at A4: the python.org installer planned a MajorUpgrade
  of the per-user 3.11.0 ([runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md), revision 2026-10-13).
- The owner approved the NuGet side-by-side route into `C:\Program Files\Python311-cp3119`; W0 verified it on the workstation.
- **A' resumes at A3 on the host 10-14 07:00-09:00** (`claude/night-plans`, `night-plans/2026-10-14/pyup-phase-a2/`).
- If A' passes, the 10-12 calendar stands: §T + T-R 00:30 10-15, B 00:30 10-16, cutover C 00:30 10-17 (runbook §7a).
- Owner 10-13 08:53 (relayed): C advance GO if every C0 check is clean; G4 amended (auto rollback; a failed rollback waits for the owner). DECISION_LOG row.
- Calendar-shift branch `claude/decisions-pyup-shift-20261013` `84c723ae2` (C 10-18) is **ON HOLD**; not a decision.
- **DST:** DST-H3 landed; DST-M2 lands in N9; OD30 (the 11-01 night rule) stays until the owner retires it.
- **LFC session 0: 10-14 11:00-19:50 EDT on the workstation**, owner-attended; pinned `acd052a2d`; signed documents stay SIGNED.
- LFC T-24h done 10-13 14:30Z (checks PASS, init-ledger CREATED, t24); t24 re-taken 14:34Z after the owner closed one
  position; pre-existing wallet positions are pinned by baselines (D9 correction, DECISION_LOG 10-13).
- **LFC no-trade window:** 10-14 T-40 snapshot to the snapshot after session 0 (F2); 10:20 EDT conditions in DECISION_LOG 10-13.
- LFC session 1: 10-15 afternoon (or >= 10-18, never 10-16/17); needs a fresh t24 taken after F2 (checklist F2a).
- **Build line** `codex/maker-replay-v2-build-20261003` = `1fd0c295f` (W1/W2/F3, T1-T3, Q2 #269, F4; owner-approved); the
  export nightly stays unregistered until a separate owner yes (>= 10-16).
- **Maker replay v2** (panel UTC 09-30..10-14 never read): spec v3.4 is the frozen oracle basis; handout r1 signed 10-12
  (H-11 r2, erratum 1, H-12 r1, isolation I-1..I-8); fresh oracle author on the host. Signature ~10-18..20; look by 11-15.
- **Model, morning:** MG-1 SIGNED 10-04 at `b044e0f1`; needs parser v2 (#190); scored on dates >= 10-15.
- **Live seals** must be RESEALED before any sealed-lane attempt (#229); the LFC re1 lane consumes none. C3 rehearsal deferred.
- **Pinned deployments:** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`), exam U6 `89618c30`; paths in the task actions.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2 (T1):** oracle author on handout r1; P1-P4 on calibration dates only; gates; signature ~10-18..20.
2. **N9, 10-14 01:00-04:00:** RS `claude/integration-20261014-n9-rs-r2` `dae4c96da` (DST-M2); RF stacked `...-n9-rf-r2`
   `48becd401` (I-6 wrapper); oc `...-n9-oc` `051d8aa64` (roll-free, after rf or rf-alone); fallback `...-n9-rf-alone-r2` `f870a759d`.
3. **Host Python:** A' 10-14 07:00; §T + T-R 10-15; B 10-16; cutover C 00:30 10-17.
4. **10-15 night: one roll-sensitive 88a head (T2)**; §T holds the lease 00:30-02:00, suite ~02:45, merge start by 03:40.
   Nights 10-16 and 10-17 are G5 no-merge; remaining 88a heads (#118, #172 + #182, #177) 10-18 or later.
5. **Measurements (09-29 only):** desk-study power rule #263. **Research:** NBS/NBH probe; T+1/T+2 NWP timing; item 337.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| A' at A3; then delete the workstation W0 temp tree | owner at host, production | 10-14 09:00 | A' receipts GO |
| Fresh t24 after F2 for session 1 (F2a) | owner | 10-14 evening | t24 20-30 h old at start |
| Policy: roll-free heads land on workstation pre-gate + Windows CI (T4 draft) | owner | after C | DECISION_LOG row |
| Evening-fix scoring prereg; OD30 retirement | owner | open | DECISION_LOG rows |
| Pinned watchdog redeploy + re-register (DRIFT since #273, DST-H3) | owner scope, production | before 11-01 | watchdog CURRENT |
| 91a policy renewal (expires 10-30) | owner (production prepares) | week of 10-26 | new policy sha |

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
