"""End-to-end score-free rehearsal on fictional calibration bundles (registration §9, §10 E5-E7; U2 part 2).

The bundles are ``fixtures.panel_v02`` fictional v0.2 days on the real calibration dates; no captured data is read.
"""
from __future__ import annotations

from datetime import datetime, timezone
import itertools

import pytest

from maker_core.replay import bundle_v02
from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.fill_model import BOUNDS
from maker_core.replay.v2 import ceilings, rehearsal
from maker_core.replay.v2.pipeline import BASE_POLICIES

from .fixtures.panel_v02 import Panel

NOW = datetime(2026, 10, 13, 17, tzinfo=timezone.utc)
CAL = "c" * 64
REPLICATES = 100  # the bootstrap floor (pull_efficiency); the rehearsal itself defaults to 2000


def fixture():
    return Panel(bands=1, step=5, full=True, capture_minutes=range(0, 600))


@pytest.fixture(scope="module")
def calibration(tmp_path_factory):
    panel = fixture()
    root = tmp_path_factory.mktemp("calibration")
    paths = {d: panel.write(root / d.isoformat(), d, provenance="captured") for d in CALIBRATION_DATES}
    return panel, paths, panel.inventory


def memory_probe(step=1000):
    """A fake ``process_memory``: the peak grows by ``step`` per call, so above-baseline is ``step``."""
    counter = itertools.count(1)
    return lambda: (0, next(counter) * step)


def rehearse(paths, inventory, mode, **overrides):
    options = dict(mode=mode, hazard_per_minute=.001, calibration_sha256=CAL, now=NOW, replicates=REPLICATES,
                   memory=memory_probe())
    options.update(overrides)
    return rehearsal.rehearse(paths, inventory, **options)


@pytest.fixture(scope="module")
def per_date(calibration):
    _, paths, inventory = calibration
    return {d.isoformat(): rehearse([paths[d]], inventory([d]), "per_date") for d in CALIBRATION_DATES}


def test_a_per_date_rehearsal_is_whitelisted_and_measures_the_whole_pipeline(per_date):
    doc = per_date[CALIBRATION_DATES[0].isoformat()]
    assert rehearsal.whitelisted(doc) is doc
    assert doc["format"] == rehearsal.FORMAT and doc["mode"] == "per_date"
    assert doc["dates"] == [CALIBRATION_DATES[0].isoformat()]
    assert doc["report_status"] == "FIXTURE_ONLY" and doc["replicates"] == REPLICATES
    measured = doc["measured"]
    assert set(measured) == set(rehearsal.MEASURED_KEYS)
    assert sum(measured["records_by_kind"].values()) == measured["records"] > 0
    assert {"book", "descriptor"} <= set(measured["records_by_kind"])
    assert measured["decisions"] > 0 and measured["wakes"] > 0 and measured["span_runs"] > 0
    assert measured["report_bytes"] > 0 and measured["sidecar_bytes"] > 0 and measured["sidecar_records"] > 0
    assert measured["peak_memory_above_baseline_bytes"] == 1000
    assert len(doc["passes"]) == 8  # four policies x two fill bounds, the clock pass being the selected trial
    assert {(p["policy"], p["fill_bound"]) for p in doc["passes"]} == {
        (p, b) for p in BASE_POLICIES for b in BOUNDS}
    assert set(doc["clock"]["matches"]) == set(BOUNDS)


def test_nothing_scored_is_in_the_document(per_date):
    text = repr(per_date)
    for key in ("fills", "final_cash", "band_days", "scores", "registered_decision", "exclusions_sha256"):
        assert f"'{key}'" not in text


def test_two_rehearsals_of_one_date_are_byte_identical_e7(calibration, per_date):
    _, paths, inventory = calibration
    day = CALIBRATION_DATES[1]
    again = rehearse([paths[day]], inventory([day]), "per_date")
    first = per_date[day.isoformat()]
    assert again["hashes"] == first["hashes"]
    assert again["passes"] == first["passes"]
    for key in set(rehearsal.MEASURED_KEYS) - {"runtime_seconds"}:
        assert again["measured"][key] == first["measured"][key], key


