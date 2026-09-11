"""Synthetic byte preservation, immutable attempts, and refusal behavior."""
from contextlib import nullcontext
import hashlib
import gzip
import json
import os
from pathlib import Path
import time

import pytest

from weather.operations import production_cold_archive_stage as stage


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _metadata(path):
    info = path.stat()
    return {"size_bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
            "device": info.st_dev, "file_id": info.st_ino,
            "allocated_bytes": info.st_size}


class FixturePin:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def metadata(self):
        return _metadata(self.path)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    # This seam replaces only Windows pins in deterministic cross-platform
    # fixtures. Production has no option or fallback enabling this behavior.
    monkeypatch.setattr(stage, "_source_pin", FixturePin)
    monkeypatch.setattr(stage, "_directory_pin", lambda path: nullcontext())
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.csv").write_bytes(b"a,b\n1,2\n" * 5)
    (source / "b.jsonl").write_bytes(b'{"value":3}\n' * 7)
    (source / "empty.csv").write_bytes(b"")
    files = [{"path": path.name, **_metadata(path)} for path in source.iterdir()]
    selection = {"schema_version": "large_archive_candidate_selection_v1",
                 "status": "MEASURED_CANDIDATE_NOT_DELETE_AUTHORITY",
                 "source_root": str(source), "files": files,
                 "file_count": len(files),
                 "logical_bytes": sum(row["size_bytes"] for row in files),
                 "allocated_bytes": sum(row["allocated_bytes"] for row in files)}
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    stage.plan_selection(selection_path, _sha(selection_path), plan_path)
    return tmp_path, source, selection_path, plan_path


def _run(corpus, name="attempt", **overrides):
    base, source, _, plan = corpus
    arguments = dict(source_root=source, admission=lambda: True,
                     deadline_monotonic=time.monotonic() + 30,
                     free_space_reserve_bytes=0)
    arguments.update(overrides)
    return stage.stage_chunk(plan, _sha(plan), "chunk-00000", base / name, **arguments)


def test_selective_grouping_keeps_market_day_and_family_independent():
    names = ["snapshots/market-a-2026-06-15/order_books_long.csv",
             "snapshots/market-a-2026-06-15/order_books_long.csv.gz",
             "snapshots/market-a-2026-06-15/price_history.csv",
             "snapshots/market-a-2026-06-16/price_history.csv",
             "snapshots/market-b-2026-06-15/price_history.csv"]
    rows = [{"path": name, "size_bytes": 10} for name in names]
    chunks = stage._chunks(rows, 100, stage.SELECTIVE_GROUPING)
    assert [[row["path"] for row in chunk["files"]] for chunk in chunks] == [
        names[:2], names[2:3], names[3:4], names[4:]]
    assert len(stage._chunks(rows, 100)) == 1
    assert len(stage._chunks(rows, 15, stage.SELECTIVE_GROUPING)) == len(rows)


@pytest.mark.parametrize("grouping,names", [
    ("unsupported", ["snapshots/market/file.csv"]),
    (stage.SELECTIVE_GROUPING, ["snapshots/file.csv"]),
    (stage.SELECTIVE_GROUPING, ["other/market/file.csv"]),
])
def test_selective_grouping_rejects_ambiguous_scope(grouping, names):
    with pytest.raises(stage.ArchiveStageError, match="grouping"):
        stage._chunks([{"path": name, "size_bytes": 1} for name in names], 10, grouping)


def test_selective_plan_binds_grouping_without_changing_legacy_bytes(corpus):
    base, _, selection_path, legacy = corpus
    legacy_value = json.loads(legacy.read_text())
    assert "chunk_grouping" not in legacy_value
    selection = json.loads(selection_path.read_text())
    for row in selection["files"]:
        row["path"] = "snapshots/market-2026-06-15/" + row["path"]
    selection_path.write_text(json.dumps(selection))
    first, second = base / "grouped-one.json", base / "grouped-two.json"
    for output in (first, second):
        stage.plan_selection(selection_path, _sha(selection_path), output,
                             chunk_grouping=stage.SELECTIVE_GROUPING)
    assert first.read_bytes() == second.read_bytes()
    value = json.loads(first.read_text())
    assert value["chunk_grouping"] == stage.SELECTIVE_GROUPING
    assert len(value["chunks"]) == 3
    stage._check_seal(value, "plan_hash")



