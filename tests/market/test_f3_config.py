"""Guards: WP-01 section 6 config contracts and the predeclared U80 grid."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from zoneinfo import ZoneInfo

import pytest

from weather.market.f3_types import load_nwp_schedule, load_policy, load_strata, load_universe
from weather.market.market_registry import BUILTIN_SPECS
from weather.paths import REPO_ROOT

CONFIG = REPO_ROOT / "config/f3"
UNIVERSE = REPO_ROOT / "tests/fixtures/f3/weather_universe_t046.json"


def rewrite(tmp_path, name, change):
    row = json.loads((CONFIG / name).read_text(encoding="utf-8"))
    change(row)
    target = tmp_path / name
    target.write_text(json.dumps(row), encoding="utf-8")
    return target


def test_strata_matches_pinned_universe_and_offset_rule():
    grid = load_strata(CONFIG / "strata.json")
    cities = load_universe(UNIVERSE)
    builtin = {spec.id for spec in BUILTIN_SPECS}
    high = {c.slug for c in cities.values() if "highest" in c.families and c.settlement_kind == "metar_routine" and c.slug not in builtin}
    low = {c.slug for c in cities.values() if "lowest" in c.families and c.settlement_kind == "metar_routine"}
    assert len(grid.cells) == len(set(grid.cells)) == 8
    assert set(grid.arms["T5-R"]["cities"]) == high and len(high) == 36
    assert set(grid.arms["D-LOW"]["cities"]) == low and len(low) == 44
    assert set(grid.cluster_of) == high | low == set(grid.region_of)
    for instant in ("2026-11-17T12:00:00+00:00", "2026-12-24T12:00:00+00:00"):
        for slug, region in grid.region_of.items():
            offset = datetime.fromisoformat(instant).astimezone(ZoneInfo(cities[slug].timezone)).utcoffset()
            assert region == ("AEA" if offset.total_seconds() < 5 * 3600 else "AP")
    with pytest.raises(TypeError):
        grid.region_of["london"] = "AP"


def test_example_economic_fields_equal_f2_example():
    # Source: docs/examples/lfc-campaign.example.json at c4c3216b1 (B068).
    p = load_policy(CONFIG / "f3_policy.example.json")
    expected = dict(shares_per_leg=D("20"), tick_pusd=D(".01"), quote_offset_pusd=D(".015"),
        requote_distance_cents=(D(1), D(3)), leg_price_range=(D(".17"), D(".80")),
        share_many_range=(D(0), D(1)), min_reward_rate=D(0), min_book_depth=D(20),
        per_order_cap_pusd=D("15.80"), per_band_cap_pusd=D("19.60"),
        per_band_daily_filled_cap_pusd=D(40), fill_cooldown_seconds=60,
        on_first_band_fill="cancel_reconcile_cooldown_and_requote_same_band", replace_retired_band=False,
        sleeve_ceiling_pusd=D(300), sleeve_loss_basis="net_of_retained_gains", local_event_dte=(1,), tokens=("YES", "NO"))
    for key, value in expected.items():
        assert getattr(p, key) == value, key
    assert all(v is None for v in p.f2_source.values())
    with pytest.raises(FrozenInstanceError):
        p.policy_id = "other"


@pytest.mark.parametrize("key,value", [("schema_version", "wrong"), ("shares_per_leg", "30"),
    ("shares_per_leg", 20), ("sleeve_loss_basis", "other"), ("fill_cooldown_seconds", 59),
    ("max_concurrent_bands", 16), ("max_concurrent_bands", True), ("max_bands_per_cluster", 4),
    ("min_reward_rate", "NaN"), ("min_book_depth", "-1"), ("quote_offset_pusd", "0.001"),
    ("tokens", ["YES"]), ("local_event_dte", [0]), ("replace_retired_band", True),
    ("retire_local_time", "24:00"), ("strata_path", "config/f3/../elsewhere.json"),
    ("share_many_range", ["1", "0"]), ("requote_distance_cents", ["1"])])
def test_malformed_policy_refused(tmp_path, key, value):
    target = rewrite(tmp_path, "f3_policy.example.json", lambda r: r.update({key: value}))
    with pytest.raises(ValueError):
        load_policy(target)


def test_policy_rejects_missing_field_and_bad_pin(tmp_path):
    target = rewrite(tmp_path, "f3_policy.example.json", lambda r: r.pop("sleeve_loss_basis"))
    with pytest.raises(ValueError):
        load_policy(target)
    target = rewrite(tmp_path, "f3_policy.example.json", lambda r: r["f2_source"].update(git_sha="bad"))
    with pytest.raises(ValueError):
        load_policy(target)


def test_nwp_grid_and_lengthening(tmp_path):
    schedule = load_nwp_schedule(CONFIG / "nwp_release_schedule.json")
    assert len(schedule.releases) == 12
    assert schedule.before_minutes + schedule.after_minutes == 35
    assert sum(r.day_offset for r in schedule.releases) == 1
    target = rewrite(tmp_path, "nwp_release_schedule.json", lambda r: r["window_minutes"].update(after=40))
    assert load_nwp_schedule(target).after_minutes == 40


@pytest.mark.parametrize("change", [lambda r: r["window_minutes"].update(before=4),
    lambda r: r["window_minutes"].update(after=29), lambda r: r.update(lengthen_only=False),
    lambda r: r["releases"].append(dict(r["releases"][0])), lambda r: r["releases"].pop()])
def test_nwp_invalid_or_shortened_refused(tmp_path, change):
    with pytest.raises(ValueError):
        load_nwp_schedule(rewrite(tmp_path, "nwp_release_schedule.json", change))


@pytest.mark.parametrize("change", [lambda r: r["cells"].pop(),
    lambda r: r["region_of"].update(london="other"), lambda r: r["cluster_of"].pop("london"),
    lambda r: r["arms"]["T5-R"]["cities"].append("london")])
def test_strata_rejects_incomplete_or_ambiguous_maps(tmp_path, change):
    with pytest.raises(ValueError):
        load_strata(rewrite(tmp_path, "strata.json", change))


def test_universe_rejects_duplicate_and_wrong_schema(tmp_path):
    row = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    row["cities"].append(row["cities"][0])
    target = tmp_path / "universe.json"
    target.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError):
        load_universe(target)
    row.update(schema_version="wrong")
    target.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError):
        load_universe(target)
