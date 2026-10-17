"""Item 330 build 2: COUNTERFACTUAL toxicity table, fill-cost provider and evidence embargo.

Guards: the COUNTERFACTUAL toxicity table and fill-cost provider (golden table hash, point-in-time features, veto
  cancel/widen, never below the constant markout floor), the evidence_embargo windows, and the maker import boundaries.
"""
import copy
from dataclasses import asdict, fields, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import importlib.util
import json
import math
from pathlib import Path

import pytest

from maker_core.contracts import Unavailable
from maker_core.contracts.evidence_embargo import (
    EXAM_EMBARGO, FIT_LAST_DATE, SCORED_PANEL, EmbargoRefused, refusal, refuse,
)
from maker_core.quoting import fill_cost as fc
from maker_core.quoting.fill_cost import (
    CONSTANT_ADVERSE_MARKOUT, ConstantFillCost, FillContext, FillCostProvider, PointInTimeError,
    TableFillCostProvider, apply_fill_cost, decide_with_fill_cost, levels, validate_table,
)
from maker_core.evidence.journal import digest
from maker_core.quoting.policy import Book, DecisionInputs, decide
from maker_core.replay import toxicity as tx
from .fixtures.fictional_domain import T0
from .fixtures.toxicity_synthetic import synthetic_records

ROOT = Path(__file__).resolve().parents[2]
FROZEN = Path(__file__).with_name("fixtures") / "toxicity_frozen.jsonl"
GOLDEN_TABLE_DIGEST = "43ca8fd96ad8e03c8602b16522fd5cc6838bbfd4119d2a6842f5a5bd21954fce"
# digest(asdict(estimate)) on the planted table, first fill context per flow state: SUPPORTED envelopes.
GOLDEN_ENVELOPES = {
    "calm": "8e6b5f91d9c5ce8b16de88fd5ab3b18e1df0de1a471ca91f6d2c9c30de2f49a0",
    "burst": "80b78e306515f0dd696d429d53bf7003ce38b2f7b7313ee8e0630215fe6a6b5e",
    "sweep": "76beffaba67bcc2bba84e69abc77ed62001c0ca355f7482e83267dc714fceddd",
}
UTC = timezone.utc


@pytest.fixture(scope="module")
def planted():
    minutes, fills = synthetic_records(dates=12, markets=12, minutes_per_cell=12, seed=11)
    return minutes, fills, tx.fit(minutes, fills, replicates=100)


def _row(table, dimension, level):
    return next(r for r in table["rows"] if (r["dimension"], r["level"]) == (dimension, level))


def _ctx(at, **overrides):
    values = dict(at_utc=at, maker_side="YES", horizon_days=1, minutes_to_close=600.0,
                  minutes_from_scheduled_print=20.0, minutes_since_model_cycle=120.0,
                  decided_probability=.4, book_imbalance=0.0, depth_shares=100.0, last_print_size=10.0,
                  burst_prints=0, sweep_bands=1, feature_times={"prints": at - timedelta(seconds=1)})
    values.update(overrides)
    return FillContext(**values)


# ---- planted regimes --------------------------------------------------------------------

def test_fit_recovers_planted_flow_and_clock_ordering(planted):
    _, _, table = planted
    assert table["label"] == "COUNTERFACTUAL" and table["table_version"] == fc.TABLE_VERSION
    calm, burst, sweep = (_row(table, "flow", lv) for lv in ("calm", "burst", "sweep"))
    assert calm["hazard"]["per_minute"] < burst["hazard"]["per_minute"] < sweep["hazard"]["per_minute"]
    assert calm["hazard"]["interval"][1] < burst["hazard"]["interval"][0]
    for h in fc.HORIZONS:
        assert calm["markout"][h]["mean_prob"] > 0 > burst["markout"][h]["mean_prob"]
        assert calm["markout"][h]["interval"][0] > sweep["markout"][h]["interval"][1]
    window, quiet = _row(table, "clock", "print_window"), _row(table, "clock", "quiet")
    assert window["markout"]["settlement"]["mean_prob"] < quiet["markout"]["settlement"]["mean_prob"]
    assert table["fit_window"]["last_date"] <= FIT_LAST_DATE.isoformat()


