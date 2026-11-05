"""A look's --market file: the host price tool and the host concat (master rulings 2026-11-03 on --market).

Guards: master rulings 2026-11-03 on --market (host price tool and host concat):

- the tool (tools/research/capture_price_export.py) reads only in-cut snapshots_long rows through the unchanged
  exporter's reader, passes every price through R19's ``capture_price``, flags a finite price outside [0, 1]
  without writing it, writes create-only per-date files with the SHA256SUMS last, and its receipt carries counts,
  shas and booleans only;
- from B's D0 the per-snapshot counts must equal the R19 sidecar (else the date refuses); before it the receipt
  discloses ``none_before_r19`` and its own counts, with no refusal (ruling 5);
- it runs only after ``--through`` is final, only on the capture host, and never writes into an export channel,
  the capture tree or a share (ruling 2);
- the concat (weather.calibration.mg1_market) joins each layout band on (row_key, kind, low, high), the keys of
  ``mg2_inputs.band_vector``, refuses unmatched and duplicate bands, holds (exit 4) on an out-of-range price, and
  writes market.parquet plus a manifest whose range_ok and duplicate_free mg1_look's pre-stamp check reads;
- both docstrings carry the look-path embargo.

Synthetic fixtures only (R19's fake capture host); no data/, no real price is read.
"""
import ast
import csv
import io
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from tests.calibration.test_b_price_coverage import BAD, D, NOW, PRICE, _local, _rows, make_coverage_host
from tests.calibration.test_mg2_input_export import LONG_HOST
from tests.host_guard import import_or_skip_on_capture_host
from tools.research import b_price_coverage as bpc
from tools.research import capture_price_export as cpe
from weather.calibration import mg1_market as mm
from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import mg2_input_export as mx
from weather.schema_families import schema_version
from weather.schema_registry_families import load_families

ROOT = Path(__file__).resolve().parents[2]
GOOD = {k: v for k, v in BAD.items() if v[1] not in ("-0.1", "1.2")}  # no finite out-of-range price
HOURS = (7, 9, 12, 16)


@pytest.fixture(autouse=True)
def _on_capture_host(monkeypatch):
    monkeypatch.setattr(cpe, "_host_identity", lambda: ("h" * 64, "h" * 64))
    monkeypatch.setattr(mm, "_host_identity", lambda: ("h" * 64, "h" * 64))


def _host(tmp_path, bad=GOOD, sidecar=True):
    data = make_coverage_host(tmp_path, bad)
    exports = tmp_path / "exports"
    mx.export(day=D, data_root=data, out=exports, now=NOW)
    if sidecar:
        bpc.count_date(day=D, data_root=data, out=exports, now=NOW)
    return data, exports


def _export(tmp_path, data, exports, **kw):
    args = {"look_id": "mg1", "day": D, "through": D, "data_root": data, "out": tmp_path / "prices",
            "coverage_root": exports, "now": NOW}
    args.update(kw)
    return cpe.export_date(**args)


def _source_rows(data, market):
    path = data / "snapshots" / allow.slug_for(market, D) / cpe.SNAPSHOTS_LONG
    by = defaultdict(list)
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        by[row["snapshot_id"]].append(row)
    return by


def _layout(tmp_path, data, hours=HOURS, name="layout"):
    """The label-free layout as the builder keys it: row_key and band_index from ``mg2_inputs.band_vector``."""
    mi = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")
    snaps, bands, expected = [], [], {}
    for market in allow.MARKETS:
        by = _source_rows(data, market)
        for hour in hours:
            sid = _local(market, D, hour).strftime("%Y%m%dT%H%M%S%z")
            key = f"{market}|{sid}"
            snaps.append({"row_key": key, "date": D.isoformat(), "market": market})
            for i, (_, kind, lo, hi, row) in enumerate(mi.band_vector(by[sid])):
                bands.append({"row_key": key, "band_index": i, "kind": kind, "low": lo, "high": hi,
                              "p_served": 0.1})
                expected[(key, i)] = bpc.capture_price(row["market_yes"])
    root = tmp_path / name
    root.mkdir()
    pd.DataFrame(snaps).to_parquet(root / mm.LAYOUT_SNAPSHOTS, index=False)
    pd.DataFrame(bands).to_parquet(root / mm.LAYOUT_BANDS, index=False)
    return root, expected


