"""MG-1 look receipt writer (``mg1_look_receipt/1``) and its registered entry point.

Guards: master's R3 ruling of 2026-10-26 on the B-1 binding: the MG-1 look receipt is written by code only, never by
hand; ``looked_at_utc`` is stamped by the clock immediately before the look's first outcome join (the start marker is
on disk before the loader runs); receipt and start marker are written in mode "x" at fixed ``weather.paths``
data paths keyed by the MG-1 rule sha; the entry point is registered by module name and source sha256 in
``MG1_CONFIRMATION_ENTRY_POINTS``; a hand-made or hand-edited receipt fails the checks B-1's VOID 5 runs.
"""
import json
import sys
import types
from pathlib import Path

import pytest

from weather import mg1_reserved_window as window
from weather import paths
from weather.calibration import mg1_look as m
from weather.schema_families import schema_version

ROOT = Path(__file__).resolve().parents[2]
RULE = ROOT / "docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md"
DATES = ["2026-10-15", "2026-11-28", "2026-10-20"]


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "LOOK_ROOT", tmp_path / "_mg1_look")
    monkeypatch.setattr(m, "head_commit", lambda root=None: "c" * 40)


def _as_main(monkeypatch, name=m.MODULE, origin=None):
    main = types.ModuleType("__main__")
    main.__spec__ = types.SimpleNamespace(name=name, origin=str(origin or m.__file__))
    monkeypatch.setitem(sys.modules, "__main__", main)


def _written(tmp_path, monkeypatch):
    _as_main(monkeypatch)
    look = m.Look(RULE)
    look.join_outcomes(lambda: None)
    result = tmp_path / "result.json"
    result.write_text("{}", encoding="utf-8")
    return look, look.finish(result=result, dates=DATES)


def test_the_entry_point_is_registered_at_its_current_source_sha():
    assert window.MG1_CONFIRMATION_ENTRY_POINTS == {m.MODULE: m.module_sha256()}
    assert m.MG1_RULE_SHA256 == m.sha256_file(RULE)


def test_the_receipt_and_start_marker_live_at_fixed_repo_paths(monkeypatch):
    monkeypatch.undo()
    assert m.LOOK_ROOT == paths.data_path("mg1_look")
    assert m.receipt_path("ab").name == "receipt-ab.json" and m.started_path("ab").name == "started-ab.json"


def test_looked_at_is_stamped_and_on_disk_before_the_first_outcome_join(tmp_path, monkeypatch):
    _as_main(monkeypatch)
    look = m.Look(RULE)
    seen = []

    def loader(x):
        started = json.loads(m.started_path(m.MG1_RULE_SHA256).read_text(encoding="utf-8"))
        seen.append(started["looked_at_utc"])
        return x

    assert look.join_outcomes(loader, 7) == 7 and look.join_outcomes(loader, 8) == 8
    assert seen == [look.looked_at_utc] * 2  # stamped once, before the first join only
    result = tmp_path / "r.json"
    result.write_text("{}", encoding="utf-8")
    receipt = json.loads(look.finish(result=result, dates=DATES).read_text(encoding="utf-8"))
    assert receipt["looked_at_utc"] == look.looked_at_utc <= receipt["completed_at_utc"]
    assert tuple(sorted(receipt)) == tuple(sorted(m.RECEIPT_FIELDS))
    assert receipt["schema"] == schema_version("mg1_look_receipt") == m.RECEIPT_SCHEMA
    assert receipt["dates_scored"] == {"count": 3, "first": "2026-10-15", "last": "2026-11-28"}
    assert receipt["entry_point"] == {"module": m.MODULE, "source_sha256": m.module_sha256()}
    assert receipt["result"]["sha256"] == m.sha256_file(result) and receipt["repo_commit"] == "c" * 40
    with pytest.raises(m.MG1LookRefused, match="finished"):
        look.join_outcomes(loader, 9)


