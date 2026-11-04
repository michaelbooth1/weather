# Rule B-1 clarification: the L6_G forward screen under B-1 §10, 2026-10-29

- **Status:** a disclosure filed after the B-1 binding (2026-10-28). It binds nothing in B-1.
- **Authority:** the owner's reserved-window exemption for L6_G, verbatim "I give my ok." (2026-10-28 ~13:0x,
  master's chat, relayed by master-agent; [decision log](../../operations/DECISION_LOG.md) row 2026-10-28
  "L6_G forward screen: reserved-window exemption (C-EX), owner"), and master's rulings of 2026-10-29.
- **History only:** no outcome, label, price or market row dated after 2026-09-29 was read to write this.
- **What changes:** nothing in B-1. This file changes no bound file, rule, hash, threshold, date, market,
  interval, estimand or keep/kill rule of B-1 or of MG-2. It records that a second candidate accrues on dates
  that overlap B's, as B-1 §10 ("Other candidates ... needs its own owner decision") requires, and pins what
  that candidate is.

## 1. Why

- **B-1 §10:** any other NBM-reading candidate on 10-15..11-28 needs its own owner decision, gets its own
  pre-registration after its own freeze, and makes no best-of selection with B on shared dates.
- **L6_G** (L6 plus a GEFS-member spread shift) is such a candidate. Its owner decision is the 10-28 exemption.
  This file discloses it next to B-1 so that B's look can see what else accrued on its dates.

## 2. The candidate and its pins

| Item | Value |
| --- | --- |
| Pre-registration | `docs/research/gefs-members-l11-2026-10-26/l6g_forward_prereg_DRAFT.md` on `claude/l6g-forward-land-20261028` |
| Frozen (a_h, b_h) state, the bound object | `l6g_state.json` sha256 `ae95686b5468bceed0fd33ead0f397dc061d9a5822f56bfb2364814553e8983e`; the emitter verifies it before every emission |
| State producer | commit `341acbd2b5d8bef89254a8c92203927d638bc7a6`; `src/weather/calibration/pooled_residual_model.py` git blob `80a585e8ea19098b8de4da03b4e7996021e87756` |
| Producer branch | `claude/ro-gates23-20261028`, pushed and **not landed**; it is retained, never deleted or rewritten, until the L6_G look is recorded |
| Frame builder clarification | `docs/research/gefs-members-l11-2026-10-26/l6g_forward_frame_clarification_2026-10-29.md` on `claude/l6g-frame-builder-20261029` @ `22ce88222b0d6766af5c722d53334b00f5cae4ec` |
| Frame builder | `src/weather/calibration/l6g_forward_frame.py` git blob `75a587b02ca5a579fdbbd08c65387fad249d4db9` |
| D0 | 2026-10-31 (the prereg's rule: latest of landing + 1, the GEFS recorder's first full receipt day and 2026-10-29; cap 2026-11-02) |
| First emission | 2026-11-01 |

**Master's ruling (2026-10-29):** the frame builder does not compare the MG-2 layout manifest's schema string.
Naming it in `src/` would trip the existing receiver ratchet, and `test_mg2_inputs` is not changed during the
bound period. The builder's other layout checks stand as its clarification lists them.

## 3. How it coexists with B

- **No effect on B.** L6_G reads MG-2's bound forward input bundles; it writes only its own vectors. B's
  scorer, vectors, receipt and verdict do not read anything L6_G writes.
- **Order of reads:** L6_G's single look comes after B's look receipt (≥ 2026-12-13).
- **No selection.** L6_G's result never alters, re-cuts or overrides B, and there is no best-of choice between
  MG-2 and L6_G on shared dates.
