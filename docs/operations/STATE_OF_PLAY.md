# State of play

**Last updated: 2026-10-08 20:21 America/Toronto (OD23 signed and 20:21 shadow answers recorded; ALL LIVE TRADING PAUSED; N2 landed RS1b and RF2e; 91a re-pinned to 06:50; B replay needs an owner judgement on 3 rows; C3 not run 10-08, fallback 10-09; owner decisions 10-07 afternoon recorded).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows. **B. An
informed, domain-neutral market maker** (weather first, YouTube views next) that widens, pulls and — only where evidence
supports it — takes a side. Going in blind is ruled out. Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **No live trading (owner 2026-09-25).** The owner starts any future live run personally. The pause and bleed limit are a
  fail-closed guard (#180, landed 10-08); with today's shared wallet it would HALT, so a live run first needs a complete
  ledger (a dedicated wallet). Owner trades stay `owner-discretionary`.
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)). Merges: roll-sensitive
  01:00-04:00 only; roll-free 00:30-09:00 (the lease refuses later); docs-only by the light path before 12:00; never 12:00-00:30.
- **Merge freeze lifted 2026-10-03, except 88a** (owner reading 10-07): the bytes of `maker_evidence_capture.py`,
  `maker_evidence_store.py` and the 88a schema record, and 88a capture behaviour (#118, #172, #177, stacked #182), wait until
  after 2026-10-14. Shared schema-registry record additions are not frozen.
- Owner decisions 2026-09-30..10-07 are rows in [DECISION_LOG](DECISION_LOG.md).
- **Testing (owner 10-04, PR #205):** focused + affected tests with PR CI as full-suite evidence once the Windows CI lane (#209)
  covers them; workstation focused runs (<= 25 files, no `serial`) are lease-exempt, full suites queue (#213).
- **Workstation: one Claude Code chat directed by the production agent** (owner 10-03; [preamble](WORKSTATION_SESSION_PREAMBLE.md)).
  Owner approvals relayed by the production agent bind it for serving-model and merge decisions, never for money or
  credentials (owner 10-06). Claude Code has no host-load hook (S4U guard only). Production-host resets in the 30 days to
  10-07 were all the owner's own manual resets, not system faults (owner 10-07).

## Current truth

- **Production source:** `master` = `origin/master` `6e5ff479`. N2 10-08: RS1b `1becbaf7` (pf2 #232 + git-version fix, #192
  with #180, cold-snapshot test time-bomb fix); RF2e `6e5ff479` (#236, #241, rf110 #105/#125/#121, #252, #251 with #249, #250,
  workstation pre-gate, #247, `wu_token_scan_v1` schema). Capture recovered after both rolls.
- **Shadow scoring embargo** (landed with #192): `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13; lifting it
  is a reviewed code change.
- **Live seals:** #229 landed with #230, so every existing live seal must be RESEALED before any live attempt.
- **Model, evening (EF §10q):** #191 lockin-anchor-v3 LIVE since 10-06 01:43. **Next serving change (owner 10-06, B):** lockin-anchor-v4 (#246 `91bf0786` on #189 `5e03609e`), `ML_MODEL_VERSION`
  v0.5.11 -> v0.5.12. **Replay 10-08 on scratch `77714748` (08-25..09-29):** clean run (no write outside its out-dir, no
  foreign module); floor check and floor invariant PASS; the literal zero-below-anchor rule fails on 3 of 75,796 rows
  (06-09: 2 rows, max 0.0096; 13-16: 1 row, max 0.0100; other blocks 0). The owner's landing condition was 0 in every block,
  so B does not land until the owner judges these rows.
- **Model, morning:** MG-1 SIGNED at `b044e0f1`; needs parser v2 #190; dates >= 10-15; D0 stage Q1-Q3 yes (owner 10-08, item 190).
- **Maker replay v2** (PR #176; panel UTC 09-30..10-14 never read): gate spec v3.4 ACCEPTED (owner 10-07) as the frozen basis
  for the independent oracle. **OD18:** the oracle is written by a fresh agent the production agent starts on this host, from
  a filtered standalone handout (one parentless commit, no remotes; exclusions recorded and hashed). Signature when the
  gates pass (~10-18..20); look by 11-15.
- **C3 console rehearsal:** approved for 10-08 09:00 (Q2 yes, Q1 keep, post-landing-night deviation accepted; the two
  runtime-refreshed config files may be dirty, hashes recorded). All 08:50 gates were GO but the console was not opened;
  files stay staged in `C:\c3` for the 10-09 fallback, which also needs 91a's first 06:50 run ended by 09:05.
- **Settlement:** WRH "Hourly Data" rows (US), WRH Temp column (foreign), floor of the HKO daily maximum (Hong Kong). EF §10c.
- **Pinned deployments (detached, locked worktrees):** `weather-watchdog-deployed-110n-1fc7ba35`,
  `weather-manual-order-journal-deployed-ebe72984`, `weather-cold-snapshot-deployed-6e5ff47` (91a from 10-09),
  `weather-cold-snapshot-deployed-979c0e7` (removed after the first 06:50 PASS), `weather-exam-deployed-664c894`.
- **Disk / 91a:** 10-08 00:30 PASS, 20.4 GB reclaimed. Re-pinned 10-08 (#238): 06:50-09:00, PT2H20M, first run 10-09 06:50
  ([runbook](cold-snapshot-compression.md)). Check `scratch\cold_snapshot_compression\nightly-<date>-*\wrapper-result.json`
  each morning. Policy expires 10-30 (renewal week of 10-26 is an owner act). `WeatherReplayBundleExportNightly` stays
  unregistered until at least 10-16.
- **88a retention hold:** keep 88a data for UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2:** W1/W2/F3 kernel fixes; W6-W8; oracle handout cut (~10-09/10) then the fresh oracle author; P1-P4 on
   calibration dates only; gates; signature ~10-18..20 (OD25: a miss slips it). Shadow parity counted from engine freeze.
2. **Merges, N3 (10-09):** #127 (option A); #259 before `045a8447e`; #255 fold; #258; SWOB `876ac224f`; H1 cut script; U6
   `b88f5565`; #247 follow-up. Then #189 + #246 (after the B judgement); #153 (Stage B disabled); #190 -> #210; #196;
   #161 -> #162 -> #160; #152 + #173; #163; #142; after 10-14 #118, #172 + #182, #177; M4 merge-tool change 10-11/12.
3. **Measurements (09-29 only; never 88a 09-30..10-14):** #173, #177 reports; desk-study power rule (if N_req <= 14 the
   embargo end moves 11-13 -> 10-31 by dated clarification). **Research:** NBS/NBH probe; T+1/T+2 NWP timing.
4. **Live:** prerequisites in parallel now (wallet funding and Credential Manager setup stay owner acts); not before the v2
   look and >= 7 days of shadow agreeing with replay.

## Owner decisions 2026-10-07/08 (rows in DECISION_LOG)

- 10-07 lists approved (OD18 host agent; OD21 DEFERRED; STQ PARKED; shortcuts; #127 A; v3.4; C3). 10-08 20:21: OD23 SIGNED
  re-worded (`decide()` mid keeps own size; diagnostic built); shadow hazard 0.001 to freeze; Q2 (a) horizon clause; parity:
  v0.2 raw tape, fills/cash/sizes/reasons reported only, embargo PR. **Open:** B replay judgement; C3 day; OD21; STQ R1-R6, release/:52.

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, `TEMP`/`TMP` inside a cleaned root. Long agent jobs run detached, not as tool background calls.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory. Stay Python; native code only by the efficiency-audit decision rule.
  Approved workstation work is never parked as low priority; production hands out the next item whenever a session frees.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
