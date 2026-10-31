# ECMWF ENS member spread against the market: market-residual P0 rule (ledger row 93, draft)

Status: DRAFT, pre-declared before any computation (2026-10-31, lane L17, task P5 (c)).

- Evidence class: dev-window kill-only P0 SCREEN.
- It is its own arm with its own K. It is not pooled with rows 78, 81 or 85-92.
- A survivor earns only the owner question on an ENS capture feed (via master). It is never a promotion,
  a release, serving, capture or scheduling decision.
- The ledger row text (row 93) was committed before this file, in `ledger_rows_draft.md`.

**Amendment A1 (2026-10-31, pre-run; applies the coordinator's rulings; no outcome, price or label was read
to write it).**

- **Decision: UNDERPOWERED, NOT RUN.** At half the planning δ, power is 0.055 for each arm (0.107 at the full δ). Section 0's data check is complete and stands; it read no outcome. Section (d) carries the MIM §5 rule 6 and checklist (f)
  compliance line. Nothing in this rule runs, and no module is admitted for it, until master rules otherwise
  in a dated Clarification with its own sha256.
- **Ledger number.** Row 93 is PROVISIONAL. L15 assigns the final number in the assembled ledger; rows 82 and
  83 have already collided. A renumber changes only the label, not this rule, and is recorded as a note.
- **Archive.** Owner rule: every ruled-out candidate goes to `C:\archive\ruled-out\<row-folder>` with its
  prereg, script sha256, outputs, receipts and logs. A NOT RUN arm is not ruled out. Its prereg is archived
  under the same folder only when the assembled ledger records its verdict.
- **Run bases (ruling 4), recorded and not cut.** The planned base for a run branch is machinery `mr_sweep`/`mr_gate` at `8bb0f9563582885c4d01d34b67476f2563260e43` (`claude/loyo-screen-runenv-20261030`). The input is `points.parquet`, sha256 `bd761fa52869d244addda7fb3746276e1eb6aad2416ac2fdc3291750d7320a7e`, read under its pin with no fetch and no rebuild. The rule branch is `claude/p5-screens-20261031`, based on `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de`.

## 0. Data check (task P5 (c), outcome-free; no download, no rebuild)

Dev-window ECMWF ENS **per-member** values exist locally, and they were obtained free from an official
source. Means or spread products alone would not have counted.

- **Path.** `data/research/free_sources/ecmwf_ens/raw/<run>.json.gz`, one file per 00Z run. The paths were
  listed only; no file was opened for values.
- **Contents.** The writer is `src/weather/sources/free_screens/ecmwf_ens.py`. Each file holds rows
  `{run, step, member, station, t2m_k}`: all 51 `2t` members (control plus 50 perturbed) at steps
  18/21/24/42/45/48, bilinear at the 11 US stations.
- **Source.** The ECMWF open data (CC BY 4.0, no account), via the public GCS mirror of the AWS
  `ecmwf-forecasts` bucket. It was fetched by lane G2 on 2026-10-23/24 under the owner's free-source
  approval.
