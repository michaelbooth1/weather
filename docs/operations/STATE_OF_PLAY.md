# State of play

**Last updated: 2026-10-21 02:16 America/Toronto (LFC backlogged; model-edge programme approved, decision 12-21;
Python C 10-21/22 on the pre-N12 master with owner GO; N12 10-22/23; owner 10-18 to 10-20 decisions are DL rows).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27 and 2026-10-19)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows, and now
the focus: find out fairly and fast whether the model can develop an edge over market prices (owner 10-19). **B. An informed,
domain-neutral market maker**; if the model shows no edge after every option is exhausted, the maker work may move to YouTube
views (owner 10-19). Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **Live trading paused** (owner 09-25); **LFC campaign backlogged** (owner 10-19): no t24, no sessions; no agent places,
  cancels or signs orders.
- Capture host: heavy work 00:30-09:00 under the lease ([host load policy](HOST_LOAD_POLICY.md)); roll-sensitive merges
  01:00-04:00; roll-free 00:30-09:00; docs-only by the light path before 12:00; never 12:00-00:30.
- 88a changes follow the host roll verdict like any other code. Owner decisions since 09-30 are rows in [DECISION_LOG](DECISION_LOG.md).
- **Testing (owner 10-04, PR #205):** focused + affected tests, PR CI (Windows lane #262 on 3.11.0) as full-suite evidence;
  every night head pre-gated on its stacked base; host-only behaviour needs a host run.
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md));
  relayed owner approvals bind it for serving-model and merges, never money or credentials; credentials never committed.
- **Workstation tracks** (owner 10-19): the model-edge programme first (harness v3, development screens, EDGE-1 drafts,
  retrain sizing memo by 11-06); YouTube-maker scoping in parallel, documents only. Testing-side work is parked on its branches.
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** read `origin/master` with git. N12 (`claude/integration-20261019-chain-r3` `739c03eff`, which
  carries the #190 parser v2 refresh `1f8c2f2c1`) lands the night 10-22/23, after C (DL 10-20).
- **Forward maker shadow ACTIVE** (`WeatherMakerShadowRunner`, 24/7, 12 bands, paper only); stop only with
  `data\maker_shadow\STOP`. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13 (end stays 11-13: #263 N_req 706, DL 10-14).
  **Descriptive reads of 10-16..11-13 are refused everywhere until the panel closes** (owner 10-17).
- **Journal pin:** `WeatherManualOrderJournal` pins five files incl. `wallet_reader_client.py`; a merge touching one makes it
  exit 3 until re-registered ([runbook](manual-order-journal.md)).
- **Wallet reader (8765)** on `a1014edab` (any-LAN code) since 10-13; serial ([wallet reader](wallet-reader.md)).
- **Host Python:** Phase B PASS 10-16 (qualified tip `90b2e1844`, an ancestor of master; roll verdict ROLL-FREE); venv
  still 3.11.0. **C runs 10-21 into 10-22 on the pre-N12 master** with the owner's GO in chat that night; B-R is
  cancelled (DL 10-20). The C night is exclusive. A 10-22 capture gap counts for MG-1 only by MG-1's own rule; a failed §R waits for the
  04:15 restore and the owner in the morning (DL 10-19). ([runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md))
- **Unregistered until C passes:** `WeatherMakerEvidenceLowestTemperature`, `WeatherEvidenceHost` (S4, owner yes 10-16),
  U6 replay-bundle export (owner yes 10-15); the 88a S2+S9 restart also waits for C.
- **LFC:** session 0 ATTESTED 10-16; campaign backlogged 10-19 before session 1; pin `21cf1ed42` recorded, idle
  ([record](../research/live-fill-calibration-session0-record-2026-10-16.md)).
- **Build line** `codex/maker-replay-v2-build-20261003` = `1fd0c295f`; the export nightly stays unregistered.
- **Maker replay v2** (panel UTC 09-30..10-14 never read): spec v3.4 frozen oracle basis; handout r1 signed 10-12; parked
  with the testing backlog; lapse 10-30 (owner 10-15) stands unless the owner re-dates it.
- **Model-edge programme** (owner 10-19, DL): harness v3 `claude/harness-v3-20261019` (controls pass on dev dates); dates
  <= 09-29 are development only (inputs copied to the workstation, owner 10-20); fair verdicts use new settled dates. Lever 2:
  the pipeline scoreboard cannot give per-block R, so harness v3 answers it after 11-13 (no new lane, no Stage B). EDGE-1
  drafts `claude/edge1-prereg-drafts-20261019` for owner sign-off Fri 10-23; **Gate 1 early no-go 12-07, primary 12-21,
  overturn-only 2027-01-25.** Code check: no NBM value reaches the served bands; the NWS hourly point forecast does; on the HGB path the intraday tail and METAR live signal never act (EF §10u).
- **Model windows:** MG-1 `b044e0f1` scored >= 10-15, BOUND D0 10-15, provisional last 11-28 (owner 10-16). t3-r3 13-16
  prereg SIGNED 10-16. Evening-fix scorer read 10-29 `--no-market`. SOURCE_DISAGREEMENT Option 1 (SD-1 `ecec210c2`) and the
  MG-1 bound (`e342baca1`) land night 10-23/24 after N12, MG-1 bound first, under a roll verdict (owner 10-16; DL 10-20). **DST:** OD30 holds 11-01, lapses 11-02.
- **No-go bar:** [exhaustion register](EXHAUSTION_REGISTER.md) (10-14; the owner keeps the no-go). Stratum-C and Aug-Sep gap numbers are tainted.
- **Live seals** must be RESEALED before any sealed-lane attempt (#229). **Pinned:** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`), exam U6 `89618c30`.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Model-edge programme:** bundle-B fixed tip Thu 10-22 -> delta review -> owner sign-off Fri 10-23; EDGE-1 D0 10-25 if
   N12 lands by 10-24, else 10-28; lever-5 Toronto host replay done 10-21; the other 11 markets and lever 6 on the workstation.
2. **Host Python:** C 10-21/22 (owner GO); then N12 10-22/23, MG-1 bound + SD-1 10-23/24, the waiting registrations and the 88a restart.
3. **YouTube-maker scoping** (documents only): owner actions O1-O5 in the 10-23 bundle.
4. **Item 337:** host no-METAR replay after C; on PASS flip, bump, quiet window (owner yes).
5. **Data layer v2:** [plan](DATA_LAYER_V2_PLAN.md); S2+S9+P1 and S4 re-dated after C.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| RF policy A (owner 10-15): roll-free heads land on workstation pre-gate + Windows CI once #274, #276/#284 green; then #209 deselect build | T4; workstation | after C | DL row; lane green |
| Evening-fix scorer `8cdcb62ec` lands (prereg SIGNED 10-13, sha256 in DL; read 10-29 `--no-market`, item 337 owns it) | T3 | 10-28 | scorer on master |
| Pinned watchdog redeploy from master, re-register only the watchdog task (owner yes 10-15) | production | after C, by 10-28 | watchdog CURRENT |
| U6 replay-bundle export registered 04:10 from the 3.11.9 build-line tip (owner yes 10-15) | production | first night after C PASS (earliest 10-23 04:10) | task registered; first receipt |
| 91a policy renewal unchanged (owner A 10-15; CP-5 LZX later, own change) | production | ~10-27 (expires 10-30) | new policy sha |
| Owner bundle B (EDGE-1 prereg, OD rulings, YouTube O1-O5) | production -> owner | Fri 10-23 | DL rows |

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic. Capture-host
  heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
