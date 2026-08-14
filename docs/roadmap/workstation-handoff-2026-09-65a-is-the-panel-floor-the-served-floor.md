# Workstation handoff 2026-09-65a — is the panel's floor the floor we actually served?

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**No α, no candidate, no C model.** Same standing as `-09-64a`: this audits the measuring
instrument, not a hypothesis about the world.

## 1. What `-09-64a` settled, and the one thing it did not

`-09-64a` is a **precise null and it holds** — I reproduced every figure on production to the last
digit. The blind-feature repair adds **no** realized-band zeros; repaired and control are identical
row-for-row. **Do not revisit that.** Sections 1c–1g stand on that axis.

**Two corrections to the reference numbers I gave you, both mine:**

1. **The served `1.017%` was wrong to quote.** It averaged across a regime change.
   `snapshots_long.csv` gained a `bin_value_hi_c` column on **2026-06-15**, all 12 markets at once
   (`28d1c146`). Fahrenheit realized-band zeros: **8.486% before (1,016 / 11,973), 0.000% after
   (0 / 79,133).** Your report was right to call the comparison descriptive rather than paired.
2. **The research path never had that defect.** `band_value_hi` parses the upper degree out of
   `range_label` when the explicit column is absent (`market_microstructure_features.py:101`,
   `backtesting/replay.py:145`, `backtesting/settlement_io.py:59`). Only the serving consumer read
   the serialized field with no fallback. So the panel's zeros were never the same phenomenon.

Full correction: `docs/operations/SERVED_BAND_FLOOR_DEFECT_2026-08-10.md`.

**What that leaves is a floor question, and one row that does not reconcile.**

Your single C zero is **Seattle `2026-07-16`**. Production's floor audit independently flags that
exact market-day: `high_so_far` = 68 against a settled 64, 8 snapshots, unquarantined. **That one
lines up.** But:

> **Denver `2026-06-08` does not.** It settled `82.0°F` on band `82-83°F` — the **lower** degree,
> where the lost-edge mechanism cannot produce a zero at any floor. Production's floor never
> exceeded the settled high that day. **Production served that band `0.5206`. The panel says
> `0.0`.** Nothing in production's floor tape reproduces that.
>
> **A floor that is wrong does not only produce zeros. It shifts mass on every row it touches.**
> The 29 zeros are the visible tip; if the panel's floor is not the served floor, the disagreement
> is larger than 29 rows and it sits underneath every number this campaign has produced.

**I am not asserting the panel's floor is wrong.** Seattle reconciles. Denver does not. That is the
whole basis for asking, and either answer is worth having.

## 2. What to do

**The join happens on production, not on your host** — I hold the served floor tape and you hold
the panel. So your deliverable is an artifact plus a trace, not a verdict.

### 2a. Emit the panel's floor, one row per snapshot

Commit to `docs/roadmap/pit-panel-floor-2026-09-65a.csv` with a `-manifest.json` and `.sha256`
beside it, exactly as `-09-61a` did for the feature extract. One row per panel snapshot
(**12,289** expected), columns:

| Column | Meaning |
| --- | --- |
| `stratum` | `B` or `C`, as the panel labels it |
| `market_id`, `target_date`, `snapshot_id` | the join key — `snapshot_id` verbatim, do not reformat |
| `floor_bucket` | the floor the panel's scoring actually used, integer, empty if none |
| `floor_source_field` | the field it came from, e.g. `high_so_far` / `observed_floor_bucket` |
| `realized_band_kind`, `realized_band_value`, `realized_band_value_hi` | the `outcome == 1` band |
| `repair_probability`, `control_probability` | on the realized band |

**No outcomes beyond the band identity, no market prices, no fitted quantities.** Keep it under a
megabyte; if it will not fit, say so rather than trimming rows silently.

If the panel does **not** carry a floor column, say so plainly, emit whatever identifies the
snapshot, and go straight to 2b — that is itself the answer to "is it the same floor", because a
panel that cannot show its floor cannot be checked against serving.

### 2b. Trace where the replay's floor comes from

Read, do not guess. The chain on master is:

```
pooled_candidate_replay.py:1320   kind, value, value_hi = snapshot_band_key(row)
pooled_candidate_replay.py:1322   band_row = band_prediction_record(feature_row, kind, value, value_hi=value_hi)
pooled_candidate_replay.py:1334   floor_bucket=band_row.get("observed_floor_bucket")
variant_prediction_runtime.py:369 floor_bucket = round_half_up(high_so_far)
```

Answer three things with file:line evidence:

- **Where does `feature_row` come from**, and is it the row captured at that snapshot or one
  reconstructed later? If reconstructed, from what?
- **Is the floor point-in-time?** Can any value that was only observable *after* the snapshot reach
  `high_so_far` on that path? This is the `forecast_high` shape (§ `forecast-high-is-not-point-in-time`)
  and it is the specific failure worth ruling in or out.
- **Denver `2026-06-08`, the panel's own rows**: what floor did it use, what was the realized band,
  and what step drove the repaired probability to exactly `0.0`? Walk one snapshot end to end.
  **A grep is not a trace.**

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED**; `-09-63a` retired it and it must not be reassigned.
- **You may read C**, on the same grounds as `-09-64a`: no candidate, no fitted parameter, no
  endpoint comparison, no accept rule. **Say so explicitly in the report.**
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). Report B and C separately.
- **Do not change the replay, the floor, or any scoring code.** Locating the divergence is the
  deliverable; fixing it is production work and needs a replay measurement first.
- **Never weaken the serving floor.** It is the one shipped win (`1.6639 → 1.4980`).
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, nothing under production
  `data/`, no promotion, activation, release or trading.

## 4. What would close this as a null

- **The panel's floor is the captured point-in-time floor, and Denver `2026-06-08`'s zero has a
  benign explanation** → the instrument is sound, the campaign's surface is the served surface on
  this axis, and this closes. **Write that down with the trace; it is as valuable as the
  alternative.** I will confirm it against the production tape either way.

## 5. Environment, branch and report

The repo venv on that host points at a removed Python 3.11; use the bundled Codex 3.12 runtime.
Install nothing.

- Branch: `codex/workstation-is-the-panel-floor-the-served-floor-2026-09-65a`
- Report: `docs/roadmap/agent-report-2026-08-20-workstation-panel-floor-provenance.md`
- Commit the extract script alongside the artifact.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
