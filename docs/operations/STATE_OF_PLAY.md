# State of play

**Last updated: 2026-10-24 America/Toronto (owner hard directive: model improvement only, then a real edge test, kill the project
if it fails; EDGE-1 postponed; paid data per source; C night 10-23/24; N12+N13+Stage-A 10-24/25).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner hard directive, 2026-10-23; supersedes 09-23..10-19)

Precondition: protect capture and settlement evidence. **The goal is model improvement only, "whatever it takes"**: do all we can,
then run a real edge test against market prices; **if it fails, the project is killed** (owner 10-23, DL). Maker, market-making,
88a development, bundle B, the plugin core and the YouTube-maker scoping are **paused**.

## Current authority

- **Live trading paused** (owner 09-25); **LFC campaign backlogged** (owner 10-19): no t24, no sessions; no agent places, cancels or signs orders.
- Capture host: heavy work 00:30-09:00 under the lease ([host load policy](HOST_LOAD_POLICY.md)); roll-sensitive merges
  01:00-04:00; roll-free 00:30-09:00; docs-only by the light path before 12:00; never 12:00-00:30.
- Owner decisions since 09-30 are rows in [DECISION_LOG](DECISION_LOG.md). The code freeze tied to EDGE-1 is lifted; normal landing rules apply.
- **Weather data:** paid only per owner-approved source recorded in DECISION_LOG (owner 10-23), no agent purchases or sign-ups, credentials never in the repo;
  free official or reputable data (Open-Meteo, IEM, NOAA/NWS, ECMWF open data, DWD, universities) needs no ask (owner 10-24); ask for packages, unknown hosts, logins, payment or anything suspicious.
