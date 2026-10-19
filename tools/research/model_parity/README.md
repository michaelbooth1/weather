# Model-parity swarm v2 — shared scoring harness (F1)

Development-only scorer for the night 2026-10-03/04 model-parity swarm. It runs on the 111h Part-1
extract (`C:\Users\Michael\Documents\nbm-guidance-111h`, read in place, never copied into the
repository): 110,807 snapshots, 626 market-days, 57 dates, 11 US markets, targets
2026-08-01..2026-09-29. Every number it produces is **development** evidence. The from stratum
(08-23..09-29) was already read by 79a/81a/111h, so it is never a holdout. Nothing here is imported
by serving.

- `harness.py` is the harness. `HARNESS_SHA256` = `harness_sha256()` (sha256 over `harness.py`
  followed by `__init__.py`). Any edit changes it, and results scored under an older hash are stale.
- `f1_candidate_template.py` is a copyable hunter skeleton covering both input patterns.
- `test_harness.py` holds the fixture-only contracts (synthetic extract, no external data).
- `C:\swarm\HARNESS.md` carries the current hash, the positive-control result and usage notes.

## Contract

1. **Cache.** `build_cache()` checks each file against `SHA256SUMS` and requires manifest status
   `COMPLETE` at parser `2e17ce0eb`. It then writes `C:\swarm\cache\{snapshots,bands}.parquet`,
   `W.npy` and `W_keys.json`, plus `cache_receipt.json`. In `bands.parquet` each row is one
   snapshot × band, keyed by `row_key = market|snapshot_id` (`snapshot_id` alone is not unique
   across markets).
2. **Rule 5.** Rows with a target date after 2026-09-29 are counted and never cached. This
   extract has 0 such rows. Loading refuses a cache whose count is not 0.
3. **Rules 2/3.** `candidate_inputs()` returns allow-listed columns only: no prices, books, mids,
   winner or settlement. `from_rowwise` hands the rule `GuardedDict`s, which raise `LeakageError`
   on forbidden keys. `score()` accepts only a frame with columns `row_key, band_index, p` and
   flags any block where the candidate's Brier is below half the market's as a leakage suspect.
4. **Rule 4.** `score()` applies 81a's floor mask itself and renormalises. The floor is the max of
   the captured `guidance_physical_floor`, `high_so_far` and `trusted_current_max`. A non-gte band
   whose `high` is below `floor(floor + 0.5)` gets 0. If a row has no captured floor, the candidate
   falls back to served (as in 81a). `unfloored=True` is a labelled diagnostic and is never
   classified LEAD.
5. **Rule 6.** The primary estimand is `all_row`: a row the candidate does not cover is scored as
   served. `matched` tables are secondary and labelled "selected on availability".
6. **Statistics.** Per-snapshot Brier is the mean over bands. Snapshots are averaged within a
   market-day, and every market-day weighs the same. There is one crossed date × market weight
   matrix W (2000 × 626, 81a `crossed_weights`, seed 20260921), so every interval is
   `W[:, cells] @ values` as a ratio of sums. MDE80 and power come from 81a's `inference` with an
   effect of −0.0075.
7. **Tables.** These cover the groups 00-05, 06-09, 10-12, 13-16, 17-23, 00-16 and all, each split
   by stratum (before, from, pooled) and population (all_row, matched). Each table gives:
   - candidate − served, with MDE80;
   - candidate − market;
   - served − market;
   - the ratio to market, flagged not interpretable when market Brier < 0.005;
   - the share of the gap closed;
   - per-market deltas and sign counts.

   Tail rows follow the EF 1/1f definition: band rows where served SE > market SE and
   |p_served − p_market| ≥ 0.30.
8. **LEAD rule (DESIGN §1).** A block is a LEAD when its from-stratum all-row delta meets all four
   conditions below. WEAK means a negative estimate that misses a condition. HARM means the
   interval lies above 0. NULL is everything else.
   - The 95% interval excludes 0.
   - The estimate is ≤ −0.0133, or ≤ −5% of the block's from-stratum served − market gap.
   - The before-stratum and from-stratum estimates are both negative.
   - At least 8 from-stratum markets are negative.

## Use

```powershell
cd C:\pt\swarm
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -m tools.research.model_parity.f1_candidate_template
```

```python
from tools.research.model_parity import harness as h
snaps, bands = h.candidate_inputs()              # allowed inputs only
cand = bands[["row_key", "band_index"]].assign(p=my_probs)
result = h.score(cand, name="t01_decided_band")  # floor + fallback applied here
h.save(result, r"C:\swarm\out\t01")
print(h.markdown(result))
```

Tests (workstation): run
`python -m pytest -q -p no:cacheprovider --basetemp <scratch> tools/research/model_parity/test_harness.py`,
then delete the basetemp.

## HARNESS v3 (2026-10-19, model-edge programme)

`harness.py` is unchanged, so `score()` and its positive control still reproduce under
`HARNESS_SHA256 = 8db69adc…`. v3 adds modules beside it; `v3_score.harness_v3_sha256()` hashes
`harness.py`, `__init__.py` and every `v3_*.py` module listed in `v3_score.V3_FILES`. Controls and
their numbers: [docs/research/harness-v3-2026-10-19.md](../../../docs/research/harness-v3-2026-10-19.md).

- `v3_gate.py` (H1) decides every request by (family, date, purpose). It reads the status paragraph of
  `docs/operations/reserved-confirmation-window.md` and `forward_alpha_ledger.jsonl` (schema
  `forward_alpha_ledger/1`; statuses `reserved`, `closed_by_default`, `open`, `spent`; scope `join` or
  `all`). It fails closed if either source is missing or unparseable. Append rows with
  `v3_gate.append_row`; never edit earlier rows.
- `v3_inputs.py` and `v3_outcomes.py` split a layout into outcome-free inputs and outcome files
  (labels, market prices). Only `v3_outcomes` names, opens or writes the outcome files, and only with a gate
  `Ticket`. `split_v2_cache` derives a layout from the v2 cache (dates <= 2026-09-29).
- `v3_dryrun.py` (H2) reports coverage and countability only, and never imports or opens the outcome side.
- `v3_power.py` (H3) is an outcome-free crossed power/MDE simulator. Its variance components come from
  a dev stats entry.
- `v3_sequential.py` (H7) computes non-binding O'Brien-Fleming-type futility boundaries.
- `v3_score.py` (H4/H5/H6) is the single-shot scorer. Its exit codes: 2 for a hash mismatch, 3 when
  a sealed result exists, 4 for a planted label, 5 for a gate refusal. E1 is R = Brier_arm/Brier_market
  per block. E2 is a frozen-weight blend, labelled complementary information, not edge.
  Every arm is also scored as its input-removed twin. It also writes the label ledger.
- Arms are single files that declare `NAME`, `FAMILY`, `READS_NBM_GUIDANCE`, `INPUTS` and `build()`
  (see `v3_arms.py`). `v3_arm_mg1_like.py` and `v3_arm_served.py` are control arms.
  `v3_arm_mg1_like.py` is not the signed MG-1 vector.
- `test_harness_v3.py` holds the synthetic unit tests. `test_v3_controls_dev.py` holds the dev
  controls: it is skipped unless `HARNESS_V3_DEV=1`, and runs only through
  `scripts\ops\workstation_heavy.ps1 -Kind pytest`.