def _leaves(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, f"{path}/{k}")
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v, path)
    else:
        yield path, value


def _rewrite(prices, day, rows=None, receipt=None):
    """Replace one date's CSV rows or receipt fields and re-publish its SHA256SUMS (a consistent tamper)."""
    csv_name, receipt_name, sums_name = cpe.file_names(day)
    if rows is not None:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(cpe.PRICES_COLUMNS)
        writer.writerows(rows)
        (prices / csv_name).write_bytes(buffer.getvalue().encode("utf-8"))
    if receipt is not None:
        body = json.loads((prices / receipt_name).read_text(encoding="utf-8"))
        body.update(receipt)
        (prices / receipt_name).write_text(json.dumps(body), encoding="utf-8")
    sums = "".join(f"{cpe._sha((prices / n).read_bytes())}  {n}\n" for n in (csv_name, receipt_name))
    (prices / sums_name).write_text(sums, encoding="ascii")


def _csv_rows(prices, day=D):
    rows = list(csv.reader(io.StringIO((prices / cpe.file_names(day)[0]).read_text(encoding="utf-8"))))
    return rows[1:]


# ----------------------------------------------------------------------------- the host price tool


def test_the_tool_writes_counts_only_receipts_and_matches_r19(tmp_path):
    data, exports = _host(tmp_path)
    receipt = _export(tmp_path, data, exports)
    prices = tmp_path / "prices"
    csv_name, receipt_name, sums_name = cpe.file_names(D)
    assert sorted(p.name for p in prices.iterdir()) == sorted([csv_name, receipt_name, sums_name])
    text = (prices / receipt_name).read_text(encoding="utf-8")
    assert json.loads(text) == receipt and PRICE not in text and "market_yes" not in text
    for path, value in _leaves(receipt):
        assert not isinstance(value, float), path  # counts, shas, strings and booleans only
    assert receipt["schema"] == cpe.SCHEMA == schema_version("capture_price_export_receipt")
    assert receipt["cross_check"]["kind"] == "r19_sidecar" and receipt["cross_check"]["match"] is True
    assert receipt["out_of_range_rows"] == 0 and receipt["counts_only"] is True
    sums = (prices / sums_name).read_text(encoding="ascii")
    assert sums == (f"{cpe._sha((prices / csv_name).read_bytes())}  {csv_name}\n"
                    f"{cpe._sha((prices / receipt_name).read_bytes())}  {receipt_name}\n")
    for market, counts in receipt["counts"].items():
        assert counts["present"] and counts["snapshots"] == 8 and counts["rows_after_cut_or_untimed"] == 7
    rows = _csv_rows(prices)
    assert all(r[0].split("|", 1)[0] in allow.MARKETS for r in rows) and {r[5] for r in rows} == {"0"}
    assert {r[4] for r in rows} <= {"", repr(float(PRICE)), "0.0", "1.0"}


def test_a_finite_out_of_range_price_is_flagged_never_written(tmp_path):
    data, exports = _host(tmp_path, bad=BAD)
    receipt = _export(tmp_path, data, exports)
    assert receipt["out_of_range_rows"] == 2 and receipt["cross_check"]["match"] is True  # R19 counts it unpriced
    flagged = [r for r in _csv_rows(tmp_path / "prices") if r[5] == "1"]
    assert len(flagged) == 2 and all(r[4] == "" for r in flagged)
    assert {r[0].split("|")[0] for r in flagged} == {"chicago", "dallas"}


