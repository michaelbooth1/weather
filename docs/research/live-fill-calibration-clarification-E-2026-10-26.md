# Live Fill-Calibration Clarification E (DRAFT - UNSIGNED)

**Status: DRAFT - UNSIGNED.** Nothing here is in force until the owner signs it
by hash in a signature record, as for clarifications C and D. Until then the
signed texts and signed clarifications C and D govern.

Owns: the six value changes for the small maker pilot (size, order cap, band
cap, band universe, R6, last start). Read when: signing it, pinning the pilot
commit, or judging a pilot session against PR §2, §3, §4 or §6.

- Amends the signed pre-registration (PR),
  `live-fill-calibration-preregistration-2026-10-09.md`, sha256
  `122d08e4ede30706284fce80d1479536e554526945d005d71f86e7ab49c20975`, signed
  by the owner 2026-10-09T18:09Z
  ([signature record](live-fill-calibration-signature-2026-10-09.md)).
  Sections touched: §2 (declared deviation), §3 (universe, filters, rank and
  item 4 = R6), §4 (last start), §6 (order shape, capital, venue terms, L
  reserve) and §11 R6.
- Signed clarification C (sha256 `4d6ae37a…9054`, signed 2026-10-10T00:28Z)
  and signed clarification D (sha256 `b6647c8c…1404`, signed
  2026-10-10T19:39Z) are unchanged.
- No signed file is edited. This file only adds to them.
- Sources: the owner's request of 2026-10-25 for a small maker pilot, and
  master ruling (2026-10-25) choosing the LFC lane and fixing the values
  below. The one-page plan `maker_pilot_onepage.md` (sha256 `ea70c22b…6a5`),
  §2-§4 and §8 item 6, is the basis master accepted.
- **Code: branch `claude/lfc-pilot-constants-20261026`, tip
  `124603578f393827fa1b67bd978f6e3b02048ae9`**, three commits on
  `bc27f55b01255ccb79bef3631326de865c25d674` (the grace fixes; a descendant of
  the session-1 pin `21cf1ed42`). Every file:line below is at `124603578` (the constants commit `6a95d245a`, the Fable-review follow-up `bcfa1226d`: pilot-market check in `PilotSession`, `lfc_leg_above_order_cap` refusal before `session_start`; and the CI-list commit `124603578`, which adds one test file to the ci.yml audit ratchet step and one to the windows-lane-a shard and changes no code or constants).
  The new pin and its DECISION_LOG row follow the review of that commit.
- Data seen while drafting: none. No outcome, price or label data after
  2026-09-29 and no 88a, panel or settlement data for 2026-09-30..10-15.

## E1. Size: 20 shares per leg

Amends PR §2 "Declared deviation" and PR §6 "Order shape".

- The size is **20 shares per leg** instead of 40 (`PILOT_SIZE`,
  `lfc_constants.py:25`).
- 20 is the reward minimum on T+1/T+2 weather bands. A band whose live
  `/rewards/markets` minimum is above 20 is refused at selection
  (`reward_minimum_outside_treatment`), and a minimum above 20 seen during a
  session ends it under the unchanged PR §6 "Venue terms" rule.
- Consequences, not separate changes:
  - each leg costs at most 16 pUSD (20 × 0.80);
  - bands are ranked by predicted reward at size 20 (PR §3 item 3);
  - the L reserve is 20 × (p_yes + p_no), and the minimum feasible reserve
    in "Stop at 100" is 20 × 0.96 = **19.20** (`MIN_FEASIBLE_RESERVE`).
- The RE-1 depth filter of 75 shares on each side is kept.

## E2. Per-order cap 15.80 pUSD

Amends PR §6 "Capital" (first half).

- The order cap is **0.79 × 20 = 15.80 pUSD** (`PER_ORDER_CAP_PUSD`,
  `lfc_constants.py:30`).

## E3. Per-band (per-market) cap 19.60 pUSD

Amends PR §6 "Capital" (second half).

- The band cap is **0.98 × 20 = 19.60 pUSD** (`PER_BAND_CAP_PUSD`,
  `lfc_constants.py:31`). One band rests at a time, so per band is per market.
- The module refuses to import if either cap differs from 0.79 × or
  0.98 × `PILOT_SIZE` (`lfc_constants.py:32-33`). Counted sessions take both
  caps from these constants (`lfc_pilot.py:127`, `:463`).

## E4. Band universe: Toronto and Denver only

Amends PR §3 item 1 "Universe".

- The universe is the canonical-registry markets **`toronto` and `denver`**
  only (`PILOT_MARKET_IDS`, `lfc_constants.py:37`), still on local T+1 and
  T+2 event dates and still rewarded at selection time.
- The public reader requests only those markets' events
  (`mm_stage2_selection.py:281`). The selection refuses any other market with
  `lfc_market_outside_pilot` (`mm_stage2_selection.py:64-65`).
- Every PR §3 item 2 filter is unchanged, apart from the size-driven figures
  in E1.

## E5. R6 dropped: no predicted-reward floor

Amends PR §3 item 4 and the R6 row of PR §11 (☒ kept becomes dropped).

- Counted sessions have **no predicted-reward ≥ 2.0 floor**
  (`PREDICTED_REWARD_FLOOR = None`, `lfc_constants.py:40`;
  `mm_stage2_selection.py:108`). Bands are still ranked by predicted reward
  and the top eligible band is posted.
- The RE-1 selection outside the campaign keeps its own floor of 2.

## E6. Last start 2026-11-20

Amends PR §4 "Dates".

- The last counted session must start by owner-local **2026-11-20**
  (America/Toronto) instead of 2026-10-31 (`LAST_START_LOCAL_DATE`,
  `lfc_constants.py:70`; refusal `after_last_start_date`).
- The earliest start (2026-10-15T00:00Z), the 23:50Z hard stop and one
  session per owner-local date are unchanged.

## E7. Unchanged

Every other signed rule stays as signed or as amended by C and D. Among them:

- post-only GTD BUY legs at m − 1.5 c and (1 − m) − 1.5 c, snapped outward;
  the [1, 3] c requote window;
- ≤ 10 submits and ≤ 4 requotes per session; the first own fill ends it;
- ≤ 8 counted sessions of ≤ 360 min; GTD expiry = session end + 60 s;
- the L ledger with its 100 pUSD budget and the permanent stop at 100;
- any foreign open order ends the session; the stale-book, stream and
  geoblock stops; the venue-term stops;
- the maker-fee class rule of D7 (a nonzero maker fee fails closed);
- the leg price range [0.17, 0.80], `share_many` ∈ [0.15, 0.70], the depth
  filter of 75, the event-level position exclusion and the panel exclusion
  file;
- the treatment label `LFC-40` and the protocol
  `LFC-live-fill-calibration-v1` keep their names so the ledger and journals
  stay continuous. The label names the campaign, not the size.

## Known effect (no rule change)

At 20 shares the signed `share_many` ≥ 0.15 filter, together with the
75-share depth filter, refuses a band whose competing depth sits at the touch:
100 shares at the touch on each side gives `share_many` ≈ 0.10. A band
qualifies when enough of that depth sits further from the mid. So the t24
`--to-go-prompt` dry run may show no qualifying Toronto or Denver band on a
date (PR §3: no band means no session that date). This is recorded so a
no-band date is not read as a fault.

## Signature

Owner signs by hash in a separate signature record, as for clarifications C
and D, after the review of `bc27f55b0..124603578` and its workstation pregate PASS.

- Owner: <OWNER SIGNS>  Date (UTC): <OWNER SIGNS>
- Data seen at signature: <OWNER SIGNS> (expected: none)
