"""Atomic look-morning label freeze and its named recovery (R24; master rulings 2026-11-03, items 2(a)-(c)).

Guards:

- (a) unless the run's audit is OK (STATION_DRIFT exits 3), the freeze refuses before any folder under
  ``frozen/`` is made;
- (b) ``frozen/<look>`` appears only by renaming a verified tmp folder. A crash or a failed check leaves only the
  tmp folder, which a later freeze reports and ignores;
- (c) ``freeze --recover`` moves only a receipt-less or null-sha freeze, only while the look has no stamp or
  receipt, and only on master's dated, outcome-blind ruling.

The module never imports the reader and never writes a label value. Fixtures only (the ``world`` of
``test_venue_label_audit``): no network, no data/.
"""

import ast
import functools
import json
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from tests.backtesting.test_venue_label_audit import (  # noqa: F401  (world is a fixture)
    NOW,
    THROUGH,
    _assert_no_label_values,
    _event,
    _events,
    world,
)
from weather.backtesting import venue_label_audit as vla
from weather.backtesting import venue_label_freeze as vlf
from weather.schema_families import schema_version
from weather.schema_registry_families import load_families

MODULE = Path(vlf.__file__)


def _frozen(world):
    return world["kwargs"]["label_root"] / "frozen"


def _later(world, seconds):
    return {**world["kwargs"], "now": NOW + timedelta(seconds=seconds)}


def _ruling(path, look_id="mg1", **changes):
    body = {"schema_version": vlf.RULING_SCHEMA, "dated": "2026-10-26", "outcome_blind": True, "look_id": look_id,
            "reason": "the freeze died before its receipt; outcome-blind"}
    body.update(changes)
    path.write_text(json.dumps({k: v for k, v in body.items() if v is not None}), encoding="utf-8")
    return path


def _drift(world):
    _events(world["kwargs"]["events_path"], extra=[_event("highest-temperature-in-chicago-on-", "2026-10-24", "KMDW")])


def test_a_drifted_run_is_refused_before_any_frozen_folder(world, monkeypatch, capsys):
    _drift(world)
    with pytest.raises(vlf.FreezeDrift, match="audit status is STATION_DRIFT: nothing was frozen"):
        vla.freeze("mg1", THROUGH, **world["kwargs"])
    assert not _frozen(world).exists() and len(list((world["kwargs"]["label_root"] / "runs").iterdir())) == 1
    kwargs = _later(world, 1)
    label_root = kwargs.pop("label_root")
    monkeypatch.setattr(vla, "refresh", functools.partial(vla.refresh, **kwargs))
    argv = ["--label-root", str(label_root), "freeze", "--look", "mg1", "--through", THROUGH.isoformat()]
    assert vla.main(argv) == vla.EXIT_STATION_DRIFT == 3
    assert "STATION_DRIFT" in capsys.readouterr().err and not _frozen(world).exists()


def test_a_crash_mid_copy_leaves_only_a_tmp_folder_that_a_later_freeze_reports_and_ignores(world, monkeypatch):
    real, calls = shutil.copyfile, []

    def dies(source, target):
        if ".tmp-" in str(target):  # only the freeze's own copies count; refresh's snapshots pass through
            calls.append(target)
            if len(calls) == 5:
                raise OSError("disk went away")
        return real(source, target)

    monkeypatch.setattr(vlf.shutil, "copyfile", dies)
    with pytest.raises(OSError, match="disk went away"):
        vla.freeze("mg1", THROUGH, **world["kwargs"])
    monkeypatch.setattr(vlf.shutil, "copyfile", real)
    left = sorted(_frozen(world).iterdir())
    assert [p.name.startswith("mg1.tmp-") for p in left] == [True] and not (_frozen(world) / "mg1").exists()
    assert not (left[0] / vlf.RECEIPT_NAME).exists()
    look_dir, receipt, _ = vla.freeze("mg1", THROUGH, **_later(world, 1))
    assert receipt["ignored_partial_dirs"] == [str(left[0])] and left[0].is_dir()
    assert vlf.receipt_defects(look_dir) == [] and json.loads(
        (look_dir / vlf.RECEIPT_NAME).read_text(encoding="utf-8")) == receipt
    assert receipt["label_root"] == str(look_dir) and receipt["audit_status"] == "OK"
    for entry in receipt["markets"].values():
        for name in vlf.FROZEN_FILES:
            assert Path(entry[name]["path"]).is_file() and str(look_dir) in entry[name]["path"]
    _assert_no_label_values(receipt)


