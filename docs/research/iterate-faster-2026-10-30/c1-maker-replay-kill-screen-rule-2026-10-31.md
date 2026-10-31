# C1 kill-only screen on export 2: maker replay v2 policies on the released panel (rule, 2026-10-31)

**STOPPED, never frozen (master ruling 2026-10-31, relayed by the coordinator).** C1 and C2 are maker-economics
reads, outside the owner's release: DECISION_LOG 2026-10-30 says "maker economics on these dates stay closed". This
draft is kept unedited below as evidence for the archive. It has no ledger row and was never run. No data was read.

**Dated research evidence, lane L16, 2026-10-31.** This is the rule for the second consumer of export 2: claim C1 in
the claim check. It was written from repository text and code only. No data file was opened. That covers no 88a
segment, no label, no price, no snapshot and no export directory listing. Nothing dated after 09-29 was read. It
authorises nothing. It runs only after master reviews it, rules the open points in §10, pins its sha in a pending
DEV_WINDOW_LEDGER row and admits the module in §9.

Citations: DL = `docs/operations/DECISION_LOG.md`, SoP = `docs/operations/STATE_OF_PLAY.md`, ER =
`docs/operations/EXHAUSTION_REGISTER.md`, DWL = `docs/operations/DEV_WINDOW_LEDGER.md`, all at `origin/master`
`265fa99cb2be2ba941d06940c9c570e4384317ec`. V2 = `docs/research/maker-replay-v2-registration-DRAFT.md` on
`codex/maker-replay-v2-build-20261003` @ `1fd0c295f6b79fb63f7ddf3e6219b32511956e5a` (the build line; never landed).
CC = `docs/research/iterate-faster-2026-10-30/claim-check-0930-1014.md` @ `31b9218b101528d1d8a5911da2916e5cb3848197`.
EM = the export manifest and the export 2 sub-manifest on `claude/embargo-release-export-manifest-20261031` @
`f449e1f62`.

## 1. What C1 is, and whether it is closed

**Definition.** C1 is the claim check's C1 (CC §2): **maker replay v2**, the successor registration. It is a DRAFT
and was never signed. Its quote panel is UTC 09-30..10-13, with settlement-only days UTC 10-14 and 10-15 and
calibration days UTC 09-27..09-29 (V2 §2:46-49).

- **Question** (V2 §1:33-36). On captured International Polymarket weather inputs, does `informed-v0` earn more modelled
  net than `blind_re1` and more than `no_quote`?
- **Pull question.** Does it pull large moves at least twice as efficiently as an exposure-matched clock?
- **Release.** DL:292 (2026-10-30) releases C1's dates for weather kill-only and atlas reads. EM §4.1 names C1's
  export scope: all 12 markets, targets 09-28..10-14; quote days UTC 09-27..10-13 at leads 1..2; 10-14 as a
  settlement-only day.

**Name collision (flag).** The coordinator located C1 as "the candidate whose block-3 scheme L14 cited as C1's
moving-block". That phrase refers to something else: S31 P0 **Clarification 1**
(`docs/research/s31-other-venue-prices-2026-10-31/clarification_s31_p0_1.md:25`, and Clarification 5 lines 19-35, on
`claude/s31-venue-inventory-20261031` @ `7e06c29f8`). That clarification's block-3 is a non-circular moving block,
whereas the D3 rulings use the circular scheme. **It is not a candidate and not this C1.** This rule takes C1 to be
the claim-check C1, the only C1 that consumes export 2 (EM §4.1, §4.3; export 2 sub-manifest §2-§4).

**Rows checked (C1 is not closed):**

