# State of play

**Last updated: 2026-10-07 09:00 America/Toronto (ALL LIVE TRADING PAUSED; N1 landed #207, RF #238/#120/#204 and #230; pf2 held on one host-suite failure; lockin-anchor-v3 first live evening passed; reboot capture gap 10-06 23:24-23:36; owner approved the 10-07 morning list).**
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
  fail-closed guard (#180, unmerged); with today's shared wallet it would HALT, so a live run first needs a complete ledger
  (a dedicated wallet). Owner trades stay `owner-discretionary`.
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)). Merges: roll-sensitive
  01:00-04:00 only; roll-free 00:30-09:00 (the lease refuses later); docs-only by the light path before 12:00; never 12:00-00:30.
- **Merge freeze lifted 2026-10-03, except 88a:** changes to 88a capture code or behaviour (#118, #172, #177, stacked #182)
  wait until after 2026-10-14 so the unread panel is captured by one 88a code version.
- Owner decisions 2026-09-30..10-07 are rows in [DECISION_LOG](DECISION_LOG.md). 10-06: L5 (host load policy rule 9); Swarm M
  full size; #180 + #192 land once landable (usual gates); B (below); OD15 (scraped public WU apiKey token acceptable, kept out
  of logs, tapes and commits; [domain context](AGENT_CONTEXT.md)); relayed approvals. 10-07: the morning list (below).
- **Testing (owner 10-04, PR #205):** focused + affected tests with PR CI as full-suite evidence once the Windows CI lane (#209)
  covers them; workstation focused runs (<= 25 files, no `serial`) are lease-exempt, full suites queue (#213).
- **Workstation: one Claude Code chat directed by the production agent** (owner 10-03; [preamble](WORKSTATION_SESSION_PREAMBLE.md)).
  Owner approvals relayed by the production agent bind it for serving-model and merge decisions, never for money or
  credentials (owner 10-06). The cloud agent is retired (owner 10-06). Claude Code has no host-load hook (S4U guard only).

## Current truth

- **Production source:** `master` = `origin/master` `8969a514`. N1 10-07: #207 `522ddfbe`; RF #238 + #120 + #204 `99a399c2`;
  #230 (#228 + #229 live-launcher stdin) `eefbb3df`; morning light paths #239 `16f45bf6` and RE-1 fill-count docs.
- **pf2 head `4949296` NOT landed:** one host-suite failure, `tests/operations/test_landing_preflight.py::`
  `test_whitespace_only_true_for_37_trailing_blank_line_deletions` (suspected host Git line-ending config); workstation fixing.
- **Live seals:** #229 landed with #230, so every existing live seal must be RESEALED before any live attempt.
- **Model, evening (EF §10q):** #191 lockin-anchor-v3 LIVE since 10-06 01:43; first live evening 10-06 passed in all 12
  markets (floor active, no mass below the anchor).
- **Next serving change (owner 10-06, B):** lockin-anchor-v4 (same-day METAR floor before lock-in; #246 `91bf0786` on #189
  `5e03609e`) and `ML_MODEL_VERSION` v0.5.11 -> v0.5.12. ROLL-SENSITIVE; lands with #189 in a quiet window only after the
  10-07 replay on scratch `77714748` shows 0 below-anchor mass in every hour block; its calibration paragraph goes in the record.
- **Capture gap 10-06:** unclean reboot ~23:24, capture down to 23:36 (~12 min, near-close window); self-recovered, 0 torn jsonl.
- **Model, morning:** MG-1 (captured NBM v2 guidance read) SIGNED 2026-10-04T16:10Z at `b044e0f1`; narrow reservation; needs
  parser v2 (#190) landed; scored on new dates >= 10-15. 111h closed (EF §10p); the morning lead (§10h/§10j) stands.
- **Maker replay v2** (PR #176; succeeds exam `maker-replay-2026-10-15`, closed NOT EXECUTED 10-03, panel UTC 09-30..10-14
  never read, [plan B audit](../roadmap/audits/exam-plan-b-2026-10-03.md)): T+1/T+2 bands, v0.2 bundles, workstation rehearsal
  and look, gates from calibration-only rehearsals before signature; build `codex/maker-replay-v2-build-20261003`; signature by
  10-23, look by 11-15. Capture-host exports only within the nightly wrapper (2 GiB, 2,700 s) until S2/P1 decides.
- **Settlement:** WRH "Hourly Data" rows (US), WRH Temp column (foreign), floor of the HKO daily maximum (Hong Kong). EF §10c.
- **Pinned deployments (detached, locked worktrees):** `weather-watchdog-deployed-110n-1fc7ba35`,
  `weather-manual-order-journal-deployed-ebe72984`, `weather-cold-snapshot-deployed-979c0e7`, `weather-exam-deployed-664c894`.
- **Disk / 91a:** the nightly failed 4 of 5 nights (10-03, 10-04, 10-06, 10-07). 10-07: `FAILED_RETAIN_AND_INSPECT` on
  capture admission (`capture_unhealthy:snapshot` at 00:34), resolved by `cold_snapshot_nightly_resolution` (no unfinished
  file). #238 (06:50-09:00 move, read retries) landed in `99a399c2`; it applies after a production re-pin and re-registration.
  Check `scratch\cold_snapshot_compression\nightly-<date>-*\wrapper-result.json` each morning. Policy expires 10-30.
- **88a retention hold:** keep 88a data for UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2:** W2-W5 built (rules 1 and 4 = B); W6-W8; P1-P4 on calibration dates only; gates; signature by 10-23.
   **Swarm M** (owner 10-06; 4 Fable + ~18 Opus + Defenders): v2 signature-ready, shadow-ready (#180/#192, shadow-vs-replay
   gate, C3 rehearsal script), safe-to-quote map on already-read dates only.
2. **Merges:** pf2 `4949296` (test fix); #189 + #246 (after the replay); #180, #192; RF #153; #105 + #125 + #121; #190 -> #210;
   #196; #161 -> #162 -> #160; #152 + #173; #163; #142; after 10-14 #118, #172 + #182, #177; M4 merge-tool change 10-11/12.
3. **Measurements (09-29 only; never 88a 09-30..10-14):** #173, #177 reports. **Research:** NBS/NBH probe; T+1/T+2 NWP timing.
4. **Live:** not before the v2 look and >= 7 days of shadow agreeing with replay.

## Owner decisions 2026-10-07 (morning list approved as recommended; detail in DECISION_LOG)

- Engine, before signature: fix W1, W2, F3 with disclosure and re-run attribution; a miss slips the signature (OD25); OD23 no
  change; U1-Q1/U1-MF5 refuse; O9 transfer by 10-13; clock fix + SWOB as one unit before 10-23 (Q2/N4, OD36, OD37 drop "HH:MM").
- MG-1: OD3/OD31/OD32 in [the reservation](reserved-confirmation-window.md); Q14/OD17 parse-and-discard is not a read; STQ
  is exploratory (T+0 only, no rule). WU history stays OFF until the token redaction lands (OD24); OD27 read-only host scan.
- Ops: [host load policy](HOST_LOAD_POLICY.md) rule 10 (tiering hole, RF settle 60 s, DST); OD29 #189 + #196 by 10-31;
  OD33-OD35 workstation commit ceiling ~90%, pre-gate by 21:30 with receipts, PASS bound to the night's base SHA.
- **Still open:** OD21 (live-executor unit/owner), C3 rehearsal day, OD11, STQ R1-R6 family and release/:52 windows, U6 merge
  of `b88f5565` into the build line.

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
