# Maker replay v2 oracle: owner rulings that bind the oracle (sheet, 2026-10-07)

> **Repository copy (2026-10-07). Companion to the [v3.4 DRAFT](maker-replay-v2-shadow-gate-spec-v3.4-DRAFT-2026-10-07.md);
> no authority of its own.** It owns only the list of owner rulings that fix the semantics the clean-room oracle must
> implement, each with its source. It restates no engine design: the meaning of each ruling is the cited spec text.
> Maker replay v2 status lives in [the state of play](../operations/STATE_OF_PLAY.md), owner decisions in
> [the decision log](../operations/DECISION_LOG.md), and work status in
> [item 330](items/item-330-maker-economics-refocus-master-plan.md).
>
> **Read when** writing or Defending the H1 cut script, preparing the oracle author's handout, or checking whether a
> later ruling changes what the oracle computes.
>
> **Handout status.** Proposed source for the handout's owner-rulings item. Whether it is handed out, and in which
> form, follows the v3.4 DRAFT once the owner accepts it; until then it is not part of the handout. Its filename matches
> the v3.4 §5 exclusion `docs/roadmap/maker-replay-v2-shadow-gate-spec-*`, so it is never in the oracle's filtered
> tree; it can reach the author only as a hashed handout item.
>
> **Update when** the owner rules, re-rules or clarifies any row below, or a relayed ruling gets its DECISION_LOG
> entry. Applying such a change to this sheet before the handout is cut is allowed; after the cut, a change is a new
> handout revision.

Source labels: **DL** = a row of `docs/operations/DECISION_LOG.md`; **SoP** = the "Owner decisions 2026-10-07"
block of `docs/operations/STATE_OF_PLAY.md`; **relayed** = relayed by the master agent on 2026-10-07 and not yet in the
decision log. Option letters refer to the cited spec rows.

## 1. Rulings that fix the oracle's semantics

| Ruling | What is ruled | Option text (spec) | Source |
| --- | --- | --- | --- |
| **W1 = OD19 (a)** | Fix W1: own legs in the decision book at their prices, on both sides, before signature, disclosed (registration row C11) with re-run attribution. | v3.1 §17 OD19 (a), as changed by v3.2 §11 OD19 and v3.3 §9 OD19 | DL 2026-10-07 "Maker replay v2 engine semantics" ("fix W1 (own legs in the decision book at their prices on both sides)"); SoP ("fix W1, W2, F3 with disclosure and re-run attribution") |
| **W2 = OD20 (a)** | Fix W2: a replacement after a cancel decides on the book without the cancelled legs, disclosed (registration row C12). | v3.1 §17 OD20 (a), as changed by v3.2 §11 OD20 | DL 2026-10-07, same row ("W2 (a replacement after cancel decides on the book without the cancelled legs)"); SoP |
| **F3** | The local-midnight horizon refresh, disclosed (registration row C13). | v3.3 §4 and §9 OD19 (C13) | DL 2026-10-07, same row ("F3 (local-midnight horizon refresh)"); SoP |
| **OD23: no change** | The policy is not changed before the exam; the handed-out `decide()` is used as is. | v3.1 §17 OD23 ("No change before the exam") | DL 2026-10-07, same row; SoP ("OD23 no change") — see OPEN item 1 |
| **OD25 (ii)** | If the kernel fix misses 10-23, the signature slips; never an automatic fallback to a known deviation. | v3.2 §11 OD25 option (ii) | DL 2026-10-07, same row ("if the kernel fix misses 10-23 the signature slips, never an automatic fallback"); SoP ("a miss slips the signature (OD25)") |
| **OD18 (b)** | A fresh clean-room agent on the host writes the oracle from the filtered handout; the workstation never authors or touches it. | v3.4 DRAFT §5 "Author" and §8 point 6 | **relayed 2026-10-07, pending DECISION_LOG entry** |
| **OD21: DEFERRED** | No TL unit or owner is named now. The constraint that the oracle's author is never TL's author stands. | v3.2 §11 OD21; v3.3 §9 OD21 (scope) | **relayed 2026-10-07, pending DECISION_LOG entry**; SoP still lists "OD21 (live-executor unit/owner)" under "Still open" |

With OD19 (a) and OD20 (a) ruled, the (b) alternatives written for each item in v3.1 §3.7 do not apply; the oracle
implements the (a) alternatives only. With OD25 (ii) ruled, there is no automatic fallback to (b) (v3.2 §2.3).

## 2. Rulings that do not change the oracle

These 2026-10-07 rulings change the engine's **inputs** or the build line's input handling, not the logic the oracle
implements. They need no re-hand of the oracle's semantics:

| Ruling | What is ruled | Source |
| --- | --- | --- |
| U1-Q1 | Refuse a calibration panel with an owner exclusion inside its span. | DL 2026-10-07 "Maker replay v2 build line"; SoP |
| U1-MF5 | Refuse a second Austin event. | DL 2026-10-07, same row; SoP |
| Q2/N4 | Pulls fire on a rise since the previous poll now; changed to a running maximum before any T+0 quoting. | DL 2026-10-07, same row; SoP |
| OD36 | SWOB and the clock fix land as one unit. | DL 2026-10-07, same row; SoP |
| OD37 | Drop the bare "HH:MM" fallback (refuse instead of guess). | DL 2026-10-07, same row; SoP |

The statement that these rulings leave the oracle unchanged is this sheet's classification (from the H1 scoping
unit), not an owner ruling.

## 3. OPEN

1. **OD23 wording.** The decision-log row says the policy "keeps ignoring own size in the mid". The spec's OD23
   premise (v3.1 §17 OD23, finding G3) says that under (a) the qualified mid **can** move with own resting size, and
   asks whether the policy should exclude it; the recommendation adopted is "no change". The ruling's effect on the
   oracle (use the handed-out `decide()` unchanged) is clear; the decision-log paraphrase conflicts with the spec
   premise and needs an owner clarification or a corrective decision-log entry before this sheet is signed.
2. **OD22 and OD26** were approved only inside "approve all recommendations". Confirm them by ID before this sheet is
   signed, or record that they do not bind the oracle.
3. **OD18 (b) and OD21 (deferred)** need their DECISION_LOG entries; `STATE_OF_PLAY.md` still lists OD21 as open.
4. **R1, R2 and R4** (v3.4 DRAFT §5 and §8 point 7) are pending; they govern the handout's form and commit, not the
   oracle's semantics.
