# State of play

**Last updated: 2026-10-23 America/Toronto (owner: more-markets phase 2 plan and decisions 1-8 approved; C night 10-23/24;
N12+N13+Stage-A fix 10-24/25; EDGE-1 D0 10-28 AT RISK, under amendments (s)/(s-C), pending the owner).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27 and 2026-10-19)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows, and now the focus:
find out fairly and fast whether the model can develop an edge over market prices (owner 10-19). **B. An informed, domain-neutral market
maker**; if the model shows no edge after every option is exhausted, the maker work may move to YouTube views (owner 10-19). Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **Live trading paused** (owner 09-25); **LFC campaign backlogged** (owner 10-19): no t24, no sessions; no agent places, cancels or signs orders.
- Capture host: heavy work 00:30-09:00 under the lease ([host load policy](HOST_LOAD_POLICY.md)); roll-sensitive merges
  01:00-04:00; roll-free 00:30-09:00; docs-only by the light path before 12:00; never 12:00-00:30.
- 88a changes follow the host roll verdict like any other code. Owner decisions since 09-30 are rows in [DECISION_LOG](DECISION_LOG.md).
- **Testing (owner 10-04, PR #205):** focused + affected tests, PR CI (Windows lane #262 on 3.11.0) as full-suite evidence; every night head pre-gated on its stacked base; host-only behaviour needs a host run.
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md));
  relayed owner approvals bind it for serving-model and merges, never money or credentials; credentials never committed.
