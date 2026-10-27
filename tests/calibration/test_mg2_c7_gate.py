"""MG-2 forward gate on as-of-capture vectors (rule §8 Clarification C7).

Guards: MG-2 rule §8 C7 (docs/research/mg2-composite-binding-2026-10-25/rule.md): the forward MG-2 vs MG-1
gate refuses the last_in_hour vectors and accepts only a forward emission's as-of-capture vectors.
"""
import json
from datetime import date

import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

mg2 = import_or_skip_on_capture_host("weather.calibration.mg2_composite")


def _emission(folder, *, mode="forward", vectors_name=None, asof_sha=None):
    folder.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({"row_key": ["a|1", "a|1"], "band_index": [0, 1], "p": [0.25, 0.75]})
    lih = folder / mg2.VECTORS
    asof = folder / mg2.ASOF_VECTORS
    frame.to_parquet(lih, index=False)
    frame.assign(p=[0.3, 0.7]).to_parquet(asof, index=False)
    audit = {"mode": mode, "vectors_sha256": mg2.sha256_file(lih),
             "asof_capture": {"vectors_sha256": asof_sha or mg2.sha256_file(asof)}}
    (folder / mg2.EMIT_AUDIT).write_text(json.dumps(audit), encoding="utf-8")
    return lih, asof


def test_the_forward_gate_refuses_the_last_in_hour_vectors(tmp_path):
    lih, _asof = _emission(tmp_path / "emit")
    with pytest.raises(mg2.Mg2Refused, match="C7"):
        mg2.require_gate_vectors(lih)
    with pytest.raises(mg2.Mg2Refused, match="C7"):
        mg2.score(layout_root=tmp_path, vectors=lih, rule=tmp_path / "no-rule.md", out=tmp_path / "out",
                  release_binding=tmp_path)


def test_a_last_in_hour_file_renamed_to_the_as_of_name_is_refused(tmp_path):
    lih, asof = _emission(tmp_path / "emit")
    asof.write_bytes(lih.read_bytes())
    with pytest.raises(mg2.Mg2Refused, match="not the as-of-capture vectors"):
        mg2.require_gate_vectors(asof)


@pytest.mark.parametrize("mode", ["control", None])
def test_vectors_of_a_control_or_unknown_emission_are_refused(tmp_path, mode):
    _lih, asof = _emission(tmp_path / "emit", mode=mode)
    with pytest.raises(mg2.Mg2Refused, match="forward emission"):
        mg2.require_gate_vectors(asof)


def test_as_of_vectors_without_their_emit_audit_are_refused(tmp_path):
    _lih, asof = _emission(tmp_path / "emit")
    (tmp_path / "emit" / mg2.EMIT_AUDIT).unlink()
    with pytest.raises(mg2.Mg2Refused, match=mg2.EMIT_AUDIT):
        mg2.require_gate_vectors(asof)


def test_the_forward_gate_accepts_the_as_of_capture_vectors(tmp_path):
    _lih, asof = _emission(tmp_path / "emit")
    assert mg2.require_gate_vectors(asof)["mode"] == "forward"
    # score passes the C7 check and stops at the next guard (no rule file here), never at C7
    with pytest.raises(Exception) as caught:
        mg2.score(layout_root=tmp_path, vectors=asof, rule=tmp_path / "no-rule.md", out=tmp_path / "out",
                  release_binding=tmp_path, today=date(2027, 6, 1))
    assert "C7" not in str(caught.value)
