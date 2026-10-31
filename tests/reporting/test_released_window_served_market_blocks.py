"""Served-vs-market per block on released targets: row 80 first, both controls first, target-date boundary.

Guards: P1 prep atlas readiness note (branch claude/embargo-release-export-manifest-20261031 @ 91cae102b) and
master's 2026-10-31 rulings - the wrapper refuses unless the row 80 receipt exists and names the same release
layout; the EF section 3 floor control and the loss-atlas positive control run before the release layout is
opened; a target of 10-15 or later is refused whatever its capture time; Austin 10-03 is dropped; only served
or market are read (MG-2 excluded); DEV_LAST is overridden in process only and restored; strata are never
pooled; outputs go only to a new or empty --out. Synthetic layouts only.
"""
from __future__ import annotations

import ast
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from weather.reporting.scorecards import dev_scorecard as sc
from weather.reporting.scorecards import dev_scorecard_data as data

from tests.host_guard import import_or_skip_on_capture_host

smb = import_or_skip_on_capture_host("tools.research.released_window.served_market_blocks")
la = import_or_skip_on_capture_host("weather.reporting.scorecards.loss_atlas")

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "reporting" / "dev_scorecard" / \
    "hard_floor_snapshot_deltas.csv.gz"
BANDS = (("lte", 77, 77), ("eq", 78, 79), ("eq", 80, 81), ("eq", 82, 83), ("gte", 84, 84))
HOURS = (0, 7, 10, 14, 18)
RULING = "owner 2026-10-30 release of 2026-09-30..10-14 (DECISION_LOG 2026-10-30 row, origin/master 5f4d87818)"
NETWORK = {"socket", "requests", "urllib", "http", "httpx", "aiohttp", "ftplib", "smtplib"}


def _pmf(mu, sd):
    out = []
    for kind, lo, hi in BANDS:
        up = np.inf if kind == "gte" else hi + .5
        low = -np.inf if kind == "lte" else lo - .5
        out.append(norm.cdf((up - mu) / sd) - norm.cdf((low - mu) / sd))
    p = np.maximum(np.asarray(out), 1e-6)
    return p / p.sum()


def _band(y):
    return next(i for i, (k, lo, hi) in enumerate(BANDS)
                if (k == "lte" and y <= hi) or (k == "gte" and y >= lo) or (k == "eq" and lo <= y <= hi))


def write_layout(root, first, n_dates, markets=("m1", "m2", "m3"), seed=5, extra_dates=()):
    rng = np.random.default_rng(seed)
    snaps, bands, labels, market = [], [], [], []
    days = [(first + timedelta(days=k)).isoformat() for k in range(n_dates)] + list(extra_dates)
    for day in days:
        for mk in markets:
            y = int(rng.integers(76, 86))
            for hour in HOURS:
                rk = f"{mk}|{day}T{hour:02d}"
                cap = datetime.fromisoformat(f"{day}T{hour:02d}:10:00")
                snaps.append({"row_key": rk, "snapshot_id": rk, "market": mk, "date": day, "local_hour": hour,
                              "n_bands": len(BANDS), "captured_at_utc": (cap + timedelta(hours=5)).isoformat(),
                              "high_so_far": 60.0, "guidance_physical_floor": np.nan,
                              "trusted_current_max": np.nan})
                ps, pm = _pmf(y - 1.5 + rng.normal(0, 1), 2.4), _pmf(y + rng.normal(0, .6), 1.5)
                for i, (kind, lo, hi) in enumerate(BANDS):
                    bands.append({"row_key": rk, "band_index": i, "kind": kind, "low": lo, "high": hi,
                                  "p_served": float(ps[i]), "date": day, "market": mk, "local_hour": hour})
                    market.append({"row_key": rk, "band_index": i, "date": day, "market": mk,
                                   "p_market_yes": float(pm[i])})
                labels.append({"row_key": rk, "date": day, "market": mk, "winner": _band(y),
                               "settlement_high": float(y), "settlement_bucket": _band(y),
                               "promotion_countable": False})
    root = Path(root)
    root.mkdir(parents=True)
    frames = {data.SNAPSHOTS_FILE: snaps, data.BANDS_FILE: bands, data.LABELS_FILE: labels,
              data.MARKET_FILE: market}
    files = {}
    for name, rows in frames.items():
        frame = pd.DataFrame(rows)
        frame.to_parquet(root / name, index=False)
        files[name] = {"sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(), "rows": len(frame),
                       "dates": sorted(frame.date.unique())}
    (root / data.MANIFEST).write_text(json.dumps({"schema": data.LAYOUT_SCHEMA, "files": files}),
                                      encoding="utf-8")
    return root


