from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pytest

from weather.operations import storage_recovery_batch_plan as subject
from weather.operations import cold_snapshot_compression as compression
from weather.schema_registry import schema_version

NOW = datetime(2026, 9, 9, 5, tzinfo=timezone.utc)
FOLDER = "snapshots/highest-temperature-in-toronto-on-july-1-2026"
SHA = "a" * 40


def context(root):
    return {"schema_version": schema_version("cold_snapshot_compression_request"),
            "production_repo_root": str(root), "approved_by": "fixture owner",
            "execution_host_id": "a" * 64, "operation": "compress_and_retain",
            "approved_at_utc": (NOW - timedelta(minutes=1)).isoformat(),
            "expires_at_utc": (NOW + timedelta(hours=1)).isoformat(),
            "inventory_wrapper_sha256": "b" * 64,
            "inventory_wrapper_receipt": str(root / "scratch/storage_recovery_inventory/one/wrapper-result.json")}


def manifest(count=40, size=64 * 1024**2):
    return {"folders": [{"path": FOLDER, "status": "COMPLETE"}],
            "files": [{"path": FOLDER + f"/{i:04d}.jsonl", "size_bytes": size,
                       "allocated_bytes": size, "attributes": 32, "device": "3", "file_id": str(i + 1),
                       "mtime_ns": str(int((NOW - timedelta(days=45)).timestamp()) * 10**9)}
                      for i in range(count)]}


def plan(root, data=None, **kwargs):
    return subject.prepare(data or manifest(), context(root), production_root=root, now=NOW, **kwargs)


def test_pilot_is_one_exact_file_and_reports_no_reclaimed_estimate(tmp_path):
    data = manifest()
    result = plan(tmp_path, data, mode="pilot")
    assert result["requests"][0]["files"] == data["files"][:1]
    assert result["selected_file_count"] == 1 and len(result["requests"]) == 1
    assert result["reclaimed_bytes"] == 0 and result["estimated_reclaimed_bytes"] is None
    assert result["cleanup_eligible"] is False


def test_expansion_is_bounded_deterministic_and_excludes_pilot(tmp_path):
    data = manifest()
    pilot = [data["files"][0]["path"]]
    first = plan(tmp_path, data, mode="expand", pilot_paths=pilot, max_batches=1)
    assert first == plan(tmp_path, data, mode="expand", pilot_paths=pilot, max_batches=1)
    assert first["selected_file_count"] == 16 and first["next_index"] == 16
    assert first["has_more"] is True
    second = plan(tmp_path, data, mode="expand", pilot_paths=pilot, start_index=first["next_index"])
    selected = [r for batch in first["requests"] + second["requests"] for r in batch["files"]]
    assert len(selected) == len({row["path"] for row in selected}) == 39
    assert pilot[0] not in {row["path"] for row in selected}
    assert second["has_more"] is False
    for payload in first["requests"] + second["requests"]:
        compression.validate_request(payload, production_root=tmp_path, now=NOW)


def test_file_count_bound_and_small_file_exclusion(tmp_path):
    data = manifest(300, size=1024**2)
    result = plan(tmp_path, data, mode="expand", pilot_paths=[data["files"][0]["path"]])
    assert len(result["requests"][0]["files"]) == 256
    data["files"][1]["size_bytes"] = 1024
    result = plan(tmp_path, data, mode="pilot")
    assert result["excluded_counts"]["under_one_MiB_planning_floor"] == 1


@pytest.mark.parametrize("kwargs", [
    {"mode": "invalid"}, {"mode": "expand"}, {"mode": "pilot", "start_index": 1},
    {"mode": "pilot", "max_batches": 9}, {"mode": "pilot", "max_batches": 0},
    {"mode": "pilot", "start_index": True},
])
def test_invalid_planning_scope_is_refused(tmp_path, kwargs):
    with pytest.raises(ValueError):
        plan(tmp_path, **kwargs)


def test_incomplete_already_compressed_and_hot_files_are_not_candidates(tmp_path):
    data = manifest(4)
    data["files"][0]["attributes"] |= 0x800
    data["files"][1]["mtime_ns"] = str(int(NOW.timestamp()) * 10**9)
    data["files"][2]["path"] = "snapshots/highest-temperature-in-toronto-on-september-1-2026/raw.json"
    result = plan(tmp_path, data, mode="pilot")
    assert result["selected_file_count"] == 1
    assert result["requests"][0]["files"][0] == data["files"][3]
    data["folders"][0]["status"] = "PARTIAL"
    with pytest.raises(ValueError, match="no eligible"):
        plan(tmp_path, data, mode="pilot")


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pilot_receipt(root, *, mutation=None, wrapper_mutation=None):
    path = root / "scratch/cold_snapshot_compression/pilot/wrapper-result.json"
    before = {"compression_format": 0, "allocation_bytes": 8192, "size_bytes": 6000,
              "mtime_ns": 123, "volume_serial": 3, "file_index": 4, "creation_filetime": 567}
    after = {**before, "compression_format": 2, "allocation_bytes": 4096}
    bound = {"status": "PASS", "apply": True, "source_git_sha": SHA, "request_sha256": "c" * 64,
             "execution_host_id": "a" * 64, "deleted_files": 0, "cleanup_eligible": False,
             "reclaimed_bytes": 4096}
    result = {**bound, "inventory_wrapper_sha256": "b" * 64,
              "results": [{"path": FOLDER + "/0000.jsonl", "status": "VERIFIED",
                           "action": "COMPRESS_AND_RETAIN", "sha256": "d" * 64,
                           "before": before, "after": after, "reclaimed_bytes": 4096}]}
    if mutation: mutation(result)
    digest = save(path.parent / "result.json", result)
    wrapper = {**bound, "teardown_proved": True, "hard_stop": False, "child_result_sha256": digest}
    if wrapper_mutation: wrapper_mutation(wrapper)
    return path, save(path, wrapper)


