# L2 rung R-V pre-registration: MOS/NBE day-max guidance as one 13-16 centre column on P3d_N_fix

Written 2026-10-26, before any MOS or NBE value has been joined to an outcome, label, price or market row.

- **Authority:** the owner's decision of 2026-10-25 ("option B"), relayed by the coordinator, who ordered R-V on
  2026-10-26 as second priority behind the MG-3 waits.
- **Evidence class:** development evidence only; no edge claim. Dev evidence alone cannot promote, bind or enter
  MG-2 or MG-3 (production captures no MOS or NBE; see "Forward parity").
- **Data limits:**
  - Nothing dated after 2026-09-29 is read. Guidance rows with a runtime on or after 2026-09-30 00Z are dropped
    at fetch.
  - Nothing touches MG-2, MG-3 or L8's branch.
  - No paid data, no new dependency, no pyproject or requirements change.
- **Code:** branch `claude/rv-mos-1316-20261026`. This rule's sha256 is recorded in code (`RV_RULE_SHA256`)
  before any R-V row exists.

## Register rows checked

Source: `docs/operations/EXHAUSTION_REGISTER.md` on `origin/claude/docs-head-20261026c` @ `e0f6bc1d6` (the newest
register head; `origin/master` @ `c33176cbf` holds an older copy).

- **S5:** "MOS / NBE (MAV/MET/MEX/LAV + NBE; MET is NAM-MOS) ... TESTED-UNDERPOWERED: 00-16 -0.0015 [-0.0049,
  +0.0019]. 13-14 -0.0063 [-0.0119, -0.0006] is post-hoc and not an increment over t3-r3 (-0.0031 [-0.0077,
  +0.0017]) ... ~90% of its morning gain is the captured-v2 control."
- **Row 16:** "No increment *exists*" is "not established at the 5% bar for NBH, MOS/NBE, ECMWF, HRRR and cloud."
- **Order 11:** "One source at a time ... MOS/NBE (IEM text, ~5-6 MB/month)".
- **X30 (R-P):** "a pooled LOYO intercept win is a bias correction, not information." This is why gate 1 also has
  an intercept-only control.
- **X33/X35 (R-L, R-L2):** NBS TXN closed at 07-12; "NBS omits the target day's TXN max from cycles issued at 13Z
  and later". Gate 1a here checks that the day-max exists in the cycles R-V uses, by year.
- **X36 (R-M):** a per-market additive shift on P3d_N_fix at 07-12 was null. It does not cover 13-16 or MOS.
- **X37/X38:** spread and width forms; R-V has none.
- **No X row closes MOS or NBE at 13-16 or over P3d_N_fix.**

The coordinator's relay also lists, by its own numbering: row 8 (R-T) vetoed by master; row 6 closed by
X33/X35; rows 5, 7 and 9 closed by X36, X30 and X37/X38; row 14 at 07-12 overlaps X6's multi-model family;
row 13 needs an owner call; row 18 is S5, never run over P3d_N. R-V is none of the closed rows:
- it is not an NBS TXN form (X33/X35) or a per-market shift (X36);
- it is a guidance value with a slope the model fits, scored against an intercept-only control (X30);
- it is at 13-16, not 07-12 (X6);
- it uses no floor, trajectory or high_so_far-gap column (closed by R-J), no HRRR, and no spread or width.

## How R-V differs from S5

| | S5 | R-V |
| --- | --- | --- |
| Model | An increment over MG-1 / the served model, captured v2 emulated | A residual input to L2's pooled HGB model P3d_N_fix |
| Training | One Aug-Sep season (2026 dev) | Blocked LOYO over five seasons (Aug-Sep 2021-25) |
| Hours | 00-16, with a post-hoc 13-14 cut | 13-16 only, declared here |
| Form | Hunter-chosen forms | One column, fixed below |

## Archive facts (inputs only; read before this rule)

- **Source:** the Iowa Environmental Mesonet MOS archive, `https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py`.
  Official, free, no key.
- **Model names:** IEM `GFS` is GFS-MOS (MAV) and IEM `NAM` is NAM-MOS (MET). `MAV` and `MET` are refused.
- **Day-max fields:** `n_x` (GFS, NAM) and `txn` (NBE) at forecast time (D+1) 00Z. That is the daytime maximum
  of day D for every US market.
