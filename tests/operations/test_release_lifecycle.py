from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import weather.operations.release_promotion as release_promotion
from weather.artifacts import ReleaseArtifactVerificationError, resolve_verified_active_release
from weather.operations.release_lifecycle import (
    MARKET_DAY_BOUNDARY_SCHEMA_VERSION,
    PROMOTION_DECISION_SCHEMA_VERSION,
    RELEASE_MANIFEST_NAME,
    ROLLBACK_DRILL_SCHEMA_VERSION,
    ReleaseLifecycleError,
    assert_candidate_only_output,
    assert_training_output_path,
    create_release,
    load_active_pointer,
    load_release_manifest,
    promote_release,
    resolve_active_release,
    rollback_release,
    validate_market_day_boundary,
    verify_release,
)
from weather.operations.release_lifecycle_cli import main as release_cli_main
from weather.operations.release_manifest import canonical_payload_sha256


NOW = datetime(2026, 7, 11, 15, 0, tzinfo=timezone.utc)
COMMIT = "a" * 40


def code_identity(*, dirty: bool = False) -> dict:
    return {
        "git_commit": COMMIT,
        "git_branch": "main",
        "git_dirty": dirty,
        "dirty_fingerprint": ("b" * 64) if dirty else None,
        "dirty_entry_count": 1 if dirty else 0,
    }


def runtime_versions() -> dict:
    return {
        "python": "3.11.9",
        "implementation": "CPython",
        "platform": "test-platform",
        "direct_dependencies": {
            "scikit-learn": {"version": "1.8.0", "declared": "scikit-learn==1.8.0"},
        },
    }


def runtime_identity(*, fingerprint: str = "source-abc") -> dict:
    return {
        "schema_version": "runtime_identity_v0.1",
        "source_fingerprint": fingerprint,
        "git_commit": COMMIT[:12],
    }


def write_candidate(root: Path, name: str) -> Path:
    candidate = root / f"candidate-{name}"
    (candidate / "models").mkdir(parents=True, exist_ok=True)
    (candidate / "config").mkdir(exist_ok=True)
    (candidate / "calibration").mkdir(exist_ok=True)
    (candidate / "models" / "weather.bin").write_bytes(f"model-{name}".encode())
    (candidate / "config" / "route.json").write_text('{"route":"pooled"}\n', encoding="utf-8")
    (candidate / "calibration" / "temperature.json").write_text('{"t":1.0}\n', encoding="utf-8")
    (candidate / "README.txt").write_text("undeclared but still integrity protected\n", encoding="utf-8")
    return candidate


def declarations() -> list[dict]:
    return [
        {"path": "models/weather.bin", "kind": "model", "role": "weather_model"},
        {"path": "config/route.json", "kind": "config", "role": "route_config"},
        {
            "path": "calibration/temperature.json",
            "kind": "calibration",
            "role": "temperature_calibrator",
        },
    ]


def build_release(
    root: Path,
    release_id: str,
    *,
    rollback_target: str | None = None,
    dirty: bool = False,
) -> dict:
    return create_release(
        release_id=release_id,
        candidate_dir=write_candidate(root, release_id),
        declarations=declarations(),
        route={"default_variant": "pooled_v1", "market_routes": {"toronto": "pooled_v1"}},
        expected_live_runtimes=["snapshot_loop", "observation_trigger"],
        releases_root=root / "releases",
        repo_root=root,
        parent_release=rollback_target,
        rollback_target=rollback_target,
        lineage={"training_corpus_sha256": "c" * 64, "target_date_end": "2026-07-10"},
        code_identity=code_identity(dirty=dirty),
        runtime_versions=runtime_versions(),
        runtime_identity=runtime_identity(),
        created_at_utc=NOW.isoformat(),
    )


def decision(release_id: str, manifest_sha256: str) -> dict:
    return {
        "schema_version": PROMOTION_DECISION_SCHEMA_VERSION,
        "decision": "PROMOTE",
        "gate_status": "PASS",
        "release_id": release_id,
        "manifest_sha256": manifest_sha256,
        "candidate_only_build": True,
        "reviewed": True,
        "reviewed_by": "release-reviewer",
        "reviewed_at_utc": NOW.isoformat(),
    }


