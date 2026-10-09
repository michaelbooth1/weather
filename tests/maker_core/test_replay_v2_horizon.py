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
NY, TOKYO, CHATHAM = "America/New_York", "Asia/Tokyo", "Pacific/Chatham"
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
    """One condition (NYC by default) for ``target`` across several fictional UTC days."""

    def __init__(self, target, cid="nyc-band", market="nyc", zone=NY):
        self.target, self.cid, self.market, self.zone = target, cid, market, zone
        close = datetime.combine(target + timedelta(days=1), datetime.min.time(), tzinfo=time_zone(zone))
        close = close.astimezone(UTC)
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
                     target_date=self.target.isoformat(), local_timezone=self.zone)]


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
def manifest_case(tmp_path, target, captures, days, zone=NY):
    band = Band(target, zone=zone)
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


def test_a_descriptor_exactly_at_the_window_start_holds_from_that_instant(tmp_path, monkeypatch):
    """Defender N6: Chatham (UTC+13:45 in November) captured exactly at 00:00Z must count at the envelope start."""
    monkeypatch.setattr(execution_manifest, "SETTLEMENT_DATE", date(2026, 11, 30))
    windows, excluded = manifest_case(
        tmp_path, date(2026, 11, 22), [(utc(2026, 11, 20), 2)],  # 11-20 13:45 local: lead 2; lead 1 from 10:15Z
        [date(2026, 11, 20)], zone=CHATHAM)
    assert [(w["start"], w["end"]) for w in windows] == [
        (iso(2026, 11, 20), iso(2026, 11, 20, 5)), (iso(2026, 11, 20, 8), iso(2026, 11, 21))]
    assert excluded == []


def test_mutant_descriptor_at_the_window_start_ignored_is_caught(tmp_path, monkeypatch):
    def strict(timeline, at):  # the Defender's ``_state`` mutant: only entries strictly before ``at``
        seen, value = False, None
        for when, horizon_days in timeline:
            if when >= at:
                break
            seen, value = True, horizon_days
        return seen, value
    monkeypatch.setattr(horizon, "_state", strict)
    with pytest.raises(AssertionError):
        test_a_descriptor_exactly_at_the_window_start_holds_from_that_instant(tmp_path, monkeypatch)


def test_a_gap_day_in_the_panel_carries_the_last_lead_across_it(tmp_path, monkeypatch):
    """Defender N1, CURRENT behaviour pinned, and an OPEN OWNER ITEM against registration C13.

    The panel has 11-17 and 11-19 but not 11-18. ``DayRoll`` derives descriptors only at local midnights inside the
    days it is driven over, so the Tokyo midnights of 11-18 15:00Z (true lead 0) and 11-19 15:00Z (lead -1) are
    never derived: the band keeps the captured lead 1 and stays active all of 11-19, where the true local lead is 0
    and then -1. The engine reads the same carried lead (manifest and engine agree), so this is not a manifest/engine
    split; it is a C13 gap. Candidate fixes for the owner: a catch-up derived item at the first instant after a gap,
    or ``run_plan`` refusing non-contiguous panel days. Until the owner rules, this test pins today's behaviour so any
    change to it is deliberate."""
    monkeypatch.setattr(execution_manifest, "SETTLEMENT_DATE", date(2026, 11, 30))
    windows, excluded = manifest_case(
        tmp_path, date(2026, 11, 19), [(utc(2026, 11, 17, 16), 1)],  # 11-18 01:00 Tokyo: lead 1
        [date(2026, 11, 17), date(2026, 11, 19)], zone=TOKYO)
    assert [(w["date"], w["start"], w["end"]) for w in windows] == [
        ("2026-11-17", iso(2026, 11, 17, 16), iso(2026, 11, 18)),
        ("2026-11-19", iso(2026, 11, 19), iso(2026, 11, 19, 5)),  # true lead 0 then -1: carried lead 1 (owner item)
        ("2026-11-19", iso(2026, 11, 19, 8), iso(2026, 11, 20))]
    assert [(e["date"], e["reason"], e["start"], e["end"]) for e in excluded] == [
        ("2026-11-17", "missing_descriptor", iso(2026, 11, 17), iso(2026, 11, 17, 16))]


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
CUT = (utc(2026, 11, 1, 3, 50), utc(2026, 11, 1, 3, 55))  # dense-11-01-dst: NYC and Toronto read lead 1 here


