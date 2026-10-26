"""Offline checks for the L12 NBS/NBH corpus finalizer on a tiny hand-made corpus.

Guards: tools/research/nbm_nbs_nbh_finalize.py sealing contract (every block re-hashed against its
manifest row, SHA256SUMS covers manifest plus every blocks file with POSIX paths, coverage counts
ok blocks per station x year x cycle and lists every gap, a later manifest row wins on resume).
"""
import hashlib
import json

from tools.research import nbm_nbs_nbh_finalize as fin


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _corpus(tmp_path, tamper=False):
    blocks = {"KATL": b" KATL  NBM V4.3 NBS GUIDANCE\n TXN  77\n", "CYYZ": b" CYYZ  NBM V4.3 NBS GUIDANCE\n TXN  50\n"}
    blob = blocks["CYYZ"] + blocks["KATL"]
    rel = "raw/nbs/20250801/nbs.t12z.blocks"
    (tmp_path / "raw/nbs/20250801").mkdir(parents=True)
    (tmp_path / rel).write_bytes(blob + (b"x" if tamper else b""))
    stations = {
        "CYYZ": {"status": "ok", "file_offset": 0, "length": len(blocks["CYYZ"]), "sha256": _sha(blocks["CYYZ"])},
        "KATL": {"status": "ok", "file_offset": len(blocks["CYYZ"]), "length": len(blocks["KATL"]),
                 "sha256": _sha(blocks["KATL"])},
    }
    rows = [
        # A torn earlier attempt for the same key: the later row must win.
        {"utc_date": "2025-08-01", "cycle": "12", "product": "nbs", "status": "object_missing"},
        {"utc_date": "2025-08-01", "cycle": "12", "product": "nbs", "status": "ok", "size": 29000000,
         "blocks_file": rel, "blocks_sha256": _sha(blob), "stations": stations},
        {"utc_date": "2025-08-01", "cycle": "13", "product": "nbs", "status": "ok", "size": 8388608,
         "blocks_file": rel, "blocks_sha256": _sha(blob),
         "stations": {"CYYZ": stations["CYYZ"], "KATL": {"status": "station_absent"}}},
        {"utc_date": "2025-08-02", "cycle": "12", "product": "nbs", "status": "object_missing"},
    ]
    (tmp_path / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return blob


def test_finalize_counts_coverage_lists_gaps_and_writes_sums(tmp_path):
    _corpus(tmp_path)
    res = fin.finalize(tmp_path)
    assert res["objects"] == 3
    assert res["mismatches"] == []
    assert res["gaps"] == ["2025-08-01 13Z nbs KATL: station_absent (object size 8388608)",
                           "2025-08-02 12Z nbs: object_missing"]
    sums = (tmp_path / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert [s.split("  ")[1] for s in sums] == ["manifest.jsonl", "raw/nbs/20250801/nbs.t12z.blocks"]
    for s in sums:
        digest, rel = s.split("  ")
        assert _sha((tmp_path / rel).read_bytes()) == digest
    assert res["sha256sums"] == _sha((tmp_path / "SHA256SUMS").read_bytes())
    cov = (tmp_path / "coverage.md").read_text(encoding="utf-8")
    # Planned: 12Z on two dates, 13Z on one, so three objects per station.
    assert "| CYYZ | 2/3 |" in cov
    assert "| KATL | 1/3 |" in cov
    lines = cov.splitlines()
    # Station x year x cycle cells below 100%: 12Z planned on 2 dates, 13Z on 1.
    assert "CYYZ 2025 12Z 1/2" in lines
    assert "KATL 2025 12Z 1/2" in lines
    assert "KATL 2025 13Z 0/1" in lines
    assert "CYYZ 2025 13Z 1/1" not in lines
    assert "## NBH" not in cov


def test_finalize_flags_a_tampered_blocks_file(tmp_path):
    _corpus(tmp_path, tamper=True)
    res = fin.finalize(tmp_path)
    assert "raw/nbs/20250801/nbs.t12z.blocks" in res["mismatches"]
    assert fin.main([str(tmp_path)]) == 1


def test_block_level_hash_mismatch_is_reported_per_station(tmp_path):
    _corpus(tmp_path)
    rows = [json.loads(x) for x in (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    rows[1]["stations"]["KATL"]["sha256"] = "0" * 64
    (tmp_path / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    res = fin.finalize(tmp_path)
    assert res["mismatches"] == ["raw/nbs/20250801/nbs.t12z.blocks#KATL"]
