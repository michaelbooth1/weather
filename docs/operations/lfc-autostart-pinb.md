# Pin B campaign and owner migration

This document owns the owner-approved Pin B policy and takeover of an existing
Pin A account. Read it for `lfc_campaign_policy_v0.4`; the ordinary execution,
money, STOP, evidence and recovery contracts remain in [LFC autostart](lfc-autostart.md).
Code qualification and an immutable final pin precede every owner command here.
Agents never register, enable, run a task, create STOP or touch the live root.

## Policy

The new schema keeps older policy snapshots readable. Its default start window
is 09:00–09:15 Toronto, its fixed trading end is 18:45 and its maximum duration
is 35,100 seconds. A late go shortens the session and never moves that end.
Every session still ends before the existing 23:50Z hard stop. The wrapper
binds the policy bytes and latest possible end plus cleanup; its task has an
11-hour containment limit. The existing GTD and cancellation proof semantics
are unchanged. All twelve captured built-ins remain on the same local date
from 09:00 through 18:45 Toronto during the approved campaign dates, so their
selected T+1 events remain T+1 throughout. Per-order horizon checks remain.

For a wider supported start window, the effective end is also bounded by the
earliest tick receiving a full wrapper envelope plus eleven hours, less thirty
minutes for cleanup. Both Python admission and PowerShell use that bound. For
07:00–09:00 it is 17:25; the default window still ends at 18:45. Earlier ticks
receive the short fallback and cannot admit against an insufficient envelope.
Actual session ends and GTD timestamps use the effective end.
The native creation time of the outer windowless task action also bounds the
wrapper deadline at eleven elapsed hours. Slow release/startup I/O cannot move
that deadline forward. A launch lacking the full cleanup margin defers before
the date is claimed. Seal/register only the final qualified bytes.

Only this schema uses 40 submits and 16 requotes per band. Exhaustion ends that
band; every other band keeps its own budget. The reference/F0/N1 constants and
older schema budgets remain 10 and 4. Ledger-bound start metadata carries the
new private-evidence limit, including every request/ACK through number 40.
The result-file allowance derives from those ledger-bound limits: seven root
files plus five originals and two files per allowed submit for each band.
Twelve bands at forty submits permit at most 1,027 files, including the go
packet. Extra files still refuse; retained ten-submit bands retain their bound.

| Field | Pin B contract |
| --- | --- |
| `learning_dates` | 2026-11-09 through 2026-11-22; the separately pinned Monday authority is unchanged |
| `transition_no_entry_date` | null; Nov 16 is an ordinary entry date |
| `confirmation_dates` | 2026-11-23 through 2026-12-22 |
| `nominal_confirmation_dates` | 30; actual claims and evidence remain separate |
| `freeze_deadline_toronto` | Nov 22 at 18:00; the existing capture window opens at 17:55 |
| `max_session_seconds` | 300–35,100, with the fixed end and UTC hard stop dominating |
| `max_submits_per_band`, `max_requotes_per_band` | 40 and 16 |
| `learning_leg_arms` | One or both of `paired`, `cheap`; default both |
| `confirmation_leg_arm` | One supported arm; default `paired` |

The leg arm is a deterministic hash of Toronto date and market, with a salt
independent of the existing 0.015/0.025 distance arm. The cheap arm uses the
existing CHEAP token-selection contract: select the cheaper leg at the band's
selection snapshot, retain that selected side for the band-day and reserve
only its quote cost. The assignment and actual selected `trade_legs` are bound
into the plan, band journal, ledger intents and outcome. A quote-side change
is never inferred from a reward payment. Confirmation uses one configured leg
arm and one offset; economic edits require a new policy revision and apply
only to an unclaimed session.

The disabled Pin B example uses a 30 pUSD daily filled-basis cap per band. This
is an already supported policy value. The 15.80 order, 19.60 resting band and
300 sleeve caps, spendable-cash check and native accounting rail are unchanged.
Money proof still precedes every fill continuation. Rewards/rebates contribute
zero to refill without the already required campaign-only attribution proof.
The December success look and actual-cash verdict are unchanged.

## Operational observations and temporary depth pauses

The coordinator shares one immutable geoblock pass/fail receipt across bands.
It reads at most once per thirty seconds, including failed attempts. Every band
uses the receipt's original collection clock and its existing freshness budget;
reusing it never refreshes that clock. A successful new read is fresh even after
a delayed band turn. A nonpassing receipt ends the session through normal cleanup.

For breadth bands, `thin_book_depth` cancels the band's orders and proves them
terminal before waiting. The same condition and selected arm are screened on a
fresh book every minute. A passing screen permits the ordinary guarded submit
path only after fresh account proof; fixed end, STOP, freshness, cash, caps and
consumed submit/requote budgets still apply. A fill racing cancellation retains
the existing fill proof and cooldown. No failed screen permits a post.

`weather.market.lfc_f2_post_books.POST_RETIREMENT_RECORDING` controls optional
market-only recording without a policy field. After a fill or band retirement,
one independent bounded worker reads both public token books each minute into
`band-N/post_books.jsonl`, retaining collection clocks and typed failures. Each
trigger extends coverage to the earlier of one hour later and the fixed end.
Session end stops the worker without joining an outstanding GET. These optional
books never gate quoting, cleanup or money proof. The owner's waiver permits
these two own-band public books on all campaign dates.
Optional write failures use the worker's own `post_books_errors.jsonl` and a
bounded `post_book_recording_failure` terminal field; the worker never locks
an account or heartbeat journal.

