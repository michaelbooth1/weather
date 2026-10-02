import json
import random

import pytest

from weather.market import maker_fair_value_nwp_buckets as nwp


def _bands(probability, mid, observed=(1, 0)):
    return [dict(probability=p, mid=m, observed_yes=y, stdev=0.1) for p, m, y in zip(probability, mid, observed)]


def _row(captured_at, market, target, lead, bands, source="nbp"):
    return dict(event_id=f"{market}-{target}", market_id=market, target_date=target, lead=lead,
                source=source, captured_at=captured_at, bands=bands)


# Hand-computed band Brier (provider, mid): A (.04, .16), G (0, .25), E (.49, .25).
ROWS = [
    _row("2026-09-26T04:00:00+00:00", "x", "2026-09-27", 1, _bands((.8, .2), (.6, .4))),  # A
    _row("2026-09-26T09:45:00+00:00", "x", "2026-09-27", 1, _bands((1.0, 0.0), (.5, .5))),  # G
    _row("2026-09-26T11:45:00-04:00", "y", "2026-09-27", 1, _bands((.3, .7), (.5, .5))),  # E
    _row("2026-09-26T08:15:30+00:00", "x", "2026-09-28", 2, _bands((.8, .2), (.6, .4))),  # B
    _row("2026-09-26T00:10:00+00:00", "y", "2026-09-28", 2, _bands((.8, .2), (.6, .4))),  # C
    _row("2026-09-26T13:40:00+00:00", "z", "2026-09-28", 2, _bands((.8, .2), (.6, .4))),  # D
    _row("2026-09-26T21:29:00+00:00", "w", "2026-09-28", 2, _bands((.8, .2), (.6, .4)), "fallback"),  # F
    _row("2026-09-26T04:00:00+00:00", "v", "2026-09-27", 1, _bands((.5, .5), (.5, .5)), "nbp_atoms"),
]
# (gfs, ecmwf, latest-of-either) minutes, from 03:30/09:30/15:30/21:30 and 01:40/07:40/13:40/19:40 UTC.
EXPECTED_MINUTES = [(30, 140, 30), (15, 125, 15), (15, 125, 15), (285.5, 35.5, 35.5),
                    (160, 270, 160), (250, 0, 0), (359, 109, 109)]
EXPECTED_BUCKETS = [("[0,60)", "[120,240)", "[0,60)"), ("[0,60)", "[120,240)", "[0,60)"),
                    ("[0,60)", "[120,240)", "[0,60)"), ("[240,360]", "[0,60)", "[0,60)"),
                    ("[120,240)", "[240,360]", "[120,240)"), ("[240,360]", "[0,60)", "[0,60)"),
                    ("[240,360]", "[60,120)", "[60,120)")]


def _run(tmp_path, report):
    path = tmp_path / "report.json"
    raw = report if isinstance(report, bytes) else json.dumps(report).encode()
    path.write_bytes(raw)
    assert nwp.main(["--report", str(path)]) == 0
    assert path.read_bytes() == raw
    return json.loads((tmp_path / "buckets.json").read_text(encoding="utf-8"))


