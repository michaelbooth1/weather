"""Item 330 build 2: COUNTERFACTUAL toxicity table, fill-cost provider and evidence embargo."""
from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
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
from maker_core.quoting.policy import DecisionInputs, decide
from maker_core.replay import toxicity as tx
from .fixtures.fictional_domain import T0
from .fixtures.toxicity_synthetic import synthetic_records

ROOT = Path(__file__).resolve().parents[2]
FROZEN = Path(__file__).with_name("fixtures") / "toxicity_frozen.jsonl"
GOLDEN_TABLE_DIGEST = "f3043040f5de0e352982c82af377e59fc7d048a7a46f638597fafe772235b1c3"
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
    minutes, fills = synthetic_records(dates=1, markets=1, minutes_per_cell=40, seed=2)
    fill = fills[0]
    with pytest.raises(PointInTimeError):
        replace(fill, context=replace(fill.context, at_utc=fill.fill_at_utc + timedelta(seconds=1)))
    early = dict(fill.marks, **{"5m": replace(fill.marks["5m"], observed_at_utc=fill.fill_at_utc + timedelta(seconds=299))})
    with pytest.raises(PointInTimeError):
        replace(fill, marks=early)
    with pytest.raises(PointInTimeError):
        replace(minutes[0], context=replace(minutes[0].context, at_utc=minutes[0].minute_utc + timedelta(seconds=1)))


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
    assert not any("price" in n and n != "decided_probability" for n in names - {"last_print_size"})
    assert not {"mid", "mid_yes", "bid", "ask", "market_price"} & names
    adjusted, _ = apply_fill_cost(inputs, TableFillCostProvider(planted[2]), _ctx(T0))
    assert adjusted.fair_value is inputs.fair_value and adjusted.book is inputs.book
    assert adjusted.adverse_markout > CONSTANT_ADVERSE_MARKOUT


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


def test_mapping_only_raises_bounds():
    estimate = fc.FillCostEstimate(.0001, .02, None, "OK", "d", ())
    mapped = fc.policy_fill_inputs(estimate, caller_hazard=.01, caller_markout=.03)
    assert (mapped.hazard_per_minute, mapped.adverse_markout) == (.01, .03)
    mapped = fc.policy_fill_inputs(estimate, caller_hazard=None)
    assert (mapped.hazard_per_minute, mapped.adverse_markout) == (.0001, .02)
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
        refuse(None, datetime(2026, 10, 1, tzinfo=UTC), purpose="read")
    with pytest.raises(ValueError):
        refusal("2026-09-01", "peek")
    with pytest.raises(ValueError):
        refusal(datetime(2026, 9, 29, 23, tzinfo=timezone(timedelta(hours=-4))), "read")


def _shift(record, days):
    delta = timedelta(days=days)
    ctx = replace(record.context, at_utc=record.context.at_utc + delta,
                  feature_times={k: v + delta for k, v in record.context.feature_times.items()})
    if isinstance(record, tx.QuoteMinute):
        return replace(record, event_date=record.event_date + delta, minute_utc=record.minute_utc + delta, context=ctx)
    return replace(record, event_date=record.event_date + delta, minute_utc=record.minute_utc + delta,
                   fill_at_utc=record.fill_at_utc + delta, context=ctx,
                   marks={h: replace(m, observed_at_utc=m.observed_at_utc + delta) for h, m in record.marks.items()})


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
                   marks={h: replace(m, observed_at_utc=m.observed_at_utc + delta) for h, m in fill.marks.items()})
    minute = replace(minutes[0], minute_utc=fill.minute_utc, condition_id=fill.condition_id,
                     context=replace(minutes[0].context, maker_side=fill.maker_side,
                                     at_utc=fill.minute_utc, feature_times={}))
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW:2026-09-30"):
        tx.fit([*minutes, minute], [fill], replicates=100)


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
