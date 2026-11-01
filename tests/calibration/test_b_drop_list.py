"""B-1 coverage drop list (workstation side): log, verdict fixed once, materialize for the look window.

Guards: master ruling R19 (2026-11-01) and B-1 Clarification 4
(docs/research/b-coverage-2026-11-02/b1-clarification-4-coverage-counts-2026-11-02.md): a sidecar is logged only
when its bytes match its SHA256SUMS and it is integers only; a verdict is refused on an unlogged sha, a false
match flag, another bundle, a missing snapshot or n_rows != n_bands (every snapshot, Denver and every hour
included), is appended once and never recomputed; a date with no 07-16 snapshot is dropped, 0.90 is kept; the
drop list holds exactly the window's logged verdicts, so a logged date that is not promotion-countable shifts
the look set without a VOID 6 (b_scorer's own recompute agrees); the module never opens a transfer file and is
admitted on the workstation offline allowlist.
"""
import hashlib
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from weather.calibration import mg2_input_allowlist as allow

from tests.host_guard import import_or_skip_on_capture_host

b_scorer = import_or_skip_on_capture_host("weather.calibration.b_scorer")
mi = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")
bdl = import_or_skip_on_capture_host("weather.calibration.b_drop_list")

ROOT = Path(__file__).resolve().parents[2]
N_BANDS = 7
SCORED = [m for m in allow.MARKETS if m != "denver"]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan(day, unpriced=0, hours=(7, 9, 12, 16), extra=()):
    """Snapshots ``(market, hour, n_bands, priced)``: the 10 scored markets at ``hours``, the first ``unpriced``
    of them unpriced; Denver and hours 6 and 17 unpriced (never counted); plus ``extra``."""
    snaps = [(m, h, N_BANDS, True) for m in SCORED for h in hours]
    snaps = [(m, h, n, i >= unpriced) for i, (m, h, n, _p) in enumerate(snaps)]
    snaps += [("denver", h, N_BANDS, False) for h in hours] + [(m, h, N_BANDS, False) for m in SCORED for h in (6, 17)]
    return snaps + list(extra)


def _sid(day, market, hour):
    return f"{day:%Y%m%d}T{hour:02d}0700-{market}"


def make_layout(root, day, snaps, bundle_sha=None):
    """A per-date layout in the builder's file format (columns b_scorer and the drop list read)."""
    import pandas as pd

    root = Path(root)
    root.mkdir(parents=True)
    snap_rows, band_rows = [], []
    for market, hour, n_bands, _priced in snaps:
        sid = _sid(day, market, hour)
        key = f"{market}|{sid}"
        snap_rows.append({"row_key": key, "snapshot_id": sid, "market": market, "date": day.isoformat(),
                          "target_date": day.isoformat(), "local_hour": hour, "n_bands": n_bands,
                          "captured_at_utc": f"{day}T{hour:02d}:07:00+00:00"})
        band_rows += [{"row_key": key, "band_index": i, "date": day.isoformat(), "market": market}
                      for i in range(n_bands)]
    s = pd.DataFrame(snap_rows, columns=["row_key", "snapshot_id", "market", "date", "target_date", "local_hour",
                                         "n_bands", "captured_at_utc"])
    s["local_hour"] = s.local_hour.astype("int64")
    b = pd.DataFrame(band_rows, columns=["row_key", "band_index", "date", "market"])
    b["band_index"] = b.band_index.astype("int64")
    s.to_parquet(root / "inputs_snapshots.parquet", index=False)
    b.to_parquet(root / "inputs_bands.parquet", index=False)
    manifest = {"schema": mi.LAYOUT_SCHEMA, "target_date": day.isoformat(),
                "bundle_manifest_sha256": bundle_sha or hashlib.sha256(day.isoformat().encode()).hexdigest(),
                "allowlist_sha256": "a" * 64, "builder_sha256": "b" * 64,
                "parser": {"module_sha256": "c" * 64, "parser_version": 2}, "snapshots": len(s),
                "files": {n: {"sha256": _sha(root / n), "rows": r} for n, r in
                          (("inputs_snapshots.parquet", len(s)), ("inputs_bands.parquet", len(b)))}}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return root


def make_sidecar(share, day, snaps, *, match=True, bundle_sha=None, rows=None, drop=None, counts=None):
    """``<share>/_b_coverage/<D>.json`` and its SHA256SUMS, as b_price_coverage writes them."""
    if counts is None:
        counts = {m: {} for m in allow.MARKETS}
        for market, hour, n_bands, priced in snaps:
            n = rows if rows is not None and (market, hour) == drop else n_bands
            counts[market][_sid(day, market, hour)] = [n, n if priced else n - 1]
        if drop is not None and rows is None:
            del counts[drop[0]][_sid(day, *drop)]
    sidecar = {"schema": "b_price_coverage/1", "target_date": day.isoformat(), "counts_only": True,
               "counts": counts, "match": match, "module_sha256": "d" * 64,
               "bundle": {"manifest_sha256": bundle_sha or hashlib.sha256(day.isoformat().encode()).hexdigest()}}
    folder = Path(share) / "_b_coverage"
    folder.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(sidecar, indent=1, sort_keys=True) + "\n").encode("utf-8")
    (folder / f"{day}.json").write_bytes(body)
    (folder / f"{day}.SHA256SUMS").write_bytes(f"{hashlib.sha256(body).hexdigest()}  {day}.json\n".encode())
    return sidecar