def test_market_day_grouping_retains_families_and_never_crosses_days():
    rows = [
        {"path": "snapshots/day-a/clob_tokens.jsonl", "size_bytes": 2},
        {"path": "snapshots/day-a/market_ws.jsonl", "size_bytes": 3},
        {"path": "snapshots/day-a/order_books_long.csv.gz", "size_bytes": 4},
        {"path": "snapshots/day-b/clob_tokens.jsonl", "size_bytes": 1},
    ]
    grouped = stage._chunks(rows, 20, stage.MARKET_DAY_GROUPING)
    assert [[row["path"] for row in chunk["files"]] for chunk in grouped] == [
        [row["path"] for row in rows[:3]], [rows[3]["path"]]]
    assert [chunk["logical_bytes"] for chunk in grouped] == [9, 1]
    assert [len(chunk["files"]) for chunk in stage._chunks(rows, 5, stage.MARKET_DAY_GROUPING)] == [2, 1, 1]
    assert len(stage._chunks(rows, 20, stage.SELECTIVE_GROUPING)) == 4
    with pytest.raises(stage.ArchiveStageError, match="snapshots/event/file"):
        stage._chunks([{"path": "elsewhere/file", "size_bytes": 1}], 10, stage.MARKET_DAY_GROUPING)


def test_partitioned_grouping_packs_ordinary_days_and_isolates_protected_days():
    rows = [{"path": f"snapshots/{event}/{name}", "size_bytes": size}
            for event, name, size in [
                ("day-a", "market_ws.jsonl", 2), ("day-b", "order_books_long.csv", 3),
                ("day-b", "order_books_long.csv.gz", 4),
                ("day-c", "clob_tokens.jsonl", 1), ("day-c", "market_ws.jsonl", 1),
                ("day-d", "clob_tokens.jsonl", 2), ("day-e", "market_ws.jsonl", 3)]]
    chunks = stage._chunks(rows, 20, stage.PARTITIONED_GROUPING, ["day-c"])
    assert [c["files"] for c in chunks] == [rows[:3], rows[3:5], rows[5:]]
    assert [c["logical_bytes"] for c in chunks] == [9, 2, 5]
    assert [r for c in chunks for r in c["files"]] == rows
    small = stage._chunks(rows, 5, stage.PARTITIONED_GROUPING, ["day-c"])
    assert all(c["logical_bytes"] <= 5 for c in small)
    many = [{"path": f"snapshots/day-{i:04d}/market_ws.jsonl", "size_bytes": 1}
            for i in range(257)]
    assert [len(c["files"]) for c in stage._chunks(many, 1024, stage.PARTITIONED_GROUPING)] == [256, 1]


@pytest.mark.parametrize("events", [["day-b", "day-a"], ["day-a", "day-a"],
                                   ["../day"], ["DAY"], [False], "day-a", ["a"] * 257])
def test_partitioned_grouping_refuses_invalid_isolation(events):
    with pytest.raises(stage.ArchiveStageError, match="isolated"):
        stage._chunks([], 10, stage.PARTITIONED_GROUPING, events)


def test_partitioned_plan_binds_isolation_and_rechecks_resealed_changes(corpus):
    base, _, selection_path, _ = corpus
    selection = json.loads(selection_path.read_text())
    for i, row in enumerate(selection["files"]):
        row["path"] = f"snapshots/day-{i}/" + row["path"]
    selection_path.write_text(json.dumps(selection))
    plan = base / "partitioned.json"
    value = stage.plan_selection(selection_path, _sha(selection_path), plan,
                                 chunk_grouping=stage.PARTITIONED_GROUPING,
                                 isolated_events=["day-1"])
    assert value["isolated_events"] == ["day-1"]
    assert len(value["chunks"]) == 3
    stage._check_seal(value, "plan_hash")
    value.pop("plan_hash")
    value["isolated_events"] = []
    plan.write_text(json.dumps(stage._seal(value, "plan_hash")))
    with pytest.raises(stage.ArchiveStageError, match="inventory"):
        _run((*corpus[:3], plan))
    assert not (base / "attempt").exists()
    with pytest.raises(stage.ArchiveStageError, match="isolated"):
        stage.plan_selection(selection_path, _sha(selection_path), base / "bad-isolation.json",
                             isolated_events=["day-1"])


def test_stage_rejects_resealed_unknown_grouping(corpus):
    _, _, _, plan = corpus
    value = json.loads(plan.read_text())
    value.pop("plan_hash")
    value["chunk_grouping"] = "unsupported"
    plan.write_text(json.dumps(stage._seal(value, "plan_hash")))
    with pytest.raises(stage.ArchiveStageError, match="grouping"):
        _run(corpus)
    assert not (corpus[0] / "attempt").exists()


