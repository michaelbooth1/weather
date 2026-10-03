# Maker trading guard: pause, bleed limit and halt

Status: canonical. Owns the fail-closed guard every future `maker_core` live runtime
must pass before placing an order, the owner-cleared PAUSE/HALT latch and the
cancel-all intent. Read when building or reviewing a maker runtime, a venue
placement port, or any live-readiness claim. This document grants no trading
authority: [the state of play](STATE_OF_PLAY.md) does, and today it says no live
trading. The owner decision this implements (2026-09-25: pause and bleed limit in
code before any future live run) is in [DECISION_LOG](DECISION_LOG.md).

## Pieces

| Module | Role |
| --- | --- |
| `maker_core.runtime.guard` | `evaluate()` (pure), `OrderGate`, `GatedPlacement`, `CancelAllIntent`, `CancelAllPort` |
| `maker_core.runtime.guard_latch` | Create-only hash-chained latch records; the owner's `init` / `status` / `clear` command |
| `maker_core.runtime.guard_conformance` | `check_guard_conformance()`: a runtime must place nothing after HALT |

All three are domain-neutral (the `maker_core` import ratchet applies), make no
venue, network or credential access, and take every path explicitly.

## Decision

`evaluate(book, campaigns, policy, now_utc, pause_requested, latched)` reads a
[portfolio ledger](portfolio-ledger.md) book and returns `ALLOW`, `PAUSE` or `HALT`
with sorted reason codes. HALT outranks PAUSE; any exception is HALT.

| HALT reason | Trigger |
| --- | --- |
| `ledger_incomplete` | Wallet book status is not `OBSERVED` or carries reasons. Unknown P&L is never traded through. This includes owner-discretionary gaps, because the wallet is shared. |
| `campaign_incomplete`, `bleed_state_unknown`, `campaign_status_unknown`, `campaign_missing_from_book` | The guarded campaign's own P&L or bleed state is unknown. |
| `bleed_limit_reached` | Campaign P&L strictly below minus `bleed_limit_pusd`, recomputed from `pnl_pusd` and the config (the ledger's flag is not trusted alone). Equal to minus the limit is still ALLOW, matching the ledger. |
| `wallet_cash_stale`, `wallet_read_from_future`, `wallet_cash_missing` | Book `as_of_utc` older than `max_cash_age_seconds`, ahead of the clock by more than `max_clock_skew_seconds`, or no cash read. |
| `book_config_mismatch`, `book_account_mismatch` | The book was not built from this exact campaign config (`config_sha256`) or account. |
| `latched_halt`, `latch_state_unknown` | A HALT is latched, or the latch directory is missing, uninitialized or fails verification. |
| `guard_evaluation_failed:<error>` | Invalid policy, malformed book, anything unexpected. |

PAUSE reasons: `owner_pause_requested` (the pause file exists) and `latched_pause`.

Policy, schema `maker_guard_v0.1`: `campaign_id` (an enabled campaign other than
`owner-discretionary`, which must have a `bleed_limit_pusd`), `max_cash_age_seconds`
(required, 1-3600), `max_clock_skew_seconds` (default 5, 0-60) and
`max_permit_age_seconds` (default 5, 1-60). Unknown fields are refused.

## Latch: durable, owner-cleared, no automatic resume

The latch directory holds `00000000.json`, ... records in the canonical journal
encoding, each binding the previous record's SHA-256: `init` (CLEAR), `trip`
(PAUSED or HALTED, with the full decision) and `clear`. Records are never
rewritten or deleted. The gate trips the latch on the first PAUSE or HALT and
escalates PAUSED to HALTED; repeating the same state appends nothing. A missing,
empty or damaged directory reads as `latch_state_unknown` = HALT, so a mistyped
path cannot silently bypass the owner's latch.

Removing the pause file does not resume. Only the owner's command clears, and it
must quote the current tip (so nobody clears a latch they have not read, or one that
re-tripped meanwhile) with the pause file absent:

```powershell
.\venv\Scripts\python.exe -m maker_core.runtime.guard_latch init   --state-dir <latch dir>
.\venv\Scripts\python.exe -m maker_core.runtime.guard_latch status --state-dir <latch dir>
.\venv\Scripts\python.exe -m maker_core.runtime.guard_latch clear  --state-dir <latch dir> --pause-file <pause file> --confirm <tip_sha256>
```

A clear is not an ALLOW: the next check re-evaluates the ledger, cash age and pause
file from scratch. `OrderGate` has no clear method, and a test fails if any
source module other than the command references `owner_clear`.

## Runtime contract

1. Build one `OrderGate(state_dir, pause_file, policy, campaigns, clock, cancel_port)`
   per runtime. A `CancelAllPort` is mandatory.
2. Before **every** order-placing decision call `gate.authorize(book)` with the latest
   ledger book. It raises `GuardRefused` unless ALLOW, else returns a single-use
   `PlacementPermit`. A new authorize revokes the previous permit, so each order
   (each leg) needs its own evaluation.
3. Every venue submit goes through `GatedPlacement(gate, send).place(order, permit)`,
   which redeems the permit immediately before `send`: refused when forged, reused,
   revoked, older than `max_permit_age_seconds`, or when a latch or pause file has
   appeared since issue.
4. On every PAUSE or HALT the gate writes the latch first, then calls
   `cancel_port.request_cancel_all(CancelAllIntent(...))` (scope `all_open_orders`,
   trigger, reasons, latch tip). It emits the intent even if the latch write failed,
   then re-raises. Both PAUSE and HALT cancel, because a resting maker order keeps
   trading. The venue implementation of the port is future work: nothing here
   calls a venue.
5. A runtime proves conformance with `check_guard_conformance(make_runtime, ...)`
   over fixture books; `tests/maker_core/test_guard.py` runs it against a compliant
   fake runtime and a permit-hoarding, guard-skipping one.

## Not yet

The runtime itself, the venue cancel-all and submit, how often the runtime refreshes
the wallet read, per-order cash headroom against the remaining bleed budget, and
the caps of the [design](informed-maker-design-2026-09-25.md) Phase 2. The pause
file and latch directory locations are chosen with the runtime.

## Update when

Update with guard reasons, policy fields, latch format or command, the runtime
contract, or the conformance kit.