def dev_expected(dev):
    start, end = data.check_range(*la.RANGE)
    layout = data.load_layout(dev, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, *la.FOLDS)
    t = sc.Table(layout, sorted(d for f in folds if f.scored for d in f.dates))
    rows = {r["block"]: r for r in sc.score_rows(t, t.p_served, True) if r["market"] == sc.ALL_MARKETS}
    return {b: round(rows[b]["gap_ratio"]["estimate"], 3) for b in ("all", "00-16")}


def write_receipt(path, release, ledger_row=80, verdict="NOT REPLICATED"):
    sha = hashlib.sha256((Path(release) / data.MANIFEST).read_bytes()).hexdigest()
    path.write_text(json.dumps({"ledger_row": ledger_row, "result": {"verdict": verdict},
                                "layout_manifest_sha256": sha}), encoding="utf-8")
    return path


@pytest.fixture
def world(tmp_path):
    dev = write_layout(tmp_path / "dev", date(2026, 8, 1), 28)
    release = write_layout(tmp_path / "release", date(2026, 10, 1), 14, markets=("m1", "m2", "austin"))
    receipt = write_receipt(tmp_path / "receipt.json", release)
    return {"dev": dev, "release": release, "receipt": receipt, "expected": dev_expected(dev),
            "out": tmp_path / "out", "swarm": tmp_path / "swarm"}


def _run(w, **over):
    kw = {"row80_receipt": w["receipt"], "floor_fixture": FIXTURE, "dev_layout": w["dev"],
          "release_layout": w["release"], "ruling": RULING, "strata": "pre+post", "out": w["out"],
          "control_expected": w["expected"], "swarm_root": w["swarm"]}
    kw.update(over)
    return smb.run(**kw)


def _forbid(monkeypatch, *names):
    def boom(*_a, **_k):
        raise AssertionError("ran after a refusal")
    for owner, attr in names:
        monkeypatch.setattr(owner, attr, boom)


def test_full_run_reads_both_strata_separately_and_restores_dev_last(world):
    receipt = _run(world)
    assert data.DEV_LAST == date(2026, 9, 29)
    assert receipt["override_in_process"] == {"dev_scorecard_data.DEV_LAST": ["2026-09-29", "2026-10-14"]}
    assert receipt["dates"]["pre"][0] == "2026-10-01" and receipt["dates"]["pre"][-1] == "2026-10-09"
    assert receipt["dates"]["post"] == [f"2026-10-{d}" for d in range(10, 15)]
    assert receipt["snapshots_dropped"] == len(HOURS)            # Austin 10-03 only
    assert receipt["floor_control"]["verdict"] == "PASS" and receipt["positive_control"]["verdict"] == "PASS"
    assert receipt["evidence_class"] == "descriptive, not countable"
    payload = json.loads((world["out"] / receipt["payload"]["json"]).read_text(encoding="utf-8"))
    assert payload["pooled"] is False
    post = payload["sections"]["post"]["rows"]
    assert {r["block"] for r in post} >= {"00-05", "06-09", "10-12", "13-16", "17-23", "00-12", "00-16", "all"}
    assert not any(r["powered"] for r in post)
    austin = [r for r in payload["sections"]["pre"]["rows"] if r["market"] == "austin" and r["block"] == "all"]
    assert austin and austin[0]["n_dates"] == 8                   # 10-03 dropped from Austin's 9 pre dates
    assert sorted(p.name for p in world["out"].iterdir()) == sorted(
        [receipt["payload"]["json"], receipt["payload"]["md"], "receipt.json"])


