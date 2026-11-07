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

The checked-in [example](../examples/lfc-campaign.example.json) is disabled.
Its terms remain the existing one-band pilot terms. Every pending money/session
choice is represented by a named field; the parser is the support contract:

| Fields | Qualified edits |
| --- | --- |
| `budget_pusd`, `per_order_cap`, `per_band_cap` | Positive reductions within the immutable source ceilings; budget cannot be below committed L. |
| `shares_per_leg`, `k_max` | Existing fixed size and one band only. Expanded terms refuse explicitly. No replenishment. |
| `per_date_cap` | Prospective new money committed by session-start local date, including earlier sessions. It is not an actual settlement-day loss measurement. |
| `daily_loss_cap`, `realised_stop` | Optional conservative prospective full-cost bounds, including carried/unknown inventory and the proposed full band reserve. No payout, profit, reward or rebate credit. Unknown settlement is full loss. |
| `max_sessions`, `last_start_local_date` | Reductions within the qualified source limits; previous counted sessions still count. |
| Entry UTC windows and `duration_seconds` | Finite half-open windows and bounded duration inside the parser's qualified range. The complete duration must fit before the UTC hard stop. |
| `fill_retires`, `unknown_settlement` | Own band and full loss respectively; the one-band controller ends on a fill. |
| `sidecar` | Optional reviewed T017 manifest; capture failure records a research gap and cannot stop the private live session. |
| `policy_name`, `policy_revision` | Bound into each attempt's receipts, ledger rows, private journal and outcome; economic changes under one name require an increased revision. |
| `local_event_dte` | A nonempty sorted subset of the reference horizons. Selection and every placement/requote use it; resting orders pull through normal cleanup at a disallowed market-local boundary. |
| `band_limit_session`, `band_limit_concurrent`, `bands_per_event` | One each in this qualified controller, matching `k_max`. Unsupported expansion refuses. |
| `start_window_toronto`, `trading_end_toronto` | Optional Toronto clock window must match each UTC entry. Full effective duration must fit by the absolute end even at the latest allowed start; incompatible windows refuse, never clip a late session. |
| `max_sessions_per_day`, `concurrent_sessions` | One each; stable account/date claims and the account guard enforce both. |
| `max_session_seconds` | Global maximum, combined with each entry's duration and optional fixed end; the effective end is recorded. |
| `learning_dates`, `confirmation_dates` | Empty, or an inclusive two-date range. Configured ranges must be disjoint, within qualification, and cover the entry. Receipts label the lane; this grants no scientific confirmation claim. |
| `capital_mode` | `committed_cost_no_recycling` only. Principal recycling and `fixed_sleeve_redeemed_principal_only` refuse. |

The immutable release records the parameter-support table and refuses if it
differs from this code's enforced contract. An unsupported expansion is a precise refusal, never a partial implementation
or implicit approval. Supported edits take effect for the next attempt; an
admitted attempt uses its immutable snapshot. Changing campaign ID/revision or
lowering a count does not reset account history. Enabling/disabling the campaign
file and actual task are independent owner controls. A disabled task does not
prove cancellation of an already running session.

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
Unverified sales, redemption or merges are never inferred from prices or marks.

The new `lfc_autostart_v1` protocol explicitly removes the historical T-24
lead-time requirement only for this lane. It first checks the previous accounting
and original inventory anchor, then binds its own fresh baseline/pre-go receipt
to the entry. Later global baseline files cannot override that binding. Existing
manual/F0 gates keep their historical protocol.

## Availability and containment

One coordinator thread owns the account guard, exclusive workload barrier,
legacy heavy slot and all newer compatibility slots through cleanup and owned
sidecar teardown. It refuses abandoned/poisoned ownership without recovery.
A pre-existing HOLD is honored; only its own marker can be released, and only
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
qualified controller has one event, so this ends its session without replacement.
Toronto and Denver midnight transitions are tested separately. A planned end
may cross such a boundary because that tested pull is in place.

Before work starts, the lane also publishes its own crash-persistent schema at
the legacy global poison location while holding every slot. Older helpers refuse
that schema instead of adopting it as an offline/Stage-0 lease. Normal contained
completion removes only the matching marker and HOLD. A crash/uncertain teardown
retains them. `weather.market.lfc_campaign_cli owner-clear-workload` is an explicit
owner-terminal operation: it requires the incident's bound account/state, hash
confirmation, a different proved Windows boot ID and all-slot exclusion. It
removes only that workload marker and its hash-bound HOLD; monetary incidents
and date claims remain for separate owner-led recovery. Automatic admission and
reconciliation never invoke it.

The task is finite, `IgnoreNew`, no wake, no catch-up, no restart-on-failure,
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

## Outcomes and optional public capture

Full session outcomes, monetary facts, original proof flags and read hashes stay
in owner/runtime evidence under the account state directory. The embargo-safe
agent projection is `C:\t\pilot\status\control`: immutable phase/progress,
freshness, incident/pending flags, safe reason codes and hashes only. It contains
no prices, fills, tokens, events, wallet or credential paths. RUNNING observations
are published at least every minute while the loop progresses. A stale last
observation is lost progress, not proof of a clean exit.

The disabled [T033 proposal](../examples/campaign.proposed.json) is a specification
example, not runtime policy or approval. Its proposed horizon, band, date, budget
and capital values are not activated by shipping it. Unknown fields and any
unsupported values fail explicitly; the runtime [reference example](../examples/lfc-campaign.example.json)
retains the current F0 terms. Original historical evidence is never relabeled.

The optional T017 adapter captures the selected event's all-band scope. It
computes explicit slower metadata/terms/fee cadences with retry room below its
hard request limit, records scope and achieved coverage, and retains source
gaps, pending baselines, local transport receipts, writer progress and errors.
An old remote book timestamp alone is not a dead local receiver. Final chunk
counts and hashes must match physical files; missing/corrupt/partial chunks
make capture incomplete. It never claims native sequence completeness. There
is no automatic private-session restart for public capture recovery.

`money_accounting_complete`, `cleanup_proven` and `unknown_submit` are distinct
from `research_evidence_complete` and public coverage. A missed scoring read or
optional sidecar gap remains visible without permanently stranding a money-clean
account. An unexplained missing core proof remains unknown and blocks starts.

## Update when

Update with policy support, task/identity contracts, claim/recovery transitions,
money proof, containment, status projection or sidecar integration changes.
