# Workstation handoff 2026-09-74a — what is the most this repair can possibly buy?

Written 2026-08-11 by the production agent. Read on `origin/master` and execute.
**No α, no realized outcome, no market comparison, no C endpoint.** Direct continuation of
`-09-73a` (merged `6a62b49c`).

## 1. Where we are, and why this mission exists

`-09-73a` produced a floor-safe input repair. Verified on production: **744 / 906** B decrease
events repaired, **366 / 368** on the main decision path, **zero** new above-settlement rows on all
28,254 replay-supported B feature snapshots, train/serve paired mismatch **2,057 → 1,510**, and it
*resolves* one of the 7 above-settlement rows we actually served. The rule is stated over payload
observables, needs no mechanism label and fits no parameter:

> At capture `t`, trust every row in the current WU payload. Recover a previously published missing
> row only when the current payload contains no row at or after that row's target-date-local minute.

The successor pre-registration is frozen at `SAFETY_CLEARED_ALPHA_UNALLOCATED_NOT_EXECUTABLE`. The
obvious next move is to allocate α and score it.

**I am not going to recommend that yet, and this mission is why.** The pre-registered primary
stratum is **366 differing decision-window events across 23 dates and 12 markets**, judged at
α = 0.0025 with `q = 3.1098893`, accepted only if a two-sided lower bound clears zero. We have been
here before: `-09-16a` was run and turned out never to have been powered, and a market-clustered
interval has a floor set by **12 markets, not by the number of dates**. α is our scarcest resource —
**7 of 20 spent, 13 left** — and this campaign's record is 31 retractions against one shipped win.

**So: before we spend, measure the ceiling.** There is a bound here that needs no outcome at all.

## 2. The bound, and why it is outcome-free

For a one-hot settled band `b`, the paired multiclass Brier improvement on a single row is

```
Δ_i  =  Σ_k (p_k − y_k)²  −  Σ_k (q_k − y_k)²
     =  (‖p‖² − ‖q‖²)  −  2 (p_b − q_b)
```

where `p` is the incumbent's band vector and `q` the candidate's. **The realized outcome enters only
through the single index `b`.** So the largest improvement any outcome could hand us is

```
ceiling_i  =  (‖p‖² − ‖q‖²)  +  2 · max_k (q_k − p_k)
```

which is computable from the two probability vectors alone. **Verify this algebra yourself before
using it** — derive it, do not trust my transcription — and state the result either way.

**The gate that follows is airtight and needs no interval theory.** The pre-registered accept rule
requires the point estimate to be `> 0`. Since `Δ_i ≤ ceiling_i` pointwise, the mean improvement can
never exceed the mean ceiling. **If the mean ceiling is `≤ 0`, the decision can never accept, and
spending α on it would be pure waste.**

Report the interval-level version too, but flag its limit honestly: pointwise domination transfers
cleanly to a *percentile* bootstrap bound, and **does not transfer cleanly to a studentised or
`mean − q·SE` bound**, because the candidate and oracle vectors have different resample standard
errors. Say which form the repository convention actually uses, and do not overclaim.

**Never read the realized band in the ceiling path.** Emit a receipt asserting it:
`realized_band_read: false`, `settlement_consulted_for_ceiling: false`. Taking the max over bands is
the whole point — the moment you look at `b` you have spent a look we did not allocate.

## 3. What to do

### 3a. First establish that replay reproduces the incumbent — and stop if it does not

**This is the first mission in this thread to run the model rather than recompute a feature, and
that is the main risk.** Before any candidate number is trusted, reproduce the **recorded** incumbent
band probabilities from the captured replay inputs on snapshots the candidate does *not* change, and
show they match what production recorded. `-09-40a` established that the incumbent reproduces its
recorded output; **re-establish it here or stop.**

Report the match rate and the exact tolerance. **If the incumbent does not reproduce, write that
down and stop — that is a bigger finding than anything else in this mission**, and it would
invalidate replay-based scoring generally.

Print the resolved `__file__` of every model, calibration and feature module you import, and confirm
it is the intended tree. A worktree that silently imports production modules has bitten us.

### 3b. Compute the displacement, before any ceiling

On the **366** differing decision-window events, and separately on the full differing B population:

- How far does the band vector actually move? Report `‖q − p‖₁`, `max_k |q_k − p_k|`, and the count
  of events where **no band probability moves by more than 0.005**.
