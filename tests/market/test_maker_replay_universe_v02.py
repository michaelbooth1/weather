"""Weather-side v0.2 universe producer for maker replay v2 (U1, W7). Fictional bundles only."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from maker_core.replay.bundle import BundleError
from maker_core.replay.bundle_v02 import open_stream_bundle
from maker_core.replay.v2.limits import DEFAULT_BUNDLE_LIFETIME_SECONDS, RunBudget, V2Limits
from maker_core.replay.v2 import intervals, panel, universe_v02
from tests.maker_core.fixtures.panel_v02 import AUSTIN_TARGET, CALIBRATION_DATES, PANEL_DAYS, SLUGS, ZONES, Panel
from weather.market import maker_replay_universe_v02 as producer
from weather.market.market_registry import BUILTIN_SPECS, spec_for_id

DAYS = (date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4))


def test_fixture_markets_are_registry_markets():
    for market, zone in ZONES.items():
        spec = spec_for_id(market)
        assert (spec.timezone, spec.slug_prefix) == (zone, SLUGS[market])
    # Toronto's local midnight is outside maintenance; Austin's is exactly its start (A-defender M5)
    assert datetime.combine(date(2026, 10, 5), time(), tzinfo=spec_for_id("toronto").tz).astimezone(timezone.utc).hour == 4
    assert datetime.combine(date(2026, 10, 5), time(), tzinfo=spec_for_id("austin").tz).astimezone(timezone.utc).hour == 5


def test_owner_exclusion_market_is_a_builtin_registry_id_and_its_close_matches_the_registry_zone():
    row = panel.OWNER_EXCLUSIONS[0]
    assert row[0] in {spec.id for spec in BUILTIN_SPECS}
    spec = spec_for_id(row[0])
    close = datetime.combine(row.target_date + timedelta(days=1), time(), tzinfo=spec.tz)
    assert close.astimezone(timezone.utc) == row.close_at_utc


def test_registry_slug_prefixes_are_unambiguous_and_the_exclusion_slug_is_literal():
    """U1 Defender MF5: no slug prefix (with its separator) is a prefix of another; Austin's zone and slug."""
    prefixes = [spec.slug_prefix + "-" for spec in BUILTIN_SPECS]
    assert not [(a, b) for a in prefixes for b in prefixes if a != b and b.startswith(a)]
    row = panel.OWNER_EXCLUSIONS[0]
    assert spec_for_id("austin").timezone == "America/Chicago"
    assert row.event_slug == spec_for_id("austin").slug_prefix + "-october-3-2026"


def test_producer_rows_equal_the_fixture_inventory_and_drive_the_rule(tmp_path, monkeypatch):
    fixture = Panel(full=True, step=60)
    paths = [fixture.write(tmp_path / d.isoformat(), d) for d in DAYS]
    names = []
    real = universe_v02.stream_records
    monkeypatch.setattr(universe_v02, "stream_records", lambda b, stem: names.append(b.stream(stem).name) or real(b, stem))
    rows = producer.universe(paths)
    assert set(names) == {"descriptor.jsonl"}
    assert rows == fixture.inventory(DAYS)
    bundles = [open_stream_bundle(p) for p in paths]
    result = intervals.evaluate(universe_v02.day_inputs(bundles), rows, panel="registered")
    assert result.owner_exclusions[0]["matched_conditions"] == fixture.austin_excluded(DAYS)
    assert {r["target_date"] for r in rows if r["condition_id"] in fixture.austin_excluded(DAYS)} == {
        AUSTIN_TARGET.isoformat()}


