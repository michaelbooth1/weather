"""MG-2 gate population without Denver (rule §8 Clarification C8).

Guards: MG-2 rule §8 C8 (docs/research/mg2-composite-binding-2026-10-25/rule.md): Denver rows never enter the
G1/G2 gate (score and the dev gate numbers); emission is unchanged.
"""
import ast
from pathlib import Path

import pandas as pd

from weather.reporting.scorecards import dev_scorecard_data as data

from tests.host_guard import import_or_skip_on_capture_host

mg2 = import_or_skip_on_capture_host("weather.calibration.mg2_composite")

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "src/weather/calibration/mg2_composite.py").read_text(encoding="utf-8")


def _layout():
    keys = ["atlanta|1", "denver|1", "nyc|1"]
    markets = ["atlanta", "denver", "nyc"]
    snaps = pd.DataFrame({"row_key": keys, "market": markets, "date": ["2026-11-02"] * 3, "local_hour": [14] * 3})
    bands = pd.DataFrame({"row_key": [k for k in keys for _ in (0, 1)], "band_index": [0, 1] * 3})
    labels = pd.DataFrame({"row_key": keys, "market": markets, "winner": [0, 1, 0]})
    market = pd.DataFrame({"row_key": [k for k in keys for _ in (0, 1)], "band_index": [0, 1] * 3,
                           "p_market_yes": [0.5] * 6})
    return data.Layout(snaps=snaps, bands=bands, labels=labels, market=market, manifest_sha256="0" * 64,
                       file_sha256={}, label_source="test")


def test_denver_rows_are_excluded_from_every_gate_frame():
    assert mg2.GATE_EXCLUDED_MARKETS == ("denver",)
    gated = mg2.gate_layout(_layout())
    for name in ("snaps", "bands", "labels", "market"):
        frame = getattr(gated, name)
        assert not frame.row_key.str.startswith("denver|").any(), name
        assert set(frame.row_key) == {"atlanta|1", "nyc|1"}, name
    assert set(gated.snaps.market) == {"atlanta", "nyc"}
    assert len(gated.bands) == 4 and len(gated.market) == 4


def test_the_gate_layout_leaves_the_input_untouched():
    layout = _layout()
    mg2.gate_layout(layout)
    assert "denver" in set(layout.snaps.market) and len(layout.bands) == 6


def _function(name):
    tree = ast.parse(SRC)
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_score_restricts_the_layout_before_the_table_is_built():
    body = ast.get_source_segment(SRC, _function("score"))
    assert "layout = gate_layout(layout)" in body
    assert body.index("layout = gate_layout(layout)") < body.index("sc.Table(layout, days)")
    assert '"gate_excluded_markets": list(GATE_EXCLUDED_MARKETS)' in body


def test_the_dev_gate_numbers_drop_denver_and_emission_does_not():
    dev = ast.get_source_segment(SRC, _function("dev_run"))
    assert "in_gate = ~np.isin(table.markets, GATE_EXCLUDED_MARKETS)" in dev
    assert "mask & in_gate" in dev and '"gate_groups": gate_groups' in dev
    emit = ast.get_source_segment(SRC, _function("emit"))
    assert "gate_layout" not in emit and "GATE_EXCLUDED_MARKETS" not in emit