def boundary(release_id: str, manifest_sha256: str, *, observed: datetime = NOW) -> dict:
    return {
        "schema_version": MARKET_DAY_BOUNDARY_SCHEMA_VERSION,
        "status": "PASS",
        "release_id": release_id,
        "manifest_sha256": manifest_sha256,
        "at_market_day_boundary": True,
        "processes_quiesced": True,
        "open_market_days": [],
        "mixed_release_market_days": [],
        "effective_target_date": "2026-07-12",
        "observed_at_utc": observed.isoformat(),
    }


def promote(root: Path, release: dict) -> dict:
    return promote_release(
        release["release_id"],
        decision=decision(release["release_id"], release["manifest_sha256"]),
        market_day_boundary=boundary(release["release_id"], release["manifest_sha256"]),
        releases_root=root / "releases",
        pointer_path=root / "releases" / "current_release.json",
        repo_root=root,
        now=NOW,
        current_runtime_versions=runtime_versions(),
        current_runtime_identity=runtime_identity(),
        current_code_identity=code_identity(),
    )


def test_create_release_inventories_every_file_and_never_overwrites(tmp_path: Path):
    result = build_release(tmp_path, "r1")
    release_dir = Path(result["release_dir"])
    manifest = load_release_manifest(release_dir)

    assert manifest["state"] == "IMMUTABLE_CANDIDATE"
    assert manifest["code"]["git_commit"] == COMMIT
    assert manifest["config_hashes"] == {
        "route_config": next(
            row["sha256"] for row in manifest["artifacts"]["inventory"] if row["role"] == "route_config"
        )
    }
    assert {row["path"] for row in manifest["artifacts"]["inventory"]} == {
        "README.txt",
        "calibration/temperature.json",
        "config/route.json",
        "models/weather.bin",
    }
    readme = next(row for row in manifest["artifacts"]["inventory"] if row["path"] == "README.txt")
    assert readme["declared"] is False
    assert readme["kind"] == "other"

    verified = verify_release(
        release_dir,
        repo_root=tmp_path,
        current_runtime_versions=runtime_versions(),
        current_runtime_identity=runtime_identity(),
    )
    assert verified["status"] == "PASS"
    assert verified["file_count"] == 4
    with pytest.raises(ReleaseLifecycleError, match="already exists"):
        build_release(tmp_path, "r1")
    assert (release_dir / RELEASE_MANIFEST_NAME).exists()


@pytest.mark.parametrize("mutation", ["tamper", "extra", "nested-manifest", "missing"])
def test_complete_verification_rejects_any_release_file_set_change(tmp_path: Path, mutation: str):
    result = build_release(tmp_path, "r1")
    release_dir = Path(result["release_dir"])
    if mutation == "tamper":
        (release_dir / "models" / "weather.bin").write_bytes(b"changed")
    elif mutation == "extra":
        (release_dir / "extra.bin").write_bytes(b"extra")
    elif mutation == "nested-manifest":
        (release_dir / "nested").mkdir()
        (release_dir / "nested" / RELEASE_MANIFEST_NAME).write_text("{}", encoding="utf-8")
    else:
        (release_dir / "config" / "route.json").unlink()

    with pytest.raises(ReleaseLifecycleError):
        verify_release(
            release_dir,
            repo_root=tmp_path,
            current_runtime_versions=runtime_versions(),
            current_runtime_identity=runtime_identity(),
        )


def test_verification_rejects_version_and_source_identity_mismatch(tmp_path: Path):
    result = build_release(tmp_path, "r1")
    release_dir = Path(result["release_dir"])
    wrong_versions = runtime_versions()
    wrong_versions["direct_dependencies"]["scikit-learn"]["version"] = "9.9.9"
    with pytest.raises(ReleaseLifecycleError, match="dependency mismatch"):
        verify_release(
            release_dir,
            repo_root=tmp_path,
            current_runtime_versions=wrong_versions,
            current_runtime_identity=runtime_identity(),
        )
    with pytest.raises(ReleaseLifecycleError, match="source identity"):
        verify_release(
            release_dir,
            repo_root=tmp_path,
            current_runtime_versions=runtime_versions(),
            current_runtime_identity=runtime_identity(fingerprint="different"),
        )


def test_candidate_only_guard_accepts_candidate_children_and_rejects_other_paths(tmp_path: Path):
    candidates = tmp_path / "artifacts" / "candidates"
    releases = tmp_path / "artifacts" / "releases"
    output = candidates / "candidate-42" / "model.bin"
    assert_candidate_only_output(
        output,
        candidates_root=candidates,
        releases_root=releases,
        active_pointer=releases / "current_release.json",
    )
    with pytest.raises(ReleaseLifecycleError, match="outside candidate root"):
        assert_candidate_only_output(
            releases / "r1" / "model.bin",
            candidates_root=candidates,
            releases_root=releases,
            active_pointer=releases / "current_release.json",
        )
    with pytest.raises(ReleaseLifecycleError, match="name a child path"):
        assert_candidate_only_output(
            candidates,
            candidates_root=candidates,
            releases_root=releases,
            active_pointer=releases / "current_release.json",
        )