| Source | Rows | What they say |
| --- | --- | --- |
| DL | :99, :103, :117, :119, :179, :200, :209, :292 | v1 exam closed NOT EXECUTED (:99). v2 design approved for build (:103). Austin 10-03 excluded (:117). Lapse moved to 2026-10-30 (:200). Maker review moved to 11-20 (:209). Dates released for kill-only reads (:292). **No row records v2 as signed, lapsed, abandoned or closed.** |
| SoP | :46-48, :64, :69 | "maker economics stay closed (embargo code unedited)" (:47). 88a hold UTC 09-27..10-30 (:64). Critical path item 2 lists "C1-C3 kill-only screens" as **pending** (:69). |
| ER | :232, :267, :305, :349 (row 18) | Row 18 (§4 maker rows) is "on the critical path", not closed. No ruled-out row names maker replay v2 or `informed-v0`. |
| Findings digest | :143 | The maker-P&L desk study is not powerable at δ = 1.0 pUSD per band-day (EF §10r). No v2 result exists. |
| DWL | rows 1-101 (grep `C1`, `replay v2`, `maker replay`) | No row for maker replay v2 or a C1 screen. Rows 53-56 (`RV-C1`), 65 and 85 (successor-batch C1, `low_so_far`) are other things that happen to be called C1. |
| WORKSTATION_STATE | :2221-2222, :2311-2313, :2339, :2418, :2451, :2462 | C1 is unresolved and enforced by its own `export_gate` (:2313). Export 2 order is atlas, then C1, then C2; each needs a frozen rule sha, D3 power if it can kill, master review and module admission (:2451). |

**Status.** By its own text the v2 draft has lapsed: V2 §13:562 said "If unsigned by 10-23"; DL:200 moved that to
10-30, and it is unsigned on 10-31. No DL row records the lapse, and CC §1 already flagged that gap. C1 is
**open**: it is neither killed nor closed. This screen is a new rule. It does **not** sign, revive or replace the v2
registration, and it does not spend v2's look.

## 2. Question, outputs and decision use

**Question (kill-only).** On the released panel, can an edge-sized economic advantage of `informed-v0` be ruled out?

- **Edge-sized** means at least Δ_edge per band-day (§6) over `blind_re1`, or over `no_quote`.
- **Policies.** The four policies keep their V2 kernels and parameters: `informed-v0`, `blind_re1`, `no_quote` and
  `clock_only`.
- **Inherited terms.** V2 §1:38-42 and §3 fix the fill bound `strictly_through`, k = 1 rewards, nominal rebates, the
  cash and caps, the hazard recipe and the 05:00-08:00 UTC exclusion.

**Outputs.** All are written under `--out`:

- `result.json`:
  - per contrast: Δ, both 95% intervals, the wider interval, both SEs, `power_at_edge` and the label;
  - the V2 registered estimand, per complete market/UTC-day, with V2's own date and crossed bootstraps (seed
    20260926), descriptive;
  - k = 0.3 and k = 0.5 sensitivities and the pull ratio, descriptive;
  - cluster counts, the dropped-cell count and reasons, unresolved fills, and the control results.
- `band_day_table.csv`, one row per band × UTC day × policy × bound, with its sha256.
- `receipt.json`: every input path and sha, the module sha, the run-branch tip, the ruling strings, the gate scope
  (§5.2) and the start and end times.
- `result.md`, a short readable form.

**Decision use.**

- **KILL at edge size.** `informed-v0` is recorded as ruled out at Δ_edge on this panel. That means a new ER §6 row,
  an archive under `C:\archive\ruled-out\<row-folder>` and the Reopen-if in §7. The register row 18 maker path then
  needs a new estimand or a larger δ (ER:349) before any further replay.
- **NOT KILLED** gives no claim. It qualifies nothing:
  - no MET, no hurdle pass and no shadow, pilot or live step;
  - no edge claim (DL:292, CC §3.1);
  - it does not count as V2's look.
- **DESCRIPTIVE** (underpowered) and **UNTESTABLE** are recorded, archived and change nothing.

## 3. Inputs (exact)

All inputs are read-only. Every file is verified against its SUMS before it is read.

**3.1 From export 2 batch 1, `C:\t\ex2b1`** (receipt `2d4c34b2…`, SHA256SUMS `84a16160…`, 136,445 files,
19,531,100,780 bytes; pre-read guard receipt `C:\t\ex2b1_guard_receipt.json`, sha256
`b130dd5be3cb0b8712bed8a7793e33d0dd5d7bdbc7caa08e17be82832745899f`). C1 uses this subset only:

