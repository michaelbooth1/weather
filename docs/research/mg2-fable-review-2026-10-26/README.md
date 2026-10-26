# MG-2 and Rule B-1: Fable review packet (2026-10-26)

Index for master's overnight Fable review. Fable reads git only; every document it needs is in this folder or
named below by commit and path. Markdown only; nothing here binds anything. Rule B-1 binds only through master's
10-27 binding commit.

## 1. Rule B-1 (bind-ready draft, with its amendments)

| File | Source | sha256 |
| --- | --- | --- |
| [B_FORWARD_TEST_DESIGN.md](B_FORWARD_TEST_DESIGN.md) | review copy of `docs/operations/B_FORWARD_TEST_DESIGN.md`, `claude/docs-head-20261026b` @ `a3f0828e1` | copy `37b138e4ccca320cd3de485420d81573a89ffe42609f3867cf8e537e0aa4f523`; source `62c144bf0826832a4627217b4c756eac10e46b88ae4729454099ae5fb5f071f8` |

- The source is the coordinator's bind-ready draft, raw sha256 `c0a4f467ff09980396d5b45dc1548f8932ed5e1a0bc4481263348f05d1433446`,
  filed in the docs head (`a8e559b20` and later), with its note and Appendix A (`retrain_overlap.md`, `11c1cf58…`).
- Amendments already in the source: master's B rulings 2026-10-26 (binding via the C7/C8 line, `710f0c672` superseded;
  scorer choices (a)-(d); `b_scorer_sha256` `b25b63f7…` and control receipt `6284af68…` to fill at binding);
  master rulings (a) Denver excluded (10 markets; MG-2 C8) and (b) venue-rule labels from 10-23. The PT-1 and
  venue-label records are in the [decision log](../../operations/DECISION_LOG.md) rows of 10-25/26 and, on the docs head, in
  `docs/operations/COOL_SEASON_PAPER_TEST_PREREG.md` (PT-1 not refit, master ruling 10-25) and `docs/operations/venue-rule-labels.md`.
- New in this copy (2026-10-26): the pre-declared SECONDARY descriptive reads in §7 (13-16 vs 07-12; Oct vs Nov-Dec;
  season-matched L6 hours 07/08 and Chicago/NYC) and the `l6_state_sha256` `<FILL@BINDING>` field.
- **Review point:** the B scorer at `48d89f855` lists its bound fields in `BOUND_FIELDS` (`b_scorer.py`); `l6_state_sha256`
  is not among them, so the scorer neither requires nor verifies it, and `unfilled()` would not flag it. Fixing that is code,
  outside this packet.

## 2. MG-2 rule documents (verbatim copies, texts unedited)

Each file is byte-identical to `docs/research/mg2-composite-binding-2026-10-25/rule.md` at the named commit.

| Clarification | File | Branch @ commit | sha256 |
| --- | --- | --- | --- |
| C6 (ledger rows 32/33 after the renumbering; L8) | [mg2_rule_C6_710f0c672.md](mg2_rule_C6_710f0c672.md) | L8 tip `710f0c672` (an ancestor of the C8 and B tips) | `2d0f21003fcbe40b02d7360938cc29e118fb8bd128fcb94515f603aa113d2d38` |
| C6+C7 (as-of-capture forward gate) | [mg2_rule_C6C7_525effe62.md](mg2_rule_C6C7_525effe62.md) | `claude/mg2-c7-asof-gate-20261025` @ `525effe62` (an ancestor of its tip `e40804dfe`) | `ccb2b82a415056ddfe1edc6fe2ca7192b82e8d940db96eb61101d99b19914f3b` |
| C8 (Denver leaves the G1/G2 gate, KDEN from 10-23) | [mg2_rule_C8_45576565b.md](mg2_rule_C8_45576565b.md) | `claude/c8-host-skip-20261026`, `45576565b` | `a36bade1079f5fa3627d8add7a7ccf837d77e6411f3ac0a03c15a17c6b959fd2` |

Companions, not copied (their relative links would break here); read them with `git show <commit>:<path>`:
`docs/research/mg2-composite-binding-2026-10-25/binding-plan.md` and `dev_rule.md` at `45576565b`.

## 3. Dated MG-2 clarification: season-matched L6 (L3)

SLOT: L3 is drafting it; its branch tip and path are added here when they arrive (expected ~22:00 2026-10-26).

## Code tips for review

| Tip | Full sha | Content |
| --- | --- | --- |
| C8 | `45576565b721c4ea896a6c257091f86c5b0d4057` | MG-2 C8 gate population (Denver out), host skip, high_so_far ImportError fix |
| B | `48d89f855f8504cdae35ed5e968f4c90fc7857bd` | B scorer (`weather.calibration.b_scorer`) and `mg2_inputs`; merges the C8 tip |