- **Which runs carry D's max (probed on 2021-08-20 and 2026 Aug-Sep):**
  - GFS: the 00Z and 06Z runs of UTC day D. The 12Z and 18Z runs do not.
  - NAM: the 00Z run of D only. The 12Z run does not.
  - NBE: in 2021-25, the 01Z and 07Z runs of D (runs at 01/07/13/19Z). In the 2026 archive, NBE runs are at
    00Z and 12Z and only the 00Z run carries D's max.
- **Coverage probe, 2021-25 (08-20 of each year, 11 stations x 3 models, all runs of the day):**
  - Throttled to one request per 10 s. At hashing it had returned 38 of the 165 files: KATL and KAUS for every
    model and year, and KBKF for 2021-23.
  - Every returned file is a non-empty CSV with the day-max field present, in the runs listed above, in every year.
  - The remaining files are reported with the sha, not used to choose anything. Gate 1a measures coverage on every
    training row and decides.
- **A 2026 copy exists** at `C:\swarm\data\iem\mos` (A-IEM-2, May-Sep 2026). R-V does not use it. Train and dev
  are fetched by one R-V fetcher (see "Data").

## The column (pre-committed, exactly one)

**For a row:** market m (station from the market registry), local target date D, cutoff hour h ∈ {13, 14, 15, 16},
snapshot instant t = h:00 local on D.

**Per source**, the value is the day-max field at forecast time (D+1) 00:00Z from one run:
- **GFS-MOS (`n_x`):** the latest of the 06Z and 00Z runs of UTC day D with runtime + 4 h 30 min ≤ t that carries
  an available value (below).
- **NAM-MOS (`n_x`):** the 00Z run of UTC day D, if runtime + 4 h 00 min ≤ t.
- **NBE (`txn`):** the 01Z run of UTC day D, else its 00Z run (01Z exists in 2021-25, 00Z in 2026), if runtime
  + 2 h 00 min ≤ t and it carries an available value.

The lags are fixed constants, the same in training and dev:
- GFS and NAM are the A-IEM-2 manifest's lags (NCO production-status times plus margin).
- NBE is 17 minutes above the measured 2026 90th percentile of 1 h 43 min (A-IEM-2 S3 listings).
- At t ≥ 13:00 local every US market is at or after 17Z, so every selected run is available by at least 6 h. The
  lags cannot bind at 13-16.

**Stated deviation (NBE cycle):** this is not the coordinator's "latest cycle issued ≤ as-of".
- In 2021-25 "latest" would be the 07Z run. In the 2026 archive it is the 00Z run: a 6-7 h train/serve staleness
  shift that no training row exhibits.
- Fixing the early D-bearing cycle keeps train and dev on the same lead.
- GFS and NAM keep "latest D-bearing run", which has the same cycles in every year.

**Composite:** `mos_x` = the mean of the available source values. A source value is available when it is finite
and within [−40, 130] °F. At least 2 of the 3 sources are required; otherwise `mos_x` is NaN.

**The model column:** `v_gap` = `mos_x` − the row's own NBM anchor.
- In training the anchor is L9's `nbm_at_cutoff` (`fh`). On dev it is the captured `usable_v2_mean`, exactly as
  R-K's `k_gap`.
- It is NaN when `mos_x` or the anchor is NaN. HGB takes NaN natively.
- `v_gap` does not change across h13-16 for a given day unless the anchor does.