- `maker_evidence/<UTC day>/<HH>-<12 hex>/`:
  - for UTC days 2026-09-27..2026-10-07, sealed segments only (a `manifest.json` exists), each read whole;
  - 09-27..09-29 serve as calibration (hazard) and 09-30..10-07 as quote days.
- `snapshots/<slug>/` for local targets 2026-09-28..2026-10-08, all 12 markets, minus Austin 10-03. The files are those
  `maker_plugin_sources.py` reads (EM §4.1):
  - `snapshots_long.csv`, `forecasts_long.csv`, `snapshot_explanations.jsonl`;
  - `forecast_payloads.jsonl` / `_long.csv`, `observation_payloads.jsonl`;
  - `clob_tokens.jsonl` / `.csv`, the referenced `forecast_payloads/sha256/...` files;
  - gz variants as found.
- `settlements/<market>/ledger.jsonl`, the rows for targets 2026-09-28..2026-10-08 in the slug-filtered copy.
- `snapshots/observation_triggers.jsonl`, rows with target ≤ 10-14, and the referenced `forecast_payload_cas/<ref>`
  files, if present in batch 1.

**3.2 From the export 1 copy, `C:\t\r80`** (row 80 export receipt `6c0f4a1d…`, SHA256SUMS `c0246a65…`; read-only;
never modified). Row 80's look receipt exists, so the order rule is met (CC §3.6):

- US11 `snapshots/<slug>/` for targets 10-09..10-14: `snapshots_long`, `forecast_payloads(_long)`, `replay_inputs`
  and `settlement.json`;
- the US11 ledger rows for targets 10-09..10-14;
- the referenced CAS bulletins.

**3.3 Pull by need from export 2 batch 2 (`batch2-rest`)** (receipt `753c1e42…`, SHA256SUMS `40fc3324…`, 72,456 files,
37.66 GB). The host keeps the master copy (master ruling, WS:2418).

- **Pull.** One new folder `C:\t\ex2b2c1`, path-filtered from the batch-2 SUMS file:

  | # | Path pattern | Dates | Markets |
  | --- | --- | --- | --- |
  | 1 | `maker_evidence/<UTC day>/**`, sealed segments whole | UTC 2026-10-08..2026-10-14 (10-14 is the settlement-only day) | — |
  | 2 | `snapshots/<toronto slug>/**`, whole folder (set A) | targets 10-09..10-14 | toronto |
  | 3 | set D files for `snapshots/<slug>/`: `forecasts_long.csv`, `snapshot_explanations.jsonl`, `observation_payloads.jsonl`, `clob_tokens.*`, the referenced `forecast_payloads/sha256/...` files | targets 10-09..10-14 | US11 |
  | 4 | `settlements/toronto/ledger.jsonl` rows | targets 10-09..10-14 | toronto |
  | 5 | `snapshots/observation_triggers.jsonl` and the referenced `forecast_payload_cas/<ref>` files, if batch 1 lacks them | — | — |

  The first job writes the pull list (path, bytes, sha from the SUMS) to `--out` before copying.
- **Disk precheck.** C: had 54.99 GB free at writing. The pull needs (listed bytes) + 10 GiB headroom free on C:, or
  the job stops before copying.
- **Verify.** Every pulled file is checked against the batch-2 SUMS. Any mismatch stops the job.

**3.4 Code.** The v2 engine, scorer, compaction and v0.2 bundle builder, read from `codex/maker-replay-v2-build-20261003`
@ `1fd0c295f6b79fb63f7ddf3e6219b32511956e5a`, unedited. The run branch merges that commit read-only plus the §9 module.
The plugin fair value uses the release the build line's `ReleaseSources` resolves. Its id and sha go in the receipt.

## 4. Exclusions

- **Austin, local target 2026-10-03, in every kind (C7).** The reader drops it before any row is used. In 88a it stays
  inside the sealed segments (EM §5.1, master ruling (a)). The V2 engine marks it `OWNER_EXCLUDED_PRIOR_READ`
  (V2 §2:50-54).
- **MG-2 and B outputs (C8/C9).** None is read. No MG-2 score is formed. B's control layout `4d53fdbd…` and
  `C:\swarm\v3layout` are not opened.
