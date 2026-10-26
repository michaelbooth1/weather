"""Lane L2 rung R-L2: NBS TXN with the format-defined cycle choice (inputs only, no outcome join).

Guards: L2 R-L2 pre-registration (docs/research/l2-pooled-residual-2026-10-24/rungl2/rule_rl2.md) - the newest
eligible cycle whose verified block carries the target-day TXN and XND (00 UTC d+1), walking older within R-L's
12 h age bound; a block failing sha256, parse or identity fails closed instead of being skipped; R-L's newest-cycle
reading is unchanged.
"""
import importlib

import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

from tests.calibration.test_rl_nbs_joiner import _block, _corpus  # noqa: E402


def _cycles():
    return [("2023-08-01", 11, "2023-08-01T12:05:00.000Z", _block("KATL", 11, txn=88), "ok"),
            ("2023-08-01", 12, "2023-08-01T13:05:00.000Z", _block("KATL", 12, txn=90), "ok"),
            ("2023-08-01", 13, "2023-08-01T13:55:00.000Z", _block("KATL", 13, txn=None), "ok")]


def test_rl2_skips_a_verified_cycle_without_the_column_and_rl_does_not(tmp_path):
    root = _corpus(tmp_path, _cycles())
    rl2 = prm.RlNbsCorpus(root, markets=("atlanta",), cycle_rule="txn_bearing")
    rl = prm.RlNbsCorpus(root, markets=("atlanta",))
    # 11:00 EDT = 15Z: 13Z is the newest eligible cycle but omits the 00Z d+1 TXN
    got = rl2.raw("atlanta", "2023-08-01", 11)
    assert (got["n_txn"], got["n_miss"], got["skipped"]) == (90.0, 0.0, 1)
    assert got["cycle_utc"] == "2023-08-01T12:00:00+00:00" and got["age_s"] == 3 * 3600
    assert got["newest_age_s"] == 2 * 3600
    assert rl.raw("atlanta", "2023-08-01", 11)["reason"] == "column_absent"
    # 10:00 EDT = 14Z: 13Z is not yet usable, so both rules take 12Z
    assert rl2.raw("atlanta", "2023-08-01", 10)["n_txn"] == rl.raw("atlanta", "2023-08-01", 10)["n_txn"] == 90.0
    frame = pd.DataFrame({"market": ["atlanta"] * 2, "target_date": ["2023-08-01"] * 2, "hour": [10, 11],
                          "fh": [89.0, 89.0]})
    _, stats = prm.rl_training_columns(frame, rl2)
    assert stats["rows_covered"] == 2 and stats["staleness"]["h11"]["share_newest_skipped"] == 1.0
    assert stats["staleness"]["h11"]["selected_cycle_utc_hour"] == {"12Z": 1}


def test_rl2_fails_closed_on_a_bad_newer_block_and_honours_the_age_bound(tmp_path):
    root = _corpus(tmp_path, _cycles())
    (tmp_path / "raw/nbs/20230801/nbs.t13z.blocks").write_bytes(_block("KATL", 13, txn=None).replace(b"80", b"81"))
    rl2 = prm.RlNbsCorpus(root, markets=("atlanta",), cycle_rule="txn_bearing")
    assert rl2.raw("atlanta", "2023-08-01", 11)["reason"] == "sha_mismatch"  # not skipped to 12Z
    # 08-02 09:00 EDT = 13Z: the newest 08-01 cycle is 24 h old, beyond the 12 h bound
    assert rl2.raw("atlanta", "2023-08-02", 9)["reason"] == "no_cycle"


def test_rl2_reports_no_txn_cycle_when_every_cycle_in_the_age_bound_lacks_the_column(tmp_path):
    root = _corpus(tmp_path, [
        ("2023-08-01", 1, "2023-08-01T02:05:00.000Z", _block("KATL", 1, txn=87), "ok"),       # 14 h old at 15Z
        ("2023-08-01", 13, "2023-08-01T13:55:00.000Z", _block("KATL", 13, txn=None), "ok")])
    rl2 = prm.RlNbsCorpus(root, markets=("atlanta",), cycle_rule="txn_bearing")
    got = rl2.raw("atlanta", "2023-08-01", 11)
    assert got["reason"] == "no_txn_cycle" and got["n_miss"] == 1.0 and got["cycle_utc"] is None
    with pytest.raises(prm.PooledModelError):
        prm.RlNbsCorpus(root, markets=("atlanta",), cycle_rule="freshest")
    assert prm.RL_VARIANTS["R-L2"]["rule_sha256"] == prm.RL2_RULE_SHA256


def test_rl_anchor_diag_pairs_txn_with_the_l9_anchor_inputs_only(tmp_path, monkeypatch):
    pytest.importorskip("weather.calibration.ols_floor_ladder")
    import json

    nbs = _corpus(tmp_path / "nbs", _cycles())
    (nbs / "SHA256SUMS").write_text("x\n", encoding="utf-8")
    monkeypatch.setitem(prm.RL_VARIANTS, "R-L2", {**prm.RL_VARIANTS["R-L2"], "sums": None})
    nbm = tmp_path / "nbm.jsonl"
    nbm.write_text(json.dumps({"available": True, "market_id": "atlanta", "target_date": "2023-08-01", "cycle": "07",
                               "last_modified": "2023-08-01T08:30:00.000Z", "mean": 89.0,
                               "product_version": "4.1"}) + "\n", encoding="utf-8")
    report = prm.rl_anchor_diag(nbs_corpus=nbs, nbs_dev_corpus=nbs, nbm_train_corpus=nbm, nbm_dev_corpus=nbm,
                                out_path=tmp_path / "out" / "diag.json", markets=("atlanta",))
    groups = report["groups"]
    # h10 and h11 EDT select the 12Z TXN 90 against the 07Z anchor 89; h07-09 have no TXN-bearing cycle
    assert groups["half_year_hour|train|2023|h10"]["mean_signed_f"] == 1.0
    assert groups["half_version|train|4.1"]["n"] == report["counts"]["train"]["paired"]
    assert groups["half_anchor_cycle|train|07Z"]["share_le_1f"] == 1.0
    assert report["counts"]["dev"]["rows"] == 0  # 2023 is outside the dev dates
    with pytest.raises(prm.PooledModelError, match="refusing to overwrite"):
        prm.rl_anchor_diag(nbs_corpus=nbs, nbs_dev_corpus=nbs, nbm_train_corpus=nbm, nbm_dev_corpus=nbm,
                           out_path=tmp_path / "out" / "diag.json", markets=("atlanta",))
