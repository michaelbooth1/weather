"""B-1 post-look floor-zeroed-band disclosure on synthetic B look worlds only (no repository data is read).

Each test builds B's own synthetic look world (``test_b_scorer._look_inputs``), optionally raises the layout's
floor on chosen snapshots so their paying band is impossible, runs ``b_scorer.look``, then discloses.

Guards: docs/research/b-floor-disclosure-2026-11-01/ (L51's accepted draft, 468aa514c) and master's 2026-11-03
build ruling (measure "paying band zeroed by the rule-4 floor (any cause)"; SPECI attribution only from a flag in
B's bytes; descriptive, non-deciding).
"""
import ast
import json
from pathlib import Path

import pandas as pd
import pytest

from tests.calibration.test_b_scorer import DATES, _look_inputs
from tests.host_guard import import_or_skip_on_capture_host

b = import_or_skip_on_capture_host("weather.calibration.b_scorer")
fd = import_or_skip_on_capture_host("weather.calibration.b_floor_disclosure")


def _raise_floor(args, picks):
    """Set high_so_far to 72 on the given (date, market, hour) snapshots whose winner is not the gte band."""
    from weather.reporting.scorecards import dev_scorecard_data as data

    path = Path(args["layout_root"]) / data.SNAPSHOTS_FILE
    snaps = pd.read_parquet(path)
    labels = pd.read_parquet(Path(args["transfer"]) / "labels.parquet").set_index("row_key").winner
    chosen = []
    for d, m, h in picks:
        rk = f"{m}|{d}|{h}"
        if int(labels[rk]) != 2:
            snaps.loc[snaps.row_key == rk, "high_so_far"] = 72.0
            chosen.append(rk)
    snaps.to_parquet(path, index=False)
    return chosen


def _gte_snapshot(args, d, m, h):
    labels = pd.read_parquet(Path(args["transfer"]) / "labels.parquet").set_index("row_key").winner
    return int(labels[f"{m}|{d}|{h}"]) == 2


def _looked(tmp_path, monkeypatch, picks=(), **kw):
    args = _look_inputs(tmp_path, monkeypatch, **kw)
    chosen = _raise_floor(args, picks)
    b.look(**args)
    return args, chosen


def _disclose(args, **over):
    return fd.disclose(**{"look_out": args["out"], "layout_root": args["layout_root"], "vectors": args["vectors"],
                          "transfer": args["transfer"], "drop_list": args["drop_list"], **over})


def _nothing_written(args):
    return not (Path(args["out"]) / fd.DISCLOSURE).exists() and not (Path(args["out"]) / fd.RECEIPT).exists()


def test_no_zeroed_cells_reports_b_primary_unchanged(tmp_path, monkeypatch):
    args, _ = _looked(tmp_path, monkeypatch)
    look = json.loads((args["out"] / b.LOOK).read_text(encoding="utf-8"))
    payload = _disclose(args)
    assert payload["label"] == fd.LABEL and payload["zeroed_cells"]["measure"] == fd.MEASURE
    assert payload["zeroed_cells"]["n_cells"] == 0 and payload["zeroed_cells"]["cells"] == []
    assert payload["zeroed_cells"]["n_scored_cells"] == 450
    rest = payload["without_zeroed_cells"]
    assert rest["same_as_b_primary"] is True
    assert rest["estimate"] == pytest.approx(look["decision"]["estimate"], abs=1e-12)
    assert payload["b_verdict"] == look["decision"]["verdict"] and payload["b_label"] == look["decision"]["label"]
    receipt = json.loads((args["out"] / fd.RECEIPT).read_text(encoding="utf-8"))
    assert receipt["schema"] == fd.RECEIPT_SCHEMA and receipt["module_sha256"] == fd.module_sha256()
    assert receipt["disclosure_sha256"] == b.sha256_file(args["out"] / fd.DISCLOSURE)
    assert receipt["inputs"]["transfer_manifest_sha256"] == look["inputs"]["transfer_manifest_sha256"]


