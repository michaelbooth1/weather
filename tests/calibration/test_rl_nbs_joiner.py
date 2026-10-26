"""Lane L2 rung R-L: the NBS TXN joiner (inputs only, no outcome join).

Guards: L2 R-L pre-registration (docs/research/l2-pooled-residual-2026-10-24/rungl/rule_rl.md) - TXN read at the
00 UTC column of the day after the target date, point-in-time cycle selection (LastModified + 10 min <= h:00,
age <= 12 h), block sha256 and header identity, sparse 3-character fields, and fail-closed missingness.
"""
import hashlib
import importlib
import json
import math

import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise


def _fields(values):
    return "".join("   " if v is None else f"{v:>3}" for v in values)


def _block(station, cycle_hour, day="8/01/2023", txn=88, xnd=2):
    # 3-hourly columns placed so one is valid at 00Z of the next day (cycle 12Z: 18Z, 21Z, 00Z, ..., 12Z)
    fhr = [(24 - cycle_hour) + 3 * k for k in range(-2, 5)]
    utc = [(cycle_hour + f) % 24 for f in fhr]
    txn_row = [txn if u == 0 else (70 if u == 12 else None) for u in utc]
    xnd_row = [xnd if u in (0, 12) else None for u in utc]
    lines = [f" {station}    NBM V4.1 NBS GUIDANCE    {day}  {cycle_hour:02d}00 UTC",
             " DT /AUG   1/AUG   2",
             " UTC " + _fields(utc),
             " FHR " + _fields(fhr),
             " TXN " + _fields(txn_row),
             " XND " + _fields(xnd_row),
             " TMP " + _fields([80, 84, 82, 76, 74, 72, 75]),
             " PRA " + "100" * 7]
    return ("\n".join(lines) + "\n").encode("ascii")


def _corpus(tmp_path, cycles):
    """cycles: [(utc_date, cycle_hour, last_modified, block_bytes, station_status)]"""
    rows = []
    for utc_date, hour, modified, block, status in cycles:
        rel = f"raw/nbs/{utc_date.replace('-', '')}/nbs.t{hour:02d}z.blocks"
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(block)
        rows.append({"product": "nbs", "utc_date": utc_date, "cycle": f"{hour:02d}", "status": "ok",
                     "last_modified": modified, "blocks_file": rel,
                     "stations": {"KATL": {"file_offset": 0, "length": len(block), "status": status,
                                           "sha256": hashlib.sha256(block).hexdigest()}}})
        rows.append({**rows[-1], "product": "nbh"})
    with open(tmp_path / "manifest.jsonl", "w", encoding="utf-8") as w:
        for r in rows:
            w.write(json.dumps(r) + "\n")
        w.write('{"product": "nbs", "utc_')  # torn tail of a corpus still being appended
    return tmp_path


def test_rl_parse_block_reads_sparse_fields_at_fhr_positions():
    block = prm.rl_parse_block(_block("KATL", 12).decode("ascii"))
    assert block["station"] == "KATL" and block["issued"].hour == 12
    cols = {k.isoformat(): v for k, v in block["columns"].items()}
    assert cols["2023-08-02T00:00:00+00:00"]["TXN"] == 88 and cols["2023-08-02T00:00:00+00:00"]["XND"] == 2
    assert cols["2023-08-01T18:00:00+00:00"]["TXN"] is None
    assert all(v["PRA"] == 100 for v in cols.values())


def test_rl_selects_the_newest_cycle_available_ten_minutes_before_the_cutoff(tmp_path):
    corpus = prm.RlNbsCorpus(_corpus(tmp_path, [
        ("2023-08-01", 12, "2023-08-01T13:05:00.000Z", _block("KATL", 12, txn=88), "ok"),
        ("2023-08-01", 13, "2023-08-01T13:55:00.000Z", _block("KATL", 13, txn=91), "ok"),
    ]), markets=("atlanta",))
    assert corpus.stats["manifest_corrupt_line"] == 1
    # 10:00 EDT = 14:00Z: the 13Z cycle (13:55 + 10 min = 14:05) is not yet usable, 12Z is
    at10 = corpus.raw("atlanta", "2023-08-01", 10)
    assert (at10["n_txn"], at10["n_xnd"], at10["n_miss"]) == (88.0, 2.0, 0.0)
    assert at10["cycle_utc"] == "2023-08-01T12:00:00+00:00" and at10["age_s"] == 2 * 3600
    assert corpus.raw("atlanta", "2023-08-01", 11)["n_txn"] == 91.0
    assert corpus.raw("atlanta", "2023-08-01", 8)["reason"] == "no_cycle"  # 12:00Z, nothing available yet
    cols = prm.rl_columns(at10, 85.0)
    assert cols["n_gap"] == pytest.approx(3.0) and cols["n_miss"] == 0.0


def test_rl_fails_closed_on_sha_identity_absent_column_and_age(tmp_path):
    good = _block("KATL", 12)
    corpus = prm.RlNbsCorpus(_corpus(tmp_path, [
        ("2023-08-01", 12, "2023-08-01T13:05:00.000Z", _block("KMIA", 12), "ok"),          # wrong station
        ("2023-08-02", 12, "2023-08-02T13:05:00.000Z", good, "ok"),                         # tampered below
        ("2023-08-03", 12, "2023-08-03T13:05:00.000Z", _block("KATL", 12, day="8/03/2023", txn=None), "ok"),
        ("2023-08-04", 12, "2023-08-04T13:05:00.000Z", _block("KATL", 12, day="8/04/2023"), "station_absent"),
    ]), markets=("atlanta",))
    (tmp_path / "raw/nbs/20230802/nbs.t12z.blocks").write_bytes(good.replace(b"88", b"99"))
    assert corpus.raw("atlanta", "2023-08-01", 10)["reason"] == "identity_mismatch"
    assert corpus.raw("atlanta", "2023-08-02", 10)["reason"] == "sha_mismatch"
    assert corpus.raw("atlanta", "2023-08-03", 10)["reason"] == "column_absent"
    # 08-04 has no usable block; the 08-03 12Z cycle is > 12 h old at 08-04 10:00 EDT
    assert corpus.raw("atlanta", "2023-08-04", 10)["reason"] == "no_cycle"
    frame = pd.DataFrame({"market": ["atlanta"] * 3, "target_date": ["2023-08-01", "2023-08-02", "2023-08-03"],
                          "hour": [10, 10, 10], "fh": [85.0, 85.0, 85.0]})
    out, stats = prm.rl_training_columns(frame, corpus)
    assert list(out["n_miss"]) == [1.0, 1.0, 1.0] and all(math.isnan(v) for v in out["n_txn"])
    gate = prm.rl_parity(stats)
    assert not gate["pass"] and not gate["checks"]["sha_mismatch"] and not gate["checks"]["identity_mismatch"]
    assert set(prm.RL_ARMS["B_L"]["extra_ols"]) | set(prm.RL_ARMS["P3d_L"]["extra_hgb"]) == set(prm.RL_FEATURES)
