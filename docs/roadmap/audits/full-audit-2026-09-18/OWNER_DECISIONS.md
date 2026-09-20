# Owner decision sheet — what only you can settle before the next live test

Prepared 2026-09-19. Engineering can clear everything else; none of it matters if these stay open. Short answers are enough.

## 1. Geographic eligibility — RESOLVED by owner statement, 2026-09-19
**Owner statement (verbatim, 2026-09-19):** "Yes this PC is eligible to trade on International Polymarket when it is
being run. We sometimes need to tunnel to Ontario to access files on my home PC. But this PC never moves from its
physical location that is trade eligible. Record this as not an issue."

**What that explains:** on 2026-09-06 the venue geoblock endpoint read `blocked=true, CA/ON` at 13:18Z and 18:21Z and
`blocked=false, MX/QUE` 4m45s and 2m36s later on the same host. The CA/ON readings are the Ontario file-access tunnel
being up; the unblocked readings minutes later are the PC's own connection with the tunnel down (the owner states its
physical location is trade-eligible and never changes). The gate behaved correctly both times: it refused while the
egress was Ontario and passed on the PC's own connection. This is the reverse of
circumvention, and it matches the retry note written that day ("the Ontario location attribution was mistaken").

**Status: not an issue, per the owner.** Recorded as the owner's attestation; nothing in the repo can verify physical
location and the runbook deliberately never stores it.

**One operating rule that follows (engineering, not a decision):** the Ontario tunnel must be DOWN for the whole of any
live session. If it comes up mid-session the venue sees Ontario, and the runbook's cancel-all rule fires. Worth a
preflight line: "home tunnel is down" next to the geoblock check. No change to the eligibility code is needed.

**Two doc clean-ups so this is not re-raised by the next audit:** `CLI_SSH_HANDOVER_2026-08-13.md:52-54` calls the
capture host "Ontario production" — correct or qualify it; and the branch item 67 ledger omits the two geography
attempts — restore them with the explanation above so the record is complete rather than quietly shorter.

## 2. Live authority
Standing instruction: no live trading. Nothing in the 24-hour plan needs it. When you lift it, say which stage
(a fresh Stage 0/1 is required anyway — the bootstrap artifact expires after one hour — then Stage 2, one band).

## 3. The economics input that changed today
Configured liquidity-reward pool for our 12 events: **~2,800/day same-day, ~4,800/day including T+1/T+2**, stable for
the 31 days I could sample (`D3_REWARD_CEILING.md`). The docs still say ~$16/day and "a subsidy, not a business", and
the July NOT_VIABLE verdict was computed against that. This supports your instinct. It is a pool shared by all makers,
not income; tonight's two studies estimate the share a capped quoter wins and what resting quotes lose to informed flow.

## 4. Caps vs reward minimums
10 pUSD per-band cap; a two-sided 20-share quote needs ~19.60. Under the current cap **no quote can be reward-eligible**,
and the harvest lane additionally clamps size to 5 shares. If rewards are the thesis, the cap has to move (to ~25 per
band for the 20-share bands; ~100+ for the 100-share same-day bands). Decide the number and the total capital at risk.

## 5. Hurdle and stop rule
Item 330 has no hurdle H, no date for G1 and no stop rule. Suggested: H = net (rewards + rebates + trading P&L) per day
per 100 pUSD deployed that you would accept; a date by which paper + first live evidence must clear it; and what
happens to capture if it does not.

## 6. Wallet and credentials
The live wallet is your personal wallet (~490 pUSD last observed; account-wide cancel-all hits personal orders; 214 pUSD
moved unexplained around the test). A dedicated wallet funded to the cap removes that. `Desktop\.env.txt` is unexplained
(I have not opened it); if it holds a signing key, rotate it.
