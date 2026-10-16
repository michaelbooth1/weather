"""Item 330 build 3 (a): the runner refuses to score without a matching signed preregistration. The seams
for builds 1 and 2 are covered here too."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from maker_core.frontier import prereg, runner
from maker_core.frontier.grid import GRID, GRID_HASH
from maker_core.frontier.prereg import PreregRefused, registration_hash, verify
from maker_core.frontier.seams import (
    CONSTANT_ADVERSE_MARKOUT, ConstantFillCost, FillCostProvider, FillModel, PricePathFillModel, QueueFillModel,
    fill_cost_terms,
)
from maker_core.frontier.share_decay import DecayModel
from maker_core.quoting.policy import Book, QuoteLeg
from maker_core.replay.fill_model import match
from maker_core.replay.payloads import Trade
from maker_core.replay.v2.lockstep import bundle_source
from .fixtures.replay_scenario import Scenario

DRAFT = Path(__file__).parents[2] / "docs" / "research" / "informed-v1-frontier-preregistration-DRAFT-2026-10-16.md"
DECAY = DecayModel(5.0, 5.0, 20.0, ())
DAY = date(2027, 2, 1)
NOW = datetime(2027, 2, 1, tzinfo=timezone.utc)


def source(tmp_path, name="b", minutes=8):
    s = Scenario(day=DAY, minutes=minutes)
    for minute in range(minutes):
        for market in s.markets:
            s.book(market, minute * 60)
    s.trade("a", 125, price=".40", size="10")
    s.trade("a", 200, price=".55", size="30")
    s.settle("a", minutes * 60 - 30, p=0)
    return bundle_source(s.bundle(tmp_path / name))


def document(signed="Michael Booth, 2027-01-31", grid=GRID_HASH):
    return ("# informed-v1 frontier preregistration\n\nGrid hash: `%s`\n\nSigned: %s\n" % (grid, signed)).encode()


# -- the registration gate ------------------------------------------------------------------------------
def test_scored_read_is_refused_while_no_preregistration_is_pinned(tmp_path):
    assert prereg.SIGNED_PREREGISTRATION_SHA256 is None
    with pytest.raises(PreregRefused, match="no_signed_preregistration"):
        runner.run([source(tmp_path)], decay=DECAY, mode="scored", registration=document())


def test_the_unsigned_draft_cannot_score_even_if_its_hash_were_pinned(monkeypatch):
    draft = DRAFT.read_bytes()
    assert b"Signed: UNSIGNED" in draft
    assert ("Grid hash: `%s`" % GRID_HASH).encode() in draft
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(draft))
    with pytest.raises(PreregRefused, match="preregistration_unsigned"):
        verify(draft)


@pytest.mark.parametrize("doc,reason", [
    (None, "registration_document_required"),
    (document(signed="Someone else"), "registration_hash_mismatch"),
])
def test_a_document_must_match_the_pin(monkeypatch, doc, reason):
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(document()))
    with pytest.raises(PreregRefused, match=reason):
        verify(doc)


@pytest.mark.parametrize("doc,reason", [
    (document(signed="UNSIGNED"), "preregistration_unsigned"),
    (document(signed=""), "preregistration_unsigned"),
    (document() + b"Signed: a second line\n", "preregistration_unsigned"),
    (document(grid="0" * 64), "grid_hash_mismatch"),
    (document().replace(b"Grid hash", b"Grid digest"), "grid_hash_mismatch"),
])
def test_signature_and_grid_hash_are_required(monkeypatch, doc, reason):
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(doc))
    with pytest.raises(PreregRefused, match=reason):
        verify(doc)


def test_a_pinned_signed_registration_scores_outside_the_windows(tmp_path, monkeypatch):
    doc = document()
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(doc))
    result = runner.run([source(tmp_path)], decay=DECAY, mode="scored", registration=doc, points=GRID[:4])
    assert result["label"] == "SCORED" and result["registration_sha256"] == registration_hash(doc)


def test_descriptive_read_is_labelled_and_needs_no_registration(tmp_path):
    result = runner.run([source(tmp_path)], decay=DECAY, points=GRID[:2])
    assert result["label"] == "DESCRIPTIVE" and result["registration_sha256"] is None
    assert result["grid_hash"] == GRID_HASH and result["decay"] == DECAY.digest()


def test_unknown_mode_baseline_or_missing_decay_are_refused(tmp_path):
    src = source(tmp_path)
    with pytest.raises(runner.FrontierRefused, match="unknown_mode"):
        runner.run([src], decay=DECAY, mode="live")
    with pytest.raises(runner.FrontierRefused, match="unknown_baseline"):
        runner.run([src], decay=DECAY, baselines=("informed-v1",))
    with pytest.raises(runner.FrontierRefused, match="decay_model_required"):
        runner.run([src], decay=None)


# -- runner behaviour -----------------------------------------------------------------------------------
def test_runner_is_deterministic_and_point_order_invariant(tmp_path):
    src = source(tmp_path)
    one = runner.run([src], decay=DECAY, hazard_per_minute=.001)
    two = runner.run([src], decay=DECAY, hazard_per_minute=.001, points=tuple(reversed(GRID)))
    assert one["digest"] == two["digest"]


def test_hold_and_resting_sell_inventory(tmp_path):
    result = runner.run([source(tmp_path)], decay=DECAY)["strategies"]
    hold, sell = (result["w1.0-s20-depth_only-%s" % inv] for inv in ("hold_to_settlement", "resting_sell"))
    assert hold["filled_shares"] == sell["filled_shares"] == 10
    assert hold["settlement_pnl"] == D("-4.90") and hold["exit_pnl"] == 0   # YES at 0.49, settled NO
    assert sell["exit_pnl"] == D("0.20") and sell["settlement_pnl"] == 0    # offered at 0.51, sold at 0.55
    assert hold["adverse_cost"] == pytest.approx(10 * CONSTANT_ADVERSE_MARKOUT)
    assert hold["reward"] == sell["reward"]


def test_quotes_are_symmetric_about_the_mid_with_no_skew():
    s = Scenario(day=DAY, minutes=1)
    band = runner.Band()
    from maker_core.replay.payloads import Descriptor
    band.descriptor = Descriptor(s.descriptors["a"], 1)
    band.book = Book(NOW, ((D(".59"), D(100)),), ((D(".61"), D(100)),), ((D(".39"), D(100)),), ((D(".41"), D(100)),))
    from maker_core.quoting.policy import RewardTerms
    band.terms = RewardTerms(NOW, D(20), D(5), D(100))
    for point in GRID:
        proposal = runner.propose(point, band, NOW)
        if proposal is None:
            continue
        yes, no = proposal[0]
        assert (D(".60") - yes.price) == (D(".40") - no.price)  # equal distance from each side's centre


# -- seams ----------------------------------------------------------------------------------------------
def trade(price, outcome="YES", size="10"):
    return Trade("t", outcome, D(price), D(size), NOW, "SELL")


@pytest.mark.parametrize("bound", ("strictly_through", "at_price"))
@pytest.mark.parametrize("price", (".38", ".40", ".41", ".60"))
def test_price_path_stand_in_equals_the_frozen_v2_match(bound, price):
    legs = (QuoteLeg("YES", D(".40"), D(20)), QuoteLeg("NO", D(".58"), D(20)))
    model = PricePathFillModel(bound)
    assert isinstance(model, FillModel)
    _, hits = model.on_trade(model.place(legs, None), trade(price))
    expected = match(legs, trade(price), bound)
    assert hits == ((expected,) if expected else ())


class StubV3Kernel:
    """Mirrors build 1's fill_v3 surface: eligibility, q_ahead and QueueState."""

    @staticmethod
    def eligibility(leg, trade):
        quote = leg.price if leg.outcome == "YES" else 1 - leg.price
        price = trade.price if trade.outcome == "YES" else 1 - trade.price
        if price == quote:
            return "at"
        return "thr" if (price < quote if leg.outcome == "YES" else price > quote) else None

    @staticmethod
    def q_ahead(book, leg):
        levels = book.yes_bids if leg.outcome == "YES" else book.no_bids
        return sum((s for p, s in levels if p == leg.price), D(0))

    class QueueState:
        def __init__(self, size, queue):
            self.size, self.left = size, queue

        def consume(self, size):
            used = min(size, self.left)
            self.left -= used
            return min(self.size, size - used)