@pytest.fixture
def ws(tmp_path):
    return {"share": tmp_path / "share", "store": tmp_path / "ws" / "store",
            "ledger": tmp_path / "ws" / "b_coverage_receipts.jsonl", "tmp": tmp_path}


def _log(ws, day):
    return bdl.log(share_root=ws["share"], day=day, store=ws["store"], ledger=ws["ledger"])


def _verdict(ws, day, layout):
    return bdl.verdict(day=day, layout=layout, store=ws["store"], ledger=ws["ledger"])


def _ready(ws, day, snaps, **kw):
    make_sidecar(ws["share"], day, snaps, **kw)
    _log(ws, day)
    return make_layout(ws["tmp"] / "layouts" / day.isoformat(), day, snaps)


# ----------------------------------------------------------------------------- log

def test_log_copies_verifies_and_is_idempotent_per_sha(ws):
    day = date(2026, 10, 29)
    assert _log(ws, day)["status"] == "not_ready"
    make_sidecar(ws["share"], day, plan(day))
    row = _log(ws, day)
    assert row["kind"] == "log" and row["schema"] == bdl.RECEIPT_SCHEMA and row["match"] is True
    assert _sha(ws["store"] / f"{day}.json") == row["sidecar_sha256"]
    assert _log(ws, day)["status"] == "already_logged"
    assert len(bdl.read_ledger(ws["ledger"], day, "log")) == 1
    make_sidecar(ws["share"], day, plan(day, unpriced=1))  # the share now holds other bytes
    with pytest.raises(bdl.DropListRefused, match="was logged with sidecar"):
        _log(ws, day)


def test_log_refuses_a_sums_mismatch_and_a_non_integer_count(ws):
    day = date(2026, 10, 30)
    make_sidecar(ws["share"], day, plan(day))
    (ws["share"] / "_b_coverage" / f"{day}.SHA256SUMS").write_text(f"{'0' * 64}  {day}.json\n", encoding="ascii")
    with pytest.raises(bdl.DropListRefused, match="not its SHA256SUMS"):
        _log(ws, day)
    counts = {m: {} for m in allow.MARKETS}
    counts["nyc"]["x"] = [7, 6.5]
    make_sidecar(ws["share"], day, [], counts=counts)
    with pytest.raises(bdl.DropListRefused, match="integers"):
        _log(ws, day)
    assert not ws["ledger"].exists()


# ----------------------------------------------------------------------------- verdict

def test_verdict_is_fixed_once_and_keeps_exactly_090(ws):
    day = date(2026, 10, 29)
    layout = _ready(ws, day, plan(day, unpriced=4))  # 36 / 40
    row = _verdict(ws, day, layout)
    assert (row["snapshots"], row["priced"], row["share"], row["dropped"]) == (40, 36, 0.9, False)
    assert row["layout_manifest_sha256"] == _sha(layout / "manifest.json")
    with pytest.raises(bdl.DropListRefused, match="fixed once"):
        _verdict(ws, day, layout)
    assert len(bdl.read_ledger(ws["ledger"], day, "verdict")) == 1


def test_verdict_drops_below_090_and_a_date_with_no_07_16_snapshot(ws):
    low, empty = date(2026, 10, 29), date(2026, 10, 30)
    assert _verdict(ws, low, _ready(ws, low, plan(low, unpriced=5)))["dropped"] is True  # 35 / 40
    row = _verdict(ws, empty, _ready(ws, empty, plan(empty, hours=())))
    assert (row["snapshots"], row["share"], row["dropped"]) == (0, 0.0, True)


@pytest.mark.parametrize("case", ["unlogged", "match_false", "other_bundle", "missing_snapshot",
                                  "band_mismatch_denver_03"])
def test_verdict_refusals(ws, case):
    day = date(2026, 10, 31)
    snaps = plan(day, extra=[("denver", 3, N_BANDS, False)])
    layout = make_layout(ws["tmp"] / "layout", day, snaps)
    if case == "unlogged":
        make_sidecar(ws["share"], day, snaps)
        match = "no logged sidecar"
    else:
        kw = {"match_false": {"match": False}, "other_bundle": {"bundle_sha": "e" * 64},
              "missing_snapshot": {"drop": ("nyc", 9)},
              "band_mismatch_denver_03": {"drop": ("denver", 3), "rows": N_BANDS + 1}}[case]
        make_sidecar(ws["share"], day, snaps, **kw)
        _log(ws, day)
        match = {"match_false": "match flag is false", "other_bundle": "not the sidecar's bundle",
                 "missing_snapshot": "no sidecar counts", "band_mismatch_denver_03": "n_rows 8 != n_bands 7"}[case]
    with pytest.raises(bdl.DropListRefused, match=match):
        _verdict(ws, day, layout)
    assert bdl.read_ledger(ws["ledger"], day, "verdict") == []


