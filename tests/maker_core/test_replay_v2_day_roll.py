"""Engine ruling F3: the horizon is refreshed at each market's local midnight (shadow-gate spec v3.2 §4.3, v3.3 §1,
§3.1 and §4). Fictional fixtures only; the dates are invented and outside every reserved or excluded window.

Guards: registration C13 (engine ruling F3, owner 2026-10-07), owner Gate Q1 zone source, and the Delta Defender
3bf0eef5c notes (a)-(d) on strict, coded and registry-checked zone names and the fall-back emitted schedule.
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


# -- Defender f0d97f11f note 5: engine-level fixtures across the DST change and east of UTC --------------------
def busy(d, first_minute, last_minute):
    """A changed book every minute from ``first_minute`` to ``last_minute``, with a view and terms renewed every
    30 minutes (terms older than an hour are a capture gap, which would mask the horizon refusal)."""
    for minute in range(first_minute, last_minute):
        if (minute - first_minute) % 30 == 0:
            d.scenario.view(d.market, minute * 60, p=.5)
            d.scenario.terms(d.market, minute * 60)
        d.scenario.book(d.market, minute * 60, mid=D(".5") + (D(".01") if minute % 2 else 0))


def horizon_refusals(e, start, end):
    return [d.decision.reasons[0] == "HORIZON_NOT_ELIGIBLE" for d in e.decisions if start <= d.at < end]


def dst_engine(first_day, second_day):
    """A New York descriptor captured once at 00:10Z on ``first_day`` (horizon 2), then a busy 03:50Z-05:12Z on
    ``second_day``; the only refreshes are the engine's local midnights, the second one across a DST change."""
    first, second = Day(first_day), Day(second_day)
    first.descriptor(600, 2)  # 00:10Z = 19:10 or 20:10 local the evening before: target second_day, never re-captured
    first.add(600, "info_event", {"events": []})
    second.add(0, "info_event", {"events": []})
    busy(second, 230, 312)  # 03:50Z-05:12Z on second_day: EDT midnight is 04:00Z, EST midnight 05:00Z
    sources = [first.source(), second.source()]
    e = EngineV2(CONFIG, run_plan(sources))
    drive(sources, [e], time_zones={"nyc": NY})
    return e


def test_engine_refresh_after_the_fall_back_uses_the_new_offset():
    e = dst_engine(date(2026, 11, 1), date(2026, 11, 2))  # EDT -> EST at 06:00Z on 11-01
    before = horizon_refusals(e, utc(2026, 11, 2, 3, 50), utc(2026, 11, 2, 5))
    after = horizon_refusals(e, utc(2026, 11, 2, 5), utc(2026, 11, 2, 5, 12))
    assert before and not any(before)  # 22:50-23:59 EST on 11-01: lead 1, eligible
    assert after and all(after)  # from 00:00 EST on 11-02: lead 0


def test_engine_refresh_after_the_spring_forward_uses_the_new_offset():
    e = dst_engine(date(2027, 3, 14), date(2027, 3, 15))  # EST -> EDT at 07:00Z on 03-14
    before = horizon_refusals(e, utc(2027, 3, 15, 3, 50), utc(2027, 3, 15, 4))
    after = horizon_refusals(e, utc(2027, 3, 15, 4), utc(2027, 3, 15, 5, 12))
    assert before and not any(before)  # 23:50-23:59 EDT on 03-14: lead 1, eligible
    assert after and all(after)  # from 00:00 EDT on 03-15 (04:00Z, not 05:00Z): lead 0


