"""Fill model v3 in the replay engine, and the v2 byte-identical ratchet (item 330 build 1).

``EngineV3`` is injected; v2 stays the default. The ratchet pins the frozen v2 files at the build-line base
1fd0c295f and EngineV2's summary on a fixed fixture: if either moves, ``EngineV3.on_trade`` (a copy of the kernel's
with only the matcher replaced) must be reviewed again before the pins are updated.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
import hashlib
from pathlib import Path

import pytest

from maker_core.replay import fill_model
from maker_core.replay.bundle import BundleError
from maker_core.replay.fill_v3 import LABEL, VERSION, EngineV3, engine_factory
from maker_core.replay.fill_v3_embargo import EmbargoRefused
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import drive, run_plan
from .fixtures.fill_v3_scenarios import engine_source, force

ROOT = Path(__file__).resolve().parents[2]
CONFIG = V2Config(hazard_per_minute=.001, debug=True, keep=True)
FROZEN = {
    "src/maker_core/replay/fill_model.py": "754c355976be4b9f5f49416e35538ee599fcbd1aeb58e207418f414f24ff6229",
    "src/maker_core/replay/_fill89a.py": "c03bcc311f4d94eea5d1b3646cf20930161fe91cd82f4249c6638672bfd97fb7",
    "src/maker_core/replay/v2/kernel.py": "ed7bd477fc114fbb3f91336f7222e66acc96c9679ed118e7b1c0ce0c7d42d595",
    "src/maker_core/replay/v2/engine.py": "5a28f80525e7f3f2c852a50909cf09daa524eb4ddd1c18e87829f570c99a3b7d",
    "src/maker_core/replay/v2/pipeline.py": "e119010d5a0ba63bcf86deec88b77ac31e1def3023844232bfa4299b509c5641",
    "src/maker_core/replay/v2/lockstep.py": "2fbe46e9c7a178dac557bc4899bf003d8f837188acc9e7b455141ddd895a8efd",
    "src/maker_core/replay/payloads.py": "16bf29493af39ad07f8b63534079abb22ffbfba71523d70e6ab0150b4193cdbd",
}
# EngineV2 on THROUGH below (pinned from the unchanged v2 engine at 1fd0c295f).
GOLDEN_V2 = {
    "strictly_through": ("a64956ff528025eba76ee3ba346b7a81739e1160f45bf138ff5e5b33054cdd4d", D("92.800000")),
    "at_price": ("90fda1af84944356512f20c5c62d75f627092922d3220828ebe851242621200b", D("90.400000")),
}
# YES leg .48 x20 behind 30: at-price 20 (queue 30 -> 10), then through 15 (queue 10 -> 0, fill 5).
THROUGH = [(10, ".48", "20", "YES"), (20, ".47", "15", "YES")]
# NO leg .48 x20 behind 10: YES .52 is at its price (queue 10 -> 6); YES .55 is through (queue 6 -> 0, fill 4).
MIRROR = [(10, ".52", "4", "YES"), (20, ".55", "10", "YES")]


def run(tmp_path, monkeypatch, trades, engine, *, bound="strictly_through", day=date(2020, 1, 1)):
    force(monkeypatch)
    src = engine_source(tmp_path, trades, day=day)
    e = engine(replace(CONFIG, fill_bound=bound), run_plan([src]))
    drive([src], [e], time_zones={"a": "UTC"})
    return e


def fills(engine):
    return [((f.at - engine.decisions[0].at).total_seconds(), f.outcome, f.price, f.size, f.bound)
            for f in engine.fills]


def test_v3_fills_only_what_is_left_after_the_queue(tmp_path, monkeypatch):
    e = run(tmp_path, monkeypatch, THROUGH, engine_factory("v3"))
    assert fills(e) == [(20.0, "YES", D(".48"), D(5), LABEL)]
    assert e.cash == D(100) - D(".48") * 5
    summary = e.summary()
    assert (summary["fill_bound"], summary["fill_model"], summary["purpose"]) == (LABEL, VERSION, "descriptive")


def test_v3_no_leg_mirror_uses_no_bids_and_the_yes_axis(tmp_path, monkeypatch):
    e = run(tmp_path, monkeypatch, MIRROR, engine_factory("v3"))
    assert fills(e) == [(20.0, "NO", D(".48"), D(4), LABEL)]


def test_v3_queue_absorbs_all_prints_no_fill(tmp_path, monkeypatch):
    e = run(tmp_path, monkeypatch, [(10, ".48", "29", "YES")], engine_factory("v3"))
    assert e.fills == []


def test_v2_on_the_same_fixture_fills_at_its_bounds(tmp_path, monkeypatch):
    e = run(tmp_path, monkeypatch, THROUGH, EngineV2)
    assert fills(e) == [(20.0, "YES", D(".48"), D(15), "strictly_through")]


@pytest.mark.parametrize("bound", sorted(GOLDEN_V2))
def test_v2_golden_summary_is_byte_identical(tmp_path, monkeypatch, bound):
    e = run(tmp_path, monkeypatch, THROUGH, engine_factory("v2"), bound=bound)
    summary = e.summary()
    assert (summary["decision_sha256"], summary["final_cash"]) == GOLDEN_V2[bound]
    assert "fill_model" not in summary and summary["fill_bound"] == bound


def test_v2_is_the_default_and_v3_never_joins_the_v2_bounds():
    assert engine_factory() is EngineV2
    assert fill_model.BOUNDS == ("strictly_through", "at_price")
    with pytest.raises(BundleError, match="unknown_fill_bound"):
        V2Config(fill_bound=LABEL)
    with pytest.raises(BundleError, match="unknown_fill_model"):
        engine_factory("v4")


def test_engine_v3_requires_an_explicit_purpose(tmp_path):
    src = engine_source(tmp_path, [])
    with pytest.raises(TypeError):
        EngineV3(CONFIG, run_plan([src]))


@pytest.mark.parametrize("path", sorted(FROZEN))
def test_frozen_v2_files_are_unchanged(path):
    raw = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw).hexdigest() == FROZEN[path]


@pytest.mark.parametrize("day,purpose,code", [
    (date(2026, 9, 30), "descriptive", "v3_reserved_window_refused"),
    (date(2026, 10, 15), "descriptive", "v3_reserved_window_refused"),
    (date(2026, 10, 1), "scored", "v3_reserved_window_refused"),
    (date(2026, 10, 20), "scored", "v3_scored_embargo_refused"),
    (date(2026, 11, 13), "scored", "v3_scored_embargo_refused"),
    (date(2026, 11, 14), "scored", "v3_scored_requires_signed_registration"),
    (date(2020, 1, 1), "scored", "v3_scored_requires_signed_registration"),
])
def test_engine_v3_refuses_embargoed_plan_days(tmp_path, day, purpose, code):
    plan = run_plan([engine_source(tmp_path, [], day=day)])
    with pytest.raises(EmbargoRefused) as caught:
        engine_factory("v3", purpose=purpose)(CONFIG, plan)
    assert caught.value.code == code


def test_engine_v3_descriptive_after_the_reserved_window_is_allowed(tmp_path, monkeypatch):
    e = run(tmp_path, monkeypatch, THROUGH, engine_factory("v3"), day=date(2026, 10, 16))
    assert [f.size for f in e.fills] == [D(5)]
