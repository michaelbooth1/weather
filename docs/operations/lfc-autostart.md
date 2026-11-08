# LFC owner-activated campaign

Status: implementation contract; activation requires a reviewed, pre-gated pin
and the owner's one-time registration and enablement. Read when preparing,
operating or reviewing the scheduled LFC lane. This guide grants no agent
authority to register, enable, run, cancel or sign.

## One task and one policy file

The owner runs `scripts/ops/register_lfc_campaign_task.ps1` with `-Action
Register`, then `Verify`, edits the campaign file, then uses `Enable`. Register
requires the reviewed head, qualified pregate receipt and existing interpreter;
it creates a disabled Interactive/Limited task and reads its definition back.
This credential-dependent owner task is an explicit exception to the ordinary
S4U operations convention. There is no signature, ARM receipt, mandatory
owner-started validation day, or per-policy-edit pregate.

The task uses the release-bound `pythonw.exe` and repository windowless launcher.
It creates no console, waits for the PowerShell wrapper, and returns that wrapper's
exit code. The wrapper is assigned suspended to a kill-on-close Job before it
can execute; the wrapper also contains the campaign child. The Interactive/Limited
owner session remains available for toasts. Registration seals the interpreter
and launcher hashes; a changed binding refuses.
Environment/binding refusals before the child starts write one sanitized line
to `status/control/launcher-refusals-YYYY-MM-DD.jsonl`. It contains reason codes
and variable names only, with no values, paths or exception text. The launcher
still exits nonzero and never starts the wrapper after a refusal.

A crash between a timely freeze receipt and its ledger anchor can complete on
the next healthy tick within the original capture window. The original bytes
and capture time stay intact. A matching partial owner-close receipt can likewise
complete after explicit owner confirmation and a fresh money proof; it accepts
only that occurrence and its unchanged artifact manifest.

Final confirmation totals use the retained confirmation claims and frozen economic
identity, including revision-only edits. A successor economic policy remains
separate even after reverting its fields. Session redemption cash sums proved
session-lot payout allocations; any owner holdings in the same transaction stay
outside that session's measured cash. Unknown allocations remain unknown.

Submission uncertainty comes from unacknowledged durable intents or a mismatch
between POST counters and known order IDs. Missing private evidence stays an
evidence fault; it never invents an ambiguous placement or becomes a PASS.
A proved pre-POST exit retires its band through ordinary cleanup. Its exact
request and any written intent packet remain bound in the abort journal row;
an actual POST or partial/unreadable ledger write cannot use this exemption.
An unexplained peer cash shortfall waits at most 120 seconds, with polls at
least five seconds apart and no submit-budget consumption. It then retires
the waiting band through ordinary cleanup; it never retries an uncertain POST.

The checked-in [F2 example](../examples/lfc-campaign.example.json) and
[alternate filename](../examples/campaign.proposed.json) are disabled runtime
policies. The breadth v0.3 rules below govern those files. The
[K2 reference](../examples/lfc-campaign.k2-reference.json) preserves v0.2. The separate
[v0.1 reference](../examples/lfc-campaign.reference.json) retains the original
one-band contract in the following table; those reference restrictions do not
override F2. Parsing a file never activates it.

## Reference v0.1 protocol