def test_zeroed_cells_are_listed_and_removed_from_both_arms(tmp_path, monkeypatch):
    picks = [(DATES[i], m, 14) for i in range(3) for m in ("nyc", "chicago")] + [(DATES[0], "nyc", 8)]
    args, chosen = _looked(tmp_path, monkeypatch, picks=picks)
    assert chosen, "the synthetic world must give at least one non-gte winner among the picks"
    payload = _disclose(args)
    cells = payload["zeroed_cells"]
    expected = sorted({(rk.split("|")[1], rk.split("|")[0]) for rk in chosen})
    assert [(c["date"], c["market"]) for c in cells["cells"]] == expected
    assert cells["n_zeroed_snapshots"] == len(chosen)
    for c in cells["cells"]:
        hits = [int(rk.split("|")[2]) for rk in chosen if rk.split("|")[:2] == [c["market"], c["date"]]]
        assert c["zeroed_snapshots"] == len(hits) and c["first_zeroed_local_hour"] == min(hits)
        assert c["covered_snapshots"] == 2
    rest = payload["without_zeroed_cells"]
    assert rest["same_as_b_primary"] is False
    assert rest["n_market_days"] == cells["n_scored_cells"] - cells["n_cells"]
    # the re-cut equals excess_rows on B's table with those cells dropped (same date-clustered draws)
    from weather.calibration import b_look_per_date as pdx
    from weather.calibration import mg2_composite as mg2

    look = json.loads((args["out"] / b.LOOK).read_text(encoding="utf-8"))
    surviving = pdx._dates(look, args["layout_root"], args["drop_list"])
    snaps, bands = mg2.read_inputs(args["layout_root"])
    manifest, _ = b.read_manifest(args["transfer"])
    files, _ = b.transfer_files(args["transfer"], manifest)
    table = b.build_table(snaps, bands, files["labels.parquet"], files["market.parquet"], surviving)
    p, covered, _ = b.arm(table, pd.read_parquet(args["vectors"]))
    _, drop = fd.zeroed_cells(table, p, covered)
    row = fd.primary_row(table, p, covered & ~drop)
    assert rest["estimate"] == pytest.approx(row["delta"]["estimate"], abs=1e-15)
    assert rest["ci95"] == pytest.approx(row["delta"]["ci95"], abs=1e-15)


