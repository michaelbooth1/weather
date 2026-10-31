# C3 kill tier: T+1 NBP fair value against 88a mids, targets 09-25..10-08 (DRAFT, not frozen)

**Status: DRAFT, NOT FROZEN, NOT RUN.** Lane L16, 2026-10-31. Research evidence, not canonical guidance. It was
written from code and repository text only. No data file was opened for it: no 88a record, snapshot, bundle, label or
price, for any date after 2026-09-29. It freezes only when master pins its sha256 in a new dev-window ledger row,
written `pending` before any computation (method §5 rules 3 and 11). After that, any change is a dated clarification.

## 0. Authority, claim and order

- **Release.** On 2026-10-30 the owner released 09-30..10-14 for kill-only and atlas reads (method §5 rule 10; DL
  2026-10-30, relayed by master). The release covers C1, C2 and C3 of the claim check
  (`claude/claim-check-0930-1014-20261030` @ `31b9218b101528d1d8a5911da2916e5cb3848197`).
- **This read is C3.** The claim check lists the frozen T+1 fair-value read as C3: prereg
  `docs/research/t1-fair-value-preregistration-2026-09-25.md` @ `4b1ef8a070d963bf1472876440e84d4b504537b8`,
  with Clarification 1 and Amendments 1-3. It was postponed, not withdrawn. Its frozen read is descriptive only. This
  draft adds a **kill rule** to it as a separate dated rule. The frozen estimator, sampling, aggregation, bootstrap
  and tables are not changed.
- **Excluded cells** (export manifest `claude/embargo-release-export-manifest-20261031` @
  `a451b0e9302c1449a0053caedc333287b08e57b2` §3):
  - C5, the UTC 10-15 spill;
  - C7, Austin target 10-03, in every kind;
  - C8/C9, the MG-2 and B outputs.

  The driver refuses a run whose selected rows include any of them (section 6, refusal R3).
- **Order (rule 9 and claim check §3.6).** Row 80's single look (C4) is the first read of US11 snapshots and labels
  for 10-01..10-14. C3 reads US11 labels for targets 10-01..10-08, so it opens nothing until row 80's look receipt
  exists. The 09-25..09-29 targets are already dev dates. Their 88a quotes were captured UTC 09-23..09-28, so C3 still
  waits, because the bundles are built per UTC day across the whole panel.
- **What a result can and cannot do.** The result is **kill-only**. The outcomes are KILL, NOT KILLED or
  INCONCLUSIVE. No outcome is a pass, an edge claim or a promotion (rule 1, rule 10, claim check §3.1).

## 1. Question and why it is cheap

The forward T+1 test (`claude/t1-forward-prereg-20261030` @ `45ab6eb0bd0fda3d3cb14714eac0fbdd7a93b6a9`, rev 8,
not frozen) will spend about 82 forward dates on arms A1 (NBM NBP), A2 (ECMWF ENS) and A3 (their blend). Its P1
freeze point is expected after UTC 11-02 closes.

C3 asks the following before that freeze. On the only captured T+1 history, does the frozen NBP percentile fair value
predict the error of the contemporaneous 88a two-sided mid at local lead 1? That history is 88a, targets 09-25..10-08.
- The 88a capture already exists, and the frozen estimator and scorer already exist.
- The cost is a host export, a bundle build and one scorer run, which is method §5 rule 2's "kill at the cheapest
  tier".

## 2. Population (fixed by the frozen T+1 prereg; nothing re-chosen)

- **Targets:** local target dates 2026-09-25..2026-10-08 inclusive (`PANEL_START`/`PANEL_END` in
  `maker_fair_value_score.py`), minus Austin 10-03 (C7).
