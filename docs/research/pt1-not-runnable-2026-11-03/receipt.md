# PT-1 NOT RUNNABLE receipt (master ruling R21)

- **Create-only receipt.** Written by WS lane L59 on the 11-04 docs head (`claude/mg1-b-rulings-docs-20261103`).
  It is never edited after it lands; any correction is a new dated file. Its raw sha256 fills PT-1's receipt
  slot.
- **Ruling:** master ruling R21 (2026-11-01), ADOPT-WITH-CONDITIONS. This is master's ruling, not an owner
  decision. Source: `C:\t\rulings-20261101\rulings.md` sha256
  `2499b5afec7a258378da9235689b594ae72a7c9f627d79c3b8c64ad489e2b44d`, :174-202 and :222. Master recorded
  on 11-03 that its landing slipped from the 11-03 docs head.
- **What is ruled:** PT-1 (the cool-season paper test) with candidate C-PT is **NOT RUNNABLE** under method
  rules 4 and 6, which the owner adopted on 2026-10-30 (DECISION_LOG.md:291). It was found from records at
  the cheapest tier (method rule 2).
- **PT-1 draft at origin/master:** `docs/operations/COOL_SEASON_PAPER_TEST_PREREG.md`, raw sha256
  `7de9be949653a1513e5690f1c2a25fc9146946bc77f24e5ac3da252c46a16986`, read at `origin/master`
  `621d67f0fdbd05556725239cd09f07468c132241`. The status note added on this head changes that file. This
  sha is the draft as ruled.
- **Data read: none; nothing fitted.** No replay, no forward read and nothing dated after 2026-09-29.

## Rule 6: training coverage does not reach the last forward date

- **The rule:** "training coverage that reaches the last forward date", with at least 20 dates before any
  PASS (MODEL_IMPROVEMENT_METHOD.md:163-164; iterate-faster `plan.md`:24).
- **C-PT's pre-13 L6 arm is covered to 12-16.**
  - L6_G FROZEN prereg (`docs/research/gefs-members-l11-2026-10-26/l6g_forward_prereg_FROZEN_2026-10-30.md`)
    :102-103 states the L6 state's training coverage as 08-01..12-16.
  - The served L6 state refuses training history past 2025-12-31 (`src/weather/calibration/l6_own_state.py`:53-55).
- **PT-1's window:** PT_D0 is the first local date after the later of MG1_LAST and MG-2's 45th date
  (draft :174-176).
  - The draft's "provisionally 12-12" came from a 45th date of 12-11 (draft :167). MG-2's 45th date is now
    12-12 (STATE_OF_PLAY.md:58), so PT_D0 is at the earliest **12-13**.
  - Counted from 12-13 with none skipped, the draft's 45 dates end about 01-26 (the draft's provisional 45th is 01-25, draft :177-178).
  - The look's hard floor is 30 countable dates (draft :185-187).
- **Arithmetic.** R21 asks for both readings of coverage to be stated:
  - **12-16 (L6_G record):** covered dates 12-13..12-16 = **at most 4**.
  - **12-31 (widest serving reading):** covered dates 12-13..12-31 = **at most 19**.
  - Both are below rule 6's 20 and the draft's 30.
  - Under either reading, coverage ends weeks before PT-1's last forward date.

## Rule 4: w first

- **The rule:** a candidate earns a market test only if its walk-forward w beats the placebo and the
  floor-only control (MODEL_IMPROVEMENT_METHOD.md:160-161).
- **MG-1 cannot fill the uncovered (January) dates** (`docs/research/market-blend-l11-2026-10-25/README.md`):
  - :21: on dev, MG-1's blend R is 1.0017 with w 0.008, and 25 of 43 dates have w = 0.
  - :24: the floor-only control is R 1.0010.
  - :14-15: the placebo controls.
  - :34: the log-fitted w is about 0.
- C-PT's own dev standing is a point estimate only (R21 unresolved note, rulings.md:232). It was not needed
  for the verdict.

## Consequences (R21)

- PT-1 claims **no date**. This receipt satisfies the conditions "after PT-1's look" and "PT-1's look
  receipt" wherever another test orders itself after PT-1: F8-MH Clarification 2 and the T+1 dated clause.
- The PT-1 reserved-window row keeps its scope. Its read never opens.
- The memo's 10-point build checklist is not adopted. There is no engine, no `--single-look`, no exporter
  edit and no binding.
- **Reopen** only for a pre-13 candidate whose coverage reaches its last forward date and whose dev w beats
  the placebo and floor-only controls, under a new prereg (rulings.md:193, :198). The register row is
  EXHAUSTION_REGISTER X106.
- **Safety:** docs only and roll-free. No host process, no B-bound file, no exporter change, no code combo.
  The embargo is unchanged.