def test_a_gte_paying_band_is_never_zeroed(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    gte = [(d, m, h) for d in DATES[:5] for m in ("nyc", "miami") for h in (8, 14) if _gte_snapshot(args, d, m, h)]
    assert gte
    from weather.reporting.scorecards import dev_scorecard_data as data

    path = Path(args["layout_root"]) / data.SNAPSHOTS_FILE
    snaps = pd.read_parquet(path)
    for d, m, h in gte:
        snaps.loc[snaps.row_key == f"{m}|{d}|{h}", "high_so_far"] = 72.0
    snaps.to_parquet(path, index=False)
    b.look(**args)
    assert _disclose(args)["zeroed_cells"]["n_cells"] == 0


def test_speci_attribution_is_not_computed_without_a_flag_in_bs_bytes(tmp_path, monkeypatch):
    args, _ = _looked(tmp_path, monkeypatch)
    speci = _disclose(args)["speci_attribution"]
    assert speci["status"] == fd.NOT_COMPUTED and speci["flag_columns"] == []
    assert "no SPECI flag" in speci["reason"]
    assert set(speci["checked"]) == {"layout_snapshots", "layout_bands", "vectors", "transfer_labels",
                                     "transfer_market"}


def test_a_speci_named_column_is_detected_but_still_not_computed():
    frames = {"layout_snapshots": pd.DataFrame(columns=["row_key", "metar_report_type"]),
              "vectors": pd.DataFrame(columns=["row_key", "p"])}
    speci = fd.speci_attribution(frames)
    assert speci["status"] == fd.NOT_COMPUTED
    assert speci["flag_columns"] == ["layout_snapshots:metar_report_type"]
    assert "no attribution method is pinned" in speci["reason"]


def test_one_disclosure_per_look(tmp_path, monkeypatch):
    args, _ = _looked(tmp_path, monkeypatch)
    _disclose(args)
    with pytest.raises(fd.DisclosureRefused, match="one disclosure"):
        _disclose(args)


def test_a_void_look_is_not_disclosed(tmp_path, monkeypatch):
    args, _ = _looked(tmp_path, monkeypatch, mg2_look={"pre_look_reads": ["price 2026-11-01"]})
    with pytest.raises(fd.DisclosureRefused, match="only a scored look"):
        _disclose(args)
    assert _nothing_written(args)


def test_inputs_other_than_bs_refuse(tmp_path, monkeypatch):
    args, _ = _looked(tmp_path, monkeypatch)
    frame = pd.read_parquet(args["vectors"])
    frame["p"] = frame["p"] * 0.999
    other = tmp_path / "other_vectors.parquet"
    frame.to_parquet(other, index=False)
    with pytest.raises(fd.DisclosureRefused, match="vectors_sha256"):
        _disclose(args, vectors=other)
    assert _nothing_written(args)


def test_an_altered_transfer_file_refuses(tmp_path, monkeypatch):
    args, _ = _looked(tmp_path, monkeypatch)
    labels = Path(args["transfer"]) / "labels.parquet"
    frame = pd.read_parquet(labels)
    frame["winner"] = (frame["winner"] + 1) % 3
    frame.to_parquet(labels, index=False)
    with pytest.raises(fd.DisclosureRefused, match="altered"):
        _disclose(args)
    assert _nothing_written(args)


def test_a_table_that_does_not_reproduce_b_refuses(tmp_path, monkeypatch):
    args, _ = _looked(tmp_path, monkeypatch)
    real = b.arm

    def shifted(table, frame):
        p, covered, reasons = real(table, frame)
        return p * 0.98 + 0.02 / 3, covered, reasons

    monkeypatch.setattr(b, "arm", shifted)
    with pytest.raises(fd.DisclosureRefused, match="does not reproduce B"):
        _disclose(args)
    assert _nothing_written(args)


def test_row_problems_name_each_mismatch():
    printed = {"n_snapshots": 4, "n_market_days": 2, "n_dates": 2, "brier_arm": 0.1, "brier_market": 0.2,
               "delta": {"estimate": -0.1, "ci95": [-0.2, 0.0]}}
    assert fd.row_problems(json.loads(json.dumps(printed)), printed) == []
    bad = json.loads(json.dumps(printed))
    bad["n_dates"] = 3
    bad["delta"]["ci95"] = [-0.2, 0.01]
    problems = fd.row_problems(bad, printed)
    assert any("n_dates" in p for p in problems) and any("ci95" in p for p in problems)
    assert fd.row_problems(None, printed)


def test_cli_refusal_exits_2(tmp_path, monkeypatch, capsys):
    args = _look_inputs(tmp_path, monkeypatch)
    code = fd.main(["--look-out", str(args["out"]), "--layout", str(args["layout_root"]),
                    "--vectors", str(args["vectors"]), "--transfer", str(args["transfer"]),
                    "--drop-list", str(args["drop_list"])])
    assert code == 2 and "refused" in capsys.readouterr().err


def test_schemas_are_registered_in_a_family():
    from weather.schema_families import schema_version

    assert schema_version("b_floor_disclosure") == fd.SCHEMA
    assert schema_version("b_floor_disclosure_receipt") == fd.RECEIPT_SCHEMA


def test_module_edits_nothing_b_bound_and_imports_read_only():
    tree = ast.parse(Path(fd.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    weather = sorted(n for n in imported if n.startswith("weather"))
    assert weather == ["weather.calibration.b_look_per_date", "weather.calibration.b_scorer",
                       "weather.calibration.mg2_composite", "weather.reporting.scorecards.dev_scorecard_data"]
    assigned = [t for node in ast.walk(tree) if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id in ("b", "mg2", "pdx")]
    assert not assigned  # never monkeypatches or rebinds anything in B, MG-2 or the extractor
    source = Path(fd.__file__).read_text(encoding="utf-8")
    assert "replay_inputs" not in source and "metar_history" not in source  # never opens MG-2's bundle or METAR