- **Leads:** local lead 1 is the **killing arm** (it is the forward test's horizon). Lead 2 is reported beside it and
  never kills.
- **Markets:** all 12 built-ins that have captured 88a events. 88a is the top-ten partial universe, so coverage is
  whatever was captured. Nothing is filled.
- **Comparator m:** the 88a two-sided mid (best bid + best ask)/2 at the first complete captured minute in each UTC
  hour per event and lead, exactly as the frozen scorer selects it.
- **Signal c:** the frozen 110b fair value. Strata `nbp` (plain piecewise) and `fallback` are kept separate. The
  Amendment 2 strata `nbp_atoms` and `nbp_resolution_tails` are reported separately.
  - **Killing stratum: lead 1, pooled table membership (plain NBP + fallback),** as the frozen pooled descriptive
    table defines it.
  - The plain-NBP-only lead-1 stratum is reported beside it.
- **Label y:** the reconciled settlement fact bound in each bundle (`observed_yes`, 0/1 per band). The scorer reads
  it only after sampling is fixed.

## 3. Statistics (forward T+1 prereg §6.1 and §6.2 forms, on this population)

Entries are (selected event-hour x band) rows from the frozen scorer's `report.json` `selected_hours[]`. Per entry:
- s = c − m, the signal's disagreement with the market;
- e = y − m, the market's error.

Date = target date. Every date-clustered draw resamples target dates.

1. **P0 (rule 3).**
   - ρ_c = pooled Pearson ρ(s, e).
   - Calibration-matched placebo: c_pl(d) = m(d) + (c(d′) − m(d′)). The donor d′ comes from a within-(market, local
     hour) derangement over the panel's target dates, then the vector is clipped to [EPS, 1 − EPS] and
     renormalised to Σm. J = 20 seeds, 20260921 + j. No outcome enters the placebo.
   - Δ = ρ_c − mean_j ρ_pl,j.
   - Date-clustered bootstrap: B = 2,000, seed 20261024. One-sided p = (1 + #{Δ*_b ≤ 0}) / (B + 1).
   - BH at q = 0.10 over the one killing arm. With one arm this reduces to p ≤ 0.10. It is written this way so that
     a later batch inherits the form.
   - **P0 holds iff** BH rejects and the lower 95% bound of Δ > 0.
2. **w (rule 4).** The pool is g = m^(1−w)·c^w, renormalised to Σm, through `market_blend.pool()`
   (`src/weather/calibration/market_blend.py` on master, unchanged).
   - At T+1 no target-day observation exists, so no band is impossible.
   - w is fitted walk-forward on target dates ≤ d − 2, on the grid 0..1 step 0.01, with a pooled Brier objective.
   - Burn-in: the first 4 countable dates fit w only. The forward test's 7 would leave fewer than 8 scored dates
     here. **Open point for master (OP1).**
   - **w holds iff all of:**
     - mean w ≥ 0.05;
     - the paired blend − placebo Brier date-clustered upper 95% bound < 0;
     - the paired blend − floor-only Brier upper bound < 0.
   - The floor-only blend must equal m (control K1).
3. **Reported beside, never deciding:**
   - provider − mid Brier, as the frozen tables give it;
   - the Brier ratio c/m;
   - P0 per block (00-05, 06-09, 10-12, 13-16, 17-23) and per market;
   - lead 2;
   - the Amendment 3 NWP buckets, through `maker_fair_value_nwp_buckets` @
     `bf03a8d4104327913b0b4062f3eb2ad8a7a7e9c9`, reported only.

## 4. Kill rule (decided before any read)

Let D = the number of distinct target dates with at least one scored lead-1 event-hour in the killing stratum, and
M = the number of distinct markets.

| Outcome | Condition | Consequence |
| --- | --- | --- |
| **INCONCLUSIVE** | D < 10 or M < 5, or fewer than 200 scored lead-1 event-hours, or any control in §5 fails | Nothing is killed, and the forward T+1 batch freezes unchanged. Recorded with the coverage numbers. A control failure is VOID, not INCONCLUSIVE. |
| **KILL** | Coverage holds and P0 does not hold, or P0 holds and w does not hold | The frozen NBP percentile fair value at T+1 has no market-residual information against 88a mids on this panel. It is recorded in the exhaustion register §6 with numbers and a "Reopen if" line. Its scope transfer to the forward batch is **OP2**. |
| **NOT KILLED** | Coverage holds, P0 holds and w holds | No claim of any kind. The forward T+1 test freezes as drafted. This result is never cited as evidence for A1. |

- The coverage floor follows the frozen scorer's UNDERPOWERED rule (fewer than ten unique clusters in either
  dimension, here relaxed to 5 markets because 88a is top-ten; **OP3**), plus a minimum entry count. Its purpose is
  that a thin 88a panel cannot kill a forward arm by default.
- There is one look, no re-run on other settings, and no stratum shopping. Only the lead-1 pooled stratum decides.
- **"Reopen if" (pre-written for a KILL):** a full-ladder T+1 comparator (the WS T+1 price recorder) over at least
  20 countable dates shows P0 holding for A1. That is the forward test itself, if master keeps A1 in it.

## 5. Controls (all run first; any failure makes the run VOID, exit 7, and nothing is read further)

- **K1, the w = 0 identity.** On the real panel, g(w = 0) must equal m exactly: max |g − m| = 0 and the Brier
  ratio R = 1 exactly. The floor-only blend must also equal m, because no band is impossible at T+1. Any
  non-identity refuses. This is `market_blend.w0_identity` semantics applied to the T+1 rows.
- **K2, reproduction.** Three checks:
  - (a) Build every UTC-day bundle twice from the same export. The two `bundle.json` sha256 must be byte-identical.
  - (b) Run the frozen scorer twice on the same bundle set. The two `report.json` files must be byte-identical
    (canonical bytes).
  - (c) The driver re-derives the frozen pooled lead-1 provider, mid and difference Brier estimates from
    `selected_hours[]`. They must match `report.json` `tables` to within 1e-12.

  The frozen scorer already refuses any band whose rebuilt fair value differs from the captured one
  (`fair_value_input_binding_mismatch`), so the input binding needs no separate check.
- **K3, synthetic positive and its negation.** This uses synthetic fixtures only: no real label or price enters, and
  no oracle is built on real data.
  - Generate a synthetic panel shaped like the real one: the same number of dates, markets and bands per event (taken
    from bundle metadata only). Draw p_true per event from a Dirichlet and y from p_true. Set m = p_true blurred by
    one noise draw, and c+ = p_true blurred by an independent draw, so c+ holds information that m lacks.
  - **Positive:** P0 and w must both hold on c+, and the gate must return NOT KILLED.
  - **Negation:** c− = m − (c+ − m), clipped and renormalised, flips the disagreement. On c−, P0 must fail
    (Δ upper bound < 0), and the gate must return KILL.
  - **Null:** c = m + a deranged (c+ − m). Its Δ interval must cover 0.
  - Seeds and noise scales are fixed in the driver before freeze.
  - These run in pytest on synthetic fixtures and once more at run time, recorded in the receipt.

## 6. Code, inputs and refusals

- **Frozen code, unlanded:**
  - `codex/t1-fair-value-scorer-20260927` @ `d937b34ab1d50cd4b8e35e80901184f7f0f82a9f`, holding
    `maker_replay_bundle.py`, `maker_fair_value_score.py` and `maker_fair_value_statistics.py`, plus `src/maker_core`;
  - `bf03a8d4104327913b0b4062f3eb2ad8a7a7e9c9` for the reported-only buckets.

  Both run from a clean worktree at that commit. The receipt records the HEAD, the dirty flag (a dirty tree refuses)
  and the scorer's `implementation_hashes`.
- **New driver (needs master's allowlist check before it is written):** `c3_kill_tier.py`. Its inputs are the frozen
  `report.json` and the 20 placebo seeds. It imports `market_blend.pool` unchanged. It writes `c3_result.json` and
  per-date rows `c3_rows.jsonl` (the P0 sufficient sums per arm and seed, and the Brier sums for blend, market,
  placebo and floor-only), beside the result.
- **Inputs:** host export per the manifest §4.
  - C3 slice: 88a sealed segments for UTC 09-23..10-07, whole and byte-identical.
  - Slug-folder support files for all 12 markets, targets 09-25..10-08: `snapshots_long.csv`,
    `forecast_payloads*`, `forecasts_long.csv`, `snapshot_explanations.jsonl`, `observation_payloads.jsonl`,
    `clob_tokens*`, and the referenced bulletin hashes.
  - `snapshots/observation_triggers.jsonl`, capture-cut.
  - The ledger rows for targets 09-25..10-08, slug-filtered, whole rows, Austin 10-03 dropped.
  - Bundles are built on the WS with `python -m weather.market.maker_replay_bundle` per UTC day, with
    `--data-root <export>` and `--markets <all 12>`.
- **Refusals** (each one exits 2 and writes nothing):
  - R1: any selected row whose target is outside 09-25..10-08.
  - R2: any bundle day outside UTC 09-23..10-07.
  - R3: any Austin 10-03 condition in a selected row. Under manifest open point 1 (a), Austin 10-03 bytes may be
    inside whole segments, so the driver drops that event before any row is read.
  - R4: no row 80 look receipt path is given, or its sha256 is not the one master records.
  - R5: a dirty tree or a wrong commit.

## 7. Timing (can it finish by about 11-05?)

| Step | Depends on | WS effort |
| --- | --- | --- |
| Driver + K3 synthetic tests | master's allowlist ruling | about half a day; pytest via `workstation_heavy.ps1 -Queue`, `--basetemp` under `C:\t\l16` |
| Freeze row (`pending`, sha of this file + driver) | master | minutes |
| Host export (C3 slice) | embargo edit `e89cbb523` landed; manifest open points 1 and 4 ruled; host night | none on the WS |
| Row 80 look receipt | L8 / master | none |
| Bundle build, 15 UTC days, each capped at 300 s | export | up to about 1.25 h, heavy queue |
| K1, K2, frozen scorer, driver | bundles | under 1 h |

- **Verdict: feasible by 11-05 only if the C3 slice of the export and row 80's receipt both exist by about 11-03.**
  The driver and controls can be ready by 11-02.
- If the export slips past 11-04, C3 cannot finish before the forward freeze. Then either the freeze waits, which
  needs master's ruling, or C3 runs after it. A kill would then trigger the forward prereg's own change rule (a dated
  clarification before its first look), never a silent edit.
- **Known refusal risks inside the frozen code:**
  - The scorer's caps (300 s, 512 MiB, 500,000 records, 256 bundles) may refuse a 15-day panel.
  - The bundle builder's 1 GiB input cap per day may refuse 88a days of 60-90 MiB plus support tables.
  - A cap refusal is recorded. Lifting a cap is a code change that needs review, never a re-run with edits.

## 8. Open points for master

- **OP1** Burn-in of 4 dates, not 7 (a 14-date panel).
- **OP2** Scope of a KILL. It closes the frozen 110b NBP estimator at T+1 against 88a mids. Should it also drop
  forward A1? A1 has different tails (uniform 1.5x tails, against 110b's linear extension and Amendment 2), and a
  different comparator (full-ladder Gamma Yes, against top-ten 88a mids). Proposed: a KILL drops A1 and keeps A2 and
  A3 (A3 holds ENS information), as a dated clarification of the forward prereg written before it freezes.
- **OP3** The coverage floor M ≥ 5 markets (the frozen scorer's UNDERPOWERED rule is 10).
- **OP4** Manifest open point 1. Austin 10-03 inside whole 88a segments, (a) or (b). This draft assumes (a), with
  refusal R3.

## 9. Draft ledger row (number assigned at freeze; the highest seen across remote ledger branches on 10-31 is 92)

| # | Date | Lane | Branch @ tip | Rule (sha256 or commit) | Type | Candidate | Headline delta [95%] | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TBD | 2026-10-31 | L16 | `claude/c3-t1-fv-kill-tier-20261031` (rule committed before any computation; released dates 09-30..10-14, kill-only, method §5 rule 10); code `d937b34ab1d50cd4b8e35e80901184f7f0f82a9f` (frozen scorer and bundle builder, unchanged) + `bf03a8d4104327913b0b4062f3eb2ad8a7a7e9c9` (reported-only buckets) + driver sha TBD | this file, sha256 TBD at freeze; frozen T+1 prereg `4b1ef8a07` | K | C3: frozen 110b NBP T+1 fair value vs 88a two-sided mid, local lead 1, pooled stratum, targets 09-25..10-08 minus Austin 10-03; P0 (20-seed calibration-matched placebo, B 2,000, seed 20261024) then w (log pool, walk-forward, burn-in 4); kill-only. Runs after row 80's look. Multiplicity: the 1st T+1 market-residual test; the forward T+1 batch follows. | pending | pending |