def test_without_the_row80_receipt_nothing_else_runs(world, monkeypatch, tmp_path):
    _forbid(monkeypatch, (sc, "run_floor_control"), (la, "positive_control"))
    with pytest.raises(smb.Refused, match="row 80 look runs first"):
        _run(world, row80_receipt=tmp_path / "missing.json")


@pytest.mark.parametrize("change", [{"ledger_row": 79}, {"verdict": None}])
def test_a_receipt_from_another_row_or_without_a_verdict_is_refused(world, tmp_path, change):
    path = write_receipt(tmp_path / "r.json", world["release"], change.get("ledger_row", 80),
                         change.get("verdict", "UNTESTABLE"))
    with pytest.raises(smb.Refused):
        _run(world, row80_receipt=path)


def test_a_receipt_naming_another_layout_is_refused(world, tmp_path):
    path = write_receipt(tmp_path / "r.json", world["dev"])
    with pytest.raises(smb.Refused, match="not this release layout"):
        _run(world, row80_receipt=path)


def test_a_failed_floor_control_stops_before_the_positive_control(world, monkeypatch):
    real = sc.run_floor_control
    monkeypatch.setattr(sc, "run_floor_control", lambda p: {**real(p), "verdict": "FAIL"})
    _forbid(monkeypatch, (la, "positive_control"))
    with pytest.raises(smb.Refused, match="floor control"):
        _run(world)


def test_a_failed_positive_control_stops_before_the_release_layout(world, monkeypatch):
    _forbid(monkeypatch, (smb, "check_release_manifest"))
    with pytest.raises(la.ControlFailed):
        _run(world, control_expected={"all": 9.999, "00-16": 9.999})
    assert data.DEV_LAST == date(2026, 9, 29)


def test_an_embargoed_target_is_refused_before_the_release_layout_opens(world, tmp_path, monkeypatch):
    release = write_layout(tmp_path / "late", date(2026, 10, 1), 14, extra_dates=("2026-10-15",))
    receipt = write_receipt(tmp_path / "r.json", release)
    _forbid(monkeypatch, (data, "load_layout"))
    monkeypatch.setattr(smb, "atlas_positive_control", lambda *a, **k: {"verdict": "PASS"})
    with pytest.raises(smb.Refused, match="embargoed target 2026-10-15"):
        _run(world, release_layout=release, row80_receipt=receipt)


@pytest.mark.parametrize("name", ["mg2", "MG-2", "mg1", "b_scorer", "composite", "module"])
def test_only_served_or_market_candidates_are_read(world, name):
    with pytest.raises(smb.Refused, match="MG-2 stays excluded"):
        _run(world, candidate=name)


@pytest.mark.parametrize(("over", "message"), [
    ({"ruling": "short"}, "DECISION_LOG"),
    ({"strata": "post"}, "--strata"),
    ({"dev_layout": "C:/t/88a/dev"}, "88a or panel"),
])
def test_ruling_strata_and_path_guards(world, over, message):
    with pytest.raises(smb.Refused, match=message):
        _run(world, **over)


def test_out_must_be_new_or_empty_and_outside_swarm(world):
    world["out"].mkdir()
    (world["out"] / "x").write_text("x")
    with pytest.raises(smb.Refused, match="new or empty"):
        _run(world)
    with pytest.raises(smb.Refused, match="under"):
        _run(world, out=world["swarm"] / "cache")


def test_a_dev_last_already_moved_is_refused_before_the_controls(world, monkeypatch):
    monkeypatch.setattr(data, "DEV_LAST", date(2026, 10, 14))
    with pytest.raises(smb.Refused, match="before the controls"):
        _run(world)


def test_the_module_imports_no_network_library():
    tree = ast.parse(Path(smb.__file__).read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & NETWORK
