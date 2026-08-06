# Workstation handoff `-09-10a` — can the MM go-live gate actually decide?

Written 2026-08-04 by the operations master agent on the production host. Read this on
`origin/master` and execute it.

## Why this, and why it must run before the clock starts

Market making is the operator's stated end goal, and **MM-blocking work outranks everything else.**

The release #1 build runs imminently. That build is the single event that unblocks maker quoting:
no release → `captured_input_replay_parity` BLOCK → `f_family_promotion_refresh` is
`verdict: not_run`, `market_count: 0` → every market carries `promotion_state: BLOCK` → the
known-edge map denies → **the maker never gets quote permission.** Live proof from 2026-07-31: all
132 intents carried `promotion_state: BLOCK`; 121 were `NO_QUOTE_KNOWN_EDGE_PERMISSION` with
`known_edge_reason: promotion_block`.

So within days, quotes start flowing and the **14-day live-forward acceptance clock begins for real.**

`docs/research/MARKET_MAKING_PLAN.md` states the gate:

> **Acceptance to MM-2:** simulated P&L (markout + rewards + rebates) positive over ≥ 14 days under
> the pessimistic fill rule, with model gates honored; plus the jurisdiction gate cleared.

**Those 14 days are irreplaceable.** This project has now spent two months of research on five dates
because nobody checked an inherited convention, and has separately had a promotion gate reject a
better candidate at 99.885–99.9905% false-rejection. **The failure mode is always the same: run the
clock first, discover the endpoint could not decide afterwards.** This mission checks first.

## The specific problem: the acceptance criterion is horizon-ambiguous, and the sign flips

The 6-event-day pilot (Atlanta/Dallas/Toronto, 2026-07-10 and 07-11):

| Cap | Tier | Net 30m | Net settlement |
| --- | --- | ---: | ---: |
| $25 | 20 | **-$10.166** | **+$11.222** |
| $50 | 50 | **-$21.448** | **+$20.604** |

**Both settlement columns are positive and both are BEFORE rewards. Both 30-minute columns are
negative.** The acceptance criterion says "P&L (markout + rewards + rebates) positive" without
naming a markout horizon, and the plan elsewhere scores markout at **+5m, +30m, and settlement**.

**Which horizon is chosen determines pass or fail.** That is not a detail to settle after the fact.

Note also that the pilot was correctly reported `INCONCLUSIVE_NOT_DECISION_GRADE`: 30 of 32 cells
were negative at 30 minutes and **no interval excluded zero.**

## Questions

### Q1 — Which horizon should the acceptance decision use, and why?

Resolve the ambiguity with reasoning grounded in the actual economics, not convention:

- These are **binary settlement** markets. Positions resolve at 0 or 1.
- **Liquidity rewards are paid daily at 00:00 UTC on resting size** via the published Q-score
  formula. That component does **not** depend on markout at any horizon.
- **Maker rebates** accrue on volume, not on markout.
- The 30m→settlement sign flip is the signature of a well-calibrated but unsharp book: picked off on
  short-horizon information, recovering by settlement because fair value is unbiased.

Decompose the pilot P&L into **markout-dependent** and **markout-independent** components and report
what fraction of expected economics is actually horizon-sensitive. State plainly whether a
markout@30m criterion would **reject a strategy that is profitable at settlement** — and if so, say
so as the headline.

Do not simply assert settlement is correct because it is favourable. If short-horizon markout is the
right risk control — e.g. because adverse selection compounds with inventory or scale — say that
instead and explain what it protects against.

### Q2 — Is 14 days decision-grade? (the number that matters most)

Using the pilot's observed variance, estimate how many **event-days** the acceptance decision needs
to be decision-grade under **crossed date × market** clustering, for the horizon Q1 recommends.

Report: MDE at 14 calendar days for the realistic quoting fleet, and the event-day count required for
80% power. **If 14 days is not enough, say the number that is.** If it is enough, say so — that is an
equally valuable answer and it lets the clock start with confidence.

Be explicit that 14 *calendar* days is not 14 *event-days*, and that markets are not independent.

### Q3 — What is instrumented today, and what silently is not?

For every acceptance input, state whether it is computable **today** from captured evidence:

- pessimistic trade-through-only fill simulation (needs book tape),
- **reward Q-share** — needs sampled books *including competitor size*,
- **rebate share** — needs our simulated maker volume against observed taker volume,
- markout at each horizon,
- fill toxicity (fills within N minutes of a decisive WU print / METAR special).

`maker_paper_score` has been **dark since 2026-08-02** (a scoring race against the 07:05 maker roll;
the fix is first in the merge queue). Say what that outage costs: are those days recoverable by
rescoring retained evidence, or are they permanently unscoreable? **A day that cannot be scored
cannot count toward 14**, so this directly sets the true clock start.

### Q4 — Does promotion PASS invalidate pilot-based estimates?

The pilot ran while promotion was BLOCK, so the quoting and fill population was heavily restricted.
After release #1, permission opens and the population changes — likely more markets, more bands, more
fills, and possibly different toxicity.

State how much the Q2 power estimate depends on the pilot population being representative, and what
should be re-estimated once real quotes flow. If the honest answer is "the power estimate must be
recomputed after the first few live-forward days," say that and specify the trigger.

## Deliverable

1. Answers to Q1–Q4 with N and crossed intervals throughout.
2. **A revised, explicit, powered acceptance specification** — named horizon, named statistic, named
   N, named decision rule, written so it can be evaluated mechanically rather than argued about — or
   a clear statement that the existing gate is sound as written.
3. **A day-1 checklist: what must be true for a live-forward day to COUNT.** This is the operational
   payload. If a day silently fails to count, we discover it on day 14.
4. A `## What would falsify this` section.

## Constraints

**No live orders, no keys, no wallet, no provider calls, no network trading of any kind.** This is a
measurement and specification mission over evidence already captured. `data/mm_runs` is retained and
mirrored deliberately — use it.

**Reserved dates `2026-08-06` → `2026-11-03` must not be read, replayed, scored, or inspected as
target dates.** `docs/operations/reserved-confirmation-window.md` is the single source of truth and
outranks this document.

**Do not weaken the trusted observed-high floor** and **do not relax the promotion gate.** There is a
known open question about whether `harvest_only` rows should be allowed through
`promotion_state: BLOCK` in paper mode. **That is an operator decision with a code change, and it is
explicitly NOT delegated here.** You may analyse the consequences; do not implement it.

**Clustering.** Crossed date × market on every interval. If an interval crosses zero, say so in the
same sentence as the point estimate. Do not quote proxy sensitivity as candidate power.

**Do not touch the release or PIT path.** The release #1 build runs on the production host around
this time.

**Network:** `git fetch` and `git push` only.

Push `codex/workstation-can-the-mm-gate-decide-2026-09-10a`. **No PR, no merge.** Report to
`docs/roadmap/agent-report-2026-08-05-workstation-can-the-mm-gate-decide.md`.

## How to disagree

If the gate is sound as written, say so plainly — confirming a gate is as useful as fixing one. If
the pilot evidence cannot support a power estimate at all, say that and stop rather than producing a
number that cannot bear weight.
