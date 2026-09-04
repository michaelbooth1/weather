from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

import weather.operations.verified_cold_archive as cold
from weather.operations.event_day_manifest import write_event_day_manifest


TOOL_IDENTITY = {
    "tool": cold.TOOL,
    "archive_format": cold.ARCHIVE_FORMAT,
    "git_commit": "a" * 40,
    "git_tree": "b" * 40,
    "git_branch": "fixture-test",
    "git_dirty": False,
}
SLUG = "highest-temperature-in-nyc-on-june-22-2026"


def _write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _payload_evidence(
    folder: Path,
    family: str,
    payload: dict,
    *,
    snapshot_id: str,
    source: str,
) -> dict:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    blob = folder / family / "sha256" / digest[:2] / f"{digest}.json"
    _write(blob, canonical + b"\n")
    return {
        "schema_version": f"{family}_manifest_v1",
        "snapshot_id": snapshot_id,
        "source": source,
        "payload_hash_algorithm": "sha256-canonical-json",
        "payload_hash": digest,
        "payload_bytes": len(canonical),
        "raw_payload_retained": True,
        "raw_payload_path": str(blob),
    }


def _identity(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _make_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    fixture = tmp_path / "vca-x"
    fixture.mkdir()
    _write(
        fixture / cold.FIXTURE_MARKER,
        json.dumps(
            {
                "allow_real_data": False,
                "purpose": cold.FIXTURE_MARKER_PURPOSE,
            }
        ),
    )
    folder = fixture / "snapshots" / SLUG
    _write(
        folder / "snapshots.jsonl",
        json.dumps(
            {
                "schema_version": "snapshot_tape_v0.1",
                "snapshot_id": "s1",
                "release_id": "release-test",
                "runtime_identity": {
                    "schema_version": "runtime_identity_v0.1",
                    "git_branch": "fixture",
                    "git_commit": "c" * 40,
                    "source_fingerprint": "fixture-source-v1",
                },
            }
        )
        + "\n",
    )
    forecast = _payload_evidence(
        folder,
        "forecast_payloads",
        {"forecast": [92, 94], "provider": "fixture"},
        snapshot_id="s1",
        source="fixture_forecast",
    )
    _write(folder / "forecast_payloads.jsonl", json.dumps(forecast) + "\n")
    observation = _payload_evidence(
        folder,
        "observation_payloads",
        {"station_id": "KAUS", "temperature": 94},
        snapshot_id="s1",
        source="fixture_observation",
    )
    _write(folder / "observation_payloads.jsonl", json.dumps(observation) + "\n")
    _write(
        folder / "source_status.jsonl",
        json.dumps(
            {
                "schema_version": "source_status_v0.1",
                "snapshot_id": "s1",
                "source": "fixture",
                "status": "OK",
            }
        )
        + "\n",
    )
    _write(
        folder / "replay_inputs.jsonl",
        json.dumps({"snapshot_id": "s1", "sources": {"fixture": {"temp": 94}}})
        + "\n",
    )
    _write(
        folder / "clob_capture_status.jsonl",
        json.dumps({"schema_version": "clob_capture_status_v0.1", "status": "OK"})
        + "\n",
    )
    _write(folder / "order_books.jsonl", '{"token_id":"t1","bid":0.5}\n')
    _write(
        folder / "settlement.json",
        json.dumps(
            {
                "event_slug": SLUG,
                "market_id": "nyc",
                "target_date": "2026-06-22",
                "settlement_bucket": 94,
                "settlement_source": "fixture",
                "quality_grade": "complete",
            }
        ),
    )
    write_event_day_manifest(folder, snapshots_root=fixture / "snapshots")

    evidence_dir = fixture / "selection-evidence"
    evidence: dict[str, Path] = {}
    for name in cold.REQUIRED_SELECTION_CHECKS:
        evidence[name] = _write(
            evidence_dir / f"{name}.json",
            json.dumps({"check": name, "source": "synthetic fixture"}),
        )
    event_manifest = json.loads(
        (folder / "event_day_manifest.json").read_text(encoding="utf-8")
    )
    checks = [
        {
            "check": "market_day_closed",
            "status": "PASS",
            "closed": True,
            "evidence": [_identity(evidence["market_day_closed"], fixture)],
        },
        {
            "check": "settlement_final",
            "status": "PASS",
            "settled": True,
            "settlement_state": "settled_countable",
            "evidence": [_identity(evidence["settlement_final"], fixture)],
        },
        {
            "check": "barriers_clear",
            "status": "PASS",
            "open_references": [],
            "evidence": [_identity(evidence["barriers_clear"], fixture)],
        },
        {
            "check": "queues_clear",
            "status": "PASS",
            "open_references": [],
            "evidence": [_identity(evidence["queues_clear"], fixture)],
        },
        {
            "check": "point_in_time_windows_clear",
            "status": "PASS",
            "open_references": [],
            "evidence": [
                _identity(evidence["point_in_time_windows_clear"], fixture)
            ],
        },
    ]
    proof = {
        "schema_version": cold.SELECTION_PROOF_SCHEMA_VERSION,
        "proof_hash": "",
        "source": {
            "source_folder": f"snapshots/{SLUG}",
            "event_slug": SLUG,
            "target_date": "2026-06-22",
            "event_day_manifest_hash": event_manifest["manifest_hash"],
        },
        "checks": checks,
    }
    proof["proof_hash"] = cold.selection_proof_content_hash(proof)
    proof_path = _write(
        fixture / "review" / "selection-proof.json",
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
    )
    return fixture, folder, proof_path


def _plan(fixture: Path, folder: Path, proof: Path, **kwargs) -> dict:
    return cold.plan_market_day(
        fixture_root=fixture,
        source_folder=folder,
        selection_proof=proof,
        as_of_date=kwargs.pop("as_of_date", "2026-08-01"),
        hot_window_days=kwargs.pop("hot_window_days", 30),
        tool_identity=TOOL_IDENTITY,
        **kwargs,
    )


def _build(
    fixture: Path, plan: dict, destination_name: str = "archive"
) -> tuple[Path, Path, dict]:
    destination = fixture / destination_name
    destination.mkdir()
    result = cold.build_archive(
        fixture_root=fixture,
        plan=plan,
        destination_root=destination,
        tool_identity=TOOL_IDENTITY,
    )
    return destination, Path(result["manifest_path"]), result


def _rewrite_manifest_for_archive(manifest_path: Path, archive_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["archive"]["bytes"] = archive_path.stat().st_size
    manifest["archive"]["sha256"] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    manifest["manifest_hash"] = cold.manifest_content_hash(manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _replace_tar(archive_path: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> None:
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for info, payload in members:
                    info.size = len(payload)
                    info.mtime = 0
                    tar.addfile(info, io.BytesIO(payload))


def test_plan_and_object_are_deterministic_and_manifest_is_complete(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    first_plan = _plan(fixture, folder, proof)
    second_plan = _plan(fixture, folder, proof)

    assert first_plan == second_plan
    assert first_plan["plan_hash"] == cold.plan_content_hash(first_plan)
    assert first_plan["selection"]["hot_window_days"] == 30
    assert first_plan["selection"]["minimum_hot_window_days"] == 30
    assert all(
        set(record) == {"path", "bytes", "sha256"}
        for record in first_plan["files"]
    )

    _, first_manifest_path, first_result = _build(fixture, first_plan, "archive-one")
    _, second_manifest_path, second_result = _build(fixture, second_plan, "archive-two")
    first_manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
    second_manifest = json.loads(second_manifest_path.read_text(encoding="utf-8"))

    assert Path(first_result["archive_path"]).read_bytes() == Path(
        second_result["archive_path"]
    ).read_bytes()
    assert first_manifest == second_manifest
    assert first_manifest["schema_version"] == cold.MANIFEST_SCHEMA_VERSION
    assert first_manifest["manifest_hash"] == cold.manifest_content_hash(first_manifest)
    assert first_manifest["totals"]["file_count"] == len(first_manifest["source"]["files"])
    assert first_manifest["totals"]["bytes"] == sum(
        row["bytes"] for row in first_manifest["source"]["files"]
    )
    assert first_manifest["archive"]["sha256"] == hashlib.sha256(
        Path(first_result["archive_path"]).read_bytes()
    ).hexdigest()
    assert first_result["source_deleted_count"] == 0


def test_create_only_collision_preserves_existing_objects(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    plan = _plan(fixture, folder, proof)
    destination, manifest_path, result = _build(fixture, plan)
    archive_path = Path(result["archive_path"])
    before = (archive_path.read_bytes(), manifest_path.read_bytes())

    with pytest.raises(cold.ColdArchiveError, match="collision"):
        cold.build_archive(
            fixture_root=fixture,
            plan=plan,
            destination_root=destination,
            tool_identity=TOOL_IDENTITY,
        )

    assert (archive_path.read_bytes(), manifest_path.read_bytes()) == before


def test_source_drift_after_plan_blocks_build(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    plan = _plan(fixture, folder, proof)
    (folder / "order_books.jsonl").write_text("changed\n", encoding="utf-8")
    destination = fixture / "archive"
    destination.mkdir()

    with pytest.raises(cold.ColdArchiveError, match="source drift|event-day"):
        cold.build_archive(
            fixture_root=fixture,
            plan=plan,
            destination_root=destination,
            tool_identity=TOOL_IDENTITY,
        )
    assert list(destination.iterdir()) == []


def test_planner_detects_a_file_changing_during_hash(tmp_path, monkeypatch):
    fixture, folder, proof = _make_fixture(tmp_path)
    original = cold.sha256_file
    changed = False

    def racing_hash(path):
        nonlocal changed
        result = original(path)
        if Path(path).name == "order_books.jsonl" and not changed:
            changed = True
            Path(path).write_bytes(Path(path).read_bytes() + b"race\n")
        return result

    monkeypatch.setattr(cold, "sha256_file", racing_hash)
    with pytest.raises(cold.ColdArchiveError, match="changed while it was hashed"):
        _plan(fixture, folder, proof)


@pytest.mark.parametrize(
    ("as_of_date", "hot_window_days"),
    [("2026-06-22", 30), ("2026-07-22", 30), ("2026-08-01", 29)],
)
def test_active_too_new_and_unsafe_hot_window_fail_closed(
    tmp_path, as_of_date, hot_window_days
):
    fixture, folder, proof = _make_fixture(tmp_path)
    with pytest.raises(cold.ColdArchiveError, match="hot window|inside the hot window"):
        _plan(
            fixture,
            folder,
            proof,
            as_of_date=as_of_date,
            hot_window_days=hot_window_days,
        )


@pytest.mark.parametrize(
    ("check_name", "updates", "message"),
    [
        ("settlement_final", {"settled": False}, "active or unsettled"),
        ("barriers_clear", {"open_references": ["barrier-1"]}, "open references"),
        ("queues_clear", {"open_references": ["queue-1"]}, "open references"),
        (
            "point_in_time_windows_clear",
            {"open_references": ["pit-window"]},
            "open references",
        ),
    ],
)
def test_selection_proof_open_and_unsettled_gates_fail_closed(
    tmp_path, check_name, updates, message
):
    fixture, folder, proof_path = _make_fixture(tmp_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    row = next(item for item in proof["checks"] if item["check"] == check_name)
    row.update(updates)
    proof["proof_hash"] = cold.selection_proof_content_hash(proof)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")

    with pytest.raises(cold.ColdArchiveError, match=message):
        _plan(fixture, folder, proof_path)


def test_absent_proof_incomplete_manifest_path_escape_and_reparse_fail(tmp_path, monkeypatch):
    fixture, folder, proof = _make_fixture(tmp_path)
    missing = fixture / "review" / "missing.json"
    with pytest.raises(cold.ColdArchiveError, match="selection proof"):
        _plan(fixture, folder, missing)

    (folder / "source_status.jsonl").unlink()
    with pytest.raises(cold.ColdArchiveError, match="incomplete or stale"):
        _plan(fixture, folder, proof)

    outside = tmp_path / "outside" / SLUG
    outside.mkdir(parents=True)
    with pytest.raises(cold.ColdArchiveError, match="escapes"):
        _plan(fixture, outside, proof)

    original = cold._is_reparse_point
    monkeypatch.setattr(cold, "_is_reparse_point", lambda path: Path(path) == folder or original(Path(path)))
    with pytest.raises(cold.ColdArchiveError, match="reparse"):
        _plan(fixture, folder, proof)


def test_split_representations_require_exact_uncompressed_parity(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    plain = _write(folder / "order_books_long.csv", "id,value\n1,one\n")
    with gzip.open(folder / "order_books_long.csv.gz", "wb") as handle:
        handle.write(b"id,value\n2,two\n")
    write_event_day_manifest(folder, snapshots_root=fixture / "snapshots")
    _refresh_proof_manifest_binding(proof, folder)

    with pytest.raises(cold.ColdArchiveError, match="cannot be proven byte-complete"):
        _plan(fixture, folder, proof)

    with gzip.open(folder / "order_books_long.csv.gz", "wb") as handle:
        handle.write(plain.read_bytes())
    write_event_day_manifest(folder, snapshots_root=fixture / "snapshots")
    _refresh_proof_manifest_binding(proof, folder)
    plan = _plan(fixture, folder, proof)
    assert plan["selection"]["split_representation_proofs"][0]["status"] == "PASS"


def _refresh_proof_manifest_binding(proof_path: Path, folder: Path) -> None:
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    event = json.loads((folder / "event_day_manifest.json").read_text(encoding="utf-8"))
    proof["source"]["event_day_manifest_hash"] = event["manifest_hash"]
    proof["proof_hash"] = cold.selection_proof_content_hash(proof)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")


def test_destination_verifier_rejects_manifest_tampering_and_archive_drift(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    destination, manifest_path, result = _build(fixture, _plan(fixture, folder, proof))
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    manifest["totals"]["bytes"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(cold.ColdArchiveError, match="manifest hash"):
        cold.verify_destination(
            fixture_root=fixture,
            destination_root=destination,
            manifest_path=manifest_path,
            tool_identity=TOOL_IDENTITY,
        )

    manifest_path.write_bytes(original_manifest)
    archive_path = Path(result["archive_path"])
    archive_path.write_bytes(archive_path.read_bytes() + b"drift")
    with pytest.raises(cold.ColdArchiveError, match="drift"):
        cold.verify_destination(
            fixture_root=fixture,
            destination_root=destination,
            manifest_path=manifest_path,
            tool_identity=TOOL_IDENTITY,
        )


def test_rehashed_unsafe_plan_and_manifest_still_fail_semantic_gates(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    plan = _plan(fixture, folder, proof)
    plan["selection"]["hot_window_days"] = 90
    plan["plan_hash"] = cold.plan_content_hash(plan)
    destination = fixture / "archive-plan"
    destination.mkdir()
    with pytest.raises(cold.ColdArchiveError, match="outside the hot window"):
        cold.build_archive(
            fixture_root=fixture,
            plan=plan,
            destination_root=destination,
            tool_identity=TOOL_IDENTITY,
        )

    safe_plan = _plan(fixture, folder, proof)
    archive_root, manifest_path, _ = _build(fixture, safe_plan, "archive-manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    barrier = next(
        row
        for row in manifest["selection_proofs"]["selection_proof"]["checks"]
        if row["check"] == "barriers_clear"
    )
    barrier["open_references"] = ["forged-open-barrier"]
    manifest["manifest_hash"] = cold.manifest_content_hash(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(cold.ColdArchiveError, match="open references"):
        cold.verify_destination(
            fixture_root=fixture,
            destination_root=archive_root,
            manifest_path=manifest_path,
            tool_identity=TOOL_IDENTITY,
        )


def test_truncated_archive_rejected_even_when_outer_identity_is_reforged(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    destination, manifest_path, result = _build(fixture, _plan(fixture, folder, proof))
    archive_path = Path(result["archive_path"])
    archive_path.write_bytes(archive_path.read_bytes()[:80])
    _rewrite_manifest_for_archive(manifest_path, archive_path)

    with pytest.raises(cold.ColdArchiveError, match="truncated|structurally invalid"):
        cold.verify_destination(
            fixture_root=fixture,
            destination_root=destination,
            manifest_path=manifest_path,
            tool_identity=TOOL_IDENTITY,
        )


def test_archive_path_traversal_is_rejected_before_restore_writes(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    destination, manifest_path, result = _build(fixture, _plan(fixture, folder, proof))
    archive_path = Path(result["archive_path"])
    traversal = tarfile.TarInfo("../escape.txt")
    _replace_tar(archive_path, [(traversal, b"escape")])
    _rewrite_manifest_for_archive(manifest_path, archive_path)
    scratch = fixture / "restore-traversal"

    with pytest.raises(cold.ColdArchiveError, match="normalized relative"):
        cold.restore_archive(
            fixture_root=fixture,
            destination_root=destination,
            manifest_path=manifest_path,
            scratch_root=scratch,
            receipt_path=fixture / "review" / "traversal-receipt.json",
            tool_identity=TOOL_IDENTITY,
        )
    assert not scratch.exists()
    assert not (fixture / "escape.txt").exists()


def test_archive_links_and_duplicate_members_are_rejected(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    destination, manifest_path, result = _build(fixture, _plan(fixture, folder, proof))
    archive_path = Path(result["archive_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first = manifest["source"]["files"][0]

    link = tarfile.TarInfo(first["path"])
    link.type = tarfile.SYMTYPE
    link.linkname = "elsewhere"
    _replace_tar(archive_path, [(link, b"")])
    _rewrite_manifest_for_archive(manifest_path, archive_path)
    with pytest.raises(cold.ColdArchiveError, match="links/special"):
        cold.verify_destination(
            fixture_root=fixture,
            destination_root=destination,
            manifest_path=manifest_path,
            tool_identity=TOOL_IDENTITY,
        )

    duplicate = tarfile.TarInfo(first["path"])
    payload = (folder / first["path"]).read_bytes()
    _replace_tar(
        archive_path,
        [(copy.copy(duplicate), payload), (copy.copy(duplicate), payload)],
    )
    _rewrite_manifest_for_archive(manifest_path, archive_path)
    with pytest.raises(cold.ColdArchiveError, match="duplicate"):
        cold.verify_destination(
            fixture_root=fixture,
            destination_root=destination,
            manifest_path=manifest_path,
            tool_identity=TOOL_IDENTITY,
        )


def test_restore_mismatch_rejected_before_scratch_creation(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    destination, manifest_path, result = _build(fixture, _plan(fixture, folder, proof))
    archive_path = Path(result["archive_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    members = []
    for index, record in enumerate(manifest["source"]["files"]):
        payload = (folder / record["path"]).read_bytes()
        if index == 0:
            payload = b"x" * len(payload)
        members.append((tarfile.TarInfo(record["path"]), payload))
    _replace_tar(archive_path, members)
    _rewrite_manifest_for_archive(manifest_path, archive_path)
    scratch = fixture / "restore-mismatch"

    with pytest.raises(cold.ColdArchiveError, match="member hash mismatch"):
        cold.restore_archive(
            fixture_root=fixture,
            destination_root=destination,
            manifest_path=manifest_path,
            scratch_root=scratch,
            receipt_path=fixture / "review" / "mismatch-receipt.json",
            tool_identity=TOOL_IDENTITY,
        )
    assert not scratch.exists()


def test_restore_and_cleanup_manifest_require_exact_archive_receipt_parity(tmp_path):
    fixture, folder, proof = _make_fixture(tmp_path)
    destination, manifest_path, _ = _build(fixture, _plan(fixture, folder, proof))
    receipt_path = fixture / "review" / "restore-receipt.json"
    restored = cold.restore_archive(
        fixture_root=fixture,
        destination_root=destination,
        manifest_path=manifest_path,
        scratch_root=fixture / "restore-success",
        receipt_path=receipt_path,
        restored_at_utc="2026-08-01T00:00:00+00:00",
        tool_identity=TOOL_IDENTITY,
    )
    assert restored["status"] == "PASS"
    assert restored["restore_receipt_hash"] == cold.restore_receipt_content_hash(restored)
    assert Path(fixture / restored["restored_root"]).is_dir()

    cleanup_path = fixture / "review" / "cleanup-manifest.json"
    cleanup = cold.generate_cleanup_manifest(
        fixture_root=fixture,
        destination_root=destination,
        manifest_path=manifest_path,
        restore_receipt_path=receipt_path,
        output_path=cleanup_path,
        generated_at_utc="2026-08-01T01:00:00+00:00",
        tool_identity=TOOL_IDENTITY,
    )
    assert cleanup["schema_version"] == "cleanup_manifest_v0.1"
    assert cleanup["operator_review"]["approved"] is False
    assert cleanup["executor_present"] is False
    assert cleanup["cleanup_plan_hash"] == cold.cleanup_plan_content_hash(cleanup)
    assert {row["path"] for row in cleanup["candidates"]} == {
        row["path"] for row in restored["files"]
    }
    assert all(Path(row["source_path"]).is_absolute() for row in cleanup["candidates"])
    assert folder.exists()


@pytest.mark.parametrize("failure", ["tampered_receipt", "wrong_manifest", "source_drift", "restore_drift"])
def test_cleanup_plan_gate_failures(tmp_path, failure):
    fixture, folder, proof = _make_fixture(tmp_path)
    destination, manifest_path, _ = _build(fixture, _plan(fixture, folder, proof))
    receipt_path = fixture / "review" / "restore-receipt.json"
    receipt = cold.restore_archive(
        fixture_root=fixture,
        destination_root=destination,
        manifest_path=manifest_path,
        scratch_root=fixture / "restore-success",
        receipt_path=receipt_path,
        tool_identity=TOOL_IDENTITY,
    )
    if failure == "tampered_receipt":
        receipt["status"] = "BLOCK"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    elif failure == "wrong_manifest":
        receipt["manifest_hash"] = "f" * 64
        receipt["restore_receipt_hash"] = cold.restore_receipt_content_hash(receipt)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    elif failure == "source_drift":
        (folder / "order_books.jsonl").write_text("source drift\n", encoding="utf-8")
    else:
        restored_root = fixture / receipt["restored_root"]
        (restored_root / "order_books.jsonl").write_text("restore drift\n", encoding="utf-8")

    with pytest.raises(cold.ColdArchiveError):
        cold.generate_cleanup_manifest(
            fixture_root=fixture,
            destination_root=destination,
            manifest_path=manifest_path,
            restore_receipt_path=receipt_path,
            output_path=fixture / "review" / "cleanup-manifest.json",
            tool_identity=TOOL_IDENTITY,
        )


def test_fixture_marker_is_required_and_repo_data_overlap_is_refused(
    tmp_path, monkeypatch
):
    unmarked = tmp_path / "vca-unmarked"
    unmarked.mkdir()
    with pytest.raises(cold.ColdArchiveError, match="marker"):
        cold.validate_fixture_root(unmarked)

    wrong_name = tmp_path / "ordinary-root"
    wrong_name.mkdir()
    _write(
        wrong_name / cold.FIXTURE_MARKER,
        json.dumps(
            {
                "allow_real_data": False,
                "purpose": cold.FIXTURE_MARKER_PURPOSE,
            }
        ),
    )
    with pytest.raises(cold.ColdArchiveError, match="fixture root"):
        cold.validate_fixture_root(wrong_name)

    protected = tmp_path / "data"
    protected_fixture = protected / "vca-protected"
    protected_fixture.mkdir(parents=True)
    _write(
        protected_fixture / cold.FIXTURE_MARKER,
        json.dumps(
            {
                "allow_real_data": False,
                "purpose": cold.FIXTURE_MARKER_PURPOSE,
            }
        ),
    )
    monkeypatch.setattr(cold, "DATA_ROOT", protected)
    with pytest.raises(cold.ColdArchiveError, match="must not overlap"):
        cold.validate_fixture_root(protected_fixture)


def test_schema_versions_are_registered():
    assert cold.ARCHIVE_FORMAT == "deterministic_tar_gzip_v0.1"
    assert cold.SELECTION_PROOF_SCHEMA_VERSION == "verified_cold_archive_selection_proof_v0.1"
    assert cold.PLAN_SCHEMA_VERSION == "verified_cold_archive_plan_v0.1"
    assert cold.MANIFEST_SCHEMA_VERSION == "verified_cold_archive_manifest_v0.1"
    assert (
        cold.VERIFICATION_RECEIPT_SCHEMA_VERSION
        == "verified_cold_archive_verification_receipt_v0.1"
    )
    assert cold.RESTORE_RECEIPT_SCHEMA_VERSION == "verified_cold_archive_restore_receipt_v0.1"
