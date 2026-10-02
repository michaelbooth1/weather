# Expansion and efficiency swarm — 2026-10-01/02

- **Owns:** the 31-agent read-only swarm of 2026-10-01 (current state, host capacity and efficiency, International Polymarket expansion candidates), its verified synthesis, the completeness critique, and the multi-domain capture architecture.
- **Read when:** planning capacity work, new market families, or capture architecture after the 10-15 look.
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)) or decisions in force ([DECISION_LOG](../../operations/DECISION_LOG.md)).

Method: one budgeted public market census (the only agent allowed Polymarket calls), 4 audit, 6 efficiency and 11 expansion researchers, 6 adversarial verifiers, an architecture designer, a synthesis and a completeness critic. All read-only; no exam-blackout data read. Numbers are a single snapshot unless marked MEASURED over time.

## Synthesis

**Verdict:** Production is healthy and disk-bound, not compute-bound (CPU ~6% at rest, 8 GB RAM free, 101.3 GiB free burning ≈+8.6 GiB/day before 91a); master moved only by docs since the 09-30 swarm, but the exam line regressed on paper (re-run script pins a superseded head, C3 constant still PENDING, six 10-01 decisions unrecorded); the cheapest expansion is more temperature slugs on the pipeline we already run, recorded 88a-style, and nothing roll-sensitive before 10-14.

## (A) State and changes since 09-30 / 10-01