def read_pilot(root, path, digest):
    return subject.pilot_files(path, digest, production_root=root, source_git_sha=SHA, context=context(root))


def test_pilot_receipt_allows_only_verified_positive_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda path: nullcontext())
    path, digest = pilot_receipt(tmp_path)
    assert read_pilot(tmp_path, path, digest) == [FOLDER + "/0000.jsonl"]
    with pytest.raises(ValueError, match="hash"):
        read_pilot(tmp_path, path, "e" * 64)


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(apply=False), lambda r: r.update(inventory_wrapper_sha256="e" * 64),
    lambda r: r["results"][0].update(status="PLANNED"),
    lambda r: r["results"][0].update(reclaimed_bytes=0),
    lambda r: r["results"][0]["after"].update(mtime_ns=124),
    lambda r: r["results"][0]["after"].update(allocation_bytes=8192),
    lambda r: r["results"].append(dict(r["results"][0])),
])
def test_rehashed_bad_pilot_cannot_authorize_expansion(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda path: nullcontext())
    path, digest = pilot_receipt(tmp_path, mutation=mutation)
    with pytest.raises(ValueError):
        read_pilot(tmp_path, path, digest)


@pytest.mark.parametrize("mutation", [
    lambda w: w.update(teardown_proved=False), lambda w: w.update(hard_stop=True),
    lambda w: w.update(reclaimed_bytes=0), lambda w: w.update(source_git_sha="e" * 40),
])
def test_failed_or_unbound_wrapper_cannot_authorize_expansion(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda path: nullcontext())
    path, digest = pilot_receipt(tmp_path, wrapper_mutation=mutation)
    with pytest.raises(ValueError):
        read_pilot(tmp_path, path, digest)


def cli_fixture(root, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(subject, "datetime", Clock)
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda path: nullcontext())
    monkeypatch.setattr(compression, "PinnedNtfsDirectory", lambda path: nullcontext())
    output = root / "scratch/storage_recovery_plans/fixture"
    output.parent.mkdir(parents=True)
    ctx = context(root)
    path = Path(ctx["inventory_wrapper_receipt"])
    bound = {"status": "PASS", "source_git_sha": SHA, "request_sha256": "c" * 64,
             "execution_host_id": ctx["execution_host_id"], "cleanup_eligible": False}
    data = {**manifest(), **bound, "schema_version": schema_version("storage_recovery_inventory"),
            "data_root": str(root / "data")}
    manifest_hash = save(path.parent / "inventory.json", data)
    result_hash = save(path.parent / "result.json", {**bound, "inventory_sha256": manifest_hash})
    wrapper_hash = save(path, {**bound, "hard_stop": False, "teardown_proved": True,
                              "deleted_files": 0, "reclaimed_bytes": 0,
                              "child_result_sha256": result_hash})
    args = ["--production-repo-root", str(root), "--inventory-wrapper-receipt", str(path),
            "--inventory-wrapper-sha256", wrapper_hash, "--source-git-sha", SHA,
            "--execution-host-id", ctx["execution_host_id"], "--approved-by", "fixture owner",
            "--expires-at-utc", ctx["expires_at_utc"], "--output-root", str(output)]
    return args, output, path


def test_cli_creates_exact_requests_and_refuses_reuse(tmp_path, monkeypatch):
    args, output, _ = cli_fixture(tmp_path, monkeypatch)
    assert subject.main(args) == 0
    retained = (output / "plan.json").read_bytes()
    report = json.loads(retained)
    assert report["schema_version"] == schema_version("storage_recovery_batch_plan")
    assert report["selected_file_count"] == 1
    for row in report["requests"]:
        raw = Path(row["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
        payload = json.loads(raw)
        candidates = compression.validate_request(payload, production_root=tmp_path, now=NOW)
        assert candidates == manifest()["files"][:1]
        compression.read_inventory(payload, candidates, production_root=tmp_path, source_git_sha=SHA)
    assert subject.main(args) == 1
    assert (output / "plan.json").read_bytes() == retained


def test_cli_refuses_damaged_chain_without_creating_output(tmp_path, monkeypatch):
    args, output, path = cli_fixture(tmp_path, monkeypatch)
    (path.parent / "inventory.json").write_text("{}")
    assert subject.main(args) == 1
    assert not output.exists()
