# Workstation handoff 2026-09-55a — write the missing producer, and trace the 21-field claim

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.

## 1. Where the chain stands

Six blockers, each found by removing the one before it. `-09-53a` got `base_retrain` past
`load_parent_contract` for the first time ever. `-09-54a` then found the sixth:

- **(a) No producer exists for `all_market_base_retrain_corpus_manifest_v0.1`.** Verified on
  production: the literal appears in exactly **two** places — `base_retrain.py:61` (consumer) and
  `schema_registry_data.py:1453` (registration). **Nothing writes it.**
- **(b) The PIT planner runs but staging is 0/60**, and its frozen **21-field** contract measured
  **1 of 21 non-null** on the free **Previous Runs** endpoint.

Both `--corpus-manifest` and `--pit-forecast-corpus-manifest` are `required=True` on `base_retrain`,
so **there is no research-mode shortcut around either.**

## 2. P0 — trace (b) BEFORE building anything for it

> **I have a hypothesis and it is explicitly NOT a finding. Trace it; do not inherit it.**

Production's own forecast archive holds **461 days of exactly 21 hourly fields** fetched from
**`historical-forecast-api.open-meteo.com`** — so those 21 fields are **demonstrably free-tier
available**. Meanwhile `previous-runs-api.open-meteo.com` is configured for
`temperature_2m_previous_day{1..7}` — lead-time temperature only, which is **consistent with the
1-of-21 measurement.**

**So the plan may be requesting all 21 fields from the wrong endpoint.** If so this is a *routing*
defect, not a free-tier wall, and blocker (b) largely collapses.

**Determine which it is, from the planner's code and the endpoint contracts:**

1. Which endpoint does the PIT plan request each of the 21 fields from?
2. Is the split principled — bulk fields from `historical_forecast`, lead-specific ones from
   `previous_runs` — or does it ask one endpoint for everything?
3. **If it is a routing defect**, say so plainly and state the minimal correction.
4. **If it is a genuine wall** — the PIT contract needs fields no free endpoint serves — then that is
   an operator decision about changing a frozen contract, and **changing it changes what any future
   candidate is trained on.** Report it as a decision, do not make it, and do not narrow the field
   set to make staging pass.

**Do not call either endpoint.** Production owns network fetches. Read the code and the recorded
manifests; if a step would fetch, stop and report.

## 3. P1 — write the missing producer for (a)

Only after (b) is characterised, because what the base corpus manifest must contain may depend on it.

- Write the producer for `all_market_base_retrain_corpus_manifest_v0.1`, matching the schema
  `base_retrain.py` already consumes and the registration already declares. **The consumer is the
  specification** — do not change it to fit what you produce.
- `-09-53a` proved the raw material exists: first-party lineage assembled and bound **12,600/12,600**
  cells at 315.83 MiB peak RSS. **Reuse that path rather than inventing a second corpus notion.**
- **Do not hand-author a manifest.** A hand-made lineage record produces a candidate that *looks*
  auditable and is not. If the only way past is to write one by hand, that is the finding.
- Match `-09-53a`'s standard on contracts: generalize, never relax; unknown inputs fail closed.

## 4. What would falsify this mission

- **(b) is a routing defect** — the best outcome; say so and the wall mostly disappears.
- **(b) is a real free-tier wall** — then it is a contract decision for the operator, and P1 may be
  premature. **Say so and stop rather than building against a contract that is about to change.**
- **The producer cannot be written without inventing corpus semantics** the consumer does not pin
  down. Then the schema is under-specified and that is the finding.
- **A seventh blocker appears behind these.** Expected by now. Name it precisely and stop.

## 5. Context you should not re-derive

- **`COMPLETE_DAY_MIN_ROWS = 18` is not a knob.** **Never pool across `2026-07-31`.**
- **Free-tier Open-Meteo only, no paid API — closed, and not reopenable by a mission.** That is
  precisely why (b) matters: if the contract needs paid data, the contract changes, not the policy.
- **The capture streak has a shelf life**: `POOLED_PIT_MAX_LATEST_TARGET_AGE_DAYS = 7` bounds how old
  the selection universe's latest target may be. Not your problem to fix, but do not design anything
  that assumes the banked window is permanent.
- Nothing is reserved; `reserved-confirmation-window.md` wins over every other document.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, with the same narrow exception as `-09-53a`: **scratch roots
only, fitting only if a step genuinely requires it and you say so.**

**The production release store must stay empty and its pointer absent — verify and state it.**
Nothing under production `data/`. No promotion, activation, order, live trading, chain run,
settlement, or loop restart. **Call no provider endpoint.** Never weaken the serving floor.

## 7. Branch and report

- Branch: `codex/workstation-write-the-corpus-producer-2026-09-55a`
- Report: `docs/roadmap/agent-report-2026-08-18-workstation-corpus-producer.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.**
**Commit and push whenever you finish, at whatever hour.**
