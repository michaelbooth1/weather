# Workstation handoff 2026-09-71a — does the cutoff narrow, and why?

Written 2026-08-11 by the production agent. Read on `origin/master` and execute.
**No α, no candidate, no fitting, no C endpoint.** Direct continuation of `-09-70a` (merged
`e86bd5c8`), which this handoff assumes you have read.

## 1. The gap, and it is mine

`-09-70a` is a clean finite-population census and I verified it on production: CSV SHA-256 matched
byte-for-byte, `ROLL-FREE` at exit 0, docs audit `PASS`, and every population figure reproduced.
`M6_unexplained` at 1.10% is a good result and the frozen precedence was the right call.

**But the B headline rests on a column I specified wrong.** I asked for `cutoff_hour_changed` as a
**boolean**. The census therefore proves 658 B events had a cutoff that *changed* — and cannot show
that it *narrowed*. Only the Atlanta `2026-06-13` trace shows a direction.

This is load-bearing, not bookkeeping:

- The window is `rows where minute <= cutoff*60`. **Only a NARROWING cutoff can lower the maximum.**
  A widening one cannot — the San Francisco control proves that, which is why `-09-70a` correctly
  kept it in `M1` despite its cutoff moving `13 -> 14`.
- **If most of the 658 widened, `M5` is misnamed** and those events have no established mechanism.
  B's real residual would go from **2.21% to roughly 75%**, and the honest headline becomes *we do
  not understand a live serving feature on the model's main decision path.*

**Either answer is worth having. Do not treat narrowing as the expected result.**

## 2. What to do

### 2a. Direction census — the correcting column

Re-run the committed `tools/research/measure_high_so_far_population_09_70a.py` with the direction
recorded. The values are already computed at line 632 and already emitted into the manifest traces
at lines 777-778; they simply never reached the CSV.

Emit `docs/roadmap/high-so-far-cutoff-direction-2026-09-71a.csv` with `-manifest.json` and
`.sha256`, one row per event, **adding**:

| Column | Meaning |
| --- | --- |
| `previous_cutoff_hour`, `cutoff_hour` | the two values |
| `cutoff_delta` | signed, `cutoff_hour - previous_cutoff_hour` |
| `capture_minute`, `previous_capture_minute` | the underlying minute, if the producer carries it |
| `rows_lost_within_window` | rows present before and excluded after, if derivable |

Report, **separately for B and C**: the signed distribution of `cutoff_delta`, how many of the 658
`M5` events narrowed vs widened, and — for any that widened — what *else* explains the decrease,
since the cutoff cannot. **Reconcile against `-09-70a`'s 658/2 split and say so if it differs.**

### 2b. Which producer writes `cutoff_hour`, and what is it actually?

`-09-70a` read `cutoff_hour` from `features_long.csv` (its line 268). **Establish which producer
writes that column** before tracing anything — do not assume the path below is the right one.

The lead, and the reason this question exists:

```
src/weather/backtesting/replay_backtest.py:460   "cutoff_hour": minute // 60 if minute is not None else None,
src/weather/backtesting/tape_scoring.py:216      "cutoff_hour": minute // 60 if minute is not None else None,
```

The sibling key on the same row is `"capture_minute": minute`. **If `cutoff_hour` is the capture
hour, it cannot go backward while the wall clock advances** — and Atlanta `2026-06-13` went
`10 -> 9` between snapshots at **11:21 and 11:32 local**, where the capture hour is 11 in both.
So at least one of these is true, and I do not know which:

1. `minute` is not the capture minute despite the key name (e.g. it tracks the latest observation),
2. `features_long.csv`'s `cutoff_hour` comes from a different producer entirely,
3. the local-time basis differs between the snapshot ID and `captured_at_local`.

**Answer it with file:line evidence and one end-to-end trace of the Atlanta pair.** A grep is not a
trace.

### 2c. The hypothesis worth testing explicitly

If `cutoff_hour` derives from the **latest observation's** minute rather than the clock, then a
series that is not append-only drags the window backward with it — and `M5`, `M3` and `M1` are not
three mechanisms but **three symptoms of one**: the observation series regresses.

**Test it, do not assume it.** The discriminating evidence is already in the census: **658 of B's
660 cutoff changes also dropped rows.** If one causes the other, say which is upstream and show it.
If they are independent, that is equally publishable.

### 2d. Name the `M6` fingerprint

**19 of the 20 B residuals share one signature** — a single current WU row, changed `latest`, same
source and cutoff, no row loss. That is a mechanism, not scatter. Characterise it, give it a name,
and say whether it is a sibling of `M2` (history collapsed toward empty) or something else. The 4 C
residuals resolve as `station` with empty WU history and are separate.

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** and must not be reassigned.
- **You may read C**, same grounds as `-09-70a`: no candidate, no fitted parameter, no endpoint
  comparison, no accept rule. **Say so explicitly in the report.**
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). B and C separate throughout.
- **Change nothing** — not `high_so_far`, not `cutoff_hour`, not the floor, not collection, not
  scoring. If you find the producer is wrong, **that is the finding**; the fix is production work
  and needs a replay measurement first.
- **Never weaken the serving floor.** It is the one shipped win (`1.6639 -> 1.4980`).
- Keep magnitudes in each market's **native unit**. Toronto is Celsius; do not pool it with the
  Fahrenheit markets, as `-09-70a` correctly did not.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, nothing written under
  production `data/`, no promotion, activation, release or trading.

## 4. What would close this

- **The 658 narrowed, and the producer explains why** → the B mechanism is established, and the
  window-regression finding is real and citable. This becomes the strongest model-input lead the
  campaign holds.
- **A material share widened** → `M5` is misnamed, B's residual is far larger than 1.10%, and
  `-09-70a`'s headline needs correcting in `ESTABLISHED_FINDINGS.md`. **Say so plainly and I will
  correct it** — a retraction found by our own follow-up is the cheap kind.

**Neither outcome licenses a serving change.** `-09-44a` was a precise null on input repair; being
the best-supported lead is not evidence of a gain.

## 5. Environment, branch and report

The repo venv on that host points at a removed Python 3.11 — use the bundled Codex 3.12 runtime.
**Install nothing.**

- Branch: `codex/workstation-does-the-cutoff-narrow-2026-09-71a`
- Report: `docs/roadmap/agent-report-2026-08-26-workstation-cutoff-direction.md`
- Commit the modified script and seed alongside the artifact.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