def test_training_output_legacy_compatibility_is_explicit_and_never_allows_release_writes(tmp_path: Path):
    candidates = tmp_path / "artifacts" / "candidates"
    releases = tmp_path / "artifacts" / "releases"
    legacy = tmp_path / "artifacts" / "models" / "active.pkl"
    with pytest.raises(ReleaseLifecycleError, match="outside candidate root"):
        assert_training_output_path(
            legacy,
            candidates_root=candidates,
            releases_root=releases,
            active_pointer=releases / "current_release.json",
        )
    quarantined = assert_training_output_path(
        legacy,
        candidates_root=candidates,
        releases_root=releases,
        active_pointer=releases / "current_release.json",
        allow_legacy_serving_output=True,
    )
    assert quarantined["status"] == "QUARANTINED_LEGACY_OUTPUT"
    assert quarantined["release_eligible"] is False
    with pytest.raises(ReleaseLifecycleError, match="immutable/active"):
        assert_training_output_path(
            releases / "r1" / "model.pkl",
            candidates_root=candidates,
            releases_root=releases,
            active_pointer=releases / "current_release.json",
            allow_legacy_serving_output=True,
        )
def test_market_day_boundary_proof_is_targeted_complete_and_fresh():
    proof = boundary("r1", "a" * 64)
    assert validate_market_day_boundary(
        proof,
        release_id="r1",
        manifest_sha256="a" * 64,
        now=NOW,
    )["status"] == "PASS"
    stale = boundary("r1", "a" * 64, observed=NOW - timedelta(hours=1))
    with pytest.raises(ReleaseLifecycleError, match="stale"):
        validate_market_day_boundary(stale, release_id="r1", manifest_sha256="a" * 64, now=NOW)
    incomplete = boundary("r1", "a" * 64)
    incomplete["processes_quiesced"] = False
    with pytest.raises(ReleaseLifecycleError, match="processes_quiesced"):
        validate_market_day_boundary(incomplete, release_id="r1", manifest_sha256="a" * 64, now=NOW)