def test_repeat_staging_is_byte_identical_and_proves_every_source(corpus):
    base, source, _, _ = corpus
    first = _run(corpus, "one")
    second = _run(corpus, "two")
    assert first["status"] == second["status"] == "PASS"
    assert _sha(base / "one/archive.tar.gz") == _sha(base / "two/archive.tar.gz")
    manifest = json.loads((base / "one/manifest.json").read_text())
    for row in manifest["files"]:
        assert row["sha256"] == _sha(source / row["path"])
    assert first["source_retained"] is True
    assert first["cleanup_eligible"] is first["deletion_authorized"] is False
    assert manifest["consumer_closure_proved"] is False
    assert manifest["source_proof"] == "native_pinned_bytes_during_staging"


def test_measured_metadata_has_no_content_authority_and_plan_is_deterministic(corpus):
    base, _, selection, plan = corpus
    before = plan.read_bytes()
    stage.plan_selection(selection, _sha(selection), base / "second-plan.json")
    assert before == (base / "second-plan.json").read_bytes()
    value = json.loads(before)
    assert value["source_content_hashes_proved"] is False
    assert all("sha256" not in row for chunk in value["chunks"] for row in chunk["files"])
    with pytest.raises(stage.ArchiveStageError, match="SHA-256"):
        stage.plan_selection(selection, "0" * 64, base / "wrong.json")
    assert not (base / "wrong.json").exists()


@pytest.mark.parametrize("change", ["path", "case_collision", "oversized", "totals"])
def test_plan_rejects_unsafe_or_unreconciled_selection(corpus, change):
    base, _, selection_path, _ = corpus
    selection = json.loads(selection_path.read_text())
    if change == "path":
        selection["files"][0]["path"] = "../outside.csv"
    elif change == "case_collision":
        selection["files"][1]["path"] = selection["files"][0]["path"].upper()
    elif change == "oversized":
        selection["files"][0]["size_bytes"] = stage.MAX_CHUNK_BYTES + 1
    else:
        selection["logical_bytes"] += 1
    selection_path.write_text(json.dumps(selection))
    with pytest.raises(stage.ArchiveStageError):
        stage.plan_selection(selection_path, _sha(selection_path), base / "bad-plan.json")


def test_chunking_whole_files_obeys_member_and_byte_bounds():
    rows = [{"path": f"{i:04d}.csv", "size_bytes": 1} for i in range(257)]
    chunks = stage._chunks(rows, 1024)
    assert [len(chunk["files"]) for chunk in chunks] == [256, 1]
    assert [chunk["chunk_id"] for chunk in chunks] == ["chunk-00000", "chunk-00001"]
    assert [chunk["logical_bytes"] for chunk in stage._chunks(rows[:5], 2)] == [2, 2, 1]
    with pytest.raises(stage.ArchiveStageError, match="whole source"):
        stage._chunks([{"path": "big.csv", "size_bytes": 4}], 3)


def test_source_drift_retains_failed_attempt_and_refuses_reuse(corpus):
    base, source, _, _ = corpus
    (source / "a.csv").write_bytes(b"replaced")
    with pytest.raises(stage.ArchiveStageError, match="metadata"):
        _run(corpus)
    attempt = base / "attempt"
    original = {path.name: path.read_bytes() for path in attempt.iterdir()}
    receipt = json.loads(original["receipt.json"])
    assert receipt["status"] == "FAIL_CLOSED"
    assert "archive.tar.gz" not in original
    assert "source metadata differs before staging: a.csv" == receipt["error_message"]
    with pytest.raises(FileExistsError):
        _run(corpus)
    assert original == {path.name: path.read_bytes() for path in attempt.iterdir()}


def test_identity_change_after_read_refuses_pass(corpus, monkeypatch):
    class DriftingPin(FixturePin):
        calls = 0

        def metadata(self):
            result = super().metadata()
            self.calls += 1
            if self.calls > 1:
                result["file_id"] += 1
            return result

    monkeypatch.setattr(stage, "_source_pin", DriftingPin)
    with pytest.raises(stage.ArchiveStageError, match="identity drift"):
        _run(corpus)
    assert not (corpus[0] / "attempt/manifest.json").exists()


def test_admission_and_expired_deadline_prevent_claim(corpus):
    with pytest.raises(stage.ArchiveStageError, match="admission"):
        _run(corpus, admission=lambda: False)
    with pytest.raises(stage.ArchiveStageError, match="deadline"):
        _run(corpus, deadline_monotonic=time.monotonic() - 1)
    assert not (corpus[0] / "attempt").exists()


