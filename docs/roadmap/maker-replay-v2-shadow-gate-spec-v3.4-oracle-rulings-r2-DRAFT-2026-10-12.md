# Maker replay v2 oracle: owner rulings that bind the oracle (sheet r2, SIGNED 2026-10-12)

> **SIGNED r2 (owner, relayed by master-agent, 2026-10-12 ~20:00). Handout item H-11.** It replaces
> [sheet r1](maker-replay-v2-shadow-gate-spec-v3.4-oracle-rulings-2026-10-07.md) as H-11. The filename keeps its
> DRAFT date stamp so links and the cut plan stay stable. It owns only the list of owner rulings that fix what the clean-room oracle computes, each with its source,
> in design words. It restates no engine code; the meaning of each ruling is the cited spec text. Maker replay v2 status
> lives in [the state of play](../operations/STATE_OF_PLAY.md), owner decisions in
> [the decision log](../operations/DECISION_LOG.md), work status in
> [item 330](items/item-330-maker-economics-refocus-master-plan.md).
>
> **Read when** signing H-11, preparing the oracle author's handout, or checking whether a later ruling changes what the
> oracle computes.
>
> **Handout status.** Handed out byte-identical and pinned by the SHA-256 of its raw bytes at the cut, and §4-checked
> like every handout file. Its filename matches the v3.4 §5 exclusion `docs/roadmap/maker-replay-v2-shadow-gate-spec-*`,
> so it reaches the author only as that hashed handout item, never through the filtered tree.
>
> **Update when** the owner rules, re-rules or clarifies a row below before the cut. After the cut, any change is a
> new handout revision (re-hand).

**Changes from r1:** OD23 now carries the owner's signed replacement wording of 2026-10-08, which settles r1's recorded
wording difference; OD18 (b) and OD21 now cite their DECISION_LOG row; OD22 and OD26 carry a confirm-by-ID line for the
signature; the 2026-10-08 and 2026-10-09 rulings are classified; sources that are not yet on the master branch are
marked.

Source labels: **DL** = a row of `docs/operations/DECISION_LOG.md` on the master branch, by date and topic; **signed,
not yet in DL** = an owner signature relayed by the master agent whose DECISION_LOG row is written but not yet landed;
**08:55** = the owner's "approve all recommendations" of 2026-10-07, 08:55. Option letters refer to the cited spec rows.

## 1. Rulings that fix the oracle's semantics

| Ruling | What is ruled (design words) | Option text (spec) | Source |
| --- | --- | --- | --- |
| **W1 = OD19 (a)** | Own resting legs are in the decision book at their prices, on both sides, before the policy decides. Disclosed as registration row C11, with re-run attribution. | v3.1 §17 OD19 (a), as changed by v3.2 §11 and v3.3 §9 OD19 | DL 2026-10-07 "Maker replay v2 engine semantics" |
| **W2 = OD20 (a)** | A replacement after a cancel decides on the book without the cancelled legs. Disclosed as registration row C12. | v3.1 §17 OD20 (a), as changed by v3.2 §11 OD20 | DL 2026-10-07, same row |
| **F3** | The descriptor horizon refreshes at local midnight. Disclosed as registration row C13. | v3.3 §4 and §9 OD19 (C13) | DL 2026-10-07, same row |
| **OD23 (signed wording)** | Before the exam, `decide()` is unchanged. It computes the qualified mid from the decision book it is given, own resting size included, and removes own size only from the competing reward score and the displayed depth. Under W1 (a) the decision book carries own legs as the venue shows them, so an own leg of at least the reward minimum size can set the best qualified bid or ask and move the mid, as it would live. Excluding own size from the mid would be a policy change and would need a new registration. The oracle uses the handed-out `decide()` as is. | v3.1 §17 OD23 ("No change before the exam"; its premise already says the mid can move with own size) | Owner signature 2026-10-08 20:21, relayed by the master agent: **signed, not yet in DL** (written as a DECISION_LOG row on a docs branch that has not landed). It supersedes the OD23 clause of DL 2026-10-07, which misdescribed `decide()`. DL 2026-10-08 (20:21) lists "the corrected OD23 wording is signed" as a parity blocker. |
| **OD25 (ii)** | If the kernel fix misses 10-23, the signature slips; never an automatic fallback to a known deviation. | v3.2 §11 OD25 option (ii) | DL 2026-10-07 "Maker replay v2 engine semantics" |
| **OD18 (b)** | A fresh agent, started by the production agent on the production host, writes the oracle from the filtered handout. The workstation never authors or touches it. | v3.4 §5 "Author", §8 point 6 | DL 2026-10-07 "OD18" |
| **OD21: deferred** | No TL unit or owner is named now. The oracle's author is never TL's author. | v3.2 §11 OD21; v3.3 §9 OD21 | DL 2026-10-07 "OD18" (same row) |
| **OD22** | Stands as recommended in the cited spec row. | v3.3 §9 OD22 | 08:55 "approve all recommendations". **Confirmed by ID at signature:** ☑ |
| **OD26** | Stands as recommended in the cited spec row: the broken-night caps are frozen after calibration and may only be lowered later. | v3.3 §9 OD26 | 08:55 "approve all recommendations". **Confirmed by ID at signature:** ☑ |
| **Q2 N1 (a)** | A derived local-midnight descriptor is produced only at a local midnight that falls inside a day the run is driven over. Across a day the run does not drive, no derived descriptor exists: the latest descriptor's horizon is carried unchanged into the next driven day, even where the true local lead would be 0 or below, until a captured descriptor, or a derived one at a midnight inside a driven day whose new lead is within 0..2, replaces it. The registered quote panel 09-30..10-13 is contiguous, so this ruling binds fixture cross-validation and partial-panel runs. The handout at `501f47579` does not carry this text (the registration text is excluded), so this row is its carrier. Classified oracle semantics by H0, 2026-10-12. | v3.2 §4.3; v3.3 §1, §3.2 (iii) | DL 2026-10-09 "Recommendations approved as listed" |

