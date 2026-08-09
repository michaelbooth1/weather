# Workstation handoff 2026-09-48a — can the maker quote at all?

Written 2026-08-08 by the production agent. Read on `origin/master` and execute.

## 1. Why this is the top item

`-09-46a` retired model-skewed quoting: 114 pre-declared cells, **zero** with positive edge. Its P1
kept exactly one route open — **market-centred harvesting, which needs no model edge** — and
`-09-47a` then showed `f` is **unidentified** from anything we hold, so the harvesting question
cannot be settled from history at all.

That leaves an obvious question nobody has asked: **while all that was being measured, what has the
maker actually been doing?**

**It has been emitting `NO_QUOTE` on every single row.** Measured on the production host before you
were dispatched, across three separate run-days including in-window runs:

| Run | Rows | `action` | Dominant `reason_code` |
| --- | ---: | --- | --- |
| 2026-08-06 17:49 | 34,452 | **100% `NO_QUOTE`** | `KNOWN_EDGE_PERMISSION` 24,057 (70%) |
| 2026-08-07 16:57 | 132 | **100% `NO_QUOTE`** | `KNOWN_EDGE_PERMISSION` 110 (83%) |
| 2026-08-08 21:00 | 6,204 | **100% `NO_QUOTE`** | `KNOWN_EDGE_PERMISSION` 5,643 (91%) |

`STALE_INPUT` is the **second** reason, not the first. That matters: canon has been calling input
freshness the MM blocker, and on these runs it is outranked roughly 3:1 by a permission gate.

## 2. What I verified, and what I did NOT conclude

**Verified in production source — you may build on these:**

- `mm_policy.apply_known_edge_permission(row, record, map_loaded)` resolves to:
  - `record is None` **and** `map_loaded=False` → `permission = "harvest_only"`, reason
    `known_edge_map_missing`
  - `record is None` **and** `map_loaded=True` → `permission = "no_quote"`, reason
    `missing_known_edge_record`
  - record present → `permission` from the record; `known_edge_allowed` only if `"edge_allowed"`
- The map is **present and loaded**: today's `preflight.json` reports
  `known_edge_map.exists = true`, `record_count = 93`, `schema_version mm_known_edge_map_v0.2`,
  `summary.active_model_gap_cell_count = 93`, path `data/backtest/mm_known_edge_map.json`.
- Quote fair value is model-derived:
  `fair = first_present(row, "fair_probability", "model_probability", "candidate_p")`,
  `edge = fair - mid`, with an `overlay = (1 - market_weight) * fair + market_weight * mid`.
- `mm_policy` carries **two spread regimes**: `harvest_half_spread` / `max_harvest_spread` (0.08)
  and `max_edge_spread` (0.12).

**The reading I did NOT reach, and you must test rather than inherit:** the above *appears* to mean a
**loaded-but-incomplete map is strictly more restrictive than no map at all** — absent map gives
`harvest_only`, present map with a missing record gives `no_quote`. **That is a hypothesis from
reading three branches of one function. Trace it through an actual run before asserting it.** This
project has twice paid for treating a consistent story as a proven one.

It may well be deliberate: a vetting gate so the bot cannot quote markets nobody has cleared. **If it
is deliberate, say so and say why it is right** — that is an equally valuable answer.

## 3. P0 — why is every row `NO_QUOTE`?

Answer in this order and **stop at the first step that fully explains it**:

1. **Attribute the `NO_QUOTE` population exactly**, per market-day and per reason, over the retained
   `quote_intents_long.csv` corpus. Crossed date × market clustering. Report the reason mix and how
   stable it is across days — the three runs above differ (70/83/91%) and that spread may itself be
   informative.
2. **For the `KNOWN_EDGE_PERMISSION` rows, which branch fired?** Distinguish *no matching record*
   from *record present but permission ≠ `edge_allowed`*. These have completely different fixes.
   Read `known_edge_permission`, `known_edge_reason` and `known_edge_record_key` on the rows rather
   than inferring from the reason code.
3. **What do the 93 records cover, and what is quoted?** Report the join: how many distinct
   market/cell keys are quoted, how many have a record, and what the coverage rate is. If the map is
   derived from active model-gap cells, note the tension explicitly — **`-09-46a` measured zero
   positive edge in all 114 cells, so a permission map keyed on model edge is permissioning against
   a quantity we have shown to be absent.**
4. **Is `harvest_only` reachable in the current configuration, and does anything downstream honour
   it?** Trace whether a `harvest_only` permission actually produces a quote, or whether a later gate
   (promotion, preflight, sizing, `policy_no_edge`) refuses it anyway. **A permission that nothing
   acts on is not a route.** This is the step that decides whether market-centred harvesting is
   currently implementable at all.

## 4. P1 — what would it take to quote market-centred, and what would it prove?

**Design only. Change nothing.** If harvesting is reachable, describe the smallest honest change that
would let the maker quote around the market mid with **no model input**, and state precisely what
evidence one day of that produces — and what it does *not*. Note the standing bounds: reward
qualification needs **$19.60** against a **$10** `max_band_notional` cap, so evaluate the
**$0-reward** column; and `f` is unidentified, so **no unique break-even may be quoted** (`-09-47a`).

## 5. What would falsify this mission

- **The gate is correct and deliberate.** Then the MM blocker is a policy decision for the operator,
  not a defect — say so plainly, and say what decision is being asked for.
- **`KNOWN_EDGE_PERMISSION` is not actually the binding constraint** — e.g. every such row would have
  been refused by promotion or preflight regardless. Then the reason ordering is cosmetic and the
  real blocker is whatever survives. **This is a live possibility; three refusals can coexist on one
  row and the reported one may just be first in precedence order.** Check precedence explicitly.
- **Harvest mode is unreachable by construction.** Then the only viable strategy cannot be run at
  all, which is the most decision-relevant answer available and must not be softened.

## 6. Context you should not re-derive

- The MM countable-day clock is **stopped**: 7 of 55 days, last counted 2026-07-12
  (`ESTABLISHED_FINDINGS.md` §8b). Relate your finding to it — **if the maker never quotes, ask what
  a "countable day" has been certifying.**
- `-09-47a` (§1b.3, §8c): `A` and `f` are **unidentified, not underpowered**. Do not attempt to
  estimate either.
- Live-trade permission is **0/12 and the gate passes anyway** — it is not the blocker.

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Fit nothing, promote nothing, place no order, enable no live
trading, call no exchange or provider endpoint.** Do not write production `data/`, run the chain,
settle a date, restart a loop, or edit the known-edge map. Crossed date × market clustering; power
before interpretation; **never pool across `2026-07-31`**.

## 8. Branch and report

- Branch: `codex/workstation-can-the-maker-quote-at-all-2026-09-48a`
- Report: `docs/roadmap/agent-report-2026-08-11-workstation-maker-quote-gate.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.**
**Commit and push whenever you finish, at whatever hour.**
