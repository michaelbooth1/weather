# Live testing plan — 2026-09-25

- **Owns:** the reviewed plan for the next adequate RE-1 sessions and the staged live experiments after RE-1.
- **Read when:** preparing the last RE-1 session or proposing RE-2 experiments.
- **Do not use for:** authority (STATE_OF_PLAY "Current authority" and the decision log own it); measured results (EF §10m-§10o).

Designed by a read-only second-opinion agent on 2026-09-24 and reviewed by the production agent against tip `03c8fd028`.

## Next adequate RE-1 session (cap now 30; session 10 was lost to post read lag, fixed in `10fa052a0`)

Purpose: the first **adequate** session (>= 180 two-sided minutes, >= 95% sampled) on a contested local T+1 band: share path at
10/30/90/180/360 minutes, fill hazard over hours, a formal `k`/`k_accrued`, requote count, heartbeat 429s.

- **Accept at the confirmation block** only if `share_many` is between ~0.15 and ~0.70 and the condition is not the held Miami
  90-91°F Sep 25 band (`0x977d84a4…`; it would end `initial_positions` after the attempt marker). Refusing (typing anything else)
  consumes nothing because the phrase is checked before the attempt is reserved. Up to three refusals ~5 minutes apart.
- **Start** at :59-:05 past the hour, after the routine METAR cluster (:51-:58) and the ~:50 HRRR drop; the latest start keeps
  six hours inside the UTC day (14:00 ET). Preflight must PASS on the same commit and UTC date.
- **Stop early only** on a fill or a cleanup failure (`cancel-only`). No manual orders on the account during the session
  (`open_orders()` is account-wide). The owner stays reachable for the six hours or checks the app on waking.

## After RE-1 (new authority for anything live)

| # | Experiment | Question | Change | Authorization |
| --- | --- | --- | --- | --- |
| S0 | Land and register 88a capture | Q-05, Q-06 | none to RE-1 | approved 2026-09-23 |
| S1 | Zero-harm over-balance test (far-from-mid buys above cash, then withdraw cash; one order above cash) | Q-13 | none (manual) | owner action |
| S2 | Resting SELL on a held lot (Miami 75 YES before it resolves, else the next lot) | Q-04 | none (manual) | placed 09-25 (Chicago 68-69 YES 75 @0.37), withdrawn unfilled by the owner; still to run |
| S3 | Contested-band campaign, 6-8 x 6 h, local T+1, depth rule, sizes alternating 20/75 | Q-01, Q-05 | constants (caps, dates, size schedule) | new owner authorization + dated pre-registration |
| S4 | Multi-band NO basket, one negRisk event, 3 adjacent bands, 20 shares | Q-12 | new order shape on the 90a engine | RE-2 + pre-registration |
| S5 | Taipei capture, then one T+1 session (deep book: 75 shares buy a tiny share) | Q-14 | config | owner (config) + RE-2 |
| S6 | Cross-market over-commitment with guards (global ratio cap, per-event and per-information-cluster caps, cancel whole book on first fill, balance read before each post) | Q-13 | 90a engine | RE-2 + pre-registration, last |