def test_envelope_orders_toxic_above_benign_and_vetoes(planted):
    _, fills, table = planted
    provider = TableFillCostProvider(table)
    assert isinstance(provider, FillCostProvider)
    by_flow = {}
    for f in fills:
        by_flow.setdefault(fc.flow_state(f.context), f.context)
    calm, burst, sweep = (provider.estimate(by_flow[k]) for k in ("calm", "burst", "sweep"))
    assert calm.veto is None and burst.veto == "BURST" and sweep.veto == "SWEEP"
    assert CONSTANT_ADVERSE_MARKOUT <= calm.adverse_markout_upper < sweep.adverse_markout_upper
    assert calm.hazard_per_minute_upper < sweep.hazard_per_minute_upper
    assert all(e.label == "COUNTERFACTUAL" and e.status == "OK" for e in (calm, burst, sweep))


def test_benign_table_never_lowers_the_constant_floor():
    minutes, fills = synthetic_records(dates=10, markets=10, minutes_per_cell=10, seed=5)
    benign = [replace(f, settlement_p_yes=(.9 if f.maker_side == "YES" else .1),
                      marks={h: replace(m, mid_yes=(.9 if f.maker_side == "YES" else .1)) for h, m in f.marks.items()})
              for f in fills]
    estimate = TableFillCostProvider(tx.fit(minutes, benign, replicates=100)).estimate(benign[0].context)
    assert estimate.adverse_markout_upper == CONSTANT_ADVERSE_MARKOUT


# ---- clustered inference ------------------------------------------------------------------

def test_underpowered_below_ten_clusters_ok_at_ten():
    small = tx.fit(*synthetic_records(dates=9, markets=10, minutes_per_cell=8, seed=3), replicates=100)
    full = tx.fit(*synthetic_records(dates=10, markets=10, minutes_per_cell=8, seed=3), replicates=100)
    assert small["counts"]["date_clusters"] == 9
    assert _row(small, "pooled", "all")["hazard"]["status"] == "UNDERPOWERED"
    assert _row(full, "pooled", "all")["hazard"]["status"] == "OK"
    narrow = tx.fit(*synthetic_records(dates=10, markets=9, minutes_per_cell=8, seed=3), replicates=100)
    assert _row(narrow, "pooled", "all")["hazard"]["status"] == "UNDERPOWERED"
    estimate = TableFillCostProvider(small).estimate(_ctx(datetime(2026, 9, 1, 15, tzinfo=UTC)))
    assert estimate.status == "UNDERPOWERED"


# ---- golden ---------------------------------------------------------------------------------

def test_golden_table_hash_on_frozen_fixture():
    minutes, fills = tx.read_records(FROZEN)
    table = tx.fit(minutes, fills, replicates=100)
    assert tx.table_digest(table) == GOLDEN_TABLE_DIGEST
    assert tx.fit(minutes, fills, replicates=100) == table
    assert json.loads(json.dumps(table)) == table


def _first_fill_per_flow(fills):
    by_flow = {}
    for f in fills:
        by_flow.setdefault(fc.flow_state(f.context), f)
    return by_flow


def test_golden_supported_envelopes(planted):
    _, fills, table = planted
    provider = TableFillCostProvider(table)
    by_flow = _first_fill_per_flow(fills)
    for flow, expected in GOLDEN_ENVELOPES.items():
        estimate = provider.estimate(by_flow[flow].context)
        assert estimate.status == "OK" and estimate.hazard_per_minute_upper is not None
        assert digest(asdict(estimate)) == expected, flow
    calm = provider.estimate(by_flow["calm"].context)
    assert calm.hazard_per_minute_upper == pytest.approx(.1733542644)
    assert calm.adverse_markout_upper == pytest.approx(.0640643615)


