"""Bleed-limit and pause enforcement. Fixture books only; no venue, credential or socket."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket

import pytest

from maker_core.contracts.portfolio import CAMPAIGNS_SCHEMA, SNAPSHOT_SCHEMA
from maker_core.portfolio.ledger import build_book
from maker_core.runtime import guard_latch
from maker_core.runtime.guard import (ALLOW, GUARD_SCHEMA, HALT, PAUSE, GatedPlacement, GuardRefused,
                                      OrderGate, PlacementPermit, evaluate, validate_policy)
from maker_core.runtime.guard_conformance import check_guard_conformance

START = "2026-09-22T00:00:00+00:00"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
ACCOUNT = "0x" + "2" * 40
SLUG = "highest-temperature-in-fixture"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("guard test attempted network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def campaigns(limit="40"):
    return dict(schema_version=CAMPAIGNS_SCHEMA, account_id=ACCOUNT, default_campaign="owner-discretionary",
        unattributed_cash_pusd="100",
        campaigns=[dict(id="weather-maker", start_utc=START, bleed_limit_pusd=limit,
                        contributions=[dict(id="wm-capital", at_utc=START, amount_pusd="100")]),
                   dict(id="youtube-maker", enabled=False),
                   dict(id="owner-discretionary", start_utc=START, contributions=[])],
        lot_overrides=[], rules=[dict(campaign="weather-maker", event_slug_prefix="highest-temperature-in-")])


POLICY = dict(schema_version=GUARD_SCHEMA, campaign_id="weather-maker", max_cash_age_seconds=300)


def book(*, loss=None, fee="0", age=timedelta(seconds=30), config=None):
    """A wallet with cash 200 = campaign 100 + reserve 100, optionally after a resolved losing buy."""
    trades, positions, cash = [], [], "200"
    if loss is not None:
        size = loss * 2  # bought at 0.5, resolved at 0
        trades = [dict(event_id="e1", transaction_hash="tx1", asset_id="a1", condition_id="c1", event_slug=SLUG,
                       at_utc="2026-09-25T12:00:00+00:00", side="BUY", size=str(size), price="0.5", fee_pusd=fee)]
        positions = [dict(asset_id="a1", condition_id="c1", event_slug=SLUG, size=str(size), avg_price="0.5",
                          classification="resolved", redeemable=True, terminal_price="0", bid=None, ask=None)]
        cash = str(200 - loss)
    snap = dict(schema_version=SNAPSHOT_SCHEMA, account_id=ACCOUNT, as_of_utc=(NOW - age).isoformat(),
                cash_pusd=cash, positions=positions, trades=trades, positions_complete=True,
                history_complete=True, history_start_utc=START)
    return build_book([snap], config or campaigns())


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class CancelPort:
    def __init__(self):
        self.intents = []

    def request_cancel_all(self, intent):
        self.intents.append(intent)


@pytest.fixture
def rig(tmp_path):
    state = tmp_path / "latch"
    guard_latch.initialize(state, NOW)
    port, clock = CancelPort(), Clock()
    gate = OrderGate(state_dir=state, pause_file=tmp_path / "PAUSE", policy=POLICY, campaigns=campaigns(),
                     clock=clock, cancel_port=port)
    return gate, port, clock, state, tmp_path / "PAUSE"


def decide(b, **kw):
    return evaluate(b, campaigns(), POLICY, now_utc=NOW, pause_requested=kw.pop("pause", False),
                    latched=kw.pop("latched", guard_latch.CLEAR), **kw)


def test_complete_fresh_book_allows():
    assert decide(book()).action == ALLOW
    assert decide(book(loss=40)).action == ALLOW  # P&L exactly -limit: ledger bleed is strictly below


def test_bleed_limit_halts_from_real_ledger():
    b = book(loss=41)
    assert b["campaigns"]["weather-maker"]["status"] == "BLEED_LIMIT"
    decision = decide(b)
    assert decision.action == HALT and "bleed_limit_reached" in decision.reasons


def test_bleed_recomputed_not_trusted():
    b = book(loss=41)
    entry = b["campaigns"]["weather-maker"]
    entry.update(status="OBSERVED", bleed_limit_reached=False)
    assert decide(b).reasons == ("bleed_limit_reached",)


@pytest.mark.parametrize("mutate, reason", [
    (lambda b: b.update(status="INCOMPLETE", reasons=["fee_unknown"]), "ledger_incomplete"),
    (lambda b: b["campaigns"]["weather-maker"].update(pnl_pusd=None, bleed_limit_reached=None,
                                                      status="INCOMPLETE"), "bleed_state_unknown"),
    (lambda b: b["campaigns"].pop("weather-maker"), "campaign_missing_from_book"),
    (lambda b: b.update(cash_pusd=None), "wallet_cash_missing"),
    (lambda b: b.update(config_sha256="0" * 64), "book_config_mismatch"),
    (lambda b: b.update(account_id="0x" + "3" * 40), "book_account_mismatch"),
    (lambda b: b.pop("as_of_utc"), "guard_evaluation_failed:'as_of_utc'"),
])
def test_unknown_or_inconsistent_book_halts(mutate, reason):
    b = book()
    mutate(b)
    decision = decide(b)
    assert decision.action == HALT and reason in decision.reasons


def test_incomplete_ledger_from_real_ledger_halts():
    b = book(loss=10, fee=None)
    assert b["status"] == "INCOMPLETE"
    assert {"ledger_incomplete", "campaign_incomplete", "bleed_state_unknown"} <= set(decide(b).reasons)


def test_stale_or_future_cash_halts():
    assert decide(book(age=timedelta(seconds=301))).reasons == ("wallet_cash_stale",)
    assert decide(book(age=timedelta(seconds=-6))).reasons == ("wallet_read_from_future",)
    assert decide(book(age=timedelta(seconds=300))).action == ALLOW


def test_pause_and_latch_states():
    assert decide(book(), pause=True).reasons == ("owner_pause_requested",)
    assert decide(book(), latched=guard_latch.PAUSED).action == PAUSE
    assert decide(book(), latched=guard_latch.HALTED).action == HALT
    assert decide(book(), latched="unreadable").action == HALT
    assert decide(book(loss=41), pause=True).action == HALT  # halt outranks pause


@pytest.mark.parametrize("change, error", [
    (dict(campaign_id="owner-discretionary"), "guarded_campaign_must_be_enabled_bot_campaign"),
    (dict(campaign_id="youtube-maker"), "guarded_campaign_must_be_enabled_bot_campaign"),
    (dict(max_cash_age_seconds=None), "invalid_max_cash_age_seconds"),
    (dict(max_cash_age_seconds=0), "invalid_max_cash_age_seconds"),
    (dict(max_permit_age_seconds=61), "invalid_max_permit_age_seconds"),
    (dict(extra=1), "unknown_guard_policy_field"),
])
def test_policy_refusals(change, error):
    with pytest.raises(ValueError, match=error):
        validate_policy({**POLICY, **change}, campaigns())
    with pytest.raises(ValueError, match="bleed_limit_required"):
        validate_policy(POLICY, campaigns(limit=None))
    assert decide(book()).action == ALLOW
    assert evaluate(book(), campaigns(), {**POLICY, **change}, now_utc=NOW, pause_requested=False,
                    latched=guard_latch.CLEAR).action == HALT


def test_halt_latches_durably_and_emits_cancel_all(rig):
    gate, port, clock, state, _ = rig
    permit = gate.authorize(book())
    with pytest.raises(GuardRefused) as refused:
        gate.authorize(book(loss=41))
    assert refused.value.decision.action == HALT
    intent = port.intents[-1]
    assert (intent.trigger, intent.scope, intent.campaign_id) == (HALT, "all_open_orders", "weather-maker")
    assert intent.latch_sha256 == guard_latch.safe_tip(state)
    with pytest.raises(PermissionError):
        gate.redeem(permit)  # issued before the halt
    assert guard_latch.read_state(state) == guard_latch.HALTED
    # A recovered book and a brand-new gate (process restart) stay halted.
    fresh = OrderGate(state_dir=state, pause_file=rig[4], policy=POLICY, campaigns=campaigns(),
                      clock=clock, cancel_port=port)
    assert fresh.check(book()).reasons == ("latched_halt",)
    records, _ = guard_latch.verify_records(state)
    assert [r["kind"] for r in records] == ["init", "trip"]  # repeated halts do not grow the latch


def test_pause_file_latches_and_only_owner_clear_resumes(rig):
    gate, port, clock, state, pause = rig
    pause.write_text("owner")
    assert gate.check(book()).action == PAUSE and port.intents[-1].trigger == PAUSE
    pause.unlink()
    assert gate.check(book()).reasons == ("latched_pause",)  # no automatic resume
    tip = guard_latch.safe_tip(state)
    pause.write_text("owner")
    with pytest.raises(ValueError, match="pause_file_present"):
        guard_latch.owner_clear(state, confirm_sha256=tip, pause_file=pause, now=NOW)
    pause.unlink()
    with pytest.raises(ValueError, match="latch_confirmation_stale"):
        guard_latch.owner_clear(state, confirm_sha256="0" * 64, pause_file=pause, now=NOW)
    guard_latch.owner_clear(state, confirm_sha256=tip, pause_file=pause, now=NOW)
    assert gate.check(book()).action == ALLOW
    assert gate.check(book(loss=41)).action == HALT  # a clear never bypasses the next evaluation


def test_pause_escalates_to_halt(rig):
    gate, _, _, state, pause = rig
    pause.write_text("")
    gate.check(book())
    gate.check(book(age=timedelta(hours=1)))
    assert [r["state"] for r in guard_latch.verify_records(state)[0]] == ["CLEAR", "PAUSED", "HALTED"]


def test_missing_or_damaged_latch_halts(rig, tmp_path):
    gate, port, clock, state, pause = rig
    other = OrderGate(state_dir=tmp_path / "typo", pause_file=pause, policy=POLICY, campaigns=campaigns(),
                      clock=clock, cancel_port=port)
    assert other.check(book()).reasons == ("latch_state_unknown",)
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="latch_uninitialized"):
        guard_latch.read_state(tmp_path / "empty")
    record = state / "00000000.json"
    record.write_bytes(record.read_bytes().replace(b'"CLEAR"', b'"CLEAR" '))
    decision = gate.check(book())
    assert decision.action == HALT and port.intents[-1].latch_sha256 is None


def test_permits_are_single_use_short_lived_and_unforgeable(rig):
    gate, _, clock, _, pause = rig
    sent = []
    placement = GatedPlacement(gate, sent.append)
    permit = gate.authorize(book())
    placement.place("order-1", permit)
    with pytest.raises(PermissionError, match="invalid"):
        placement.place("order-2", permit)
    forged = PlacementPermit("f" * 32, NOW.isoformat(), "weather-maker", "x")
    with pytest.raises(PermissionError, match="invalid"):
        placement.place("order-3", forged)
    first, second = gate.authorize(book()), gate.authorize(book())
    with pytest.raises(PermissionError, match="invalid"):
        placement.place("order-revoked", first)
    placement.place("order-2", second)
    late = gate.authorize(book())
    clock.now = NOW + timedelta(seconds=6)
    with pytest.raises(PermissionError, match="expired"):
        placement.place("order-4", late)
    clock.now = NOW
    paused = gate.authorize(book())
    pause.write_text("")
    with pytest.raises(PermissionError, match="latched_or_paused"):
        placement.place("order-5", paused)
    assert sent == ["order-1", "order-2"]


class FakeRuntime:
    """Obeys the contract: authorize before each decision, place through the port."""

    def __init__(self, gate, placement):
        self.gate, self.placement, self.n = gate, placement, 0

    def step(self, b):
        permit = self.gate.authorize(b)
        self.n += 1
        self.placement.place(f"order-{self.n}", permit)


class HoardingRuntime(FakeRuntime):
    """Misbehaves: hoards permits while allowed and skips the guard afterwards."""

    def __init__(self, gate, placement):
        super().__init__(gate, placement)
        self.saved = []

    def step(self, b):
        if not self.saved:
            self.saved = [self.gate.authorize(b) for _ in range(3)]
            self.placement.place("order-0", self.saved.pop())
            return
        for permit in list(self.saved):
            try:
                self.placement.place("hoarded", permit)
            except PermissionError:
                pass
        self.gate.check(b)  # observes the decision but never asks for a fresh permit
        self.placement.place("forged", PlacementPermit("0" * 32, NOW.isoformat(), "weather-maker", "x"))


@pytest.mark.parametrize("runtime", [FakeRuntime, HoardingRuntime])
def test_conformance_no_placement_after_halt(rig, runtime):
    gate, port, *_ = rig
    check_guard_conformance(runtime, gate=gate, allow_book=book(), halt_book=book(loss=41),
                            cancel_intents=port.intents)


def test_gate_refuses_construction_without_cancel_port(rig):
    _, _, clock, state, pause = rig
    with pytest.raises(TypeError, match="cancel_all_port_required"):
        OrderGate(state_dir=state, pause_file=pause, policy=POLICY, campaigns=campaigns(), clock=clock,
                  cancel_port=object())


def test_owner_cli_init_status_clear(tmp_path, capsys):
    state, pause = tmp_path / "latch", tmp_path / "PAUSE"
    assert guard_latch.main(["init", "--state-dir", str(state)]) == 0
    assert guard_latch.main(["init", "--state-dir", str(state)]) == 1
    capsys.readouterr()
    guard_latch.trip(state, guard_latch.HALTED, dict(reasons=["bleed_limit_reached"]), NOW)
    assert guard_latch.main(["status", "--state-dir", str(state)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "HALTED"
    assert guard_latch.main(["clear", "--state-dir", str(state), "--pause-file", str(pause),
                             "--confirm", "0" * 64]) == 1
    assert guard_latch.main(["clear", "--state-dir", str(state), "--pause-file", str(pause),
                             "--confirm", status["tip_sha256"]]) == 0
    assert guard_latch.read_state(state) == guard_latch.CLEAR
    with pytest.raises(ValueError, match="latch_not_set"):
        guard_latch.owner_clear(state, confirm_sha256=guard_latch.safe_tip(state), pause_file=pause, now=NOW)


def test_only_the_owner_command_can_clear():
    root = Path(__file__).resolve().parents[2] / "src"
    callers = sorted(str(p.relative_to(root)) for p in root.rglob("*.py")
                     if "owner_clear" in p.read_text(encoding="utf-8"))
    assert callers == [str(Path("maker_core/runtime/guard_latch.py"))]
    assert "owner_clear" not in vars(OrderGate)
