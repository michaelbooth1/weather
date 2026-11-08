# Live fill-calibration — clarification F: economic selection filters relaxed so the campaign trades (2026-11-07)

Status: **in force**, owner-directed 2026-11-07. The owner's words and the reviews are in
[the approval record](live-fill-calibration-clarification-F-signature-2026-11-07.md).

F amends two signed texts:

- the pre-registration ([`live-fill-calibration-preregistration-2026-10-09.md`](live-fill-calibration-preregistration-2026-10-09.md)), §3 filters;
- clarification E ([`live-fill-calibration-clarification-E-2026-10-26.md`](live-fill-calibration-clarification-E-2026-10-26.md)), E7, which kept those filters at 20 shares.

The pre-registration, clarifications C, D and E, and the session-1 freeze are otherwise unchanged. F applies
prospectively, from session 1 (2026-11-09) on. No session had been counted when it was made.

## F1. The change (LFC profile only; the RE-1 path is unchanged)

| Selection filter | Before | After |
| --- | --- | --- |
| Predicted `share_many` | [0.15, 0.70] | **off** ([0, 1]) |
| Reward rate of the band | ≥ 40 pUSD/day | **any rewarded band** (> 0) |
| Displayed YES-book depth per side within the reward max spread | ≥ max(75, size) | **≥ 20** (the leg size) |

- **Code:** session-1 executor pin `57fe4ce1eeb14e7c0800d5eaecf65fc7eef638e1` on `codex/lfc-f0-sharefloor-20261107`. Its ancestors are
  `27f169cef80aa93d6c9c52551a040694e8d2a5f5`, an intermediate step that lowered only the share floor to 0.08 and
  was superseded the same night, never used live, and `f531395522d0b0a37495185b2750164008fe586a`.
  The values live in `lfc_constants.py` (`SHARE_MANY_RANGE`, `MIN_REWARD_RATE`, `MIN_BOOK_DEPTH`) and are threaded
  through selection, preflight, `live`, the post-go re-read and requotes.
- **Unchanged:**
  - the reward max spread ≥ 3 c and the reward minimum size ≤ the leg size;
  - the book spread ≤ 6 c, the size-adjusted mid in [0.20, 0.80] and legs in [0.17, 0.80];
  - the post-only touch buffer and the [1, 3] c leave-alone window;
  - Toronto and Denver only, local T+1/T+2, and the event-position exclusion;
  - the 20-share leg, the 100 pUSD L budget, 15.80 pUSD per order, 19.60 pUSD per band, the session count and length,
    GTD expiry and every stop;
  - **ranking by predicted reward.** Selection still posts the best band available; it only stops refusing when the
    best is not great.
- **F2 self-start campaign:** its selection fields default to the same values in its own pin. They stay adaptable in
  the learning window and freeze at 11-16 (T033).

## F2. Why

- **The owner's directive, verbatim:** "I think we over safetyfied this. I want a 95% chance we trade at all. Nothing
  less seems accepetable to me".
- **The three filters are economic, not money-safety rules:**
  - the share floor was set for 40-share legs (`s20 = s40/(2 − s40)` makes 0.15 at 40 equal 0.0811 at 20);
  - the rate floor and the depth guard were RE-1's reward-economics choices.
- **What still protects the money:** the caps, the price ranges, the spread limit, post-only quoting, GTD expiry and
  the venue's heartbeat dead-man.
- **With the old filters,** an informal estimate (F4) suggested most selection runs found no eligible band.

## F3. Effect on the measured quantities

The protocol's `c_at` and `c_thr` are per offered share and are compared with replay at the same size, as before. The
relaxed filters admit bands with more competition, lower reward rates and thinner books, so the selected population
changes. The change is prospective and the replay is matched to the selected conditions, so this brings no selection
bias.

Reports keep the population visible. Verdicts and diagnostics report, at selection time:

- `share_many` in [0, 0.08), [0.08, 0.15) and ≥ 0.15;
- reward rate below or at least 40;
- depth below or at least 75.

Expected reward credit per session falls for the newly admitted bands. Reward income was never the protocol's
qualifying quantity.

## F4. Data seen

- **The change** rests on the owner's directive and the formula above. It needs no data.
- **An informal estimate of how often the old filters idle a session** was made on 2026-11-07 from 88a maker-capture
  metadata for UTC 2026-09-26..10-12.
  - Under the edge trial charter §3.2, the released 09-30..10-14 window may describe.
  - Under the reserved-confirmation-window embargo row, maker-economics reads of 09-30..10-14 stay closed.
  - The read is recorded as an exposure in [DECISION_LOG](../operations/DECISION_LOG.md), and the owner rules which
    text governs. F does not depend on that estimate.
- No data for event dates on or after 2026-10-15 was read.