| Fields | Qualified edits |
| --- | --- |
| `budget_pusd`, `per_order_cap`, `per_band_cap` | Positive reductions within the immutable source ceilings; budget cannot be below committed L. |
| `shares_per_leg`, `k_max` | Existing fixed size and one band only. Expanded terms refuse explicitly. No replenishment. |
| `per_date_cap` | Prospective new money committed by session-start local date, including earlier sessions. It is not an actual settlement-day loss measurement. |
| `daily_loss_cap`, `realised_stop` | Optional conservative prospective full-cost bounds, including carried/unknown inventory and the proposed full band reserve. No payout, profit, reward or rebate credit. Unknown settlement is full loss. |
| `max_sessions`, `last_start_local_date` | Reductions within the qualified source limits; previous counted sessions still count. |
| Entry UTC windows and `duration_seconds` | Finite half-open windows and bounded duration inside the parser's qualified range (300 seconds minimum). The complete duration must fit before the UTC hard stop. |
| `fill_retires`, `unknown_settlement` | Own band and full loss respectively; the one-band controller ends on a fill. |
| `sidecar` | Only null/disabled is qualified. Enabling refuses before claim: whole-session interval coverage needs a reviewed adapter release. |
| `policy_name`, `policy_revision` | Bound into each attempt's receipts, ledger rows, private journal and outcome; economic changes under one name require an increased revision. |
| `local_event_dte` | A nonempty sorted subset of the reference horizons. Selection and every placement/requote use it; resting orders pull through normal cleanup at a disallowed market-local boundary. |
| `band_limit_session`, `band_limit_concurrent`, `bands_per_event` | One each in this qualified controller, matching `k_max`. Unsupported expansion refuses. |
| `start_window_toronto`, `trading_end_toronto` | Optional Toronto clock window must match each UTC entry. Full effective duration must fit by the absolute end even at the latest allowed start; incompatible windows refuse, never clip a late session. |
| `max_sessions_per_day`, `concurrent_sessions` | One each; stable account/date claims and the account guard enforce both. |
| `max_session_seconds` | Global maximum within the same qualified duration range, combined with each entry's duration and optional fixed end; the effective end is recorded. |
| `learning_dates`, `confirmation_dates` | Empty, or an inclusive two-date range. Configured ranges must be disjoint, within qualification, and cover the entry. Receipts label the lane; this grants no scientific confirmation claim. |
| `capital_mode` | `committed_cost_no_recycling` only. Principal recycling and `fixed_sleeve_redeemed_principal_only` refuse. |

The immutable release records the parameter-support table and refuses if it
differs from this code's enforced contract. An unsupported expansion is a precise refusal, never a partial implementation
or implicit approval. Supported edits take effect for the next attempt; an
admitted attempt uses its immutable snapshot. Changing campaign ID/revision or
lowering a count does not reset account history. Enabling/disabling the campaign
file and actual task are independent owner controls. A disabled task does not
prove cancellation of an already running session.
The running process reads task enablement at most once per minute, with a
five-second read timeout. Policy disablement and the owner-only STOP checkpoints
remain independent of that cached Scheduler observation.

The minimum leaves 120 seconds for opening reads before the controller's existing
180-second pre-POST horizon. The boundary is tested with nonzero opening latency;
it is not a promise to place through an outage. Unsupported short durations refuse
at policy parsing and the final preclaim predicate, before any claim or skip is
written. This reference protocol requires the full duration to fit. F2 explicitly
shortens a late session at its fixed end instead.

## F2 breadth v0.3 fields

The disabled example uses every captured built-in registry city. A configured
subset is supported. Selection admits one band per city and excludes the whole
event when the original inventory baseline holds any of its conditions. Event
T+1 uses each market's own zone; the session calendar and hard end use Toronto.
Every placement, requote and resting-order check still enforces local T+1.

| Fields | Enforcement |
| --- | --- |
| `market_ids`, `band_limit_session`, `band_limit_concurrent` | Captured built-in cities only; matching concurrent/session limits within that universe. One band per city/day and one account/date claim. No new city replaces an unavailable or retired city within the session. |
| `on_first_band_fill` | The breadth value cancels the affected band's remaining orders, proves every original intent/ACK and terminal quantity, then reconciles fresh whole-account trades, inventory and native cash before continuation. The v0.2 retirement value remains supported. |
| `per_band_daily_filled_cap_pusd` | Gross UTC-day filled cost basis plus all same-city resting reserve and proposed new reserve must fit. The single durable intent gate enforces it, including later policy revisions. Redemptions and profits never reduce this gross filled basis. |
| `fill_cooldown_seconds` | Integer 60–3600 seconds; default 60. Wait after inventory is first proved, then obtain another fresh proof before quoting. During the wait, other bands, shared heartbeat, STOP and the fixed end continue normally. Unknown ACKs, quantities or statuses never authorize continuation. |
| `learning_quote_offsets_pusd` | Deterministic SHA-256 of Toronto date and market assigns a band-day arm during the learning dates only. The plan, band receipts, original intent and outcome retain that arm. Retries cannot change it. Prices still round outward to the venue tick. |
| `quote_offset_pusd` | Single offset from the confirmation freeze onward. The owner/master's field value governs; a later economic edit requires a new revision and is labelled successor learning. Learning arms never restart after the learning window. |

The existing per-order, resting-band and native sleeve caps dominate all these
fields. Per-band submit/requote limits continue across fill cycles; continuation
does not reset them. A proof while another band rests is separate from final
cleanup: only exactly bound LIVE orders with zero matched quantity may remain,
and final completion still requires an empty account and complete terminal proof.
Private manifests retain every band packet and original file; missing evidence
keeps the same occurrence-specific owner recovery rules. The previous schemas
remain readable, with their original retirement and band-count restrictions.