def test_cli_fit_is_create_only(tmp_path):
    out = tmp_path / "table.json"
    assert tx.main(["fit", "--input", str(FROZEN), "--output", str(out), "--replicates", "100"]) == 0
    assert tx.table_digest(json.loads(out.read_text(encoding="utf-8"))) == GOLDEN_TABLE_DIGEST
    with pytest.raises(FileExistsError):
        tx.main(["fit", "--input", str(FROZEN), "--output", str(out), "--replicates", "100"])


# ---- point in time ----------------------------------------------------------------------------

def test_feature_after_fill_raises():
    at = datetime(2026, 9, 2, 15, tzinfo=UTC)
    with pytest.raises(PointInTimeError):
        _ctx(at, feature_times={"book": at + timedelta(seconds=1)})
    with pytest.raises(PointInTimeError):
        _ctx(at, minutes_since_model_cycle=-1.0)
    # A print exactly at the instant is the triggering print: it must not enter its own context.
    with pytest.raises(PointInTimeError, match="strictly before"):
        _ctx(at, feature_times={"prints": at})
    _ctx(at, feature_times={"prints": at - timedelta(microseconds=1), "book": at})
    minutes, fills = synthetic_records(dates=1, markets=1, minutes_per_cell=40, seed=2)
    fill = fills[0]
    with pytest.raises(PointInTimeError):
        replace(fill, context=replace(fill.context, at_utc=fill.fill_at_utc + timedelta(seconds=1)))
    early = dict(fill.marks, **{"5m": replace(fill.marks["5m"], observed_at_utc=fill.fill_at_utc + timedelta(seconds=299))})
    with pytest.raises(PointInTimeError):
        replace(fill, marks=early)
    with pytest.raises(PointInTimeError):
        replace(fill, context=replace(fill.context, feature_times=dict(fill.context.feature_times,
                                                                       prints=fill.fill_at_utc)))
    with pytest.raises(PointInTimeError):
        replace(minutes[0], context=replace(minutes[0].context, at_utc=minutes[0].minute_utc + timedelta(seconds=1)))


def test_settlement_needs_its_own_observation_time():
    _, fills = synthetic_records(dates=1, markets=1, minutes_per_cell=40, seed=2)
    fill = fills[0]
    assert fill.settlement_observed_at_utc in fill.dates()
    assert None not in replace(fill, settlement_p_yes=None, settlement_observed_at_utc=None).dates()
    with pytest.raises(tx.ToxicityError, match="settlement_needs_observation_time"):
        replace(fill, settlement_observed_at_utc=None)
    with pytest.raises(tx.ToxicityError, match="settlement_needs_observation_time"):
        replace(fill, settlement_p_yes=None)
    assert replace(fill, settlement_p_yes=None, settlement_observed_at_utc=None).markout("settlement") is None
    with pytest.raises(PointInTimeError):
        replace(fill, settlement_observed_at_utc=fill.fill_at_utc - timedelta(seconds=1))
    assert tx.parse_record(tx.record_payload(fill)) == fill


def test_fit_refuses_unidentified_records():
    minutes, fills = synthetic_records(dates=1, markets=1, minutes_per_cell=40, seed=2)
    with pytest.raises(tx.ToxicityError, match="fill_without_exposure_minute"):
        tx.fit([m for m in minutes if m.minute_utc != fills[0].minute_utc], fills, replicates=100)
    with pytest.raises(tx.ToxicityError, match="duplicate_fill"):
        tx.fit(minutes, fills + fills[:1], replicates=100)
    with pytest.raises(tx.ToxicityError, match="non_counterfactual_record"):
        replace(fills[0], basis="own_fill")


def test_context_after_decision_instant_raises(inputs):
    with pytest.raises(PointInTimeError):
        apply_fill_cost(inputs, ConstantFillCost(), _ctx(T0 + timedelta(seconds=1)))


