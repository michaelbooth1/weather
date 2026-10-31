"""Ruling (i) per-date extractor on synthetic B look worlds only (no repository data, label or price is read).

Each test builds B's own synthetic look world (``test_b_scorer._look_inputs``), runs ``b_scorer.look`` on it, then
extracts. The extractor must read only the bytes B read, reproduce B's printed rows, and feed the frozen post-look
module.

Guards: docs/research/b-look-prep-2026-10-31/master-ruling-b-post-look.md (master ruling (b) and ruling (i), frozen
module pins).
"""
import ast
import json
from pathlib import Path

import pandas as pd
import pytest

from tests.calibration.test_b_scorer import DATES, _look_inputs
from tests.host_guard import import_or_skip_on_capture_host

b = import_or_skip_on_capture_host("weather.calibration.b_scorer")
pdx = import_or_skip_on_capture_host("weather.calibration.b_look_per_date")
from weather.calibration import b_post_look_serial as post  # noqa: E402


def _looked(tmp_path, monkeypatch, **kw):
    args = _look_inputs(tmp_path, monkeypatch, **kw)
    b.look(**args)
    return args


def _extract(args, **over):
    return pdx.extract(**{"look_out": args["out"], "layout_root": args["layout_root"], "vectors": args["vectors"],
                          "transfer": args["transfer"], "drop_list": args["drop_list"], **over})


def _nothing_written(args):
    return not (Path(args["out"]) / pdx.PER_DATE).exists() and not (Path(args["out"]) / pdx.RECEIPT).exists()


def test_extraction_reproduces_b_and_feeds_the_post_look_module(tmp_path, monkeypatch):
    args = _looked(tmp_path, monkeypatch)
    look = json.loads((args["out"] / b.LOOK).read_text(encoding="utf-8"))
    payload = _extract(args)
    assert [r["date"] for r in payload["primary"]] == DATES
    assert {r["n"] for r in payload["primary"]} == {10}  # ten markets, one (date, market) cell each
    assert sorted(payload["splits"]) == ["07-12", "13-16"]
    s = sum(r["S"] for r in payload["primary"])
    n = sum(r["n"] for r in payload["primary"])
    assert s / n == pytest.approx(look["decision"]["estimate"], abs=1e-12)
    for name, rows in payload["splits"].items():
        printed = b._row(look["rows"], name)["delta"]["estimate"]
        assert sum(r["S"] for r in rows) / sum(r["n"] for r in rows) == pytest.approx(printed, abs=1e-12)
    on_disk = json.loads((args["out"] / pdx.PER_DATE).read_text(encoding="utf-8"))
    assert on_disk == payload
    receipt = json.loads((args["out"] / pdx.RECEIPT).read_text(encoding="utf-8"))
    assert receipt["schema"] == pdx.RECEIPT_SCHEMA and receipt["module_sha256"] == pdx.module_sha256()
    assert receipt["b_look_sha256"] == b.sha256_file(args["out"] / b.LOOK)
    assert receipt["per_date_sha256"] == b.sha256_file(args["out"] / pdx.PER_DATE)
    assert receipt["inputs"]["transfer_manifest_sha256"] == look["inputs"]["transfer_manifest_sha256"]
    # the frozen post-look module accepts the extraction against B's own decision (its delta guard passes)
    result = post.analyse(payload["primary"], look, payload["splits"])
    assert result["b_verdict"] == look["decision"]["verdict"] and result["n_dates"] == 45


def test_one_extraction_per_look(tmp_path, monkeypatch):
    args = _looked(tmp_path, monkeypatch)
    _extract(args)
    with pytest.raises(pdx.PerDateRefused, match="one extraction"):
        _extract(args)


def test_a_void_look_has_no_cells(tmp_path, monkeypatch):
    args = _looked(tmp_path, monkeypatch, mg2_look={"pre_look_reads": ["price 2026-11-01"]})
    with pytest.raises(pdx.PerDateRefused, match="only a scored look"):
        _extract(args)
    assert _nothing_written(args)