def test_atomic_promotion_active_resolution_and_one_command_rollback(tmp_path: Path):
    pointer_path = tmp_path / "releases" / "current_release.json"
    drill_record_path = tmp_path / "backtest" / "release_rollback_drill.json"
    r1 = build_release(tmp_path, "r1")
    assert promote(tmp_path, r1)["status"] == "PROMOTED"
    first = load_active_pointer(pointer_path)
    assert first["active_release_id"] == "r1"
    assert first["previous_release_id"] is None
    assert first["sequence"] == 1

    resolved = resolve_active_release(
        releases_root=tmp_path / "releases",
        pointer_path=pointer_path,
        repo_root=tmp_path,
        current_runtime_versions=runtime_versions(),
        current_runtime_identity=runtime_identity(),
    )
    assert resolved["release_id"] == "r1"
    with pytest.raises(ReleaseArtifactVerificationError, match="served artifact bindings"):
        resolve_verified_active_release(
            releases_root=tmp_path / "releases",
            pointer_path=pointer_path,
            repo_root=tmp_path,
            current_runtime_versions=runtime_versions(),
            current_runtime_identity=runtime_identity(),
        )
    neutral = resolve_verified_active_release(
        releases_root=tmp_path / "releases",
        pointer_path=pointer_path,
        repo_root=tmp_path,
        current_runtime_versions=runtime_versions(),
        current_runtime_identity=runtime_identity(),
        served_artifact_paths={
            "weather_model": tmp_path / "releases" / "r1" / "models" / "weather.bin",
            "route_config": tmp_path / "releases" / "r1" / "config" / "route.json",
            "temperature_calibrator": (
                tmp_path / "releases" / "r1" / "calibration" / "temperature.json"
            ),
        },
        served_route={
            "default_variant": "pooled_v1",
            "market_routes": {"toronto": "pooled_v1"},
        },
    )
    assert neutral["status"] == "PASS"
    assert neutral["release_id"] == "r1"
    assert neutral["manifest_sha256"] == r1["manifest_sha256"]
    assert neutral["pointer_sha256"] == first["pointer_sha256"]
    assert neutral["sequence"] == 1
    assert neutral["runtime_checked"] is True
    assert neutral["served_bindings_verified"] is True
    assert len(neutral["served_binding_sha256"]) == 64
    assert neutral["served_artifact_roles"] == [
        "route_config",
        "temperature_calibrator",
        "weather_model",
    ]

    r2 = build_release(tmp_path, "r2", rollback_target="r1")
    assert promote(tmp_path, r2)["status"] == "PROMOTED"
    second = load_active_pointer(pointer_path)
    assert second["active_release_id"] == "r2"
    assert second["previous_release_id"] == "r1"
    assert second["sequence"] == 2

    with pytest.raises(ReleaseLifecycleError, match="outside the immutable releases root"):
        rollback_release(
            market_day_boundary=boundary("r1", r1["manifest_sha256"]),
            releases_root=tmp_path / "releases",
            pointer_path=pointer_path,
            drill_record_path=pointer_path,
            now=NOW,
        )
    assert load_active_pointer(pointer_path)["active_release_id"] == "r2"

    rolled_back = rollback_release(
        market_day_boundary=boundary("r1", r1["manifest_sha256"]),
        releases_root=tmp_path / "releases",
        pointer_path=pointer_path,
        drill_record_path=drill_record_path,
        now=NOW,
    )
    assert rolled_back["status"] == "ROLLED_BACK"
    assert rolled_back["restart_required"] is True
    final = load_active_pointer(pointer_path)
    assert final["action"] == "ROLLBACK"
    assert final["active_release_id"] == "r1"
    assert final["previous_release_id"] == "r2"
    assert final["sequence"] == 3
    identity = rolled_back["release_identity_proof"]
    assert identity == json.loads(drill_record_path.read_text(encoding="utf-8"))[
        "post_rollback_identity"
    ]
    assert identity["status"] == "PASS"
    assert identity["release_id"] == "r1"
    assert identity["manifest_sha256"] == r1["manifest_sha256"]
    assert identity["pointer_sha256"] == final["pointer_sha256"]
    assert identity["pointer_sequence"] == 3
    assert identity["pointer_action"] == "ROLLBACK"
    assert identity["integrity_verified"] is True
    assert identity["runtime_compatibility_checked"] is False
    assert len(identity["proof_sha256"]) == 64

    drill = json.loads(drill_record_path.read_text(encoding="utf-8"))
    assert drill["schema_version"] == ROLLBACK_DRILL_SCHEMA_VERSION
    assert drill["evidence_contract"] == "release_rollback_drill"
    assert drill["status"] == "PENDING_MANUAL_RESTART"
    assert drill["rollback_status"] == "PASS"
    assert drill["rollback_source_release_id"] == "r2"
    assert drill["rollback_target_release_id"] == "r1"
    assert drill["restored_release_id"] == "r1"
    assert drill["release_id"] == "r1"
    assert drill["manifest_sha256"] == r1["manifest_sha256"]
    assert drill["rollback_duration_seconds"] > 0
    assert drill["rollback_started_at_utc"] == NOW.isoformat()
    assert drill["rollback_completed_at_utc"] == NOW.isoformat()
    assert drill["post_rollback_identity_status"] == "PASS"
    assert drill["manual_coordinated_restart"] == {
        "required": True,
        "status": "PENDING",
        "release_id": "r1",
        "required_runtimes": ["observation_trigger", "snapshot_loop"],
        "completed_at_utc": None,
        "completed_by": None,
        "runtime_identity_proof": None,
    }
    assert drill["health_status"] == "PENDING"
    assert drill["health_proof"] is None
    assert drill["rollback_intent_sha256"] == drill["rollback_intent"][
        "record_sha256"
    ]
    assert drill["rollback_intent"]["planned_pointer_sha256"] == final[
        "pointer_sha256"
    ]
    assert drill["record_sha256"] == canonical_payload_sha256(
        drill,
        omit=("record_sha256",),
    )
    with pytest.raises(ReleaseLifecycleError, match="refusing to toggle"):
        rollback_release(
            market_day_boundary=boundary("r2", r2["manifest_sha256"]),
            releases_root=tmp_path / "releases",
            pointer_path=pointer_path,
            drill_record_path=drill_record_path,
            now=NOW,
        )