def test_bundle_caps_are_sixteen_panel_and_three_calibration(tmp_path):
    fixture = Panel(markets=("toronto",), bands=1, step=240, full=True)
    panel_paths = [fixture.write(tmp_path / "p" / d.isoformat(), d) for d in PANEL_DAYS]
    calibration_paths = [fixture.write(tmp_path / "c" / d.isoformat(), d) for d in CALIBRATION_DATES]
    assert len(producer.universe(panel_paths, calibration_paths)) > 0
    for bad in ((panel_paths + calibration_paths[:1], ()), (panel_paths[:1], calibration_paths * 2),
                ((), ())):
        with pytest.raises(ValueError, match="invalid_bundle_inventory"):
            producer.universe(*bad)
    assert producer.MAX_BUNDLES == 19
    # MF6: duplicate days, days from the wrong set, and a calibration-kind (hazard) bundle are refused
    for bad in (([panel_paths[0]] * 2, ()), (calibration_paths[:1], ()), ((), panel_paths[:1]),
                ((), [calibration_paths[0]] * 2)):
        with pytest.raises(ValueError, match="invalid_bundle_inventory"):
            producer.universe(*bad)
    hazard = Panel(markets=("toronto",), bands=1, step=240).write(tmp_path / "h" / "2026-09-27", CALIBRATION_DATES[0])
    with pytest.raises(ValueError, match="calibration_kind_bundle_not_a_universe_input"):
        producer.universe((), [hazard])


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture(scope="module")
def nineteen(tmp_path_factory):
    """The full M10 cap: 16 panel and 3 calibration night-format bundles (fictional, tiny)."""
    root = tmp_path_factory.mktemp("nineteen")
    fixture = Panel(markets=("toronto",), bands=1, step=240, full=True)
    panel_paths = [fixture.write(root / "p" / d.isoformat(), d) for d in PANEL_DAYS]
    calibration_paths = [fixture.write(root / "c" / d.isoformat(), d) for d in CALIBRATION_DATES]
    return panel_paths, calibration_paths


def _recording_opens(monkeypatch, *, advance=0.0, clock=None):
    calls, real = [], producer.open_stream_bundle

    def opener(path, **kwargs):
        calls.append(kwargs)
        if clock is not None:
            clock.now += advance
        return real(path, **kwargs)
    monkeypatch.setattr(producer, "open_stream_bundle", opener)
    return calls


def test_universe_opens_every_bundle_on_one_shared_run_budget_and_v2_limits(nineteen, monkeypatch):
    """U1 Defender r2 C2: ONE ``RunBudget`` per run, shared by all 19 opens, and X1's ``V2Limits``."""
    calls = _recording_opens(monkeypatch)
    assert producer.universe(*nineteen)
    assert len(calls) == producer.MAX_BUNDLES == 19
    runs = {id(c["run"]) for c in calls}
    assert len(runs) == 1 and isinstance(calls[0]["run"], RunBudget)
    assert all(type(c["limits"]) is V2Limits for c in calls)
    run = calls[0]["run"]
    assert run.stored_bytes == sum(open_stream_bundle(p).input_bytes for p in (*nineteen[0], *nineteen[1]))
    # a caller's own run is used as given, never replaced by a fresh one
    mine = RunBudget()
    calls.clear()
    producer.universe(*nineteen, run=mine)
    assert {id(c["run"]) for c in calls} == {id(mine)} and mine.stored_bytes == run.stored_bytes


def test_a_run_over_many_bundles_is_bounded_by_the_shared_deadline_not_each_bundle_lifetime(nineteen, monkeypatch):
    """Each open takes 10,000 s on a fake clock. Every bundle alone is far inside its own 32,768 s lifetime
    (each lifetime starts at that bundle's open), but the run's shared deadline refuses at the 4th open."""
    clock = FakeClock()
    calls = _recording_opens(monkeypatch, advance=10_000.0, clock=clock)
    with pytest.raises(BundleError, match="^run_time_cap$"):
        producer.universe(*nineteen, clock=clock)
    assert len(calls) == 4  # opens at 10,000..30,000 s pass; the 4th, at 40,000 s, is past the 32,768 s run deadline
    assert 10_000.0 < DEFAULT_BUNDLE_LIFETIME_SECONDS  # one open never exhausts a per-bundle lifetime
    # the same timeline with per-bundle budgets only would have admitted every open
    clock.now = 0.0
    for path in nineteen[0][:4]:
        clock.now += 10_000.0
        open_stream_bundle(path, clock=clock)
    # a tighter caller deadline binds sooner
    clock.now, calls[:] = 0.0, []
    with pytest.raises(BundleError, match="^run_time_cap$"):
        producer.universe(*nineteen, run=RunBudget(max_run_seconds=25_000.0, clock=clock), clock=clock)
    assert len(calls) == 3


def test_a_run_over_many_bundles_is_bounded_by_the_shared_stored_total(nineteen, monkeypatch):
    """Stored bytes are charged to the one run across bundles, so the run total binds even though every
    bundle is far below its own stored cap."""
    sizes = [open_stream_bundle(p).input_bytes for p in nineteen[0]]
    calls = _recording_opens(monkeypatch)
    with pytest.raises(BundleError, match="^run_input_byte_cap$"):
        producer.universe(*nineteen, run=RunBudget(max_run_stored_bytes=sizes[0] + sizes[1] + 1))
    assert len(calls) == 3 and max(sizes) < V2Limits().max_bundle_stored_bytes
