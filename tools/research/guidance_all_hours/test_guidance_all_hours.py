"""Synthetic contracts; no production evidence or network access."""
import gzip
import hashlib
import json

import pytest

from tools.research.guidance_all_hours.features import v2_features, v2_valid
from tools.research.guidance_all_hours.run import block, decision, load_rows, verify_input
from tools.research.morning_guidance.candidate import candidates


def row(**v2):
    values = dict(zip(("v2_p10", "v2_p25", "v2_p50", "v2_p75", "v2_p90", "v2_mean", "v2_stddev"),
                      (69, 70, 71, 72, 74, 71, 2)))
    values.update(v2)
    return {"unit": "F", "v2_status": "available", "target_date": "2026-09-01",
            "features": {"nbm_prob_tmax_p50": 55, "nbm_prob_tmax_physical_valid_flag": 0,
                         "nbm_prob_tmax_impossible_flag": 1, "guidance_physical_floor": 70.6,
                         "high_so_far": 70.6, "forecast_high": 71}, **values}


def test_only_nbm_values_and_flags_are_replaced():
    f = v2_features(row())
    assert f["nbm_prob_tmax_p50"] == 71 and f["nbm_prob_tmax_stddev"] == 2
    assert f["nbm_prob_tmax_physical_valid_flag"] == 1 and f["nbm_prob_tmax_impossible_flag"] == 0
    assert f["forecast_high"] == 71 and f["guidance_physical_floor"] == 70.6
    bands = [{"kind": "lte", "low": 70, "high": 70}, {"kind": "eq", "low": 71, "high": 71},
             {"kind": "gte", "low": 72, "high": 72}]
    assert candidates(bands, [.2, .5, .3], f)[2] == "eligible"


def test_unavailable_v2_leaves_no_nbm_values_so_candidate_falls_back():
    f = v2_features({**row(), "v2_status": "unavailable"})
    assert not any(k.startswith("nbm_prob_tmax_") for k in f)


def test_floor_margin_and_partial_impossibility_follow_the_builder():
    floor = 70.0
    ok = {"nbm_prob_tmax_p10": 69.1, "nbm_prob_tmax_p90": 75, "nbm_prob_tmax_mean": 72}
    assert v2_valid(ok, floor, "F")
    assert not v2_valid({**ok, "nbm_prob_tmax_p10": 69.09}, floor, "F")   # partial -> invalid
    assert not v2_valid({"nbm_prob_tmax_p90": 68}, floor, "F")
    assert v2_valid({"nbm_prob_tmax_p90": 10}, None, "F")                # no captured floor
    assert not v2_valid({}, floor, "F")


def test_exam_panel_rows_are_counted_and_never_loaded(tmp_path):
    with gzip.open(tmp_path / "guidance_rows.jsonl.gz", "wt") as stream:
        for d in ("2026-09-29", "2026-09-30", "2026-10-01"):
            stream.write(json.dumps({**row(), "target_date": d}) + "\n")
    rows, exam = load_rows(tmp_path)
    assert [r["target_date"] for r in rows] == ["2026-09-29"]
    assert exam["rows_with_target_on_or_after_2026_09_30"] == 2


def test_input_must_match_sums_and_be_complete(tmp_path):
    manifest = {"status": "INCOMPLETE_BUDGET_EXCEEDED", "parser": {"head": "2e17ce0eb" + "0" * 31}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    for name in ("guidance_rows.jsonl.gz", "market_days.jsonl.gz"):
        (tmp_path / name).write_bytes(b"x")
    def sums():
        (tmp_path / "SHA256SUMS").write_text("".join(
            f"{hashlib.sha256((tmp_path / n).read_bytes()).hexdigest()} *{n}\n"
            for n in ("guidance_rows.jsonl.gz", "market_days.jsonl.gz", "manifest.json")))
    sums()
    with pytest.raises(ValueError, match="COMPLETE"):
        verify_input(tmp_path)
    (tmp_path / "market_days.jsonl.gz").write_bytes(b"y")
    with pytest.raises(ValueError, match="SHA256SUMS"):
        verify_input(tmp_path)


def test_hour_blocks_and_decision_rule():
    assert [block(h) for h in (0, 5, 6, 9, 10, 12, 13, 16, 17, 23)] == [
        "00-05", "00-05", "06-09", "06-09", "10-12", "10-12", "13-16", "13-16", "17-23", "17-23"]
    def t(b, s, est, ci):
        d = {"delta": {"estimate": est, "ci95": ci}}
        return {"block": b, "stratum": s, "C1": d, "C2": d}
    tables = [t("all_hours", "pooled", -.014, [-.02, -.012]), t("all_hours", "before_20260823", -.01, [0, 0]),
              t("all_hours", "from_20260823", .001, [0, 0]), t("13-16", "pooled", -.01, [-.02, -.001]),
              t("17-23", "pooled", -.01, [-.02, .001])]
    out = decision(tables, {"label_for_v2_tables": None})
    assert out["C1"]["reaches_twice_descriptive"] and not out["C1"]["reaches_twice_interval"]
    assert out["C1"]["strata_opposite_sign"]
    f1 = out["falsifier_1_stale_07z_adds_nothing"]
    assert not f1["13-16"]["afternoon_route_falsified"] and f1["17-23"]["afternoon_route_falsified"]
    assert not out["falsifier_2_pooled_near_81a"]["all_hours_route_closed"]
