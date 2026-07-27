# Workstation handoff — 2026-07-28c: scale the corpus until it decides (a standing queue)

The make-measurable queue is **accepted**, and it is the most consequential thing this program
has produced. Not because the answer is good — it is still `INCONCLUSIVE` — but because for the
first time the apparatus can actually produce an answer.

You delivered the three things that were missing: historical executions **are** retrievable
from the Data API with transaction hash, exchange timestamp, condition, token, side, price and
positive size, so **no collector change is needed**; the scorer now admits only genuine
executions, deduplicates identity-preserving, carries exchange time, does side-aware fills and
rejects `price_change`; and your own environment blocker is fixed. Validated here: 45/45 of
your new tests pass, and the changes are roll-free — none of the three files is loaded by
either capture loop, so this merges without touching the fleet.

Calling the result `INCONCLUSIVE_NOT_DECISION_GRADE` on six event-days, when a tidier agent
would have reported "market making loses money at 30 minutes", is the right call. Thirty of 32
cells negative sounds decisive until you note that **no interval excluded zero and every
settlement cell was positive**.

## What the pilot actually suggests

| Cap | Tier | Net 30m (before rewards) | Net settlement (before rewards) |
| ---: | ---: | ---: | ---: |
| $10 | none fits | structural block | — |
| $25 | 20 | −$10.166 | **+$11.222** |
| $50 | 50 | −$21.448 | **+$20.604** |

Two features matter. Both settlement columns are **positive and before rewards**, so any
liquidity-reward dollars are upside on top rather than something we need in order to break
even. And the sign flips between 30 minutes and settlement, which is the exact signature of a
**well-calibrated but unsharp** book: picked off on short-horizon information we do not have,
recovering by settlement because the fair value is unbiased. That is the hypothesis this whole
line has been circling, and it is now testable rather than rhetorical.

It is also six event-days — Atlanta, Dallas and Toronto on 2026-07-10 and 07-11. Nothing can
be concluded from that, and the US-positive / Toronto-negative split could easily be two days
of noise. **The measurement is sound and the sample is not.** Fix the sample.

**This handoff is a queue. Work in order, do not idle.**

## Mission 0 (prerequisite): green the ratchets your branch reddened

I have **not merged your branch yet**. The full suite on the merge result gives 5 failures
against a 2-failure baseline, so it adds three — all repo-hygiene ratchets, none a correctness
problem:

- `test_module_size_audit` ×2 — `mm_paper_scoring.py` grew past the warning threshold, so the
  count is now 20 and `docs/operations/module-ownership-map.md` still says 19. It needs the
  count updated and the module listed with ownership metadata.
- `test_schema_registry::test_source_tree_strict_audit_has_only_explicit_exclusions` — two new
  schemas, `mm_execution_evidence_v0.1` and `mm_execution_v2`, exist in source but are neither
  registered nor explicitly excluded.

I could have patched these myself, but both encode intent I would be guessing at: who owns the
module, and what those schema versions promise. They are yours, they are small, and master
should not go red on ratchets that exist precisely to stop this drift. Fix them, push, and I
will merge — the rest of the branch is validated here (45/45 of your new tests pass, and all
three touched files are roll-free, loaded by neither capture loop).

## Mission 1: establish retention, then backfill everything it allows

You correctly declined to promote an approximate vendor retention statement into a
completeness guarantee. So establish the real horizon empirically: probe backwards until the
Data API stops returning executions, and report the oldest date that actually yields data.

Then backfill the maximum the horizon allows, across **all 12 markets**, not three. The
admitted run took 7.16 seconds for six event-days, so compute is not the constraint — fetching
is. Stay polite to the endpoint: respect rate limits, cache raw responses under your output
root, and make the backfill resumable so a failure does not restart it.

Report coverage honestly: event-days fetched, executions retained, and any gaps.

## Mission 2: re-run at scale and split the sample

Re-run the same frozen scenarios on the full corpus and report:

1. **Confidence intervals that now mean something.** With six event-days everything crossed
   zero. State plainly whether the 30-minute loss and the settlement gain are distinguishable
   from zero at scale.
2. **Per-market and C-versus-F splits.** Toronto supplied the primary loss and the US subset
   was positive. Toronto is our only Celsius market *and* the streak/lock market, so a real
   Toronto-specific effect matters well beyond market making. Distinguish "Toronto is worse"
   from "Celsius is worse" from "two noisy days".
3. **Cap sensitivity** across $10/$25/$50 as before, plus whatever the data suggests.
4. **The horizon question**: if 30-minute marks are negative but settlement is positive, what
   does the P&L curve look like between them, and what does that imply about how long
   inventory must be held? A strategy that only pays at settlement has different capital and
   risk properties than one that pays in minutes — say which we would be running.

## Mission 3: close the rewards gap

Historical liquidity-reward allocations remain unknown, and rewards are competition-normalized
so they cannot be reconstructed from our own fills alone. Determine whether any historical
allocation data is obtainable from the raw-rewards API. If it is not, specify exactly what
forward capture would be required to measure it — that is a decision I will take, and I want
it costed rather than assumed.

Note the asymmetry in our favour: settlement P&L is already positive **before** rewards, so
rewards decide how good this is, not whether it works.

## Guardrails

- `data/` read-only with proven deny-write ACL; single declared output root.
- **No collector, trading, sizing, quoting, cap, serving, scheduler, promotion, release or
  pointer change.** Measurement and written design only. Cap changes and any live quoting
  remain operator decisions.
- Topic branches only; push without asking; never master, no PRs, no merges.
- Leakage: the settlement-positive result is exactly where a fill simulation could cheat by
  using post-quote information. Re-state the argument at scale, and treat a large improvement
  as a leakage suspect first.
- NOT-DONE / NOT-REHEARSED first-class. If the scaled corpus turns settlement negative, say so
  immediately — that closes the track on real evidence and is a success.

## Handback

`docs/roadmap/agent-report-<date>-workstation-mm-scaled.md`: retention horizon and backfill
coverage, the scaled re-run with intervals, the per-market/C-vs-F/holding-horizon splits, and
the rewards determination. Push all topic branches.

Context: streak 6/14, earliest lock ~2026-08-03. Your scorer branch merges here today once the
full suite confirms; it is roll-free so it does not need the quiet window.
