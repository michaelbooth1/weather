"""Re-run and attribute (spec v3.2 §1.4, v3.3 §4.2) for W1(a), W2(a) and F3 on fictional fixtures."""
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
