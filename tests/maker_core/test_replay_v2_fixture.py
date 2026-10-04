"""W0: the 170-condition fictional day (maker replay v2), and #166's fixture left byte-identical."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import Limits, load_bundle, timestamp
from maker_core.replay.payloads import decode
from tools.research.maker_replay_v2.fixture170 import Day
from tools.research.maker_replay_v2.run import write_forms
from tools.research.pull_cap_precheck import fixture as fixture_166

DAY = date(2026, 9, 27)
NEW_YORK_MIDNIGHT = datetime(2026, 9, 27, 4, tzinfo=timezone.utc)


def _digest(values):
    return hashlib.sha256(b"".join(canonical_bytes(v) for v in values)).hexdigest()


@pytest.mark.parametrize("reduced, count, digest", [
    (False, 2026, "b4ac982fd9a021194d61c8aaebec6c4e1d7a256784f1a0be4e06835ef572941a"),
    (True, 599, "1c4a3c3aa54c896e89f6f842a188fcd0bcba83546e5885ea3a19da5a3413c366"),
])
def test_166_fixture_outputs_stay_byte_identical(reduced, count, digest):
    conditions, records = fixture_166.day_records(DAY, 12, churn=1.5, trades=40, minutes=30, reduced=reduced)
    assert len(records) == count
    assert _digest([conditions] + records) == digest


def test_density_matches_the_real_calibration_union():
    stats = Day(DAY).stats()
    assert stats["union"] == 170 and stats["events"] == 48 and stats["coverage_groups"] == 16
    assert 115 <= stats["instantaneous_min"] <= stats["instantaneous_mean"] <= stats["instantaneous_max"] <= 130
    assert .6 <= stats["t1_t2_share"] <= .75
    assert Day(DAY, union=171).stats()["union"] == 171


def _window(**kwargs):
    # 03:50-04:10 UTC: New York and Toronto cross local midnight at 04:00.
    return Day(DAY, union=60, trades=200, start_minute=230, minutes=20, **kwargs)


def test_rows_are_sorted_deterministic_and_decodable_by_the_v1_payloads():
    rows = list(_window().rows())
    assert _digest(rows) == _digest(_window().rows())
    keys = [(timestamp(r["captured_at"]), r["sequence"]) for r in rows]
    assert keys == sorted(keys) and len({r["sequence"] for r in rows}) == len(rows)
    assert {"descriptor", "book", "terms", "outcome_view", "info_event", "plugin_input", "coverage",
            "trade", "settlement"} <= {r["kind"] for r in rows}
    # A settlement is written at first sight but stamped at its later ledger time, as the exporter does.
    assert any(r["kind"] == "settlement" and r["sequence"] < prev["sequence"] for prev, r in zip(rows, rows[1:]))


def test_v01_form_loads_through_the_frozen_reader_and_every_payload_decodes(tmp_path):
    written = write_forms(_window(), tmp_path)
    bundle = load_bundle(written["v01"], limits=Limits(2**30, 10**6, 300))
    assert len(bundle.records) == sum(written["counts"]["v0.1"].values())
    for record in bundle.records:
        decode(record)


def test_horizon_rolls_at_local_midnight():
    day = _window()
    rows = list(day.rows())
    new_york = {cid for cid, band in day.bands.items() if band.market_id == "city00"}
    horizons = {}
    for r in rows:
        if r["kind"] == "descriptor" and r["condition_id"] in new_york:
            horizons.setdefault(r["condition_id"], []).append((timestamp(r["captured_at"]), r["payload"]["horizon_days"]))
    rolled = {cid: h for cid, h in horizons.items() if len(h) == 2}
    assert rolled and all(a < NEW_YORK_MIDNIGHT <= b and hb == ha - 1 for (a, ha), (b, hb) in rolled.values())
    # The T+0 event leaves the export; the new T+2 event is discovered after midnight.
    old = {cid for cid in new_york if day.bands[cid].target == date(2026, 9, 26)}
    assert not any(r["condition_id"] in old and r["kind"] == "book" and timestamp(r["captured_at"]) >= NEW_YORK_MIDNIGHT
                   for r in rows)
    new = {cid for cid in new_york if day.bands[cid].target == date(2026, 9, 29)}
    assert new and all(h == [(h[0][0], 2)] and h[0][0] > NEW_YORK_MIDNIGHT for cid, h in horizons.items() if cid in new)


def test_terms_every_capture_with_rare_body_changes_and_trades_at_rate():
    day = Day(DAY, union=60, trades=2000, start_minute=600, minutes=60, terms_changes=6)
    rows = list(day.rows())
    terms = [r for r in rows if r["kind"] == "terms"]
    per_condition = Counter(r["condition_id"] for r in terms)
    assert min(per_condition.values()) >= 55  # one reward row a minute per selected condition
    bodies = Counter((r["condition_id"], r["payload"]["min_size"], r["payload"]["rate_per_day"],
                      r["payload"]["max_spread_cents"]) for r in terms)
    assert len(bodies) < 2 * len(per_condition)
    trades = sum(r["kind"] == "trade" for r in rows)
    assert 0 < trades <= 2000 * 60 / 1440 * 1.6


def test_coverage_is_one_state_per_group_per_capture():
    day = _window()
    states = {}
    for r in day.rows():
        if r["kind"] == "coverage":
            states.setdefault((r["captured_at"], day.groups[r["condition_id"]]), set()).add(r["payload_sha256"])
    assert states and all(len(s) == 1 for s in states.values())
    assert len({g for _, g in states}) >= 4
    flips = Counter(next(iter(s)) for s in states.values())
    assert len(flips) > 10  # health expiry and renewal change the state many times


def test_crafted_mismatch_breaks_exactly_one_group_capture():
    day = _window(mismatch_minute=240)
    mixed = {}
    for r in day.rows():
        if r["kind"] == "coverage":
            mixed.setdefault((r["captured_at"], day.groups[r["condition_id"]]), set()).add(r["payload_sha256"])
    assert sum(len(s) > 1 for s in mixed.values()) == 1
    assert min(timestamp(at) for (at, _), s in mixed.items() if len(s) > 1) >= day.start + timedelta(minutes=240)
