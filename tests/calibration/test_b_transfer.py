"""Rule B-1's one outcome transfer writer (binding plan 9.6/9.7; master T1-T5 2026-11-03; R19; R24), synthetic only.

Guards: the written ``b_transfer/1`` manifest and files pass the scorer's own ``read_manifest``,
``manifest_problems`` and ``transfer_files`` (constants copied from ``b_scorer`` and pinned equal here); the
dates are the input-countable dates from D0 in order through B's 45th countable date; T1: a date counts iff all
10 B market-days are promotion_countable in the ledger's latest revision (Denver ignored), the ledger sha is
recorded (T5); T2: a reader refusal or a missing label row makes the date non-countable and moves the 45th date
later; T3: a B layout snapshot on a countable date without a label refuses; T4: prices only through
``capture_price``, a finite price outside [0, 1] refuses, counts must equal the R19 sidecar; R24 (3): labels only
from the frozen copy, only inside the registered entry point, ``read_through`` = the date; every refusal writes
nothing; the target is never the daily input inbox. Every fixture is synthetic (tmp_path).
"""
import hashlib
import json
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host
from weather.backtesting import venue_label_reader as vr
from weather.backtesting.venue_rule_labels import VENUE_RULE_CUTOVER_DATE, VENUE_RULE_VERSION
from weather.calibration import b_transfer as t

D0 = date(2026, 10, 29)
ALL11 = sorted(t.MARKET_TZ)
LOOKED = datetime(2027, 1, 10, 12, 0, tzinfo=timezone.utc)
NOW = datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc)
FROZEN_AT = datetime(2027, 1, 11, 12, 0, tzinfo=timezone.utc)
# 58 calendar dates from D0 minus three refused bundles; three dates have one B market-day not countable, so the
# 45th countable date is D0 + 50 days.
MISSING = {D0 + timedelta(days=k) for k in (4, 20, 33)}
NOT_PROMOTION = {D0 + timedelta(days=k) for k in (2, 11, 40)}
INPUT_DATES = [D0 - timedelta(days=2), D0 - timedelta(days=1)] + [
    D0 + timedelta(days=k) for k in range(58) if D0 + timedelta(days=k) not in MISSING]
