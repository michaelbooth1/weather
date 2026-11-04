# MG-1 pre-registration — Clarification 3 (2026-11-04): owner answers to A1, A5 and A12

Status: **owner decision** (DECISION_LOG 2026-11-04). It answers the three readings that
[Clarification 2](morning-guidance-read-mg1-clarification-2-2026-11-03.md) left as **owner questions, open**,
and supersedes that text for A1, A5 and A12 only. Clarification 2's file is not edited, and every other ruling in it
stands. This is a separate dated amendment file, as
[the MG-1 pre-registration](morning-guidance-read-mg1-preregistration-2026-10-04.md) requires. That file's signed
bytes (SHA-256 `b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665`, DECISION_LOG row 2026-10-04),
Clarification 1 and Clarification 2 are unchanged.

## Source

OWNER DECISION, 2026-11-04 ~10:55 ET, verbatim "approve all recommendations" (owner in the master chat, relayed by master). Master put its recommendations to the owner; the owner approved all of them. The
question text is `docs/research/mg1-look-scoring-2026-10-31/scoring-note.md` §3 on
`claude/mg1-look-scoring-20261031` @ `1179f990d2c350a5c6cc81755c4a77252e344c83`.

## Answers

| # | Subject | Owner answer (2026-11-04) | `mg1_look` at `1179f990d` (PROVISIONAL constant) |
| --- | --- | --- | --- |
| A1 | Denver in the US11 support and scoring | **Denver is OUT.** MG-1's fixed support is B-1's ten markets. The A14 sign rule ("at least 8 of 11 markets negative") becomes **at least 8 of 10**. | `MARKETS` lists B-1's ten plus Denver (line 198) |
| A5 | Materiality bar sign | **bar = -0.05 * \|gap\|.** The bar is always at or below zero, whatever gap's sign. | `bar = -MATERIALITY * gap` (line 507), which is at or above zero when gap <= 0 |
| A12 | Falsifier 4 | **Judged on the CROSSED INTERVAL**, the whole crossed CI, not the crossed point estimate. | the crossed point estimate (line 518); under equal-cell weighting it can trigger only through a population difference |

## What changes and what does not

- Each answer is one constant in `mg1_look`, as Clarification 2 §3 ruled. The change lands on the mg1_look scoring
  head and is recorded, with the re-registered `mg1_look.py` sha256, in a dated note before the look. This file
  changes no code.
- Unchanged: the estimand, the pass rule's other conditions, falsifiers 1-3 except A14's count, the void conditions,
  D0, the 45-date count, the reservation, and every A, T and R11 ruling in Clarification 2.
- No outcome, label, price or score was read to write this file.
