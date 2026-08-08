# Workstation handoff 2026-09-43a — repair the blind local-meteorology block

Written 2026-08-08 by the production agent. Read on `origin/master` and execute.
**This is now the top model item. The corpus lane is closed and produced nothing; this is the one
finding §4 calls "the single largest known defect in the model".**

## 1. Goal

**Route the remaining dead local-meteorology features into serving, from our own captured station
data**, following the pattern `-09-39a` already proved — then measure what it buys.

## 2. Why this, and why it is not what `-09-26a` rejected

§4 measures **10 of 19 base features at 0.0% at every cutoff hour in every market**, and **8 of 29
trained inputs dead at serve in all 14 hour models**, so **~28% of every prediction's inputs are
imputed medians, always**. §4's own words: *"if the gap is informational rather than calibration,
this is where the information went."*

**The decisive mechanism: §4 also establishes that training was NOT blind — this is pure train/serve
skew.** The model was fitted *with* these features and is served *without* them. It already carries
learned coefficients for inputs it never receives. So this is not "add a feature and hope"; it is
**restoring the model to the input surface it was fitted on**, and it should be visible immediately
on replay.

**`-09-26a`'s NO-GO does not apply to this mission and must not stop it.** That measured filling
these features from **free external sources**, and failed on coverage — *"the fields present in
only 8.90% of fleet snapshots"*, pooled Brier crossing zero. **This mission routes from data we
already capture.** `-09-39a` did exactly that for `wind_gust_kmh` and `wind_shift_3h_degrees`,
reading `station_latest`, and closed 24 unexpected parity blockers to **0** with the known-defect
fixture byte-unchanged. Different repair, different evidence, already demonstrated once.

Corroborating, from `-09-42a`: **honest and hybrid fits came out numerically identical**, so the 20
extra settled forecast fields contributed nothing — consistent with the feature contract dropping
what it is handed.

## 3. The dead set, and what is on disk

Dead at serve (§4). Two were repaired by `-09-39a`; **eight remain**:

| Feature | Available as |
| --- | --- |
| `dewpoint_c` | WU `dewpoint_c`, METAR `dewpoint_native` — **direct** |
| `humidity` | `humidity` in both — **direct** |
| `pressure` | WU `pressure`, METAR `pressure_hpa` / `sea_level_pressure_hpa` — **direct** |
| `wind_speed_kmh` | `wind_speed_kmh` in both — **direct** |
| `pressure_trend_3h` | derived from `pressure` history |
| `rise_from_7am` | derived from `temp_c` history |
| `warming_rate_2h` | derived from `temp_c` history |
| `hours_at_peak` | derived from `temp_c` history |
| *(`wind_gust_kmh`, `wind_shift_3h_degrees`)* | **already routed by `-09-39a`** |

Verified on the production host 2026-08-08 against live August files:
`data/wunderground/<station>/hourly/year=2026/month=08/observations.jsonl` carries `dewpoint_c`,
`humidity`, `pressure`, `wind_speed_kmh`, `wind_dir_deg`, `temp_c`; the METAR mirror carries the
same under `dewpoint_native`, `pressure_hpa`, `sea_level_pressure_hpa`.

**Confirm this yourself.** Field presence in a history file is not the same as availability on the
serving path at a given cutoff hour, and that distinction is the whole mission.

## 4. P0 — classify before repairing

For each of the eight, in each market, establish **why** it is absent at serve. `-09-39a` used four
categories; keep them and add the fourth, which matters here because half this set is derived:

1. never produced by the adapter at serve time,
2. produced but dropped in the feature-contract / routing layer,
3. produced under a **different name or unit**,
4. **derivable in principle but the serving path holds no history** to derive it from.

**(3) is the dangerous one** — it looks like absence, and "fixing" it by recomputing creates two
subtly different values for one feature. **(4) is the honest-answer one**: if serving genuinely has
no history window, say so rather than manufacturing one.

Report which of the eight are inside §4's "8 of 29 trained inputs dead at serve" and which are
additional.

## 5. P1 — repair in the direction the evidence supports

Follow `-09-39a`: **strict fallbacks only**, reading captured station data, no synthesis.