def test_a_freeze_that_fails_its_check_is_never_renamed(world, monkeypatch):
    real = vla.refresh

    def refresh_then_lose_a_source(*args, **kwargs):
        run_dir, receipt, run_audit = real(*args, **kwargs)
        manifest = json.loads((run_dir / "labels" / "nyc" / "manifest.json").read_text(encoding="utf-8"))
        Path(manifest["wu_daily_summary"]).unlink()
        return run_dir, receipt, run_audit

    monkeypatch.setattr(vla, "refresh", refresh_then_lose_a_source)
    with pytest.raises(vla.AuditRefused, match="failed its check.*nyc wu_daily_summary is missing"):
        vla.freeze("mg1", THROUGH, **world["kwargs"])
    left = sorted(p.name for p in _frozen(world).iterdir())
    assert len(left) == 1 and left[0].startswith("mg1.tmp-") and not (_frozen(world) / "mg1").exists()


@pytest.mark.parametrize("defect", ["no_receipt", "null_sha", "unreadable"])
def test_recover_moves_a_defective_freeze_to_void_and_a_refreeze_follows(world, defect):
    look_dir, receipt, _ = vla.freeze("mg1", THROUGH, **world["kwargs"])
    path = look_dir / vlf.RECEIPT_NAME
    if defect == "no_receipt":
        path.unlink()
    elif defect == "unreadable":
        path.write_text("{", encoding="utf-8")
    else:
        receipt["markets"]["nyc"]["manifest"]["sha256"] = None
        path.write_text(json.dumps(receipt), encoding="utf-8")
    ruling = _ruling(world["tmp"] / "ruling.json")
    data_root = world["tmp"] / "data"
    record = vlf.recover("mg1", ruling, label_root=world["kwargs"]["label_root"], data_root=data_root,
                         now=NOW + timedelta(seconds=1))
    void = Path(record["to"])
    assert not look_dir.exists() and void.name == "mg1.void-20261026T111501Z" and void.is_dir()
    on_disk = json.loads((void / vlf.RECOVERY_NAME).read_text(encoding="utf-8"))
    assert on_disk == record and record["schema_version"] == vlf.RECOVERY_SCHEMA
    assert record["ruling"]["sha256"] == vla._sha256(ruling) and record["defects"]
    if defect == "null_sha":
        assert record["defects"] == ["nyc manifest sha256 is null"]
    again, _, _ = vla.freeze("mg1", THROUGH, **_later(world, 2))
    assert vlf.receipt_defects(again) == []


