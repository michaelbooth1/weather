"""Storage recovery inventory is metadata evidence, never deletion authority."""
from datetime import date
import os
from pathlib import Path

import pytest

from weather.operations import storage_recovery_inventory as subject

AS_OF = date(2026, 9, 8)
SLUG = "highest-temperature-in-atlanta-on-july-1-2026"
FOLDER = "snapshots/" + SLUG


def setup_folder(tmp_path):
    root = tmp_path / "data"
    folder = root / FOLDER
    folder.mkdir(parents=True)
    (folder / "snapshots.jsonl").write_bytes(b'{"value":1}\n' * 100)
    return root, folder


def run(root, folders=None, **kwargs):
    return subject.inventory(root, folders or [FOLDER], as_of=AS_OF,
                             guard=kwargs.pop("guard", lambda: None),
                             allocation=kwargs.pop("allocation", lambda p, s: 4096),
                             **kwargs)


def test_reports_allocated_and_logical_bytes_separately_without_reclaim(tmp_path):
    root, folder = setup_folder(tmp_path)
    result = run(root)
    assert result["status"] == "PASS"
    assert result["complete_folder_allocated_bytes"] == 4096
    assert result["complete_folder_logical_bytes"] == (folder / "snapshots.jsonl").stat().st_size
    assert result["cleanup_eligible"] is False
    assert result["reclaimed_bytes"] == result["deleted_files"] == 0
    assert result["payload_bytes_read"] == result["source_files_changed"] == 0
    assert result["files"][0]["path"] == FOLDER + "/snapshots.jsonl"