def test_queue_adapter_consumes_the_displayed_queue_first():
    book = Book(NOW, ((D(".40"), D(15)),), ((D(".42"), D(15)),), ((D(".58"), D(15)),), ((D(".60"), D(15)),))
    model = QueueFillModel(StubV3Kernel())
    state = model.place((QuoteLeg("YES", D(".40"), D(20)),), book)
    state, hits = model.on_trade(state, trade(".40", size="10"))
    assert hits == ()                              # 10 of the 15 ahead consumed
    state, hits = model.on_trade(state, trade(".40", size="10"))
    assert hits[0][1] == D(5)                       # 5 left ahead, 5 fill
    with pytest.raises(TypeError):
        QueueFillModel(object())


@dataclass
class Estimate:
    adverse_markout_upper: float
    veto: str | None = None


class Provider:
    def __init__(self, estimate):
        self.value = estimate

    def estimate(self, context):
        return self.value


def test_fill_cost_terms_never_go_below_the_constant():
    assert fill_cost_terms(None) == (CONSTANT_ADVERSE_MARKOUT, None)
    assert fill_cost_terms(Estimate(.001)) == (CONSTANT_ADVERSE_MARKOUT, None)
    assert fill_cost_terms(Estimate(.02, "BURST")) == (.02, "BURST")
    with pytest.raises(ValueError):
        fill_cost_terms(Estimate(.02, "SPOOF"))
    assert isinstance(ConstantFillCost(), FillCostProvider)


def test_injected_cost_provider_reaches_every_strategy(tmp_path):
    src = source(tmp_path)
    contexts = []

    def builder(**context):
        contexts.append(context)
        return context

    strict = runner.run([src], decay=DECAY, points=GRID[:1], baselines=(), cost_provider=Provider(Estimate(.02)),
                        context_builder=builder)["strategies"]
    assert strict[GRID[0].label]["adverse_cost"] == pytest.approx(10 * .02)
    assert contexts and set(contexts[0]) == {"condition_id", "at", "band", "strategy"}
    vetoed = runner.run([src], decay=DECAY, points=GRID[:1], baselines=("blind_re1",),
                        cost_provider=Provider(Estimate(.02, "SWEEP")))["strategies"]
    assert all(v["quotes"] == 0 and v["vetoes"] > 0 for v in vetoed.values())