def test_mid_attempt_admission_loss_is_terminal_and_retains_partial(corpus):
    archive_path = corpus[0] / "attempt/archive.tar.gz"

    def admission():
        return not (archive_path.exists() and archive_path.stat().st_size > 0)

    with pytest.raises(stage.ArchiveStageError, match="admission"):
        _run(corpus, admission=admission)
    value = json.loads((corpus[0] / "attempt/receipt.json").read_text())
    assert value["status"] == "FAIL_CLOSED"
    assert (corpus[0] / "attempt/archive.tar.gz").exists()


def test_disk_reserve_refuses_before_any_output(corpus, monkeypatch):
    usage = stage.shutil.disk_usage(corpus[0])
    monkeypatch.setattr(stage.shutil, "disk_usage", lambda path: type(usage)(10, 9, 1))
    with pytest.raises(stage.ArchiveStageError, match="insufficient disk"):
        _run(corpus, free_space_reserve_bytes=1)
    assert not (corpus[0] / "attempt").exists()


def test_output_writer_has_hard_cap_and_preserves_existing_bytes(tmp_path):
    guard = stage._Guard(lambda: True, time.monotonic() + 30, stage.MIB)
    path = tmp_path / "partial"
    with path.open("xb") as stream:
        writer = stage._Writer(stream, guard, 3, tmp_path, 0)
        writer.write(b"abc")
        with pytest.raises(stage.ArchiveStageError, match="worst-case cap"):
            writer.write(b"d")
    assert path.read_bytes() == b"abc"
    assert writer.bytes == 3
    assert writer.digest.hexdigest() == hashlib.sha256(b"abc").hexdigest()


def test_verifier_rejects_changed_object_and_forged_member_hash(corpus):
    base, _, _, _ = corpus
    _run(corpus)
    archive = base / "attempt/archive.tar.gz"
    manifest = json.loads((base / "attempt/manifest.json").read_text())
    altered = dict(manifest)
    altered["files"] = [dict(row) for row in manifest["files"]]
    altered["files"][0]["sha256"] = "0" * 64
    altered.pop("manifest_hash")
    stage._seal(altered, "manifest_hash")
    with pytest.raises(stage.ArchiveStageError, match="member content"):
        stage.verify_archive(archive, altered, admission=lambda: True,
                             deadline_monotonic=time.monotonic() + 30)
    with archive.open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(stage.ArchiveStageError, match="object hash"):
        stage.verify_archive(archive, manifest, admission=lambda: True,
                             deadline_monotonic=time.monotonic() + 30)


@pytest.mark.skipif(os.name != "nt", reason="native Windows sharing contract")
def test_native_pin_rejects_existing_writer_and_preserves_bytes(tmp_path):
    path = tmp_path / "native.csv"
    path.write_bytes(b"native fixture")
    with path.open("r+b"):
        with pytest.raises(OSError):
            with stage._source_pin(path):
                pytest.fail("writer exclusion was not enforced")
    with stage._source_pin(path) as pin:
        before = pin.metadata()
        assert before["size_bytes"] == len(b"native fixture")
        with pytest.raises(OSError):
            path.open("r+b")
        assert pin.metadata() == before
    assert path.read_bytes() == b"native fixture"


@pytest.mark.skipif(os.name == "nt", reason="POSIX must not claim native Windows proof")
def test_production_source_pin_has_no_portable_fallback(tmp_path):
    path = tmp_path / "source.csv"
    path.write_bytes(b"data")
    with pytest.raises(OSError, match="native Windows"):
        stage._source_pin(path)



def test_verifier_rejects_hidden_payload_after_tar_footer(corpus):
    base, _, _, _ = corpus
    _run(corpus)
    archive = base / "attempt/archive.tar.gz"
    manifest = json.loads((base / "attempt/manifest.json").read_text())
    hidden = gzip.decompress(archive.read_bytes()) + b"hidden payload"
    archive.write_bytes(gzip.compress(hidden, compresslevel=1, mtime=0))
    manifest["archive_bytes"] = archive.stat().st_size
    manifest["archive_sha256"] = _sha(archive)
    manifest.pop("manifest_hash")
    stage._seal(manifest, "manifest_hash")
    with pytest.raises(stage.ArchiveStageError, match="footer or trailing"):
        stage.verify_archive(archive, manifest, admission=lambda: True,
                             deadline_monotonic=time.monotonic() + 30)