def test_fixture_reproduces_hand_computed_assignments_and_intervals(tmp_path):
    result = _run(tmp_path, dict(status="DESCRIPTIVE_ONLY", selected_hours=ROWS, tables={}))
    assert result["status"] == "REPORTED_ONLY"
    assert result["interpretation_constraint"] == nwp.INTERPRETATION_CONSTRAINT
    assert "**by construction**" in result["interpretation_constraint"]
    assigned = result["assignments"]
    assert [a["market_id"] for a in assigned] == ["x", "x", "y", "x", "y", "z", "w"]  # tied stratum excluded
    for a, minutes, buckets in zip(assigned, EXPECTED_MINUTES, EXPECTED_BUCKETS):
        assert tuple(a["minutes_since"][k] for k in nwp.CLOCKS) == pytest.approx(minutes)
        assert tuple(a["buckets"][k] for k in nwp.CLOCKS) == buckets

    cells = result["cells"]
    assert len(cells) == 2 * 3 * 4
    # One date, two markets: x's day averages hours A and G, (.02, .205); y is E, (.49, .25).
    cell = cells["lead_1/gfs/[0,60)"]
    assert (cell["hours"], cell["band_hours"], cell["market_days"]) == (3, 6, 2)
    assert (cell["date_clusters"], cell["market_clusters"], cell["status"]) == (1, 2, "UNDERPOWERED")
    diff = cell["brier"]["provider_minus_mid"]
    assert diff["estimate"] == pytest.approx((-.185 + .24) / 2)
    # Market multiplicities (2,0)/(1,1)/(0,2) each far above 5%: the tails are the two days exactly.
    assert diff["crossed"]["interval_90"] == pytest.approx([-.185, .24])
    assert diff["crossed"]["valid_replicates"] == nwp.REPLICATES
    assert diff["date_only"]["interval_90"] == pytest.approx([.0275, .0275])
    assert cell["brier"]["provider"]["estimate"] == pytest.approx((.02 + .49) / 2)
    assert cells["lead_1/ecmwf/[120,240)"]["brier"] == cell["brier"]

    single = cells["lead_2/ecmwf/[240,360]"]  # C alone
    assert (single["hours"], single["market_days"]) == (1, 1)
    assert single["brier"]["provider_minus_mid"]["crossed"]["interval_90"] == pytest.approx([-.12, -.12])
    assert single["brier"]["provider_minus_mid"]["date_only"]["interval_90"] == pytest.approx([-.12, -.12])
    assert cells["lead_2/latest_of_either/[0,60)"]["hours"] == 2  # B and D
    assert cells["lead_2/latest_of_either/[60,120)"]["hours"] == 1  # fallback F is a member

    empty = cells["lead_2/gfs/[60,120)"]
    assert (empty["hours"], empty["brier"], empty["status"]) == (0, None, "UNDERPOWERED")


@pytest.mark.parametrize("report, reason", [
    (dict(status="DESCRIPTIVE_ONLY", tables={}), "missing_selected_hours"),
    (dict(selected_hours=[{k: v for k, v in ROWS[0].items() if k != "captured_at"}]), "missing_selected_hour_fields"),
    (dict(selected_hours=[dict(ROWS[0], captured_at="2026-09-26T04:00:00")]), "naive_captured_at"),
    (b"not json", "report_not_a_json_object"),
])
def test_report_without_the_fields_is_not_computed(tmp_path, report, reason):
    result = _run(tmp_path, report)
    assert (result["status"], result["reason"]) == ("NOT_COMPUTED", reason)
    assert "cells" not in result
    assert result["interpretation_constraint"] == nwp.INTERPRETATION_CONSTRAINT


def test_existing_output_and_missing_report_refuse(tmp_path):
    with pytest.raises(SystemExit) as missing:
        nwp.main(["--report", str(tmp_path / "report.json")])
    assert missing.value.code == 2
    (tmp_path / "report.json").write_text("{}", encoding="utf-8")
    (tmp_path / "buckets.json").write_text("kept", encoding="utf-8")
    with pytest.raises(SystemExit) as exists:
        nwp.main(["--report", str(tmp_path / "report.json")])
    assert exists.value.code == 2
    assert (tmp_path / "buckets.json").read_text(encoding="utf-8") == "kept"


def test_vendored_aggregation_matches_the_frozen_statistics():
    frozen = pytest.importorskip("weather.market.maker_fair_value_statistics")
    rng = random.Random(3)
    rows = []
    for _ in range(120):
        n, y = rng.randint(2, 4), rng.randrange(2)
        rows.append(dict(target_date=f"2026-09-{rng.randint(10, 30)}", market_id=f"m{rng.randint(0, 12)}",
                         bands=[dict(probability=rng.random(), mid=rng.random(), observed_yes=int(j == y),
                                     stdev=.1) for j in range(n)]))
    for subset in (rows, rows[:3], []):
        expected, actual = frozen.summarize(subset), nwp.summarize_brier(subset)
        assert {k: expected[k] for k in actual} == actual
