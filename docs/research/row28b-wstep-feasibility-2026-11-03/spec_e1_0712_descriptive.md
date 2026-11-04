# E1 spec: row 28's 07-12 descriptive slot, POST-HOC-FILLED DESCRIPTIVE (spec only; nothing run, nothing read)

Lane L59, WS, 2026-11-03.

- **Authority.** Master ruling 11-03, "E1: GO … for the SPEC ONLY at this step". The run waits for master's GO.
- **Label.** **POST-HOC-FILLED DESCRIPTIVE** everywhere. It fills row 28's own pre-registered descriptive slot after
  the verdict. It cannot change the row-28 verdict.
- **Use.** Its only use is SELECTION: whether to add a 07-12 arm to the forward draft before 12-17, and the same-kind
  σ and delta for that arm's (f) block. A 07-12 claim can only come from a forward re-test from zero.

## Blocking gap (STOP and ask before any run)

- **The comparator needs an input row 28 never bound.**
  - The L6 stack serves mu = v2_mean + a_h + b_h (N − v2_mean), where N is the own-observation nowcast.
  - N is read from `nowcasts.parquet`, keyed by captured-snapshot `row_key` and built by
    `weather.calibration.upstream_obs_screen serve` (`src/weather/reporting/scorecards/free_source_candidates/l6_stack.py:1-13, 28-30`).
  - Row 28's history rows come from `extract_market` (prereg §3.3). They have no snapshot `row_key`, and row 28
    bound no METAR history source ("No METAR history source is used", `prereg_row28.md:170`).
  - **An N for 2021-25 Dec 17-May 31 history rows would be a NEW extract.** It is not built, not specified here and
    not run.
- **Master to choose one:**
  - **(i) GO for a separate, outcome-blind N extract.** It would need its own source manifest and sha, and would come
    with a DWL disclosure.
  - **(ii) Use S' = MG-1 at 07-12 as the comparator**, computable from bound inputs only. This is what the L6 stack
    serves wherever N is absent: "snapshots without N are MG-1 exactly" (`l6_stack.py:13`). It departs from
    prereg:286 and would be labelled as the departure.
  - **(iii) Do not run E1.**
- Nothing below runs until this is ruled.

## Arms

- **B at 07-12.** Arm B's spec (`prereg_row28.md:219`, Dec 17-May 31 rows only), fitted per hour for h = 7..12 by
  the same per-hour routine (`row28_run_v12.py:2011-2016`).
  - This is a **separate fit**, with its own output sha, in a new runner `row28_run_v13.py` (v12 is unchanged).
  - **The 13-16 fits and the 343b state sha are untouched**, and no 343b file is read or written.
- **S (prereg:286, verbatim):** "Hours 07–12 are scored descriptively against the served pre-13 comparator and never
  decide. That comparator is the L6 stack over MG-1, with bound coefficients `07a67425…ee17e9` and state
  `800072c7…2ee2db`."
  - Full shas: L6 part `07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9` and L6 state
    `800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db` (`src/weather/calibration/l6g_forward_frame.py:41-42`).
  - Disclosure: the state is the season-matched L6, fitted on Oct-Dec 2021-25 (DWL row 46; to be verified at spec
    freeze). Its training therefore includes Dec 17-31 rows of the held-out folds. S is a frozen served model and is
    not walk-forward, as at 13-16.

## Folds and rows

- **Folds.** Season-years 2021-2025. Fold Y holds out Dec 17 (Y−1) .. Dec 16 (Y) from B's training
  (`prereg_row28.md:199-200`).
  - All five folds are pooled into one descriptive estimate. There is no look/final split, no futility and no Holm
    family; E1 decides nothing.
- **Rows.** US10 × hours 07-12 on row 28's deciding-date list (`deciding_dates_r4.txt`, CRLF sha256 `6913484a…84bcfb`,
  660 dates; `FREEZE_RECORD.md:30`).
  - Rows are dropped under row 28's §1.1 and §5 integrity rules, applied at the 07-12 cutoffs before any label join.
  - A scored row needs its 07Z bulletin posted by its own cutoff (`prereg_row28.md:177`). Earlier cutoffs can drop
    more dates than at 13-16.
  - Drop counts by code are reported before labels.

