"""Fail-closed trading guard: ALLOW / PAUSE / HALT before every order placement.

Contract: docs/operations/maker-trading-guard.md. ``evaluate`` is pure. ``OrderGate``
adds the owner-cleared latch (``guard_latch``), single-use placement permits and the
cancel-all intent. No venue, credential, network or domain access occurs here.
"""
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import secrets
from threading import RLock
from typing import Callable, Protocol, runtime_checkable

from maker_core.contracts import utc_time
from maker_core.contracts.portfolio import active_campaigns, amount, instant, validate_campaigns
from maker_core.evidence.journal import digest
from maker_core.runtime import guard_latch

GUARD_SCHEMA = "maker_guard_v0.1"
ALLOW, PAUSE, HALT = "ALLOW", "PAUSE", "HALT"


def validate_policy(policy, campaigns):
    """A guarded campaign must be an enabled bot campaign with a bleed limit."""
    if not isinstance(policy, dict) or policy.get("schema_version") != GUARD_SCHEMA:
        raise ValueError("invalid_guard_policy")
    if set(policy) - {"schema_version", "campaign_id", "max_cash_age_seconds",
                      "max_clock_skew_seconds", "max_permit_age_seconds"}:
        raise ValueError("unknown_guard_policy_field")
    limits = (("max_cash_age_seconds", None, 1, 3600), ("max_clock_skew_seconds", 5, 0, 60),
              ("max_permit_age_seconds", 5, 1, 60))
    for key, default, low, high in limits:
        value = policy.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError("invalid_" + key)
    campaigns = validate_campaigns(campaigns)
    name = policy.get("campaign_id")
    campaign = next((c for c in active_campaigns(campaigns) if c["id"] == name), None)
    if campaign is None or name == "owner-discretionary":
        raise ValueError("guarded_campaign_must_be_enabled_bot_campaign")
    if campaign.get("bleed_limit_pusd") is None:
        raise ValueError("bleed_limit_required")
    return policy


@dataclass(frozen=True)
class GuardDecision:
    action: str
    reasons: tuple
    campaign_id: object
    account_id: object
    decided_at_utc: str
    book_sha256: object
    book_as_of_utc: object


def _checks(book, campaigns, policy, now):
    halt = []
    config_hash = digest(campaigns)
    validate_policy(policy, campaigns)
    name = policy["campaign_id"]
    if book.get("config_sha256") != config_hash:
        halt.append("book_config_mismatch")
    account = campaigns.get("account_id")
    if account is not None and str(book.get("account_id", "")).lower() != account.lower():
        halt.append("book_account_mismatch")
    if book.get("status") != "OBSERVED" or book.get("reasons"):
        halt.append("ledger_incomplete")
    as_of = instant(book["as_of_utc"])
    if as_of > now + timedelta(seconds=policy.get("max_clock_skew_seconds", 5)):
        halt.append("wallet_read_from_future")
    elif now - as_of > timedelta(seconds=policy["max_cash_age_seconds"]):
        halt.append("wallet_cash_stale")
    if book.get("cash_pusd") is None:
        halt.append("wallet_cash_missing")
    entry = (book.get("campaigns") or {}).get(name)
    if not isinstance(entry, dict):
        return halt + ["campaign_missing_from_book"]
    if entry.get("status") != "OBSERVED":
        halt.append({"INCOMPLETE": "campaign_incomplete", "BLEED_LIMIT": "bleed_limit_reached"}.get(
            entry.get("status"), "campaign_status_unknown"))
    if entry.get("pnl_pusd") is None or entry.get("bleed_limit_reached") is not False:
        halt.append("bleed_state_unknown" if entry.get("bleed_limit_reached") is None else "bleed_limit_reached")
    else:
        limit = next(c for c in campaigns["campaigns"] if c["id"] == name)["bleed_limit_pusd"]
        # Strictly below minus the limit, matching the ledger; recomputed, not trusted.
        if amount(entry["pnl_pusd"]) < -amount(limit):
            halt.append("bleed_limit_reached")
    return halt


