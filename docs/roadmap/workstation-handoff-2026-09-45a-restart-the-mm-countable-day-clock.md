# Workstation handoff 2026-09-45a — restart the MM countable-day clock

Written 2026-08-08 by the production agent. Read on `origin/master` and execute.
**This is now the top item on the project's end goal.** The market-making bot is objective #3 and
the gate that decides it has been unable to accumulate evidence for 27 days.

## 1. Goal

**Root-cause why maker days stopped counting toward the live-forward gate, and author the fix.**
Deliver a branch plus a measured claim about what the countable-day yield would become.

## 2. The measurement you are starting from

`ESTABLISHED_FINDINGS.md` §8b, produced by
`python -m weather.reporting.market.mm_countability_postmortem` (landed roll-free, runs daily
as `WeatherMmCountabilityReport` into `data/alerts/MM_COUNTABILITY.md`):

| Measure | Value |
| --- | ---: |
| Maker days on disk | **55** (`2026-06-15` → `2026-08-08`) |
| Days that counted | **7** |
| Yield | **12.7%** |
| **Last counted day** | **`2026-07-12`** |

| Gate / root cause | Days | Occurrences | First → last |
| --- | ---: | ---: | --- |
| `model_freshness` / `stale_model_row` | **52 of 55** | 758 | 06-15 → 08-07 |
| `clob_freshness` / `stale_clob_book_tape` | **52** | 643 | 06-15 → 08-07 |
| `clob_book_useful_write` / `stale_or_missing_clob_book_rows` | 36 | 39 | 06-20 → 08-07 |
| `no_remediation_file_written` | 27 | 39 | 06-15 → 08-08 |
| `snapshot_model_useful_write` | 26 | 28 | 06-20 → 08-07 |

**The yield, not elapsed calendar time, sets the date the MM gate can rule.** At 12.7% the 22–43
countable-day bar is never reached.

## 3. THE BOUNDARY THAT DECIDES THIS MISSION

**The freshness gates are CORRECT. Do not weaken, widen, or bypass one to raise the yield.**

A countable day built on stale inputs is worse than no countable day: it feeds the MM decision
false evidence, and the decision it gates is whether to trade real money. The project has already
recorded that this specific gate family is right and that I pattern-matched against it and was
wrong (`ESTABLISHED_FINDINGS` §8b, and the continuity-gate correction in the MM track).

Raising yield by relaxing a threshold is the shortcut the operator explicitly forbade: **parity is
the bar and defects are preferred over gains.** If your honest conclusion is "the inputs genuinely
cannot be fresh enough at maker runtime without more capture cadence," **say that** — it is a real
and valuable answer and it redirects the track.

## 4. P0 — root-cause the two leading blockers

Both are *input freshness at maker runtime*. On the 08-07 sample the model row was ~19 minutes old
when the maker ran (latest capture 16:38:16Z, run 16:57:12Z).

Answer, with evidence, for **`model_freshness`/`stale_model_row`** and
**`clob_freshness`/`stale_clob_book_tape`** separately:

1. **What is the configured threshold**, and where is it set?
2. **What is the actual age distribution** of the input at maker runtime across the 55 days? Not one
   sample — the distribution, by market and by hour.
3. **Which side is at fault** — is the maker scheduled at a bad moment relative to capture cadence,
   or is capture genuinely not producing rows that recently?
4. **Is this a regression?** Six of the seven counted days are `06-17` → `06-27` and the seventh is
   `07-12`. Something worked and stopped. Ten MM-module commits landed in `06-24`..`06-30` —
   `5735b573 0b7979c9 13342614 71c24297 1d9d9491 d9175473 5b84b0d3 2f4a9ea1 f8cd4086 d50ca6fe
   00c92222`. **Do not name a culprit from filenames** — bisect or trace it.

`clob_freshness` is known to block on **max gap across the whole day**, so a single ~3-minute gap
poisons an entire market-day. Confirm whether that is what is firing, because if so the fix is about
gap elimination, not scheduling.

## 5. P1 — what would the yield actually become?

**A fix is only worth merging if you can say what it buys.** Re-run the post-mortem logic against
the counterfactual: had your fix been in place, how many of the 55 days would have counted?

- You may reuse `weather.reporting.market.mm_countability_postmortem` directly — it is small and
  reads only `preflight_remediation.json`.
- **State it as a range with its assumptions**, not a point. If the historical evidence cannot
  support the counterfactual, say so rather than inventing one.
- **A fix that raises yield from 12.7% to 20% still never reaches the bar.** Say plainly whether
  your fix makes the gate reachable at all.

## 6. P2 — the observability hole, only if P0 and P1 are done

**27 days have runs that wrote no `preflight_remediation.json` at all.** The post-mortem buckets
these into `no_remediation_file_written` rather than dropping them, so the yield is not overstated —
but those runs cannot explain themselves. Find out why the file is missing. **Drop this if it
threatens P0.**

## 7. Method — binding

- **Never weaken a gate, threshold, admission bar, or known-defect fixture.** See §3.
- **Do not run the maker against the live exchange, place an order, or enable live trading.**
- Do not write production `data/`, run the chain, settle a date, or restart anything.
- Ledger rows are **not** market-days — deduplicate to `(market, target_date)`, then apply
  `promotion_countable`.
- **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).
- Report power on any comparative claim; **"not powered" is a valid verdict.**
- `pytest -q` on master is **GREEN** (3,349 passed, 0 failed). **If something is red, it is yours.**

## 8. What would falsify this mission

- **The maker's schedule is fine and capture genuinely cannot deliver fresher inputs.** Then the fix
  is a capture-cadence decision on a 16 GB host with a live streak to protect — **stop and report**,
  do not implement it.
- **The blockers are downstream of the dead chain.** The chain has been dead at step 4 since 08-04
  and the fix merges 01:20 on 08-09. Check whether that explains the last four days *only* — it
  cannot explain 06-27 → 08-04, so it cannot be the whole story.
- **No single regression exists** and the yield was always this bad. Then 06-17 → 06-27 needs
  another explanation, and the track needs a different plan.

## 9. Branch and report

- Branch: `codex/workstation-restart-the-mm-countable-day-clock-2026-09-45a`
- Report: `docs/roadmap/agent-report-2026-08-09-workstation-mm-countable-day-clock.md`

Base on **`origin/master`**, which carries the post-mortem tool and §8b. As of the 01:20 merge on
08-09 it also carries `-09-43a`, the chain fix, and the schema literals. Per
`DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and a per-file roll verdict
from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — **do not derive it by hand.**
**Commit and push whenever you finish, at whatever hour.**
