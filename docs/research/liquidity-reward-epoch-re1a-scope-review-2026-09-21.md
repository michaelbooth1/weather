# RE-1A place-and-hold addendum: scope review

**PROPOSAL ONLY; BLOCKED BEFORE ANY ORDER.** This addendum records the scope
cut requested in mission 09-80a. It neither replaces the frozen
[RE-1 pre-registration](https://github.com/michaelbooth1/weather/blob/a14ce80dc0189ddbcd1de1af11111f27e07bfe99/docs/research/liquidity-reward-epoch-preregistration-2026-09-20.md)
nor authorizes a measurement.

Proposed treatment: price once, twenty shares on each of two post-only BUY
legs, at most two submissions, no re-quotes, at most 45 minutes per sealed
attended session. End at the first fill, drift outside the 1–3 cent leave-alone
window or venue reward spread, reward minimum above twenty, rate below forty,
one-sided book, non-eligible/unreadable geography, heartbeat loss, operator
stop or timeout. Several sessions would replace one 360-minute session.

**The verdict table is unchanged.** It requires at least 180 visible two-sided
minutes and caps RE-1 at three sessions. The proposed session ceiling yields
at most 135 minutes across the entire cap. A single session is necessarily
short, and aggregation cannot fix the arithmetic. No implementation may
substitute the selection rule's hypothetical 360-minute prediction for a
prediction accumulated over actual visible minutes.

Consequently no prediction/payout verdict engine or three-band dress rehearsal
is claimed. The owner must define the observation unit and budget in a new
dated treatment before this scope cut can become an executable experiment.
The [decision draft](../operations/stage2-hold-owner-authorization-draft.md)
also records the independent wallet and dead-man timing blockers.