BANDS = [("lte", 60, 60), ("eq", 61, 62), ("eq", 63, 64), ("gte", 65, 65)]
BUCKET, WINNER = 63, 2
SCHEMAS = {t.FREEZE_RECEIPT_NAME: "venue_label_freeze_receipt_v1", t.SIDECAR_NAME: "synthetic_sidecar/1"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _row_key(m, d, s):
    return f"{m}|{d.isoformat()}-{s}"


def _write_window(root, dates=INPUT_DATES, bands=BANDS):
    root.mkdir(parents=True, exist_ok=True)
    snaps, band_rows = [], []
    for d in dates:
        for m in ALL11:
            for s in range(2):
                rk = _row_key(m, d, s)
                snaps.append({"row_key": rk, "snapshot_id": f"{d.isoformat()}-{s}", "market": m,
                              "date": d.isoformat(), "local_hour": 9 + s, "p_served": 0.25})
                band_rows += [{"row_key": rk, "band_index": i, "kind": k, "low": float(lo), "high": float(hi),
                               "p_served": 0.25, "date": d.isoformat(), "market": m}
                              for i, (k, lo, hi) in enumerate(bands)]
    pd.DataFrame(snaps).to_parquet(root / t.LAYOUT_FILES[0], index=False)
    pd.DataFrame(band_rows).to_parquet(root / t.LAYOUT_FILES[1], index=False)
    manifest = {"schema": t.WINDOW_SCHEMA, "dates": [d.isoformat() for d in dates],
                "files": {n: {"sha256": _sha(root / n), "rows": 0} for n in t.LAYOUT_FILES}}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root / "manifest.json"


def _ledger_row(m, d, countable, revision=1):
    return {"event_slug": f"highest-temperature-in-{m}-on-{d.isoformat()}", "market_id": m,
            "target_date": d.isoformat(), "revision_number": revision, "promotion_countable": countable}


def _write_ledger(root, extra=()):
    for m in ALL11:
        rows = [_ledger_row(m, d, not (m == "nyc" and d in NOT_PROMOTION) and m != "denver") for d in INPUT_DATES]
        rows += [r for r in extra if r["market_id"] == m]
        path = root / m / "ledger.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return root


def _label_row(d, row_count=24, bucket=BUCKET):
    return {"local_date": d.isoformat(), "max_temp_native": float(bucket), "max_temp_bucket_native": bucket,
            "label_source": "metar_routine", "label_station": "KXXX", "label_station_basis": "registry",
            "label_rule_version": VENUE_RULE_VERSION, "label_cutover_date": VENUE_RULE_CUTOVER_DATE.isoformat(),
            "row_count": row_count}


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_frozen(root, *, skip=(), rows_for=None, frozen_at=FROZEN_AT, through=INPUT_DATES[-1]):
    markets = {}
    for m in ALL11:
        rows = rows_for(m) if rows_for else [_label_row(d) for d in INPUT_DATES if (m, d) not in skip]
        csv = root / m / "daily" / "daily_summary.csv"
        _write_csv(csv, rows)
        markets[m] = {"label_csv": {"path": str(csv), "sha256": _sha(csv)}, "wu_daily_summary": {"sha256": None},
                      "label_csv_matches_manifest": True}
    receipt = {"schema_version": SCHEMAS[t.FREEZE_RECEIPT_NAME], "look_id": "b-look-synthetic",
               "through": through.isoformat(), "frozen_at_utc": frozen_at.isoformat(), "audit_status": "ok",
               "markets": markets}
    (root / t.FREEZE_RECEIPT).write_text(json.dumps(receipt), encoding="utf-8")
    return root


def _market_export(window_dir, price=0.1):
    snaps = pd.read_parquet(window_dir / t.LAYOUT_FILES[0])
    rows = [{"row_key": rk, "band_index": i, "p_market_yes": price} for rk in snaps.row_key for i in range(4)]
    rows.append({"row_key": "nyc|stray", "band_index": 0, "p_market_yes": 0.5})  # no snapshot: never travels
    return pd.DataFrame(rows)


def _write_sidecars(root, market, dates=INPUT_DATES):
    root.mkdir(parents=True, exist_ok=True)
    for d in dates:
        counts = {}
        for rk, group in market[market.row_key.str.contains(f"|{d.isoformat()}-", regex=False)].groupby("row_key"):
            m, sid = rk.split("|", 1)
            priced = sum(t.capture_price(v) is not None for v in group.p_market_yes)
            counts.setdefault(m, {})[sid] = [int(len(group)), int(priced)]
        _write_sidecar(root, d, counts)
    return root


def _write_sidecar(root, d, counts, match=True):
    body = (json.dumps({"schema": SCHEMAS[t.SIDECAR_NAME], "target_date": d.isoformat(), "counts": counts,
                        "match": match}, indent=1, sort_keys=True) + "\n").encode("utf-8")
    (root / f"{d.isoformat()}.json").write_bytes(body)
    (root / f"{d.isoformat()}{t.SIDECAR_SUMS_SUFFIX}").write_bytes(
        f"{hashlib.sha256(body).hexdigest()}  {d.isoformat()}.json\n".encode("ascii"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "_entry_running", lambda: True)
    monkeypatch.setattr(t, "_registered", lambda name: SCHEMAS[name])
    window = _write_window(tmp_path / "window")
    market = _market_export(tmp_path / "window")
    mkt = tmp_path / "export_market.parquet"
    market.to_parquet(mkt, index=False)
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": "mg1_look_receipt/1", t.MG1_RECEIPT_TIME: LOOKED.isoformat()}),
                       encoding="utf-8")
    kw = dict(market=mkt, input_window=window, ledger_root=_write_ledger(tmp_path / "settlements"),
              frozen_labels=_write_frozen(tmp_path / "frozen" / "b-look-synthetic"),
              coverage_root=_write_sidecars(tmp_path / "_b_coverage", market), d0=D0.isoformat(),
              mg1_look_receipt=receipt, out=tmp_path / "transfer", now=NOW)
    return tmp_path, kw


def _countable_dates(extra_excluded=()):
    days = [d for d in INPUT_DATES if d >= D0 and d not in NOT_PROMOTION and d not in set(extra_excluded)]
    return [d.isoformat() for d in days[:t.N_DATES]]


def _manifest(kw):
    return json.loads((Path(kw["out"]) / t.TRANSFER_MANIFEST).read_text(encoding="utf-8"))


def test_the_constants_equal_the_scorers():
    b = import_or_skip_on_capture_host("weather.calibration.b_scorer")
    inputs = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")
    assert (t.TRANSFER_SCHEMA, t.TRANSFER_MANIFEST, t.TRANSFER_FILES, t.N_DATES, t.MG1_RECEIPT_TIME) == (
        b.TRANSFER_SCHEMA, b.TRANSFER_MANIFEST, b.TRANSFER_FILES, b.N_DATES, b.MG1_RECEIPT_TIME)
    assert t.WINDOW_SCHEMA == inputs.WINDOW_SCHEMA and t.LAYOUT_FILES == inputs.LAYOUT_FILES
    assert t.B_MARKETS == tuple(sorted(b.MARKETS)) and "denver" not in t.B_MARKETS
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
    priced = b.priced_snapshots(pd.read_parquet(tmp / "window" / t.LAYOUT_FILES[1]), market)
    assert bool(priced.reindex(labels.row_key).all())


def test_dates_run_from_d0_in_order_through_the_45th_countable_date(env):
    tmp, kw = env
    t.write(**kw)
    manifest = _manifest(kw)
    days = [r["date"] for r in manifest["dates"]]
    assert days[0] == D0.isoformat() and days[-1] == (D0 + timedelta(days=50)).isoformat()
    assert days == sorted(days) and not {d.isoformat() for d in MISSING} & set(days)
    assert [r["date"] for r in manifest["dates"] if not r["promotion_countable"]] == sorted(
        d.isoformat() for d in NOT_PROMOTION)
    assert manifest["countable"]["non_countable"] == [{"date": d.isoformat(), "reason": t.NON_COUNTABLE_LEDGER}
                                                      for d in sorted(NOT_PROMOTION)]
    assert sum(r["promotion_countable"] for r in manifest["dates"]) == t.N_DATES
    labels = pd.read_parquet(kw["out"] / "labels.parquet")
    assert list(labels.columns) == list(t.LABEL_COLUMNS) + list(t.OPTIONAL_LABEL_COLUMNS)
    assert labels.date.min() == D0.isoformat() and set(labels.market) == set(t.B_MARKETS)
    counted = labels[labels.promotion_countable]
    assert (counted.winner == WINNER).all() and labels[~labels.promotion_countable].winner.isna().all()
    assert len(counted) == t.N_DATES * len(t.B_MARKETS) * 2


def test_t1_one_b_market_day_not_countable_moves_the_date_out_and_denver_is_ignored(env):
    tmp, kw = env
    t.write(**kw)
    flags = {r["date"]: r["promotion_countable"] for r in _manifest(kw)["dates"]}
    # nyc alone is not countable on NOT_PROMOTION dates; Denver is never countable in the fixture.
    assert all(not flags[d.isoformat()] for d in NOT_PROMOTION)
    assert sum(flags.values()) == t.N_DATES


def test_t5_the_latest_ledger_revision_decides_and_the_ledger_sha_is_recorded(env):
    tmp, kw = env
    up, down = D0 + timedelta(days=11), D0 + timedelta(days=5)  # up was not countable in revision 1
    extra = [_ledger_row("nyc", up, True, revision=2), _ledger_row("miami", down, False, revision=2)]
    _write_ledger(kw["ledger_root"], extra)
    t.write(**kw)
    manifest = _manifest(kw)
    flags = {r["date"]: r["promotion_countable"] for r in manifest["dates"]}
    assert flags[up.isoformat()] is True and flags[down.isoformat()] is False
    assert manifest["countable"]["ledger_sha256"] == {
        m: _sha(kw["ledger_root"] / m / "ledger.jsonl") for m in t.B_MARKETS}
    countable = [d for d, c in flags.items() if c]
    expected = [d for d in INPUT_DATES if d >= D0 and (d not in NOT_PROMOTION or d == up) and d != down]
    assert countable == [d.isoformat() for d in expected[:t.N_DATES]]


def test_t1_a_market_day_with_no_ledger_row_or_two_events_is_not_countable(env):
    tmp, kw = env
    gone, twin = D0 + timedelta(days=6), D0 + timedelta(days=8)
    path = kw["ledger_root"] / "seattle" / "ledger.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r["target_date"] != gone.isoformat()]
    rows.append({**_ledger_row("seattle", twin, True), "event_slug": "another-event"})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    t.write(**kw)
    flags = {r["date"]: r["promotion_countable"] for r in _manifest(kw)["dates"]}
    assert flags[gone.isoformat()] is False and flags[twin.isoformat()] is False
    assert sum(flags.values()) == t.N_DATES


@pytest.mark.parametrize("kind", ["missing row", "thin row"])
def test_t2_a_reader_refusal_or_missing_label_makes_the_date_non_countable_and_moves_the_45th_later(
        env, kind):
    tmp, kw = env
    hole = D0 + timedelta(days=9)
    rows_for = (lambda m: [_label_row(d, row_count=5 if (m == "austin" and d == hole) else 24)
                           for d in INPUT_DATES if not (kind == "missing row" and m == "austin" and d == hole)])
    import shutil
    shutil.rmtree(kw["frozen_labels"])
    _write_frozen(kw["frozen_labels"], rows_for=rows_for)
    t.write(**kw)
    manifest = _manifest(kw)
    flags = {r["date"]: r["promotion_countable"] for r in manifest["dates"]}
    assert flags[hole.isoformat()] is False
    assert {"date": hole.isoformat(), "reason": t.NON_COUNTABLE_LABEL} in manifest["countable"]["non_countable"]
    assert [d for d, c in flags.items() if c] == _countable_dates(extra_excluded=[hole])
    assert manifest["dates"][-1]["date"] > (D0 + timedelta(days=50)).isoformat()  # later, never earlier
    labels = pd.read_parquet(kw["out"] / "labels.parquet")
    assert labels[labels.date == hole.isoformat()].winner.isna().all()


def test_r24_labels_are_read_from_the_frozen_copy_through_each_date_only(env, monkeypatch):
    tmp, kw = env
    calls = []
    real = vr.read_venue_labels

    def spy(market_id, target_dates, **kwargs):
        calls.append((market_id, list(target_dates), kwargs))
        return real(market_id, target_dates, **kwargs)

    monkeypatch.setattr(vr, "read_venue_labels", spy)
    t.write(**kw)
    last = (D0 + timedelta(days=50))
    assert calls and {m for m, *_ in calls} == set(t.B_MARKETS)
    for market, days, kwargs in calls:
        assert days == [kwargs["read_through"]] and kwargs["read_through"] <= last
        assert kwargs["allow_reserved_window"] is True and kwargs["model_scoring"] is True
        assert Path(kwargs["venue_label_csv"]).is_relative_to(kw["frozen_labels"])
        assert Path(kwargs["label_root"]) == Path(kw["frozen_labels"])
    assert not {d for _, (d,), _ in calls} & NOT_PROMOTION  # ledger-non-countable dates are never read
    manifest = _manifest(kw)
    assert manifest["labels"]["freeze_receipt_sha256"] == _sha(kw["frozen_labels"] / t.FREEZE_RECEIPT)


def test_the_label_loader_refuses_outside_the_registered_entry_point(env, monkeypatch):
    tmp, kw = env
    monkeypatch.setattr(t, "_entry_running", lambda: False)
    with pytest.raises(t.TransferRefused, match="registered entry point"):
        t.write(**kw)
    assert not Path(kw["out"]).exists()


def test_entry_running_matches_this_module_name_and_bytes_only(monkeypatch, tmp_path):
    other = tmp_path / "b_transfer.py"
    other.write_text("# a lookalike\n", encoding="utf-8")
    for name, origin, expected in ((t.ENTRY_MODULE, t.__file__, True), (t.ENTRY_MODULE, str(other), False),
                                   ("weather.calibration.other", t.__file__, False)):
        fake = types.ModuleType("__main__")
        fake.__spec__ = types.SimpleNamespace(name=name, origin=origin)
        monkeypatch.setitem(sys.modules, "__main__", fake)
        assert t._entry_running() is expected


def test_t4_prices_go_through_capture_price_and_unpriced_rows_become_nan(env):
    tmp, kw = env
    market = pd.read_parquet(kw["market"])
    bad = market.row_key == _row_key("nyc", D0 + timedelta(days=1), 0)
    market.loc[bad, "p_market_yes"] = [float("nan"), float("inf"), None, 0.4]
    market.to_parquet(kw["market"], index=False)
    import shutil
    shutil.rmtree(kw["coverage_root"])
    _write_sidecars(kw["coverage_root"], market)
    t.write(**kw)
    out = pd.read_parquet(kw["out"] / "market.parquet")
    row = out[out.row_key == _row_key("nyc", D0 + timedelta(days=1), 0)].sort_values("band_index")
    assert row.p_market_yes.isna().tolist() == [True, True, True, False]
    finite = out.p_market_yes.dropna()
    assert finite.between(0, 1).all()
    assert _manifest(kw)["prices"]["sidecar_sha256"].keys() == {r["date"] for r in _manifest(kw)["dates"]}


def test_capture_price_matches_the_r19_predicate():
    cases = {None: None, True: None, "x": None, float("nan"): None, float("inf"): None, -0.1: None, 1.2: None,
             0: 0.0, 1: 1.0, "0.25": 0.25, 0.5: 0.5}
    for value, expected in cases.items():
        assert t.capture_price(value) == expected
    try:
        from tools.research import b_price_coverage as counts_tool
    except ImportError:
        return  # the R19 head is not on this branch; the value table above pins the predicate
    for value in list(cases) + [" 0.3 ", -0.0, 1.0000001]:
        assert t.capture_price(value) == counts_tool.capture_price(value)


def test_nothing_under_src_names_the_counts_tool():
    assert "b_price_coverage" not in Path(t.__file__).read_text(encoding="utf-8")


def _edit_market(kw, fn):
    fn(pd.read_parquet(kw["market"])).to_parquet(kw["market"], index=False)


def _sidecar_edit(kw, day, fn):
    path = kw["coverage_root"] / f"{day.isoformat()}.json"
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    fn(sidecar)
    _write_sidecar(kw["coverage_root"], day, sidecar["counts"], sidecar["match"])


def _break_bands(tmp, kw):
    """One countable date's nyc snapshot has bands that do not contain the bucket: no winner (T3)."""
    window = tmp / "window"
    bands = pd.read_parquet(window / t.LAYOUT_FILES[1])
    rk = _row_key("nyc", D0 + timedelta(days=3), 1)
    hit = (bands.row_key == rk) & (bands.band_index == WINNER)
    bands.loc[hit, ["low", "high"]] = [90.0, 91.0]
    bands.to_parquet(window / t.LAYOUT_FILES[1], index=False)
    manifest = json.loads(kw["input_window"].read_text(encoding="utf-8"))
    manifest["files"][t.LAYOUT_FILES[1]]["sha256"] = _sha(window / t.LAYOUT_FILES[1])
    kw["input_window"].write_text(json.dumps(manifest), encoding="utf-8")


def _refreeze(tmp, kw, **kwargs):
    import shutil
    shutil.rmtree(kw["frozen_labels"])
    _write_frozen(kw["frozen_labels"], **kwargs)


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
    "layout altered": (lambda tmp, kw: pd.read_parquet(tmp / "window" / t.LAYOUT_FILES[0]).head(5).to_parquet(
        tmp / "window" / t.LAYOUT_FILES[0], index=False), "does not match"),
    "too few countable": (lambda tmp, kw: kw["input_window"].write_text(json.dumps(
        {**json.loads(kw["input_window"].read_text(encoding="utf-8")),
         "dates": [d.isoformat() for d in INPUT_DATES[:30]]})), "only"),
    "ledger missing": (lambda tmp, kw: (kw["ledger_root"] / "dallas" / "ledger.jsonl").unlink(), "ledger missing"),
    "T3 no winner": (_break_bands, "T3 layout coverage"),
    "T4 out of range": (lambda tmp, kw: _edit_market(kw, lambda f: f.assign(p_market_yes=[
        (1.2 if i == 333 else v) for i, v in enumerate(f.p_market_yes)])), "outside"),
    "T4 counts differ": (lambda tmp, kw: _sidecar_edit(kw, D0 + timedelta(days=7), lambda s: s["counts"]["miami"].update(
        {f"{(D0 + timedelta(days=7)).isoformat()}-0": [4, 3]})), "T4 price counts"),
    "T4 snapshot not in sidecar": (lambda tmp, kw: _sidecar_edit(kw, D0, lambda s: s["counts"].pop("houston")),
                                   "T4 price counts"),
    "T4 sidecar unpublished": (lambda tmp, kw: (kw["coverage_root"] / f"{D0.isoformat()}.SHA256SUMS").unlink(),
                               "no published coverage sidecar"),
    "T4 sidecar sums differ": (lambda tmp, kw: (kw["coverage_root"] / f"{D0.isoformat()}.json").write_text(
        "{}", encoding="utf-8"), "does not match its SHA256SUMS"),
    "duplicate price": (lambda tmp, kw: pd.concat([pd.read_parquet(kw["market"])] * 2).to_parquet(
        kw["market"], index=False), "duplicate"),
    "market columns": (lambda tmp, kw: _edit_market(kw, lambda f: f.drop(columns=["p_market_yes"])), "lacks columns"),
    "no freeze receipt": (lambda tmp, kw: (kw["frozen_labels"] / t.FREEZE_RECEIPT).unlink(), "no R24 freeze receipt"),
    "frozen csv altered": (lambda tmp, kw: (kw["frozen_labels"] / "nyc" / "daily" / "daily_summary.csv").write_text(
        "local_date\n", encoding="utf-8"), "differs from the freeze receipt"),
    "frozen before finality": (lambda tmp, kw: _refreeze(tmp, kw, frozen_at=datetime(2026, 12, 18, tzinfo=timezone.utc)),
                               "frozen before"),
    "frozen copy ends early": (lambda tmp, kw: _refreeze(tmp, kw, through=D0 + timedelta(days=30)),
                               "frozen label copy ends"),
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
    argv = ["write", "--market", str(kw["market"]), "--input-window", str(kw["input_window"]),
            "--ledger-root", str(kw["ledger_root"]), "--frozen-labels", str(kw["frozen_labels"]),
            "--coverage-root", str(kw["coverage_root"]), "--d0", kw["d0"],
            "--mg1-look-receipt", str(tmp / "nope.json"), "--out", str(kw["out"])]
    assert t.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"


def test_import_refuses_from_a_production_package():
    saved = sys.modules.pop("weather.calibration.b_transfer")
    try:
        with pytest.raises(ImportError, match="research-only"):
            exec("import weather.calibration.b_transfer", {"__name__": "weather.serving.anything"})
    finally:
        sys.modules["weather.calibration.b_transfer"] = saved


def test_the_writer_imports_neither_the_scorer_nor_mg2_composite_nor_mg2_inputs():
    source = Path(t.__file__).read_text(encoding="utf-8")
    assert "import b_scorer" not in source and "mg2_composite import" not in source
    assert "from weather.calibration import" not in source and "import mg2_inputs" not in source