def test_mutant_fixed_offset_midnight_is_caught_by_the_engine_fixture(monkeypatch):
    """The previous midnight's UTC offset carried forward. After the fall-back it only adds a no-op refresh an
    hour early (lead still 1) and then refreshes on time, so the decisions cannot catch it there; the spring-forward
    fixture bites in decisions (the mutant refreshes an hour late), and the fall-back emitted-schedule test below
    catches its extra item and chained sha."""
    from maker_core.replay.v2 import day_roll

    def fixed_offset(zone, instant):
        local = instant.astimezone(day_roll._zone(zone) if isinstance(zone, str) else zone)
        midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time())
        return (midnight - local.utcoffset()).replace(tzinfo=UTC)
    monkeypatch.setattr(day_roll, "next_local_midnight", fixed_offset)
    test_engine_refresh_after_the_fall_back_uses_the_new_offset()  # the decisions alone cannot see it here
    with pytest.raises(AssertionError):
        test_engine_refresh_after_the_spring_forward_uses_the_new_offset()


TOKYO = "Asia/Tokyo"


def tokyo_engine():
    d = Day(date(2026, 11, 1), market="tky", cid="tky-band")
    d.descriptor(600, 1)  # 00:10Z 11-01 = 09:10 JST 11-01: target 11-02
    d.add(600, "info_event", {"events": []})
    busy(d, 890, 912)  # 14:50Z-15:12Z: local midnight 11-02 JST is 15:00Z on the UTC date 11-01
    src = d.source()
    e = EngineV2(CONFIG, run_plan([src]))
    drive([src], [e], time_zones={"tky": TOKYO})
    return e


def test_engine_lead_follows_the_local_date_east_of_utc():
    e = tokyo_engine()
    before = horizon_refusals(e, utc(2026, 11, 1, 14, 50), utc(2026, 11, 1, 15))
    after = horizon_refusals(e, utc(2026, 11, 1, 15), utc(2026, 11, 1, 15, 12))
    assert before and not any(before)
    assert after and all(after)


def test_mutant_utc_lead_is_caught_by_the_engine_fixture(monkeypatch):
    from maker_core.replay.v2 import day_roll
    monkeypatch.setattr(day_roll, "local_lead", lambda zone, target, instant: (target - instant.date()).days)
    with pytest.raises(AssertionError):
        test_engine_lead_follows_the_local_date_east_of_utc()


# -- Owner Gate Q1 (2026-10-07): the zone map comes from the bound universe inventory --------------------------
def zone_pack(tmp_path, zones):
    """One condition of market ``a`` per day from 2026-11-20, each with its inventory ``local_timezone``."""
    bundles, inventory = [], []
    for n, zone in enumerate(zones):
        day = date(2026, 11, 20) + timedelta(days=n)
        s = Scenario(day, markets=("a",), minutes=10)
        for r in s.records:
            if r["kind"] == "descriptor":
                r["payload"]["horizon_days"] = 1
                r["payload_sha256"] = sha256(canonical_bytes(r["payload"]))
        bundles.append(s.bundle(tmp_path / day.isoformat()))
        inventory.append(dict(condition_id=s.cid("a"), market_id="a", domain_id="fictional",
                              target_date=(day + timedelta(days=1)).isoformat(), local_timezone=zone))
    return bundles, sorted(inventory, key=lambda r: r["condition_id"])


def test_market_time_zones_come_from_the_validated_inventory(tmp_path):
    from maker_core.replay.execution_manifest import market_time_zones
    bundles, inventory = zone_pack(tmp_path, ["Europe/London", "Europe/London"])
    zones = market_time_zones(bundles, inventory, registered=REGISTERED)
    assert dict(zones) == {"a": "Europe/London"}
    from maker_core.replay.v2.day_roll import DayRoll
    DayRoll(zones)  # accepted by the reader as is


def test_market_whose_conditions_disagree_on_the_zone_is_refused(tmp_path):
    from maker_core.replay.execution_manifest import market_time_zones
    # Both zones are UTC+0 in November, so each row passes the close/horizon check on its own.
    bundles, inventory = zone_pack(tmp_path, ["UTC", "Europe/London"])
    with pytest.raises(BundleError, match="market_time_zone_disagreement"):
        market_time_zones(bundles, inventory, registered=REGISTERED)


