"""Rule B-1's one outcome transfer writer (binding plan sections 9.6 and 9.7), on synthetic data only.

Guards: the written ``b_transfer/1`` manifest and files pass the scorer's own ``read_manifest``,
``manifest_problems`` and ``transfer_files`` (constants copied from ``b_scorer`` and pinned equal here); the
dates are the input-countable dates from D0 in order through the 45th promotion-countable date (none skipped,
none after); labels travel only after MG-1's look (``transferred_at_utc`` after the receipt's
``looked_at_utc``, the receipt bound by sha256), after the MG-1 window closed and after the 45th date ended in
every market; every refusal writes nothing; the target is never the daily input inbox.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host
from weather.calibration import b_transfer as t

D0 = date(2026, 10, 15)
MARKETS = sorted(t.MARKET_TZ)
LOOKED = datetime(2027, 1, 10, 12, 0, tzinfo=timezone.utc)
NOW = datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc)
# Input-countable dates: 55 calendar dates from D0 minus three refused bundles; three are not
# promotion-countable. The 45th countable date is therefore D0 + 50 days.
MISSING = {D0 + timedelta(days=k) for k in (4, 20, 33)}
NOT_PROMOTION = {D0 + timedelta(days=k) for k in (2, 11, 40)}
INPUT_DATES = [D0 - timedelta(days=2), D0 - timedelta(days=1)] + [
    D0 + timedelta(days=k) for k in range(55) if D0 + timedelta(days=k) not in MISSING]


def _labels(dates=INPUT_DATES):
    rows = []
    for d in dates:
        for m in MARKETS:
            for s in range(2):
                countable = d not in NOT_PROMOTION
                rows.append({"row_key": f"{m}|{d.isoformat()}-{s}", "date": d.isoformat(), "market": m,
                             "winner": 3 if countable else None, "promotion_countable": countable,
                             "settlement_bucket": "70-71", "label_source": "synthetic"})
    return pd.DataFrame(rows)


def _market(labels):
    rows = [{"row_key": rk, "band_index": i, "p_market_yes": 0.1} for rk in labels.row_key for i in range(4)]
    rows.append({"row_key": "nyc|stray", "band_index": 0, "p_market_yes": 0.5})  # no label: never travels
    return pd.DataFrame(rows)


@pytest.fixture()
def env(tmp_path):
    labels = _labels()
    lab, mkt = tmp_path / "export_labels.parquet", tmp_path / "export_market.parquet"
    labels.to_parquet(lab, index=False)
    _market(labels).to_parquet(mkt, index=False)
    window = tmp_path / "window.json"
    window.write_text(json.dumps({"schema": t.WINDOW_SCHEMA, "dates": [d.isoformat() for d in INPUT_DATES]}),
                      encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": "mg1_look_receipt/1", t.MG1_RECEIPT_TIME: LOOKED.isoformat()}),
                       encoding="utf-8")
    kw = dict(labels=lab, market=mkt, input_window=window, d0=D0.isoformat(), mg1_look_receipt=receipt,
              out=tmp_path / "transfer", now=NOW)
    return tmp_path, kw


def _countable_dates():
    days = [d for d in INPUT_DATES if d >= D0 and d not in NOT_PROMOTION]
    return [d.isoformat() for d in days[:t.N_DATES]]


def test_the_constants_equal_the_scorers():
    b = import_or_skip_on_capture_host("weather.calibration.b_scorer")
    inputs = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")
    assert (t.TRANSFER_SCHEMA, t.TRANSFER_MANIFEST, t.TRANSFER_FILES, t.N_DATES, t.MG1_RECEIPT_TIME) == (
        b.TRANSFER_SCHEMA, b.TRANSFER_MANIFEST, b.TRANSFER_FILES, b.N_DATES, b.MG1_RECEIPT_TIME)
    assert t.WINDOW_SCHEMA == inputs.WINDOW_SCHEMA
    assert {m: t.MARKET_TZ[m] for m in b.MARKET_TZ} == b.MARKET_TZ and set(t.MARKET_TZ) - set(b.MARKET_TZ) == {"denver"}
    for day in ("2026-11-28", "2026-12-05", "2027-03-14"):
        assert t.embargo_end(day) >= b.embargo_end(day)


def test_the_written_transfer_passes_the_scorers_manifest_checks(env):
    b = import_or_skip_on_capture_host("weather.calibration.b_scorer")
    tmp, kw = env
    result = t.write(**kw)
    out = kw["out"]
    manifest, rows = b.read_manifest(out)
    assert manifest is not None, rows
    assert b.manifest_problems(manifest, rows, _countable_dates(), D0) == []
    frames, problems = b.transfer_files(out, manifest)
    assert problems == []
    labels, market = frames["labels.parquet"], frames["market.parquet"]
    assert sorted(set(labels.date.astype(str))) == sorted(d.isoformat() for d, _ in rows)
    assert set(market.row_key) <= set(labels.row_key) and "nyc|stray" not in set(market.row_key)
    assert manifest["mg1_look_receipt_sha256"] == b.sha256_file(kw["mg1_look_receipt"])
    assert b._utc(manifest["transferred_at_utc"]) > LOOKED
    assert result["countable"] == t.N_DATES and sorted(p.name for p in out.iterdir()) == sorted(
        t.TRANSFER_FILES + (t.TRANSFER_MANIFEST,))


def test_dates_run_from_d0_in_order_through_the_45th_countable_date(env):
    tmp, kw = env
    t.write(**kw)
    manifest = json.loads((kw["out"] / t.TRANSFER_MANIFEST).read_text(encoding="utf-8"))
    days = [r["date"] for r in manifest["dates"]]
    assert days[0] == D0.isoformat() and days[-1] == (D0 + timedelta(days=50)).isoformat()
    assert days == sorted(days) and not {d.isoformat() for d in MISSING} & set(days)
    assert [r["date"] for r in manifest["dates"] if not r["promotion_countable"]] == sorted(
        d.isoformat() for d in NOT_PROMOTION)
    assert sum(r["promotion_countable"] for r in manifest["dates"]) == t.N_DATES
    labels = pd.read_parquet(kw["out"] / "labels.parquet")
    assert list(labels.columns) == list(t.LABEL_COLUMNS) + list(t.OPTIONAL_LABEL_COLUMNS)
    assert labels.date.min() == D0.isoformat()


def test_a_second_write_is_refused_and_leaves_the_first(env):
    tmp, kw = env
    t.write(**kw)
    before = (kw["out"] / t.TRANSFER_MANIFEST).read_bytes()
    with pytest.raises(t.TransferRefused, match="new or empty"):
        t.write(**kw)
    assert (kw["out"] / t.TRANSFER_MANIFEST).read_bytes() == before


def _edit_labels(kw, fn):
    frame = fn(pd.read_parquet(kw["labels"]))
    frame.to_parquet(kw["labels"], index=False)


REFUSALS = {
    "receipt missing": (lambda tmp, kw: kw.update(mg1_look_receipt=tmp / "nope.json"), "does not exist"),
    "before the MG-1 look": (lambda tmp, kw: kw.update(now=LOOKED), "not after the MG-1 look"),
    "MG-1 window open": (lambda tmp, kw: kw.update(now=datetime(2026, 11, 28, 23, tzinfo=timezone.utc)),
                         "has not closed"),
    "embargo": (lambda tmp, kw: (kw["mg1_look_receipt"].write_text(json.dumps(
        {t.MG1_RECEIPT_TIME: "2026-12-01T00:00:00+00:00"})), kw.update(now=datetime(2026, 12, 5, 6, tzinfo=timezone.utc))),
                "embargo"),
    "inbox target": (lambda tmp, kw: kw.update(out=tmp / "inbox" / "mg2-inputs" / "transfer"), "input inbox"),
    "out not empty": (lambda tmp, kw: (kw["out"].mkdir(), (kw["out"] / "x").write_text("x")), "new or empty"),
    "window schema": (lambda tmp, kw: kw["input_window"].write_text(json.dumps({"schema": "other", "dates": []})),
                      "input window schema"),
    "export misses a date": (lambda tmp, kw: _edit_labels(kw, lambda f: f[f.date != (D0 + timedelta(days=7))
                                                                         .isoformat()]), "does not cover"),
    "too few countable": (lambda tmp, kw: kw["input_window"].write_text(json.dumps(
        {"schema": t.WINDOW_SCHEMA, "dates": [d.isoformat() for d in INPUT_DATES[:30]]})), "only"),
    "flag varies in a date": (lambda tmp, kw: _edit_labels(kw, lambda f: f.assign(promotion_countable=[
        (False if i == 60 else v) for i, v in enumerate(f.promotion_countable)])), "varies"),
    "no winner": (lambda tmp, kw: _edit_labels(kw, lambda f: f.assign(winner=[
        (None if i == 50 else v) for i, v in enumerate(f.winner)])), "no winner"),
    "label columns": (lambda tmp, kw: _edit_labels(kw, lambda f: f.drop(columns=["winner"])), "lacks columns"),
    "duplicate price": (lambda tmp, kw: pd.concat([pd.read_parquet(kw["market"])] * 2).to_parquet(
        kw["market"], index=False), "duplicate"),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_every_refusal_writes_nothing(env, case):
    tmp, kw = env
    edit, match = REFUSALS[case]
    edit(tmp, kw)
    out = Path(kw["out"])
    before = sorted(p.name for p in out.iterdir()) if out.is_dir() else None
    with pytest.raises(t.TransferRefused, match=match):
        t.write(**kw)
    after = sorted(p.name for p in out.iterdir()) if out.is_dir() else None
    assert after == before and not (out / t.TRANSFER_MANIFEST).exists()


def test_the_cli_reports_a_refusal_with_exit_2(env, capsys):
    tmp, kw = env
    argv = ["write", "--labels", str(kw["labels"]), "--market", str(kw["market"]), "--input-window",
            str(kw["input_window"]), "--d0", kw["d0"], "--mg1-look-receipt", str(tmp / "nope.json"),
            "--out", str(kw["out"])]
    assert t.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"


def test_import_refuses_from_a_production_package():
    saved = sys.modules.pop("weather.calibration.b_transfer")
    try:
        with pytest.raises(ImportError, match="research-only"):
            exec("import weather.calibration.b_transfer", {"__name__": "weather.serving.anything"})
    finally:
        sys.modules["weather.calibration.b_transfer"] = saved


def test_the_writer_imports_neither_the_scorer_nor_mg2_composite():
    source = Path(t.__file__).read_text(encoding="utf-8")
    assert "import b_scorer" not in source and "mg2_composite import" not in source
    assert "from weather.calibration import" not in source