With OD19 (a) and OD20 (a) ruled, the (b) alternatives written for each item in v3.1 §3.7 do not apply: the oracle
implements the (a) alternatives only, and no classifier for the (b) branches is needed. With OD25 (ii) ruled, there is
no automatic fallback to (b) (v3.2 §2.3).

## 2. Rulings that do not change the oracle's logic

These rulings change the engine's inputs, the build line's input handling, run bindings or the shadow, not the logic
the oracle implements. The classification is this sheet's (workstation unit H1), not an owner ruling; the owner's
signature of this sheet adopts it.

| Ruling | What is ruled | Why the oracle's logic is unchanged | Source |
| --- | --- | --- | --- |
| U1-Q1 | Refuse a calibration panel with an owner exclusion inside its span. | panel admission (input) | DL 2026-10-07 "Maker replay v2 build line" |
| U1-MF5 | Refuse a second Austin event. | panel admission (input) | same row |
| Q2/N4 | Supporting pulls fire on a rise since the previous poll now; a running maximum before any T+0 quoting. | trigger input | same row |
| OD36 | SWOB and the clock fix land as one unit. | input delivery | same row |
| OD37 | Drop the bare "HH:MM" fallback (refuse instead of guess). | input parsing | same row |
| Parity definition | "Shadow agrees with replay" means the same quote/no-quote decision and every price within 1 tick on identical tapes. | the shadow-vs-replay gate, not the oracle | DL 2026-10-08 "Parity definition" |
| Shadow hazard and tape | Forward shadow hazard 0.001 per minute until the engine freeze; a v0.2 raw-record shadow tape. | shadow only | DL 2026-10-08 (20:21) |
| T1-T3 (a, a, a) | Pin the time-zone database for scored runs and bind its version and the zone map into the run digest; the market zone lookup requires the registry argument. | run integrity: the oracle's cross-validation runs use the same pinned zone data | DL 2026-10-09 "Recommendations approved as listed" |
| Q2 horizon clause (a) FULL | Active intervals are computed by the manifest builder from captured-or-derived descriptors; T+0 runs become exclusions, never NO_QUOTE; calibration hazard count unchanged (disclosed). | The oracle takes the manifest's active intervals as given (v3.1 §6.3 I14 step 1) and already withdraws legs at the interval end; `decide()`'s horizon input is F3 (§1). The Kernel's blind_re1 HORIZON_NOT_ELIGIBLE pull is outside Tier I (I14 step 3, informed-v0 only) and unreachable inside clause windows (registration §4 gate ordering). Classified input-only by H0, 2026-10-12. | DL 2026-10-08 (20:21) |

## Signature

Owner: owner, relayed by master-agent, 2026-10-12 ~20:00 (DECISION_LOG 2026-10-12) Date: 2026-10-12 OD22 confirmed ☑ OD26 confirmed ☑ §3 classified ☑ (by H0, 2026-10-12; §3 removed, rows moved to §1 and §2)

The SHA-256 of this file's raw bytes is recorded in the H1 manifest at the cut; a change after signature is a new
revision.