def test_market_time_zones_refuse_a_zone_the_descriptors_contradict(tmp_path):
    from maker_core.replay.execution_manifest import market_time_zones
    bundles, inventory = zone_pack(tmp_path, ["America/New_York"])  # close 00:00Z is 19:00 EST, not local midnight
    with pytest.raises(BundleError, match="universe_target_descriptor_mismatch"):
        market_time_zones(bundles, inventory, registered=REGISTERED)


# -- Delta Defender 3bf0eef5c notes (a)-(d) and the NO_REFRESH guard -------------------------------------------
REGISTERED = MappingProxyType({"a": "Europe/London"})  # the fictional domain registry for market ``a``
BAD_NAMES = ["Mars/Olympus_Mons", "europe/london", "../zoneinfo/UTC", "Europe/London ", " Europe/London",
             "Europe/London\n", ""]


@pytest.mark.parametrize("name", BAD_NAMES, ids=repr)
def test_inventory_zone_lookup_failures_are_coded(tmp_path, name):
    """(a)+(b): an invalid, mis-cased, traversal or whitespace-padded name refuses with a coded BundleError on
    every platform (Windows' filesystem lookup accepted a trailing space)."""
    from maker_core.replay.execution_manifest import active_intervals, market_time_zones
    bundles, inventory = zone_pack(tmp_path, ["Europe/London"])
    inventory[0]["local_timezone"] = name
    with pytest.raises(BundleError, match="unknown_time_zone|incomplete_universe_binding"):
        active_intervals(bundles, inventory)  # every manifest path through the inventory check
    with pytest.raises(BundleError, match="unknown_time_zone|incomplete_universe_binding"):
        market_time_zones(bundles, inventory, registered={"a": name})


@pytest.mark.parametrize("name", [n for n in BAD_NAMES if n], ids=repr)
def test_day_roll_zone_names_are_strict(name):
    from maker_core.replay.v2.day_roll import DayRoll, local_lead, next_local_midnight
    with pytest.raises(BundleError, match="unknown_time_zone"):
        DayRoll({"a": name})
    with pytest.raises(BundleError, match="unknown_time_zone"):
        local_lead(name, date(2026, 11, 2), utc(2026, 11, 1))
    with pytest.raises(BundleError, match="unknown_time_zone"):
        next_local_midnight(name, utc(2026, 11, 1))


def test_strict_zone_accepts_canonical_names_and_aliases():
    from maker_core.replay.bundle import time_zone
    for name in ("Europe/London", "UTC", "GB", "Asia/Tokyo", "America/New_York"):
        assert time_zone(name).key == name


class _LenientZone:
    """A stand-in for a filesystem lookup that accepts any name (Windows accepted ``"Europe/London "``)."""

    def __init__(self, key):
        self.key = key


@pytest.mark.parametrize("name", ["Europe/London ", "Europe/London\n", "europe/london", "Mars/Olympus_Mons"], ids=repr)
def test_strict_zone_names_do_not_rely_on_the_platform_lookup(monkeypatch, name):
    """Delta Defender c70581325 N1: strictness is the listed-name membership check, not the platform's ``ZoneInfo``.

    Linux ``ZoneInfo`` already refuses these names, so without this stub a revert of the membership check
    (``bundle.time_zone``) or of ``day_roll._zone`` to a raw lookup would pass CI (ubuntu) and regress only on Windows.
    Since owner T1(a) the lookup is ``bundle.pinned_zone`` (the pinned tzdata bytes), so that is what the stub replaces.
    """
    from maker_core.replay import bundle
    from maker_core.replay.v2 import day_roll
    monkeypatch.setattr(bundle, "pinned_zone", _LenientZone)
    monkeypatch.setattr(day_roll, "ZoneInfo", _LenientZone)
    # positive control: the stub is the lookup actually used, so the refusals below are not vacuous
    assert isinstance(bundle.time_zone("Europe/London"), _LenientZone)
    assert isinstance(day_roll._zone("Europe/London"), _LenientZone)
    with pytest.raises(BundleError, match="unknown_time_zone"):
        bundle.time_zone(name)
    with pytest.raises(BundleError, match="unknown_time_zone"):
        day_roll._zone(name)
    with pytest.raises(BundleError, match="unknown_time_zone"):
        day_roll.DayRoll({"a": name})


