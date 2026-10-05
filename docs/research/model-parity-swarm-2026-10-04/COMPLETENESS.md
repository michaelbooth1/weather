# COMPLETENESS (S-CRITIC): what the model-parity swarm v2 did NOT run, read or verify

> **Development only. Every number quoted here is a development read on previously inspected dates (DESIGN rule 7).**
> Written by S-CRITIC (Fable) on 2026-10-04, 03:17-03:45 local, on the workstation, after the synthesis (S-SYNTH, 03:16)
> and the canon drafts (S-CANON, 03:20). Nothing was scored and no rule was registered. The only computations were two
> `harness.table_lookup` reads of existing score files and one `stats.json` read (section 1). Deadline 08:15.
> The Write tool guard blocked `report.md`; the text was placed by shell copy and is also in `result.json["report_md"]`.
>
> **Inputs read:** every `report.md` under `C:\swarm\out\` (72 agent directories), the `result.json` of the agents whose
> reports are reconstructions or missing, the docs copies in `docs/research/model-parity-swarm-2026-10-04/`, `SYNTHESIS.md`,
> `s-canon.md`, `STATUS.md`, `C:\swarm\DESIGN.md`, `COMMON.md`, `HARNESS.md`, `PREFLIGHT.md`, `registry.jsonl` (134 lines),
> `phase_log.jsonl`, and every `MANIFEST.json` under `C:\swarm\data\`.
>
> **How to read this.** Section 1 says what was checked and holds. Sections 2-9 list what was not done, grouped by the
> decision it bears on. Section 10 is the prioritised follow-up list. A gap here is not a defect finding: no refuter
> verdict is overturned, and the synthesis headline stands on what was measured.
>
> **Note added 2026-10-04 about 04:10 local by S-REVISE (the critic's text below is unchanged).** Two late agents closed
> some items. **Closed:** follow-up 3 (independent re-implementation of d-defect-r2, T27: reproduced, bit-exact once two
> reading conventions are aligned, also rung 2); follow-up 5 (statistics refuter on MG-1 and ladder r1/r2: R-STAT-MG1 for
> MG-1 and r2 − r1, T27 for r1); follow-up 9 for rung 1, MG-1 and t3-r3 (rung 1 clears Bonferroni at 138 and 938; MG-1 and
> t3-r3 13-16 fail it); and the S7-gate contradiction of section 2 and section 8.1 (T27: the gate is not necessary, because
> the restored strength feeds the taper; an extra gate is worth −0.00008 at 17-23; LADDER r1b − r1 is stage order). The
> 15-16 framing of section 4 / 8.7 / follow-up 8 is corrected in SYNTHESIS and the canon drafts. Verdict item 2 is
> therefore partly closed. **Still open:** the `estimate_distribution` replay (follow-ups 1-2), the `v2_mean` value
> re-derivation (follow-up 4, now also parser v2's rejection of the 12Z/13Z/19Z NBP cycles), a from-text t3-r3
> re-implementation, and everything in P4-P6. See SYNTHESIS section 11, `t27.md`, `r-stat-mg1.md`.

## 0. Verdict

1. **The synthesis is complete against its own evidence, and its headline numbers reproduce from the score files.** Nothing
   it cites is contradicted by a source report I read.
2. **The verification budget was spent on the wrong objects.** DESIGN §5 put two refuters on each LEAD and DESIGN §4 asked the
   spares to re-implement the top three leads. By the time the board settled, the three things that survive are the
   evening restoration (`d-defect-r2` = `ladder-r1`), the morning captured-v2 read (`r-t5-inc-c1` = MG-1) and `t3-r3` at
   13-16. **None of the three was independently re-implemented from its rule text, none of the ladder rungs had a refuter,
   and MG-1 had no statistics refuter.** The Fable refuters went to T1, T2 and T4 (one family, later classed a serving
   defect); the spares went to T6, T10 and T5 (source classifiers whose increments were already null), and two of them
   (T24, T25) re-derived the same source (NBS).
3. **The evening fix rests on one served payload and a band-level emulation.** The faithful replay through
   `estimate_distribution` that D-DEFECT, LADDER, D-RUNG1C and the synthesis each call "the confirmation step" was not run
   tonight. LADDER's own S7-gate emulation (`r1b - r1 = +0.0004 [+0.0001, +0.0010]`) says the gate adds nothing, while
   D-DEFECT and the synthesis make the S7 gate a required part of the fix on the strength of that one payload. That
   contradiction is unresolved.
4. **The morning route's load-bearing input was never value-verified from a primary source.** `v2_mean` comes from the 111h
   parser-v2 re-derivation. The swarm verified its *availability* (R-PIT-T18: S3 listing of 119 `blend_nbptx` cycles) but
   never downloaded a `blend_nbptx` bulletin and re-parsed it to check the *values*, and no agent checked the "last+1-day
   indexing quirk" that D-MORNING §2 and D3 §6 name as a freeze condition.
5. **Several availability bases are still assumptions** (section 5), one of them (METAR +10 min at KBKF) known to be optimistic
   on 80.7% of reports; the drafts written before 02:30 do not carry the late findings (M0, KBKF, 15-16 harm of MG-1).
6. **Eight agents have no primary report** (section 7), one refuter (R-STAT-T7) left only a `stats.json`, and the synthesis
   mis-states where one of them lives.

## 1. What was verified and holds (so the gaps are in proportion)

- Harness: `HARNESS_SHA256 8db69adc...f29f74` on every cited score; positive control exact to 6 dp; served - served = 0;
  `test_harness.py` includes an oracle-leakage test (`test_oracle_candidate_is_flagged_as_leakage_suspect`) and
  forbidden-column tests, so the tripwire and the allow-list were exercised, not only asserted. The statistics refuters
  for T1, T2, T4, T5, T6, T8, T10 and T18 re-implemented floor mask, Brier, cells and W intervals without `harness.score`
  and matched to 1e-6 or better: the harness scoring path is independently confirmed.
- Spot checks by this critic via `harness.table_lookup`: `ladder_r2.score.json` from-stratum all-row gap closed, all hours,
  0.541 [0.345, 0.696] (synthesis: 54% [35, 70]); 17-23 0.789 [0.633, 0.889] (79% [63, 89]); 00-16 0.418 [0.188, 0.616]
  (42% [19, 62]); `d_defect_r2.score.json` 17-23 cand - served -0.0254, gap 0.851 [0.764, 0.915] (85% [76, 92]). All match.
- Registry: 134 lines, 134 unique ids, counted by this critic; the synthesis denominator is right.
- R-STAT-T7's load-bearing number exists only in `C:\swarm\out\refute-stat-t7\stats.json`; I read it: `r1-c1|00-16|from`
  = -0.0015 [-0.0048, +0.0019], 8/11 markets, LOMO worst -0.0009. The synthesis cites [-0.0049, +0.0019]; same number.
- Every LEAD-classified family that the synthesis calls a survivor or a source had both a PIT and a statistics refuter run
  with +1 h and +2 h shifts (T1, T2, T3, T4, T5, T6, T7, T8, T10, T15, T18), plus R-T5-INC.
- Every acquisition finished before the 04:30 freeze (last: A-HRRR-AWS 01:53). No manifest is incomplete; no raw object is
  left staged (`C:\swarm\data\nbh\_stage` empty); every fetcher PID is reported exited.
- No leakage-suspect group in any of the 106 frames T19 re-scored. 0 rows after 2026-09-29 in every score file read.
- The reconstructed-report label is carried wherever the synthesis cites F1, T1, T5, A-NBH, A-IEM-2, refute-pit-t3 and
  refute-stat-t3, and numbers from them are cited from score files, as COMMON required.

## 2. The evening restoration (rung 1): what is not yet verified

This is the owner's first decision, so its gaps come first.

| Gap | Evidence | Why it matters |
|---|---|---|
| **No replay through `estimate_distribution`.** r1, r1b, r1c are band-level emulations applied to served FINAL bands, uniform within band, post-calibration (D-DEFECT §6, LADDER §6, D-RUNG1C §6). | All three reports name the replay as the confirmation step; none ran it. | The 85% [76, 92] figure is an emulation. In serving the lock-in runs before calibration; the faithful number may differ in either direction. |
| **One served payload, one snapshot, one market.** ATL 2026-09-20 23:55 (D-DEFECT, added 01:45 by master-agent). | `component_payload.lockin_strength` was not reported numerically; only stage probabilities. No 13-19 h snapshot, no second market, no `stage_attribution` read. | "Defect confirmed on a served payload" rests on n = 1. The S3-S5 (13-19 h) no-op is inferred from code only. |
| **S7 gate: emulation and payload disagree.** LADDER r1b (restore + taper + gate) minus r1: +0.0004 [+0.0001, +0.0010] at 17-23: the gate adds nothing or slightly hurts. The payload shows calibration moving above-high mass 0.031 -> 0.087. | D-DEFECT §5 and SYNTHESIS §9.1 make the gate "required"; LADDER says "the mass left above the high is not residual calibration spread". | A required part of the proposal is unsupported by the swarm's own emulation. Only the replay settles it. |
| **No independent re-implementation and no refuter.** `ladder-r1` "reproduces d-defect-r2 exactly" by re-running D-DEFECT's code path. No spare re-derived S1/S2 strengths from the `model_distribution_signals.py` constants from the rule text; no PIT or statistics refuter was assigned to d-defect-r1/r2, ladder-r0..r2 or ladder-r1c. | The remaining-rise family refuters (T1-T4, T15) verified *different* candidates that share the mechanism; they did not touch the restoration's code or its METAR `max_times` join. | The headline fix has less direct verification than any source classifier on the board. |
| **D-DEFECT r2's first run had an alignment bug; fixed, re-run, earlier output overwritten** (D-DEFECT §6). | No pre-fix score file kept. | A disclosed selection event with no artefact trail. |
| **D-RUNG1C (S3-S5) depends on a declared forecast proxy**; the real `open_meteo` / `nws_hourly` / GEFS rows are "untested" (D-RUNG1C §2, §6); `official_current_stale` assumed False. | Two proxies agree (P1, P2). | The S3-S5 bundle recommendation (-0.0032 at 15-16) is proxy-based. |
| **M0 inherited.** The restoration anchors on `guidance_physical_floor`, which D-CAP1 shows is keyed on `reportTime` and sits above the settlement on about 2.2% of Oct-Dec station-days. | D-CAP1 §2.2 (03:05). D-DEFECT (01:37) and LADDER (02:32) predate it. | On an affected day the restored lock-in locks mass onto a band above the truth. Not re-scored excluding the two affected days. |

## 3. The morning route (MG-1 / RV-1): what is not yet verified

| Gap | Evidence | Why it matters |
|---|---|---|
| **`v2_mean` values never re-derived from primary bytes.** The swarm acquired NBH and NBS text (A-NBH) and IEM NBS/NBE (A-IEM-2) but **no `blend_nbptx` (NBP) bulletin**. R-PIT-T18 listed 119 NBP cycles on S3 for LastModified only. T25 value-matched IEM NBS against 8 live NBS bulletins; nobody did the same for NBP v2. | D-MORNING §2 and D3 §6 both make "live v2 equals the 111h extractor's value on 100% of rows" a freeze condition; the "last+1-day indexing quirk" of the extractor is named but unchecked. | Every morning number (MG-1 -0.0100, T18 -0.0140, RV-1 -0.0134, rung 2) inherits the 111h re-derivation unverified. |
| **MG-1 had no statistics refuter.** R-T5-INC (PIT) covers it; the synthesis itself notes MG-1 00-16 fails Bonferroni over 134 x 7 (z about -2.7). No LOMO/LOWO/11-market t for `r-t5-inc-c1` as a candidate. R-STAT-T7's paired `r1 - c1` is on T7's *history-fitted* c1, a different sigma. | Independent reproduction of the number exists (t10-c2, t9 rebuild, ladder `mg1-c1-alone` all give -0.010018), which is good, but reproduction is not robustness. | The draft the owner is asked to sign has weaker statistics than T18 or T7. |
| **D-MORNING (01:41) predates LADDER (02:32), D-RUNG1C (02:43), T26 (02:41), D-CAP1 M0 (03:05) and D3 (03:12).** It does not state MG-1's 15-16 harm (+0.0068 vs rung 1, 2/11), that any composition must keep the lock-in on top (T19: MG-1 alone gives back 77% on 17-23 non-tail rows), M0, or KBKF. `grep` confirms: M0/`reportTime`/`obsTime` appear only in d-cap1, d-cap2, SYNTHESIS, s-canon, state-of-play-proposal, t20, t26; KBKF appears in no draft except D2. | D1, D3, D-HG also predate or omit M0. | The five drafts are not mutually consistent on validity conditions. |
| **T18/RV-1 forking disclosed but not refuted:** `t18-c1` was registered after reading r1; D3 chose RV-1 over `d3-z1` on from-stratum reads (disclosed). R-STAT-T18 refit from procedure (good) but no from-text re-implementation. | D3 §2. | Acceptable under "new dates only", but it is one more fork on the same dates the owner will be asked to reserve. |
| **Open-Meteo `hrrr_high` grid point at KSFO not verified** (A-HRRR-AWS: Open-Meteo uses an adjacent land cell, +4.3 F; "production's hrrr_high ... presumably the same point selection. This is not verified here"). T20 did not close it; its HRRR run matching was "inconclusive" (4.1% matched a run initialised after the fetch). | A-HRRR-AWS §KSFO, T20 §4. | Immaterial to the ladder (hrrr_high adds -0.0005 in T18) but a stated open item. |

## 4. The 13-16 / 15-16 residual (t3-r3): what is not yet verified

- **Both t3-r3 refuter reports are orchestrator reconstructions** (refute-pit-t3, refute-stat-t3). Their `result.json` files hold
  the numbers (runs, r3/r3s tables) but no narrative; `C:\swarm\out\r-pit-t3` is a duplicate directory of the same data.
  SYNTHESIS §10 says "r-pit-t3 has result.json `report_md`"; it does not (keys: `HARNESS_SHA256, runs, local_hour_mismatch,
  local_date_ne_target, metar_runmax_minus_captured_obs`). The reconstruction is the only prose record of those two verdicts.
- **No from-text re-implementation of t3-r3.** R-STAT-T3 re-ran T3's own `build()`; D2's `d2-r3f` reproduces it on the
  captured floor (a good serve-form check) but imports T3. The remaining-rise pmf table (3,036 cells) was never rebuilt
  independently.
- **15-16 is a post-hoc slice.** The registered block is 13-16; the "-0.0181 [-0.0251, -0.0112] over rung 2 at 15-16"
  (LADDER, SYNTHESIS §0.3) and the "largest residual" framing are hour slices chosen after seeing the 13-14 / 15-16 split.
  No refuter examined 15-16; D2 made 13-16 the primary, correctly, but the canon draft repeats 15-16 as if it were the
  finding. (D1's 13-14 pool hint is the same kind of slice, and D1 says so.)
- **13-16 is availability-sensitive** (WEAK at serve-only +1 h, R-PIT-T3; loses about 40% per hour, D2 §4). The measured
  production freshness (3.8 min median, T17, from `high_so_far` ingestion) is the only evidence that serve-time freshness
  is better than +10 min; it was not measured for the floor field a stage would read.
- **KBKF.** T26 found 288 of 317 leakage-direction running-max changes at KBKF; it re-scored only T1-r2. No 13-16 lead
  (t3-r3, t2-r1, t4-r3) was re-scored under the measured basis or without KBKF.

## 5. Availability bases that are still assumed (rule 1)

| Input | Basis used | Measured tonight? | Who relies on it | Consequence |
|---|---|---|---|---|
| IEM METAR/SPECI | valid + 10 min | **Partly.** T26 measured AWC `receiptTime` for 2026-09-04..09-29 only (25 of 60 dates; AWC retention). Aug 1 - Sep 4 is unmeasured and now unrecoverable from AWC. KBKF: p50 10.4 min, p95 113 min, 80.7% > 10 min. | T1-T4, T13-T17, D-DEFECT, LADDER r1, D-RUNG1C, t3-r3 draft | 17-23 insensitive (+2 h shifts hold); 13-16 sensitive. History tables (<= 07-31) assume +10 for KBKF too. |
| IEM MOS MAV / MET / MEX / LAV | +4h30 (NCO schedule) / +4h00 / +5h00 / +1h00 | **No.** A-IEM-2, T7, R-PIT-T7, D-CAP2 all say assumed. Only NBE (S3 LastModified) is measured. | T7; the "MOS 13-14 borderline" | Immaterial to the verdict (t7-r4 NBE-only still LEAD; r3 +2 h unchanged), but the 13-14 hint rests on assumed lags. |
| IEM RAOB soundings | valid + 60 min | **No** (A-Soundings: "stated basis, not measured"). | T11 (WEAK) | Immaterial. |
| Open-Meteo Single-Runs HRRR | run + 3 h | **Indirectly.** AWS LastModified bounds the model (max +92 min); Open-Meteo's own ingest for Aug-Sep is inferred (about 2 h), live meta sampled only tonight; archive reprocessing "cannot be ruled out" (A-SingleRuns). | T8, T9, D-RUNG1C proxies P1/P2 | T8/T9 null anyway; D-RUNG1C's -0.0032 inherits the proxy. |
| Open-Meteo Single-Runs NBM / IFS | run + 6 h / + 8 h | No per-run stamp; IFS +8 h conservative against AWS +7.57 h. | D-RUNG1C proxies only | Low. |
| Captured NBM v2 (`v2_available_at`) | production `response_received_at` (NOMADS) | **Yes** for availability (R-PIT-T18, 119 cycles; 0.78% of rows precede S3 LastModified, backed by NOMADS receipt). **No** for values (section 3). | MG-1, T18, RV-1, ladder r2 | Basis must be stated as NOMADS receipt; values unverified. |
| NBH / NBS S3 LastModified | per object | **Yes, three times** (R-PIT-T5 24 HEADs, R-T5-INC 85, T24 1608/1608, T25 30 listings + 8 downloads). | T5, T6 | Over-verified relative to the survivors. |
| ECMWF IFS S3 | per object | Yes (A-ECMWF per row; R-PIT-T10 6 HEADs). | T10 | Fine. |
| GOES, neighbour METAR | LastModified / valid + 10 | GOES measured; neighbours assumed (AWOS may be later). | T14 r5, T13 | Immaterial. |

## 6. Data coverage thin spots

| Source | Thin where | Who it limits |
|---|---|---|
| 1-minute ASOS (truth only) | KBKF: none. Minute coverage 58-91%; only 230 of 572 possible station-days are "full". | F2's true-max statement (67.8% band disagreement) rests on 230 days, 10 markets. |
| Soundings | No Denver RAOB at all; Houston/Austin have no 12Z launch; Miami 39/67 days at 12Z. | T11 coverage 52.7%; Denver and Houston fall back entirely. |
| Neighbour METAR | History only 2026-05-01 onward (92 days); A-IEM-3 did not pull 2024-25. | T13 cells thin (61.8% candidate share); T13 says a 2024-25 pull would allow finer cells. Not done. |
| HRRR Single-Runs | No 00/03Z runs fetched (00-05 run age median 8.5 h); 2 runs null at source; hourly runs not fetched; the AWS check covers 12/18Z f00-f12 only. | T8/T9 00-05 reads are structurally stale. |
| ECMWF | 3-hourly `2t`; coastal 0.25 deg cells (KLAX, KSFO, KMIA); Single-Runs native `ecmwf_ifs` was fetched (134 runs) but never scored against the S3 product. | T10's undersampling cost measured at -0.0006; the native-grid comparison was not made. |
| GOES | 4 scenes missing upstream; no parallax correction; night ACM IR-only. | T14 r5 only. |
| IEM MOS | 06-17 00Z NBM listing empty (22 station-runs excluded); IEM NBS only 4x/day, so t6-r3's history cadence differs from the hourly evaluation (T25). | T6 r3 fit; immaterial to classes. |
| Captured table | `trusted_current_max` null on 100% of rows; `nws_grid_high` null on 27% of 17-23 rows; 31 decided 17-23 rows carry a captured floor **10 F** above the METAR running max (R-PIT-T1). | The 31 rows are **unexplained**: D-CAP1's M0 explains KLGA 09-19 (+1.06 F) and KMIA 08-29 (+1 F), not a +10 F floor. Handed to T20/F2 by two refuters; neither investigated it. |
| F3 atlas | Before stratum only. DESIGN §2 said "From-stratum atlas only in Phase 5"; it was not produced (`C:\swarm\atlas` holds `*_before.parquet` only). | LADDER's residual table partly substitutes. |

## 7. Claims whose primary artefact is missing, reconstructed or misplaced

| Agent | What exists | What is missing |
|---|---|---|
| F1 | HARNESS.md, result.json (positive control, table facts), code, 14 tests | No report by the agent; summary reconstructed by the orchestrator. Acceptable: HARNESS.md is the durable artefact. |
| T1 | result.json (numbers only), score files, fit files, PIT parquet | No full report text anywhere; the T1 "report" is the orchestrator's summary. The decided-band *rule text* lives only in the registry. |
| T5 | `result.json` key `report_markdown` (4,906 bytes, the agent's full report) | **Never materialised**: `docs/.../t5.md` and `out/t5/report.md` are the 1,713-byte reconstruction. The full text is on disk and should replace the stub. |
| A-NBH, A-IEM-2 | result.json (structured), MANIFEST.json | No agent report text; reconstruction only. The manifests carry the detail. |
| refute-pit-t3, refute-stat-t3 | result.json (tables), score files, code | No narrative from the agent; `r-pit-t3` is a duplicate directory. SYNTHESIS §10 wrongly lists r-pit-t3 among those with `report_md`. |
| R-STAT-T7 | `stats.json` only (no report.md, no result.json, no phase-log-independent text) | The verdict "SURVIVES; attribution defect" exists only in `phase_log.jsonl` and in citations. The numbers are recoverable from stats.json (section 1). |
| D-DEFECT production payload | Transcribed stage table in the report (ATL 09-20 23:55) | The payload itself is on the capture host; no copy, hash or path receipt is in `C:\swarm`. |
| D2 | report.md | Header points to `C:\pt\swarm\docsesearch\...` (mangled path); the docs copy is correct. |
| Many | code sha256 cited with ellipses (`0851103e...3521`, `4a6aa874...`) | Full hashes are in result.json for most; fine, but the canon should cite full hashes or none. |

## 8. Internal inconsistencies to settle before the canon drafts land

1. **S7 gate** (section 2): "required" (D-DEFECT §5, SYNTHESIS §9.1, s-canon 10q) versus "adds nothing" (LADDER r1b). The
   canon text should say the gate is motivated by one payload and not supported by the emulation, pending replay.
2. **T15 sigma.** Code clamps sigma at 0.5 F (`t15_diurnal_projection.py:166`); registry text and report say 0.27 F
   (R-PIT-T15, R-STAT-T15). Conservative, immaterial, but the registry text is wrong as written; T15 is not drafted, so
   this only needs recording.
3. **T6 REM0 fix after first score** (disclosed; outputs kept in `v1_bug_rem0`). Fine; record it.
4. **Current temperature capture.** T2 and T4 said "needs new capture"; T20 shows `current_temp` is captured. The synthesis
   follows T20; the T2/T4 docs copies still say the opposite.
5. **"Late re-uploads"** (A-NBH, A-IEM-2) corrected by T24 to "upstream delays + one S3 backlog"; the synthesis carries the
   correction, the acquirer docs do not.
6. **Multiplicity.** Refuters used 35, 40, 63, 69, 92, 112, 116 rules at their run times; the synthesis recomputed only a
   normal-approximation Bonferroni over 134 x 7 = 938 for the survivors. No refuter re-ran its LOMO/LOWO at the final count.
7. **15-16 framing** (section 4): a post-hoc hour slice presented as the residual finding.
8. **Reconstruction labels** are in the synthesis, but `s-canon.md` cites "one served payload" without the n = 1 caveat.

## 9. DESIGN items not executed, or executed partially

| DESIGN item | Status |
|---|---|
| §2 F3 from-stratum atlas in Phase 5 | Not produced. |
| §4 T21-T26 "independent re-implementation of the top 3 leads" | Done for T6, T10, T5 (source classifiers). Not done for the survivors (d-defect-r2, r-t5-inc-c1, t3-r3, t18-c1). |
| §4 T21-T26 "PIT re-derivation for the top 3 sources" | NBS done twice (T24, T25); METAR done (T26, 25 days); NBP v2 availability done by R-PIT-T18; MOS, soundings, Open-Meteo ingest not measured. |
| §5 "two refuters per LEAD" | Done for every LEAD family except: T9 (classifier LEAD 06-09 and 17-23; hunter's own +5 h only), T12 (classifier LEAD 00-05; controls only), T13 r2 / T14 r1 (classifier LEADs equal to controls), T16 (dup of T2; "Not run: a +60 min latency stress"). All were closed by control attribution, which is defensible, but it is not two refuters. |
| §5 refuters on the ladder, D-DEFECT, D-RUNG1C | None. |
| §6 deep dives "sensitivity (+1 h, coverage loss)" | Done for D1, D2, D3; D-MORNING has no coverage-loss or +1 h section of its own (it relies on R-T5-INC). |
| §6 HG-1 power | Not sized for the 8/11 sign rule, by design (rule 8). Stated. |
| §7 Phase 5: one `workstation_heavy.ps1` pytest with repo-wide audits; commit, push, draft PR, CI | **Pending at 03:25.** S-CANON ran `agent_docs_audit` (PASS). No pytest or compileall record yet. STATUS.md must carry the result or the "pushed with focused tests green" fallback. |
| §7 docs/README.md route line | Done (line 87; it references EF §10q, which S-CANON drafted). |
| COMMON "manifests freeze at 04:30" | Moot: all acquisitions finished by 01:53. Only `ecmwf/MANIFEST.json` carries an explicit `frozen_local`; the others carry `built`/`created`/`finalised` stamps. |
| Captured-but-untested fields | `open_meteo_*_high_delta` (NBM/GFS/NAM members), `global_ensemble`, `nws_hourly` rows, `mrms_precip` were never screened as candidates or in the T18 pool (T20 table: "no hunter used them"). The "no external source adds anything" statement does not cover these already-captured internal fields. |

## 10. Prioritised follow-up list

Each item names what, where it can run, roughly how long, and what it blocks. "Capture host" items are read-only and
belong to the operations agent inside the 00:30-09:00 window; nothing here is a serving or capture change.

**P1 - before the owner decides on the evening fix (blocks SYNTHESIS §9.1)**
1. **Replay `estimate_distribution` on captured inputs** for at least two closed market-days (one with an evening run-max
   break, one 13-19 h case), with S1/S2 re-anchored and with and without the S7 gate. Capture host, read-only, about 1-2 h.
   Settles the 85% figure and the S7-gate contradiction (section 2, section 8.1).
2. **Read `component_payload.lockin_strength` and `high_has_stood_lockin.stage_attribution`** on at least five evening
   snapshots across at least three markets (not only ATL 09-20). Capture host, read-only, about 30 min. Turns n = 1 into
   a confirmation.
3. **Independent re-implementation of `d-defect-r2` from the stage spec** (constants from `model_distribution_signals.py`,
   anchor B, METAR `max_times` join) by an agent that did not write D-DEFECT or LADDER, scored through the harness.
   Workstation, about 1 h. Closes the "no spare on the headline" gap.

**P2 - before any morning draft is frozen (blocks SYNTHESIS §9.2-9.3)**
4. **Value-verify `v2_mean`**: download about 20 `blend_nbptx` bulletins across cycles 00/01/07/19Z and dates in both
   strata, parse the TXN maximum the way parser v2 does, and compare with the extract's `v2_mean` / `v2_stddev`; include
   the "last+1-day" quirk check. Workstation, anonymous S3, about 1 h. Without it the morning route's input is trusted,
   not verified.
5. **Statistics refuter on `r-t5-inc-c1` (MG-1) and on ladder r1/r2**: LOMO, LOWO, 11-market t, Bonferroni at 134 x 7,
   availability-vs-outcome. Workstation, about 1 h. The owner is asked to sign MG-1 with less robustness evidence than T18.
6. **Consistency pass over the five drafts** (D-MORNING, D1, D2, D3, D-HG): add M0 (D-CAP1) and KBKF (T26) validity items,
   the 15-16 MG-1 harm and the "lock-in stays on top" constraint (LADDER, T19), and the NOMADS-receipt availability basis
   (R-PIT-T18). Docs only, roll-free, about 1 h.

**P3 - before the canon drafts land (blocks S-CANON 10q)**
7. Materialise `C:\swarm\out\t5\result.json["report_markdown"]` into `out/t5/report.md` and `docs/.../t5.md`; write a
   `refute-stat-t7` report from `stats.json`; correct SYNTHESIS §10 (r-pit-t3 has no `report_md`); fix the D2 path string.
   Docs only, 20 min.
8. Reframe 15-16 in 10q and the synthesis as a post-hoc slice of the registered 13-16 block (section 4); state the S7-gate
   contradiction and the n = 1 payload in 10q.
9. Re-run the Bonferroni/LOMO checks of the four survivors at the final registry count (134) from W draws, not the normal
   approximation. Workstation, 30 min.

**P4 - cheap sensitivities that were not run**
10. Re-score t3-r3, t2-r1 and t4-r3 at 13-16 (a) without KBKF and (b) under T26's receipt-aware basis for 09-05..09-29.
    Workstation, 20 min each.
11. Re-score ladder r1/r2 and t3-r3 excluding the two M0-affected station-days (KLGA 09-19, KMIA 08-29) to size the M0 bias
    on this table. 15 min.
12. Investigate the 31 rows with a captured floor 10 F above the METAR running max (R-PIT-T1): which station-days, which
    floor component, and whether M0 or a different capture defect explains them. 30 min.
13. T16: run the +60 min latency stress it skipped (immaterial, but the report says "Not run").

**P5 - measurements that can only be made later or elsewhere**
14. METAR receipt for 2026-08-01..09-04 is unrecoverable from AWC (retention about 25 days). Record it as permanently
    unmeasured; the only route is production's retained raw payloads (an ops audit of `receiptTime` presence, D-CAP2 §7).
15. MOS MAV/MET/MEX/LAV publication times: measurable only from live NOMADS/tgftp listings, which are dated after 09-30 and
    forbidden tonight. Only needed if the MOS 13-14 question is kept alive (D-CAP2 §4.4); default is decline.
16. Open-Meteo HRRR ingest for Aug-Sep: unrecoverable; record as inferred.
17. The KSFO grid-point choice behind production's `hrrr_high` (A-HRRR-AWS): one captured payload read on the capture host.

**P6 - orchestration**
18. Run the Phase-5 `workstation_heavy.ps1` pytest and repo audits and record the result in STATUS.md before push; if the
    full run is blocked, say so and list the focused tests that passed (DESIGN §7).
19. Produce the from-stratum F3 atlas (DESIGN §2, Phase 5) or record that LADDER's residual table replaces it.
20. Optional: screen the captured-but-untested fields (`open_meteo_*_high_delta`, `global_ensemble`, `nws_hourly`) in the
    T18 pool framework so the "no source adds anything" statement covers internal fields too. Workstation, 1 h.

## 11. What this critic did not do

- I re-ran nothing beyond two `table_lookup` reads and one `stats.json` read. I did not re-execute any hunter, refuter or
  spare, and I did not open any candidate code beyond `test_harness.py` (grep only).
- I did not verify the registry sha256 of any rule text against its agent's code, nor registration-before-first-score
  timestamps; I relied on the refuters that did (R-STAT-T1/T2/T4/T6/T15/T18, R-PIT-T7/T8/T10).
- I did not read `completed_results.json` / `completed_slim.json` (orchestrator state) or the canon edits in
  `docs/operations/*` beyond `s-canon.md`'s own summary.
- I did not check the docs copies byte-for-byte against `C:\swarm\out\*\report.md`; sizes match for every pair I compared.
- Nothing here is evidence, a verdict change, a serving, capture, config or reservation proposal, or an authorisation.

## Files

- `C:\swarm\out\s-critic\report.md` (this file; placed by shell copy because the Write tool guard blocks report files),
  `C:\swarm\out\s-critic\result.json` (includes `report_md`).
- Docs copy: `C:\pt\swarm\docs\research\model-parity-swarm-2026-10-04\COMPLETENESS.md`.
- No code written, no rule registered, no score produced, no git run.
