from pathlib import Path

import pytest

from tools.research.retrain_pilot.run import main, make_guarded_open


def test_guarded_open_redirects_writes_outside_out_dir(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    outside = tmp_path / "served" / "feature_model_hgb_x.pkl"
    guarded = make_guarded_open(out_dir)
    with guarded(outside, "wb") as handle:
        handle.write(b"x")
    assert not outside.exists()
    assert (out_dir / "redirected" / outside.name).read_bytes() == b"x"


def test_guarded_open_keeps_writes_inside_out_dir_and_reads_anywhere(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    inside = out_dir / "a.txt"
    guarded = make_guarded_open(out_dir)
    with guarded(inside, "w", encoding="utf-8") as handle:
        handle.write("ok")
    with guarded(inside, encoding="utf-8") as handle:
        assert handle.read() == "ok"


def test_refuses_non_2026_target_date(tmp_path):
    with pytest.raises(SystemExit):
        main([
            "--market", "atlanta", "--target-date", "2025-10-20",
            "--data-root", str(tmp_path / "d"), "--artifacts-read-root", str(tmp_path / "a"),
            "--out-dir", str(tmp_path / "o"),
        ])


def test_refuses_out_dir_inside_data_root(tmp_path):
    with pytest.raises(SystemExit):
        main([
            "--market", "atlanta", "--target-date", "2026-10-20",
            "--data-root", str(tmp_path), "--artifacts-read-root", str(tmp_path / "a"),
            "--out-dir", str(tmp_path / "o"),
        ])
