import hashlib
import json
from pathlib import Path

import pytest

from weather.operations import cold_snapshot_nightly_resolution as resolution
from weather.paths import repo_path
from weather.schema_registry import schema_version

NAME = "nightly-20260930-apply-lowbudget-a1"
FOLDER = "snapshots/highest-temperature-in-nyc-on-september-1-2026"


def write(path, payload):
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")


def native(allocation, compressed, index):
    return {"size_bytes": 634880 if allocation > 4096 else 385, "allocation_bytes": allocation,
            "mtime_ns": 1, "volume_serial": 2, "file_index": index, "creation_filetime": 5,
            "attributes": 0x820 if compressed else 32, "compression_format": 2 if compressed else 0}


def attempt(tmp_path, *, finish_last=True):
    """The 2026-09-30 shape: a positive file, then a resident file with zero savings."""
    root = tmp_path.resolve()
    folder = root / "scratch" / "cold_snapshot_compression" / NAME
    batch = folder / "batch-0000"
    batch.mkdir(parents=True)
    write(folder / "wrapper-result.json", {"status": "FAILED", "teardown_proved": True, "hard_stop": False,
        "deleted_files": 0, "cleanup_eligible": False, "apply": True, "source_git_sha": "b" * 40,
        "request_sha256": "c" * 64, "execution_host_id": "d" * 64})
    write(folder / "result.json", {"schema_version": schema_version("cold_snapshot_nightly_receipt"),
        "status": "FAILED_RETAIN_AND_INSPECT", "source_git_sha": "b" * 40, "request_sha256": "c" * 64,
        "apply": True, "deleted_files": 0, "cleanup_eligible": False,
        "error": "no positive allocated-byte savings; stop before expanding"})
    paths = [FOLDER + "/clob_features.jsonl", FOLDER + "/replay_input_status.json"]
    write(batch / "selection.json", {"files": [{"path": p} for p in paths + [FOLDER + "/z.csv"]]})
    for ordinal, (path, before, after) in enumerate(zip(paths, (634880, 392), (159744, 392))):
        preimage = {"path": path, "before": native(before, False, ordinal), "sha256": f"{ordinal}" * 64,
                    "action": "COMPRESS_AND_RETAIN"}
        write(batch / f"{ordinal:03d}-before.json", preimage)
        if finish_last or ordinal == 0:
            write(batch / f"{ordinal:03d}-after.json", {**preimage, "after": native(after, True, ordinal),
                  "status": "VERIFIED", "reclaimed_bytes": before - after})
    return root, folder


def test_all_verified_failed_attempt_is_resolved_once_without_counting_savings(tmp_path):
    root, folder = attempt(tmp_path)
    record = resolution.resolve(root, NAME, "production agent")
    wrapper_sha = hashlib.sha256((folder / "wrapper-result.json").read_bytes()).hexdigest()
    assert record["status"] == "RESOLVED" and record["wrapper_result_sha256"] == wrapper_sha
    assert record["files_verified"] == 2 and record["verified_reclaimed_bytes"] == 634880 - 159744
    assert record["deleted_files"] == 0 and record["cleanup_eligible"] is False
    written = json.loads((folder.parent / "resolved-nightly" / f"{NAME}.json").read_text())
    assert written == record
    with pytest.raises(FileExistsError):
        resolution.resolve(root, NAME, "production agent")


def test_unfinished_file_is_not_resolved(tmp_path):
    root, folder = attempt(tmp_path, finish_last=False)
    with pytest.raises(ValueError, match="unfinished"):
        resolution.resolve(root, NAME, "production agent")
    assert not (folder.parent / "resolved-nightly").exists()


@pytest.mark.parametrize("change", [{"sha256": "f" * 64}, {"status": "FAILED"}])
def test_hash_or_status_disagreement_is_not_resolved(tmp_path, change):
    root, folder = attempt(tmp_path)
    path = folder / "batch-0000" / "001-after.json"
    write(path, {**json.loads(path.read_text()), **change})
    with pytest.raises(ValueError, match="not an equal-hash VERIFIED"):
        resolution.resolve(root, NAME, "production agent")


@pytest.mark.parametrize("change", [{"status": "PASS"}, {"teardown_proved": False}, {"hard_stop": True}])
def test_only_torn_down_failed_attempts_qualify(tmp_path, change):
    root, folder = attempt(tmp_path)
    path = folder / "wrapper-result.json"
    write(path, {**json.loads(path.read_text()), **change})
    with pytest.raises(ValueError, match="torn-down FAILED"):
        resolution.resolve(root, NAME, "production agent")


def test_scheduled_runner_accepts_only_a_resolution_bound_to_the_wrapper_hash():
    text = (repo_path() / "scripts/ops/cold_snapshot_nightly_run.ps1").read_text()
    for needle in ("resolved-nightly\\", "failed_attempt_resolution", "wrapper_result_sha256 -ceq $wrapperHash",
                   "Get-FileHash -LiteralPath $receiptPath", "Prior nightly attempt requires review"):
        assert needle in text
    assert resolution.ATTEMPT.fullmatch("resolved-nightly") is None
    assert not Path("resolved-nightly").match("nightly-*")
