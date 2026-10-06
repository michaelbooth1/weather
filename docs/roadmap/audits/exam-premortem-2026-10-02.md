# Exam pre-mortem swarm — 2026-10-02

- **Owns:** the 25-agent read-only pre-mortem of the maker replay exam path (refusal hunt with adversarial verification, night calendar), post-exam landing plan, expansion and model groundwork.
- **Read when:** planning exam steps, post-exam merge nights, or the lowest-temperature / foreign-city / YouTube groundwork.
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)) or decisions in force ([DECISION_LOG](../../operations/DECISION_LOG.md)).

Read-only agents; no exam-blackout data read; numbers are MEASURED only where marked. Owner decisions are in DECISION_LOG.

## Synthesis

**Verdict:** The exam is schedulable (look 10-16, slack to 10-31) only if one more workstation round (W2, off `origin/codex/integration-exam-20261002` d6086f3c0, discard `claude/exam-fix-20261002`) lands before the first export on the 10-04 night and the owner signs a Clarification 4 for the `engine_event_cap` mismatch before the rehearsals; nothing in the exam chain can consume the look before reservation, and the two post-reservation risks (runtime and report caps) have cheap pre-checks.

## A. Exam

**Confirmed refusal risks, ranked (all MEASURED-in-code; magnitudes UNVERIFIED unless stated).**