## Outputs (only these; no per-row dump, no per-market or per-hour table)

- d̄ = mean over dates of [Brier_B − Brier_S] over US10 rows at 07-12, using the multi-band Brier (prereg §6.1);
- the date-clustered 95% CI and the block-3 95% CI;
- the per-date SD σ_d;
- the lag-1 ρ, with κ_AR and κ_block3;
- the integer N of dates and rows.

They are written to one result JSON and are guarded like row 28's outputs.

## Inputs and bindings reused (row 28's freeze; no new input except the gap above)

- **NBM.** `manifest_nbp.json` `2948b7180f54b0aa413360553d82851a3e3610cf1a3576104422d346259b6f5f`.
- **IEM.** `manifest_iem.json` `17aca6d162316aeb4b391cd145ca830578e8191e1a49a878bb6e93ed699ad61f` and
  `manifest_iem_gap.json` `bdf84209d1ef99c2cff74caf0b81201b63e873944fd2cb8607dc9277fa9fb402` (`FREEZE_RECORD.md:19-22`).
- **Build path and labels.** The B-bound builder `pooled_residual_model.extract_market` (read only; coverage hours
  7-20, `prereg_row28.md:63`). The F2 pins and calibrated-weights shas as in `RUN_LOG.md` "Pinned files". The WU
  labels copy as row 28's stage 4.
- **Records root.** A **NEW records root** (for example `C:\t\L59\e1\records`), never the frozen `C:\t\L59\row28` run
  dirs.
  - The build call is identical. If it would need any extract beyond row 28's bound manifests, STOP and ask.

## Cost estimate (from row 28's recorded stages)

- **Build into the new root.** About 1.5-2.5 h, with peak job memory about 5.1 GB (row 28's rebuild peak
  5,060,091,904 bytes) and about 8 GB of disk (the row-28 run dir is 7.9 GB).
- **Fit and score.** One arm plus S at six hours, against row 28's four arms at four hours, so about 1-2 h (row 28's
  look and score took about 2 h each).
- **Run conditions.**
  - WS only, under `workstation_heavy.ps1 -Queue`, with -RepoRoot outside guarded worktrees.
  - Disk floor at start: 45 GiB free on C:, and a 12.8 GB memory stop.
  - Stages: build, integrity, labels, score, each on the coordinator's go.

## DEV_WINDOW_LEDGER row draft (NOT committed until master's GO)

- **Row.** Next free number, currently 119 (master and remote branches end at 118).
- **Entry.** | 2026-11-?? | L59 | E1 spec branch @ <tip> | this spec sha256 <at GO> | descriptive | **POST-HOC-FILLED
  DESCRIPTIVE** fill of row 28's prereg §4.4 slot (hours 07-12, B vs S).
  - Reuse: Dec 17-May 31 2021-25 labels, already used by rows 116-118 (row 28) and by the earlier P3F and PIT-corpus
    work (`prereg_row28.md:526`). Reuse count: at least 2 prior uses of these dates; the exact count is filled from the
    ledger at GO.
  - Use: selection only (forward 07-12 arm add/no-add and its σ/delta). It cannot change the row-28 verdict. No
    dates ≥ 2026-09-30; no panel.

## E3 decision rule (fixed now, before any run; master's suggestion)

- **ADD a 07-12 B−S arm** to the forward draft before freeze **only if both hold:**
  1. E1's point d̄ ≤ −2 × its own SE. The SE is taken from the date-clustered interval; the more conservative of the
     date-clustered and block-3 intervals is used.
  2. The projected power at N = 45 under rules 16 + 19 is ≥ 0.8. The projection inputs are:
     - σ = 1.5 × E1's σ_d (same kind and distance, with the forward season's planning bound as at 13-16);
     - VIF = max(1, (1+ρ)/(1−ρ), κ_block3²) from E1;
     - futility inflation ×1.07;
     - delta = half of E1's point (rule 6).
- **Otherwise DON'T ADD.** The result is recorded and nothing else changes.
- If added, the arm is the fixed-sequence secondary behind 13-16 (`extension_0712_feasibility.md` (c)). The 13-16 PASS
  rule is unchanged.