def evaluate(book, campaigns, policy, *, now_utc, pause_requested, latched):
    """Pure decision. Any error, unknown P&L or doubt is HALT; nothing resumes here."""
    utc_time(now_utc)
    try:
        halt = _checks(book, campaigns, policy, now_utc)
    except (ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        halt = ["guard_evaluation_failed:" + (str(error)[:80] or type(error).__name__)]
    pause = ["owner_pause_requested"] if pause_requested else []
    if latched == guard_latch.CLEAR:
        pass
    elif latched == guard_latch.HALTED:
        halt.append("latched_halt")
    elif latched == guard_latch.PAUSED:
        pause.append("latched_pause")
    else:
        halt.append("latch_state_unknown")
    action = HALT if halt else PAUSE if pause else ALLOW
    book_ok = isinstance(book, dict)
    try:
        book_hash = digest(book)
    except (ValueError, TypeError):
        book_hash = None
    return GuardDecision(action, tuple(sorted(set(halt + pause))),
                         policy.get("campaign_id") if isinstance(policy, dict) else None,
                         book.get("account_id") if book_ok else None, now_utc.isoformat(),
                         book_hash, book.get("as_of_utc") if book_ok else None)


@dataclass(frozen=True)
class CancelAllIntent:
    """Every open order on the account, for the venue port to cancel; never a placement."""
    trigger: str
    reasons: tuple
    campaign_id: object
    account_id: object
    decided_at_utc: str
    latch_sha256: object
    scope: str = "all_open_orders"


@runtime_checkable
class CancelAllPort(Protocol):
    def request_cancel_all(self, intent: CancelAllIntent) -> None: ...


class GuardRefused(RuntimeError):
    def __init__(self, decision):
        super().__init__(decision.action + ":" + ",".join(decision.reasons))
        self.decision = decision


@dataclass(frozen=True)
class PlacementPermit:
    """Opaque, single-use and short-lived. Only the issuing gate can redeem it."""
    permit_id: str
    issued_at_utc: str
    campaign_id: str
    book_sha256: str


class OrderGate:
    """The only placement path: ``authorize`` per decision, ``redeem`` per submit.

    A PAUSE or HALT is latched durably before the cancel-all intent is emitted;
    the gate never clears a latch (the owner command does). One outstanding permit.
    """

    def __init__(self, *, state_dir, pause_file, policy, campaigns, clock: Callable,
                 cancel_port: CancelAllPort):
        if not isinstance(cancel_port, CancelAllPort):
            raise TypeError("cancel_all_port_required")
        self.policy = validate_policy(policy, campaigns)
        self.campaigns, self.clock, self.cancel_port = campaigns, clock, cancel_port
        self.state_dir, self.pause_file = Path(state_dir), Path(pause_file)
        self.permits, self.lock = {}, RLock()

    def _pause_requested(self):
        try:
            return self.pause_file.exists() or self.pause_file.is_symlink()
        except OSError:
            return True

    def check(self, book):
        with self.lock:
            now = self.clock()
            try:
                latched = guard_latch.read_state(self.state_dir)
            except (ValueError, OSError) as error:
                latched = "unreadable:" + str(error)[:40]
            decision = evaluate(book, self.campaigns, self.policy, now_utc=now,
                                pause_requested=self._pause_requested(), latched=latched)
            if decision.action == ALLOW:
                return decision
            self.permits.clear()
            target = guard_latch.HALTED if decision.action == HALT else guard_latch.PAUSED
            try:
                if latched in (guard_latch.CLEAR, guard_latch.PAUSED) and latched != target:
                    guard_latch.trip(self.state_dir, target, decision, now)
            finally:
                # Latch first; cancel even when the latch write itself failed.
                self.cancel_port.request_cancel_all(CancelAllIntent(
                    decision.action, decision.reasons, decision.campaign_id, decision.account_id,
                    decision.decided_at_utc, guard_latch.safe_tip(self.state_dir)))
            return decision

    def authorize(self, book):
        """Call before every order-placing decision; raises GuardRefused unless ALLOW."""
        with self.lock:
            decision = self.check(book)
            if decision.action != ALLOW:
                raise GuardRefused(decision)
            permit = PlacementPermit(secrets.token_hex(16), decision.decided_at_utc,
                                     decision.campaign_id, decision.book_sha256)
            # One outstanding permit: each order needs its own fresh evaluation.
            self.permits = {permit.permit_id: permit}
            return permit

    def redeem(self, permit):
        """The placement port calls this immediately before sending; single use."""
        with self.lock:
            issued = self.permits.pop(getattr(permit, "permit_id", None), None)
            if issued is None or issued != permit:
                raise PermissionError("placement_permit_invalid")
            now = self.clock()
            age = now - instant(permit.issued_at_utc)
            if not timedelta(0) <= age <= timedelta(seconds=self.policy.get("max_permit_age_seconds", 5)):
                raise PermissionError("placement_permit_expired")
            try:
                latched = guard_latch.read_state(self.state_dir)
            except (ValueError, OSError):
                latched = "unreadable"
            if latched != guard_latch.CLEAR or self._pause_requested():
                self.permits.clear()
                raise PermissionError("placement_latched_or_paused")
            return permit


class GatedPlacement:
    """Placement port wrapper: nothing reaches ``send`` without a redeemed permit.

    ``send`` is the future venue submit; this module never calls a venue itself.
    """

    def __init__(self, gate, send: Callable):
        if not isinstance(gate, OrderGate):
            raise TypeError("order_gate_required")
        self.gate, self.send = gate, send

    def place(self, order, permit):
        self.gate.redeem(permit)
        return self.send(order)


__all__ = ["ALLOW", "PAUSE", "HALT", "GUARD_SCHEMA", "GuardDecision", "CancelAllIntent", "CancelAllPort",
           "GuardRefused", "PlacementPermit", "OrderGate", "GatedPlacement", "evaluate", "validate_policy"]
