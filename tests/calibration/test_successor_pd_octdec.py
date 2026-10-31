import json

import numpy as np
import pytest

from weather.calibration import successor_pd_octdec as c2


def test_daily_stats_iid_vif_floor():
    dates = np.repeat([f"2021-10-{i:02d}" for i in range(1, 31)], 2)
    markets = np.tile(["a", "b"], 30)
    d = np.zeros(60)
    d[::2] = np.arange(30) % 2  # alternating per-date mean -> negative lag-1
    _, s = c2.daily_stats(dates, markets, d)
    assert s["n_dates"] == 30
    assert s["rho_lag1"] < 0
    assert s["vif"] >= 1.0


def test_versions_flags_boundary(tmp_path):
    p = tmp_path / "c.jsonl"
    rows = [dict(target_date="2023-10-01", cycle="01", product_version="4.1", available=True),
            dict(target_date="2023-12-01", cycle="01", product_version="4.2", available=True),
            dict(target_date="2024-08-01", cycle="01", product_version="4.2", available=True)]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    counts, per_year, mixed = c2.versions([p], c2.OCTDEC_MONTHS)
    assert mixed == ["2023"] and "2024" not in per_year


def test_rule_pin_refuses(tmp_path):
    rule = tmp_path / "rule.md"
    rule.write_text("not the rule", encoding="utf-8")
    with pytest.raises(c2.SuccessorC2Error):
        c2.run(research_root=tmp_path, nbm_corpora=[], rule=rule, out=tmp_path / "out" / "c2.json")