- **Workstation tracks** (owner 10-19): the model-edge programme first (harness v3, development screens, EDGE-1 drafts,
  retrain sizing memo by 11-06; bundle B decided 10-21); YouTube-maker scoping in parallel, documents only. Testing-side work is parked on its branches.
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** read `origin/master` with git. N12 (`739c03eff`, #190 parser v2 `1f8c2f2c1`) did NOT merge 10-22/23:
  the host suite failed on a pyarrow 24 hive-partition test read (test fix `aeae6e0fa`). N12 and N13 (each with that fix) plus the Stage-A fix head land 10-24/25, after the host bounded suite.
- **Forward maker shadow ACTIVE** (`WeatherMakerShadowRunner`, 24/7, 12 bands, paper only); stop only with
  `data\maker_shadow\STOP`. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13 (end stays 11-13: #263 N_req 706, DL 10-14).
  **Descriptive reads of 10-16..11-13 are refused everywhere until the panel closes** (owner 10-17).
- **Journal pin:** `WeatherManualOrderJournal` pins five files incl. `wallet_reader_client.py`; a merge touching one exits 3 until re-registered ([runbook](manual-order-journal.md)).
- **Wallet reader (8765)** on `a1014edab` (any-LAN code) since 10-13; serial ([wallet reader](wallet-reader.md)).
- **Host Python:** Phase B PASS 10-16 (qualified tip `90b2e1844`, an ancestor of master; roll verdict ROLL-FREE); venv
  still 3.11.0; C 10-21/22 NO-GO at C2, nothing swapped. **C GO night 10-23/24 (owner 10-22, DL):** start 00:30; up to 2
  same-night retries until 03:30 only for failures before C3 (zero capture gap); a failure after the swap undoes itself and
  waits for the owner. Runbook on master (`5bbdd4280`), kit `claude/night-plans-pyup-c-next-20261022`. ([runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md))
- **Unregistered until C passes:** `WeatherMakerEvidenceLowestTemperature`, `WeatherEvidenceHost` (S4, owner yes 10-16),
  U6 replay-bundle export (owner yes 10-15). S2+S9 lands 10-25/26 from `17439f7c8`; the C night now precedes it, so its 88a restart is the night after (10-26/27) via the restart script (never re-register).
- **LFC:** session 0 ATTESTED 10-16; backlogged 10-19; pin `21cf1ed42` idle ([record](../research/live-fill-calibration-session0-record-2026-10-16.md)).
  **Maker replay v2** (panel 09-30..10-14 never read): spec v3.4, handout r1 signed 10-12, parked, lapse 10-30; build line `1fd0c295f`, export unregistered.
- **More markets phase 2** (owner 10-23, DL; [study](../research/more-markets-phase2-scoping-2026-10-23.md)): R1 five pilot cities after S2+S9 day-3
  receipts; R2 five more recorder-only from 11-01 (HK stays recorder-only); M1 model lane M = 18, Europe first, built on the workstation, lands
  no earlier than 12-21; M = 24 only once offboarding is proven. New METAR-settled cities label from IEM METAR; built-ins stay WU pending the
  METAR-vs-WU study. Offboarding goes to the cold Drive with hash-verify, never delete; the owner sees the list first.
- **Model-edge programme** (owner 10-19): harness v3 (`claude/harness-v3-20261019`); dates <= 09-29 are development only.
  **Bundle B decided 10-21, every default** (DL; questions as listed at `d138c3c54`): absent arms neither block nor satisfy NO-GO; Gate 1
  folds into 12-21 (H-A0, H-A1 UNTESTABLE), so NO-GO rests on MG-1; T1 = NWS hourly; E3 UNTESTABLE; retrain waived for
  12-21 (best case futility-only R0 from 11-17), its reservation narrow ([RCW](reserved-confirmation-window.md)). **12-21
  primary, overturn-only 2027-01-25.** Dev replay base is current code, not served (EF §10v); NBM reaches no band (EF §10u).
- **Model windows:** MG-1 `b044e0f1` scored >= 10-15, BOUND D0 10-15, provisional last 11-28 (owner 10-16). t3-r3 13-16
  prereg SIGNED 10-16. Evening-fix scorer read 10-29 `--no-market`. SOURCE_DISAGREEMENT Option 1 (SD-1 `ecec210c2`) and the
  MG-1 bound (`e342baca1`) land in N13 (`d04fe82fc`) night 10-24/25, MG-1 bound first, under a roll verdict (DL 10-20, 10-22). **DST:** OD30 holds 11-01, lapses 11-02.
- **No-go bar:** [exhaustion register](EXHAUSTION_REGISTER.md) (10-14; the owner keeps the no-go). Stratum-C and Aug-Sep gap numbers are tainted.
- **Live seals** must be RESEALED before any sealed-lane attempt (#229). **Pinned:** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`), exam U6 `89618c30`.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Model-edge programme:** EDGE-1 D0 10-28, AT RISK (N13 serves after the 10-24 clock; DL 10-22); signed bundle-B copies before D0;
   retrain column-allowlist head (build 10-27, land 10-30); Open-Meteo Previous Runs fetch (owner yes); lever 6 on the workstation.
2. **Host nights:** C 10-23/24; N12 + N13 (MG-1 bound + SD-1 + DST label fix, EF §10w; deferred past 12-21 if that chain fails) + Stage-A fix 10-24/25, after the host bounded suite; S2+S9 10-25/26; 88a restart 10-26/27; then the waiting registrations.
3. **YouTube-maker scoping** (documents only): owner actions O1-O5 in the 10-23 bundle.
4. **Item 337:** host no-METAR replay after C; on PASS flip, bump, quiet window (owner yes).
5. **Data layer v2:** [plan](DATA_LAYER_V2_PLAN.md); S2+S9 10-25/26; P1 and S4 re-dated after C.
6. **More markets (workstation):** METAR-vs-WU agreement study; offboarding plan (owner sees the list); then M1; R1 after S2+S9 day 3.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| RF policy A (owner 10-15): roll-free heads land on workstation pre-gate + Windows CI once #274, #276/#284 green; then #209 deselect build | T4; workstation | after C | DL row; lane green |
| Evening-fix scorer `8cdcb62ec` lands (prereg SIGNED 10-13, sha256 in DL; read 10-29 `--no-market`, item 337 owns it) | T3 | 10-28 | scorer on master |
| Pinned watchdog redeploy from master, re-register only the watchdog task (owner yes 10-15) | production | after C, by 10-28 | watchdog CURRENT |
| U6 replay-bundle export registered 04:10 from the 3.11.9 build-line tip (owner yes 10-15) | production | first night after C PASS (earliest 10-25 04:10) | task registered; first receipt |
| 91a policy renewal unchanged (owner A 10-15; CP-5 LZX later, own change) | production | ~10-27 (expires 10-30) | new policy sha |
| Signed bundle-B copies (GNG, EDGE-1 and methods annexes) land with their signing rows, after the Fable delta | production; workstation | before D0 | DL signing rows |
| Retrain column allowlist head `claude/retrain-column-allowlist-20261021` (bundle-B prerequisite; R0 drops pressure, base models only, DL 10-21) | workstation | build 10-27, land 10-30 | roll verdict; on master |
| Open-Meteo Previous Runs fetch 2021-2023 Oct-Dec US11 (owner yes 10-21, (j)) under `workstation_heavy.ps1` | workstation | before R0 11-17 | corpus in `data/training/pit_forecast_corpus/` |

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic. Capture-host
  heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