def test_market_price_never_enters_fair_value_or_context(inputs, planted):
    names = {f.name for f in fields(FillContext)}
    assert not {"mid", "mid_yes", "bid", "ask", "market_price", "price"} & names
    provider, ctx = TableFillCostProvider(planted[2]), _ctx(T0)
    adjusted, mapped = apply_fill_cost(inputs, provider, ctx)
    assert adjusted.fair_value is inputs.fair_value and adjusted.book is inputs.book
    assert adjusted.adverse_markout > CONSTANT_ADVERSE_MARKOUT
    # Behavioural: inputs that differ only in book prices map to identical fill inputs and fair value.
    for bid, ask in ((".20", ".22"), (".79", ".81")):
        bids, asks = ((D(bid), D(100)),), ((D(ask), D(100)),)
        moved = replace(inputs, book=Book(T0, bids, asks, bids, asks))
        assert moved.book != inputs.book
        moved_adjusted, moved_mapped = apply_fill_cost(moved, provider, ctx)
        assert moved_mapped == mapped
        assert moved_adjusted.fair_value == adjusted.fair_value
        assert (moved_adjusted.hazard_per_minute, moved_adjusted.adverse_markout) == (
            adjusted.hazard_per_minute, adjusted.adverse_markout)


# ---- differential: Unavailable == today's constant path --------------------------------------

def test_constant_default_matches_policy():
    assert DecisionInputs.__dataclass_fields__["adverse_markout"].default == CONSTANT_ADVERSE_MARKOUT


@pytest.mark.parametrize("hazard", [None, 0.0, .001, .02, .5])
@pytest.mark.parametrize("markout", [CONSTANT_ADVERSE_MARKOUT, .01])
@pytest.mark.parametrize("horizon", [0, 1, 2])
def test_unavailable_fallback_equals_constant_path(inputs, hazard, markout, horizon):
    base = replace(inputs, hazard_per_minute=hazard, adverse_markout=markout, horizon_days=horizon)
    adjusted, mapped = apply_fill_cost(base, ConstantFillCost(), _ctx(T0))
    assert adjusted is base and mapped.source == "constant_fallback" and mapped.veto is None
    assert decide_with_fill_cost(base, ConstantFillCost(), _ctx(T0)) == decide(base)


def test_unsupported_table_is_unavailable(inputs):
    minutes, fills = synthetic_records(dates=2, markets=2, minutes_per_cell=3, seed=4)
    provider = TableFillCostProvider(tx.fit(minutes, fills, replicates=100))
    assert isinstance(provider.estimate(_ctx(T0)), Unavailable)
    assert decide_with_fill_cost(inputs, provider, _ctx(T0)) == decide(inputs)
    vetoed = provider.estimate(_ctx(T0, sweep_bands=3))
    assert vetoed.veto == "SWEEP" and vetoed.status == "UNSUPPORTED"
    assert vetoed.adverse_markout_upper == CONSTANT_ADVERSE_MARKOUT


def test_veto_withdraws_quote(inputs, planted):
    # An unsupported table leaves both bounds at the caller's values, isolating the veto.
    provider = TableFillCostProvider(tx.fit(*synthetic_records(dates=2, markets=2, minutes_per_cell=3, seed=4),
                                            replicates=100))
    assert decide(inputs).action == "QUOTE"
    for overrides, veto in (({"burst_prints": 5}, "BURST"), ({"sweep_bands": 3}, "SWEEP")):
        decision = decide_with_fill_cost(inputs, provider, _ctx(T0, **overrides))
        assert decision.action == "NO_QUOTE" and decision.legs == ()
        assert decision.reasons == (f"FILL_COST_VETO_{veto}",)
    assert decide_with_fill_cost(inputs, provider, _ctx(T0)) == decide(inputs)
    calm = decide_with_fill_cost(inputs, TableFillCostProvider(planted[2]), _ctx(T0))
    assert calm.input_hash != decide(inputs).input_hash  # A supported envelope tightened the inputs.


def _unsupported_provider():
    return TableFillCostProvider(tx.fit(*synthetic_records(dates=2, markets=2, minutes_per_cell=3, seed=4),
                                        replicates=100))