**DONE (MEASURED)**
- Integration #147/#148 landed 10-01 01:38 (165 files; wallet reader, 91a nightly, cockpit); then three docs-only merges. master = origin/master = `819f81488`, 0 behind/ahead.
- 09-30 swarm items: C2 signed (DECISION_LOG:83); estimand rule; Desktop ACE fixed; 26 stale tasks unregistered; push stays Interactive; YouTube plugin held; 91a stop-on-zero built, task Ready for 00:30 tonight.
- Exec-tape write storm fix (#116) in master: 0.55 GB/day vs ~314 GB/day before.
- Fleet: four supervisors `ensure_status OK`, no restarts since the 09-30 14:19 power-loss recovery; 88a running (96 conditions, 1.89 req/s, 23 HTTP errors in 1.4 d); host_health CLEAN; commit 33%.
- PR #158 (Clarification 3 draft) merged into the exam branch; #157 head `6ac18be7e` (tail fix + C3), CI green. 10-01 lock fixes done.

**BUILT, not landed:** #152 fsync fix (after 10-13); desk study `codex/maker-pnl-adverse-selection-20261001` @67e44273b (no PR, no DECISION_LOG row); #156 reward scan; workstation batch #151/#153/#154/#155; #117–#121 (110v Parts 2–6, rebased, none merged).

**OPEN:** learning lane unblock (#153, `WeatherEveningEvidenceRefresh` Disabled); NBS/NBH probe #146; candidate-2 pinned worktree #137; 48 open draft PRs, 6 CONFLICTING (#145 #133 #129 #127 #125 #124), 24 conflict on `correspondence-index.md` by merge-tree despite gh saying MERGEABLE.

**REGRESSED / drift**
- `run_rerun_111k.ps1:3` pins `6e7162e8e`; the exam tree is `6ac18be7e`. The script throws `exam tree head moved` at ~04:45 with nobody awake. It also gates a `fair_value.py` the panel will never use.
- `authorization.py` on the exam tree: `CLARIFICATION_3_SHA256 = "PENDING_OWNER_SIGNATURE"`. C3 was signed 10-01 17:44Z, blob at 8120ce2f8, SHA-256 `fcbcb7d0…` VERIFIED by hash — but no DECISION_LOG row, no REVOKE v1 / APPROVE v3. Tree must move once more.
- Unrecorded 10-01 decisions: tail-fix Amendment 2 / option A; C3 reporting-only scope; desk-study C1 approval; "all 15 bundles from one pinned tree"; 88a retention hold 10-15..10-30; prereg 574f8369b.
- STATE_OF_PLAY stale: master sha (says 979c0e752), free space (~107 → 101.3 GiB), "#134/#128 conflict" (both now MERGEABLE), exam roots missing. HOST_LOAD_POLICY:392 still "Codex-owned"; AGENTS.md:77 hook line wrong until #155.
- Working tree carries uncommitted fleet drift in `config/location_market_events.json` and `locations.json`.
- Stale JSON in `heavy_workload.lock` (pid 16904, dead). OS mutex governs per `workload_admission.ps1:2037-2045`; whether 91a's own acquisition agrees is UNVERIFIED — check for `SKIPPED_WORKLOAD_LEASE_BUSY` this morning.

**Tonight's readiness:** 91a first real run 00:30 (32 GiB budget, deadline 04:45; one report saw it `Running`). Two unclean power losses in 48 h, no UPS. Calibration days 09-27/28/29 have 24/24 sealed segments; the unsealed-segment refusal should not fire.

**Exam path to the look (dates):** 10-02 day: docs light path (rows above), workstation PR setting the C3 constant → head H*, then REVOKE v1 + APPROVE v3 rows before any manifest build. 10-02/03 night: 91a + plugin re-run from H* (lease-wait, ≤2,700 s). 10-03/04: calibration exports ×3. **10-04/05: ceiling rehearsal + `derive_ceilings` — move ahead of the panel backlog** (≤546 s / ≤~546 MiB per date or "not executable on this host", unmeasured). 10-05→10-14: panel exports 2–3/night after 91a (≈30 slots for 21 exports). 10-15/16: settlement export, universe, manifest verify. Look 10-16/17, late ≤10-31; v3 expiry ≤2026-11-01T04:00Z. Any stop after `attempts/<id>.json` is reserved spends the look.

## (B) Capacity

| Resource | MEASURED | Headroom |
|---|---|---|
| Disk free | 101.3 GiB (108.7 GB) of 930.6 GiB | **binding** |
| Gross write (capture-only day, 10-01) | 11.9 GiB; 4-day range 11.9–23.4 incl. agent activity | — |
| Recurring reclaim | 3.3 GiB/day (06:00 raw-tape tiering only; other jumps were ad-hoc) | — |
| Net before 91a | ≈ +8.6 GiB/day → **~6 days to the 50 GiB suite floor** | — |
| Persisted per closed city-day | 0.439 GiB (one sample) → 5.27 GiB/day at 12 cities | — |
| CPU | 6% avg at rest; fleet 0.2 core (parents) + ESTIMATED 0.1–0.2 (snapshot children); Defender ~17% of one core (the 79% reading was swarm-inflated — REFUTED) | large |
| RAM / commit | 8.3 GB free; commit 33% of 31.7 GiB; capture privates 2.9 GB | large |
| Disk I/O | 3% busy, 2.7 MB/s | >10× |
| Polymarket REST | fleet 2.3–3.5 req/s; 88a 1.9 req/s of which ~83% is per-condition `/rewards`; documented limits 50–900 req/s per endpoint; `/rewards` and WS limits undocumented | ~10× cities, UNVERIFIED |
| Websocket | 5 market-channel connections, ~15 GB/day inbound to keep 0.2% of frames; 8 reconnects/h on Wi-Fi | rumoured 5/IP cap UNVERIFIED |
| Overnight lease | 00:30–09:00 serial; 91a holds 00:30–04:45 nightly, so every suite/merge night costs a 91a night | second binding |
| Stage-A | 09:30–11:55, ~75 min recomputes immutable history | first *time* ceiling on adding cities |
| Open-Meteo | 10,000/day free quota binds at ~130 cities | first REST limit that actually binds |

91a: 2.97:1 MEASURED on 1,147 small files (median 0.18 MB); ratio on the 50–90 MB JSONL/CSV UNVERIFIED. **Unresolved conflict:** one reviewer read `cold_snapshot_nightly.py:25-36` (256 MiB/file, 2-day age), another `cold_snapshot_compression.py:96-110` (≤64 MiB/file, 30 days unchanged, ≤1 GiB/batch). Tonight's receipt decides which bound governs the 88 MB `clob_tokens.jsonl`. Backlog ≈465 GiB ≈15 nights (ESTIMATED); steady state after backlog ESTIMATED +2.3–4.1 GiB/day.

**Saturation under expansion:** +12 cities on today's pipeline ≈ +170–180 GB standing (30-day pre-91a hold) against 101 GiB free — refused. By family in the 88a pattern (~0.8 MB/condition-day gzipped, ~1 req/condition/min): 1,000 conditions ≈ 1 GB/day disk, 0.5 req/s with batched books — disk is not the constraint there, the IP budget and WS fan-in are.

## (C) Efficiency plan (ranked)

| # | Lever | Saves | Risk | Effort | Roll | Earliest |
|---|---|---|---|---|---|---|
| 1 | Roll-free batch A: #141 index shard, #117 Stage-A incremental, #120 thin ensure, #121 profile, #155/#154/#153/#151/#128/#146 | Stage-A −~75 min/day (unblocks cities); ~4,320 interpreter starts/day | low | done | free | 10-03→04 (suite 00:30, 91a off that night) |
| 2 | 88a `/rewards` change-trigger (Gamma `clobRewards` as trigger, 15-min venue sweep) | 88a 114→~10 req/min: **−1.6 req/s, −80% fleet REST** | low; exam may pin 88a to 10-14/10-31 | small | 88a restart | after look, or 10-16 if contract allows |
| 3 | #118 CLOB write-on-change + token-row dedup (`write_token_rows` every poll; 27% of each book record) | −1.5 to −2.7 GB/day writes, −50k Gamma GET/day | med (readers of `clob_tokens.csv`) | built | sensitive | 10-16→17 |
| 4 | #119 snapshot tail reads | −563 GB/day reads, −5% core | low | built | sensitive | 10-16→17 |
| 5 | Per-market fast interval (fleet sits at 15 s ~85% of the day) | −~2 GB/day | owner cadence decision | small | sensitive | 10-16→17 |
| 6 | 88a fsync → 1 s grouped writer (reuse `execution_tape_io.py`) | −90% IOPS (707k/day), ~5% core | low | small | 88a restart | after 10-13 |
| 7 | Shared Gamma event cache across loops + 12-slug batched discovery | −24–96 `/events`/min (~2× fleet REST) | low | small | sensitive | batch B |
| 8 | Obs-trigger: status trim, METAR `ids=` batching, per-source TTL | −1.5 GB/day writes, 12× fewer METAR calls | low | small | sensitive | batch B |
| 9 | Schema-registry lazy lookup (17 of 32 roll-sensitive verdicts are registry rows only) | quiet-window nights 5→2/month | low | small | sensitive once | batch B |
| 10 | Storage: stop duplicate `*_long.csv`/`clob_tokens.csv` after close; parquet via closed-day lane; gzip the 4 big JSONL | −0.43 / −0.3 / +0.64 GiB/day beyond NTFS | med (readers) | medium | sensitive | after 10-13 |
| 11 | Shared WS subscriber (5 sockets→3, one decode) | halves 15 GB/day inbound, ~8% core | changes raw-book evidence semantics | medium | owner + sensitive | November |
| 12 | Closed-day export lane (hashed bundles) → workstation; suite verification = CI + workstation | frees 00:30 slot nightly | low | medium | free | Stage 0 |
| 13 | Wi-Fi → Ethernet | 8 reconnects/h on trade streams | none | cable | none | any day |
| 14 | RAM 2×16 GB DDR4 (~$300–450 CAD) | commit ceiling 64–80 GB; Stage B re-enable | 20–30 min capture gap | hardware | shutdown | 05:00–08:00 after 10-15 |

Not a lever: Defender exclusion (already excludes `data\`); CLOB enrichment loop (dead since 07-27, zero cost today).

## (D) Expansion scorecard (D data / T timing / R rewards / S maker safety / C cost; 0–5)

| Family | Pool USDC/day (one snapshot) | D | T | R | S | C | Total |
|---|---|---|---|---|---|---|---|
| **Lowest-temp, our 12 cities** (396 live mkts) | ~400 ours; 2,199 in 8 of 45 cities | 5 | 4 | 2 | 4 | 5 | **20** |
| Geomagnetic Kp daily | 200 | 5 | 4 | 1 | 3 | 5 | 18 |
| Monthly precipitation (5 cities) | 1,000 | 4 | 4 | 3 | 4 | 4 | 19 |
| **Top-6 foreign highest (+lowest)** | ≈3.6k; Shanghai $104/day@100 sh MEASURED | 4 | 3 | 5 | 3 | 2 | **17** |
| **MrBeast views** (owner #2) | 1,150; 253/day band unquoted at snapshot | 4 | 4 | 3 | 3 | 4 | **18** |
| App Store rank | 200 | 5 | 4 | 1 | 3 | 5 | 18 |
| USDM drought (weekly step) | 2,141 | 3 | 2 | 4 | 3 | 5 | 17 |
| Rain-daily (14 US) | 575 | 4 | 4 | 2 | 2 | 5 | 17 |
| Stock/commodity hit-price | 5,964 | 4 | 2 | 4 | 3 | 3 | 16 |
| Treasury ladders | ~4,000 (most legs decided) | 4 | 2 | 3 | 2 | 3 | 14 |
| Post-count ladders | 1,400 | 2 | 4 | 2 | 2 | 4 | 14 (feed is venue-hosted) |
| FOMC | 2,950, min 200 | 4 | 1 | 5 | 1 | 4 | 15 |
| Legislative/bankruptcy one-offs | 58,400 (25% of venue) | 1 | 1 | 5 | 1 | 2 | 10 |
| Sports / crypto up-down | 16.5k / **0** | 3 | 1 | 1 | 1 | 1 | 7 |

Context: venue 229k/day over 19,065 rewarded conditions; temperature complex 15.2k; our 12 take 1,200 same-day (2,399 incl. tomorrow). Weather:temp pays 1.0 USDC/day per min-size share, 4× the next category. Pools ≥500/day are capital contests ($0.7–3.4M in band → ≤$0.36/day for our quote). 57% of same-day foreign reward needs min-size 100.

**Top 3**
1. **Lowest-temperature, 12 cities** — first step: 12 slugs as 88a `--extra-conditions` (cap 32, recorder-only, no snapshot/obs lanes) after 10-14; workstation desk study of hour-of-minimum from captured obs now. Falsified if minimum undercut after 09:00 local on >30% of days, or rewarded bands outside 0.10–0.90 >80% of rewarded minutes. Check by 10-31.
2. **Top-6 foreign highest(+lowest)** (Shanghai, Seoul, London, Paris, Tokyo, HK) — 14 days passive 88a capture, no model lanes. Falsified if modelled 20-share share <0.05 or same-day `min_size` is 100. Decide mid-November.
3. **MrBeast views** — passive book+terms capture (~29 mkts) + `videos.list` per minute from 10-16, beside the owner's collector; needs 7 days of measured disk before production. Falsified if mids move before the API count changes or bands are decided at post.
Ride-alongs in the recorder at ~zero cost: Kp (2 events/day), monthly precipitation, USDM, App Store RSS — desk studies only.

**Not now:** sports (no rewards on game books); politics/elections/geopolitics (jump, saturated); the two one-off families (sponsor-driven, UNVERIFIED, transient); FOMC/CPI/PCE (scheduled jump, pros); crypto up/down (0 reward, millisecond repricing); crypto hit-price/WTI (faster feeds); Treasury (desk only); post-count ladders (`xtracker.polymarket.com` is the venue; X API paid); mentions, awards, DWTS, Netflix/Spotify (release jumps, no free fair-value input); earthquakes (pick-off at the event); hurricanes (recon leads); all 37 cities on today's pipeline (~33 GiB/day).

## (E) Architecture and staging

Split capture into a **domain-neutral venue recorder** (lift `EvidenceStore/PublicReader/PublicStream` into `capture_core`; `config/capture_families.json` with `{family_id, domain_id, discovery, cadence_s, retention_class, quote_candidate}`; one `/books` POST per 100 tokens/min; venue-wide `/rewards/markets/current` every 15 min, per-condition GET only for ≤120 quote candidates; one market-channel subscriber fanned out locally; change-only JSON, hourly gzip-at-write, sha256 manifests; retention classes A settlement-grade / B model evidence / C diagnostics; one host-wide request bucket, start 2.5 req/s) and a **per-domain model-evidence lane** (weather's snapshot/CLOB/obs loops — the whole 11 GiB/day — frozen at 12 cities until levers 3/5/10 land). Plugins own slugs, `plugin_input` fetch allowlists, settlement adapter, fair value, info clock; new families get no model lane until a desk study earns it. Contract gap: `Profile.eligible_horizons=(1,2)` and the T−3 h gate assume daily close — a new Profile is needed before any weekly/monthly family quotes.

Authority: production host = recorder + weather lanes + Stage-A + 91a + export sealing; 32 GB workstation = desk studies, plugins, training, replay, export consumer, never capture; third box (owner, after 10-15) = capture-only for non-weather families if IP or disk binds.

Stages: **0** (now→10-14, roll-free): 91a receipt, batch A, schema + docs, export-lane runbook, desk studies. **1** (first quiet window after 10-14): #118/#119, per-market fast interval, `/rewards` trigger, lowest-12 as recorder conditions. **2** (November): `capture_core`, ~1,000 conditions ≈ 1 GB/day, families above. **3** (after storage levers + Stage-A incremental): promote ≤6 cities into the model lane (+1.5 GiB/day). **4**: plugin quoting after the look and falsifiers. Guards: receipt per stage with req/s, GB/day, 429 count; abort if 24-h trail low <70 GiB or any 429.

## (F) Decisions for the owner

1. Tonight's re-run from `6e7162e8e` — **skip it; land the C3 constant commit first, re-pin once to H*, accept the `…-resolution-tails` model id.**
2. Record the 10-01 decisions and C3 hash, REVOKE v1 / APPROVE v3 — **today, docs light path, before any manifest build.**
3. #157: pin as exam worktree and merge after the look vs land now — **pin; zero capture restarts during the panel.**
4. Ceiling rehearsal order — **run 10-04/05, before panel exports.**
5. Close #78 #82–#85 now; #96 #100 #107–#109 #112–#114 #133 #149 when the exam tree lands — **yes.**
6. Per-market fast interval (evidence cadence) — **approve for batch B.**
7. 88a `/rewards` trigger timing vs exam retention hold — **after the look unless the contract explicitly allows 10-16.**
8. Shared WS subscriber (raw-book semantics) — **design now, decide November.**
9. Lowest-12 via 88a extras after 10-14 — **approve.**
10. RAM to 48 GB, 05:00–08:00 window after 10-15 — **approve (~$300–450 CAD).**
11. Workstation as second capture host — **no.** Third box — **decide after 10-15, capture-only, after the YouTube disk measurement.**
12. Second disk — **hold** (09-23 stands); revisit if the trail low still falls after two weeks of 91a receipts.
13. Ethernet to the host — **yes.**
14. Reward census as a `weather.*` CLI, 4×/day inside 00:30–09:00 (+0.6 req/s serialized against 88a) — **yes, after the first 91a receipts.**
15. Still undecided: ProtonVPN on the capture host; crash dumps.

## (G) What NOT to do

- No roll-sensitive merge before 10-14; no direct full pytest at any hour; no overlapping lease jobs; never derive a roll verdict by hand.
- Do not run `run_rerun_111k.ps1` as pinned; do not reserve an attempt before the ceiling rehearsal passes.
- Do not add cities on today's pipeline before tonight's 91a receipt, Stage-A incremental, and levers 3/5/10; do not trust 3:1 on the big files until measured.
- Do not plan around the 58k/day one-off pools or any pool ≥500/day; do not touch crypto, sports, politics, paid data, or the venue-hosted post tracker.
- Do not use the workstation for capture or restore the `/MIR` mirror; do not shorten or rewrite tapes, 88a journals, settlements, or WU evidence.
- Do not read 88a/exam data for 09-30..10-14; do not call Polymarket from this IP outside a granted budget.
- Do not treat the swarm's own CPU/Defender readings as steady state.

## Completeness critique

**Verdict:** The synthesis answers "state" well, "efficiency" partially, and "which markets" with a scorecard whose ranking it then does not follow; its disk arithmetic rests on an unverified 91a throughput that the code's own per-night file cap likely invalidates.

1. **91a backlog "≈15 nights" is probably wrong by an order of magnitude.** `cold_snapshot_nightly.py:28` caps `MAX_FILES_PER_NIGHT = 8192`; the synthesis's only measured sample has a median file of 0.18 MB. 8,192 × 0.18 MB ≈ 1.5 GB logical/night unless large files dominate bytes — the 32 GiB budget would then never be reached, and the "+8.6 → +2.3–4.1 GiB/day" steady state is ESTIMATED on a cap that may not bind. The first receipt (task `WeatherColdSnapshotNightly` Running since 00:30 today, result pending) must report which cap stopped it before any date in (B)/(E) is believed.

2. **The "unresolved 64 vs 256 MiB conflict" is resolvable by reading code and should not have been left open.** The nightly lane selects with its own `MAX_FILE_BYTES = 256*MIB` (`cold_snapshot_nightly.py:25,91`) and compresses via `opener=LARGE_OPENER` (`:142`); the 64 MiB/30-day validator (`cold_snapshot_compression.py:96,108`, importing `ntfs_file_compression.py:15`) governs the manual batch lane. 88 MB `clob_tokens.jsonl` is eligible tonight (MEASURED by code).

3. **Expansion is never tied to the project goal.** Owner canon: model → fair value → domain-neutral maker. The scorecard has no "do we have a free fair-value input" axis; lowest-temperature has no model at all (the pipeline is a daily-high model; only EF §10k notes NBM minimum tokens exist). Settlement sources for Shanghai/Seoul/HK WU stations are UNVERIFIED. No $/day revenue estimate accompanies any top-3 pick, so "most efficient" cannot be judged.

4. **Scorecard and Top-3 disagree.** Monthly precipitation scores 19 and Kp 18, yet foreign highest (17) and MrBeast (18) are promoted over them with no stated tiebreak. Either the weights are wrong or the ranking is post-hoc.

5. **Most likely wrong recommendation: RAM to 48 GB (F10, lever 14).** The synthesis itself measures RAM/commit as "large headroom" (8.3 GB free, commit 33%). It costs a capture shutdown and ~$300–450 CAD to relieve a non-binding constraint, while the binding one (disk, no second disk per 09-23) gets "hold". The structural fix — closed-day export lane (lever 12) — is ranked 12th with no owner or date.

6. **Authorization chain inconsistent with DECISION_LOG.** Row 83 (MEASURED) says REVOKE v1 / APPROVE **v2** are appended once the verifier binds a second clarification; the synthesis says REVOKE v1 / APPROVE **v3**. Skipping v2 needs an explicit owner row, otherwise the C2 row's conditional stands and conflicts with `authorization.py` `CLARIFIED_IDS` (v2 and v3 both defined, C3 constant `PENDING_OWNER_SIGNATURE` CONFIRMED on `6ac18be7e`).

7. **Re-run script pin CONFIRMED but mislocated.** `C:\tmp\agent-kit\run_rerun_111k.ps1:3` pins `6e7162e8e…`; `:13` throws `exam tree head moved`; `origin/codex/integration-exam-20261002` = `6ac18be7e`. It is not a repo file, so "docs light path" cannot fix it — someone must edit a scratch script.

8. **Lever 1 labels Python PRs (#117, #120, #121) "roll-free" by hand.** AGENTS.md forbids deriving a roll verdict manually; `roll_verdict.ps1 -Branch` output is not cited. UNVERIFIED.

9. **Lowest-12 via 88a extras collides with the exam retention hold.** 88a journals are held 10-15..10-30 and feed the settlement export/universe (10-15/16). Adding conditions to the same recorder "after 10-14" risks changing the exam universe. `--extra-conditions` exists (`maker_evidence_capture.py:368`); the "cap 32" is UNVERIFIED.

10. **"Overnight" is not audited.** Today's 00:30 run is live now (CPU 1.9–2.9% sampled 00:36, python 17828/9584 started 00:30/00:35), and the swarm itself ran inside the lease window beside 91a — no note of the swarm's own cost or lease compliance.

11. **Lever 2's "83% of 88a is per-condition `/rewards`" is UNVERIFIED** — the pattern exists (`maker_evidence_public.py:151`) but no request census is cited; `/books` is already batched ×100 (`maker_evidence_capture.py:90`).

12. **Minor drift confirmed:** STATE_OF_PLAY:3,32 stale (107 GiB, `979c0e752`); free now 101.7 GiB (Get-Volume); uncommitted `config/locations.json`, `location_market_events.json`; Open-Meteo 10,000/day appears nowhere in canon (ESTIMATED from public terms).

## Architecture

**Verdict:** Capture should split into one domain-neutral *venue recorder* (the 88a pattern: change-only JSON, hourly gzip-at-write, hash manifests; MEASURED ~0.8 MB/condition-day, 47 MiB RSS, ~7% of one core for 96 conditions) that scales to ~1,000 conditions for ~1 GB/day, and a per-domain *model-evidence* lane (weather's snapshot/CLOB/obs loops, MEASURED 0.44 GiB/city-day retained, the whole 11 GiB/day problem) that stays at 12 cities until write-side levers land; nothing roll-sensitive before 10-14, and the first 91a run is in progress now (`WeatherColdSnapshotNightly` State=Running at 00:30 — its receipt sets Stage 0's numbers).

## 1. Shared layer (domain-neutral, one process family)

| Component | Design | Basis |
|---|---|---|
| Discovery registry | `config/capture_families.json`: `{family_id, domain_id, discovery: series\|tag_slug\|slug_pattern\|condition_ids, cadence_s, retention_class, quote_candidate: bool}`. Gamma discovery hourly, descriptors change-only. Replaces the 32-id `--extra-conditions` hook (`maker_evidence_capture.py:46`) and the slug-prefix `event_identity`. | 88a universe bound is 1,200 conditions (`:148`), not 32 |
| Book + terms stream | One POST `/books` per 100 tokens per minute (1,000 conditions = 20 POST/min). Venue-wide `/rewards/markets/current` every 15 min (39 pages, 6.7 MB); per-condition `/rewards` GET only for the ≤120 quote-candidate set, refreshed on Gamma `clobRewards` change. Allowlist add at `maker_evidence_public.py:67-71`. | Removes ~84% of 88a's 1.9 req/s (api report); REST limits documented 500/10 s `/books` |
| Trade stream | One market-channel subscriber per host, fan-out via local queue to execution-tape and recorder writers (5 sockets → 3, one decode pass). Non-core families get books only, no WS. | 15 GB/day inbound duplicated today; WS per-IP cap UNVERIFIED |
| Storage format | `maker_evidence_v2` journals, change-key dedup, hourly `.jsonl.gz` seal + sha256 manifest = compression-at-write. Replay envelope already carries `domain_id` streams. | 85 MB/day MEASURED for 96 conditions |
| Retention classes | **A settlement-grade** (books gz, trades, terms, settlement facts, raw `plugin_input` fetches): never shortened, exported off-host after 30 d. **B model evidence** (snapshots, variants, replay inputs, explanations): NTFS at 91a, export after 14 d, local reclaim by manifest. **C diagnostics/status**: rotate+gzip, 7 d. | storage report levers 2/3/5 |
| Status writes | One status JSON per process, ≥5 s throttle, per-family counters incl. req/s and HTTP 429/timeout counts, written via the 1 s grouped writer (`execution_tape_io.py`). | obs-trigger 0.44 GB/day status churn |
| Request budget | One host-wide token bucket (config ceiling, start 2.5 req/s total) shared by all Polymarket callers; exceeding it degrades cadence, never bursts. | IP shared with capture; one 429 costs evidence |

## 2. Per-domain (plugin-owned)

Universe slug rules; `plugin_input` fetch list (public URL allowlist: WRH/IEM METAR, NBM, SWPC Kp, USDM CSV, Netflix TSV, YouTube Data API); settlement adapter; fair-value provider; info clock; and — weather only — the obs trigger and 10-min model snapshot children. New families get **no** model-evidence lane until a desk study earns it.

## 3. Where it runs (authority)

- **Production 16 GB host:** venue recorder (class A for every family), weather obs/snapshot loops, Stage-A, 91a, class-A/B export sealing. Only it holds Scheduler, production-state and capture authority. Memory stays <0.5 GB extra at Stage 2 (recorder is one process).
- **32 GB workstation:** desk studies, plugin development, training, replay, bounded suites, consumer of the closed-day export lane. **Not** a capture host (registry admits only `capture_colocated_v1`/`portable_execution_v1`; `DELEGATION_CONTRACT.md:67-70`). The mirror stays frozen; the export lane (hashed bundles, 88a-style receipts) replaces it.
- **Third box (owner decision, after 10-15):** capture-only mini-PC on the LAN (Windows stack unchanged, shares IP) or VPS (separate IP, Linux port). Runs the recorder for non-weather families if host disk or the IP budget binds at Stage 2. Live execution from it is forbidden by the attestation literal; it holds no credentials.

## 4. Overnight lease timetable after expansion (local, serial)

| Time | Job | Change |
|---|---|---|
| 00:05 | host health watchdog | — |
| 00:30 | 91a NTFS nightly (32 GiB budget) | elapsed MEASURED from tonight's receipt; if >2.5 h, reduce budget to 16 GiB on suite nights |
| 04:15 | training restore | — |
| 05:00 / 06:00 | CLOB tiering / raw-tape tiering (+~25 s per city) | unchanged until lever 4 (gzip raw books at hour close) makes 06:00 a no-op |
| 06:50 | economics snapshot | — |
| **07:00 (new)** | closed-day export sealing (class A >30 d, class B >14 d) + manifest reclaim | roll-free `.ps1` + packaged CLI; bounded to 20 min |
| 08:10 | staleness sweep | — |
| 09:30–11:55 | Stage-A (outside lease) | must go incremental (#117) before any city is added |

Recorder gzip seals are hourly and need no lease. The bounded test suite leaves the host (CI + workstation), removing the 00:30 collision.

## 5. Staged migration and capacity

**Stage 0 — now to 10-14, roll-free only.** Read tonight's 91a receipt; recompute net GiB/day from the trail. Land roll-free PRs #117, #120, #121. Write `capture_families.json` schema + docs, recorder design, export-lane runbook. Desk studies on workstation (lowest-temp hour-of-minimum, USDM, Kp, Treasury ladders, App Store RSS). *Capacity:* 101.3 GiB free; net +8.6 GiB/day pre-91a; 91a reclaims ESTIMATED ~20 GiB/night over ~15 nights if 3:1 holds on big files (UNVERIFIED — measure). Floor at 50 GiB ≈ 6 days without 91a.

**Stage 1 — first quiet window after 10-14.** Merge #118/#119 (CLOB write-on-change, snapshot tail reads: −1.5 GB/day writes, −5% core, −563 GB/day reads), the per-market fast interval (owner cadence decision; −2 GB/day), and the `/rewards` change-trigger (88a 1.9 → ~0.3 req/s). Add the 12 `lowest-temperature` slugs as recorder-only conditions. *Capacity:* +120 conditions ≈ +0.1 GiB/day on disk, +~1.5 req/s raw polling (net fleet still below today's 3 req/s after the `/rewards` fix); disk net falls to ESTIMATED +5 GiB/day pre-91a, +1–3 after.

**Stage 2 — November.** Lift `EvidenceStore/PublicReader/PublicStream` into a neutral `capture_core` package, one recorder process, families: lowest-45, top-6 foreign highest(+lowest), Kp, monthly precipitation, USDM, MrBeast (owner's plugin #2), Treasury ladders passive. *Capacity:* ~1,000 conditions → 20 POST/min + 15-min reward sweep ≈ 0.5 req/s; ESTIMATED 5–6 GB/day wire, ~1 GB/day on disk; RAM +0.3 GB; lease +0 (hourly seals). WS stays at 3 connections (weather only). If the IP budget or disk-day trail low falls, move non-weather families to the third box.

**Stage 3 — after storage levers 1b/2/3 (per city 0.44 → ~0.08 GiB/day) and Stage-A incremental.** Promote up to 6 cities (top foreign pools) into the model-evidence lane. *Capacity:* 18 cities ≈ +1.5 GiB/day retained, Stage-A +~35 min only if incremental landed. Without the levers, +6 cities ≈ +85 GiB standing over 30 d — refused.

**Stage 4 — plugin quoting.** Only after replay exam (10-15..10-31) and the desk-study falsifiers; the recorder's class-A journals are what the plugins replay.

**Hard guards throughout:** no capture-path module change before 10-14; every stage adds a receipt (`data/capture_families/<date>/receipt.json`) with req/s, GB/day, 429 count; abort a stage when the 24-h trail low drops below 70 GiB or any 429 appears.

## Census summary

**Verdict:** Snapshot 2026-10-02 03:59:59Z–04:13:34Z (97 of 150 GETs, all HTTP 200, 1.6 s spacing, 405 MB saved): the temperature complex pays ~15.2k USDC/day across 49 cities × {highest, lowest}; our 12 captured cities take ~2.8k/day (18%) — the cheapest expansion is the 37 registry cities and the new **lowest-temperature** variable we do not capture or mention anywhere in the repo.

## Method and coverage (MEASURED unless marked)

- Gamma `/events/pagination?active=true&closed=false` → `totalResults: 20330` active events (1 GET). Full enumeration is impossible in budget (100/page cap; `limit=500` returned 100).
- Sample: top ~2,100 events by `volume24hr` (ordering stops at offset 2,100 — UNVERIFIED whether that is "all events with non-null 24h volume"), top 1,200 by `liquidity`, all 321 `tag_slug=weather`, 500 newest, 200 default-order → **3,268 unique events, 68,124 markets, 52,921 live** (active, not closed, acceptingOrders≠false). Sample 24h volume $38.1M, liquidity $682M.
- CLOB `/rewards/markets/current`: 38 pages, **19,056 reward rows, 228,899 USDC/day** active rate (date-filtered configs). 8,838 (180,897/day, 79%) matched a live sampled market; top 480 unmatched looked up via `/markets?condition_ids=` (12 GETs): all 480 live, 18,410/day — long-tail small events (Treasury-yield ladders ~4,000/day, median home values, AI-lab rankings, Core PCE, White-House "full lid"). Remaining 9,738 unmatched carry 29,592/day, mostly 1–5/day each.
- Reward terms, all 19,056: `rate_per_day` mode 1 (6,893), 5 (3,687), 3, 2; `max_spread` 4.5c in 79% (6.5c 8%, 5.5c 7%); `min_size` 20 in 80% (50: 11%). Reward by series recurrence (live sample): one-off/none 130.5k, monthly 20.6k, daily 19.6k, weekly 9.5k /day.

## (a) Tag table (live sampled markets; an event counts under every tag it carries)

| tag | events | markets | vol24 $ | liq $ | rw mkts | rw/day | mode min/spread |
|---|---|---|---|---|---|---|---|
| sports | 959 | 37,689 | 13.0M | 230M | 3,129 | 16,527 | 20 / 4.5 |
| politics | 811 | 5,808 | 12.3M | 360M | 2,160 | 85,085 | 20 / 4.5 |
| recurring | 978 | 6,152 | 10.0M | 38.7M | 1,532 | 41,841 | 20 / 4.5 |
| games (sports games) | 735 | 32,508 | 9.8M | 142M | 83 | 991 | 20 / 4.5 |
| elections | 535 | 4,210 | 5.2M | 290M | 1,341 | 21,482 | 20 / 4.5 |
| geopolitics | 240 | 998 | 4.4M | 29.1M | 528 | 15,073 | 20 / 4.5 |
| crypto | 645 | 2,039 | 4.4M | 31.9M | 748 | 3,967 | 30 / 4.5 |
| economy | 71 | 478 | 3.2M | 13.5M | 222 | 6,624 | 20 / 4.5 |
| tech | 180 | 1,792 | 1.6M | 41.4M | 675 | 69,733 | 20 / 4.5 |
| ai | 146 | 1,393 | 1.6M | 24.1M | 589 | 53,025 | 20 / 4.5 |
| **weather** | **321** | **2,931** | **1.53M** | **8.2M** | **715** | **21,000** | **20 / 4.5** |
| daily-temperature | 223 | 2,417 | 1.48M | 7.1M | 421 | 15,217 | 20 / 4.5 |
| finance | 158 | 1,397 | 1.5M | 24.7M | 875 | 30,296 | 20 / 5.5 |
| pop-culture | 132 | 1,470 | 1.4M | 16.6M | 561 | 12,168 | 20 / 6.5 |
| midterms | 288 | 1,331 | 1.6M | 33.7M | 677 | 12,381 | 20 / 4.5 |

Weather = 4.0% of sampled volume, 9.2% of all reward rate. Captured-12 (highest only): 36 events, 396 live markets, vol24 $506k (33% of weather volume), liq $1.9M, 2,399/day.

## (b) Top non-weather reward markets

The top 26 are two one-off families: **"<State> enacts data center moratorium by…"** (OK, LA, MO, IN, OH, TX; 2,000/day each on the 2026/mid-2027/2027 legs, 1,000 on 2028; min 50, spread 5.5c; mids 0.06–0.48; vol24 $0–88k) = 42,000/day, and **"<Co> announces bankruptcy by…"** (Anthropic, CoreWeave, NuScale, Payward; 2,000/day per leg, min 200/50, spread 4.5c, mids 0.05–0.23) = 16,400/day. Together 25% of all reward money. Then:

| rate/day | min | spr | mid | vol24 | end | question |
|---|---|---|---|---|---|---|
| 1,314 | 200 | 4.5 | 0.635 | 27k | 11-04 | 2026 Balance of Power: D Senate, D House |
| 1,059 | 200 | 4.5 | 0.295 | 32k | 11-04 | Balance of Power: R Senate, D House |
| 1,000 | 200 | 2.5 | 0.745 | 805k | 10-29 | Fed no change Oct 2026 (fomc, monthly) |
| 1,000 | 200 | 2.5 | 0.245 | 567k | 10-29 | Fed +25 bps Oct 2026 |
| 1,000 | 200 | 4.5 | 0.165 | 159k | 11-01 | Israel accuses Iran/proxies of plane stabbing by Oct 31 |
| 1,000 | 100 | 4.5 | 0.415 | 45k | 02-01 | Any of the Cornell 7 charged… |
| 634/616 | 100 | 6.5 | 0.40/0.61 | 339k/353k | 10-05 | Lula / Flávio Bolsonaro win Brazil 2026 |
| 500 ea | 100 | 6.5 | — | 92–262k | — | Senate OH/TX winner, next French president, next Israeli PM |

Non-weather recurring families by reward/day: fomc 2,400 (monthly); who-trump-insult 1,676, trump-praise 1,108, trump-insult-on 798, trump-talk 599 (monthly); who-attends-US-Iran-talks 1,820; Israel-action-against-Lebanon-by-day 1,500 (31 daily legs); DWTS eliminations 1,003 (weekly); US-Iran ceasefire 884; best-ai-company 800; **MrBeast views 800 monthly + 300 weekly**; Saudi-Yemen action 780; cfb-2026 706; rogan-mentions 375; elon-tweets 300; truth-social posts 400 (daily); wti-daily-close 450; crude-oil hit 520; ewy/abnb/coin hit-price 300–500. Full list: `analysis_v2.txt`.

## (c) Recurring families (series `recurrence`, live sample)

Daily: 35,055 markets — sports game books (nfl-2026 6,867 mkts/$2.6M; cfb-2026 12,570/$1.3M; wta, atp, nhl, UNL/CONCACAF soccer, Brazil Série B, LoL, Valorant), crypto hit-price daily plus 5m/15m/hourly up-or-down (0 reward), **49 `<city>-daily-weather` + `<city>-daily-lowest-temperature` series**, rain-daily (14 cities, 555/day), wti-daily-close (450), geomagnetic-storm daily (200), truth-social posts. Weekly: elon-tweets, white-house tweets, BTC/ETH multi-strikes, **drought-d4-weekly (40 states, 1,184/day) + ag-commodity-drought-weekly (8 crops/livestock, 813/day)**, DWTS, rogan-mentions, Netflix #1 show, Bab-el-Mandeb transits (400), ewy weekly. Monthly: fomc, BTC/ETH/WTI/ABNB/COIN hit-price, Trump insult/praise/talk/companies, best-AI-company/lab rankings, **monthly-precipitation (NYC, London, HK, Seoul, Seattle; 200/day each)**, MrBeast views, Treasury-yield high/low ladders (2y/5y/10y/30y, ~450/day each), median home value by metro, Core PCE, US tornadoes, Mt Washington wind, global temperature anomaly.

## (d) Weather families we do not capture

- **37 more cities with `highest-temperature` events** (all already in `config/locations.json`, 51 ids; jinan/zhengzhou stale since May). Snapshot reward/day for Oct-2+Oct-3 events (highest+lowest): shanghai 1,000; seoul, london, paris 600; tokyo 400; hong-kong 399; munich 301; most others 300 (singapore, kuala-lumpur, manila, panama-city highest-only ~200–295); wellington 100. Non-captured highest: 37 events/day, 407 live markets, vol24 $691k (Oct-2), 6,918/day; versus captured-12 highest 1,200/day (100/city). **Timing caveat:** HK/Tokyo Oct-2 showed 0 reward at 12:00 local — pool moves intraday; EF §10a's 2,800 same-day / 4,800 all-active for our 12 is consistent with this snapshot (2,399 + 400 lowest). Rewards sit on 2–5 of 11 bands per event, not all bands; event-day `min_size` rises to 100 for several EU/other cities.
- **`lowest-temperature-in-<city>` — 45 cities incl. all 12 ours.** Zero hits for "lowest" in `docs/operations`, `config`, `src`. Pool 1,999/day (Oct-2+3), vol24 $69k, liq $1.2M; min 20, spread 4.5c, 11 bands, same WU stations → marginal capture cost is one more event slug per city.
- Other weather series with rewards: where-will-it-rain daily (14 cities, 555/day), monthly precipitation (1,000/day), US Drought Monitor D4 by state + ag drought (≈2,000/day, weekly Thursday release), first-snow 2026 (31 cities, 110/day), geomagnetic storm level daily (200/day, NOAA Kp), hurricane/typhoon intensity (Rachel, Nolo, Choi-wan; 50–100/day), Bangkok 24h rainfall (100), Mt Washington wind, San Diego sea level (155), river levels (Rhine 200, Danube/Mississippi 50), earthquakes weekly (50–70; USGS), El Niño RONI. None requires paid data (ESTIMATED: all settle on public NOAA/USGS/USDM/WU-type sources — resolution text not read for each).

## Recommendations

1. Capture-side cheapest win: add `lowest-temperature` slugs for the 12 cities (same stations, same obs pipeline) and the Shanghai/Seoul/London/Paris/Tokyo/HK highest+lowest events (≈3.6k/day at snapshot vs our 2.8k). Disk/CPU cost per city-day is the known ~11 GiB/12 cities ≈ 0.9 GiB/city-day before compression (ESTIMATED from context).
2. Research-side: the structurally similar non-temperature families (rain-daily, D4 drought, geomagnetic Kp, monthly precipitation) are public-instrument, time-decided markets like ours; combined ≈3.8k/day. MrBeast views (owner's plugin #2) pays 1,100/day today.
3. Flag: 58k/day (25%) sits in two one-off legislative/bankruptcy families — likely sponsor-driven and transient (UNVERIFIED); do not plan around it.

## Raw data

`C:\Users\micha\AppData\Local\Temp\claude\C--Users-micha-Desktop-github-weather\2184e0ab-b64e-44aa-95c1-ec99eb4fd436\scratchpad\market-census-20261001\` — `index.jsonl` (97 rows: n, url, time_utc, status, sha256, file, bytes); `001-002-events-*.json`, `003-events-pagination-probe.json`, `004-041-rewards-current-p0..37.json`, `042-064-events-vol24-o*.json`, `065-076-events-liq-o*.json`, `077-080-events-tag-weather-o*.json`, `081-085-events-newest-o*.json`, `086-097-markets-lookup-b1..12.json`; derived: `live_markets_projection.json`, `lookup_projection.json`, `analysis_v1.txt`, `analysis_v2.txt`, `analysis_v3.txt`; scripts `fetch.ps1`, `analyze.py`, `analyze2.py`, `analyze3.py`. Endpoint shapes taken from `src/weather/market/maker_evidence_public.py:20-68,146-178`, `src/weather/market/exchange_economics.py:45-46,492-532`, `src/weather/operations/location_config_refresh.py:22-77`.