def test_no_look_output_refuses(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    with pytest.raises(pdx.PerDateRefused, match="no B look output"):
        _extract(args)


def test_an_edited_b_look_refuses(tmp_path, monkeypatch):
    args = _looked(tmp_path, monkeypatch)
    path = args["out"] / b.LOOK
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(pdx.PerDateRefused, match="receipt names"):
        _extract(args)
    assert _nothing_written(args)


@pytest.mark.parametrize("which,match", [("vectors", "vectors_sha256"), ("drop_list", "drop_list_sha256"),
                                         ("manifest", "transfer_manifest_sha256")])
def test_inputs_other_than_bs_refuse(tmp_path, monkeypatch, which, match):
    args = _looked(tmp_path, monkeypatch)
    if which == "vectors":
        frame = pd.read_parquet(args["vectors"])
        frame["p"] = frame["p"] * 0.999
        other = tmp_path / "other_vectors.parquet"
        frame.to_parquet(other, index=False)
        over = {"vectors": other}
    elif which == "drop_list":
        other = tmp_path / "other_drop.json"
        other.write_text(json.dumps({"schema": b.DROP_LIST_SCHEMA, "dropped": DATES[:1]}), encoding="utf-8")
        over = {"drop_list": other}
    else:
        manifest = Path(args["transfer"]) / b.TRANSFER_MANIFEST
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        over = {}
    with pytest.raises(pdx.PerDateRefused, match=match):
        _extract(args, **over)
    assert _nothing_written(args)


def test_an_altered_transfer_file_refuses(tmp_path, monkeypatch):
    args = _looked(tmp_path, monkeypatch)
    labels = Path(args["transfer"]) / "labels.parquet"
    frame = pd.read_parquet(labels)
    frame["winner"] = (frame["winner"] + 1) % 3
    frame.to_parquet(labels, index=False)
    with pytest.raises(pdx.PerDateRefused, match="altered"):
        _extract(args)
    assert _nothing_written(args)


def test_another_layout_date_set_refuses(tmp_path, monkeypatch):
    from weather.reporting.scorecards import dev_scorecard_data as data

    args = _looked(tmp_path, monkeypatch)
    snaps_path = Path(args["layout_root"]) / data.SNAPSHOTS_FILE
    snaps = pd.read_parquet(snaps_path)
    snaps[snaps.date != DATES[-1]].to_parquet(snaps_path, index=False)
    with pytest.raises(pdx.PerDateRefused, match="look date set"):
        _extract(args)


def test_another_running_scorer_refuses(tmp_path, monkeypatch):
    args = _looked(tmp_path, monkeypatch)
    monkeypatch.setattr(b, "module_sha256", lambda: "0" * 64)
    with pytest.raises(pdx.PerDateRefused, match="B scorer"):
        _extract(args)


def test_a_table_that_does_not_reproduce_b_refuses(tmp_path, monkeypatch):
    args = _looked(tmp_path, monkeypatch)
    real = b.arm

    def shifted(table, frame):
        p, covered, reasons = real(table, frame)
        return p * 0.98 + 0.02 / 3, covered, reasons

    monkeypatch.setattr(b, "arm", shifted)
    with pytest.raises(pdx.PerDateRefused, match="does not reproduce B"):
        _extract(args)
    assert _nothing_written(args)


def test_reproduction_problems_name_each_mismatch():
    look = {"rows": [{"group": "07-16", "market": "ALL", "n_snapshots": 4, "n_market_days": 2, "n_dates": 2,
                      "brier_arm": 0.1, "brier_market": 0.2, "delta": {"estimate": -0.1}}],
            "decision": {"estimate": -0.1}}
    good = {"07-16": {"rows": [{"date": "d1", "S": -0.1, "n": 1}, {"date": "d2", "S": -0.1, "n": 1}],
                      "n_snapshots": 4, "n_market_days": 2, "n_dates": 2, "brier_arm": 0.1, "brier_market": 0.2,
                      "estimate": -0.1}, "07-12": None, "13-16": None}
    assert pdx.reproduction_problems(good, look) == []
    bad = json.loads(json.dumps(good))
    bad["07-16"]["rows"][0]["S"] = -0.2
    bad["07-16"]["n_dates"] = 3
    problems = pdx.reproduction_problems(bad, look)
    assert any("n_dates" in p for p in problems) and any("printed estimate" in p for p in problems)
    assert any("decision estimate" in p for p in problems)
    extra = dict(good, **{"07-12": good["07-16"]})
    assert any("only one of" in p for p in pdx.reproduction_problems(extra, look))


def test_cli_refusal_exits_2(tmp_path, monkeypatch, capsys):
    args = _look_inputs(tmp_path, monkeypatch)
    code = pdx.main(["--look-out", str(args["out"]), "--layout", str(args["layout_root"]),
                     "--vectors", str(args["vectors"]), "--transfer", str(args["transfer"]),
                     "--drop-list", str(args["drop_list"])])
    assert code == 2 and "refused" in capsys.readouterr().err


def test_module_edits_nothing_b_bound_and_imports_b_read_only():
    tree = ast.parse(Path(pdx.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    weather = sorted(n for n in imported if n.startswith("weather"))
    assert weather == ["weather.calibration.b_scorer", "weather.calibration.mg2_composite",
                       "weather.reporting.scorecards.dev_scorecard",
                       "weather.reporting.scorecards.dev_scorecard_data"]
    assigned = [t for node in ast.walk(tree) if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id in ("b", "mg2")]
    assert not assigned  # never monkeypatches or rebinds anything in B or MG-2