def test_veto_cancel_is_the_default_and_widen_moves_legs_out(inputs):
    provider, sweep = _unsupported_provider(), _ctx(T0, sweep_bands=3)
    base = decide(inputs)
    assert base.action == "QUOTE" and base.legs
    assert decide_with_fill_cost(inputs, provider, sweep) == decide_with_fill_cost(
        inputs, provider, sweep, veto_action="cancel")
    widened = decide_with_fill_cost(inputs, provider, sweep, veto_action="widen", widen_ticks=2)
    tick = inputs.market.tick
    assert widened.action == "QUOTE" and len(widened.legs) == len(base.legs)
    for before, after in zip(base.legs, widened.legs):
        assert (after.outcome, after.size) == (before.outcome, before.size)
        assert after.price == before.price - 2 * tick
    assert widened.reasons == (*base.reasons, "FILL_COST_VETO_SWEEP_WIDENED")
    assert widened.share_many == 0.0 and widened.net_per_minute == 0.0
    # No veto: the widen path is identical to the plain decision.
    assert decide_with_fill_cost(inputs, provider, _ctx(T0), veto_action="widen") == decide(inputs)


def test_widen_past_the_book_withdraws(inputs):
    provider, burst = _unsupported_provider(), _ctx(T0, burst_prints=5)
    base = decide(inputs)
    ticks = int(max(leg.price for leg in base.legs) / inputs.market.tick)
    withdrawn = decide_with_fill_cost(inputs, provider, burst, veto_action="widen", widen_ticks=ticks)
    assert withdrawn.action == "NO_QUOTE" and withdrawn.legs == ()
    assert withdrawn.reasons == ("FILL_COST_VETO_BURST",)
    for bad in ({"veto_action": "ignore"}, {"veto_action": "widen", "widen_ticks": 0},
                {"veto_action": "widen", "widen_ticks": 1.5}):
        with pytest.raises(ValueError):
            decide_with_fill_cost(inputs, provider, burst, **bad)


def test_mapping_only_raises_bounds():
    estimate = fc.FillCostEstimate(.0001, .02, None, "OK", "d", ())
    mapped = fc.policy_fill_inputs(estimate, caller_hazard=.01, caller_markout=.03)
    assert (mapped.hazard_per_minute, mapped.adverse_markout) == (.01, .03)
    mapped = fc.policy_fill_inputs(estimate, caller_hazard=.00001)
    assert (mapped.hazard_per_minute, mapped.adverse_markout) == (.0001, .02)
    # The table only raises an existing bound: a missing or non-finite caller hazard is kept, so the
    # policy's MISSING_CONSERVATIVE_FILL_BOUND refusal still fires.
    mapped = fc.policy_fill_inputs(estimate, caller_hazard=None)
    assert (mapped.hazard_per_minute, mapped.adverse_markout) == (None, .02)
    mapped = fc.policy_fill_inputs(estimate, caller_hazard=float("nan"))
    assert math.isnan(mapped.hazard_per_minute) and mapped.adverse_markout == .02
    with pytest.raises(ValueError):
        fc.FillCostEstimate(.1, .001, None, "OK", "d", ())
    with pytest.raises(ValueError):
        fc.FillCostEstimate(.1, .01, None, "OK", "d", (), label="f")


# ---- embargo: every dated entry point ----------------------------------------------------------

def test_embargo_windows():
    assert EXAM_EMBARGO == (date(2026, 9, 30), date(2026, 10, 15))
    assert SCORED_PANEL == (date(2026, 9, 30), date(2026, 11, 13)) and FIT_LAST_DATE == date(2026, 9, 29)
    for purpose in ("read", "fit", "scored"):
        assert refusal("2026-09-29", purpose) is None
        for day in ("2026-09-30", "2026-10-07", "2026-10-15T23:59:00+00:00"):
            assert refusal(day, purpose).startswith("EMBARGO_EXAM_WINDOW")
    assert refusal("2026-10-16", "read") is None
    assert refusal("2026-10-16", "fit").startswith("EMBARGO_FIT_AFTER_2026-09-29")
    assert refusal("2026-11-13", "scored").startswith("EMBARGO_SCORED_PANEL")
    assert refusal("2026-11-14", "scored") is None
    with pytest.raises(EmbargoRefused):
        refuse(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC), purpose="read")
    with pytest.raises(ValueError):
        refusal("2026-09-01", "peek")