def cut_windows(sources, low=CUT[0], high=CUT[1]):
    """A window cut the clause does not ask for: [low, high) removed where the engine still reads lead 1."""
    out = []
    for s in sources:
        p = s.plan
        windows = {cid: tuple((x, y) for a, b in spans for x, y in ((a, min(b, low)), (max(a, high), b)) if x < y)
                   for cid, spans in p.windows.items()}
        out.append(DaySource(DayPlan(p.day, p.conditions, MappingProxyType(windows), p.groups, p.provenance,
                                     p.input_hashes, p.declared), s.records))
    return out


def verdicts(result):
    return {c["attribution"]["verdict"] for passes in result.values() for c in passes.values()}


def test_q2_attributes_every_changed_decision_to_a8_or_its_cascade():
    from tools.research.maker_replay_v2 import attribution
    # Negative control first (Defender M1): a cut where the engine reads lead 1 is not the clause, so it must FAIL.
    control = attribution.report_q2(["dense-11-01-dst"], windows=cut_windows)
    assert "FAIL_A8_CUT_NOT_THE_CLAUSE" in verdicts(control), control
    result = attribution.report_q2()
    print("Q2_ATTRIBUTION_JSON " + json.dumps(result, sort_keys=True, default=str))
    cells = {(f, k): c["attribution"] for f, passes in result.items() for k, c in passes.items()}
    assert {c["verdict"] for c in cells.values()} == {"PASS"}, {k: c for k, c in cells.items() if c["verdict"] != "PASS"}
    assert all(set(c["classes"]) <= {"A8"} for c in cells.values()), cells
    assert all(c["clause_violations"] == c["unexplained_cuts"] == 0 for c in cells.values()), cells
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


# -- the Defender's three M1 mutants: each must make the A8 re-run FAIL -------------------------------------------
def test_mutant_a8_predicate_always_true_is_caught(monkeypatch):
    """A8 labelling every tick in the post run (self-labelling) must not pass: the negative control catches it."""
    from tools.research.maker_replay_v2 import attribution
    original = attribution.attributing

    def vacuous(engine, q2=False):
        cls = original(engine, q2=q2)
        cls.outside_clause = lambda self, cid, at: q2
        return cls
    monkeypatch.setattr(attribution, "attributing", vacuous)
    with pytest.raises(AssertionError):
        test_q2_attributes_every_changed_decision_to_a8_or_its_cascade()


def test_mutant_utc_zone_windows_fail_the_re_run(monkeypatch):
    """Clause windows cut at UTC midnight while the engine rolls at the NYC midnight: the band stays active at
    engine lead 0, so the clause is not applied and the re-run must FAIL."""
    from tools.research.maker_replay_v2 import attribution
    original = horizon.timelines
    monkeypatch.setattr(horizon, "timelines", lambda sources, zones: original(sources, {m: "UTC" for m in zones}))
    result = attribution.report_q2(["dense-11-01-dst"])
    assert "FAIL_A8_CLAUSE_NOT_APPLIED" in verdicts(result), result


def test_mutant_eligible_leads_zero_one_two_fail_the_re_run(monkeypatch):
    from tools.research.maker_replay_v2 import attribution
    monkeypatch.setattr(horizon, "ELIGIBLE", (0, 1, 2))
    result = attribution.report_q2(["dense-11-01-dst"])
    assert "FAIL_A8_CLAUSE_NOT_APPLIED" in verdicts(result), result


# -- Defender D1: a late window end on a sparse-wake band -----------------------------------------------------------
KATHMANDU = "Asia/Kathmandu"  # UTC+05:45: the 11-21 local midnight is 2026-11-20 18:15Z
LEAVE = utc(2026, 11, 20, 18, 15)