- **No edge claim** (DL:292, CC §3.1). No label in §7 is a pass.
- **Local target date ≤ 2026-10-14** (C5). Any condition with a target of 10-15 or later is inactive (V2 §4:226 already
  says so). No 88a day after UTC 10-14 is read; the guard refuses one.
  - The registered settlement-only day UTC 10-15 is absent, so 10-13/10-14 positions that settle only there stay
    unresolved. Their cells drop out under V2 C9 (V2 §3:88). The count is reported. EM §5.2 calls this a reduced
    panel.
- **The 10-16..11-13 descriptive refusal and the maker_shadow OUTCOME window** are untouched. Nothing reads
  `maker_shadow` or the 88a panel through `MakerEvidencePanel`.

## 5. Method

**5.1 Engine.** V2 at `1fd0c295f`, unedited:

- v0.2 bundles are built per UTC day from the sealed segments and slug folders;
- the execution manifest is built and verified (V2 §4 active intervals, horizons 1..2, the 05:00-08:00 UTC exclusion,
  target ≤ 10-14, Austin 10-03 excluded);
- the hazard comes from calibration 09-27..09-29 by the inherited recipe, and its value goes in the receipt;
- the engine runs `pipeline.run_passes` for the four policies, at both fill bounds, with the pinned tzdata and
  registered zones.
- **Caps.** Bundle caps are passed at the CLI's host limits (`maker_replay_bundle_v02.py:238`; `HOST_MAX_BYTES`
  = 70% of RAM). The v0.1 path that blocked C3 is not used. Any engine or bundle refusal is recorded as **BLOCKED**,
  never lifted (C3 precedent, DWL row 100).

**5.2 Gate scope (needs a ruling, §10 O2).** `export_gate.export_permitted` and `read_permitted` refuse every UTC day
09-30..10-15 while `SIGNED_REGISTRATION_SHA256` is None (`src/maker_core/replay/export_gate.py:39-43` @ `1fd0c295f`).
Master ruled that `export_gate` stays unedited (EM §0). The proposed path follows the row 80 / atlas precedent
(in-process `DEV_LAST` override, `served_market_blocks.py` @ `d155a665a`):

- the §9 module replaces `export_permitted` and `read_permitted` **in-process only**, with a function that permits
  exactly UTC days 2026-09-27..2026-10-14 and refuses everything else, including 10-15;
- the file on disk is unchanged, and its sha is checked before and after;
- the ruling string and the permitted-day list are written to the receipt.

Without that ruling C1 is **BLOCKED** at its own gate, and this rule records it so.

**5.3 No scored V2 report.** `report.build_report` refuses an unenrolled manifest (F4, "no escape hatch"; V2
§3:183-191). This screen does not call `build_report` and does not enrol anything. It computes its statistics from
the band-day sums that `run_passes` returns, which the V2 report reads too (V2 §7:392-393). Whether that is acceptable
is open point O3.

## 6. Statistic, D3 label rule and power

**Per-band-day contrast.** For c ∈ {`informed-v0` − `blind_re1`, `informed-v0` − `no_quote`}, the primary is at
`strictly_through` and k = 1. Here k = 1 favours a pass (V2 §12:543), so it is conservative for a kill.

- **Contrast.** Δ_c = Σ_d S_d / Σ_d n_d, a ratio over date clusters d (UTC quote days).
  - S_d is the sum, over the band-days of date d complete under both policies, of the paired modelled net difference.
  - n_d is the count of those band-days.
- **Units.** pUSD per band-day, the unit of the only pre-registered maker δ (DL:189).

**D3 label rule.** Every deciding interval is the wider of two intervals over date clusters:

- **(i) Date-clustered bootstrap.** Dates are resampled with replacement.
- **(ii) REV-2 circular block-3 bootstrap.** It is defined in C3 REVISION-2 §2 (sha256 `23f2b0b3…`) and implemented as
  `c3_kill_tier.block_counts` with `BLOCK_LEN = 3`:
  - ⌈n/3⌉ blocks of 3 consecutive present dates, wrapping at the end and truncated to n;
  - gaps are skipped, not filled.