def test_embargo_refuses_undated_and_naive_values():
    for purpose in ("read", "fit", "scored"):
        with pytest.raises(EmbargoRefused, match="EMBARGO_UNDATED"):
            refuse(None, purpose=purpose)
        with pytest.raises(EmbargoRefused, match="EMBARGO_UNDATED"):
            refuse(datetime(2026, 9, 1, tzinfo=UTC), None, purpose=purpose)
        with pytest.raises(EmbargoRefused, match="EMBARGO_NAIVE_DATETIME"):
            refuse(datetime(2026, 9, 1, 12), purpose=purpose)
        with pytest.raises(EmbargoRefused, match="EMBARGO_NAIVE_DATETIME"):
            refusal("2026-09-01T12:00:00", purpose)


def test_embargo_converts_aware_datetimes_to_utc():
    plus2, minus4 = timezone(timedelta(hours=2)), timezone(timedelta(hours=-4))
    # 09-30 01:30 at +02:00 is 09-29 23:30 UTC: before the exam window and fittable.
    early = datetime(2026, 9, 30, 1, 30, tzinfo=plus2)
    for purpose in ("read", "fit", "scored"):
        assert refusal(early, purpose) is None
        assert refusal("2026-09-30T01:30:00+02:00", purpose) is None
    refuse(early, purpose="fit")
    # 09-29 23:00 at -04:00 is 09-30 03:00 UTC: inside the exam window.
    assert refusal(datetime(2026, 9, 29, 23, tzinfo=minus4), "read") == "EMBARGO_EXAM_WINDOW:2026-09-30"
    # 10-16 01:00 at +02:00 is 10-15 23:00 UTC: still inside; 03:00 at +02:00 is out for a read.
    assert refusal(datetime(2026, 10, 16, 1, tzinfo=plus2), "read") == "EMBARGO_EXAM_WINDOW:2026-10-15"
    assert refusal(datetime(2026, 10, 16, 3, tzinfo=plus2), "read") is None


def _shift(record, days):
    delta = timedelta(days=days)
    ctx = replace(record.context, at_utc=record.context.at_utc + delta,
                  feature_times={k: v + delta for k, v in record.context.feature_times.items()})
    if isinstance(record, tx.QuoteMinute):
        return replace(record, event_date=record.event_date + delta, minute_utc=record.minute_utc + delta, context=ctx)
    return replace(record, event_date=record.event_date + delta, minute_utc=record.minute_utc + delta,
                   fill_at_utc=record.fill_at_utc + delta, context=ctx,
                   marks={h: replace(m, observed_at_utc=m.observed_at_utc + delta) for h, m in record.marks.items()},
                   settlement_observed_at_utc=(None if record.settlement_observed_at_utc is None
                                               else record.settlement_observed_at_utc + delta))


@pytest.mark.parametrize("target,code", [(date(2026, 10, 3), "EMBARGO_EXAM_WINDOW"),
                                         (date(2026, 10, 16), "EMBARGO_FIT_AFTER"),
                                         (date(2026, 12, 1), "EMBARGO_FIT_AFTER")])
def test_fit_refuses_embargoed_dates(target, code):
    minutes, fills = synthetic_records(dates=1, markets=1, minutes_per_cell=20, seed=2)
    days = (target - minutes[0].event_date).days
    with pytest.raises(EmbargoRefused, match=code):
        tx.fit(minutes + [_shift(minutes[0], days)], fills, replicates=100)
    with pytest.raises(EmbargoRefused, match=code):
        tx.fit(minutes, fills + [_shift(fills[0], days)], replicates=100)