def test_before_r19_the_own_counts_are_disclosed_and_nothing_refuses(tmp_path, monkeypatch):
    data, exports = _host(tmp_path, sidecar=False)
    monkeypatch.setattr(bpc, "FIRST_DATE", D + timedelta(days=1))  # D now precedes B's D0: no sidecar exists
    receipt = _export(tmp_path, data, exports)
    assert receipt["cross_check"]["kind"] == "none_before_r19" and receipt["cross_check"]["match"] is None
    assert "disclosed" in receipt["cross_check"]["note"]
    assert all(c["snapshots"] == 8 for c in receipt["counts"].values())


@pytest.mark.parametrize("case,match", [
    ("no_sidecar", "no published R19 counts sidecar"),
    ("source_changed", "differ from the R19 sidecar in \\['nyc'\\]"),
    ("not_final", "has not ended in every market"),
    ("after_through", "is after --through"),
    ("exports_out", "inside .*exports"),
    ("snapshots_out", "inside .*snapshots"),
    ("unc_out", "UNC \\(share\\) path"),
    ("relative_out", "is not absolute"),
    ("look", "is not one of"),
    ("again", "already has files"),
])
def test_the_tool_refuses_and_writes_nothing(tmp_path, case, match):
    data, exports = _host(tmp_path, sidecar=case != "no_sidecar")
    kw = {"not_final": {"now": allow.export_cut_utc(D)}, "after_through": {"through": D - timedelta(days=1)},
          "exports_out": {"out": data / "exports" / "prices"}, "snapshots_out": {"out": data / "snapshots" / "p"},
          "unc_out": {"out": "\\\\host\\xfer\\prices"}, "relative_out": {"out": "prices"},
          "look": {"look_id": "t1"}}.get(case, {})
    if case == "source_changed":
        path = data / "snapshots" / allow.slug_for("nyc", D) / cpe.SNAPSHOTS_LONG
        extra = _rows("nyc", _local("nyc", D, 13), [PRICE] * 7)
        with open(path, "a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=list(LONG_HOST), lineterminator="\n").writerows(extra)
        quiet = datetime.now().timestamp() - 2 * 3600
        os.utime(path, (quiet, quiet))
    if case == "again":
        _export(tmp_path, data, exports)
        before = sorted(p.name for p in (tmp_path / "prices").iterdir())
    with pytest.raises(cpe.PriceExportRefused, match=match):
        _export(tmp_path, data, exports, **kw)
    if case == "again":
        assert sorted(p.name for p in (tmp_path / "prices").iterdir()) == before
    else:
        assert not (tmp_path / "prices").exists()


def test_the_tool_refuses_off_the_capture_host(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cpe, "_host_identity", lambda: ("w" * 64, "h" * 64))
    argv = ["--look", "mg1", "--data-root", str(tmp_path), "--out", str(tmp_path / "p"), "--from", D.isoformat(),
            "--through", D.isoformat()]
    assert cpe.main(argv) == cpe.EXIT_REFUSED
    assert "only on the dedicated capture host" in capsys.readouterr().out
    monkeypatch.setattr(cpe, "_host_identity", lambda: (_ for _ in ()).throw(OSError("no assignment")))
    assert cpe.main(argv) == cpe.EXIT_REFUSED
    assert "not provable" in capsys.readouterr().out


def test_the_tool_cli_prints_counts_only(tmp_path, monkeypatch, capsys):
    data, exports = _host(tmp_path)
    monkeypatch.setattr(cpe, "datetime", type("Clock", (datetime,), {"now": classmethod(lambda cls, tz=None: NOW)}))
    argv = ["--look", "b", "--data-root", str(data), "--out", str(tmp_path / "prices"), "--from", D.isoformat(),
            "--through", D.isoformat(), "--coverage-root", str(exports)]
    assert cpe.main(argv) == 0
    out = capsys.readouterr().out
    assert PRICE not in out and json.loads(out)["status"] == "written" and json.loads(out)["cross_check"] == "r19_sidecar"


# ----------------------------------------------------------------------------- the host concat


def _built(tmp_path, bad=GOOD, look_id="mg1"):
    data, exports = _host(tmp_path, bad=bad)
    _export(tmp_path, data, exports, look_id=look_id)
    layout, expected = _layout(tmp_path, data)
    return data, layout, expected


def test_the_concat_keys_every_band_as_the_builder_does(tmp_path):
    _, layout, expected = _built(tmp_path)
    path, manifest = mm.build(look_id="mg1", layout=layout, prices=tmp_path / "prices", out=tmp_path / "market")
    frame = pd.read_parquet(path)
    assert list(frame.columns) == list(mm.MARKET_COLUMNS) and str(frame.band_index.dtype) == "int64"
    got = {(r.row_key, int(r.band_index)): r.p_market_yes for r in frame.itertuples(index=False)}
    assert set(got) == set(expected)
    for key, want in expected.items():
        assert (math.isnan(got[key]) if want is None else got[key] == want), key
    assert any(math.isnan(v) for v in got.values()) and any(v == float(PRICE) for v in got.values())
    on_disk = json.loads((path.parent / mm.MANIFEST).read_text(encoding="utf-8"))
    assert on_disk == manifest and manifest["schema"] == mm.SCHEMA == schema_version("mg1_market_manifest")
    assert manifest["market_sha256"] == mm.sha256_file(path) and manifest["look_id"] == "mg1"
    assert manifest["range_ok"] is True and manifest["duplicate_free"] is True
    assert manifest["layout"]["bands_sha256"] == mm.sha256_file(layout / mm.LAYOUT_BANDS)
    assert manifest["counts"]["bands"] == len(expected) and manifest["counts"]["snapshots"] == 11 * len(HOURS)
    assert manifest["counts"]["price_rows_not_in_layout"] > 0  # D-1 evening, 06, 10 (bad bands), 17 local
    assert manifest["dates"][D.isoformat()]["cross_check"]["kind"] == "r19_sidecar"
    text = (path.parent / mm.MANIFEST).read_text(encoding="utf-8")
    assert PRICE not in text
    for leaf, value in _leaves(manifest):
        assert not isinstance(value, float), leaf


def test_an_out_of_range_price_holds_and_writes_nothing(tmp_path, capsys):
    _, layout, _ = _built(tmp_path, bad=BAD)
    with pytest.raises(mm.MarketHeld, match="held: 2 matched capture-time prices"):
        mm.build(look_id="mg1", layout=layout, prices=tmp_path / "prices", out=tmp_path / "market")
    assert not (tmp_path / "market").exists()
    argv = ["build", "--look", "mg1", "--layout", str(layout), "--prices", str(tmp_path / "prices"), "--out",
            str(tmp_path / "market")]
    assert mm.main(argv) == mm.EXIT_HELD == 4
    assert capsys.readouterr().err.startswith("held: ")


@pytest.mark.parametrize("case,match", [
    ("unmatched", "1 layout bands have no price row"),
    ("duplicate", "1 layout bands have more than one price row"),
    ("bad_value", "held: 1 matched"),
    ("tampered", "differs from"),
    ("other_look", "is not the capture_price_export/1 receipt of look 'mg1'"),
    ("no_date", "has no published price files"),
    ("out_exists", "already exists"),
    ("unc_out", "UNC \\(share\\) path"),
    ("off_host", "only on the dedicated capture host"),
])
def test_the_concat_refuses_before_writing(tmp_path, monkeypatch, case, match):
    _, layout, _ = _built(tmp_path)
    prices, out = tmp_path / "prices", tmp_path / "market"
    rows = _csv_rows(prices)
    keys = set(pd.read_parquet(layout / mm.LAYOUT_BANDS).row_key)
    i = next(n for n, r in enumerate(rows) if r[0] in keys)  # a row of a layout band
    if case == "unmatched":
        _rewrite(prices, D, rows=rows[:i] + rows[i + 1:])
    elif case == "duplicate":
        _rewrite(prices, D, rows=rows + [rows[i]])
    elif case == "bad_value":
        _rewrite(prices, D, rows=rows[:i] + [rows[i][:4] + ["1.5", "0"]] + rows[i + 1:])
    elif case == "tampered":
        (prices / cpe.file_names(D)[0]).write_text("row_key\n", encoding="utf-8")
    elif case == "other_look":
        _rewrite(prices, D, receipt={"look_id": "b"})
    elif case == "no_date":
        (prices / cpe.file_names(D)[2]).unlink()
    elif case == "out_exists":
        out.mkdir()
    elif case == "unc_out":
        out = "\\\\host\\xfer\\market"
    elif case == "off_host":
        monkeypatch.setattr(mm, "_host_identity", lambda: ("w" * 64, "h" * 64))
    expected = mm.MarketHeld if case == "bad_value" else mm.MarketRefused
    with pytest.raises(expected, match=match):
        mm.build(look_id="mg1", layout=layout, prices=prices, out=out)
    if case != "out_exists":
        assert not (tmp_path / "market").exists()
    else:
        assert list(out.iterdir()) == []


# ----------------------------------------------------------------------------- contracts


def test_the_concat_copies_the_tools_file_contract():
    assert (mm.PRICES_SCHEMA, mm.PRICES_SUFFIX, mm.RECEIPT_SUFFIX, mm.SUMS_SUFFIX, mm.PRICES_COLUMNS) == (
        cpe.SCHEMA, cpe.PRICES_SUFFIX, cpe.RECEIPT_SUFFIX, cpe.SUMS_SUFFIX, cpe.PRICES_COLUMNS)
    assert mm.LOOK_IDS == cpe.LOOK_IDS == ("mg1", "b")
    # mg1_look's pre-stamp check names these (Build A, claude/mg1-look-holds-checkkeys-20261103); a pin of the
    # two modules' constants lands with the combined head.
    assert (mm.MANIFEST, mm.SCHEMA, mm.MARKET_COLUMNS) == (
        "mg1_market_manifest.json", "mg1_market/1", ("row_key", "band_index", "p_market_yes"))


def test_both_docstrings_carry_the_look_path_embargo():
    for module in (cpe, mm):
        doc = " ".join(module.__doc__.split())
        for phrase in ("REGISTERED STEP OF THE LOOK PATH", "look morning, after the 45th date's finality",
                       "under master's lease, in the same session as the look, ON THE CAPTURE HOST",
                       "before the look receipt", "counts, shas and booleans only",
                       "No agent or human views a price value", "the look is HELD"):
            assert phrase in doc, (module.__name__, phrase)


def _imports(path):
    found = set()
    for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found |= {f"{node.module}.{a.name}" for a in node.names}
    return found


def test_import_contracts():
    tool = {m for m in _imports(cpe.__file__) if m.startswith(("weather", "tools"))}
    assert tool == {"tools.research.b_price_coverage", "weather.paths", "weather.calibration.mg2_input_allowlist",
                    "weather.calibration.mg2_input_export", "weather.execution_host.current_execution_host_id",
                    "weather.execution_host.load_execution_host_assignment"}
    concat = {m for m in _imports(mm.__file__) if m.startswith(("weather", "tools"))}
    assert concat == {"weather.paths", "weather.execution_host.current_execution_host_id",
                      "weather.execution_host.load_execution_host_assignment"}
    users = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")
             if any(name.startswith("tools") for name in _imports(p))]
    assert users == []  # nothing under src imports the host tool (or anything under tools)


def test_the_schemas_are_registered_in_their_family():
    registry = load_families()
    assert registry.errors == ()
    for name in ("capture_price_export_receipt", "mg1_market_manifest"):
        assert registry.family_of(name) == "capture_prices"