def test_a_written_receipt_passes_and_one_look_per_rule(tmp_path, monkeypatch):
    _, path = _written(tmp_path, monkeypatch)
    assert path == m.receipt_path(m.MG1_RULE_SHA256) and m.receipt_problems(path) == []
    with pytest.raises(m.MG1LookRefused, match="exactly one look"):
        m.Look(RULE)
    m.receipt_path(m.MG1_RULE_SHA256).unlink()  # even without the receipt, the start marker refuses
    with pytest.raises(m.MG1LookRefused, match="started-.*exactly one look"):
        m.Look(RULE)


def test_a_crash_after_the_first_join_still_spends_the_look(monkeypatch):
    _as_main(monkeypatch)
    look = m.Look(RULE)
    with pytest.raises(RuntimeError):
        look.join_outcomes(lambda: (_ for _ in ()).throw(RuntimeError("join broke")))
    assert m.started_path(m.MG1_RULE_SHA256).is_file()
    with pytest.raises(m.MG1LookRefused, match="exactly one look"):
        m.Look(RULE)


@pytest.mark.parametrize("name,origin", [("weather.calibration.mg1_look2", None), ("mg1_look", None),
                                         (None, None), (m.MODULE, "edited")])
def test_only_the_registered_entry_point_can_stamp(tmp_path, monkeypatch, name, origin):
    if origin:
        origin = tmp_path / "mg1_look.py"
        origin.write_bytes(Path(m.__file__).read_bytes() + b"# edited\n")
    _as_main(monkeypatch, name, origin)
    look = m.Look(RULE)
    with pytest.raises(m.MG1LookRefused, match="not the registered MG-1 look"):
        look.join_outcomes(lambda: None)
    assert not m.started_path(m.MG1_RULE_SHA256).exists() and look.looked_at_utc is None


def test_refusals_before_anything_is_read(tmp_path, monkeypatch):
    other = tmp_path / "rule.md"
    other.write_bytes(RULE.read_bytes() + b"\n")
    with pytest.raises(m.MG1LookRefused, match="not the signed"):
        m.Look(other)
    _as_main(monkeypatch)
    look = m.Look(RULE)
    with pytest.raises(m.MG1LookRefused, match="no outcome was joined"):
        look.finish(result=other, dates=DATES)


def test_hand_made_or_hand_edited_receipts_fail(tmp_path, monkeypatch):
    _, path = _written(tmp_path, monkeypatch)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert m.receipt_problems(tmp_path / "absent.json") == [f"MG-1 look receipt {tmp_path / 'absent.json'} "
                                                            "does not exist"]
    hand = tmp_path / "hand.json"
    hand.write_text(json.dumps({"looked_at_utc": "2026-12-14T00:00:00Z"}), encoding="utf-8")
    assert m.receipt_problems(hand) == ["MG-1 look receipt schema is not mg1_look_receipt/1"]
    edited = dict(receipt, looked_at_utc="2026-12-01T00:00:00Z")
    hand.write_text(json.dumps(edited), encoding="utf-8")
    problems = m.receipt_problems(hand)
    assert any("body_sha256" in p for p in problems) and any("differ from the written" in p for p in problems)
    path.write_text(json.dumps(edited, indent=1, sort_keys=True) + "\n", encoding="utf-8")  # edited in place
    assert any("body_sha256" in p for p in m.receipt_problems(path))
    stranger = dict(receipt, entry_point={"module": m.MODULE, "source_sha256": "0" * 64})
    stranger["body_sha256"] = m.body_sha256(stranger)
    path.write_text(json.dumps(stranger), encoding="utf-8")
    assert m.receipt_problems(path) == [
        "MG-1 look receipt was not written by the registered entry point at its registered sha"]


def test_the_run_command_refuses_until_the_scoring_is_built(capsys):
    assert m.main(["run"]) == 2
    assert "not built" in capsys.readouterr().err