Breadth setup constructs all clients and starts all exact-pair streams before
opening band sessions. It then obtains a fresh whole-account/native-cash proof
inside the original start window. Known redemptions reconcile against existing
lots and the original inventory anchor; neither the anchor nor the prepared
receipt is replaced. Transient read gaps may retry within that window. A missed
window creates no placement intent. The fresh `go_account.json` is hashed into
the session outcome and retained result; missing or changed evidence follows
the same occurrence-specific recovery rules as other originals. Band/day cost
lookups use an index rebuilt from the verified ledger during replay.

## F2 v0.2 fields and admission

The example owns exact defaults; `lfc_f2_policy` and the release's support table
own supported values. Unknown fields and unsupported values refuse explicitly.

| Fields | Enforcement |
| --- | --- |
| Markets, native-date horizons and selection | F2 fixes `local_event_dte` to `[1]` (T+1 only); other sets refuse. Use the bound F0 reference with explicit campaign share, reward-rate and depth fields; retain the midpoint, spread, leg and money limits. Pick the highest planning reward per city, tie by condition ID; use that same rank when cash admits fewer bands. An absent city stays idle. |
| Band/event limits | At most two concurrent bands, one event per city, no replacement. One cooperative process owns the account/date claim and all workload slots. Each band retains its own submit/requote limits. |
| `tokens`, `order_side`, `shares_per_leg` | Paired YES+NO, YES, NO, or CHEAP (lower quoted probability; YES wins a tie). BUY only at the approved fixed size; no reward-minimum scaling. |
| Offset, distance window, price/share ranges and caps | Applied to proposals and placement/requote checks, with final raw-POST and signed-order checks. Monetary caps dominate allowed prices. |
| `share_many_range`, `min_reward_rate`, `min_book_depth` | Share bounds may span zero through one, disabling that screen. The rate floor requires a positive reward at zero and is inclusive above zero. Depth must cover at least the selected leg size. The same fields govern discovery, pre-go, fresh placement and requote reads; learning edits require a higher policy revision and cannot be pooled into the frozen confirmation lane. |
| Fill, replacement and inventory-exit fields | First fill cancels that band's remaining orders and retires it. Other bands continue. Hold inventory for actual venue payout/redemption; own cancel-race fills. |
| Start/end, duration and calendar fields | Derive finite Toronto entries, excluding transition and separately bound Monday F0. Late go shortens exposure, retaining the fixed end. No catch-up or second claim. |
| Funding, capital mode, top-ups and reinvestment | Native-unit sleeve in the existing account ledger. Actual redemption releases at most lot basis. The reconciled bridge includes legacy L/inventory; no config/date/deposit reset. |
| Loss-stop fields | Null. Total sleeve, prospective exposure and actual spendable principal cash are the monetary gates; no additional daily or smaller cumulative stop. |
| Policy identity/revision | Snapshot per attempt. Economic changes require a higher revision and apply only at the next unclaimed session, including changes of name. |
| Evidence and economic-contract fields | Label cash population, final look, strict positive-cash hurdle and inference contract. A prediction is never income or a promotion decision. |
| Sidecar | Null/disabled only; enabled capability still refuses until interval coverage is qualified. |

The ledger advances its protocol before capital events. Genesis and historical
L remain intact. F2 refuses the old L post gate after the bridge. In collateral
native units its disjoint lots require:

`realized principal loss + unrecovered basis + resting reserve + new reserve + paid/reserved costs <= funding ceiling`.

Fresh spendable cash is an independent gate. Unknown payout returns no principal.
Cancellation frees only proved unfilled reserve. Redemption returns at most
released basis; profit, incentives and later deposits are segregated. Incoming
unattributed cash is quarantined; an unexplained debit refuses another post.
A later known payout appends a scoped resolution, retaining its original unknown
read. Unknown outgoing costs refuse admission.

The initial bridge refuses unresolved outgoing payments and incoming cash without
a bounded label. An unresolved incoming label is rounded upward and quarantined
outside principal; it returns no basis and does not block the bridge. Later discovery of an older credit never
adds it to the bridge balance again: it reclassifies only the bridge's original
unattributed quarantine, and reduces the effective allocation for any remainder.
Known external funds and later deposits cannot replace that principal. The
original bridge receipt is preserved. An unresolved older credit remains quarantined until its native cash is known;
no payout is guessed and the label never funds new risk.