def test_market_time_zones_require_the_domain_registry(tmp_path):
    from maker_core.replay.execution_manifest import market_time_zones
    bundles, inventory = zone_pack(tmp_path, ["Europe/London"])
    with pytest.raises(TypeError):
        market_time_zones(bundles, inventory)


def test_same_offset_wrong_zone_is_refused_by_the_registry(tmp_path):
    """(c): Africa/Abidjan equals London's offset in November, so the descriptor check alone passes it."""
    from maker_core.replay.execution_manifest import active_intervals, market_time_zones
    bundles, inventory = zone_pack(tmp_path, ["Africa/Abidjan"])
    active_intervals(bundles, inventory)  # the offset-only inventory check cannot tell
    with pytest.raises(BundleError, match="market_time_zone_registry_mismatch"):
        market_time_zones(bundles, inventory, registered=REGISTERED)


def test_market_missing_from_the_registry_is_refused(tmp_path):
    from maker_core.replay.execution_manifest import market_time_zones
    bundles, inventory = zone_pack(tmp_path, ["Europe/London"])
    with pytest.raises(BundleError, match="market_time_zone_unregistered"):
        market_time_zones(bundles, inventory, registered={"b": "Europe/London"})


class DerivedLog:
    """An observer recording every derived (local-midnight) item the lockstep emits."""

    def __init__(self):
        self.items = []

    def instant(self, at, batch):
        self.items.extend((at, i.condition_id, i.value.horizon_days, i.payload_sha256) for i in batch if i.derived)


def fall_back_schedule():
    first, second = Day(date(2026, 11, 1)), Day(date(2026, 11, 2))
    first.descriptor(600, 2)
    first.add(600, "info_event", {"events": []})
    second.add(0, "info_event", {"events": []})
    busy(second, 230, 312)
    sources = [first.source(), second.source()]
    log = DerivedLog()
    drive(sources, [EngineV2(CONFIG, run_plan(sources))], observers=(log,), time_zones={"nyc": NY})
    captured = next(r.payload_sha256 for r in first.source().records() if r.kind == "descriptor")
    return log.items, captured


def test_fall_back_emits_exactly_the_local_midnight_schedule():
    """(d): one derived item per local midnight (04:00Z EDT, then 05:00Z EST), each sha chained from the prior."""
    from maker_core.replay.v2.day_roll import derived_sha
    items, captured = fall_back_schedule()
    first = derived_sha(captured, 1)
    assert items == [(utc(2026, 11, 1, 4), "nyc-band", 1, first),
                     (utc(2026, 11, 2, 5), "nyc-band", 0, derived_sha(first, 0))]


def test_mutant_fixed_offset_midnight_is_caught_by_the_fall_back_schedule(monkeypatch):
    """The decisions cannot see this mutant after the fall-back; its extra 04:00Z item and chained sha can."""
    from maker_core.replay.v2 import day_roll

    def fixed_offset(zone, instant):
        local = instant.astimezone(day_roll._zone(zone) if isinstance(zone, str) else zone)
        midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time())
        return (midnight - local.utcoffset()).replace(tzinfo=UTC)
    monkeypatch.setattr(day_roll, "next_local_midnight", fixed_offset)
    with pytest.raises(AssertionError):
        test_fall_back_emits_exactly_the_local_midnight_schedule()


def test_scored_run_passes_refuse_no_refresh():
    """NO_REFRESH exists for the attribution re-run's pre-F3 variant (``lockstep.drive``); the scored entry point
    refuses it before any engine runs."""
    from maker_core.replay.v2.day_roll import NO_REFRESH
    from maker_core.replay.v2.pipeline import run_passes
    with pytest.raises(BundleError, match="day_roll_refresh_required"):
        run_passes([engine_day()], CONFIG, time_zones=NO_REFRESH)