- **Both bootstraps.** B = 2,000 and seed 20261024. Each applies per-date counts to the same (S_d, n_d) rows and
  recomputes the ratio.
- **Interval.** Two-sided 95% percentile. The wider interval takes the smaller lower bound and the larger upper bound.
  SE_c is the larger of the two bootstrap SDs (ddof 1).
- **Reported only.** The crossed date × market bootstrap.

**Edge size.** Δ_edge = **1.0 pUSD per band-day**. This is the desk-study power rule's pre-registered δ (DL:189; EF §10r).
V2's own δ_ref was never set (V2 §12:535-538, §14). Master or the owner may set a different Δ_edge **before the run**
(O4). ER:349 already suggests a larger δ.

**Power at edge size.** power_c = Φ(Δ_edge / SE_c − 1.960), with SE_c the larger SE, computed at run time.

- Power ≥ 0.5 if and only if SE_c ≤ 1.0 / 1.960 = 0.510 pUSD per band-day.
- With G date clusters, that needs a per-date SD of at most 0.510·√G: 1.909 at G = 14, or 1.613 at G = 10.

**Projection (pre-run).** From the only recorded σ, the desk study's 4-date pilot (DL:189), assuming the per-date SD
of the paired contrast is about the same. The pilot is a different estimand, so this is not binding:

| σ_d per date (pUSD per band-day) | G = 14 | G = 13 | G = 10 |
| --- | --- | --- | --- |
| 4.713 (point) | SE 1.260, power 0.122 | SE 1.307, power 0.116 | SE 1.491, power 0.099 |
| 10.679 (90% upper) | SE 2.854, power 0.054 | SE 2.962, power 0.052 | SE 3.377, power 0.048 |

**The expected outcome is DESCRIPTIVE.** A paired contrast can have a much smaller SD than single-policy P&L, which is
the only way this read could kill. Master should weigh that before admitting the job (O7).

## 7. Decision table

Steps run in order. The first that applies sets the label.

| # | Condition | Label |
| --- | --- | --- |
| 1 | Any control in §8 fails, an input sha mismatches, or a forbidden input appears | **VOID** (nothing read further) |
| 2 | Engine, bundle, gate or manifest refusal | **BLOCKED** (recorded, not lifted) |
| 3 | Fewer than 10 date clusters or 10 market clusters for a contrast after exclusions (V2 §4:259-260) | **UNTESTABLE** |
| 4 | power_c < 0.5 for **both** contrasts | **DESCRIPTIVE** (cannot kill) |
| 5 | A contrast with power_c ≥ 0.5 has a wider upper 95% bound < Δ_edge | **KILL at edge size** for `informed-v0` on this panel. One contrast suffices, because V2's hurdle needs both. The result names which contrast. |
| 6 | Otherwise | **NOT KILLED** (no claim) |

- **Reported beside every label:** the pull ratio, k = 0.3 and k = 0.5, the `fill_through` bound and the V2 registered
  estimand. None of them changes the label.
- **Reopen-if** (for a KILL), drafted for master: a new prospective maker registration with a new estimand or a
  larger δ, on panel dates other than these, signed before any read of them; or a fair-value model that the kill did
  not test, under its own rule.

## 8. Controls (all must pass before step 4 is read)

1. **Gate scope.** `export_gate.py`'s sha is unchanged before and after the run. The in-process scope permits exactly
   09-27..10-14, and a self-check calls it on 10-15 and 09-26 and gets refusals.
2. **Determinism (V2 E7 analogue).** Calibration day 09-27 is run twice in fresh processes with different
   PYTHONHASHSEED values. The band-day table shas must be equal.
3. **Structural.** `no_quote` has zero quotes, fills and rewards in every cell. `clock_only` exposure matches within
   one minute where the pull ratio is reported.
4. **Exclusions.** The manifest's exclusions include `OWNER_EXCLUDED_PRIOR_READ` for the Austin 10-03 conditions, no
   active interval has a target after 10-14, and no 88a day after 10-14 was opened.