def test_the_carried_run_feeds_the_ceiling_rule_and_e5(calibration, per_date):
    _, paths, inventory = calibration
    carried = rehearse([paths[d] for d in reversed(CALIBRATION_DATES)], inventory(CALIBRATION_DATES), "carried")
    assert carried["dates"] == [d.isoformat() for d in CALIBRATION_DATES]
    assert carried["measured"]["records"] == sum(d["measured"]["records"] for d in per_date.values())
    assert carried["measured"]["input_bytes"] == sum(d["measured"]["input_bytes"] for d in per_date.values())
    rows = {day: rehearsal.ceiling_input(doc) for day, doc in per_date.items()}
    derived = ceilings.derive(rows, rehearsal.ceiling_input(carried))
    assert derived["executable"] is True and derived["host_limit_binding"] == []
    largest = max(r["records"] for r in rows.values())
    assert derived["ceilings"]["records"] == ceilings.next_power_of_two(ceilings.N * largest)
    assert ceilings.e5_memory(rows, rehearsal.ceiling_input(carried), derived)["status"] == "PASS"
    limits = ceilings.run_limits(derived)
    assert limits["max_records"] >= carried["measured"]["records"]


def test_a_non_calibration_path_refuses_before_any_bundle_is_opened(calibration, monkeypatch, tmp_path):
    _, paths, inventory = calibration
    inventory = inventory(CALIBRATION_DATES)
    monkeypatch.setattr(bundle_v02, "open_stream_bundle", lambda *a, **k: pytest.fail("a bundle was opened"))
    with pytest.raises(BundleError, match="rehearsal_restricted_to_calibration_dates"):
        rehearse([tmp_path / "2026-10-02" / "bundle"], inventory, "per_date")
    with pytest.raises(BundleError, match="rehearsal_per_date_requires_one_date"):
        rehearse([paths[d] for d in CALIBRATION_DATES[:2]], inventory, "per_date")
    with pytest.raises(BundleError, match="rehearsal_carried_requires_the_three_calibration_dates"):
        rehearse([paths[d] for d in CALIBRATION_DATES[:2]], inventory, "carried")
    with pytest.raises(BundleError, match="rehearsal_duplicate_date"):
        rehearse([paths[CALIBRATION_DATES[0]]] * 3, inventory, "carried")
    with pytest.raises(BundleError, match="rehearsal_hazard_variant_invalid"):
        rehearse([paths[CALIBRATION_DATES[0]]], inventory, "per_date", hazard_variant="per_band")


def test_a_bundle_whose_manifest_names_another_day_refuses(calibration, tmp_path):
    panel, _, inventory = calibration
    inventory = inventory(CALIBRATION_DATES[:1])
    moved = panel.write(tmp_path / CALIBRATION_DATES[1].isoformat(), CALIBRATION_DATES[0], provenance="captured")
    with pytest.raises(BundleError, match="rehearsal_restricted_to_calibration_dates"):
        rehearse([moved], inventory, "per_date")


def test_ceiling_input_refuses_an_incomplete_or_foreign_document(per_date):
    doc = dict(per_date[CALIBRATION_DATES[0].isoformat()])
    with pytest.raises(BundleError, match="rehearsal_format_invalid"):
        rehearsal.ceiling_input(dict(doc, format="maker_core.replay.rehearsal.v1"))
    measured = dict(doc["measured"])
    del measured["span_runs"]
    with pytest.raises(BundleError, match="incomplete_ceiling_measurement"):
        rehearsal.ceiling_input(dict(doc, measured=measured))
    assert set(rehearsal.ceiling_input(doc)) == set(ceilings.MEASURED)
