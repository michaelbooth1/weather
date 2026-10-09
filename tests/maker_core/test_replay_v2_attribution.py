"""Re-run and attribute (spec v3.2 §1.4, v3.3 §4.2) for W1(a), W2(a) and F3 on fictional fixtures.

Guards: registration C11-C13 attribution discipline (spec v3.2 §1.4; owner decision 2026-10-07, OD25).
"""
import json
from pathlib import Path

import pytest

from maker_core.replay.v2.day_roll import NO_REFRESH
from tools.research.maker_replay_v2 import attribution
from tools.research.maker_replay_v2.attribution import attribute, fixtures, run

PINNED = json.loads((Path(__file__).parent / "fixtures" / "replay_v2_prefix_digests.json").read_text())["fixtures"]


@pytest.mark.parametrize("name", sorted(PINNED))
def test_frozen_variant_reproduces_the_pre_fix_engine(name):
    table, zones = fixtures()
    post = run(table[name](), "frozen", zones)
    got = {f"{p}/{b}": m for (b, p), (_, m) in post.items()}
    assert {k: {f: v[f] for f in PINNED[name][k]} for k, v in got.items()} == PINNED[name]


def test_every_ruling_attributes_every_changed_decision():
    result = attribution.report()
    print("ATTRIBUTION_JSON " + json.dumps(result, sort_keys=True, default=str))
    verdicts = {(f, v, k): cell["attribution"]["verdict"] for f, variants in result.items()
                for v, passes in variants.items() if v != "frozen" for k, cell in passes.items()}
    assert set(verdicts.values()) == {"PASS"}, {k: v for k, v in verdicts.items() if v != "PASS"}
    changed = {v: sum(c["attribution"]["changed_decisions"] for p in result.values() for c in p[v].values())
               for v in ("W1", "W2", "F3", "all")}
    assert changed["W1"] > 0 and changed["all"] > 0  # the rulings bite on these fixtures


def test_mutant_unattributed_change_fails_the_re_run(monkeypatch):
    """A Kernel change outside A1-A6 (here: every decision book loses its deepest public YES ask) must FAIL."""
    from dataclasses import replace
    from maker_core.replay.v2.kernel import Kernel, compose_book

    def tampered(self, state, legs):
        book = compose_book(state.latest["book"], legs)
        return replace(book, yes_asks=book.yes_asks[:-1] or book.yes_asks)
    monkeypatch.setattr(Kernel, "decision_book", tampered)
    table, zones = fixtures()
    sources = table["dense-09-27"]()
    base = run(sources, "frozen", zones)
    monkeypatch.setattr(attribution, "variant", lambda engine, name: engine)  # the tampered Kernel as-is
    post = run(sources, "all", zones)
    verdicts = {attribute(base[k][0], post[k][0])["verdict"] for k in post}
    assert verdicts - {"PASS"}, verdicts


def test_refresh_off_and_on_differ_only_where_a_derived_descriptor_exists():
    table, zones = fixtures()
    post = run(table["dense-11-01-dst"](), "F3", zones)
    engine = post["strictly_through", "informed-v0"][0]
    assert engine.derived_shas  # NYC and Toronto roll at 04:00Z inside the window
    assert set(engine.classes) <= {"A6"}
    assert NO_REFRESH is not None


# -- W2 fixture: the cancelled legs rest ON public levels at a replacement (coordinator follow-up 2026-10-07) --
W2_FIXTURE = "w2-on-level"


def w2_runs(*names):
    table, zones = fixtures()
    sources = table[W2_FIXTURE]()
    return sources, zones, {name: run(sources, name, zones) for name in names}


def test_w2_fixture_cancels_legs_resting_on_public_levels_and_replaces_at_the_same_instant():
    from maker_core.replay.v2.kernel import REPLACEMENT_REASONS
    from tools.research.maker_replay_v2.dense import OnLevelReplacementDay
    _, _, runs = w2_runs("frozen")
    events = runs["frozen"]["strictly_through", "informed-v0"][0].decisions
    quote = next(d for d in events if d.decision.action == "QUOTE")
    cancel = next(d for d in events if d.decision.action == "CANCEL" and d.decision.reasons[0] in REPLACEMENT_REASONS)
    assert [d for d in events if d.at == cancel.at][1:]  # a same-instant replacement follows the cancel
    moved = OnLevelReplacementDay.MOVED_BOOK
    for leg in quote.decision.legs:  # every cancelled leg sits on an existing public level (T2 adds size there)
        levels = moved["yb"] if leg.outcome == "YES" else moved["ya"]
        price = leg.price if leg.outcome == "YES" else 1 - leg.price
        assert price in {p for p, _ in levels}, (leg, levels)


def test_w2_alone_changes_decisions_against_the_frozen_engine_and_attributes_them_a5():
    _, _, runs = w2_runs("frozen", "W2")
    cells = {key: attribute(runs["frozen"][key][0], runs["W2"][key][0]) for key in runs["W2"]}
    assert {c["verdict"] for c in cells.values()} == {"PASS"}, cells
    informed = [cells[bound, "informed-v0"] for bound in ("strictly_through", "at_price")]
    assert all(c["changed_decisions"] > 0 and set(c["classes"]) == {"A5"} for c in informed), informed
    print("W2_FIXTURE_JSON " + json.dumps({f"{p}/{b}": c for (b, p), c in cells.items()}, sort_keys=True, default=str))


def test_the_production_kernel_equals_the_all_variant_on_the_w2_fixture():
    """The matrix's ``all`` hooks are the Kernel's own: the unwrapped engine gives the same decisions."""
    from maker_core.replay.v2.engine import EngineV2
    from maker_core.replay.v2.kernel import V2Config
    from maker_core.replay.v2.lockstep import drive, run_plan
    sources, zones, runs = w2_runs("all")
    plan = run_plan(sources)
    engines = {key: EngineV2(V2Config(hazard_per_minute=attribution.HAZARD, keep=True, policy=key[1],
                                      fill_bound=key[0]), plan) for key in runs["all"]}
    drive(sources, list(engines.values()), time_zones=zones)
    assert {k: e.decision_sha.hexdigest() for k, e in engines.items()} == {
        k: e.decision_sha.hexdigest() for k, (e, _) in runs["all"].items()}


def test_mutant_w2_kernel_on_the_pre_cancel_book_is_caught(monkeypatch):
    from maker_core.replay.v2.kernel import Kernel
    monkeypatch.setattr(Kernel, "replacement_book", lambda self, state, cancelled: self.decision_book(state, cancelled))
    with pytest.raises(AssertionError):
        test_the_production_kernel_equals_the_all_variant_on_the_w2_fixture()
