"""Weather-side v0.2 universe producer for maker replay v2 (U1, W7). Fictional bundles only."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from maker_core.replay.bundle_v02 import open_stream_bundle
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


def test_producer_rows_equal_the_fixture_inventory_and_drive_the_rule(tmp_path, monkeypatch):
    fixture = Panel()
    paths = [fixture.write(tmp_path / d.isoformat(), d) for d in DAYS]
    names = []
    real = universe_v02._stream
    monkeypatch.setattr(universe_v02, "_stream", lambda b, ref, *a: names.append(ref.name) or real(b, ref, *a))
    rows = producer.universe(paths)
    assert set(names) == {"descriptor.jsonl"}
    assert rows == fixture.inventory(DAYS)
    bundles = [open_stream_bundle(p) for p in paths]
    result = intervals.evaluate(universe_v02.day_inputs(bundles), rows, panel="registered")
    assert result.owner_exclusions[0]["matched_conditions"] == fixture.austin_excluded(DAYS)
    assert {r["target_date"] for r in rows if r["condition_id"] in fixture.austin_excluded(DAYS)} == {
        AUSTIN_TARGET.isoformat()}


def test_bundle_caps_are_sixteen_panel_and_three_calibration(tmp_path):
    fixture = Panel(markets=("toronto",), bands=1, step=240)
    panel_paths = [fixture.write(tmp_path / "p" / d.isoformat(), d) for d in PANEL_DAYS]
    calibration_paths = [fixture.write(tmp_path / "c" / d.isoformat(), d) for d in CALIBRATION_DATES]
    assert len(producer.universe(panel_paths, calibration_paths)) > 0
    for bad in ((panel_paths + calibration_paths[:1], ()), (panel_paths[:1], calibration_paths * 2),
                ((), ())):
        with pytest.raises(ValueError, match="invalid_bundle_inventory"):
            producer.universe(*bad)
    assert producer.MAX_BUNDLES == 19
