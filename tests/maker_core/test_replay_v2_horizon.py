"""Owner ruling Q2(a) full: the registration §4 horizon clause, applied mechanically (registration C15, class A8).

Fictional fixtures only: every date is invented (2026-11, 2027-03) and outside every reserved or excluded window.
The DST nights are America/New_York's fall-back (2026-11-01) and spring-forward (2027-03-14).

Guards: registration §4 and C15 (owner decision Q2(a), 2026-10-08): intervals end at local midnight by captured or
derived descriptor, exclusions not NO_QUOTE, legs withdrawn at interval end, blind RE-1 horizon gate, A8 attribution.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import json
from types import MappingProxyType

import pytest

from maker_core.evidence.journal import plain
from maker_core.replay import execution_manifest
from maker_core.replay.bundle import FORMAT, Condition, load_bundle, time_zone
from maker_core.replay.v2 import horizon
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import Kernel, V2Config
from maker_core.replay.v2.lockstep import DayPlan, DaySource, drive, record_from_row, run_plan, windows_of
from .fixtures.replay_bundle import seal
from .fixtures.replay_scenario import Scenario

UTC = timezone.utc
NY, TOKYO = "America/New_York", "Asia/Tokyo"
CONFIG = V2Config(hazard_per_minute=.001, debug=True, keep=True)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def day_bounds(day):
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return start, start + timedelta(days=1)


# -- lead_window: the exporter's single-day form ---------------------------------------------------------------
@pytest.mark.parametrize("zone, target, day, expected", [
    # fall-back night: 11-01 starts at 04:00Z (EDT), 11-02 at 05:00Z (EST)
    (NY, date(2026, 11, 1), date(2026, 11, 1), (utc(2026, 11, 1), utc(2026, 11, 1, 4))),
    (NY, date(2026, 11, 2), date(2026, 11, 2), (utc(2026, 11, 2), utc(2026, 11, 2, 5))),
    (NY, date(2026, 11, 3), date(2026, 11, 1), (utc(2026, 11, 1, 4), utc(2026, 11, 2))),
    # spring-forward night: 03-14 starts at 05:00Z (EST), 03-15 at 04:00Z (EDT)
    (NY, date(2027, 3, 14), date(2027, 3, 14), (utc(2027, 3, 14), utc(2027, 3, 14, 5))),
    (NY, date(2027, 3, 15), date(2027, 3, 15), (utc(2027, 3, 15), utc(2027, 3, 15, 4))),
    (NY, date(2027, 3, 16), date(2027, 3, 14), (utc(2027, 3, 14, 5), utc(2027, 3, 15))),
    # east of UTC: Tokyo's midnight is 15:00Z the day before
    (TOKYO, date(2026, 11, 20), date(2026, 11, 19), (utc(2026, 11, 19), utc(2026, 11, 19, 15))),
    (TOKYO, date(2026, 11, 21), date(2026, 11, 19), (utc(2026, 11, 19), utc(2026, 11, 20))),
    # lead 0 all day and lead 3 all day: empty envelopes at the nearer day edge
    (NY, date(2026, 11, 1), date(2026, 11, 2), (utc(2026, 11, 2), utc(2026, 11, 2))),
    (NY, date(2026, 11, 20), date(2026, 11, 2), (utc(2026, 11, 3), utc(2026, 11, 3))),
])
def test_lead_window_is_local_leads_one_and_two_clipped_to_the_day(zone, target, day, expected):
    assert horizon.lead_window(time_zone(zone), target, *day_bounds(day)) == expected


@pytest.mark.parametrize("zone, target", [(NY, date(2026, 11, 2)), (NY, date(2027, 3, 15)), (TOKYO, date(2026, 11, 20))])
def test_lead_window_ends_at_the_engines_local_midnight(zone, target):
    from maker_core.replay.v2.day_roll import next_local_midnight
    low, high = horizon.lead_window(time_zone(zone), target, utc(2000, 1, 1), utc(2100, 1, 1))
    assert next_local_midnight(zone, high - timedelta(seconds=1)) == high
    assert next_local_midnight(zone, low - timedelta(seconds=1)) == low


# -- runs: the clause over one envelope ---------------------------------------------------------------------
def test_runs_split_the_envelope_by_the_latest_descriptor():
    start, end = day_bounds(date(2026, 11, 1))
    line = [(utc(2026, 11, 1, 0, 10), 1), (utc(2026, 11, 1, 4), 0), (utc(2026, 11, 1, 4), 1),  # last wins
            (utc(2026, 11, 1, 9), None), (utc(2026, 11, 1, 10), 0)]
    assert horizon.runs(line, start, end) == [
        (start, utc(2026, 11, 1, 0, 10), horizon.MISSING),
        (utc(2026, 11, 1, 0, 10), utc(2026, 11, 1, 9), None),
        (utc(2026, 11, 1, 9), utc(2026, 11, 1, 10), horizon.MISSING),  # an invalid descriptor
        (utc(2026, 11, 1, 10), end, horizon.OUTSIDE)]
    assert horizon.runs(line, end, end) == []
    assert horizon.runs([(utc(2026, 10, 31, 12), 2)], start, end) == [(start, end, None)]


# -- A band built row by row (Scenario payload shapes, one condition ID across days) ---------------------------
class Band:
    """One NYC condition for ``target`` across several fictional UTC days."""

    def __init__(self, target, cid="nyc-band", market="nyc"):
        self.target, self.cid, self.market = target, cid, market
        close = datetime.combine(target + timedelta(days=1), datetime.min.time(), tzinfo=time_zone(NY)).astimezone(UTC)
        base = Scenario(day=target, markets=(market,), minutes=1).descriptors[market]
        self.desc = replace(base, condition_id=cid, close_at_utc=close, settle_at_utc=close + timedelta(minutes=1))
        self.days = {}

    def scenario(self, day):
        if day not in self.days:
            s = Scenario(day=day, markets=(self.market,), minutes=24 * 60)
            s.records = []
            s.cid = lambda _market: self.cid
            self.days[day] = s
        return self.days[day]

    def descriptor(self, at, horizon_days):
        s = self.scenario(at.date())
        s.add(self.market, "descriptor", (at - s.start).total_seconds(),
              dict(market=plain(self.desc), horizon_days=horizon_days))

    def event(self, at):
        s = self.scenario(at.date())
        s.add(self.market, "info_event", (at - s.start).total_seconds(), {"events": []})

    def rows(self, day):
        rows = sorted(self.scenario(day).records, key=lambda r: (r["captured_at"], r["sequence"]))
        return [dict(r, sequence=n) for n, r in enumerate(rows)]

    def source(self, day, windows=None):
        start, end = day_bounds(day)
        conditions = (Condition(self.cid, self.market, "fictional", start, end),)
        records = [record_from_row(r) for r in self.rows(day)]
        plan = DayPlan(day, conditions, windows_of(conditions, None) if windows is None else MappingProxyType(windows),
                       MappingProxyType({}), "synthetic", MappingProxyType({"fixture": "0" * 64}), windows is not None)
        return DaySource(plan, lambda: iter(records))

    def bundle(self, root, day):
        start, end = day_bounds(day)
        folder = root / day.isoformat()
        folder.mkdir()
        manifest = dict(format=FORMAT, day=day.isoformat(), sealed_at=end.isoformat(), provenance="synthetic",
                        conditions=[dict(condition_id=self.cid, market_id=self.market, domain_id="fictional",
                                         active_from=start.isoformat(), active_until=end.isoformat())], streams=[])
        seal(folder, manifest, self.rows(day))
        return load_bundle(folder)

    def inventory(self):
        return [dict(condition_id=self.cid, market_id=self.market, domain_id="fictional",
                     target_date=self.target.isoformat(), local_timezone=NY)]


def test_day_windows_follow_captured_and_derived_descriptors_and_agree_with_the_lead_window():
    band = Band(date(2026, 11, 1))
    band.descriptor(utc(2026, 10, 31, 0, 10), 2)  # 10-30 20:10 EDT: target 11-01 is two local days ahead
    band.event(utc(2026, 11, 1, 0, 10))
    sources = [band.source(date(2026, 10, 31)), band.source(date(2026, 11, 1))]
    lines = horizon.timelines(sources, {"nyc": NY})
    assert lines["nyc-band"] == [(utc(2026, 10, 31, 0, 10), 2), (utc(2026, 10, 31, 4), 1), (utc(2026, 11, 1, 4), 0)]
    first, missing = horizon.day_windows(sources[0].plan, lines)
    assert first == {"nyc-band": ((utc(2026, 10, 31, 0, 10), utc(2026, 11, 1)),)}
    assert missing == [("nyc-band", utc(2026, 10, 31), utc(2026, 10, 31, 0, 10), horizon.MISSING)]
    second, outside = horizon.day_windows(sources[1].plan, lines)
    assert second == {"nyc-band": ((utc(2026, 11, 1), utc(2026, 11, 1, 4)),)}  # ends at the EDT midnight
    assert outside == [("nyc-band", utc(2026, 11, 1, 4), utc(2026, 11, 2), horizon.OUTSIDE)]
    assert second["nyc-band"][0] == horizon.lead_window(time_zone(NY), date(2026, 11, 1),
                                                        *day_bounds(date(2026, 11, 1)))


# -- execution_manifest.active_intervals ---------------------------------------------------------------------
def manifest_case(tmp_path, target, captures, days):
    band = Band(target)
    for at, lead in captures:
        band.descriptor(at, lead)
    for day in days:
        band.event(day_bounds(day)[0] + timedelta(hours=12, minutes=30))
    bundles = [band.bundle(tmp_path, day) for day in days]
    return execution_manifest.active_intervals(bundles, band.inventory())


def iso(*args):
    return utc(*args).isoformat()


def test_active_intervals_end_at_local_midnight_across_the_fall_back_night(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_manifest, "SETTLEMENT_DATE", date(2026, 11, 30))  # a fictional panel
    windows, excluded = manifest_case(
        tmp_path, date(2026, 11, 3),
        [(utc(2026, 11, 1, 0, 10), 3), (utc(2026, 11, 2, 12), 1)],  # 10-31 20:10 EDT: lead 3; 11-02 07:00 EST: lead 1
        [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)])
    assert [(w["date"], w["start"], w["end"]) for w in windows] == [
        ("2026-11-01", iso(2026, 11, 1, 4), iso(2026, 11, 1, 5)),  # derived lead 2 at the EDT midnight
        ("2026-11-01", iso(2026, 11, 1, 8), iso(2026, 11, 2)),
        ("2026-11-02", iso(2026, 11, 2), iso(2026, 11, 2, 5)),
        ("2026-11-02", iso(2026, 11, 2, 8), iso(2026, 11, 3)),
        ("2026-11-03", iso(2026, 11, 3), iso(2026, 11, 3, 5))]  # ends at the EST midnight: lead 0
    assert [(e["date"], e["reason"], e["start"], e["end"]) for e in excluded] == [
        ("2026-11-01", "missing_descriptor", iso(2026, 11, 1), iso(2026, 11, 1, 0, 10)),
        ("2026-11-01", "horizon_outside_1_2", iso(2026, 11, 1, 0, 10), iso(2026, 11, 1, 4)),
        ("2026-11-03", "horizon_outside_1_2", iso(2026, 11, 3, 5), iso(2026, 11, 4))]


def test_active_intervals_end_at_local_midnight_across_the_spring_forward_night(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_manifest, "SETTLEMENT_DATE", date(2027, 3, 31))
    windows, excluded = manifest_case(tmp_path, date(2027, 3, 15), [(utc(2027, 3, 14, 1), 2)],  # 03-13 20:00 EST
                                      [date(2027, 3, 14), date(2027, 3, 15)])
    assert [(w["start"], w["end"]) for w in windows] == [
        (iso(2027, 3, 14, 1), iso(2027, 3, 14, 5)), (iso(2027, 3, 14, 8), iso(2027, 3, 15)),
        (iso(2027, 3, 15), iso(2027, 3, 15, 4))]  # the EDT midnight, an hour earlier than the 03-14 one
    assert [(e["reason"], e["start"], e["end"]) for e in excluded] == [
        ("missing_descriptor", iso(2027, 3, 14), iso(2027, 3, 14, 1)),
        ("horizon_outside_1_2", iso(2027, 3, 15, 4), iso(2027, 3, 16))]
    assert (windows[-1]["start"], windows[-1]["end"]) == tuple(t.isoformat() for t in horizon.lead_window(
        time_zone(NY), date(2027, 3, 15), *day_bounds(date(2027, 3, 15))))


def test_mutant_whole_envelope_intervals_are_caught(tmp_path, monkeypatch):
    monkeypatch.setattr(horizon, "runs", lambda timeline, start, end: [(start, end, None)] if start < end else [])
    with pytest.raises(AssertionError):
        test_active_intervals_end_at_local_midnight_across_the_fall_back_night(tmp_path, monkeypatch)


# -- the engine: withdrawal at the interval end, and the blind RE-1 gate ------------------------------------------
def quoting_band(last_book_second):
    """NYC, target 11-01, labelled lead 1 from 00:10Z; a book every 30 s (no capture gap) from 03:50Z."""
    band = Band(date(2026, 11, 1))
    band.descriptor(utc(2026, 11, 1, 0, 10), 1)
    band.event(utc(2026, 11, 1, 0, 10))
    s = band.scenario(date(2026, 11, 1))
    s.view(band.market, 230 * 60, p=.5)
    s.terms(band.market, 230 * 60)
    for second in range(230 * 60, last_book_second + 1, 30):
        s.book(band.market, second, mid=D(".5") + (D(".01") if second // 60 % 2 else 0))
    return band


def drive_one(source, policy):
    engine = EngineV2(replace(CONFIG, policy=policy), run_plan([source]))
    drive([source], [engine], time_zones={"nyc": NY})
    return engine


@pytest.mark.parametrize("policy", ["informed-v0", "blind_re1"])
def test_legs_are_withdrawn_at_the_local_midnight_interval_end(policy):
    band = quoting_band(239 * 60 + 30)  # the last book at 03:59:30Z: only the interval end wakes it at 04:00Z
    day = date(2026, 11, 1)
    lines = horizon.timelines([band.source(day)], {"nyc": NY})
    windows, _ = horizon.day_windows(band.source(day).plan, lines)
    assert windows == {"nyc-band": ((utc(2026, 11, 1, 0, 10), utc(2026, 11, 1, 4)),)}
    clause = drive_one(band.source(day, windows), policy)
    before = [d for d in clause.decisions if d.at < utc(2026, 11, 1, 4)]
    assert before and before[-1].decision.action in ("QUOTE", "HOLD") and before[-1].decision.legs is not None
    at_end = [d for d in clause.decisions if d.at >= utc(2026, 11, 1, 4)]
    assert [(d.at, d.decision.action, d.decision.reasons) for d in at_end] == [
        (utc(2026, 11, 1, 4), "CANCEL", ("OUTSIDE_ACTIVE_INTERVAL",))]
    envelope = drive_one(band.source(day), policy)  # whole-day windows: the legs rest past local midnight
    after = [d for d in envelope.decisions if d.at >= utc(2026, 11, 1, 4)]
    assert after and after[0].at == utc(2026, 11, 1, 4, 0, 30)  # first woken by the book gap, 30 s later


def test_blind_re1_is_refused_outside_leads_one_and_two_like_informed_v0():
    band = quoting_band(251 * 60)  # books to 04:11Z on the envelope windows: the gate alone keeps T+0 unquoted
    engine = drive_one(band.source(date(2026, 11, 1)), "blind_re1")
    assert engine.states["nyc-band"].latest["descriptor"].horizon_days == 0
    before = [d for d in engine.decisions if d.at < utc(2026, 11, 1, 4)]
    after = [d for d in engine.decisions if utc(2026, 11, 1, 4) <= d.at <= utc(2026, 11, 1, 4, 11)]  # books fresh
    assert any(d.decision.action == "QUOTE" for d in before)
    assert after and {d.decision.reasons for d in after} == {("HORIZON_NOT_ELIGIBLE",)}
    assert not any(d.decision.action in ("QUOTE", "HOLD") for d in after)
    assert Kernel.blind_horizons == (1, 2)


def test_mutant_blind_gate_removed_is_caught(monkeypatch):
    monkeypatch.setattr(Kernel, "blind_horizons", None)
    with pytest.raises(AssertionError):
        test_blind_re1_is_refused_outside_leads_one_and_two_like_informed_v0()


# -- attribution: Q2 is its own class A8, against W1+W2+F3 -------------------------------------------------------
def test_q2_attributes_every_changed_decision_to_a8_or_its_cascade():
    from tools.research.maker_replay_v2 import attribution
    result = attribution.report_q2()
    print("Q2_ATTRIBUTION_JSON " + json.dumps(result, sort_keys=True, default=str))
    cells = {(f, k): c["attribution"] for f, passes in result.items() for k, c in passes.items()}
    assert {c["verdict"] for c in cells.values()} == {"PASS"}, {k: c for k, c in cells.items() if c["verdict"] != "PASS"}
    assert all(set(c["classes"]) <= {"A8"} for c in cells.values()), cells
    dst = [c for (f, _), c in cells.items() if f == "dense-11-01-dst"]
    assert sum(c["changed_decisions"] for c in dst) > 0  # NYC and Toronto leave lead 1 at 04:00Z in the window
    assert any(cells["dense-11-01-dst", f"blind_re1/{b}"]["classes"].get("A8") for b in ("strictly_through", "at_price"))


def test_the_production_kernel_on_clause_windows_equals_the_q2_variant():
    from tools.research.maker_replay_v2 import attribution
    table, zones = attribution.fixtures()
    sources = attribution.horizon_sources(table["dense-11-01-dst"](), zones)
    runs = attribution.run(sources, "Q2", zones)
    plan = run_plan(sources)
    engines = {key: EngineV2(V2Config(hazard_per_minute=attribution.HAZARD, keep=True, policy=key[1],
                                      fill_bound=key[0]), plan) for key in runs}
    drive(sources, list(engines.values()), time_zones=zones)
    assert {k: e.decision_sha.hexdigest() for k, e in engines.items()} == {
        k: e.decision_sha.hexdigest() for k, (e, _) in runs.items()}


def test_mutant_a8_change_without_its_class_fails_the_re_run(monkeypatch):
    """The Q2 run with A8 recording switched off: its changes are unattributed, so the re-run must FAIL."""
    from tools.research.maker_replay_v2 import attribution
    original = attribution.attributing
    monkeypatch.setattr(attribution, "attributing", lambda engine, q2=False: original(engine, q2=False))
    table, zones = attribution.fixtures()
    sources = table["dense-11-01-dst"]()
    base = attribution.run(sources, "all", zones)
    post = attribution.run(attribution.horizon_sources(sources, zones), "Q2", zones)
    verdicts = {attribution.attribute(base[k][0], post[k][0])["verdict"] for k in post}
    assert verdicts - {"PASS"}, verdicts