Withdrawals consume set-aside external cash, profit and incentives, in that order,
before charging any post-bridge excess to principal. Pre-bridge withdrawals are
already reflected in the opening balance and never become campaign costs.
Allocation follows cash-flow time, so a
later deposit cannot cover an earlier withdrawal whose receipt resolves late.
An outgoing flow is charged before a same-second incoming flow when the
whole-second timestamps cannot prove their order.
Production cost booking comes only from evidenced outgoing transfers; there is
no production `capital_cost` writer. The unchanged maker-fee guard requires a
zero maker charge. An unrecorded fee debit instead fails the fresh balance gate
as `capital_cash_changed`; it is not silently booked as a zero cost.

Every start in a supported clock window must fit before the existing 23:50 UTC
cutoff within one UTC date. Otherwise policy parsing refuses before any date can
be claimed or skipped. Market-local horizon pulls remain independent of this
UTC evidence boundary, including Denver midnight inside a supported session.

The bridge checks bounded activity, account fills and exact inventory against
the original baseline. It verifies Polygon identity and the collateral's actual
decimals, then matches retained ERC-20 receipts to native wallet flows. Data API
cash labels are candidates; a mismatched or unallocated payout returns no
principal. There is no assumed USD conversion. See the
[v2 schema](https://data-api.polymarket.com/v2/openapi.json) and
[ERC-20 transfer contract](https://eips.ethereum.org/EIPS/eip-20).
When a transaction has more than one incoming activity row for this maker,
cash stays UNKNOWN unless retained per-position payout evidence binds the whole
redemption bundle. The total alone cannot prove each condition's payout.
Unproved cost bases remain charged; their incoming labels stay quarantined.
There is no redemption, sale, top-up or transfer capability in this code.

Outcomes separate PLANNING scenarios from MEASURED fills, fees, carried basis
and redemption cash. Accrual and paid rewards are distinct; missing earned-scope
or payment linkage stays unknown, never zero or predicted income. Rebates remain
flagged separately from loss.

The freeze captures at the first healthy tick from November 16 17:55 through
November 17 08:55 Toronto, before pending-postcheck and incident early returns.
This explicitly amends the earlier nominal 18:00 deadline for this lane. The
receipt keeps its actual timestamp. A missing or late freeze emits an evidence
gap notice, and later sessions remain successor learning rather than claiming
confirmation. Policy edits cannot backdate or replace a freeze receipt.

## Claims, proof and recovery

Enrollment is owner-run after the frozen F0 session, against the existing fixed
ledger and its original genesis. The explicit ledger protocol event advances
enrolled writes so old clients refuse the new history. It never rewrites old
rows, creates a fresh money ledger or changes the frozen worktree. Emergency
account-wide `weather.market.re1_attended_cli cancel-only` remains available
through the existing owner procedure.

The state directory is account scoped under `C:\t\pilot\account-state`, separate
from the editable policy. A Windows account mutex protects enrolled ledger
writers. Durable account/date claims precede the order-capable invocation;
their hashes and incident hashes are bound into the ledger. Missing enrolled
state, a second writer, an unresolved claim or a corrupt continuity proof
refuses. Config changes, ordinary reboot and reinstall cannot reset claims.
Whole-trusted-state rollback is unsupported: keep the task disabled during a
restore and perform owner-led continuity review before resuming.

Every reachable post-claim exit persists a result in a finally block. After a
hard exit, a durable claim with no leg intents automatically closes MISSED with
research gaps, since that attempt could not have submitted an order. Its date
stays consumed. A claim with intents cannot use this automatic closure.

The dispatcher finishes pending money postchecks and returns before considering
a fresh entry. Known acknowledged attempts may finish read-only postchecks on
later ticks after transient transport failure. It never adopts an unknown order,
closes a crash as success or clears an ambiguous placement. Such an incident is
sticky and consumes the date. The explicit `owner-recover` command requires an
owner terminal, incident-hash confirmation and fresh complete money proof; it
cannot repair unknown order identities or invent missing inventory evidence.
An owner-reviewed repair must resolve those facts first. Original flags remain.
Every account observation and failed read is retained separately, including an
early quantity mismatch followed by a later matching read during propagation.

Money proof requires complete bounded account reads, valid terminal identities
and matched quantities, per-order fills, zero open orders and every token's
quantity against the original immutable inventory anchor plus verified fills.
A missing holding fails even if aggregate L agrees. Microfills remain inventory;
API absence, including below a visibility floor, does not prove exact zero.
Each account component retains its own UTC read interval; freshness uses the
oldest component, so a fresh report end cannot refresh earlier stale reads.
Unverified sales, redemption or merges are never inferred from prices or marks.

The new `lfc_autostart_v1` protocol explicitly removes the historical T-24
lead-time requirement only for this lane. It first checks the previous accounting
and original inventory anchor, then binds its own fresh baseline/pre-go receipt
to the entry. Later global baseline files cannot override that binding. Existing
manual/F0 gates keep their historical protocol.

For an operational incident whose private evidence is missing, the owner may
run `weather.market.lfc_campaign_cli owner-close --release <release.json>
--release-sha256 <sha256> --incident <occurrence-id>`. One terminal confirmation
names the exact incident hash. Fresh account-wide proof must establish every
acknowledged order's validated terminal quantity, no resting orders and reconciled
inventory/cash. Any unacknowledged intent refuses. This close preserves missing
artifacts as research faults, original receipts and consumed dates; it never
invents a journal or reports research PASS. Only a proved-dead workload marker
may be released. A restored artifact is anchored, and a later loss or change
creates a fresh N1 occurrence requiring another owner decision.

## Availability and containment

Enrollment and every new admission inspect legacy/F0 monetary history. A lost
acknowledgement, adoption, crash closure or retained unknown-submit flag requires
explicit owner recovery even when ordinary reconciliation now lists no orders.
Only the exact intentional S0 exercises named by the existing valid owner
attestation use that qualification contract. Reconcile never clears ambiguity.
If this gate refuses, the owner reviews and repairs the original identities and
containment, then runs `weather.market.lfc_campaign_cli owner-recover-history
--head <qualified-sha> --session <original-session-id>` in the qualified pin's
interpreter after frozen F0. This terminal-confirmed, GET-only operation takes
account/all-slot exclusion, proves current quantities and no resting orders,
and appends a hash-bound recovery without changing failed flags or used dates.
It neither registers nor enables a task. Missing recovery evidence refuses.
The enrollment identity also anchors retained legacy private files. Normal F0
history must have a complete chained private proof; untyped failed legacy proof
needs explicit owner review rather than a guessed ancillary exemption. Recovery
binds the original journal/intent evidence and never synthesizes a lost journal.
Missing or changed legacy originals after enrollment record a sticky evidence
fault, including if the ledger's old unknown-submit flag was false.

One coordinator thread owns the account guard, exclusive workload barrier,
legacy heavy slot and all newer compatibility slots through cleanup and owned
sidecar teardown. It refuses abandoned/poisoned ownership without recovery.
The campaign owns `status/campaign-work.lock`, separate from the agents' manual
`C:\t\codex\HOLD_HEAVY`. A pre-existing manual hold is honored and never owned
or removed by the campaign; agents never create it on entry dates. Only the
campaign's own marker can be released, and only
after proved child containment. A busy job or transient pre-go read defers with
bounded back-off inside the original start window. No claim or order is made
before admission; no start occurs at or after the window end. A missed window
is recorded without catch-up. A claimed attempt is never restarted.

The market-local horizon is checked against the current clock before every
placement/requote, again at the raw-POST callback after signing/metadata reads,
and during quoting. A fresh-looking table's creation time
cannot authorize a T+0 order. A disallowed native-date transition retires the
event through normal cancel/verify cleanup; `horizon_retirement` remains in the
outcome even if a cancel-race fill also changes the session's end reason. The
reference controller has one event. F2 retires only that band without replacement;
unaffected bands continue.
Toronto and Denver midnight transitions are tested separately. A planned end
may cross such a boundary because that tested pull is in place.

Before work starts, the lane also publishes its own crash-persistent schema at
the legacy global poison location while holding every slot. Older helpers refuse
that schema instead of adopting it as an offline/Stage-0 lease. Normal contained
completion removes only the matching marker and HOLD. A crash/uncertain teardown
retains them. `weather.market.lfc_campaign_cli owner-clear-workload` is an explicit
owner-terminal operation: it requires the incident's bound account/state, hash
confirmation, all-slot exclusion and proof that the recorded process is gone
(either a different boot ID or exact process-creation identity). It
removes only that workload marker and its hash-bound HOLD; monetary incidents
and date claims remain for separate owner-led recovery. Automatic admission and
reconciliation never invoke it.

The task action launches PowerShell with its documented `-WindowStyle Hidden`;
Interactive/Limited owner-session binding remains
in place for desktop toasts. The task is finite, `IgnoreNew`, no wake, no catch-up, no restart-on-failure,
no idle dependency, no demand start, InteractiveToken/LeastPrivilege, with a
bounded execution limit. It needs the owner logged on and the PC awake and
connected. It starts only on suitable power, but entering battery mode does not
hard-kill a live session. The wrapper contains its child tree in a kill-on-close
Job. Scheduler termination is process containment, never cancellation proof.
These settings follow [Microsoft's task settings contract](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset).
Its five-minute timer has floating local Scheduler boundaries; those ticks never
authorize a start outside the campaign's explicit UTC window and Toronto date.

To request normal cleanup, the OWNER alone creates `C:\t\pilot\STOP`. Agents
never create it: its existence causes real cancellation. A separate observation
thread checks it during blocking reads; normal session checkpoints perform the
existing cancel-known-IDs, account-wide cancel-all and verification. The owner
removes it only after reviewing cleanup. No agent edits the armed pin or owner
control/state files. Clock discontinuity or a long live-loop gap records an
incident and ends through cleanup; the absolute and monotonic ends remain.

Orders retain the original signed GTD timestamp of session end plus 60 seconds.
[Polymarket's GTD contract](https://docs.polymarket.com/trading/place-orders#limit-orders)
applies a one-minute security threshold, so effective venue expiry is the session
end; the documented raw timestamp must also be at least three minutes ahead.
The added minute is not permission to quote beyond the stop. Expiry/deadman is a
venue backstop, never local cancellation proof. Cleanup journals requests and
acknowledgements separately; full outcomes expose `cancellation_requested` and
`cancellation_proven` separately. An outage retains reserves and non-success
until complete terminal/account evidence proves cleanup, even after time passes.

## Outcomes and optional public capture

Full session outcomes, monetary facts, original proof flags and read hashes stay
in owner/runtime evidence under the account state directory. The embargo-safe
agent projection is `C:\t\pilot\status\control`: immutable phase/progress,
freshness, incident/pending flags, safe reason codes and hashes only. It contains
no prices, fills, tokens, events, wallet or credential paths. RUNNING observations
are published at least every minute while the loop progresses. A stale last
observation is lost progress, not proof of a clean exit.

The disabled [F2 example](../examples/lfc-campaign.example.json) and
[proposal copy](../examples/campaign.proposed.json) carry the B036 owner-approved
v0.2 terms. The [v0.1 reference](../examples/lfc-campaign.reference.json) retains
the compatibility contract. Shipping examples does not register or enable a task.
Unsupported values refuse explicitly; original history is never reset or relabeled.

The first healthy tick in the capture window above seals the economic parameters
automatically. The immutable freeze records its actual observation time and hash.
A missed window is late, never backdated;
trading may continue as learning. A changed economic revision after that seal
abandons confirmation: its claimed dates and all subsequent dates are successor
learning, even if parameters later revert. No extra owner action or pregate is
needed for supported edits. Missing freeze originals take the same sticky N1
artifact-fault path as missing private session evidence.

F2 outcomes distinguish PLANNING reward scenarios from MEASURED fills, fees,
carried cost basis, actual native redemptions and incentives. Unknown fees or
payments remain null. Account incentive credits are shown separately; a payment
without a verified earned-session link is never booked as session income.
Read-only hourly follow-up records independent D+1/D+2 passes and venue settlement,
including while an incident or pending attempt blocks further trading. It never
clears an incident. A retained marker permits these reads only after its exact
account/state owner is proved gone; the marker remains and no live lease is
granted. Unavailable exclusion is retried on a later tick. Public calls are capped at two per second and the
pass has a bounded read budget. Failures remain explicit gaps. It never redeems
holdings, places orders or consumes another date. Redemption remains an owner or
separately authorized facility action; until proved, its principal stays charged.
Later facts create immutable `status/<session>.e-<hash>.json` economics supplements;
the original outcome remains unchanged. The control projection remains free of
economic facts for researchers who must stay blind. The default final-look helper
requires complete measured cash and the registered family closure; positive cash
alone is not qualified edge, and missing evidence gives INCONCLUSIVE.


The optional T017 capability is explicitly refused in this release, including
at the adapter constructor. A manifest alone cannot enable it. Qualification
must bind capture to the actual private-session interval and retain cumulative
gaps/errors; current readiness cannot establish continuous historical coverage.
The retained diagnostic reader preserves historical gap counts and errors and
checks physical final chunks, but never labels that as whole-session completeness.
A future adapter must also preserve the hard 2 rps budget and contained teardown.
Public gaps remain separate from private money proof; no private session restarts
for capture recovery. Null/disabled capture is supported without a public claim.

`money_accounting_complete`, `cleanup_proven` and `unknown_submit` are distinct
from `research_evidence_complete` and public coverage. A missed scoring read or
optional sidecar gap remains visible without permanently stranding a money-clean
account. An unexplained missing core proof remains unknown and blocks starts.

Private completion requires the chained session journal, matching submit intent
and ACK files, terminal identities/quantities and prediction/end bindings. Each
result has its own ledger hash anchor. Pending finalization reopens and hashes
these originals; later admissions repeat the check for closed attempts. Process-local
proof caching is bound to file identity, size, timestamps and the native NTFS
per-file update sequence (USN). Timestamps alone can coalesce rapid edits. If
the read-only USN query is unavailable, full content/proof reads replace caching;
the code never creates or changes a volume journal. See the
[Microsoft file-USN contract](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_read_file_usn_data).
Deletion, replacement or a same-size edit with restored mtime invalidates the cache.
A fresh process validates the full ledger
chain and retained proofs again. Ledger appends still hash the complete on-disk
history before every write; money/account reads are never cached. Missing,
changed or unclassified core evidence records a sticky evidence fault. A generic
exception type or a scoring gap cannot excuse it. The automatic lane retains
explicit typed fault codes: supported scoring/public gaps affect research, while
acknowledged terminal GET outages remain pending until fresh complete accounting
proves them. Original flags remain unchanged. Owner recovery also requires the
retained originals and never reconstructs a missing journal from an empty account.
An explicit owner recovery may close a fully retained but originally failed or
unknown result after the owner has repaired its identities and current account
proof is complete. Its separately hashed owner receipt binds every original,
the resolved identities and fresh account proof. Original failure flags remain
unchanged. Automatic closeout cannot select this authority or create that receipt;
later admission still revalidates originals and the owner decision. This
`owner-recover` path refuses missing or changed originals. The separate
`owner-close` path above acknowledges the evidence fault with research incomplete
and independently proves money; it does not waive that fault into a PASS.
Each detected fault occurrence binds its source attempt, affected artifact and a
ledger-backed detection sequence. Repeated observations deduplicate only while
that occurrence is open. A later loss, including after recovery or reboot, creates
a new immutable incident and needs its own owner decision. Prior incident and
closure receipts and consumed dates remain intact; an old closure never clears a
future occurrence or a different artifact. Final start gates check active incidents.

Native redemption allocation is position scoped. CTF payout vectors at the
receipt block, ERC-1155 quantities and native pUSD transfers must agree; v2
module/AutoRedeemer events bind each position payout. A collapsed paired API row
can cover both tokens; repeated rows cannot credit the transaction twice. Every
lot retains its own cost ceiling. Unmatched or pre-snapshot reads are quarantined
outside principal. A native transfer without a position allocation returns no
principal. Unknown incoming labels remain segregated, including before the bridge;
unknown outgoing cash or an incoming flow without a bounded label refuses.
The public contract sources are [CTF](https://github.com/gnosis/conditional-tokens-contracts/blob/master/contracts/ConditionalTokens.sol)
and [Polymarket v2](https://github.com/Polymarket/polymarket-v2-external).

A cash or inventory mismatch first defers as propagation pending. A second
mismatch at least 15 minutes after the first latches a monetary incident. A
consistent read clears only this candidate; it never clears an incident, a
claimed date or an ambiguous placement. These observations survive a reboot.

The runtime sends the existing Windows toast and appends a safe one-line record
to `status/notifications.jsonl` on incident, pending cleanup, completion and a
missed/refused start window. Every control record includes
`orders_open_unproven`; it is true for unresolved intents, unclosed placed attempts
or a failed fresh absence proof. Healthy unclaimed idle/deferred records are false.
True is a warning, never a cancellation proof. An
existing incident always projects INCIDENT, including during pending postchecks.
Busy workload admission, retained HOLD/marker state and no qualifying band have
distinct reasons. Repeated observations use the same open incident identity;
only a new fault occurrence receives a new incident identity.
Automatic admission never guesses that a marker is stale or deletes it; the
existing owner recovery requires proved process-exit/boot identity continuity.

Before go, the session volume needs at least the code's 5 GiB free-space floor.
The owner-only STOP checkpoint remains unchanged. A separate watchdog exits the
process after 120 seconds without quoting-loop progress, first
publishing an incident with cancellation unproved. Setup, cleanup and verification
use bounded operations and the wrapper deadline, which is the effective trading
end plus thirty minutes, also bounded by monotonic elapsed time. A malformed or
out-of-window policy gets at most thirty minutes to report refusal. The stall watchdog never kills
a cancellation in flight. Band cleanup keeps the account heartbeat ticking and
resynchronizes the clock-gap guard without waiving wall/monotonic drift. The account claim and work
markers remain retained; process teardown is not order-cancellation proof.
Each tick appends its exit code and sanitized traceback frames to
`status/campaign-ticks.jsonl`, rotating at 1 MiB and retaining archives. No
exception messages, source text, prices, market IDs or private paths enter it.

Manual or automatic redemption is not manual trading. The owner chooses a
manual redemption cadence or the separately authorized auto-redeem facility;
this task only records their evidence and never triggers redemption. Top up
BEFORE enrolling. Deposits after enrollment stay separate forever and cannot
increase trading principal. The owner's pre-enable check now performs the
read-only bridge and prints ENROLLMENT_FUNDING with the actual `funding_native`.
For the intended fully funded sleeve, confirm `funding_native = 300000000` and
`capital_bridge_complete = true`; a configured ceiling is not proof of funding.

No manual trades, merges or splits on this wallet through 2026-12-31. Any one
halts F2 because the account inventory/cash bridge no longer reconciles; deposits
and withdrawals are fine. Redemption follows the separate rule above.

A retained resolution with an exact zero payout books that lot's remaining basis
as realized loss without requiring a burn. Its unswept physical quantity remains
in account inventory reconciliation and appears separately from carried economic
inventory. A later burn cannot charge the same basis twice. Prices never settle
these lots; a conflicting positive payout refuses.

After the December evidence cutoff, the cleared owner/custodian may create one
read-only snapshot with the qualified interpreter:

```powershell
& '<qualified-python>' -m weather.market.lfc_campaign_cli final-look --release '<release.json>' --release-sha256 '<sha256>' --output '<new-final-cash.json>'
```

The command refuses before the configured cutoff, writes create-only and calls
`final_cash_assessment` at the final-look time. Between noon and 18:00 Toronto it
labels the look not open. Unredeemed winners at cutoff are a separate quantity
and payout-evidence table, never cash; later receipts remain supplements. Known
purchase/redemption cash subtotals are MEASURED and exclude PLANNING predictions.
The current automatic evidence does not prove earned-session links for paid
rewards, all fee/cost attribution, family closure or an independent cutoff cash
bridge. These remain explicit gaps and the snapshot is INCONCLUSIVE; the command's
zero exit means the report was written, not that a scientific PASS was proved.

Retained campaign JSON uses the shared `STATE_JSON_LIMIT` for both writes and
reads, including the private go packet and public economics supplements. Writers
refuse an oversized record before publishing it. The bounded retention cache
returns larger valid records without copying them into its cache; native receipt
bodies remain hash references rather than repeated account snapshots. The
synthetic year-end capacity test covers every cumulative state family with
twelve bands per day, SDK trade rows, paged activity and capital allocations.

A committed owner operational close is idempotent across a crash before its
attempt-close receipt. A later tick or owner retry revalidates the original
decision, terminal identities and retained artifacts, then creates only the
missing receipt. It does not repeat the decision, replace evidence, or waive a
later fault occurrence. Research gaps remain gaps.

Each wrapper launch reads one bounded policy-byte snapshot. Its deadline and
that exact snapshot's SHA256 are passed to the child, which checks them before
claim and again at the live boundary and placement checkpoints. The entire
permitted start window plus cleanup must fit the parent budget. An early tick
crossing into a window, or an edit between parent and child reads, defers without
an incident or a new date claim. A new tick can admit the revised policy. Once
claimed, a session retains its original admitted snapshot; a supported edit is
for the next unclaimed session. The prepared receipt retains the launch envelope.

## Update when

Update with policy support, task/identity contracts, claim/recovery transitions,
money proof, containment, status projection or sidecar integration changes.
