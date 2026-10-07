"""Engine ruling F3: the horizon is refreshed at each market's local midnight (shadow-gate spec v3.2 §4.3, v3.3 §1,
§3.1 and §4). Fictional fixtures only; the dates are invented and outside every reserved or excluded window.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from types import MappingProxyType

import pytest

from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.replay.bundle import BundleError, Condition, sha256
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import DayPlan, DaySource, bundle_source, drive, record_from_row, run_plan, windows_of
from maker_core.replay.v2.reference import ReferenceEngine
from .fixtures.replay_scenario import Scenario

UTC = timezone.utc
NY, LA = "America/New_York", "America/Los_Angeles"
CONFIG = V2Config(hazard_per_minute=.001, debug=True, keep=True)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


# -- local_lead and the next local midnight (v3.3 §1) ---------------------------------------------------------
def test_local_lead_is_the_plugin_rule_on_the_market_local_date():
    from maker_core.replay.v2.day_roll import local_lead
    target = date(2026, 11, 1)
    assert local_lead(NY, target, utc(2026, 11, 1, 3, 59, 59)) == 1  # 23:59:59 EDT on 10-31
    assert local_lead(NY, target, utc(2026, 11, 1, 4)) == 0  # 00:00 EDT on 11-01
    assert local_lead(LA, date(2026, 11, 2), utc(2026, 11, 2, 7, 59, 59)) == 1  # 23:59:59 PST
    assert local_lead(LA, date(2026, 11, 2), utc(2026, 11, 2, 8)) == 0
    assert local_lead("UTC", target, utc(2026, 11, 1)) == 0


def test_next_local_midnight_follows_the_zone_rule_across_the_dst_night():
    from maker_core.replay.v2.day_roll import next_local_midnight
    assert next_local_midnight(NY, utc(2026, 10, 31, 12)) == utc(2026, 11, 1, 4)  # EDT
    assert next_local_midnight(NY, utc(2026, 11, 1, 4)) == utc(2026, 11, 2, 5)  # EST after the DST night
    assert next_local_midnight(LA, utc(2026, 11, 1, 12)) == utc(2026, 11, 2, 8)  # PST
    assert next_local_midnight("Europe/London", utc(2026, 10, 25, 12)) == utc(2026, 10, 26)  # GMT
    assert next_local_midnight("UTC", utc(2026, 11, 1)) == utc(2026, 11, 2)  # strictly after


def test_unknown_time_zone_is_refused():
    from maker_core.replay.v2.day_roll import DayRoll
    with pytest.raises(BundleError, match="unknown_time_zone"):
        DayRoll({"nyc": "Mars/Olympus_Mons"})


# -- A small hand-built day: one NYC condition, descriptor captured before local midnight --------------------
class Day:
    """Rows of one fictional UTC day for condition ``cid`` of market ``market`` (Scenario payload shapes)."""

    def __init__(self, day, market="nyc", cid="nyc-band"):
        self.scenario = Scenario(day=day, markets=(market,), minutes=24 * 60)
        self.scenario.records = []  # rebuilt below with explicit times
        self.scenario.cid = lambda _market: cid  # one condition ID across days, in every payload
        self.day, self.market, self.cid = day, market, cid
        self.desc = replace(self.scenario.descriptors[market], condition_id=cid)

    def add(self, seconds, kind, payload):
        self.scenario.add(self.market, kind, seconds, payload)

    def descriptor(self, seconds, horizon):
        self.add(seconds, "descriptor", dict(market=plain(self.desc), horizon_days=horizon))

    def source(self):
        rows = []
        for r in sorted(self.scenario.records, key=lambda r: (r["captured_at"], r["sequence"])):
            rows.append(dict(r, condition_id=self.cid))
        records = [record_from_row(r) for r in rows]
        start = self.scenario.start
        conditions = (Condition(self.cid, self.market, "fictional", start, start + timedelta(days=1)),)
        plan = DayPlan(self.day, conditions, windows_of(conditions, None), MappingProxyType({}), "synthetic",
                       MappingProxyType({"fixture": "0" * 64}))
        return DaySource(plan, lambda: iter(records))


def roll_items(sources, zones):
    from maker_core.replay.v2.day_roll import DayRoll
    roll = DayRoll(zones)
    out = []
    for source in sources:
        out.extend(roll.items(source))
    return roll, out


def test_derived_descriptor_at_local_midnight_carries_the_new_lead_and_is_otherwise_identical():
    d = Day(date(2026, 11, 1))
    d.descriptor(600, 1)  # 00:10Z = 20:10 EDT on 10-31: target 11-01
    d.add(5 * 3600, "info_event", {"events": []})
    roll, items = roll_items([d.source()], {"nyc": NY})
    derived = [(at, i) for at, batch in items for i in batch if i.derived]
    assert [(at, i.value.horizon_days, i.derived) for at, i in derived] == [(utc(2026, 11, 1, 4), 0, "local_midnight")]
    captured = [i for _, batch in items for i in batch if i.kind == "descriptor" and not i.derived][0]
    assert replace(derived[0][1].value, horizon_days=1) == captured.value
    assert derived[0][1].payload_sha256 != captured.payload_sha256
    assert derived[0][1].payload_sha256 == sha256(canonical_bytes(
        {"derived": "local_midnight", "from": captured.payload_sha256, "horizon_days": 0}))
    assert roll.emitted == [(utc(2026, 11, 1, 4), "nyc-band", 0, derived[0][1].payload_sha256)]


def test_a_new_lead_outside_zero_to_two_gets_no_refresh():
    d = Day(date(2026, 11, 1))
    d.descriptor(600, 3)  # target 11-03; at 11-01 local midnight the lead is 2 -> refreshed
    early = Day(date(2026, 11, 2), cid="nyc-band")
    early.descriptor(600, 4)  # 11-01 20:10 EDT + 4 = target 11-05; at 11-02 05:00Z the lead is 3 -> skipped
    _, items = roll_items([d.source()], {"nyc": NY})
    assert [i.value.horizon_days for _, b in items for i in b if i.derived] == [2]
    _, items = roll_items([early.source()], {"nyc": NY})
    assert [i for _, b in items for i in b if i.derived] == []
    late = Day(date(2026, 11, 2), cid="nyc-band")
    late.descriptor(600, 0)  # target 11-01; at 11-02 05:00Z the lead would be -1 -> no refresh
    _, items = roll_items([late.source()], {"nyc": NY})
    assert [i for _, b in items for i in b if i.derived] == []


def test_order_within_an_instant_is_derived_before_regular_and_regular_overrides():
    d = Day(date(2026, 11, 1))
    d.descriptor(600, 1)
    d.descriptor(4 * 3600, 1)  # a regular descriptor exactly at local midnight, still labelled 1
    _, items = roll_items([d.source()], {"nyc": NY})
    batch = dict(items)[utc(2026, 11, 1, 4)]
    assert [(i.kind, i.derived, i.value.horizon_days) for i in batch] == [("descriptor", "local_midnight", 0),
                                                                          ("descriptor", None, 1)]


def test_mutant_md7_derived_after_regular_is_caught(monkeypatch):
    from maker_core.replay.v2 import day_roll
    monkeypatch.setattr(day_roll, "_instant", lambda derived, regular: [*regular, *derived])
    with pytest.raises(AssertionError):
        test_order_within_an_instant_is_derived_before_regular_and_regular_overrides()


def test_refresh_spans_days_and_uses_the_zone_rule_on_the_dst_night():
    first, second = Day(date(2026, 10, 31)), Day(date(2026, 11, 1))
    first.descriptor(600, 2)  # 10-30 20:10 EDT + 2: target 11-01
    second.add(600, "info_event", {"events": []})
    _, items = roll_items([first.source(), second.source()], {"nyc": NY})
    assert [(at, i.value.horizon_days) for at, b in items for i in b if i.derived] == [
        (utc(2026, 10, 31, 4), 1), (utc(2026, 11, 1, 4), 0)]


def test_an_invalid_descriptor_stops_the_refresh():
    d = Day(date(2026, 11, 1))
    d.descriptor(600, 1)
    d.add(700, "descriptor", dict(market=plain(d.desc), horizon_days="not-a-number"))
    _, items = roll_items([d.source()], {"nyc": NY})
    assert [i for _, b in items for i in b if i.derived] == []


def test_a_market_without_a_time_zone_is_refused():
    d = Day(date(2026, 11, 1))
    d.descriptor(600, 1)
    with pytest.raises(BundleError, match="market_time_zone_unknown"):
        roll_items([d.source()], {"other": NY})


# -- Through the engine: the horizon read after local midnight is the new one ---------------------------------
def engine_day():
    d = Day(date(2026, 11, 1))
    d.descriptor(600, 1)  # target 11-01, labelled horizon 1 until the next captured descriptor
    d.add(600, "info_event", {"events": []})
    for minute in range(230, 252):  # 03:50Z-04:11Z, a changed book every minute so every minute wakes
        seconds = minute * 60
        if minute == 230:
            d.scenario.view(d.market, seconds, p=.5)
            d.scenario.terms(d.market, seconds)
        d.scenario.book(d.market, seconds, mid=D(".5") + (D(".01") if minute % 2 else 0))
    return d.source()


@pytest.mark.parametrize("engine", [EngineV2, ReferenceEngine], ids=["v2", "reference"])
def test_engine_reads_the_refreshed_horizon_after_local_midnight(engine):
    src = engine_day()
    e = engine(replace(CONFIG, debug=engine is EngineV2), run_plan([src]))
    drive([src], [e], time_zones={"nyc": NY})
    assert e.states["nyc-band"].latest["descriptor"].horizon_days == 0
    after = [d for d in e.decisions if d.at >= utc(2026, 11, 1, 4)]
    before = [d for d in e.decisions if d.at < utc(2026, 11, 1, 4)]
    assert any(d.decision.reasons[0] == "HORIZON_NOT_ELIGIBLE" for d in after)
    assert not any(d.decision.action in ("QUOTE", "HOLD") for d in after)
    assert any(d.decision.action in ("QUOTE", "HOLD") for d in before)
    assert not any("HORIZON_NOT_ELIGIBLE" in d.decision.reasons for d in before)


def test_refresh_is_not_a_wake_source():
    src = engine_day()
    with_roll, without = EngineV2(CONFIG, run_plan([src])), EngineV2(CONFIG, run_plan([src]))
    from maker_core.replay.v2.day_roll import NO_REFRESH
    drive([src], [with_roll], time_zones={"nyc": NY})
    drive([src], [without], time_zones=NO_REFRESH)
    assert sorted({d.at for d in with_roll.decisions}) == sorted({d.at for d in without.decisions})
    assert with_roll.wakes == without.wakes


def test_engines_agree_with_the_refresh_on_a_multi_zone_fixture():
    from tools.research.maker_replay_v2.dense import DenseDay
    from tools.research.maker_replay_v2.sources import FIXTURE_ZONES, materialize
    from tools.research.maker_replay_v2.bench import fingerprint
    source, _ = materialize(DenseDay(date(2026, 11, 1), union=12, trades=2000, start_minute=225, minutes=40))
    plan = run_plan([source])
    v2, ref = EngineV2(CONFIG, plan), ReferenceEngine(replace(CONFIG, debug=False), plan)
    drive([source], [v2, ref], time_zones=FIXTURE_ZONES)
    assert fingerprint(v2) == fingerprint(ref)


def test_time_zones_are_required_by_drive():
    src = engine_day()
    with pytest.raises(TypeError):
        drive([src], [EngineV2(CONFIG, run_plan([src]))])


def test_mutant_mcf2_skipped_refresh_is_caught(monkeypatch):
    from maker_core.replay.v2 import day_roll
    monkeypatch.setattr(day_roll, "local_lead", lambda zone, target, instant: 99)  # every refresh out of scope
    with pytest.raises(AssertionError):
        test_engine_reads_the_refreshed_horizon_after_local_midnight(EngineV2)