def test_deadline_during_read_retains_failed_attempt(corpus, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(stage.time, "monotonic", lambda: clock[0])
    original = stage._Reader.read

    def expire_before_read(self, size=-1):
        clock[0] = 11.0
        return original(self, size)

    monkeypatch.setattr(stage._Reader, "read", expire_before_read)
    with pytest.raises(stage.ArchiveStageError, match="deadline"):
        _run(corpus, deadline_monotonic=10.0)
    receipt = json.loads((corpus[0] / "attempt/receipt.json").read_text())
    assert receipt["status"] == "FAIL_CLOSED"
    assert (corpus[0] / "attempt/archive.tar.gz").exists()


def test_selected_symlink_is_not_read(corpus):
    base, source, _, _ = corpus
    selected = source / "a.csv"
    outside = base / "outside.csv"
    outside.write_bytes(selected.read_bytes())
    selected.unlink()
    try:
        selected.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable in this fixture session")
    with pytest.raises(stage.ArchiveStageError, match="links and reparse"):
        _run(corpus)
    assert outside.read_bytes() == b"a,b\n1,2\n" * 5


def test_explicit_missing_hash_binding_is_refused(corpus):
    base, _, selection, _ = corpus
    with pytest.raises(stage.ArchiveStageError, match="explicit lowercase SHA"):
        stage.plan_selection(selection, None, base / "unbound.json")
    assert not (base / "unbound.json").exists()


@pytest.mark.parametrize("character", ["\\x00", "\\x01", "\\n", "\\r", "\\t", "\\x7f", "\\x85"])
def test_source_paths_reject_embedded_controls(character):
    character = bytes(character, "ascii").decode("unicode_escape")
    with pytest.raises(stage.ArchiveStageError, match="control characters"):
        stage._relative("snapshots/event/file" + character + ".csv")


def test_writer_digest_avoids_redundant_full_archive_read(corpus, monkeypatch):
    original = stage._hash
    hashed_paths = []

    def observed_hash(path, guard):
        hashed_paths.append(Path(path))
        return original(path, guard)

    monkeypatch.setattr(stage, "_hash", observed_hash)
    _run(corpus)
    assert hashed_paths == []
    manifest = json.loads((corpus[0] / "attempt/manifest.json").read_text())
    assert manifest["archive_sha256"] == _sha(corpus[0] / "attempt/archive.tar.gz")


def test_verify_streams_one_disk_pass_and_checks_archive_digest(corpus):
    base, _, _, _ = corpus
    _run(corpus)
    path = base / "attempt/archive.tar.gz"
    manifest = json.loads((base / "attempt/manifest.json").read_text())
    guards = []
    class CountingGuard(stage._Guard):
        def __init__(self, admission, deadline):
            super().__init__(admission, deadline, 16 * stage.MIB)
            guards.append(self)
    stage.verify_archive(path, manifest, admission=lambda: True,
                         deadline_monotonic=time.monotonic() + 30, guard_factory=CountingGuard)
    assert guards[0].bytes == path.stat().st_size
    manifest["archive_sha256"] = "0" * 64
    manifest.pop("manifest_hash")
    stage._seal(manifest, "manifest_hash")
    with pytest.raises(stage.ArchiveStageError, match="object hash"):
        stage.verify_archive(path, manifest, admission=lambda: True,
                             deadline_monotonic=time.monotonic() + 30)


def test_stage_records_lower_allocation_without_changing_approved_scope(corpus, monkeypatch):
    class CompressedPin(FixturePin):
        def metadata(self):
            value = super().metadata()
            value["allocated_bytes"] //= 2
            return value
    monkeypatch.setattr(stage, "_source_pin", CompressedPin)
    _run(corpus)
    manifest = json.loads((corpus[0] / "attempt/manifest.json").read_text())
    plan = json.loads(corpus[3].read_text())
    assert stage._matches_staged_rows(plan["chunks"][0]["files"], manifest["files"])
    for row in manifest["files"]:
        assert row["allocated_bytes"] == row["size_bytes"] // 2
        assert row["sha256"] == _sha(corpus[1] / row["path"])


@pytest.mark.parametrize("field", ["file_id", "device", "mtime_ns", "size_bytes", "allocated_bytes"])
def test_stage_still_refuses_changed_identity_or_larger_allocation(corpus, monkeypatch, field):
    class ChangedPin(FixturePin):
        def metadata(self):
            value = super().metadata()
            value[field] += 1
            return value
    monkeypatch.setattr(stage, "_source_pin", ChangedPin)
    with pytest.raises(stage.ArchiveStageError, match="metadata"):
        _run(corpus)
    assert not (corpus[0] / "attempt/archive.tar.gz").exists()