def sparse_band():
    """Kathmandu, target 11-21, captured lead 1 at 00:01Z; books every 55 s from 18:00Z, so no book lands in
    [18:15:00, 18:15:20) and only the interval end wakes the band at local midnight."""
    band = Band(date(2026, 11, 21), cid="ktm-band", market="nyc", zone=KATHMANDU)
    band.descriptor(utc(2026, 11, 20, 0, 1), 1)
    band.event(utc(2026, 11, 20, 0, 1))
    s = band.scenario(date(2026, 11, 20))
    s.view(band.market, 18 * 3600, p=.5)
    s.terms(band.market, 18 * 3600)
    for second in range(18 * 3600, 18 * 3600 + 30 * 60, 55):
        s.book(band.market, second, mid=D(".5") + (D(".01") if second // 55 % 2 else 0))
    return band


def late_end(sources, late=timedelta(seconds=20)):
    """The mutant: every clause window that ends inside the day ends ``late`` after it."""
    out = []
    for s in sources:
        p = s.plan
        end = p.start + timedelta(days=1)
        windows = {cid: tuple((a, b + late if b < end else b) for a, b in spans) for cid, spans in p.windows.items()}
        out.append(DaySource(DayPlan(p.day, p.conditions, MappingProxyType(windows), p.groups, p.provenance,
                                     p.input_hashes, p.declared), s.records))
    return out


def sparse_cells(windows=None, engine=EngineV2):
    from tools.research.maker_replay_v2 import attribution
    band, zones = sparse_band(), {"nyc": KATHMANDU}
    sources = [band.source(date(2026, 11, 20))]
    base = attribution.run(sources, "all", zones, engine=engine)
    clause = attribution.horizon_sources(sources, zones)
    post = attribution.run(clause if windows is None else windows(clause), "Q2", zones, engine=engine)
    cells = {}
    for key, (engine, _) in post.items():
        engine.absent_a8(base[key][0])
        cells[key] = attribution.attribute(base[key][0], engine)
    return base, post, cells


def test_sparse_wake_band_passes_and_the_late_window_end_mutant_fails():
    base, post, cells = sparse_cells()
    assert {c["verdict"] for c in cells.values()} == {"PASS"}, cells
    assert all(c["clause_violations"] == c["unexplained_cuts"] == 0 for c in cells.values()), cells
    informed = next(e for (_, policy), (e, _) in post.items() if policy == "informed-v0")
    assert [(d.decision.action, d.decision.reasons) for d in informed.decisions if d.at == LEAVE] == [
        ("CANCEL", ("OUTSIDE_ACTIVE_INTERVAL",))]  # legs were resting and are withdrawn at local midnight
    for engine, _ in base.values():  # sparse: no wake in the 20 s after local midnight on the envelope run
        assert not [d for d in engine.decisions if LEAVE < d.at < LEAVE + timedelta(seconds=20)]
    _, _, mutant = sparse_cells(late_end)
    assert "FAIL_A8_CLAUSE_NOT_APPLIED" in {c["verdict"] for c in mutant.values()}, mutant


# -- Defender E1: each completeness rule has its own test ---------------------------------------------------------
def test_completeness_rule_i_fails_leg_free_decisions_outside_leads_one_and_two():
    """Rule (i) alone: with the window ending 10 min late, ``no_quote`` holds no legs (rule (ii) has nothing to see)
    but keeps deciding at engine lead 0; those decisions must FAIL the re-run."""
    _, post, cells = sparse_cells(lambda sources: late_end(sources, timedelta(minutes=10)))
    assert sum(policy == "no_quote" for _, policy in post) == 2
    for (bound, policy), (engine, _) in post.items():
        if policy == "no_quote":
            assert any(d.at > LEAVE for d in engine.decisions)
            assert not any(e.legs for e in engine.states.values())
            assert cells[bound, policy]["verdict"] == "FAIL_A8_CLAUSE_NOT_APPLIED", cells[bound, policy]


class NoWithdrawal(EngineV2):
    """Engine mutant: the interval-end withdrawal is dropped, so legs rest at lead 0 and no decision is taken."""

    def pull(self, cid, at, reason):
        if reason != "OUTSIDE_ACTIVE_INTERVAL":
            super().pull(cid, at, reason)


def test_completeness_rule_ii_fails_legs_left_resting_outside_leads_one_and_two():
    """Rule (ii) alone: correct clause windows, but an engine that never withdraws at the interval end. After local
    midnight the band is inactive, so it is never decided again (rule (i) sees no decision) and the base's later
    lead-0 decisions are A8 by ``absent_a8``; only the resting legs show the clause was not applied."""
    _, post, cells = sparse_cells(engine=NoWithdrawal)
    assert sum(policy == "informed-v0" for _, policy in post) == 2
    for (bound, policy), (engine, _) in post.items():
        if policy == "informed-v0":
            assert engine.states["ktm-band"].legs and not [d for d in engine.decisions if d.at >= LEAVE]
            assert cells[bound, policy]["verdict"] == "FAIL_A8_CLAUSE_NOT_APPLIED", cells[bound, policy]