- How often does the **argmax band** change at all?
- Report the same split by native unit and by market. **Do not pool Celsius with Fahrenheit.**

**A repair that fixes the input but does not move the distribution cannot move the score.** If most
of the 366 barely move, say so plainly in the verdict line — that alone would close this thread.

### 3c. Compute the ceiling

Emit `docs/roadmap/repair-ceiling-2026-09-74a.csv` with `-manifest.json` and `.sha256`, one row per
differing B snapshot, joining on the `-09-73a` keys so the artifacts reconcile.

| Column | Meaning |
| --- | --- |
| the `-09-73a` join keys | `stratum`, `market_id`, `target_date`, `snapshot_id`, `window` |
| `incumbent_probs`, `candidate_probs` | the two band vectors, and the band edges used |
| `l1_displacement`, `max_abs_displacement`, `argmax_changed` | §3b |
| `ceiling_delta_brier` | the oracle bound above |
| `floor_delta_brier` | the same expression with `min_k`, i.e. the worst outcome could do |
| `incumbent_reproduces_recorded` | the §3a control, per row |

Report the **mean ceiling** and the **mean floor** over the primary stratum, over each reported-only
stratum, and per market. Report the ceiling's dispersion across the 12 market clusters and across
the 23 date clusters — **that dispersion is the thing that decides whether 12 markets can ever
resolve this**, and it is why the ceiling is worth computing separately per cluster.

### 3d. State the verdict as a recommendation on α, and nothing more

Close with one of:

- **`CEILING_CANNOT_ACCEPT`** — mean ceiling `≤ 0`. The pre-registered decision is unwinnable.
  **Recommend the operator does NOT allocate.** The thread closes as a precise null and the input
  repair stands on input-integrity grounds alone.
- **`CEILING_MARGINAL`** — the ceiling is positive but small against the cluster dispersion.
  Say so with numbers and let the operator decide. **Do not dress a marginal ceiling up as
  promising.**
- **`CEILING_ADMITS_A_DECISION`** — the ceiling is comfortably positive and the cluster dispersion
  does not obviously swamp it. The α look becomes worth its price.

**You are not authorised to allocate, and a positive ceiling is not evidence of a gain** — it is the
best case, achieved only by an outcome that cooperates on every row. Do not compute the realized
improvement under any label.

## 4. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** and must not be reassigned.
- **No realized outcome, anywhere.** No Brier, CRPS, log loss, hit rate, calibration curve or
  reliability diagram against settlement; no market price; no comparison to the market. The settled
  roster may be read **only** to reproduce `-09-73a`'s floor-safety receipts, and the ceiling path
  must assert it consulted no outcome.
- **B only for every quantity in §3b–§3d.** C stays a passthrough; no C endpoint, probability,
  score or selection. Say so explicitly.
- **Never pool across `2026-07-31`** (anchor `b77cfbed`).
- **Point-in-time is absolute** — the candidate's inputs at snapshot `t` use only snapshots with
  `captured_at_utc <= t`, and recovered rows strictly earlier. Re-emit `-09-73a`'s receipts and
  assert them; **`item-224`'s win was leakage.**
- **Change nothing** — not the model, calibration, floor, producer, collection or scoring. This is a
  counterfactual measurement.
- **Never weaken the serving floor** (`1.6639 → 1.4980`).
- Native units per market throughout; toronto is Celsius.
- **A grep is not a trace.** Walk at least one large-displacement event and one zero-displacement
  event end to end.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, nothing under production
  `data/`, no promotion, activation, release or trading.

## 5. What would close this

- **A ceiling that cannot accept** → we learn, *for free*, that the best-supported input repair this
  campaign has ever produced still cannot win its own pre-registered decision. **Write it down
  plainly. It is a precise null, it saves an α spend, and it is worth as much to me as the other
  outcome.**
- **A ceiling that admits a decision** → the α look is priced and the operator can allocate against
  a known best case, instead of against hope.
- **The incumbent does not reproduce in replay** → stop everything and report. That would be the
  most important finding on this board.

## 6. Environment, branch and report

The repo venv on that host points at a removed Python 3.11 — use the bundled Codex 3.12 runtime.
**Install nothing.**

- Branch: `codex/workstation-what-is-the-most-this-can-buy-2026-09-74a`
- Report: `docs/roadmap/agent-report-2026-08-29-workstation-repair-ceiling.md`
- Extend `-09-73a`'s harness rather than rewriting it; commit the harness and versioned seed
  alongside the artifacts.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
