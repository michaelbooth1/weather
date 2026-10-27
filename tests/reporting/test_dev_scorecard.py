"""Development scorecard: date guard, walk-forward folds, scoring semantics, content addressing.

Guards: owner directive 2026-10-23 (lane C) that the scorecard reads dates <= 2026-09-29 only and
refuses later dates; EF section 3 (positive control); EF section 5 (crossed date x market clustering,
never pooled across 2026-07-31); walk-forward training strictly before each scored fold.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather.reporting.scorecards import dev_scorecard as sc
from weather.reporting.scorecards import dev_scorecard_data as data

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "reporting" / "dev_scorecard" / \
    "hard_floor_snapshot_deltas.csv.gz"
BANDS = (("lte", 79, 79), ("eq", 80, 81), ("gte", 82, 82))


def _parquet(frame, path):
    frame.to_parquet(path, index=False)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_layout(root, n_dates=14, markets=("m1", "m2"), first=date(2026, 8, 1), manifest_dates=None,
                 seed=7):
    rng = np.random.default_rng(seed)
    snaps, bands, labels, market = [], [], [], []
    for k in range(n_dates):
        day = (first + timedelta(days=k)).isoformat()
        for mk in markets:
            winner = int(rng.integers(0, 3))
            for hour in (3, 14):
                rk = f"{mk}|{day}T{hour:02d}"
                snaps.append({"row_key": rk, "market": mk, "date": day, "local_hour": hour, "n_bands": 3,
                              "high_so_far": 70.0, "guidance_physical_floor": np.nan,
                              "trusted_current_max": np.nan, "feature_x": float(rng.normal())})
                ps, pm = rng.dirichlet(np.ones(3)), rng.dirichlet(np.ones(3))
                for i, (kind, lo, hi) in enumerate(BANDS):
                    bands.append({"row_key": rk, "band_index": i, "kind": kind, "low": lo, "high": hi,
                                  "p_served": float(ps[i]), "date": day, "market": mk})
                    market.append({"row_key": rk, "band_index": i, "date": day, "market": mk,
                                   "p_market_yes": float(pm[i])})
                labels.append({"row_key": rk, "date": day, "market": mk, "winner": winner,
                               "settlement_high": 80.0 + winner, "settlement_bucket": 80 + winner,
                               "promotion_countable": False})
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    frames = {data.SNAPSHOTS_FILE: pd.DataFrame(snaps), data.BANDS_FILE: pd.DataFrame(bands),
              data.LABELS_FILE: pd.DataFrame(labels), data.MARKET_FILE: pd.DataFrame(market)}
    files = {}
    for name, frame in frames.items():
        files[name] = {"sha256": _parquet(frame, root / name), "rows": len(frame),
                       "dates": manifest_dates or sorted(frame.date.unique())}
    (root / data.MANIFEST).write_text(json.dumps({"schema": data.LAYOUT_SCHEMA, "files": files}), encoding="utf-8")
    return root


def run_cli(args):
    return sc.main([str(a) for a in args])


# ----------------------------------------------------------------------------- date guard

@pytest.mark.parametrize("start,end", [("2026-08-01", "2026-09-30"), ("2026-07-30", "2026-08-10"),
                                       ("2026-08-05", "2026-08-04"), ("2026-10-23", "2026-10-24")])
def test_cli_refuses_ranges_outside_development_before_touching_the_layout(tmp_path, start, end, capsys):
    missing = tmp_path / "no-such-layout"
    code = run_cli(["score", "--layout", missing, "--from", start, "--to", end, "--candidate", "served",
                    "--out", tmp_path / "out"])
    assert code == 2
    assert "refused" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_last_development_date_is_accepted(tmp_path):
    assert data.check_range("2026-07-31", "2026-09-29") == (date(2026, 7, 31), date(2026, 9, 29))


def test_layout_declaring_a_later_date_is_refused_before_any_file_is_opened(tmp_path, monkeypatch):
    root = write_layout(tmp_path / "lay", manifest_dates=["2026-08-01", "2026-09-30"])
    opened = []
    real = data._read_verified
    monkeypatch.setattr(data, "_read_verified", lambda *a: opened.append(a[1]) or real(*a))
    with pytest.raises(data.Refused, match="after 2026-09-29"):
        data.load_layout(root, data.DEV_FIRST, data.DEV_LAST)
    assert opened == []


def test_a_later_row_hidden_behind_an_honest_looking_manifest_is_refused(tmp_path):
    root = write_layout(tmp_path / "lay", n_dates=2)
    lab = pd.read_parquet(root / data.LABELS_FILE)
    lab.loc[0, "date"] = "2026-10-01"
    manifest = json.loads((root / data.MANIFEST).read_text())
    manifest["files"][data.LABELS_FILE]["sha256"] = _parquet(lab, root / data.LABELS_FILE)
    (root / data.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(data.Refused, match="after 2026-09-29"):
        data.load_layout(root, data.DEV_FIRST, data.DEV_LAST)


def test_rows_outside_the_range_are_filtered_at_read_time(tmp_path):
    root = write_layout(tmp_path / "lay", n_dates=10)
    lay = data.load_layout(root, date(2026, 8, 3), date(2026, 8, 5))
    assert lay.dates == ["2026-08-03", "2026-08-04", "2026-08-05"]
    assert set(lay.labels.date) == set(lay.dates) and set(lay.market.date) == set(lay.dates)


def test_tampered_file_fails_its_manifest_sha(tmp_path):
    root = write_layout(tmp_path / "lay", n_dates=2)
    pd.read_parquet(root / data.MARKET_FILE).assign(p_market_yes=0.5).to_parquet(root / data.MARKET_FILE)
    with pytest.raises(data.LayoutError, match="sha256"):
        data.load_layout(root, data.DEV_FIRST, data.DEV_LAST)


# ----------------------------------------------------------------------------- folds

def test_fold_scheme_trains_strictly_before_each_fold_with_a_gap():
    avail = [(date(2026, 8, 1) + timedelta(days=k)).isoformat() for k in range(21)]
    folds = data.make_folds(avail, date(2026, 8, 1), date(2026, 8, 21), fold_days=7, gap_days=1,
                            min_train_dates=5)
    assert [(f.start, f.end) for f in folds] == [("2026-08-01", "2026-08-07"), ("2026-08-08", "2026-08-14"),
                                                ("2026-08-15", "2026-08-21")]
    assert [f.scored for f in folds] == [False, True, True]
    assert folds[1].train_last == "2026-08-06" and folds[1].train_dates[-1] == "2026-08-06"
    assert max(folds[2].train_dates) == "2026-08-13"
    assert all(max(f.train_dates or ("0",)) < f.start for f in folds)


# ----------------------------------------------------------------------------- scoring semantics

def _score(tmp_path, spec, n_dates=14, markets=("m1", "m2"), min_train=0, **kw):
    root = write_layout(tmp_path / "lay", n_dates=n_dates, markets=markets)
    return sc.run_score(root, "2026-08-01", (date(2026, 8, 1) + timedelta(days=n_dates - 1)).isoformat(), spec,
                        min_train_dates=min_train, **kw)


def test_market_as_candidate_gives_ratio_exactly_one_everywhere(tmp_path):
    payload = _score(tmp_path, data.CandidateSpec("market"))
    for row in payload["rows"]:
        assert row["gap_ratio"]["estimate"] == pytest.approx(1.0, abs=1e-12)
        assert row["gap_ratio"]["ci95"] == pytest.approx([1.0, 1.0], abs=1e-12)
        assert row["model_minus_market"]["estimate"] == pytest.approx(0.0, abs=1e-15)


def test_served_ratio_matches_an_independent_cell_computation(tmp_path):
    payload = _score(tmp_path, data.CandidateSpec("served"))
    root = tmp_path / "lay"
    b = pd.read_parquet(root / data.BANDS_FILE).merge(pd.read_parquet(root / data.MARKET_FILE)[
        ["row_key", "band_index", "p_market_yes"]]).merge(pd.read_parquet(root / data.LABELS_FILE)[
            ["row_key", "winner"]])
    b["y"] = (b.band_index == b.winner).astype(float)
    b["se_s"], b["se_m"] = (b.p_served - b.y) ** 2, (b.p_market_yes - b.y) ** 2
    snap = b.groupby(["row_key", "date", "market"])[["se_s", "se_m"]].mean().reset_index()
    cell = snap.groupby(["date", "market"])[["se_s", "se_m"]].mean()
    row = next(r for r in payload["rows"] if r["market"] == "ALL" and r["block"] == "all")
    assert row["gap_ratio"]["estimate"] == pytest.approx(cell.se_s.sum() / cell.se_m.sum(), rel=1e-12)
    assert row["brier_market"] == pytest.approx(cell.se_m.mean(), rel=1e-12)
    lo, hi = row["gap_ratio"]["ci95"]
    assert lo <= row["gap_ratio"]["estimate"] <= hi
    assert row["n_dates"] == 14 and row["n_markets"] == 2 and row["n_market_days"] == 28
    assert "model_minus_served" not in row
    assert row["provenance"]["labels"] and row["provenance"]["layout_manifest_sha256"]


def test_powered_flag_uses_the_twelve_cluster_floor_on_every_resampled_dimension(tmp_path):
    payload = _score(tmp_path, data.CandidateSpec("served"), n_dates=12)
    rows = {(r["market"], r["block"]): r for r in payload["rows"]}
    assert rows[("m1", "all")]["powered"] is True               # 12 dates, one market: date-clustered
    assert rows[("ALL", "all")]["powered"] is False             # 2 market clusters < 12
    payload = _score(tmp_path / "b", data.CandidateSpec("served"), n_dates=11)
    assert all(not r["powered"] for r in payload["rows"])


def test_candidate_floor_mask_zeroes_impossible_bands_and_falls_back_to_served(tmp_path):
    root = write_layout(tmp_path / "lay", n_dates=3)
    snaps = pd.read_parquet(root / data.SNAPSHOTS_FILE)
    snaps["high_so_far"] = 80.2                                  # floor bucket 80 -> band 0 (lte 79) impossible
    manifest = json.loads((root / data.MANIFEST).read_text())
    manifest["files"][data.SNAPSHOTS_FILE]["sha256"] = _parquet(snaps, root / data.SNAPSHOTS_FILE)
    (root / data.MANIFEST).write_text(json.dumps(manifest))
    lay = data.load_layout(root, data.DEV_FIRST, date(2026, 8, 3))
    table = sc.Table(lay, lay.dates)
    first = table.snaps.row_key.iloc[0]
    frame = pd.DataFrame({"row_key": [first] * 3, "band_index": [0, 1, 2], "p": [0.5, 0.25, 0.25]})
    p, reasons = table.candidate_vector(frame)
    assert p[:3] == pytest.approx([0.0, 0.5, 0.5])
    assert p[3:6] == pytest.approx(table.p_served[3:6])         # uncovered snapshot keeps served
    assert reasons == {"absent": len(table.snaps) - 1, "candidate": 1}


# ----------------------------------------------------------------------------- walk-forward candidates

MODULE = '''
import pandas as pd
NAME = "probe"
SEEN = []
def fit(train):
    SEEN.append(sorted(set(train["labels"].date)))
    assert "p_market_yes" not in train["bands"].columns
    return {"last": max(train["labels"].date)}
def predict(state, snaps, bands):
    assert "winner" not in snaps.columns and "p_market_yes" not in bands.columns
    assert min(snaps.date) > state["last"]
    out = bands[["row_key", "band_index"]].copy()
    out["p"] = 1.0 / 3
    return out
'''


def test_module_candidate_is_fit_per_fold_on_labels_before_the_fold(tmp_path):
    path = tmp_path / "cand.py"
    path.write_text(MODULE)
    root = write_layout(tmp_path / "lay", n_dates=21)
    payload = sc.run_score(root, "2026-08-01", "2026-08-21", data.CandidateSpec("module", str(path)),
                           fold_days=7, gap_days=1, min_train_dates=5)
    fits = payload["candidate"]["fits"]
    assert [f["fold"] for f in fits] == [1, 2]
    assert [f["max_train_label_date"] for f in fits] == ["2026-08-06", "2026-08-13"]
    assert payload["population"]["first_date"] == "2026-08-08"
    assert payload["candidate"]["walk_forward"] == "enforced_fit_per_fold"
    assert payload["candidate_coverage"] == {"candidate": payload["population"]["n_snapshots"]}
    assert all("model_minus_served" in r for r in payload["rows"])


def test_module_returning_rows_outside_its_fold_is_refused(tmp_path, capsys):
    path = tmp_path / "cand.py"
    path.write_text(MODULE.replace('out = bands[["row_key", "band_index"]].copy()',
                                   'out = bands[["row_key", "band_index"]].copy()\n'
                                   '    out.loc[0, "row_key"] = "m1|2026-08-01T03"'))
    root = write_layout(tmp_path / "lay", n_dates=14)
    code = run_cli(["score", "--layout", root, "--from", "2026-08-01", "--to", "2026-08-14",
                    "--candidate-module", path, "--min-train-dates", "5", "--out", tmp_path / "out"])
    assert code == 6
    assert "outside its fold" in capsys.readouterr().err


def test_vectors_candidate_must_declare_training_and_not_overlap_scored_folds(tmp_path):
    root = write_layout(tmp_path / "lay", n_dates=14)
    bands = pd.read_parquet(root / data.BANDS_FILE)
    vec = bands[["row_key", "band_index"]].assign(p=1.0 / 3)
    vec_path = tmp_path / "vec.parquet"
    vec.to_parquet(vec_path)
    base = ["score", "--layout", root, "--from", "2026-08-01", "--to", "2026-08-14", "--min-train-dates", "5",
            "--candidate-vectors", vec_path, "--out", tmp_path / "out"]
    assert run_cli(base) == 6
    assert run_cli(base + ["--trained-through", "2026-08-07"]) == 6       # fold 08-08 trains only to 08-06
    assert run_cli(base + ["--trained-through", "2026-08-06"]) == 0
    assert run_cli(base + ["--no-training"]) == 0


def test_distribution_candidate_maps_native_buckets_onto_bands(tmp_path):
    root = write_layout(tmp_path / "lay", n_dates=2, markets=("m1",))
    rows = [{"market": "m1", "snapshot_id": "2026-08-01T03", "target_date": "2026-08-01",
             "distribution": {"78": 0.1, "79": 0.1, "80": 0.3, "81": 0.1, "82": 0.2, "83": 0.2}},
            {"market": "m1", "snapshot_id": "unknown", "distribution": {"80": 1.0}}]
    path = tmp_path / "d.jsonl.gz"
    path.write_bytes(gzip.compress("\n".join(json.dumps(r) for r in rows).encode()))
    lay = data.load_layout(root, data.DEV_FIRST, date(2026, 8, 2))
    frame, meta = data.distribution_predictions(data.CandidateSpec("distributions", str(path), no_training=True),
                                                lay, [])
    assert frame.p.tolist() == pytest.approx([0.2, 0.4, 0.4])
    assert meta["unknown_snapshots"] == 1
    late = tmp_path / "late.jsonl"
    late.write_text(json.dumps({**rows[0], "target_date": "2026-09-30"}))
    with pytest.raises(data.Refused):
        data.distribution_predictions(data.CandidateSpec("distributions", str(late), no_training=True), lay, [])


# ----------------------------------------------------------------------------- outputs and control

def test_outputs_are_deterministic_and_content_addressed(tmp_path, capsys):
    root = write_layout(tmp_path / "lay", n_dates=5)
    args = ["score", "--layout", root, "--from", "2026-08-01", "--to", "2026-08-05", "--candidate", "served",
            "--min-train-dates", "0"]
    assert run_cli(args + ["--out", tmp_path / "a"]) == 0
    assert run_cli(args + ["--out", tmp_path / "b"]) == 0
    first, second = (json.loads(line) for line in capsys.readouterr().out.strip().splitlines())
    assert first["sha256"] == second["sha256"]
    body = Path(first["json"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == first["sha256"] == Path(first["json"]).stem
    assert Path(first["md"]).read_text(encoding="utf-8").startswith("# Development scorecard")
    assert json.loads(body)["schema"] == sc.SCHEMA_VERSION


def test_serving_floor_positive_control_reproduces_ef3():
    payload = sc.run_floor_control(FIXTURE)
    assert payload["verdict"] == "PASS"
    assert payload["tracker_method"]["digits_match_ef3"] is True
    assert round(payload["tracker_method"]["delta"], 10) == sc.FLOOR_REFERENCE["delta"]
    native = payload["scorecard_method"]
    assert native["delta"]["estimate"] < 0 and native["delta"]["ci95"][1] < 0
    assert (native["n_dates"], native["n_markets"], native["n_market_days"]) == (8, 11, 85)


def test_floor_control_refuses_a_fixture_with_the_wrong_bytes(tmp_path):
    bad = tmp_path / "x.csv"
    bad.write_text("target_date,market_id,baseline_current_brier,hard_current_brier,market_brier\n")
    with pytest.raises(data.LayoutError, match="sha256"):
        sc.run_floor_control(bad)


# ----------------------------------------------------------------------------- paired control (lane G)

def test_control_equal_to_served_reproduces_model_minus_served_and_self_control_is_zero(tmp_path):
    path = tmp_path / "cand.py"
    path.write_text(MODULE)
    root = write_layout(tmp_path / "lay", n_dates=14)
    bands = pd.read_parquet(root / data.BANDS_FILE)
    served = bands[["row_key", "band_index"]].assign(p=bands.p_served.to_numpy())
    served.to_csv(tmp_path / "served.csv", index=False)
    cand = data.CandidateSpec("module", str(path))
    ctl = data.CandidateSpec("vectors", str(tmp_path / "served.csv"), no_training=True)
    payload = sc.run_score(root, "2026-08-01", "2026-08-14", cand, min_train_dates=5, control=ctl)
    assert payload["control"]["kind"] == "vectors"
    for row in payload["rows"]:
        assert row["model_minus_control"]["estimate"] == pytest.approx(row["model_minus_served"]["estimate"],
                                                                        abs=1e-15)
        assert row["model_minus_control"]["ci95"] == pytest.approx(row["model_minus_served"]["ci95"], abs=1e-15)
        assert row["control_minus_served"]["estimate"] == pytest.approx(0.0, abs=1e-15)
    same = sc.run_score(root, "2026-08-01", "2026-08-14", cand, min_train_dates=5,
                        control=data.CandidateSpec("module", str(path)))
    assert all(r["model_minus_control"]["ci95"] == pytest.approx([0.0, 0.0], abs=1e-15) for r in same["rows"])
    assert all(r["model_minus_served"]["estimate"] != 0.0 for r in same["rows"])


def test_control_cannot_be_the_served_or_market_identity(tmp_path):
    path = tmp_path / "cand.py"
    path.write_text(MODULE)
    root = write_layout(tmp_path / "lay", n_dates=14)
    with pytest.raises(data.Refused, match="control"):
        sc.run_score(root, "2026-08-01", "2026-08-14", data.CandidateSpec("module", str(path)),
                     min_train_dates=5, control=data.CandidateSpec("served"))


def test_cli_control_module_writes_the_paired_columns(tmp_path, capsys):
    path = tmp_path / "cand.py"
    path.write_text(MODULE)
    root = write_layout(tmp_path / "lay", n_dates=14)
    code = run_cli(["score", "--layout", root, "--from", "2026-08-01", "--to", "2026-08-14",
                    "--candidate-module", path, "--control-module", path, "--min-train-dates", "5",
                    "--out", tmp_path / "out"])
    assert code == 0
    md = Path(json.loads(capsys.readouterr().out)["md"]).read_text(encoding="utf-8")
    assert "model - control [95%]" in md and "- Control: `module`" in md


def test_hourly_rows_and_date_clustered_paired_intervals(tmp_path):
    path = tmp_path / "cand.py"
    path.write_text(MODULE)
    root = write_layout(tmp_path / "lay", n_dates=14)
    spec = data.CandidateSpec("module", str(path))
    payload = sc.run_score(root, "2026-08-01", "2026-08-14", spec, min_train_dates=5,
                           control=data.CandidateSpec("module", str(path)), hourly=True)
    blocks = {r["block"] for r in payload["rows"] if r["market"] == "ALL"}
    assert {"h03", "h14", "13-16"} <= blocks and not {"h05", "07-12"} & blocks   # fixture hours are 3 and 14
    pooled = [r for r in payload["rows"] if r["market"] == "ALL"]
    assert all("model_minus_control_date_clustered" in r for r in pooled)
    assert not any("model_minus_control_date_clustered" in r for r in payload["rows"] if r["market"] != "ALL")
    row = next(r for r in pooled if r["block"] == "all")
    assert row["model_minus_served_date_clustered"]["estimate"] == pytest.approx(row["model_minus_served"]["estimate"])
    plain = sc.run_score(root, "2026-08-01", "2026-08-14", spec, min_train_dates=5)
    assert not any(r["block"].startswith("h") for r in plain["rows"])
