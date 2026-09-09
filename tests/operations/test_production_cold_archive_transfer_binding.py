"""Production transfers must preserve the exact selected member inventory."""
from copy import deepcopy
import pytest
from weather.operations.production_cold_archive_transfer import validate_manifest_plan


@pytest.fixture
def planned_manifest():
    row = {"path": "snapshots/example/clob_tokens.jsonl", "size_bytes": 32,
           "mtime_ns": 42, "device": 7, "file_id": 18, "allocated_bytes": 4096}
    plan = {"plan_hash": "a" * 64, "source_root": "fixture/data"}
    chunk = {"chunk_id": "chunk-00000", "files": [row]}
    manifest = {**plan, "chunk_id": chunk["chunk_id"], "files": [{**row, "sha256": "b" * 64}]}
    return manifest, plan, chunk


def test_exact_selected_members_bind(planned_manifest):
    validate_manifest_plan(*planned_manifest)


@pytest.mark.parametrize("field", ["plan_hash", "source_root", "chunk_id", "path", "file_id", "size_bytes", "allocated_bytes"])
def test_matching_labels_cannot_hide_another_source(planned_manifest, field):
    manifest, plan, chunk = deepcopy(planned_manifest)
    if field in {"plan_hash", "source_root", "chunk_id"}:
        manifest[field] = "another"
    elif field == "path":
        manifest["files"][0][field] = "snapshots/another/clob_tokens.jsonl"
    else:
        manifest["files"][0][field] += 1
    with pytest.raises(ValueError):
        validate_manifest_plan(manifest, plan, chunk)


def test_extra_member_cannot_enter_transfer(planned_manifest):
    manifest, plan, chunk = deepcopy(planned_manifest)
    manifest["files"].append({**manifest["files"][0], "path": "snapshots/another/clob_tokens.jsonl"})
    with pytest.raises(ValueError):
        validate_manifest_plan(manifest, plan, chunk)