@pytest.mark.parametrize("case,match", [
    ("stamped", "has a stamp or receipt"),
    ("unregistered", "no registered stamp location"),
    ("complete", "is a complete freeze"),
    ("absent", "nothing to recover"),
    ("not_blind", "not marked outcome_blind"),
    ("other_look", "names look 'b', not 'mg1'"),
    ("future", "dated 2026-10-27, after today"),
    ("schema", "recovery ruling schema"),
    ("no_reason", "gives no reason"),
    ("no_ruling_file", "missing or malformed"),
])
def test_recover_refusals_move_nothing(world, case, match):
    label_root, data_root = world["kwargs"]["label_root"], world["tmp"] / "data"
    look_id = "t1" if case == "unregistered" else "mg1"
    if case != "absent":
        look_dir, receipt, _ = vla.freeze(look_id, THROUGH, **world["kwargs"])
        if case != "complete":
            (look_dir / vlf.RECEIPT_NAME).unlink()
    if case == "stamped":
        stamp = data_root / "mg1_look" / "started-abc.json"
        stamp.parent.mkdir(parents=True)
        stamp.write_text("{}", encoding="utf-8")
    changes = {"not_blind": {"outcome_blind": False}, "other_look": {"look_id": "b"},
               "future": {"dated": "2026-10-27"}, "schema": {"schema_version": "x"},
               "no_reason": {"reason": " "}}.get(case, {})
    ruling = _ruling(world["tmp"] / "ruling.json", **changes)
    if case == "no_ruling_file":
        ruling = world["tmp"] / "missing.json"
    before = sorted(p.name for p in _frozen(world).iterdir()) if _frozen(world).exists() else []
    with pytest.raises(vla.AuditRefused, match=match):
        vlf.recover(look_id, ruling, label_root=label_root, data_root=data_root, now=NOW)
    after = sorted(p.name for p in _frozen(world).iterdir()) if _frozen(world).exists() else []
    assert after == before


def test_b_look_consumed_marker_blocks_recovery(world):
    look_dir, _, _ = vla.freeze("b", THROUGH, **world["kwargs"])
    (look_dir / vlf.RECEIPT_NAME).unlink()
    marker = world["tmp"] / "data" / "b_look" / "consumed-abc.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    with pytest.raises(vla.AuditRefused, match="has a stamp or receipt"):
        vlf.recover("b", _ruling(world["tmp"] / "r.json", look_id="b"), label_root=world["kwargs"]["label_root"],
                    data_root=world["tmp"] / "data", now=NOW)
    assert look_dir.is_dir()


def test_the_cli_recover_and_its_argument_refusals(world, monkeypatch, capsys):
    look_dir, _, _ = vla.freeze("mg1", THROUGH, **world["kwargs"])
    (look_dir / vlf.RECEIPT_NAME).unlink()
    root = str(world["kwargs"]["label_root"])
    ruling = str(_ruling(world["tmp"] / "ruling.json"))
    monkeypatch.setattr(vlf, "look_stamps", lambda look_id, data_root=None: [])
    assert vla.main(["--label-root", root, "freeze", "--recover", "mg1"]) == 2
    assert vla.main(["--label-root", root, "freeze", "--recover", "mg1", "--ruling", ruling, "--look", "mg1"]) == 2
    assert vla.main(["--label-root", root, "freeze", "--look", "mg1"]) == 2
    assert vla.main(["--label-root", root, "freeze", "--look", "mg1", "--through", THROUGH.isoformat(),
                     "--ruling", ruling]) == 2
    assert look_dir.is_dir()
    capsys.readouterr()
    assert vla.main(["--label-root", root, "freeze", "--recover", "mg1", "--ruling", ruling]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["defects"] == [f"no readable {vlf.RECEIPT_NAME}"] and not look_dir.exists()


def test_module_embargo_size_and_schemas():
    source = MODULE.read_text(encoding="utf-8")
    for token in ("read_venue_labels", "venue_label_reader", "allow_reserved_window", "Path.cwd", "getcwd",
                  "rmtree", "unlink"):
        assert token not in source
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
    assert {name for name in imported if name.startswith("weather")} == {
        "weather.backtesting", "weather.backtesting.venue_rule_labels", "weather.market.market_registry",
        "weather.paths", "weather.schema_families"}
    assert len(source.splitlines()) <= 600
    assert len(Path(vla.__file__).read_text(encoding="utf-8").splitlines()) <= 600  # the budget is never raised
    registry = load_families()
    assert registry.errors == ()
    for name, constant in (("venue_label_freeze_recovery_ruling", vlf.RULING_SCHEMA),
                           ("venue_label_freeze_recovery", vlf.RECOVERY_SCHEMA)):
        assert registry.family_of(name) == "venue_labels"
        assert schema_version(name) == constant == f"{name}_v1"