5. **K3 on synthetic data** (driver tests, fixture-only):
   - positive (+3 pUSD per band-day): NOT KILLED, with power ≥ 0.5;
   - negation (−1): KILL;
   - null at high SE: DESCRIPTIVE;
   - the block-3 counts reproduce `c3_kill_tier.block_counts` exactly.
6. **Input integrity.** The ex2b1 and r80 subsets are re-verified against their SUMS, and the batch-2 pull against its
   SUMS. There must be no extra files under the pull folder.

## 9. Module (needs admission; lanes never self-admit)

- **Module.** `tools/research/released_window/c1_maker_replay_screen.py` (new), plus its tests under
  `tests/research/released_window/`. It is written only after this rule is reviewed. Its allowlist line goes into
  `workload_admission.ps1`, the hook mirror and the ratchet test **only as master's admission diff**.
- **Process.** One process does the pull plan, then bundles, manifest, engine, statistics and receipt. Each stage is a
  separate `-Queue` job if master prefers.
- **No network.**
  - An AST scan of the module and its non-stdlib import closure finds no `socket`, `ssl`, `http`, `urllib`,
    `requests`, `aiohttp`, `websocket(s)` or `ftplib` imports. The batch-2 pull is a plain file copy from the staged
    share path, done by the PowerShell wrapper step, not by the module.
  - An end-to-end test runs on a fictional fixture with `socket.socket` patched to raise.
- **Writes.** Only under `--out`, which must be a new, empty directory outside `C:\archive`, `C:\swarm`, `C:\t\r80`,
  `C:\t\ex2b1` and any path containing `88a` or `panel`.
  - Inputs are opened read-only.
  - A test asserts that every created path is under `--out`. The pull folder `C:\t\ex2b2c1` is the one other write,
    made by the wrapper step.
- **Origin.** The atlas pre-flight is repeated: every module resolves under the run tree, with `PYTHONPATH=<run
  tree>\src` and cwd at the repo root.
- **Heavy.** Through `scripts\ops\workstation_heavy.ps1 -Queue` only, after master admits it. Pytest uses `--basetemp`
  under `C:\t\l16`, deleted afterwards.

## 10. Open points for master

- **O1. Does a kill-only replay of maker policies breach "maker economics stay closed" (SoP:47)?**
  - The owner released C1 by name for kill-only reads (DL:292).
  - The same row says that, with the maker_shadow embargo code unedited, maker economics on these dates stay closed.
  - This screen is maker economics, but kill-only and outside `maker_shadow`.
  - It needs an explicit ruling, possibly from the owner.
- **O2. The in-process gate scope (§5.2).** Without it, C1 is BLOCKED.
- **O3. Band-day sums without a scored V2 report or enrolment (§5.3).** The alternative, enrolling a manifest, is an
  owner-policy change.
- **O4. Δ_edge.** 1.0 pUSD per band-day (DL:189), or a larger owner δ, fixed before the run.
- **O5. Run cost is unmeasured on real data.** V2's executability gates E1-E8 and its ceilings were never filled in
  canon (V2 §9:439, §14). A calibration-only cost probe on UTC 09-27, which is outside the gate, should run first as
  its own admitted job. If it projects more than the wrapper caps over 16 days, C1 is recorded BLOCKED (cost) without
  touching a panel day.
- **O6. The S31 Clarification 1 name collision (§1).** Confirm that this is the intended C1.
- **O7. The projected power is 0.05-0.12 (§6).** Master may record C1 as **UNTESTABLE by projection** without running
  it, or run it for the descriptive table.
- **O8. Strata.** Unlike the atlas (pre 10-01..10-09 and post 10-10..10-14), C1 is one 14-date panel. Splitting it would
  leave fewer than 10 date clusters per stratum, so it is not split. Confirm.
- **O9. V2's lapse has no DL row (CC §1).** The docs head may want one. This rule does not write it.

## 11. Freeze

The rule is frozen by its sha256 in a `pending` DEV_WINDOW_LEDGER row, which the coordinator numbers, before any
computation. The row is type K if O7 is ruled "run"; otherwise the outcome is recorded as UNTESTABLE by projection.
The row names this file's sha, the run-branch tip, the module sha once admitted, and master's rulings on O1-O8.
Nothing in §3 is opened before then.
