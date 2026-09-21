# Stage 2 place-and-hold: owner decision draft

**NOT IN FORCE. This document grants nothing.** It owns the reviewable Stage 2
decision and abort card. Read before owner review; the
[pilot runbook](INTERNATIONAL_MM_LIVE_PILOT.md#stage-2-one-band-maker-quote)
owns execution. Mission 09-80b corrects the prior cancellation and duration
specifications. Offline implementation authority is not live authority.

## Treatment for owner review

- Fresh dedicated wallet, isolated branch, cash at most 100 pUSD. The old
  September 6 allocation is not isolation: the real validator rejects its
  recorded 275.48 and 489.60767 pUSD balances. The allocation validator stays
  unchanged. Fresh attended Stage 0/1 evidence is required on the adopted source.
- Two independent, single-use token capabilities for one condition: twenty
  YES shares and twenty NO shares, BUY, post-only, no replacement. Numeric
  limits are 16/order, 20/band, 25/event, 25/daily loss and 100/wallet.
- One typed confirmation per sealed session includes its displayed scope and
  the physical-location/no-circumvention literal. The file-access tunnel must
  be down. Geography remains an independent fresh official endpoint check.
- The credential-import receipt has no maximum age. Its exact fields, host,
  principal, identity reference and deleted-source comparison remain binding.
- Fresh token-bound venue fee must be finite, nonnegative, equal to the
  candidate fee and journaled before each submit. Zero is accepted evidence.
- Explicit cancel-all of both legs, acknowledgement and authoritative terminal
  reconciliation are primary on every end condition. The unchanged venue
  heartbeat-lapse observation window is 10–15 seconds. **After total loss of
  connectivity, two post-only twenty-share buys may remain for up to fifteen
  seconds; about 19.40 pUSD of reserved capital bounds the loss.** Five seconds
  is the heartbeat cadence, not a guaranteed cancellation deadline.
- Ratify the [PROPOSED RE-1A addendum](../research/re1a-hold-treatment-addendum-2026-09-21.md)
  before the first order: cumulative 180 visible two-sided minutes and
  `P_many >= 2` on one band in one UTC reward day; 120 minutes/session,
  four sessions/day, three reward days total, all reported. The selection
  rule, RE-1M, prediction formula and verdict thresholds are unchanged.

## Exact authorization shape, deliberately unfilled

After host qualification, review, guarded adoption and fresh attended Stage
0/1, the owner must separately approve the adopted tip, exact host/principal,
dedicated public identity reference, condition, complete selection-table hash,
session window and the treatment above. This implementation branch is not a
new exception to the delegation contract's sole authorized portable topic ref.

The two grants must contain identical four-field objects. The approved
`stage2_hold_v1` profile supplies its SHA-256; its canonical bytes include all
capital, duration and campaign limits. `authorized_on` must equal the execution
UTC date. The aware `expires_at_utc` must remain in that date and outlive the
whole session plus twenty-second cleanup. Duplicate or extra keys fail closed.

The future diff is one line inside the sole `## Current authority` section of
`STATE_OF_PLAY.md`, and one optional top-level key in the existing assigned-host
JSON. The placeholders below are intentionally invalid; **do not write either
grant as part of implementation or rehearsal**:

```text
Stage 2 owner authorization: {"profile_id":"stage2_hold_v1","profile_sha256":"<reviewed canonical profile SHA-256>","authorized_on":"<execution UTC date>","expires_at_utc":"<owner-approved aware expiry>"}
```

```json
"stage2_hold_owner_authorization": {
  "profile_id": "stage2_hold_v1",
  "profile_sha256": "<same reviewed canonical profile SHA-256>",
  "authorized_on": "<same execution UTC date>",
  "expires_at_utc": "<same owner-approved aware expiry>"
}
```

The host's six existing assignment fields remain exact and unchanged. Grant
shape support does not grant credential access, alter the offline module
allowlist, or authorize a session. The adapter rechecks the grants at capability
authorization, signing and posting. The sealer binds the grants and source
bytes; the launcher retains the host lease, deny-write protections, attended
desktop checks and kill-on-close child containment.

## Abort card

1. Before either submit, a missing confirmation, isolated-wallet proof, exact
   predecessor, grant, source binding, fresh fee, geography, book or reward
   terms means refusal. Check zero account-wide open orders before leg one;
   before leg two, permit exactly our first resting order and nothing else.
2. On any fill, unknown event, rejected/ambiguous submission, held-price
   distance outside 1–3 cents or the reward spread, reward minimum above twenty,
   daily rate below forty, one-sided book, failed geography refresh, heartbeat
   loss, operator stop or deadline: stop submissions and request cancel-all.
3. Require the acknowledgement, terminal REST orders, zero open orders after
   quiescence, exact scoped positions/trades and collateral reconciliation.
   Unknown cleanup is a failed attempt even if the dead-man later clears it.
   Preserve all evidence. An unresolved attempt or fill blocks another campaign
   attempt; no taker exit, replacement order or automatic retry is authorized.
4. Freeze `P_many`, `P_single` and the journal hash before any earnings read.
   Keep every session and report all three permitted reward days. A short,
   incomplete, changed-terms or rehearsal record cannot prove a paid epoch.

## Update when

Rewrite this draft when the owner ratifies or changes the treatment, or the
implementation's exact grant/session contract changes. It is never authority.
