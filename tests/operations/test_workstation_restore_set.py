"""Restore-set planning, event-manifest binding and cache publication on fixtures.

The two cloud/crypto steps are fixture seams that hand back receipts built by
the catalog test chain; every catalog, restore and cache record is produced by
the production publishers.
"""
from datetime import date
import hashlib
import json
import shutil
import time

import pytest

from tests.cold_archive_fixture import SLUG, corpus, recovery, snapshots_root  # noqa: F401
from weather import cold_archive_locations as locations
from weather.operations import event_day_manifest as manifests
from weather.operations import workstation_restore_set as restore_set

TAPE = b"snapshot_id,range_label\ns1,60-61\n"
FILES = {"snapshots_long.csv": TAPE}
DAY = date(2026, 6, 15)


def _manifest(corpus, sha256=None):
    record = {"path": "snapshots_long.csv", "bytes": len(TAPE),
              "sha256": sha256 or hashlib.sha256(TAPE).hexdigest()}
    manifest = {"artifact_families": [{"name": "snapshots", "files": [record]}]}
    manifest["manifest_hash"] = manifests.manifest_content_hash(manifest)
    (corpus.day / manifests.MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")


def _archived(corpus, *, manifest=True):
    proof = recovery(corpus)  # Publishes the catalog entry and markers.
    if manifest:
        _manifest(corpus)
    (corpus.day / "snapshots_long.csv").unlink()
    return proof


def _steps(corpus, proof):
    def download(*, output_root, **_):
        output_root.mkdir()
        return shutil.copyfile(proof["transport_receipt"], output_root / "receipt.json")

    def restore(*, attempt, restore_id, **_):
        output = attempt / "restore" / restore_id
        member = output / "members" / "snapshots" / SLUG / "snapshots_long.csv"
        member.parent.mkdir(parents=True)
        member.write_bytes(TAPE)
        return shutil.copyfile(proof["restore_receipt"], output / "receipt.json"), output / "members"

    return restore_set.Steps(download=download, restore=restore)


def _plan(corpus, families=("snapshots",), start=DAY, end=DAY):
    return restore_set.plan_restore_set(data_root=corpus.root, start_date=start, end_date=end,
                                        families=families)


def _run(corpus, proof, **changes):
    args = dict(data_root=corpus.root, work_root=corpus.tmp / "work", set_id="set-a1",
                start_date=DAY, end_date=DAY, families=["snapshots"], steps=_steps(corpus, proof),
                admission=lambda: True, deadline_monotonic=time.monotonic() + 30,
                free_space_reserve_bytes=0)
    args.update(changes)
    (corpus.tmp / "work").mkdir(exist_ok=True)
    return restore_set.run_restore_set(**args)


@pytest.mark.parametrize("corpus", [FILES], indirect=True)
def test_restore_set_publishes_a_verified_cache_that_readers_resolve(corpus):
    proof = _archived(corpus)
    plan = _plan(corpus)
    assert [row["state"] for row in plan["members"]] == ["archived"]
    assert [row["archive_id"] for row in plan["archives"]] == ["catalog-fixture-a1"]
    with pytest.raises(locations.ArchivedInputRequired):
        locations.resolve_local_path(corpus.day / "snapshots_long.csv")
    result = _run(corpus, proof)
    assert (result["status"], result["verified_member_count"]) == ("RESTORED", 1)
    restored = locations.resolve_local_path(corpus.day / "snapshots_long.csv")
    assert "restore_cache" in restored.parts and restored.read_bytes() == TAPE
    assert json.loads((corpus.tmp / "work" / "set-a1" / "restore-set.json").read_text())["status"] == "RESTORED"
    assert [row["state"] for row in _plan(corpus)["members"]] == ["cached"]
    assert _plan(corpus)["archives"] == []


@pytest.mark.parametrize("corpus", [FILES], indirect=True)
def test_restore_set_refuses_a_hand_copied_original(corpus):
    _archived(corpus)
    (corpus.day / "snapshots_long.csv").write_bytes(TAPE)
    with pytest.raises(restore_set.RestoreSetRefused) as caught:
        _plan(corpus)
    assert caught.value.code == "hand_copied_original"


@pytest.mark.parametrize("corpus", [FILES], indirect=True)
def test_restore_set_refuses_a_member_that_differs_from_the_event_manifest(corpus):
    _archived(corpus)
    _manifest(corpus, sha256="0" * 64)
    with pytest.raises(restore_set.RestoreSetRefused) as caught:
        _plan(corpus)
    assert caught.value.code == "event_manifest_mismatch"


@pytest.mark.parametrize("corpus", [FILES], indirect=True)
def test_restore_set_refuses_without_an_event_manifest(corpus):
    _archived(corpus, manifest=False)
    with pytest.raises(restore_set.RestoreSetRefused) as caught:
        _plan(corpus)
    assert caught.value.code == "event_manifest_missing"


@pytest.mark.parametrize("corpus", [FILES], indirect=True)
def test_restore_set_selects_only_requested_dates_and_families(corpus):
    _archived(corpus)
    assert _plan(corpus, families=("features",))["members"] == []
    assert _plan(corpus, start=date(2026, 6, 16), end=date(2026, 6, 20))["members"] == []
    with pytest.raises(restore_set.RestoreSetRefused):
        _plan(corpus, families=("not-a-family",))


@pytest.mark.parametrize("corpus", [FILES], indirect=True)
def test_restore_set_work_root_must_be_outside_the_data_root(corpus):
    proof = _archived(corpus)
    with pytest.raises(restore_set.RestoreSetRefused) as caught:
        _run(corpus, proof, work_root=corpus.root)
    assert caught.value.code == "work_root_overlap"


@pytest.mark.parametrize("corpus", [FILES], indirect=True)
def test_restore_set_plan_cli_is_read_only(corpus, capsys):
    _archived(corpus)
    before = sorted(path for path in corpus.root.rglob("*"))
    assert restore_set.main(["plan", "--data-root", str(corpus.root), "--start-date", "2026-06-15",
                             "--end-date", "2026-06-15", "--family", "snapshots"]) == 0
    assert json.loads(capsys.readouterr().out)["restore_bytes"] == len(TAPE)
    assert sorted(path for path in corpus.root.rglob("*")) == before


@pytest.mark.parametrize("corpus", [FILES], indirect=True)
def test_restore_set_run_cli_requires_the_workstation_wrapper(corpus, capsys, monkeypatch):
    _archived(corpus)
    monkeypatch.delenv(restore_set.bridge.stage.WRAPPER_ENV, raising=False)
    args = ["run", "--data-root", str(corpus.root), "--start-date", "2026-06-15",
            "--end-date", "2026-06-15", "--family", "snapshots", "--work-root", str(corpus.tmp),
            "--set-id", "set-a1", "--rclone-executable", "x", "--rclone-config", "x",
            "--dpapi-secret", "x", "--drive-remote-name", "x", "--crypt-remote-name", "x",
            "--free-space-reserve-bytes", "0"]
    assert restore_set.main(args) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "workstation_wrapper_required"
    assert not (corpus.tmp / "set-a1").exists()