`weather.market.lfc_own_trades` projects stream and REST executions by trade ID
and own order ID. The band's terminal `own_trade_projection` contains one current
record per identity, with provisional/final state and bounded provenance. `fill`
rows contain projection updates; an order-only signal awaiting execution details
is `fill_pending`. Original order/event/REST evidence remains in the journal.
Reconciliation preserves the existing non-FAILED trade rule, and terminal order
proof still determines booked cost and reserve release. Missing legacy trade IDs
are explicitly labelled as content identities rather than venue identities.

Scoring summaries require the selected legs, including a single cheap leg. The
per-order minute observations remain. Daily cap refusals retain filled, resting,
replaced-own, proposed, cap and available headroom in collateral native units;
the prospective gross admission calculation is unchanged.

## Two recorded reward views

Daily economics, immutable economics supplements and final decision-page inputs
carry both `strict_attributable` and `campaign_estimate`. Strict recognition and
the existing capital attribution rule remain unchanged: unproved income
contributes zero. The estimate never enters capital, headroom or refill.

The estimate records venue earnings for each UTC condition-day on which the
campaign acknowledged a quote, once across attempts and legs. It retains native
asset units, the earned date, accrual identity, source hash and actual collection
time. Account-wide earnings snapshots update every quoted condition they contain,
including retired bands. `asset_estimates` keeps assets separate; a single-asset
summary names that asset, and a multiple-asset observation has no combined native
amount. `estimated_pusd_native` is present only when pUSD earnings were actually
observed. Neither an asset USD rate nor nominal parity converts USDC.e into pUSD.
Same-day observations and independently collected D+1/D+2 receipts remain
separate; the latest observed estimate is selected without summing passes or
allocating an entire condition-day independently to each attempt.
Missing earnings remain missing, while an observed zero remains zero.

An otherwise valid D+1/D+2 wire walk that omits an asset can support an estimate
for its observed asset. Its incomplete strict receipt remains incomplete; the
estimate replays request/response pairing, pagination, account, date, amounts
and provenance before accepting those rows. Failed or forged partial walks
contribute no estimate. Account-state `reward-context/` retains compact observed
owner touches; `reward-projections/` caches replay of older session journals by
their immutable source hash. New terminal predictions carry their estimates.

Any observed noncampaign own order or trade touching that condition-day flags
the estimate. Existing account reads and validated own-stream events supply this
context without another venue read. Open-order snapshots and trade history
cannot prove complete cancelled order history, so absence of observed
contamination never proves clean exclusive
attribution. Payment candidates retain their own IDs, transaction hashes and
payment times. Their earned-date link remains unverified; an earning-date label
or amount match never turns an accrual into paid income.

## Preserving the existing account

An upgrade keeps the same active campaign pathname, maker, ledger genesis,
account-state ID, host and principal. It never enrolls a replacement account,
rebuilds a capital bridge, clears an incident, replays old activity as new, or
releases consumed dates. Existing closures and their intents/anchors retain
their original bytes. An unknown placement continues to block admission until
the existing explicit owner recovery; an evidence fault keeps its own recovery.

Pin A's `policies/freeze.json` and anchor remain immutable. Pin B uses the same
capture routine and event type for its separate `policies/freeze-pinb.json`
epoch. Both originals are validated; a new epoch cannot hide loss of the old.
There is no new task, signature, ARM receipt or validation-day requirement.

If Pin A already sealed on Nov 16, Pin B remains installable and trading can
continue. Its interim learning entries are labelled `successor_learning`.
Its own timely Nov 22 capture can establish the Nov 23 confirmation family;
the retained Pin A confirmation claims are never pooled into that family.
A missing/late Pin B seal leaves successor-learning evidence rather than
manufacturing a confirmation PASS. Neither seal resets campaign economics.
The capture remains a healthy-tick operation, not a second concurrent task.
If the Nov 22 session is still running at 17:55, the first healthy tick after
its normal cleanup captures within the existing overnight window. The receipt
records that actual time; it is never backdated to 17:55.

## Owner takeover

The master supplies the final immutable Pin B worktree and successful pregate
receipt before takeover. Budget roughly five to ten minutes after the prior
session has completed normal cleanup/postchecks; do not force that time target
by clearing evidence, latches or work locks. Keep the prior release and source.

1. Disable future ticks of `WeatherLFCCampaign`. This does not stop a running
   session. Wait for its ordinary end; the upgrade refuses an enabled, queued
   or running predecessor.
2. From Pin A, run read-only status and require a clean result. Resolve pending
   money/evidence using existing owner commands; never reset the root.
3. From the qualified Pin B checkout, prepare a create-only disabled candidate:
   `python -m weather.market.lfc_f2_pinb --upgrade-from '<absolute-campaign.json>' --output '<absolute-candidate.json>'`.
   Review the carried fields and approved Pin B changes, then atomically replace
   the one active campaign file while preserving a backup.
4. Run the existing owner registrar with `-Action Upgrade`, the new release
   filename and `-PreviousReleasePath` pointing to the old release. Supply the
   ordinary qualified head/interpreter/pregate parameters. It rechecks the old
   disabled task definition and both account identities before replacing only
   that task's action. The new task remains disabled; the old release is kept.
5. Verify the new task/release, edit `enabled` to true in the one campaign file,
   then enable through the same registrar. No manual task start is required.

Never run old Pin A code against a root after it has acquired Pin B-only
snapshots. Retaining older snapshots is supported by Pin B; an older binary
cannot interpret a later schema. Revisions of supported fields use the current
compatible code and the existing next-unclaimed-session rule.

## Update when

Update with changes to Pin B policy fields, quote-side definitions, capture
epochs, account-preserving migration or owner registrar arguments.