# ----------------------------------------------------------------------------- materialize

def _market_frame(snaps_by_day):
    """The transfer's price frame the R19 way (NaN where capture_price is None) for b_scorer's recompute."""
    import numpy as np
    import pandas as pd

    rows = []
    for day, snaps in snaps_by_day.items():
        for market, hour, n_bands, priced in snaps:
            key = f"{market}|{_sid(day, market, hour)}"
            rows += [{"row_key": key, "band_index": i, "p_market_yes": 0.5 if priced or i else np.nan}
                     for i in range(n_bands)]
    return pd.DataFrame(rows)


def test_materialize_is_the_window_verdicts_and_agrees_with_b_scorer_recompute(ws):
    days = [date(2026, 10, 29), date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1)]
    plans = {days[0]: plan(days[0], unpriced=5), days[1]: plan(days[1], unpriced=4),
             days[2]: plan(days[2], unpriced=9), days[3]: plan(days[3], hours=())}
    layouts = {}
    for day in days:
        layouts[day] = _ready(ws, day, plans[day])
        _verdict(ws, day, layouts[day])
    # 10-31 is logged and dropped but not promotion-countable: the transfer leaves it out of the window.
    window_days = [days[0], days[1], days[3]]
    window = ws["tmp"] / "window"
    mi.concat(layouts=[layouts[d] for d in window_days], out=window)
    out = ws["tmp"] / "look" / "b_drop_list.json"
    payload = bdl.materialize(window=window, out=out, ledger=ws["ledger"])
    look_dates = [d.isoformat() for d in window_days]
    assert payload["schema"] == b_scorer.DROP_LIST_SCHEMA == "b_drop_list/1"
    assert payload["dates"] == look_dates
    assert payload["dropped"] == ["2026-10-29", "2026-11-01"]
    assert set(payload["dropped"]) <= set(look_dates)  # VOID 6's first clause
    import pandas as pd

    snaps = pd.read_parquet(window / "inputs_snapshots.parquet")
    bands = pd.read_parquet(window / "inputs_bands.parquet")
    market = _market_frame({d: plans[d] for d in window_days})
    coverage = b_scorer.market_coverage(snaps, b_scorer.priced_snapshots(bands, market))
    recomputed = sorted(d for d in look_dates if coverage.get(d, {"share": 0.0})["share"] < b_scorer.COVERAGE_MIN)
    assert recomputed == payload["dropped"]  # VOID 6's second clause: no VOID 6
    with pytest.raises(bdl.DropListRefused, match="written once"):
        bdl.materialize(window=window, out=out, ledger=ws["ledger"])


def test_materialize_refuses_a_member_without_verdict_or_with_another_layout(ws):
    a, b = date(2026, 10, 29), date(2026, 10, 30)
    la = _ready(ws, a, plan(a))
    _verdict(ws, a, la)
    lb = _ready(ws, b, plan(b))
    window = ws["tmp"] / "window"
    mi.concat(layouts=[la, lb], out=window)
    with pytest.raises(bdl.DropListRefused, match="0 verdict rows"):
        bdl.materialize(window=window, out=ws["tmp"] / "d1.json", ledger=ws["ledger"])
    _verdict(ws, b, lb)
    manifest = json.loads((window / "manifest.json").read_text(encoding="utf-8"))
    manifest["members"][1]["manifest_sha256"] = "f" * 64
    (window / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(bdl.DropListRefused, match="is not the verdict's"):
        bdl.materialize(window=window, out=ws["tmp"] / "d2.json", ledger=ws["ledger"])
    assert not (ws["tmp"] / "d1.json").exists() and not (ws["tmp"] / "d2.json").exists()


# ----------------------------------------------------------------------------- ratchets

def test_module_never_names_a_transfer_or_label_file_and_avoids_the_receiver():
    text = (ROOT / "src/weather/calibration/b_drop_list.py").read_text(encoding="utf-8")
    for name in ("labels.parquet", "market.parquet", "transfer_files", "read_manifest", "TRANSFER_MANIFEST"):
        assert name not in text, name


def test_hook_admits_the_drop_list_module():
    spec = importlib.util.spec_from_file_location("bdl_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    module = "weather.calibration.b_drop_list"
    assert module in hook._OFFLINE_WEATHER_MODULES
    assert "weather.calibration.b_price_coverage" not in hook._OFFLINE_WEATHER_MODULES  # host-only, leased
    for near in (module + ".child", module + "_x"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {module} materialize --window w --out o'
    }}, constrained_capture_host=False) is not None  # recognized: workstation_heavy.ps1 only