def test_rollback_finalization_failure_leaves_recoverable_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    r1 = build_release(tmp_path, "r1")
    promote(tmp_path, r1)
    r2 = build_release(tmp_path, "r2", rollback_target="r1")
    promote(tmp_path, r2)
    pointer_path = tmp_path / "releases" / "current_release.json"
    drill_record_path = tmp_path / "backtest" / "release_rollback_drill.json"

    real_write = release_promotion._write_json_atomic
    failed_finalization = False

    def fail_first_final_record(path: Path, payload: dict) -> None:
        nonlocal failed_finalization
        if (
            payload.get("status") == "PENDING_MANUAL_RESTART"
            and not failed_finalization
        ):
            failed_finalization = True
            raise OSError("injected final record failure")
        real_write(path, payload)

    monkeypatch.setattr(
        release_promotion,
        "_write_json_atomic",
        fail_first_final_record,
    )
    with pytest.raises(
        ReleaseLifecycleError,
        match="same rollback command can retry finalization",
    ):
        rollback_release(
            market_day_boundary=boundary("r1", r1["manifest_sha256"]),
            releases_root=tmp_path / "releases",
            pointer_path=pointer_path,
            drill_record_path=drill_record_path,
            now=NOW,
        )

    rolled_pointer = load_active_pointer(pointer_path)
    assert rolled_pointer["action"] == "ROLLBACK"
    assert rolled_pointer["active_release_id"] == "r1"
    intent = json.loads(drill_record_path.read_text(encoding="utf-8"))
    assert intent["status"] == "PENDING_POINTER_RECONCILIATION"
    assert intent["planned_pointer_sha256"] == rolled_pointer["pointer_sha256"]
    assert intent["record_sha256"] == canonical_payload_sha256(
        intent,
        omit=("record_sha256",),
    )

    recovered = rollback_release(
        market_day_boundary={},
        releases_root=tmp_path / "releases",
        pointer_path=pointer_path,
        drill_record_path=drill_record_path,
        now=NOW,
    )
    assert recovered["status"] == "ROLLED_BACK"
    assert recovered["release_identity_proof"]["pointer_sha256"] == rolled_pointer[
        "pointer_sha256"
    ]
    completed = json.loads(drill_record_path.read_text(encoding="utf-8"))
    assert completed["status"] == "PENDING_MANUAL_RESTART"
    assert completed["rollback_intent"] == intent


def test_promotion_rejects_dirty_release_and_wrong_rollback_target(tmp_path: Path):
    dirty = build_release(tmp_path, "dirty", dirty=True)
    with pytest.raises(ReleaseLifecycleError, match="dirty or unknown"):
        promote_release(
            "dirty",
            decision=decision("dirty", dirty["manifest_sha256"]),
            market_day_boundary=boundary("dirty", dirty["manifest_sha256"]),
            releases_root=tmp_path / "releases",
            pointer_path=tmp_path / "releases" / "current_release.json",
            repo_root=tmp_path,
            now=NOW,
            current_runtime_versions=runtime_versions(),
            current_runtime_identity=runtime_identity(),
            current_code_identity=code_identity(),
        )

    clean_root = tmp_path / "clean"
    r1 = build_release(clean_root, "r1")
    promote(clean_root, r1)
    wrong = build_release(clean_root, "r2", rollback_target=None)
    with pytest.raises(ReleaseLifecycleError, match="rollback_target"):
        promote(clean_root, wrong)


def test_pointer_and_manifest_tampering_fail_closed(tmp_path: Path):
    release = build_release(tmp_path, "r1")
    promote(tmp_path, release)
    pointer_path = tmp_path / "releases" / "current_release.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["active_release_id"] = "attacker"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(ReleaseLifecycleError, match="pointer content hash"):
        load_active_pointer(pointer_path)

    manifest_path = Path(release["release_dir"]) / RELEASE_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["route"]["default_variant"] = "attacker"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReleaseLifecycleError, match="manifest content hash"):
        verify_release(Path(release["release_dir"]), check_runtime=False)