- **Coverage.** 171 runs: 2024-08-15..09-30, 2025-07-31..09-30 and 2026-07-30..09-29.
- **Reduced table.** `points.parquet` (sha256
  `bd761fa52869d244addda7fb3746276e1eb6aad2416ac2fdc3291750d7320a7e`, 3,751 rows) holds per (run, station,
  target_date) `ens_mean_f`, **`ens_sd_f` (the SD over the 51 members of each member's maximum over the
  run's three steps for that target date)** and `n_members`. The manifest records 0 fetch errors.
- **Not used.** No Oct-Dec ENS exists locally, and none is fetched under this rule.
- **No rebuild.** This rule reads `points.parquet` only, after a sha256 pin. It does not re-download or
  rebuild it, and it does not touch any other cache. `open_meteo_archives.py` is untouched.

Therefore X5 is not relabelled NOT TESTED. Its reopen line ("ENS spread as spread information", register
X5) is tested here.

## 1. Mechanism and prior, written before any read

**Mechanism.** The 51-member spread of the ECMWF daily-max proxy is a day-specific measure of forecast
uncertainty. Retail weather products publish a point forecast, and the NBM publishes a blended spread
whose information is already in the market's centre and width. If traders size their width from point
forecasts or from the NBM, then on days when ECMWF's members disagree more than usual the market is too
narrow, and on days when they agree it is too wide. That is the type S, sign + hypothesis.

**R14** does not bind this rule, because master ordered it (task P5). The mechanism by which the market
might lack the information is still stated: the member-level ENS is free, but it needs GRIB decoding, so
it is plausibly under-used by retail traders.

**The prior is low:**

- The nearest spread signals against the market were all killed on dev (row 78 receipt `02c46630…`):
  - OM-MM-SPREAD +0.0004 [−0.0017, +0.0021];
  - OM-GM-SPREAD +0.0011 [−0.0015, +0.0030].
- GEFS member SD as a model-side scale modulator failed gate 2 (X43).
- HRRR 3x3 spread as width is closed at all hours (X38, X39).
- Row 88's GEFS-SPREAD80 against the market at 00-06 is pending.

## 2. Machinery

This rule is identical to `docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md` (sha256
`85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`), sections 1-5, except where this file
says otherwise.

**Data:**

- layout `C:/swarm/v3layout`;
- burn-in 2026-08-01..08-14;
- scored dates 2026-08-15..09-29;
- e = y − m.

**Signal:**

- market moments μ_m and σ_m² from m̃ = m/Σm, with the σ_m² floor 0.25;
- z_b is the band midpoint, and open bands use ±W/2;
- type S band signal s_b = g_z·((z_b − μ_m)² − σ_m²)/σ_m²;
- g_z is the value z-scored within market over the covered fit snapshots;
- candidate c_b = Σm·m̃_b·exp(s_b/σ_s)/Σ m̃·exp(s/σ_s), with the sweep's σ_s.

**Placebo and bootstrap:**

- the calibration-matched disagreement placebo: c_pl(d) = m(d) + (c(d′) − m(d′)), with d′ a derangement within
  (market, local hour), via `market_blend.placebo_vector`;
- J = 20 placebo seeds 20260921 + j; clip to [EPS, 1] and renormalise;
- Δ = ρ_c − mean_j ρ_pl,j, with ρ_c = ρ(c − m, y − m);
- B = 10,000 date-cluster draws with seed 20261024, where draw b uses j = b mod 20;
- one-sided p = (1 + #{Δ* ≤ 0})/(B + 1).

**Thresholds and outputs:**

- UNTESTABLE below 20 covered dates or 1,000 snapshots (p = 1, still counted in K);
- per-date rows carry the six sufficient sums.

## 3. Prior reads (disclosed)

- **G2-a and G2-b (row 13, X5)** read the dev ENS member MEAN, bias-adjusted, with outcomes:
  - against MG-1 at 00-12: −0.0000 [−0.0033, +0.0031];
  - against t3-r3 at 13-16: −0.0002 [−0.0005, +0.0001].
  - Neither scored the spread, and neither read the market.
- **The spread was already built.** `ens_sd_f` already exists in `points.parquet` because G2's `build()`
  computed it. No lane has read it against an outcome, a price or a label. Lane L17 has listed paths and
  the manifest only.
- **Nearest kills against the market:**
  - row 78: OM-MM-SPREAD, OM-GM-SPREAD, NBM-SKEW;
  - X43 R-Q (GEFS SD, model-side, 07-12 dR −0.00260 [−0.00650, +0.00094]);
  - X38/X39 (HRRR 3x3 spread);
  - X54/X55 (Open-Meteo spreads).
- **Availability is modelled, not a capture receipt.** The 00Z run is taken as available at 09:00Z
  (`AVAILABLE_AFTER_H = 9`), from ECMWF's open-data release time of about 08Z. Production does not
  capture ENS.
- **The daily-max proxy under-reads the maximum.** It is the maximum of three 3-hourly values, so its
  spread is a spread of a proxy. At Pacific stations steps 18-24 cover 11-17 PDT. At Eastern stations they
  cover 14-20 EDT.

## 4. Candidates (K = 2)

| id | value | run | covered iff | type | sign | block |
| --- | --- | --- | --- | --- | --- | --- |
| ENS-SD-0712 | `ens_sd_f` (°F) for (station, target_date = D), steps 18/21/24 | 00Z of D | `available_utc` (D 09:00Z) ≤ `captured_at_utc`, `n_members` = 51, finite | S | + | local 07-12 |
| ENS-SD-0006 | `ens_sd_f` for (station, target_date = D), steps 42/45/48 | 00Z of D−1 | `available_utc` (D−1 09:00Z) ≤ `captured_at_utc`, `n_members` = 51, finite | S | + | local 00-06 |

- Station mapping: `free_screens.common.us_stations()` ICAO to layout market. Toronto is excluded because
  it has no ENS row.
- **No other value is tested** under this rule. The excluded values are:
  - `ens_mean_f`, which is X5's construct and already killed;
  - member quantiles;
  - the p90 − p10;
  - any 13-16 block.
- EF §10w is not engaged: the dev window holds no DST change.
- Coverage is checked first, outcome-free (S1): covered snapshots and dates per candidate. Any candidate
  under the UNTESTABLE thresholds is UNTESTABLE, with p = 1, and still counts in K.

## 5. Serve parity

NONE. Production captures no ECMWF ENS. A survivor is not promotable. It earns only the owner question on
a free ENS capture feed. That question goes via master, and any paid source needs per-source owner
approval in DECISION_LOG.

## 6. Decision

A candidate SURVIVES iff all three hold:

- it is testable;
- BH at q = 0.10 over K = 2 rejects;
- the Δ 95% lower bound is > 0.

Otherwise it is a KILL, or UNTESTABLE when it is untestable.

**Only for a survivor:**

- the w = 0 identity control;
- then the rule_mr w gate (`mr_gate.gate_candidate`, walk-forward log pool g = m^(1−w)·c^w, w on 0..1,
  dates ≤ d−2) in the survivor's own block, with c_pl,0 as the placebo.
- PASS needs all four legs:
  - mean w ≥ 0.05;
  - the blend R date-clustered upper bound < 1;
  - blend − placebo Brier upper bound < 0;
  - blend − floor-only Brier upper bound < 0.

There is one run. Its outputs are:

- a receipt JSON;
- per-date rows JSONL plus per-market per-date rows;
- the extracted capture-time feature file.

All of them are written once, under `C:/t/l17/ens/` only.

## (a) Positive control

These must reproduce before any candidate row is read. A failure makes the run NOT INTERPRETABLE (VOID).

- **C1, served against the market:** pooled R 1.774 (all hours) and 1.526 (00-16), to 3 digits (row 78
  receipt).
- **C2, MG-1 07-12 excess over the market:** 0.0120 (observed 0.011957 in row 78).
- **C3, the w = 0 identity:** R = 1.0, max |diff| 0.0.
- **A4 synthetic sign control (standing rule, row 91 amendment).**
  - Build: r = ((y_mid − μ_m)² − σ_m²)/σ_m² from the settled band midpoint, plus noise ε with
    SD = sd(r) and seed 20261031.
  - SYN+ uses g = r + ε, type S, sign +. It must SURVIVE.
  - SYN− uses g = −(r + ε). It must read Δ < 0.
  - The control is built in memory inside the run and reported only as its Δ and CI. It is never written
    as a feature, never a candidate and never counted in K. It reads the outcome deliberately, as a
    planted control, and is not an oracle candidate.
  - **Ruling 3 (coordinator, 2026-10-31): confirmed as a CONTROL, not an oracle, on four conditions.**
    1. It uses dev-date outcomes dated ≤ 2026-09-29 only.
    2. It stays in memory and is never written as a candidate vector.
    3. Its outputs are labelled `CONTROL`.
    4. SYN+ always runs with its negation SYN−. A run that lacks either one is VOID.

## (b) Comparator fairness

The comparator is the capture-time market. The candidate is the same market tilted by the band signal,
so it gets the same floor (none: the P0 tilts the market vector and does not add a running-max floor) and
the same calibration (the market's own moments). The placebo uses the same tilt machinery and the same
calibration, with the signal deranged across dates, so the placebo matches the candidate's flexibility
exactly. In the w gate, the floor-only control (market plus the hard floor) is the floor comparator.

## (c) Targeted loss slice

- **The 07-12 sharpness share.** About two thirds of MG-1's 07-12 excess over the market is sharpness,
  not centre. Position 0 carries +0.0093 of L6's +0.0081. This is R-H atlas `ff7ee23179be2bec…` (X27).
  EF §10ag does not itself state "two thirds" (review takeaway 6), so the figure is quoted from the atlas
  row only.
- **The 00-06 slice.** Atlas `046aa7a924af7063…` (`atlas_0006.json`).
- A type S signal targets exactly that width error. Expected size: below the 5% bar (about 0.0012), going
  by the row 78 spread kills.

## (d) MDE and clusters

| field | value | source |
| --- | --- | --- |
| N | 43 date clusters (2026-08-15..09-29) | layout |
| sigma_d of Delta | 0.00754 (proxy) | row 78 OM-GM-SPREAD date-clustered CI half-width 0.00225 → SE 0.00115 → × √43 |
| rho | not estimable before the run; reported after it | — |
| VIF | 1.78 (floor) | max(1, (1+ρ)/(1−ρ), block3²) unknown → floor 1.78 |
| MDE80 | 0.0043 in Delta units (= 2.802 · 0.00754 · √1.78 / √43) | checklist (f) |
| delta (planning) | +0.0011 (largest type S Delta point in row 78) | row 78 |
| power at delta | about 0.11 | normal approximation |
| N80 at delta | about 660 dates | (MDE80/delta)² · 43 |
| class | SCREEN (delta < MDE80) | checklist (f) |
| intervals | date-clustered, with a block-3 interval reported beside it | MIM §5 rule 7 |

Consequences:

- A KILL here is "KILL at edge size". It is not evidence that ENS spread carries no information, which
  is review takeaway 3's relabel.
- The verdict line must carry TESTED-UNDERPOWERED when the Δ CI includes +0.0043.
- The post-run sigma_d, rho and block-3 ratio are reported, and they cannot change the verdict.

### MIM §5 rule 6 and checklist (f) compliance (coordinator instruction, 2026-10-31)

**What (f) requires below power 0.5.**

- Power must be ≥ 0.5 at delta, and delta is taken at half the dev point. The checklist says: "State the
  power at the dev point and at half of it, and use half for class".
- A test that cannot show this "is a SCREEN or does not launch". That is PREREGISTRATION_CHECKLIST (f),
  `claude/s5-power-futility-gate-20261030` @ `9206b56a083cb9ca7cb63b0fafddb8c7a98a0d8d`, lines 49-79.
- MIM §5 rule 6 (`claude/docs-owner-20261030` @ `e759a55d10e31dd48559ef99b9d2959c41271fd3`, lines
  161-162) says "no screen launched below power 0.5".
- As written, (f) binds pre-registrations that spend forward dates (checklist line 51). Rule 6's sentence
  carries no such limit, and the coordinator applies it to these screens.

**Numbers.**

- SE = 0.00754·√1.78/√43 = 0.00153.
- Power at the planning δ +0.0011 is 0.107. At half (0.00055) it is 0.055.
- The same holds for both ENS-SD-0712 and ENS-SD-0006, because they share the proxy.

**Why it is not argued admissible as a "KILL at edge size" SCREEN.** A KILL closes the ENS-spread
estimand (section 7) on a read that misses a planning-size effect about 94% of the time.

**Decision.** Both arms are UNDERPOWERED, NOT RUN. K stays 2, and an arm that is not run carries p = 1.
The data check in section 0 is the only deliverable of task (c) under this rule.

**Reopening.** A run needs one of the following, as a dated Clarification with its own sha256 before any
module:

- a master ruling that rule 6 does not bind kill-only dev reads; or
- a same-pair sigma_d from a captured ENS feed that gives power ≥ 0.5 at half the dev point.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER: this is row 93. The scored dates 2026-08-15..09-29 have been read by every
market-facing dev row since row 15, and this is at least the 90th row on the dev window.

The ENS values themselves:

- they were read once before with outcomes (row 13, G2-a and G2-b, the mean only);
- the spread estimand against the market has never been read.

## 7. Kill and reopen line (written now)

**KILL scope.** A KILL closes the ECMWF open-data ENS member SD of the 00Z three-step daily-max proxy
against the market, at 00-06 and 07-12, on dev.

**What reopens it.** Only a captured ENS feed (true receipt times, hourly steps) together with a new rule
on dates disjoint from dev, with the mechanism written first.

**What is not covered.** The kill does not cover:

- ENS as a model-side width input (R9 open family, own ladder);
- the ENS mean on a new arm.

No other quantile, step set, block, sign or transform runs under any name.

## 8. Test plan (before any run; the coordinator admits the module)

- **Module.** A new module `weather.calibration.ens_spread_p0` on a run branch off the `loyo_screen` run
  environment (`8bb0f9563582885c4d01d34b67476f2563260e43`). It is wired as `loyo_screen ens-spread-p0`.
  - It does no network I/O.
  - It reads `points.parquet` only after its sha256 pin.
  - It refuses to write outside `C:/t/l17/ens/`.
  - It refuses any target_date > 2026-09-29.
- **Unit tests (synthetic frames only, no real rows).**
  - The covered-iff rule: `available_utc` against `captured_at_utc`, the n_members filter, and D versus
    D−1 run selection by block.
  - The ICAO-to-market map.
  - A refusal on a wrong pin and on a post-cutoff date.
  - SYN+/SYN− signs on a toy market.
  - Pytest runs with `--basetemp` under `C:\t\l17\pytest-ens`, which is deleted afterwards.
- **The run.** One run, after admission, via
  `scripts\ops\workstation_heavy.ps1 -Queue -Kind weather_heavy`, with OMP/MKL/OPENBLAS set to 10,
  `-MinAvailableMemoryGB 3` and a write-once out dir.
