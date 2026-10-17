"""Item 330 build 3 (a): the runner refuses to score without a matching signed preregistration. The seams
for builds 1 and 2 are covered here too.

Guards: no scored frontier read without a pinned, signed preregistration matching grid, decay and fill model; runner
  determinism and quoting rules; the build 1/2 seams (v2 stand-in equality, queue adapter, 0.0043 markout floor).
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from maker_core.frontier import prereg, runner
from maker_core.frontier.adapters import FILL_V3_BINDING
from maker_core.frontier.grid import BASELINES, GRID, GRID_HASH
from maker_core.frontier.prereg import PreregRefused, registration_hash, verify
from maker_core.frontier.seams import (
    CONSTANT_ADVERSE_MARKOUT, ConstantFillCost, FillCostProvider, FillModel, PricePathFillModel, QueueFillModel,
    binding, fill_cost_terms,
)
from maker_core.frontier.share_decay import DecayModel
from maker_core.quoting.policy import Book, QuoteLeg
from maker_core.replay.fill_model import match
from maker_core.replay.payloads import Trade
from maker_core.replay.v2.lockstep import bundle_source
from .fixtures.frontier_cost_stub import SCORED_COST, STUB_TABLE_DIGEST, TOXICITY_LINE
from .fixtures.replay_scenario import Scenario

DRAFT = Path(__file__).parents[2] / "docs" / "research" / "informed-v1-frontier-preregistration-DRAFT-2026-10-16.md"
DECAY = DecayModel(5.0, 5.0, 20.0, ())
FILL = binding(PricePathFillModel())  # build 4: bound by class, version and name
BOUND = dict(decay_digest=DECAY.digest(), fill_model_binding=FILL)
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


def document(signed="Michael Booth, 2027-01-31", grid=GRID_HASH, decay=None, fill=FILL):
    return ("# informed-v1 frontier preregistration\n\nGrid hash: `%s`\n\nDecay digest: `%s`\n\nFill model: `%s`\n\n"
            "%sSigned: %s\n" % (grid, decay or DECAY.digest(), fill, TOXICITY_LINE, signed)).encode()


# -- the registration gate ------------------------------------------------------------------------------
def test_scored_read_is_refused_while_no_preregistration_is_pinned(tmp_path):
    assert prereg.SIGNED_PREREGISTRATION_SHA256 is None
    with pytest.raises(PreregRefused, match="no_signed_preregistration"):
        runner.run([source(tmp_path)], decay=DECAY, mode="scored", registration=document(), **SCORED_COST)


def test_the_unsigned_draft_cannot_score_even_if_its_hash_were_pinned(monkeypatch):
    draft = DRAFT.read_bytes()
    assert b"Signed: UNSIGNED" in draft
    assert ("Grid hash: `%s`" % GRID_HASH).encode() in draft
    assert prereg._DECAY.findall(draft.decode()) and prereg._FILL.findall(draft.decode()) == [FILL_V3_BINDING]
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(draft))
    with pytest.raises(PreregRefused, match="preregistration_unsigned"):
        verify(draft, **BOUND)


@pytest.mark.parametrize("doc,reason", [
    (None, "registration_document_required"),
    (document(signed="Someone else"), "registration_hash_mismatch"),
])
def test_a_document_must_match_the_pin(monkeypatch, doc, reason):
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(document()))
    with pytest.raises(PreregRefused, match=reason):
        verify(doc, **BOUND)


@pytest.mark.parametrize("doc,reason", [
    (document(signed="UNSIGNED"), "preregistration_unsigned"),
    (document(signed=""), "preregistration_unsigned"),
    (document() + b"Signed: a second line\n", "preregistration_unsigned"),
    (document(grid="0" * 64), "grid_hash_mismatch"),
    (document().replace(b"Grid hash", b"Grid digest"), "grid_hash_mismatch"),
    (document(decay="0" * 64), "decay_digest_mismatch"),
    (document().replace(b"Decay digest", b"Decay hash"), "decay_digest_mismatch"),
    (document(fill="v2-at_price"), "fill_model_mismatch"),
    (document().replace(b"Fill model", b"Fill rule"), "fill_model_mismatch"),
    (document() + b"Fill model: v2-at_price\n", "fill_model_mismatch"),
])
def test_signature_grid_decay_and_fill_model_are_required(monkeypatch, doc, reason):
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(doc))
    with pytest.raises(PreregRefused, match=reason):
        verify(doc, **BOUND)


def test_a_pinned_signed_registration_scores_the_whole_grid_outside_the_windows(tmp_path, monkeypatch):
    doc = document()
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(doc))
    result = runner.run([source(tmp_path)], decay=DECAY, mode="scored", registration=doc,
                        points=tuple(reversed(GRID)), **SCORED_COST)
    assert result["label"] == "SCORED" and result["registration_sha256"] == registration_hash(doc)
    assert set(result["strategies"]) == {p.label for p in GRID} | set(BASELINES)


@pytest.mark.parametrize("kwargs,reason", [
    (dict(points=GRID[:4]), "scored_requires_full_grid"),
    (dict(points=GRID + GRID[:1]), "scored_requires_full_grid"),
    (dict(baselines=("no-quote", "blind_re1")), "scored_requires_all_baselines"),
    (dict(decay=DecayModel(5.0, 5.0, 11.0, ())), "decay_digest_mismatch"),
    (dict(fill_model=PricePathFillModel("at_price")), "fill_model_mismatch"),
])
def test_a_scored_run_must_match_what_was_signed(tmp_path, monkeypatch, kwargs, reason):
    doc = document()
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(doc))
    arguments = dict(decay=DECAY, mode="scored", registration=doc, **SCORED_COST)
    arguments.update(kwargs)
    with pytest.raises((PreregRefused, runner.FrontierRefused), match=reason):
        runner.run([source(tmp_path)], **arguments)


class _OtherTable:
    table_digest = "8" * 64

    def estimate(self, context):
        return None


@pytest.mark.parametrize("cost,reason", [
    (dict(), "scored_requires_fill_cost_table"),
    (dict(cost_provider=ConstantFillCost(), context_builder=lambda **_: None), "scored_requires_fill_cost_table"),
    (dict(cost_provider=_OtherTable(), context_builder=lambda **_: None), "toxicity_table_mismatch"),
])
def test_a_scored_run_needs_the_registered_fill_cost_table(tmp_path, monkeypatch, cost, reason):
    """Round 3: the toxicity table, and whether one is used at all, is not a free parameter of a scored read."""
    doc = document()
    assert TOXICITY_LINE.strip() in doc.decode() and STUB_TABLE_DIGEST in doc.decode()
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(doc))
    with pytest.raises((PreregRefused, runner.FrontierRefused), match=reason):
        runner.run([source(tmp_path)], decay=DECAY, mode="scored", registration=doc, **cost)
    without_line = doc.replace(TOXICITY_LINE.encode(), b"")
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", registration_hash(without_line))
    with pytest.raises(PreregRefused, match="toxicity_table_mismatch"):
        runner.run([source(tmp_path, name="c")], decay=DECAY, mode="scored", registration=without_line,
                   **SCORED_COST)


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
    with pytest.raises(runner.FrontierRefused, match="context_builder_required"):
        runner.run([src], decay=DECAY, cost_provider=Provider(Estimate(.02)))


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


def test_a_quote_is_not_fillable_after_its_hold_lapses(tmp_path):
    def held(trade_second):
        s = Scenario(day=DAY, minutes=8)
        for market in s.markets:
            s.book(market, 0)  # one book only: the quote lapses HOLD_SECONDS after it
        s.trade("a", trade_second, price=".40", size="10")
        s.settle("a", 450, p=0)
        out = runner.run([bundle_source(s.bundle(tmp_path / str(trade_second)))], decay=DECAY, points=GRID[:1],
                         baselines=())["strategies"]
        return out[GRID[0].label], len(s.markets)
    assert held(runner.HOLD_SECONDS - 20)[0]["filled_shares"] == 10
    late, bands = held(runner.HOLD_SECONDS + 5)
    # no fill, and every band earned reward for exactly one hold and no longer
    assert late["filled_shares"] == 0 and late["quoted_seconds"] == runner.HOLD_SECONDS * bands


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

    result = runner.run([src], decay=DECAY, points=GRID[:1], baselines=(), cost_provider=Provider(Estimate(.02)),
                        context_builder=builder)
    strict = result["strategies"]
    assert strict[GRID[0].label]["adverse_cost"] == pytest.approx(10 * .02)
    assert strict[GRID[0].label]["cost_unavailable"] == 0
    assert result["cost_provider"].endswith(".Provider")
    assert contexts and set(contexts[0]) == {"condition_id", "at", "band", "strategy"}
    vetoed = runner.run([src], decay=DECAY, points=GRID[:1], baselines=("blind_re1",),
                        cost_provider=Provider(Estimate(.02, "SWEEP")), context_builder=builder)["strategies"]
    assert all(v["quotes"] == 0 and v["vetoes"] > 0 for v in vetoed.values())


class UnavailableProvider:
    """Like build 2 returning Unavailable: an object with no markout."""

    def estimate(self, context):
        return object()


def test_an_unavailable_cost_estimate_is_counted_not_silent(tmp_path):
    src = source(tmp_path)
    fallback = runner.run([src], decay=DECAY, points=GRID[:1], baselines=(), cost_provider=UnavailableProvider(),
                          context_builder=lambda **c: c)
    totals = fallback["strategies"][GRID[0].label]
    assert totals["cost_unavailable"] > 0
    assert totals["adverse_cost"] == pytest.approx(10 * CONSTANT_ADVERSE_MARKOUT)
    assert fallback["cost_provider"].endswith(".UnavailableProvider")
    constant = runner.run([src], decay=DECAY, points=GRID[:1], baselines=())
    assert constant["strategies"][GRID[0].label]["cost_unavailable"] > 0
    assert constant["cost_provider"] == "maker_core.frontier.seams.ConstantFillCost"
