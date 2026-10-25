# Development scorecard (lane C, 2026-10-23)

**Status:** dated research record. Owns the design of `weather.reporting.scorecards.dev_scorecard`,
the inventory it was built from, and its positive-control result. Every number is **development**
evidence (dates <= 2026-09-29); nothing here is confirmation, edge or promotion evidence.

**Read when:** you score a model change on development dates, or need to know what the scorecard
reads and refuses.

## Inventory (what existed before the build)

| Item | Where | What it is |
| --- | --- | --- |
| "L1 scoreboard" | not found | No code, doc or branch uses the name. The nearest objects are `weather.reporting.market.market_beating_objective_scoreboard` (live daily scoreboard, not walk-forward) and HARNESS v2/v3 below. |
| HARNESS v2 | master, `tools/research/model_parity/harness.py` | Swarm scorer on the 111h extract; floor mask, served fallback, one crossed W (2,000 draws, seed 20260921). Positive control 111h C1 and served/market 1.768x [1.568, 2.039]. |
| HARNESS v3 | **unmerged**, `claude/harness-v3-20261019`, `tools/research/model_parity/v3_*.py`; [record](https://github.com/michaelbooth1/weather/blob/claude/harness-v3-20261019/docs/research/harness-v3-2026-10-19.md) on that branch | Gate, dry run, power, single-shot sealed scorer, label ledger; control (a) reproduces EF §3 to every digit from a fixture. Endpoint E1 R = Brier_arm / Brier_market per block. |
| Dev layout (scored corpus) | workstation `C:\swarm\v3layout` (`harness_v3_layout/1`, built 2026-10-19 from the v2 cache) | 11 US markets (no Toronto), 57 dates 2026-08-01..09-29 (08-16, 09-01, 09-02 absent), 110,807 snapshots, 1,218,877 band rows, 626 market-days. Inputs, labels and per-band market prices in separate sha-pinned files. |
| Replay corpus | workstation `data\inbox\replay-inputs-le0929\` (checksum-verified copy, `SHA256SUMS`) | 732 folders = 12 markets x 61 dates 07-31..09-29, `replay_inputs.jsonl` only (no prices). Lever-5 / M8 replays ran on it (EF §10u, §10v). |
| Market prices <= 09-29 | inside the layout (`market.parquet`, captured `p_market_yes` per band per snapshot) | No separate book/snapshot tree on the workstation; Toronto has none here. |
| Settlement labels <= 09-29 | layout `labels.parquet`, from `data/settlements/<market>/ledger.jsonl` (WU daily history, `settlement_authority=ledger_authority`, per the 111h `market_days`) | One settled band per market-day; `promotion_countable` false (development). |
| Pre-registered rules | EF §1, §1b, §1d, §5, §10j; HARNESS v2 README | Brier per band, averaged per snapshot then equal market-day cells; gap ratio R = model/market (not interpretable when market Brier < 0.005); crossed date x market clustering mandatory; MDE80 from the centred bootstrap at effect −0.0075; the market clusters set a hard floor (12 in the sealed panel, 11 US here). |

## Design

- **CLI:** `python -m weather.reporting.scorecards.dev_scorecard score|control-floor` (module docstrings
  hold the full contract; inputs in `dev_scorecard_data`).
- **Date guard:** `--to` after 2026-09-29 or `--from` before 2026-07-31 is refused (exit 2) before the
  layout is opened; a manifest declaring any later date refuses the file before it is opened; rows are
  sha-checked and filtered at read time, then re-checked.
- **Candidates:** `--candidate served|market` (served vector of record; market identity control),
  `--candidate-module` (walk-forward `fit(train)` / `predict(state, snapshots, bands)`; labels and
  prices never reach `predict`), `--candidate-vectors` (row_key, band_index, p) or
  `--candidate-distributions` (jsonl of native-degree distributions, e.g. a served-vector replay), each
  with `--trained-through DATE` or `--no-training`. Candidates get the v2 floor mask and served fallback.
- **Fold scheme:** consecutive `--fold-days` (7) calendar folds from `--from`; a fold trains on layout
  dates <= fold start − (`--gap-days` + 1) (default: D−2, because D−1 settles during D); scored only when
  the pool has >= `--min-train-dates` (7) dates. The scheme alone fixes the scored rows, so every
  candidate type is scored on the same population. With the defaults on 08-01..09-29 scoring starts 08-15.
- **Output rows** per market x block (00-05, 06-09, 10-12, 13-16, 17-23, 00-16, all) and pooled `ALL`:
  Brier and log score for model, market and served; gap ratio with crossed interval; model − market (and
  model − served) with interval and MDE80; n_dates, n_markets; provenance; `powered` = every resampled
  dimension has >= 12 clusters (dates per market; dates and markets pooled), so no pooled US row can be
  powered (EF §10j).
- **Results:** content-addressed `<out>/<sha256>.json` and `.md`; no wall-clock field, fixed seeds.
- **Base caveat (EF §10v):** `served` is the vector of record; a replay-derived candidate's delta to it
  mixes current-code drift with the variant.

## Positive control (EF §3, fixture `hard_floor_snapshot_deltas.csv @ ba748b76`, vendored gzip, sha-checked)

| Method | Before | After | Delta [95%] |
| --- | --- | --- | --- |
| Tracker (seed 3215258335) | 1.6639158425 | 1.4979600580 | −0.1659557845 [−0.3552671491, −0.0697874559]; every digit matches EF §3 |
| Scorecard (equal market-day cells, crossed W) | 1.7945 [1.3958, 2.6061] | 1.5211 [1.2348, 1.9165] | −0.2733 [−0.8649, −0.0662] |

Sign reproduced, interval excludes 0: **PASS** (D=8, M=11, 85 market-days; unpowered at the 12-cluster
floor). The fixture dates are 07-02..07-10, a control-only use.

## Baseline (served vs market)

**Not run.** `scripts\ops\workstation_heavy.ps1 -Kind weather_heavy` refuses
`weather.reporting.scorecards.dev_scorecard` (not on the offline allowlist in
`scripts/ops/workload_admission.ps1`). Running it needs a reviewed allowlist line or an explicit
ruling; the command is then:

```powershell
python -m weather.reporting.scorecards.dev_scorecard score --layout C:\swarm\v3layout `
  --from 2026-08-01 --to 2026-09-29 --candidate served --out <dir>
```

Expected consistency check on the full range with `--min-train-dates 0`: pooled `all` served/market
1.768x [1.568, 2.039] (HARNESS v2).

## Update when

Do not rewrite this record; add dated addenda (for example, the baseline once it runs).

## Addendum 2026-10-23 (lane G, `claude/free-source-screens-20261023`)

Additive changes for the free-source screens; existing rows and numbers are unchanged:
- `--control-module` / `--control-vectors`: a second candidate scored on the same rows and crossed weights;
  each row then carries `brier_control`, `model_minus_control` (with MDE80) and `control_minus_served`, the
  paired increment of a source over its no-source rule.
- A `00-12` aggregate row (MG-1's block) beside `00-16` and `all`.
- A module candidate whose fitted state is a dict with a `provenance` dict has it recorded once as
  `candidate.state_provenance` (input file hashes, fixed tables).
- `--hourly` (lever L4): adds one pooled and per-market row per local hour (`h00`..`h23`) and a `07-12`
  aggregate; with a control, pooled rows also carry date-clustered `model_minus_control_date_clustered` and
  `model_minus_served_date_clustered` (secondary; the crossed interval stays binding, EF ?5).
Record of use: [free-source screens](free-source-screens-2026-10-23.md).