def test_never_opens_payload_contents(tmp_path, monkeypatch):
    root, _ = setup_folder(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("payload open")
    monkeypatch.setattr(Path, "open", forbidden)
    assert run(root)["status"] == "PASS"


@pytest.mark.parametrize("folder", [
    "../data", "/snapshots/event", "snapshots/../backtest",
    "snapshots/" + SLUG + "/../other", "snapshots//" + SLUG,
    "snapshots\\" + SLUG, "snapshots/" + SLUG + ":stream",
    "snapshots/highest-temperature-in-atlantis-on-july-1-2026",
    "snapshots/highest-temperature-in-atlanta-on-february-30-2026",
    "snapshots/highest-temperature-in-atlanta-on-august-9-2026",
    "snapshots/highest-temperature-in-atlanta-on-september-8-2026",
    "forecast_payload_cas", "settlements", "backtest/unclassified",
])
def test_rejects_paths_outside_exact_cold_folder_contract(tmp_path, folder):
    root, _ = setup_folder(tmp_path)
    with pytest.raises(subject.InventoryRefused):
        run(root, [folder])


def test_rejects_duplicate_and_oversized_folder_requests():
    with pytest.raises(subject.InventoryRefused, match="duplicate"):
        subject.validate_folders([FOLDER, FOLDER], as_of=AS_OF)
    with pytest.raises(subject.InventoryRefused, match="twelve"):
        subject.validate_folders([FOLDER] * 13, as_of=AS_OF)


def test_root_must_be_absolute(tmp_path):
    with pytest.raises(subject.InventoryRefused, match="absolute"):
        subject.validate_root(Path("relative"))


def test_backtest_root_does_not_double_count_cache(tmp_path):
    root = tmp_path / "data"
    (root / "backtest/replay_cache" / SLUG).mkdir(parents=True)
    (root / "backtest/report.csv").write_bytes(b"row\n")
    (root / "backtest/replay_cache" / SLUG / "cache.json").write_bytes(b"{}\n")
    result = run(root, ["backtest", "backtest/replay_cache/" + SLUG])
    assert result["status"] == "PASS"
    assert [r["files"] for r in result["folders"]] == [1, 1]
    assert result["complete_folder_allocated_bytes"] == 8192


def test_nested_payload_metadata_is_included(tmp_path):
    root, folder = setup_folder(tmp_path)
    (folder / "forecast_payloads/raw").mkdir(parents=True)
    (folder / "forecast_payloads/raw/blob.json").write_bytes(b"{}\n")
    result = run(root)
    assert result["status"] == "PASS"
    assert result["folders"][0]["files"] == 2
    assert result["complete_folder_allocated_bytes"] == 8192


def test_hardlinks_block_entire_folder_budget(tmp_path):
    root, folder = setup_folder(tmp_path)
    os.link(folder / "snapshots.jsonl", folder / "second.jsonl")
    result = run(root)
    assert result["status"] == "PARTIAL"
    assert result["folders"][0]["status"] == "BLOCK"
    assert result["complete_folder_allocated_bytes"] == 0


def test_reparse_or_symlink_is_never_followed(tmp_path):
    root, folder = setup_folder(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"private")
    try:
        (folder / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    result = run(root)
    assert result["folders"][0]["status"] == "BLOCK"
    assert not any("secret" in r["path"] for r in result["files"])
    assert result["complete_folder_allocated_bytes"] == 0


def test_changed_file_blocks_capacity_claim(tmp_path):
    root, folder = setup_folder(tmp_path)
    def changing(path, expected):
        path.write_bytes(b"replacement with a different size")
        return 4096
    result = run(root, allocation=changing)
    assert result["folders"][0]["status"] == "BLOCK"
    assert "file_metadata_changed" in result["folders"][0]["reason"]
    assert result["complete_folder_allocated_bytes"] == 0


@pytest.mark.parametrize("limits,expected", [
    (subject.Limits(entries=1), "entry_count_limit"),
    (subject.Limits(directory_entries=1), "directory_entry_limit"),
    (subject.Limits(output_bytes=1), "output_byte_limit"),
])
def test_bounds_are_partial_and_do_not_supply_a_capacity_budget(tmp_path, limits, expected):
    root, folder = setup_folder(tmp_path)
    (folder / "another.json").write_bytes(b"{}\n")
    result = run(root, limits=limits)
    assert result["status"] == "PARTIAL"
    assert result["stop_reasons"][0]["reason"] == expected
    assert result["complete_folder_allocated_bytes"] == 0
    assert result["reclaimed_bytes"] == 0


def test_time_bound_is_enforced_before_directory_scan(tmp_path):
    root, _ = setup_folder(tmp_path)
    ticks = iter([0.0, 2.0, 2.0])
    result = run(root, limits=subject.Limits(seconds=1), clock=lambda: next(ticks))
    assert result["stop_reasons"][0]["reason"] == "elapsed_seconds_limit"
    assert result["entries_observed"] == 0


def test_guard_refusal_stops_without_inventory(tmp_path):
    root, _ = setup_folder(tmp_path)
    def refused():
        raise RuntimeError("capture admission")
    with pytest.raises(RuntimeError, match="capture admission"):
        run(root, guard=refused)


@pytest.mark.parametrize("limits", [
    subject.Limits(entries=subject.MAX_ENTRIES + 1),
    subject.Limits(directory_entries=0),
    subject.Limits(seconds=float("nan")),
    subject.Limits(seconds=subject.MAX_SECONDS + 1),
    subject.Limits(entries=True),
])
def test_limits_cannot_be_relaxed(tmp_path, limits):
    root, _ = setup_folder(tmp_path)
    with pytest.raises(subject.InventoryRefused):
        run(root, limits=limits)


@pytest.mark.skipif(os.name != "nt", reason="native NTFS allocation")
def test_native_allocation_and_identity_match(tmp_path):
    root, folder = setup_folder(tmp_path)
    result = run(root, allocation=subject.native_allocation)
    assert result["status"] == "PASS"
    row = result["files"][0]
    assert row["allocated_bytes"] >= row["size_bytes"]
    assert row["allocated_bytes"] % 4096 == 0
    assert int(row["file_id"]) == (folder / "snapshots.jsonl").stat().st_ino


@pytest.mark.skipif(os.name != "nt", reason="native NTFS allocation")
def test_native_allocation_rejects_different_file_identity(tmp_path):
    _, folder = setup_folder(tmp_path)
    other = folder / "other.jsonl"
    other.write_bytes(b"{}\n")
    with pytest.raises(subject.InventoryRefused, match="identity"):
        subject.native_allocation(other, (folder / "snapshots.jsonl").stat())