**If a feature genuinely cannot be known at serve time, the correct fix is to remove it from
training — not to invent it at serve.** That is a complete and legitimate outcome; say it plainly
rather than manufacturing a value to turn a gate green. Parity is about **equality**, not presence:
a differently-computed value passes a presence check and fails parity in substance.

## 6. P2 — measure it, and expect this one to move served output

**`-09-39a` measured zero served delta only because the bound June artifacts do not select its two
features. Do not expect that here.** These eight are in the trained set, so routing them **will**
change predictions. That is the point, and it must be measured, not assumed:

- **Input completeness first** — the deterministic part. Report the 0.0% → *n*% change per feature
  per market. This needs no power argument and is the primary evidence the repair landed.
- **Served-output delta on the replay corpus** — centre, width, Brier — with **crossed date ×
  market clustering and power**. The corpus carries tens of thousands of replays, so this is the
  one place recently where adequate power is plausible; recent candidate fits ran at **0.054–0.146**
  and could conclude nothing. Report power either way.
- **Train/serve parity must stay at 0 unexpected.** `-09-39a` earned that; do not lose it, and do
  not edit the known-defects fixture to keep it.
- **Never weaken or bypass the serving floor** to move a number. §3 records it as the one shipped
  win, and centre displacement was traced to mass below it.

## 7. State this consequence explicitly in the report

§4: *"the cool bias, the market gap, the severity tail and the centre-displacement work were all
measured on a model missing 10 of 19 base inputs at all times."* **A successful repair invalidates
the baseline those results sit on.** Do not quietly re-cite them afterwards. Name which established
findings would need re-measurement — that list is a deliverable in its own right.

## 8. Method — binding

- **Crossed date × market clustering** on every comparison; report power before interpreting a
  point. **"Not powered" is a valid verdict** and beats a directional story.
- **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).
- Ledger rows are **not** market-days — deduplicate to `(market, target_date)`, then apply
  `promotion_countable`.
- `pytest -q` is **red on master** — 4 unowned failures named in `STATE_OF_PLAY.md`. Diff against
  those; classify anything else rather than lumping it in.

## 9. Boundaries

`DELEGATION_CONTRACT.md` §2 in full.

- **Fit no candidate, promote nothing, collect nothing, make no provider call.** This runs on data
  already on disk — that is precisely what distinguishes it from `-09-26a`.
- Do not write production `data/`, run the chain, settle a date, or restart anything.
- **Do not declare the confirmation window.** Check `reserved-confirmation-window.md` at run time;
  it wins over this handoff.
- Expect `roll_verdict.ps1` **exit 3** — `model_features.py`, `feature_store.py` and
  `model_sources.py` sit in the snapshot and observation-trigger closures. It does not block you:
  production merges in the 01:00–04:00 quiet window, and **pushing a branch never rolls anything.**

## 10. What would falsify this mission

- **The features are genuinely unknowable at serve.** Then the fix is to drop them from training,
  and saying so is the result.
- **They are already routed and §4 is stale.** `-09-39a` moved two of them; if more have since been
  fixed, the finding needs correcting and that is the deliverable.
- **The repair lands but served output does not improve**, or the comparison is not powered. Report
  it. A measured "the missing 28% was not worth anything" is a genuine and valuable answer, and it
  would redirect the whole model effort.
- **Repair changes served output materially in the wrong direction.** Stop before anything ships;
  that becomes a serving decision, not a parity fix.

## 11. Branch and report

- Branch: `codex/workstation-repair-the-blind-feature-block-2026-09-43a`
- Report: `docs/roadmap/agent-report-2026-08-08-workstation-repair-the-blind-feature-block.md`

Base on **`origin/codex/workstation-exclude-denver-station-days-and-fit-2026-09-42a`** (head
`1937d34f`, already reconciled with master) — it carries the parity repair you are extending, the
corpus work and the exclusion registry. If that stack has landed on master by the time you start,
base on `origin/master` instead and say which you used.

Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and a per-file roll verdict
from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — do not derive it by hand.
**Commit and push whenever you finish, at whatever hour.**
