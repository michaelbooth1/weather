# State of play

**Last updated: 2026-10-15 11:30 America/Toronto (owner 10-15 "All as recommended" + batch 2 "approve all": RF A, U6 10-20,
#209 build, 91a A, watchdog by 10-28, OD-B1 build, O9 UTC cutoff; replay v2 M/E6/13/16/17; DLv2 §9; review 11-20).**
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
  engineering. **Heavy freeze** 10-16 10:00 EDT until LFC session 0 is done (none 10-14); after it, a **second `workstation_heavy` slot**
  for focused runs < 5 min (owner 10-13 ~14:35; workstation only, never capture PC or live; script change separate).
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** read `origin/master` with git. Since N9 only docs, `.ps1` and tests have landed (10-15: the suite
  capture-worker re-read `2e6c16e6c`, the data-layer v2 S0 receipts and five docs batches).
- **Forward maker shadow ACTIVE** (`WeatherMakerShadowRunner`, 24/7, 12 bands, paper only); stop only with
  `data\maker_shadow\STOP`. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13 (end stays 11-13: #263 N_req 706, DL 10-14).
- **Journal pin:** `WeatherManualOrderJournal` pins five files incl. `wallet_reader_client.py`; a merge touching one makes it
  exit 3 until re-registered ([runbook](manual-order-journal.md)).
- **Wallet reader (8765)** restarted by the owner 10-13 10:21 on `a1014edab` (any-LAN code). The LFC client config is **not** in the session-0 pin `C:\wt\lfc-pinned-e27909a76` yet: the owner re-enters it there on 10-16 before the 10:00 checks (session-0 runbook §3.6 step 3, owner only).
- **Host Python: A' PASS 10-14; §T + T-R PASS 10-15 00:31** (hash-locked tzdata 2026.3 into the production venv; capture
  10/10 after). Venv still 3.11.0; 3.11.9 side by side. Next: B 00:30 10-16, cutover C 00:30 10-17 ([runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md) §7a).
- Owner 10-13 08:53 (relayed): C advance GO if every C0 check is clean; G4 amended (auto rollback; a failed rollback waits for the owner). DECISION_LOG row.
- Calendar-shift branch `claude/decisions-pyup-shift-20261013` `84c723ae2` (C 10-18) is **ON HOLD**; not a decision.
- **DST:** DST-H3 landed; DST-M2 lands in N9; OD30 (the 11-01 night rule) holds for 11-01 and lapses 11-02 (owner 10-15).
- **LFC session 0: Fri 10-16 from 11:00 EDT (~3 h) on the workstation**, owner-attended, locked in (owner 10-14 16:22);
  guard (owner "Keep B" 10-14 16:27; G7 exception): Phase B clean by 09:00 10-16, reader + capture re-checked, else it slips. Code deadline 10-25 00:00Z; new pin by master.
- Logistics (dates, times, session day) take the owner's chat yes in DECISION_LOG, no signature (owner 10-13 ~22:00). init-ledger done 10-13.
- **LFC no-trade window:** 10-16 T-40 (10:20 EDT) to F2; all T-40 steps re-made 10-16 (scope `--date 2026-10-16`).
- LFC session 1: >= 10-18 after a session-0 PASS, never 10-17; t24 the day before (20-30 h old at start).
- **Build line** `codex/maker-replay-v2-build-20261003` = `1fd0c295f` (W1/W2/F3, T1-T3, Q2 #269, F4; owner-approved); the
  export nightly stays unregistered until a separate owner yes (>= 10-16).
- **Maker replay v2** (panel UTC 09-30..10-14 never read): spec v3.4 is the frozen oracle basis; handout r1 signed 10-12
  (H-11 r2, erratum 1, H-12 r1, I-1..I-8); fresh oracle author on the host. Signature target 10-22..23;
  look by 11-15. **Lapse 10-30** (owner 10-15); §4 window start: whole minute (no amendment). Owner 10-15: C15/A8 = whole-minute
  intervals (M); E6 MEASURED pull-candidate ceiling (carried x 14/3); §9 trim kept; consolidated rows 13/16/17 binding (DL 10-15).
- **Model:** MG-1 `b044e0f1` (scored >= 10-15) needs #190; 10-18: #190, then stage (roll verdict + parity); #162 on #190 >= 10-19.
- **No-go bar:** [exhaustion register](EXHAUSTION_REGISTER.md) (10-14; the owner keeps the no-go). Maker-track owner review 11-20 (was 10-31). Stratum-C and Aug-Sep gap numbers are tainted; a post-fix scoreboard is URGENT.
- **Live seals** must be RESEALED before any sealed-lane attempt (#229); the LFC re1 lane consumes none. C3 rehearsal deferred.
- **Pinned deployments:** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`), exam U6 `89618c30`; paths in the task actions.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2 (T1):** oracle author on handout r1; P1-P4 on calibration dates only; gates; signature target 10-22..23.
2. **Host Python:** B 00:30 10-16 (guard above); cutover C 00:30 10-17.
3. **#177 (T2, owner yes) moved to the 10-18 night:** the 10-15 suite failed on a new #177 test (timing) and a master date
   test; fix head `claude/integration-20261018-88a-rs-r3` `9121de239` (tests only). 10-16/10-17 G5 no-merge; #182 + #172 10-18; #118 >= 10-18.
4. **Item 337:** host no-METAR replay >= 10-15; on PASS flip, bump, quiet window (owner yes). NBS/NBH; NWP timing (#263 done 10-14, EF §10r).
5. **Data layer v2 (T3/T4, owner 10-14):** [plan](DATA_LAYER_V2_PLAN.md); S0 receipts landed 10-15; S0b FC-11 10-16; S1 10-19, S3 10-20, S2+S9+P1 10-21; §9 answered except Q6, Q9, Q14 (DL 10-14, 10-15).

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| LFC session 0 re-pin and runbook re-date to 10-16: done; pin `e27909a76` recorded in DL 10-15; reader client config re-entry is an owner step 10-16 | owner | 10-16 10:00 | `config\local\wallet_reader_client.json` present in the pin (name check only) |
| RF policy A (owner 10-15): roll-free heads land on workstation pre-gate + Windows CI once #274, #276/#284 green; then #209 deselect build | T4; workstation | after C | DL row; lane green |
| Evening-fix scorer `8cdcb62ec` lands (prereg SIGNED 10-13, sha256 in DL; read 10-29 `--no-market`, item 337 owns it) | T3 | 10-28 | scorer on master |
| Pinned watchdog redeploy from master, re-register only the watchdog task (owner yes 10-15) | production | after C, by 10-28 | watchdog CURRENT |
| U6 replay-bundle export registered 04:10 from the 3.11.9 build-line tip (owner yes 10-15) | production | night 10-20 | task registered; first receipt |
| 91a policy renewal unchanged (owner A 10-15; CP-5 LZX later, own change) | production | ~10-27 (expires 10-30) | new policy sha |

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