**Arms (per cutoff hour h13-16, R-A's inputs, as-of-capture snapshot rule, WU whole °F):**
- **P3d_N_fix:** R-A's arm, unchanged.
- **P3d_V** = P3d_N_fix + `extra_hgb` (`v_gap`).
- **P3d_I (intercept-only control)** = P3d_N_fix + `extra_ols` (10 market indicators `mi_<market>`, Atlanta the
  base level).
  - Per-hour fits make this a per-market/hour intercept.
  - It is fitted the same way as P3d_V: the same rows, the same inner-LOYO scale model and the same nesting.
  - The OLS step (not HGB) is used because an intercept is linear and HGB already sees lat, lon and elevation.
- **B_N:** R-A's arm, only for the reproduction control.

**Constraints:**
- No other MOS, NBE or LAMP field, cycle, lag, source subset, weighting, transform or interaction is used.
- No floor, trajectory or high_so_far-gap column; no HRRR; no spread or width column.
- No MEX, LAV or NBS.

## Data

- **One fetcher for train and dev:**
  - `rv-fetch` in the R-V code: IEM `mos.py`, models GFS, NAM and NBE, the 11 US stations.
  - Runtimes from 07-31 00Z to 09-30 23:59Z for 2021-25, and from 2026-07-31 00Z to 2026-09-29 23:59Z for dev.
  - One connection, ≥ 8 s between requests, backing off on "Too many requests".
  - It writes raw CSVs and a manifest with each file's sha256. Raw bytes are a few MB in total.
- **Training rows:** R-A's 2021-25 Aug-Sep h13-16 rows (`dev_training_frame`), the same as R-J and R-K.
- **Dev rows:** R-K's dev population (scorecard folds 2026-08-01..09-29, scored 08-15..09-29), h13-16.

## Gates (in order; each stops the rung if it fails)

### Gate 1a: coverage (inputs only)

- **Requirement:** `mos_x` finite on ≥ 0.95 of the training rows 2021-25 h13-16.
- **Reported:** per source and per year, the share of rows whose selected run exists and carries the D-max field.
  This is the R-L lesson: a field present in early cycles can be absent in later ones or later versions.
- **On failure:** R-V stops as STOPPED at gate 1a (not a kill).

### Gate 1b: version shift (inputs only, training years)

- **Reported per year 2021-25:** mean and sd of each source minus the training anchor `fh`, and of `v_gap`.
- **Requirement:** no per-year mean of `v_gap` differs from the pooled 2021-25 mean by more than 1.5 °F.
- **On failure:** STOPPED at gate 1b (not a kill).

### Gate 1: nested LOYO 2021-25 Aug-Sep at 13-16

- **Rows:** blocked leave-one-year-out (`rung_loyo`), all four arms on identical rows.
- **Statistic:** mean per row of the Brier difference, pooled over h13-16, with a date-clustered bootstrap (2,000
  draws, seed 20261024).
- **PASS requires both:**
  - Brier(P3d_V) − Brier(P3d_N_fix): upper 95% bound < 0;
  - Brier(P3d_V) − Brier(P3d_I): upper 95% bound < 0.
- **Reported:** each hour, h13-14 and h15-16; P3d_I − P3d_N_fix; per market; log loss.
- **Reproduction control (refused otherwise, not a gate):** P3d_N_fix and B_N LOYO rows at h13-16 equal R-J's
  `loyo_rows.jsonl` (same keys, max |diff| ≤ 1e-12), as in R-K.

### Gate 2: dev, P3d_V beats P3d_N_fix at 13-16

- **Before any dev read:** a DEV_WINDOW_LEDGER row is filed naming this rule's sha. Selection evidence only.
- **Dev input checks (inputs only; STOPPED, not a kill, if failed):**
  - `mos_x` finite on ≥ 0.95 of the dev rows h13-16;
  - |mean dev `v_gap` − mean training `v_gap`| ≤ 1.5 °F.
- **Statistic:** dR = mean_cell(Brier_P3d_V − Brier_P3d_N_fix) / mean_cell(Brier_market), ALL markets, h13-16
  pooled, with date-clustered 95% intervals (2,000 draws, seed 20260921), on snapshots covered by both arms.
- **PASS** if the upper bound is below 0.
- **Reported only:** P3d_V − P3d_I, each hour, h13-14, h15-16, per market, and R vs market.
- **Reproduction controls (refused otherwise):**
  - P3d_N_fix at 13-16 is byte-identical to R-H's (`abc43507…`);
  - MG-1's 07-12 control gives 0.012.

## PRE-REGISTERED KILL

If gate 1 or gate 2 fails, MOS/NBE day-max guidance is closed as a 13-16 centre input on P3d_N_fix. No other
MOS/NBE field, cycle, lag, source subset, weighting or transform is run as a 13-16 centre input on this family.
Gates 1a and 1b, and the dev input checks, are STOPs, not kills.

## Forward parity

- Production does not capture MOS or NBE. A gate-2 PASS gives a drafted proposal only:
  - a forward recorder of the same three runs with retrieval stamps;
  - a captured-forward check that its lag stays inside the constants above;
  - a snapshot payload carrying the run identities for captured-input replay and release binding.
- No promotion, MG-2/MG-3 change or binding follows from R-V evidence.