- **Testing (owner 10-04, PR #205):** focused + affected tests, PR CI (Windows lane #262 on 3.11.0) as full-suite evidence; every night head pre-gated on its stacked base; host-only behaviour needs a host run.
- **Workstation: one Claude Code chat directed by the production agent** ([preamble](WORKSTATION_SESSION_PREAMBLE.md));
  relayed owner approvals bind it for serving-model and merges, never money, credentials or risky downloads; credentials never committed.
  **Lanes run in parallel** (owner 10-23), one branch each; every landing goes through master-agent with a pre-gate receipt. **Keep it fully busy; Fable cautiously** (owner 10-24).
- **Landed is not running:** a new loop, nightly, scorer or task is done only when its Open-commitments verify has run.

## Current truth

- **Production source:** read `origin/master` with git. N12 (`739c03eff`, #190 parser v2 `1f8c2f2c1`) did NOT merge 10-22/23:
  the host suite failed on a pyarrow 24 hive-partition test read (test fix `aeae6e0fa`). Rebuilt heads on master `5bbdd4280`, pinned:
  N13 `12515e390`, Stage-A `8e40cd082`, S2+S9 `ac1c1abf9` (workstation pre-gates PASS on pyarrow 24.0.0).
- **Outcome embargo unchanged:** no outcome, price or label read after 09-29; it is the reserved window for the future edge test.
  Dates <= 09-29 are development only. **Descriptive reads of 10-16..11-13 stay refused** (owner 10-17).
- **Forward maker shadow ACTIVE** (`WeatherMakerShadowRunner`, 24/7, paper only; development paused); stop only with
  `data\maker_shadow\STOP`. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..11-13 (DL 10-14).
- **Journal pin:** `WeatherManualOrderJournal` pins five files incl. `wallet_reader_client.py`; a merge touching one exits 3 until re-registered ([runbook](manual-order-journal.md)).
- **Wallet reader (8765)** on `a1014edab` (any-LAN code) since 10-13; serial ([wallet reader](wallet-reader.md)).
- **Host Python:** Phase B PASS 10-16 (qualified tip `90b2e1844`); venv still 3.11.0. **C GO night 10-23/24 (owner 10-22, DL):**
  start 00:30; up to 2 same-night retries until 03:30 only before C3; a failure after the swap undoes itself and waits for the
  owner. Runbook on master (`5bbdd4280`), kit `claude/night-plans-pyup-c-next-20261022` ([runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md)).
- **Unregistered until C passes:** `WeatherMakerEvidenceLowestTemperature`, `WeatherEvidenceHost` (S4), U6 replay-bundle export.
  S2+S9 lands 10-25/26; its 88a restart is 10-26/27 via the restart script (never re-register).
- **Venue rule change (EF §10x):** from the 10-23 events the venue resolves on the raw METAR API, highest **routine** report
  (SPECI excluded), tenths °C half-up to °F, WU fallback; Denver names KDEN, not our KBKF. **Labels:** venue rule for dates
  >= 10-23 (owner 10-23); WU before, unless the host WU-vs-venue measurement (08-11..09-29, after C) says otherwise.
  **Denver >= 10-23 labels KDEN and is unsupported for model scoring** until a KDEN model passes the gates (DL; [study](../research/denver-kden-vs-kbkf-2026-10-23.md)).
- **More markets** (owner 10-23, DL; [study](../research/more-markets-phase2-scoping-2026-10-23.md)): R1 five pilot cities
  recorder-only the morning after S2+S9 lands (day-1 receipt if its checks pass); R2 five more from 11-01 (HK recorder-only);
  M1 model lane Europe first, M = 18 then 24 after offboarding is proven, lands when ready; new cities label from IEM METAR.
- **Offboarding:** plan on `claude/research-data-offboarding-plan-20261023` (`c7fb4b63e`; amend paused); cold Drive is unencrypted, hash-verify,
  never delete, the owner sees each list first; size survey on a host night after C. Never offload `.env`, cred or token files.
- **R0 rebuild** (owner 10-21, 10-23, DL): US 11, base models only, drop pressure, Miami drops consensus columns, 2024-25 fetch
  yes (retrain sizing memo at `5c845e282`, not yet on master). Dev replay base is current code, not served (EF §10v); NBM reaches no band (EF §10u).
- **EDGE-1 postponed** (owner 10-23): D0 10-28 no longer holds; bundle B paused; a new schedule comes with the edge-test redesign.
  MG-1 bound + SD-1 still land in N13; t3-r3 prereg SIGNED 10-16; evening-fix scorer read 10-29 `--no-market`.
- **No-go bar:** [exhaustion register](EXHAUSTION_REGISTER.md) (10-14; the owner keeps the no-go). Stratum-C and Aug-Sep gap numbers are tainted.
- **Live seals** must be RESEALED before any sealed-lane attempt (#229). **Pinned:** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`), exam U6 `89618c30`.
- **88a retention hold:** keep UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok. **DST:** OD30 holds 11-01.

## Ordered critical path

1. **Venue-rule labels** (top model priority) for training and evaluation from 10-23; Denver KDEN study feeds the station choice.
2. **Dev scorecard:** walk-forward model vs market vs settlement on dates <= 09-29; every model change is measured on it.
3. **New-city model lane M1** (Europe first) and **R0 rebuild**, both scored on the dev scorecard.
4. **Information gap:** free sources not yet used, and paid candidates with cost and a measure-before-buying plan (proposal only).
5. **Host nights:** C 10-23/24; N12 + N13 (MG-1 bound, SD-1, DST label fix) + Stage-A 10-24/25 after the host bounded suite;
   S2+S9 10-25/26; R1 recorder-only the next morning; 88a restart 10-26/27; then the waiting registrations.
6. **Item 337:** host no-METAR replay after C; on PASS flip, bump, quiet window (owner yes).

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| WU-vs-venue measurement 08-11..09-29 on the host (owner 10-23) | production | after C | research doc; DL row |
| Venue-rule label path, spec + code (owner 10-23) | workstation | before N+1 night after review | pre-gate receipt; on master |
| Evening-fix scorer `8cdcb62ec` lands (prereg SIGNED 10-13, sha256 in DL; read 10-29 `--no-market`, item 337 owns it) | T3 | 10-28 | scorer on master |
| Pinned watchdog redeploy from master, re-register only the watchdog task (owner yes 10-15) | production | after C, by 10-28 | watchdog CURRENT |
| U6 replay-bundle export registered 04:10 from the 3.11.9 build-line tip (owner yes 10-15) | production | first night after C PASS | task registered; first receipt |
| 91a policy renewal unchanged (owner A 10-15; CP-5 LZX later, own change) | production | ~10-27 (expires 10-30) | new policy sha |
| Workstation pre-gate refuses when the venv differs from the pinned requirements | workstation | after the label path | receipt shows pin check |

## Standing decisions

- International Polymarket only; paid weather sources only per owner-approved source; backups deprioritized; streak contiguity is
  a diagnostic. Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture; worktrees `GIT_LFS_SKIP_SMUDGE=1`.
- Native units, WU cutoffs, probability mass, train/serve parity, replay, release binding and evidence retention stay mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
