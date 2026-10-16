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