1. **`engine_event_cap` at `engine_preflight` (`engine.py:179` vs `ceilings.py:70-74`)** — non-consuming but terminal as signed: rehearsal measures heap pops, the engine also caps Σrecords, panel bundles carry ~D records per timestamp. Only a signed Clarification 4 + code fix cures it.
2. **`time_cap` at export (`maker_plugin_capture.py:58-60`)** — non-consuming. Calibration exports call `reward_terms` for every descriptor on 154,034 reward rows/day (MEASURED) and discard the result. W2 item (a) removes it; pass `--max-seconds 11000`.
3. **`input_byte_cap` (`capture.py:93-95`, 4 GiB default)** — non-consuming. Base day ≈3.9 GB plus Segment-cache re-reads on 11–13 segments >64 MiB (MEASURED). Pass `--max-input-bytes 17179869184`.
4. **`bundle_output_cap`/memory at export (`bundle.py:177-178`, 2 GiB; `MemoryError` not caught `night.py:245`)** — non-consuming but a stuck `day_out` forces a new root. Coverage fan-out is D × ~20k rows/day. Export one day first; read `bundle.bytes`, `peak_memory_bytes`.
5. **Runbook/tree traps (`$Docs` on master, no `-P`/PYTHONPATH, v2 JSON vs row 88's v3, `--clarification-3` missing)** — non-consuming, no record, but each costs a night. W1 pins `CLARIFICATION_3_SHA256`; W2 (f) fixes the runbook.
6. **Post-reservation `time_cap` / `report_byte_cap` (`__main__.py:111-113`, `diagnostics.py:89-90`)** — **consuming.** Pre-checks: `verify_elapsed + 15×largest.runtime ≤ 0.8×ceiling`; `report_bytes − 15×largest ≥ 2×manifest.json + 1 MiB`.
7. **`window_preflight` (`ceilings.py:150-158`)** — non-consuming; 8192 s ⇒ look starts ≤06:43 Toronto; start ~01:50 after 91a releases.
8. **Silent degradations, not refusals:** `calibrate_hazard` writes `unavailable_calibration` with exit 0 on a bad path (`pack_cli.py:194-197`) and `rehearse` accepts it; hazard biased low from trade-WS reconnects (1,968 disconnects on 09-29, MEASURED). Assert `global_fallback == null`, no `binding_status`.
9. **`pull_opportunity_cap` at scoring (`pull_efficiency.py:172-174`)** — consuming, UNVERIFIED magnitude; folds into Clarification 4.

Refuted and dropped: release binding on calibration exports, unsealed 09-27..30 segments, support-row strictness, receipt cap, BOM in `owner-decision.json`, hazard collapse to exactly 1.0.

**Consolidated workstation fix prompt (W2):**

```
Start from docs/operations/WORKSTATION_SESSION_PREAMBLE.md.

Branch: create codex/exam-w2-20261003 from origin/codex/integration-exam-20261002 (d6086f3c0). Do not use origin/claude/exam-fix-20261002; it is a duplicate W1 to be closed.

Scope (all pre-manifest; exporter output must stay byte-identical for a given input; the five docs/research/maker-replay-*.md, approved_registrations.py and bundle.json field sets must not change):
a. src/weather/market/maker_replay_bundle.py ~:359 — guard the reward_terms call with `if projection.kinds is None or "terms" in projection.kinds`. Test: calibration-kinds export over a fixture with reward rows yields byte-identical events.jsonl/bundle.json and unchanged counts.
b. src/weather/market/maker_plugin/runner.py:151-205 — CaptureIndex.reward_rows: bisect the time-sorted lists and recompute only cids named in the row body. Test: linear-vs-bisect equality on 3 cids × 50 rows.
c. src/weather/market/maker_replay_night.py:245 — add MemoryError to the except tuple so a REFUSED receipt lands. Test: injected MemoryError → REFUSED receipt, retry not day_already_sealed_or_attempted.
d. maker_replay_night.py:241-256 — apply event trimming before the 8 MiB receipt check. One unit test.
e. Rename receipt field `clamped_to_capture` → `leading_capture` (W1 keeps venue time; the name is wrong).
f. Runbook docs/roadmap/.../agent-report-2026-10-111e-followup.md: step A uses `--max-input-bytes 17179869184 --max-seconds 11000 --max-output-bytes <explicit ≤ 11.2 GiB>`; fresh --out root per attempt; $Docs read the five frozen docs from the locked worktree with --clarification-3, --decision-log from master; Invoke-ExamStep uses -P -B with PYTHONPATH=<worktree>\src and the __file__ probe; owner-decision JSON has the 10 v3 keys and watches attempts\...-v3.json; post-step asserts (global_fallback == null, no binding_status, pooled.fallback_reasons == []); add a latest-start table from window_preflight (8192 s → 06:43, 4096 s → 07:51).
g. Draft (do not sign) docs/research/maker-replay-clarification-4.md: engine.py:179 and pull_efficiency.py:172-174 compare record/candidate counts against the engine_events ceiling that rehearsals measure as heap pops; propose rehearsing engine_events = max(processed, Σrecords, pull candidates). Include the code diff behind a flag that is inert until the clarification hash is pinned, with a D>12 e2e fixture test.

Run the focused tests, then the full suite via scripts/ops/workstation_heavy.ps1 -Kind pytest. Merge origin/master into the branch, regenerate the correspondence index after committing, push, open a PR, wait for CI green. Hand back the head sha (40 hex) and the list of hashed maker_core files you touched. No auto-fix, thanks.
```

**Night-by-night calendar** (slots: A 01:45–05:00 after 91a, B 05:31–06:00, C 06:41–08:10; ≤3 exports/night; a REFUSED day is non-consuming, retry into a new root):

- **10-03 night:** no export. Day: W2 prompt out; owner decides coverage fan-out and reconnect loop (E1/E2); Clarification 4 drafted.
- **10-04:** pin `weather-exam-deployed-<W2 sha>`, recompute `module-hash`, `__file__` probe. **E1: calibration 09-27** (A). Read `runtime_seconds`, `peak_memory_bytes`, `bundle.bytes/records/counts.coverage`, skew summary. If runtime <1,500 s and peak <5 GB: 09-28 (A), 09-29 (C). Fallback: one per night 10-05/06.
- **10-05:** remaining calibration; `quote_markets` + `calibrate_hazard` (new filenames; asserts; inspect `cities[*].exclusions.trade_coverage_gap`). Day: owner signs Clarification 4 and appends REVOKE v1 / APPROVE v3 rows (UTC-dated, roll-free).
- **10-06:** rehearsal-panel exports 09-27/28/29. Stop and escalate if any `bundle.bytes` > 546 MiB. Free pre-check of row/docs binding via `manifest build` → expect `manifest_before_scoring_date_toronto`.
- **10-07:** Clarification 4 merged and pinned; three rehearsals serially in A (lease state logged), `derive_ceilings`, headroom ratios, latest look start. Export 09-30 in C (power-loss day).
- **10-08..10-14:** panel 10-01..10-13 at 3/night (10-08: 01–03; 10-09: 04–06; 10-10: 07–09; 10-11..14: one each plus catch-up slack of 2/night).
- **10-15:** export 10-14 (A); universe, build, verify; check Σ18 bytes/records vs ceilings and the report-cap margin.
- **10-16: LOOK** ≈01:50; DECISION_LOG frozen; worktree clean.
- **Fallback chain (hard edges):** W2 pinned 10-19; calibration ×3 by 10-20; hazard 10-21; rehearsal exports 10-22; Clarification 4 merged 10-22 day; rehearsals 10-23; panel ×15 10-24..29; rows 10-29 day; build 10-30; look 10-31 ≤06:43. v3 expires 11-01T04:00Z.

## B. Post-exam landing schedule

Gate: nothing roll-sensitive before the look is done; if candidate-2 (#137, decision due 10-12) runs its own exam (panel 10-16..29, look 10-31), only #142 (disk relief) and, if the owner says so, #152 land before 10-30.

- **N1 10-15→16 night (roll-free, needs no quiet window):** let 91a finish (~01:45), bounded suite ~01:50, merge ~03:30 before 05:00 tiering. Integration branch `codex/integration-postexam-20261015`: #141 first (take its index root, commit, regenerate, commit), #155, #154, #150 (resolve `wallet-reader.md`: #150 paragraph + #154 address substitution), #151, #128, #146, then #117, #121, #120 (merge only; no task re-registration). Close #149. #153 held (rewires 09:30 chain; also conflicts with #145).
- **N2 10-17 (01:00–04:00):** #152, then #143. Disable 91a that night; prove three workers recovered between merges.
- **N3 10-19:** #119, then #118 only if its hourly `clob_tokens` cadence is traced cadence-independent for the plugin (DECISION_LOG:77 binds band identity from token batches) — otherwise #118 after 10-30.
- **N4 10-21:** #142 alone, rebased after #119 (resolve `forecast_archive.py`); reader trace of `snapshot_explanations_long.csv` consumers done first.
- **N5 10-23:** #104 then #145 (owner row 09-29 confirms the paper-run tool), after yml/`mm_policy.py` resolution and a fresh workstation full suite. Fix #152's `tests/conftest.py` to honour explicit `--basetemp` before N2.

All nights: disable 91a → 00:30 suite on the merged worktree → `quiet_window_merge.ps1` (no `-DryRun`) → recovery proof → `WeatherOneShotPush` → re-enable 91a → STATE_OF_PLAY rewrite.

## C. Expansion groundwork

| Family | Settlement | Free data | Desk study |
|---|---|---|---|
| **Lowest temp** (12 cities, same stations) | NWS `wrh/timeseries` "Temp" column min, WU fallback; 2 °F buckets US, 1 °C Toronto (MEASURED); rules text UNVERIFIED (JS-rendered) | WU `min_temp` already parsed; METAR/ASOS obs; retained NBM bulletins carry the 12Z-valid minimum (`TXN` second group) | **GO** — top priority; falsifier by 10-31 |
| **Foreign 6** | WRH for EGLC/LFPB/RKSI/ZSPD/RJTT; HKO `climat.htm` 0.1 °C for HK; `locations.json` blocks stale | IEM/aviationweather METAR global; Open-Meteo (ECMWF/UKMO/AROME/JMA); HKO open API | **GO (cheap)** — WRH≡IEM check + EGLC weekend gaps; recorder-only at Stage 2, model lane refused on disk |
| **YouTube** | "views counter" at 24 h/72 h/7 d; verbatim rules UNVERIFIED; counting regime changed 2026-08-24; counts non-monotone | Data API `videos.list` 1 unit/call, ~3k/day at 30 s; RSS for upload detection | **NO-GO until** PR #107 merged, API-key placement decided (E6), after 10-15 |
| **Ride-alongs** | Kp daily (SWPC Kp JSON; 4.67-vs-5 ambiguity decisive); monthly precip (NOWData; running sum, floor logic reusable); USDM (weekly API, never revised); App Store (RSS vs charts page basis risk) | All ≤5 KB public JSON/CSV | **GO** precip and Kp as workstation scripts; USDM/App Store defer |
| **Reward terms** | one `/rewards/markets/current` sweep (~40 pages) covers every family | Already paginated in `exchange_economics.py:372-393` | Build `weather.market.reward_census` (spec in x-reward-terms); close #129 |

**Desk-study prompt 1 — lowest temperature:**

```
Start from docs/operations/WORKSTATION_SESSION_PREAMBLE.md.

Desk study only; no capture, no credentials, no src/ behaviour change. Branch codex/desk-lowest-temp-20261003. Inputs: the obs export the production agent will scp (WU history min_temp, METAR/ASOS hourly and one-minute temps, retained NBM bulletins for 2026-08-01..09-29 for the 11 US stations + CYYZ). Deliverable: docs/research/lowest-temperature-desk-study-2026-10.md with (Q1) whether the venue's "Temp column minimum" on weather.gov/wrh/timeseries equals the hourly METAR min or the CLI/daily-summary min — compute both per station-day and count bucket disagreements under the measured 2 °F / 1 °C buckets; (Q3) fraction of daily lows occurring after 18:00 local by month; (Q2 prep) a parse of the NBP TXN minimum group (12Z-valid, provenance-checked like EF §10k) producing p10-p90 per station-date, no scoring against markets. Read a browser render of one live lowest-temperature rules page and quote it verbatim with date. State MEASURED vs UNVERIFIED per table. Push, open a PR, hand back the head sha. No auto-fix, thanks.
```

**Desk-study prompt 2 — foreign settlement check:**

```
Start from docs/operations/WORKSTATION_SESSION_PREAMBLE.md.

Desk study only. Branch codex/desk-foreign-wrh-20261003. For 2026-09-20..09-29 and stations EGLC, LFPB, RKSI, ZSPD, RJTT: fetch IEM ASOS METAR (the global reader in src/weather/sources/metar_history.py) and a browser render of weather.gov/wrh/timeseries?site=<icao> per day; compare daily max per station-local date (timezone from config/locations.json) and report every mismatch and every WRH gap (EGLC overnight/weekend closure especially). For Hong Kong, read HKO climat.htm Absolute Daily Max and the Open Data rhrread endpoint for the same days and document the 0.1 °C to whole-degree bracket rule as observed on resolved markets. Deliverable: docs/research/foreign-settlement-desk-study-2026-10.md plus a roll-free diff to config/locations.json settlement blocks (source_type wrh_timeseries for the five; HK precision one_decimal). No capture, no credentials, nothing under data\. Push, PR, hand back the head sha. No auto-fix, thanks.
```

## D. Model prep

**111h (PR #146, `03a028bd8`): runnable tonight from a detached worktree; nothing must merge.** Two pre-run items: (1) the extractor indexes `last+1` day, so `--to 2026-09-29` opens 09-30 NBM manifests — contradicts the frozen doc; record the deviation in the report (or one-line fix + re-CI, costs a night); (2) runtime 1.5–2.5 h against a 2 h cap (UNVERIFIED) — accept `INCOMPLETE_BUDGET_EXCEEDED` as a one-night loss with the block-once optimisation next.

Sequence (production, ~01:50 after `scratch\cold_snapshot_compression\nightly-<today>\wrapper-result.json` exists):

```powershell
$prod='C:\Users\micha\Desktop\github\weather'; $env:GIT_LFS_SKIP_SMUDGE='1'
git -C $prod fetch origin codex/guidance-all-hours-20260930 codex/nbm-target-fix-20260921
$tip=(git -C $prod rev-parse origin/codex/guidance-all-hours-20260930).Trim()   # expect 03a028bd8
git -C $prod worktree add --detach C:\pt\w111h $tip
git -C $prod worktree add --detach C:\pt\w111h-parser 2e17ce0eb
Get-Content $prod\data\logs\heavy_workload.lock   # no ACTIVE owner
$p=Start-Process powershell -PassThru -WindowStyle Hidden -RedirectStandardOutput "$prod\scratch\guidance_extract_111h.log" -RedirectStandardError "$prod\scratch\guidance_extract_111h.err" -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"C:\pt\w111h\scripts\ops\guidance_extract_run.ps1",'-ProductionRepoRoot',$prod,'-ExpectedSourceTip',$tip,'-ParserWorktree','C:\pt\w111h-parser','-OutputRoot',"$prod\data\exports\nbm-guidance-111h",'-From','2026-08-01','-To','2026-09-29'); $p.Id
# poll $p.HasExited; read manifest.json status + SHA256SUMS; remove both worktrees; owner scp to the workstation
```

Collision: 111h and exam E1 both want slot A; 111h tonight (10-03 night has no export), exam from 10-04.

**NBS/NBH pre-registration skeleton: drafted, not frozen.** Candidates C-NBS (Normal(TXN, XND) at 00Z) and C-NBH (hourly TMP/TSD max-bound), fixed-market date-clustered estimand, strata by local hour block, minimum effect half of 0.0074 in 13–16. Blockers before freeze: (a) 12-bulletin trace confirming whether the 00Z `TXN` column survives NBS cycles ≥19Z (UNVERIFIED); (b) ≥7 days of per-cycle S3 latency; (c) land `-09-83c` parser v2 + reuse index (24 cycles × 30 MB/day otherwise). Sequence after 111h per the 09-30 decision. Fair-value gaps (1,817 capture-lateness + 894 `no_bulletin`) are capture/reader fixes post-exam; the T+1 fallback has no US input by construction.

## E. Owner decisions (recommendation in one line)

1. **Coverage fan-out (per-event vs per-30 s, `bundle.py:184-190`)** — keep as-is for this exam; explicit "no change" now, since any change forces a full re-export.
2. **Trade-WS reconnect loop before calibration export** — no code change; accept biased-low hazard, record it as a method note, fix post-exam.
3. **Clarification 4 (`engine_event_cap`/pull cap)** — sign by 10-05 day; without it the line as signed cannot pass on real panel data.
4. **Which W1** — d6086f3c0 (codex); close `claude/exam-fix-20261002`.
5. **Candidate-2 exam (#137) by 10-12** — defer to after this look; it re-freezes roll-sensitive landings through 10-29.
6. **YouTube API key on the capture host** — no; capture on the workstation after 10-15.
7. **#118 before 10-30** — no, unless traced cadence-independent.
8. **ProtonVPN / crash dumps** — uninstall after an egress check outside 12:00–18:00; enable dumps.
9. **91a policy renewal (expires 10-30)** — sign 10-27.
10. **RAM 48 GB** — defer; non-binding.
11. **111h `last+1` deviation** — record in the report, do not spend a night re-pinning.

## F. Dated ops checklist 10-03 → 10-31

- **10-03 day:** W2 and both desk-study prompts out; close RE-1 PRs #78, #82–#85; read Stage B step durations (read-only); Ethernet this week.
- **10-03 night:** 111h extract (~01:50–04:00); verify manifest; remove worktrees. No exam export.
- **10-04:** pin W2; E1 calibration 09-27 (A); obs export for the lowest-temp study + owner scp; wallet-reader re-registration from #150 waits for N1. Desk-study pilot export (`-DryRun` first) only in a free slot B/C.
- **10-05:** calibration 09-28/29, hazard steps; owner signs Clarification 4, REVOKE v1 / APPROVE v3 rows.
- **10-06:** rehearsal-panel exports; 546 MiB check; free binding pre-check.
- **10-07:** Clarification 4 merged + re-pinned; rehearsals + `derive_ceilings`; 09-30 export.
- **10-08:** panel 10-01..03; 91a stop-on-zero-savings review (7 receipts).
- **10-09..10-14:** panel through 10-13; 10-12 candidate-2 decision; Stage B chunking built on the workstation; 10-14 settlement day, no merges.
- **10-15:** 10-14 export, universe, build, verify.
- **10-16:** look ≈01:50; then N1 roll-free integration that night (after the `.completed.json`, before 05:00); wallet-reader re-registration (owner); reward-census registration; RAM only if still wanted.
- **10-17:** N2 (#152, #143). **10-19:** N3. **10-21:** N4 (#142). **10-23:** N5 (#104/#145).
- **10-16..10-30:** retention hold; `/rewards` trigger only after the look; Stage B re-enable after chunking + #153 landing.
- **10-27:** 91a policy signed and re-registered (hard stop 10-30).
- **10-31:** lowest-temp falsifier check; release the 88a hold after the panel transfer; add lowest-12 recorder conditions; write the post-exam ops batch as one numbered roadmap item cited from STATE_OF_PLAY.

## Critic

**Verdict:** The exam chain is schedulable as drafted only after four gaps are closed: the enrollment round between build and look is absent from every calendar, Clarification 4 needs a v4 authorization (so the 10-05 v3 rows and 10-06 pre-check are premature), three consuming refusal paths are unexamined, and the 10-16 night double-books the look with N1.

1. **Enrollment missing (MEASURED in code).** The look refuses unless the manifest hash is in `APPROVED_REGISTRATIONS` (`__main__.py:84-90` → `authorization.py:166`); the enrollment template (steps 4–6) requires a topic branch, review, roll verdict, landing and a second `manifest verify`. Neither the 10-15→10-16 line nor the fallback "build 10-30; look 10-31" has that round or a re-pin of `weather-exam-deployed-<sha>`. Fix: 10-15 A build+verify → 10-15 day enrollment PR/review → 10-16 A re-pin + verify → look 10-17 (or accept a same-night squeeze explicitly).

2. **Clarification 4 is unbound as planned.** `CLARIFIED_IDS`/`SIGNED_BINDINGS` know only v2/v3 (`authorization.py:21-39`); every prior clarification created a new ID. Signing C4 on 10-05 means REVOKE v3/APPROVE v4 plus a verifier change, so the 10-05 rows and the 10-06 "binding pre-check" target an ID that will be revoked. Also the owner is asked to sign a rule change before evidence exists: the rehearsal JSON already carries both `measured.records` and `engine_events` (`pack_cli.py:138-139`). Reorder: rehearse first (10-06/07), decide C4 on the numbers, write rows once. Cheaper path for `engine.py:179`: Σrecords is already ceilinged by `max_records` at load (`__main__.py:129-131`, `execution_manifest.py:145-147`), so redirecting that check is an implementation correction, not a rule change. The real gap is `pull_opportunity_cap` (`pull_efficiency.py:172-174`): candidates = active minutes × conditions, computable from the manifest, so move the count to `engine_preflight` where a refusal is non-consuming.

3. **Unexamined consuming paths.** `memory_ceiling` (`ceilings.py:170-171`, active through scoring), `engine_output_cap` (`engine.py:241-242`), `unpaired_pull_traces`/`pull_cluster_identity_mismatch` (`pull_efficiency.py:152-155,177-178`). The 546 MiB `bundle.bytes` stop rule measures the wrong quantity: the signed limit is process peak above baseline (`ceilings.py:12-13`); on-disk-to-object ratio UNVERIFIED. Pre-check: after `derive_ceilings`, h = ceiling/(15×largest) per quantity; require each panel receipt's records and conditions ≤ h × largest calibration day; read rehearsal peak directly. Host safety: an "executable" ceiling can be 11.2 GiB (`bundle.py:36-37`) beside three capture workers; `host_preflight` checks commit only before start (`ceilings.py:142-147`). Check available physical RAM ≥ `memory_bytes` at 01:45.

4. **Ceiling measurement is not bound to the calibration.** `measured_limits` validates format and derivation only (`execution_manifest.py:125-132`); nothing compares `ceiling-measurement.json.calibration_sha256` to the sealed `calibration.json` hash. With A.8 (unavailable calibration → hazard 1.0, `calibration.py:25`), a stale rehearsal yields tiny ceilings and consuming refusals. Assert equality before build; W2 can add it to `build_manifest`.

5. **10-16 double-booked.** Look ≈01:50 may run to 04:07 (8192 s) under the lease; §B puts N1's bounded suite at 01:50 and merge at 03:30; §F says N1 after `.completed.json` before 05:00. Both cannot hold. N2 (10-17) is hard-dated although a 10-16 non-consuming refusal retries 10-17. Make N1/N2 conditional on `.completed.json` and shift one night.

6. **Standing decision contradicted.** DECISION_LOG 2026-10-02 row: tree = `6ac18be7e` plus only the C3 hash commit, roots `exam-c2`/`maker-replay-panel`. `d6086f3c0` already adds `3275fcdc9` (exporter changes) and W2 touches `maker_replay_bundle.py`, `runner.py`, `night.py` (all in `module_closure`, `night.py:44-55`, and `source_hashes`, `execution_manifest.py:41-44`). The synthesis must say that row is superseded by W2's pin, with new roots.

7. **E1 premise wrong today.** "Any change forces a full re-export" — STATE_OF_PLAY (10-02 02:40): calibration export REFUSED, no panel export exists. The D-row coverage fan-out per stream event (`bundle.py:186-192`, called from `stream()`) is the direct driver of item 2's Σrecords-vs-heap-pops gap; it is cheapest to change before 10-04. Magnitude UNVERIFIED.

8. **Owner asks without evidence.** E8 (ProtonVPN uninstall, dumps) cites nothing. E5's cost claim is unsupported: the 09-30 row has candidate 2 running from a pinned worktree and the 10-15..10-30 retention hold already exists, so it freezes no master landing.

9. **Refuted, for the record (MEASURED on `d6086f3c0`):** frozen docs are 3,250–14,286 B and DECISION_LOG 23,329 B on master, well under the 65,536/262,144/458,752 reader caps (`authorization.py:122,159,168`); `CLARIFICATION_3_SHA256` already matches the signed bytes (`fcbcb7d0…`), so W1 need not "pin" it; `late_look_permitted` ignores refusal records (`execution_receipt.py:59-75`).

10. **W2 branch choice OK:** `d6086f3c0` contains `6ac18be7e`; the claude branch differs only in exporter/payload/test files; neither is CI-attested at its current head in the synthesis — ask for the PR #157 check state on `d6086f3c0` before pinning.