def test_fit_refuses_a_mark_that_crosses_into_the_embargo():
    minutes, fills = synthetic_records(dates=1, markets=1, minutes_per_cell=20, seed=2, first=date(2026, 9, 29))
    fill = fills[0]
    shifted = fill.context
    moved = datetime(2026, 9, 29, 23, 59, 30, tzinfo=UTC)
    delta = moved - fill.fill_at_utc
    fill = replace(fill, minute_utc=fill.minute_utc + delta, fill_at_utc=moved,
                   context=replace(shifted, at_utc=moved, feature_times={k: v + delta for k, v in shifted.feature_times.items()}),
                   marks={h: replace(m, observed_at_utc=m.observed_at_utc + delta) for h, m in fill.marks.items()},
                   settlement_observed_at_utc=moved)
    minute = replace(minutes[0], minute_utc=fill.minute_utc, condition_id=fill.condition_id,
                     context=replace(minutes[0].context, maker_side=fill.maker_side,
                                     at_utc=fill.minute_utc, feature_times={}))
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW:2026-09-30"):
        tx.fit([*minutes, minute], [fill], replicates=100)


def test_fit_refuses_a_settlement_read_inside_the_embargo():
    # A 09-29 event whose settlement was observed on 09-30 is not fittable (conservative).
    minutes, fills = synthetic_records(dates=1, markets=1, minutes_per_cell=20, seed=2, first=date(2026, 9, 29))
    assert tx.fit(minutes, fills, replicates=100)["fit_window"]["last_date"] == "2026-09-29"
    late = replace(fills[0], settlement_observed_at_utc=datetime(2026, 9, 30, 1, tzinfo=UTC))
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW:2026-09-30"):
        tx.fit(minutes, [late, *fills[1:]], replicates=100)


def _write(path, records):
    path.write_text("".join(json.dumps(tx.record_payload(r), sort_keys=True) + "\n" for r in records),
                    encoding="utf-8")
    return path


def test_read_records_and_cli_refuse_embargoed_dates(tmp_path):
    minutes, fills = synthetic_records(dates=1, markets=1, minutes_per_cell=20, seed=2)
    exam = _write(tmp_path / "exam.jsonl", [_shift(minutes[0], 35)])        # 2026-10-06
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW"):
        tx.read_records(exam)
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW"):
        tx.main(["fit", "--input", str(exam), "--output", str(tmp_path / "a.json"), "--replicates", "100"])
    later = _write(tmp_path / "later.jsonl", [_shift(minutes[0], 50)])      # 2026-10-21: readable, not fittable
    assert len(tx.read_records(later)[0]) == 1
    with pytest.raises(EmbargoRefused, match="EMBARGO_FIT_AFTER"):
        tx.main(["fit", "--input", str(later), "--output", str(tmp_path / "b.json"), "--replicates", "100"])
    assert not (tmp_path / "a.json").exists() and not (tmp_path / "b.json").exists()
    payload = tx.record_payload(_shift(minutes[0], 35))
    with pytest.raises(EmbargoRefused):
        tx.parse_record(payload)


def test_score_table_refuses_scored_panel(planted):
    _, fills, table = planted
    with pytest.raises(EmbargoRefused, match="EMBARGO_SCORED_PANEL"):
        tx.score_table(table, [_shift(fills[0], 61)])                      # 2026-11-01
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW"):
        tx.score_table(table, [_shift(fills[0], 35)])
    report = tx.score_table(table, [_shift(f, 80) for f in fills[:50]])     # after 11-13
    assert report["label"] == "COUNTERFACTUAL" and report["scored_fills"] == 50
    assert 0 <= report["envelope_coverage"] <= 1


def _with_loss(fill, loss, fill_id):
    token = fill.price - loss
    return replace(fill, fill_id=fill_id, settlement_p_yes=(token if fill.maker_side == "YES" else 1 - token))


def test_score_table_coverage_is_exact(planted):
    _, fills, table = planted
    calm = _shift(_first_fill_per_flow(fills)["calm"], 80)
    envelope = TableFillCostProvider(table).estimate(calm.context).adverse_markout_upper
    inside, outside = _with_loss(calm, envelope - .001, "in"), _with_loss(calm, envelope + .001, "out")
    assert -inside.markout("settlement") == pytest.approx(envelope - .001)
    report = tx.score_table(table, [inside, outside])
    assert (report["scored_fills"], report["envelope_coverage"]) == (2, .5)
    assert tx.score_table(table, [inside, inside])["envelope_coverage"] == 1.0
    assert tx.score_table(table, [outside])["envelope_coverage"] == 0.0
    unsettled = replace(inside, settlement_p_yes=None, settlement_observed_at_utc=None)
    assert tx.score_table(table, [unsettled]) == dict(report, scored_fills=0, envelope_coverage=None)


