# State of play

**Last updated: 2026-10-17 09:45 America/Toronto (C did not run 10-17; next C night 10-19/20; N11 tonight without C;
descriptive reads of 10-16..11-13 refused. Owner 10-17 ~09:18 and 10-16 ~09:22 decisions are DL rows).**
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
- The 88a code freeze (owner 10-07) **lapsed after 2026-10-14**; 88a changes follow the host roll verdict like any other
  code. Owner decisions since 09-30 are rows in [DECISION_LOG](DECISION_LOG.md).
- **Testing (owner 10-04, PR #205):** focused + affected tests, PR CI (Windows lane #262 on 3.11.0) as full-suite evidence;
  every night head pre-gated on its stacked base; host-only behaviour needs a host run.
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md));
  relayed owner approvals bind it for serving-model and merges, never money or credentials; credentials never committed.
- **Workstation tracks** (owner 10-13 ~10:50): T1 shadow MM / replay v2 (critical path), T2 88a 10-15 head, T3 model, T4
  engineering. **Heavy freeze** lifted 10-16 (LFC session 0 done); a **second `workstation_heavy` slot**
  for focused runs < 5 min (owner 10-13 ~14:35; workstation only, never capture PC or live; script change separate).
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** read `origin/master` with git. Since N9 only docs, `.ps1`, tests and one pin have landed (10-15: suite
  worker re-read `2e6c16e6c`, MG-1 test date fix `728f0d1b6`, python-dotenv 1.2.2 pin `3b48fa315`, S0 receipts, docs).
- **Forward maker shadow ACTIVE** (`WeatherMakerShadowRunner`, 24/7, 12 bands, paper only); stop only with
  `data\maker_shadow\STOP`. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13 (end stays 11-13: #263 N_req 706, DL 10-14).
  **Descriptive reads of 10-16..11-13 are refused everywhere until the panel closes** (owner 10-17).
- **Journal pin:** `WeatherManualOrderJournal` pins five files incl. `wallet_reader_client.py`; a merge touching one makes it
  exit 3 until re-registered ([runbook](manual-order-journal.md)).
- **Wallet reader (8765)** on `a1014edab` (any-LAN code) since 10-13. It is serial: space post-run reads and retry one
  timeout after a quiet wait (session-0 finding, [wallet reader](wallet-reader.md)).
- **Host Python: Phase B PASS 10-16** (3.11.9: bounded suite 21/21 on the stage venv, release case A, `qualification.json`
  PASS; attempt 1 false NO-GO from verifier r1, fixed by r2; B3 and E finished by hand after the `f611cf22c` wrapper defect:
  capture 10/10, `status.ps1` exit 2 only from 3 standing flags; [runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md) revision notes).
  Venv still 3.11.0. **C did not run 10-17** (no owner GO by 01:15); next C night Mon 10-19 into 10-20, owner GO in chat that night.
- Owner 10-13 08:53: C advance GO if every C0 check is clean; G4 amended (auto rollback; a failed one waits for the owner). **DST:**
  DST-H3 and DST-M2 (`41fa7bc57`) landed; OD30 (the 11-01 night rule) holds for 11-01 and lapses 11-02 (owner 10-15).
- **LFC session 0 ATTESTED 10-16** (~16:35Z, pin `e27909a76`, 0 fills; final verify PASS, `counted_sessions` 0; DL row,
  [record](../research/live-fill-calibration-session0-record-2026-10-16.md)). **Session 1: Sun 10-18 `go` 12:00 EDT**
  (owner 10-16 14:28; t24 Sat 10-17 ~14:00 EDT; fallback Mon 10-19) on pin `21cf1ed42` (DL row). Manual trading paused from
  session 1 until the last lot settles (prereg §5, owner 10-16). Logistics take the owner's chat yes in DL (10-13).
- **Build line** `codex/maker-replay-v2-build-20261003` = `1fd0c295f` (W1/W2/F3, T1-T3, Q2 #269, F4; owner-approved); the
  export nightly stays unregistered until a separate owner yes (>= 10-16).
- **Maker replay v2** (panel UTC 09-30..10-14 never read): spec v3.4 is the frozen oracle basis; handout r1 signed 10-12
  (H-11 r2, erratum 1, H-12 r1, I-1..I-8); fresh oracle author on the host. Signature target 10-22..23;
  look by 11-15. **Lapse 10-30** (owner 10-15); §4 window start: whole minute (no amendment). Owner 10-15: C15/A8 = whole-minute
  intervals (M); E6 MEASURED pull-candidate ceiling (carried x 14/3); §9 trim kept; consolidated rows 13/16/17 binding (DL 10-15).
- **Model:** MG-1 `b044e0f1` (scored >= 10-15) needs #190; 10-18: #190, then stage (roll verdict + parity); #162 on #190 >= 10-19.
  MG-1 window BOUND (owner 10-16): D0 10-15, provisional last 11-28, may only move later. t3-r3 13-16 prereg SIGNED 10-16.
- **Owner 10-16 ~09:22 (DL rows):** SOURCE_DISAGREEMENT Option 1 + ledger blocker class and the MG-1 bound land after N12 (roll
  verdict); S4 evidence-host registration yes after the 10-18 BLAS receipt; WRH Synoptic token no; reboot deferred.
- **No-go bar:** [exhaustion register](EXHAUSTION_REGISTER.md) (10-14; the owner keeps the no-go). Maker-track owner review 11-20 (was 10-31). Stratum-C and Aug-Sep gap numbers are tainted; a post-fix scoreboard is URGENT.
- **Live seals** must be RESEALED before any sealed-lane attempt (#229); the LFC re1 lane consumes none. C3 rehearsal deferred. **Pinned:** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`), exam U6 `89618c30`; paths in the task actions.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2 (T1):** oracle author on handout r1; P1-P4 on calibration dates only; gates; signature target 10-22..23.
2. **Host Python:** B PASS 10-16; C did not run 10-17; next C night 10-19/20 (owner GO that night); N11 lands 10-17/18 without C.
3. **N11 (10-17/18) is `claude/integration-20261018-stack6-r` `802591bde`** (supersedes stack4/stack5/88a-rs-r3); N12 10-18/19; #118 >= 10-18.
4. **Item 337:** host no-METAR replay >= 10-15; on PASS flip, bump, quiet window (owner yes). NBS/NBH; NWP timing (#263 done 10-14, EF §10r).
5. **Data layer v2 (T3/T4, owner 10-14):** [plan](DATA_LAYER_V2_PLAN.md); S0 receipts landed 10-15; S0b FC-11 10-16; S1 10-19, S3 10-20, S2+S9+P1 10-21; §9 answered except Q6, Q9, Q14 (DL 10-14, 10-15).

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| RF policy A (owner 10-15): roll-free heads land on workstation pre-gate + Windows CI once #274, #276/#284 green; then #209 deselect build | T4; workstation | after C | DL row; lane green |
| Evening-fix scorer `8cdcb62ec` lands (prereg SIGNED 10-13, sha256 in DL; read 10-29 `--no-market`, item 337 owns it) | T3 | 10-28 | scorer on master |
| Pinned watchdog redeploy from master, re-register only the watchdog task (owner yes 10-15) | production | after C, by 10-28 | watchdog CURRENT |
| U6 replay-bundle export registered 04:10 from the 3.11.9 build-line tip (owner yes 10-15) | production | night 10-20 | task registered; first receipt |
| 91a policy renewal unchanged (owner A 10-15; CP-5 LZX later, own change) | production | ~10-27 (expires 10-30) | new policy sha |

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic. Capture-host
  heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