def test_cli_builds_and_verifies_a_release_from_a_candidate_spec(tmp_path: Path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('release test')\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nname='release-test'\nversion='0.1.0'\ndependencies=['scikit-learn']\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "app.py", "pyproject.toml"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )
    candidate = write_candidate(tmp_path, "cli")
    spec = tmp_path / "release-spec.json"
    spec.write_text(
        json.dumps(
            {
                "release_id": "cli-r1",
                "artifacts": declarations(),
                "route": {"default_variant": "pooled_v1"},
                "expected_live_runtimes": ["snapshot_loop"],
                "rollback_target": None,
            }
        ),
        encoding="utf-8",
    )
    releases = repo / "artifacts" / "releases"
    create_status = release_cli_main(
        [
            "--releases-root",
            str(releases),
            "--repo-root",
            str(repo),
            "create",
            "--candidate",
            str(candidate),
            "--spec",
            str(spec),
        ]
    )
    assert create_status == 0
    create_output = json.loads(capsys.readouterr().out)
    assert create_output["status"] == "CREATED"
    verify_status = release_cli_main(
        [
            "--releases-root",
            str(releases),
            "--repo-root",
            str(repo),
            "verify",
            "cli-r1",
        ]
    )
    assert verify_status == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    proof_now = datetime.now(timezone.utc)
    decision_path = tmp_path / "decision-r1.json"
    decision_path.write_text(
        json.dumps(decision("cli-r1", create_output["manifest_sha256"]) | {"reviewed_at_utc": proof_now.isoformat()}),
        encoding="utf-8",
    )
    boundary_path = tmp_path / "boundary-r1.json"
    boundary_path.write_text(
        json.dumps(
            boundary("cli-r1", create_output["manifest_sha256"], observed=proof_now)
            | {"effective_target_date": proof_now.date().isoformat()}
        ),
        encoding="utf-8",
    )
    common = ["--releases-root", str(releases), "--repo-root", str(repo)]
    assert release_cli_main(
        common
        + [
            "promote",
            "cli-r1",
            "--decision",
            str(decision_path),
            "--market-day-boundary",
            str(boundary_path),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PROMOTED"

    candidate_r2 = write_candidate(tmp_path, "cli-r2")
    spec_r2 = tmp_path / "release-spec-r2.json"
    spec_r2.write_text(
        json.dumps(
            {
                "release_id": "cli-r2",
                "artifacts": declarations(),
                "route": {"default_variant": "pooled_v2"},
                "expected_live_runtimes": ["snapshot_loop"],
                "parent_release": "cli-r1",
                "rollback_target": "cli-r1",
            }
        ),
        encoding="utf-8",
    )
    assert release_cli_main(
        common + ["create", "--candidate", str(candidate_r2), "--spec", str(spec_r2)]
    ) == 0
    create_r2 = json.loads(capsys.readouterr().out)
    decision_r2 = tmp_path / "decision-r2.json"
    decision_r2.write_text(
        json.dumps(decision("cli-r2", create_r2["manifest_sha256"]) | {"reviewed_at_utc": proof_now.isoformat()}),
        encoding="utf-8",
    )
    boundary_r2 = tmp_path / "boundary-r2.json"
    boundary_r2.write_text(
        json.dumps(
            boundary("cli-r2", create_r2["manifest_sha256"], observed=proof_now)
            | {"effective_target_date": proof_now.date().isoformat()}
        ),
        encoding="utf-8",
    )
    assert release_cli_main(
        common
        + [
            "promote",
            "cli-r2",
            "--decision",
            str(decision_r2),
            "--market-day-boundary",
            str(boundary_r2),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PROMOTED"

    rollback_boundary = tmp_path / "rollback-boundary.json"
    rollback_boundary.write_text(
        json.dumps(
            boundary("cli-r1", create_output["manifest_sha256"], observed=proof_now)
            | {"effective_target_date": proof_now.date().isoformat()}
        ),
        encoding="utf-8",
    )
    rollback_drill = tmp_path / "backtest" / "release_rollback_drill.json"
    assert release_cli_main(
        common
        + [
            "rollback",
            "--market-day-boundary",
            str(rollback_boundary),
            "--drill-record",
            str(rollback_drill),
        ]
    ) == 0
    rollback_output = json.loads(capsys.readouterr().out)
    assert rollback_output["status"] == "ROLLED_BACK"
    assert rollback_output["drill_status"] == "PENDING_MANUAL_RESTART"
    assert rollback_output["drill_record_path"] == str(rollback_drill.resolve())
    assert rollback_output["release_identity_proof"]["release_id"] == "cli-r1"
    assert rollback_output["release_identity_proof"]["status"] == "PASS"
    assert json.loads(rollback_drill.read_text(encoding="utf-8"))[
        "post_rollback_identity"
    ] == rollback_output["release_identity_proof"]
    assert load_active_pointer(releases / "current_release.json")["active_release_id"] == "cli-r1"