def test_provider_and_table_validation_refuse_embargoed_dates(planted):
    table = planted[2]
    provider = TableFillCostProvider(table)
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW"):
        provider.estimate(_ctx(datetime(2026, 10, 3, 15, tzinfo=UTC)))
    late_feature = _ctx(datetime(2026, 10, 16, 0, 0, 30, tzinfo=UTC),
                        feature_times={"prints": datetime(2026, 10, 15, 23, 59, tzinfo=UTC)})
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW"):
        provider.estimate(late_feature)
    for last in ("2026-10-16", "2026-10-01"):
        with pytest.raises(EmbargoRefused):
            validate_table(dict(table, fit_window=dict(table["fit_window"], last_date=last)))
    with pytest.raises(ValueError):
        validate_table(dict(table, label="f"))
    with pytest.raises(ValueError):
        validate_table(dict(table, spec=dict(table["spec"], sweep_min_bands=2)))


def test_table_version_requires_the_default_spec(planted):
    table = planted[2]
    other = dict(table["spec"], sweep_min_bands=2)
    consistent = dict(table, spec=other, spec_digest=digest(other))
    with pytest.raises(ValueError, match="requires the default spec"):
        validate_table(consistent)
    with pytest.raises(ValueError, match="requires the default spec"):
        TableFillCostProvider(consistent)


def test_each_markout_cell_is_gated_on_its_own_fills(planted):
    _, fills, table = planted
    ctx = _first_fill_per_flow(fills)["calm"].context
    baseline = TableFillCostProvider(table).estimate(ctx).adverse_markout_upper
    assert baseline < .5

    def planted_cell(cell_fills):
        edited = copy.deepcopy(table)
        row = _row(edited, "flow", "calm")
        assert row["fills"] >= fc.DEFAULT_SPEC.min_fills_per_row
        row["markout"]["settlement"] = dict(row["markout"]["settlement"], fills=cell_fills, interval=[-.5, -.4])
        return TableFillCostProvider(edited).estimate(ctx)

    assert planted_cell(fc.DEFAULT_SPEC.min_fills_per_row - 1).adverse_markout_upper < .5
    assert planted_cell(fc.DEFAULT_SPEC.min_fills_per_row).adverse_markout_upper == .5


# ---- boundaries ----------------------------------------------------------------------------------

def test_new_modules_respect_maker_boundaries():
    spec = importlib.util.spec_from_file_location(
        "toxicity_import_architecture", ROOT / "tests" / "operations" / "test_import_architecture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for relative, name in (("src/maker_core/contracts/evidence_embargo.py", "maker_core.contracts.evidence_embargo"),
                           ("src/maker_core/quoting/fill_cost.py", "maker_core.quoting.fill_cost"),
                           ("src/maker_core/replay/toxicity.py", "maker_core.replay.toxicity"),
                           ("src/weather/market/maker_plugin/toxicity_features.py",
                            "weather.market.maker_plugin.toxicity_features")):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert module.maker_boundary_violations(source, name) == [], relative
    policy = (ROOT / "src/maker_core/quoting/policy.py").read_text(encoding="utf-8")
    assert "fill_cost" not in policy and "toxicity" not in policy


def test_levels_cover_every_dimension():
    labels = levels(_ctx(datetime(2026, 9, 2, 15, tzinfo=UTC), minutes_from_scheduled_print=-2.0,
                         decided_probability=None, book_imbalance=-.9, maker_side="NO", depth_shares=10.0,
                         last_print_size=0.0, horizon_days=0, minutes_to_close=30.0))
    assert labels == {"clock": "print_window", "decided": "unknown", "close": "lt6h", "horizon": "T+0",
                      "imbalance": "with", "depth": "thin", "print": "none", "flow": "calm"}
