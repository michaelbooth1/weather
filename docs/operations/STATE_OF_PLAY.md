# State of play

**Last updated: 2026-10-03 01:00 America/Toronto (ALL LIVE TRADING PAUSED; exam tree W2 pinned 664c8943; replay cost explodes with band count - A/A'/B decision pending real density; 91a nightly running; ~102 GiB free).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows. **B. An
informed, domain-neutral market maker** (weather first, YouTube views next) that widens, pulls and — only where evidence
supports it — takes a side. Going in blind is ruled out. Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **No live trading (owner 2026-09-25).** The owner starts any future live run personally; pause and bleed limit go into code
  first. The owner's manual trades share the wallet and stay `owner-discretionary`, outside automated data.
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)). Merges: roll-sensitive
  01:00-04:00 only; roll-free 00:30-12:00; docs-only by the light path before 12:00; never 12:00-00:30.
- **Exam-period merge policy (2026-09-27):** during panel UTC days 09-30..10-13 only disk-relief and exam-tooling
  roll-sensitive merges land; everything else waits until after 10-13. Nothing joins an integration branch before its CI is green.
- 2026-09-30, 2026-10-01 and 2026-10-02 owner decisions (swarm items; Clarifications 2 and 3 signed; tail-fix option A; desk-study
  Clarification 1; review items; T+1/T+2 options A and C) are rows in [DECISION_LOG](DECISION_LOG.md).
- **Workstation sessions are Claude Code** (Codex lapsed 2026-09-29); dispatch prompts start from
  [the session preamble](WORKSTATION_SESSION_PREAMBLE.md). Claude Code has no host-load hook; the S4U guard is its backstop.

## Current truth

- **Production source:** `master` = `origin/master`; last code integration `979c0e752` (2026-10-01 01:38, #147 + #148); later
  merges are docs-only light paths.
- **Exam code tree (pinned):** `origin/codex/integration-exam-20261002` `664c8943` (CI green) = W2 #164 (trade-clock bound,
  Clarification 3 hash pinned, reward-terms skip, caps, MemoryError receipts, pre-reservation pull count) + T+1 Amendment 3.
  Locked worktree `weather-exam-deployed-664c894`; exporter module hash `ce682825…`. Every exam bundle comes from this tree.
- **Plugin bar PASS (10-02, 09-26 data, `data/alerts/weather-plugin-111k-20260926-r2/`):** status COMPLETE; lead-1 end to end
  8,710; identity mismatch 0, unverified 0; complete mass over the captured band set on 2,504 of 3,276 lead-1 records
  (all-band 0: 88a books selected bands only, by design). No knot refusals; tied reads carry their own model ids. One
  T+1 fair value recomputed by hand from its knots matched to four decimals.
- **Replay cost (workstation, synthetic fixtures; #166, #168, #175):** one 12-band date peaks ~2.5 GiB / 373 s; cost grows
  ~quadratically with the daily band union (engine construction, not the signed text); at ~120 bands one date needs >= 7.5 h
  and ~31.5 GiB of report. Streaming alone fits only to ~14 bands. Real per-date band union is measured from the calibration
  bundles (bundle.json only) before any decision; NO rehearsal or derive_ceilings on the capture host until then.
- **Exam roots:** data `data\`; calibration `scratch\maker-replay-exam-c2b\calibration-<UTC stamp>` per attempt (the 09-29
  attempt in `...-c2` is spent); panel `scratch\maker-replay-panel`.
- **Pinned deployments (detached, locked worktrees):** watchdog `weather-watchdog-deployed-110n-1fc7ba35`; order journal
  `weather-manual-order-journal-deployed-ebe72984`; cold-snapshot nightly `weather-cold-snapshot-deployed-979c0e7`; exam tree above.
- **Disk:** first real 91a nightly 10-02 PASS: 19.9 GiB reclaimed in 73 min, no deletes; free ~117 GiB. A FAILED night blocks
  later nights until resolved: check `scratch\cold_snapshot_compression\nightly-<date>-*\wrapper-result.json` each morning.
  Policy expires 10-30 (owner renewal ~10-27). On a night with a 00:30 suite, disable the nightly first.
- **88a retention hold:** keep 88a data for UTC 10-15..10-30 for the desk-study decision panel (pre-registration `574f8369b`,
  Clarification 1 `67e44273`); compression is lossless and allowed.
- **Learning lane:** Stage B (`WeatherEveningEvidenceRefresh`) disabled since 2026-08-13; its runtime is unmeasured (the
  08-13 record is the out-of-memory run). #153 (06:45 trigger) does not land before the look: the 06:41-09:00 slot is the
  exam's.
- **Host incidents:** unclean power losses 2026-09-29 ~19:50 and 2026-09-30 14:05 (the second may have been a hang;
  ProtonVPN was the last service to fail). Owner decision pending: ProtonVPN on the capture host, crash dumps.
- **Settlement source:** venue resolves on weather.gov WRH hourly data; master hard-codes WU; agreement 359/360 (EF §10c).
- **Replay exam:** calibration 09-27..29, panel 09-30..10-13, settlement 10-14; look on any Toronto date 10-15..10-31 while
  no attempt is reserved. Authorization goes v1 -> **v3** (five signed hashes; v2 never written).
- **Expansion swarm (2026-10-01/02):** disk, not CPU/RAM, binds; cheapest expansion is lowest-temperature markets for our 12
  cities, then six foreign highest-temperature cities, then YouTube views; see
  [audits/swarm-expansion-2026-10-01.md](../roadmap/audits/swarm-expansion-2026-10-01.md).

## Ordered critical path

1. **Exam:** real band density from calibration bundles -> owner A / A' (prospective Clarification 4: trajectory-identical
   engine + compact report; go/no-go 10-12) / B (close NOT EXECUTED, panel unread) -> then rehearsal off the capture host,
   panel exports, v4 rows, build/verify, look by 10-31. Open: the 10-15 T+1 read would read panel-date settlements.
2. **Disk:** watch nightly 91a receipts; #142 after the exam if needed.
3. **Post-exam batch (after 10-13):** roll-free set (#141 first, #155, #154, #150, #151, #128, #146), then #118/#119/#117,
   #152, #153 and the 88a rewards-trigger efficiency.
4. **Research:** desk-study pilot export (owner scp); 111h extract; NBS/NBH probe after 111h; lowest-temperature desk study.

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, `TEMP`/`TMP` inside a cleaned root. Long agent jobs run detached, not as tool background calls.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory. Languages: stay Python; native code only by the efficiency-audit decision rule.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
