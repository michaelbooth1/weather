from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from weather.market import live_sdk_overlay as overlay
from weather.market import live_sdk_portability as portability


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_sdk(tmp_path: Path) -> tuple[Path, Path]:
    profile = tmp_path / "profile"
    root = profile / "ops/sdk-overlay"
    wheelhouse = profile / "ops/sdk-wheelhouse"
    package = root / "polymarket"
    metadata = root / "polymarket_client-0.6.0.dist-info"
    package.mkdir(parents=True)
    metadata.mkdir(parents=True)
    wheelhouse.mkdir(parents=True)
    init = package / "__init__.py"
    init.write_text('__version__ = "0.6.0"\n', encoding="utf-8")
    metadata_file = metadata / "METADATA"
    metadata_file.write_text(
        "Metadata-Version: 2.1\nName: polymarket-client\nVersion: 0.6.0\n",
        encoding="utf-8",
    )
    (metadata / "WHEEL").write_text(
        "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        encoding="utf-8",
    )
    wheel_names = [
        "polymarket_client-0.6.0-py3-none-any.whl",
        "native-1.0.0-cp311-cp311-win_amd64.whl",
    ]
    for index, name in enumerate(wheel_names):
        (wheelhouse / name).write_bytes(f"wheel-{index}".encode())
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    tree_rows = [
        f"{path.relative_to(root).as_posix()}:{path.stat().st_size}:{sha(path)}"
        for path in files
    ]
    ordered_wheels = [wheelhouse / name for name in wheel_names]
    wheel_rows = [f"{path.name}:{sha(path).upper()}" for path in ordered_wheels]
    payload = {
        "schema_version": overlay.MANIFEST_SCHEMA_VERSION,
        "distribution": overlay.EXPECTED_DISTRIBUTION,
        "import_package": overlay.EXPECTED_IMPORT_PACKAGE,
        "version": overlay.EXPECTED_VERSION,
        "overlay": {
            "path_base": "user_profile",
            "relative_path": "ops/sdk-overlay",
            "file_count": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "tree_manifest_sha256": hashlib.sha256(
                "\n".join(tree_rows).encode()
            ).hexdigest(),
            "metadata_relative_path": metadata_file.relative_to(root).as_posix(),
            "metadata_sha256": sha(metadata_file),
            "package_init_relative_path": init.relative_to(root).as_posix(),
            "package_init_sha256": sha(init),
        },
        "wheelhouse": {
            "path_base": "user_profile",
            "relative_path": "ops/sdk-wheelhouse",
            "file_count": len(ordered_wheels),
            "bytes": sum(path.stat().st_size for path in ordered_wheels),
            "name_hash_manifest_sha256": hashlib.sha256(
                "\n".join(wheel_rows).encode()
            ).hexdigest(),
            "ordered_file_names": wheel_names,
            "core_wheel_name": wheel_names[0],
            "core_wheel_sha256": sha(ordered_wheels[0]),
        },
    }
    manifest = tmp_path / "sdk-manifest.json"
    manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return profile, manifest


@pytest.fixture
def supported_host(monkeypatch):
    evidence = {
        "checks": {
            "windows": True,
            "machine_amd64": True,
            "pointer_width_64": True,
            "cpython": True,
            "python_3_11": True,
            "python_executable_regular": True,
            "sysconfig_win_amd64": True,
            "ambient_computer_matches_os": True,
            "ambient_user_matches_os": True,
        },
        "compatible": True,
        "implementation": "CPython",
        "machine": "AMD64",
        "pointer_bits": 64,
        "python_version": "3.11.0",
        "python_executable": "C:/Python311/python.exe",
        "python_executable_sha256": "a" * 64,
        "system": "Windows",
        "execution_host_id": "b" * 64,
        "execution_host_id_contract": (
            "international_live_execution_host_v2:windows_machine_guid"
        ),
        "windows_identity": {
            "computer_name": "TESTHOST",
            "user_name": "tester",
            "user_sid": "S-1-5-21-test",
        },
    }
    monkeypatch.setattr(portability, "_host_evidence", lambda: evidence)
    return evidence


def export_fixture(tmp_path: Path, monkeypatch, supported_host):
    source_profile, manifest = build_sdk(tmp_path / "source")
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: source_profile.resolve()
    )
    bundle_parent = tmp_path / "public"
    receipts = tmp_path / "receipts"
    bundle_parent.mkdir()
    receipts.mkdir()
    bundle = bundle_parent / "sdk-bundle"
    receipt = receipts / "export.json"
    result = portability.export_public_sdk_bundle(
        manifest,
        sha(manifest),
        bundle,
        confirmation=portability.EXPORT_CONFIRMATION,
        receipt_out=receipt,
    )
    return source_profile, manifest, bundle, receipt, result


def test_export_creates_exact_public_bundle_and_negative_authority(
    tmp_path, monkeypatch, supported_host
):
    _profile, manifest, bundle, receipt, result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )

    validated = portability.validate_public_sdk_bundle(
        bundle,
        expected_sdk_manifest_sha256=sha(manifest),
    )
    stored = json.loads(receipt.read_text(encoding="ascii"))
    assert result == stored
    assert result["result"] == "CREATED"
    assert validated["sdk_manifest_sha256"] == sha(manifest)
    assert result["authority"] == portability.NEGATIVE_AUTHORITY
    assert result["authority"]["credential_access"] is False
    assert result["authority"]["exchange_contact"] is False
    assert result["authority"]["scheduler_mutation"] is False
    assert result["authority"]["live_trading_authority"] is False
    assert datetime.fromisoformat(result["created_at_utc"]).tzinfo is not None
    assert result["host"]["execution_host_id"] == supported_host["execution_host_id"]
    assert result["host"]["execution_host_id_contract"] == (
        "international_live_execution_host_v2:windows_machine_guid"
    )
    portability._verify_self_hash(stored, "receipt_sha256")


def test_bundle_validation_defaults_to_the_repository_exact_sdk(
    tmp_path, monkeypatch, supported_host
):
    _profile, _manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )

    with pytest.raises(portability.LiveSdkPortabilityError, match="expected exact"):
        portability.validate_public_sdk_bundle(bundle)


def test_export_requires_exact_literal_and_never_overwrites_conflict(
    tmp_path, monkeypatch, supported_host
):
    source_profile, manifest = build_sdk(tmp_path / "source")
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: source_profile.resolve()
    )
    parent = tmp_path / "public"
    receipts = tmp_path / "receipts"
    parent.mkdir()
    receipts.mkdir()
    bundle = parent / "sdk-bundle"
    bundle.mkdir()
    marker = bundle / "do-not-overwrite.txt"
    marker.write_text("owner data", encoding="utf-8")

    with pytest.raises(portability.LiveSdkPortabilityError, match="confirmation"):
        portability.export_public_sdk_bundle(
            manifest,
            sha(manifest),
            bundle,
            confirmation="yes",
            receipt_out=receipts / "wrong-literal.json",
        )
    with pytest.raises(portability.LiveSdkPortabilityError):
        portability.export_public_sdk_bundle(
            manifest,
            sha(manifest),
            bundle,
            confirmation=portability.EXPORT_CONFIRMATION,
            receipt_out=receipts / "conflict.json",
        )
    assert marker.read_text(encoding="utf-8") == "owner data"


def test_export_failure_removes_its_private_staging_tree(
    tmp_path, monkeypatch, supported_host
):
    source_profile, manifest = build_sdk(tmp_path / "source")
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: source_profile.resolve()
    )
    parent = tmp_path / "public"
    receipts = tmp_path / "receipts"
    parent.mkdir()
    receipts.mkdir()

    def fail_copy(*_args, **_kwargs):
        raise portability.LiveSdkPortabilityError("injected copy failure")

    monkeypatch.setattr(portability, "_copy_tree_new", fail_copy)
    with pytest.raises(portability.LiveSdkPortabilityError, match="copy failure"):
        portability.export_public_sdk_bundle(
            manifest,
            sha(manifest),
            parent / "sdk-bundle",
            confirmation=portability.EXPORT_CONFIRMATION,
            receipt_out=receipts / "failed-export.json",
        )

    assert not list(parent.glob(".sdk-bundle.staging-*"))
    assert not (parent / "sdk-bundle").exists()


def test_stale_staging_is_preserved_and_blocks_an_ambiguous_retry(tmp_path):
    stale = tmp_path / ".sdk-bundle.staging-prior"
    stale.mkdir()
    marker = stale / "owner.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(portability.LiveSdkPortabilityError, match="reviewed cleanup"):
        portability._new_staging(tmp_path, "sdk-bundle")

    assert marker.read_text(encoding="utf-8") == "preserve"


def test_rollback_requires_every_published_root_to_have_the_exact_state(tmp_path):
    destination = tmp_path / "published"
    source = tmp_path / "staging/source"
    destination.mkdir()
    source.mkdir(parents=True)

    failures = portability._rollback_published_roots([(destination, source)])

    assert failures
    assert destination.is_dir()
    assert source.is_dir()


def test_rollback_moves_an_exact_published_root_back_to_staging(tmp_path):
    destination = tmp_path / "published"
    source = tmp_path / "staging/source"
    source.parent.mkdir(parents=True)
    destination.mkdir()
    (destination / "artifact.txt").write_text("public", encoding="utf-8")

    failures = portability._rollback_published_roots([(destination, source)])

    assert failures == []
    assert not destination.exists()
    assert (source / "artifact.txt").read_text(encoding="utf-8") == "public"


def test_mutable_outputs_are_refused_inside_repository(
    tmp_path, monkeypatch, supported_host
):
    source_profile, manifest = build_sdk(tmp_path / "source")
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: source_profile.resolve()
    )
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(portability, "REPOSITORY_ROOT", repository.resolve())
    receipts = tmp_path / "receipts"
    receipts.mkdir()

    with pytest.raises(portability.LiveSdkPortabilityError, match="outside the repository"):
        portability.export_public_sdk_bundle(
            manifest,
            sha(manifest),
            repository / "forbidden-bundle",
            confirmation=portability.EXPORT_CONFIRMATION,
            receipt_out=receipts / "export.json",
        )
    with pytest.raises(portability.LiveSdkPortabilityError, match="outside the repository"):
        portability.audit_installed_sdk(
            manifest,
            sha(manifest),
            profile_root=source_profile,
            receipt_out=repository / "forbidden-receipt.json",
        )


def test_export_is_idempotent_for_an_exact_existing_bundle(
    tmp_path, monkeypatch, supported_host
):
    _profile, manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )
    before = {
        path.relative_to(bundle).as_posix(): sha(path)
        for path in bundle.rglob("*")
        if path.is_file()
    }
    second = portability.export_public_sdk_bundle(
        manifest,
        sha(manifest),
        bundle,
        confirmation=portability.EXPORT_CONFIRMATION,
        receipt_out=tmp_path / "receipts/second-export.json",
    )

    after = {
        path.relative_to(bundle).as_posix(): sha(path)
        for path in bundle.rglob("*")
        if path.is_file()
    }
    assert second["result"] == "ALREADY_PRESENT_EXACT"
    assert after == before


def test_import_creates_current_user_roots_and_exact_rerun_is_read_only(
    tmp_path, monkeypatch, supported_host
):
    _source, _manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )
    destination = tmp_path / "destination-profile"
    destination.mkdir()
    monkeypatch.setattr(
        portability,
        "EXPECTED_SDK_MANIFEST_SHA256",
        sha(bundle / portability.SDK_MANIFEST_NAME),
    )
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: destination.resolve()
    )

    first = portability.import_public_sdk_bundle(
        bundle,
        confirmation=portability.IMPORT_CONFIRMATION,
        receipt_out=tmp_path / "receipts/import.json",
    )
    before = {
        path.relative_to(destination).as_posix(): sha(path)
        for path in destination.rglob("*")
        if path.is_file()
    }
    second = portability.import_public_sdk_bundle(
        bundle,
        confirmation=portability.IMPORT_CONFIRMATION,
        receipt_out=tmp_path / "receipts/import-second.json",
    )
    after = {
        path.relative_to(destination).as_posix(): sha(path)
        for path in destination.rglob("*")
        if path.is_file()
    }

    assert first["result"] == "CREATED"
    assert second["result"] == "ALREADY_PRESENT_EXACT"
    assert before == after
    assert not list((destination / "ops").glob(".*.staging-*"))


def test_import_creates_distinct_nested_parents_below_the_shared_root(
    tmp_path, monkeypatch, supported_host
):
    source_profile, manifest = build_sdk(tmp_path / "source")
    (source_profile / "ops/a").mkdir()
    (source_profile / "ops/b").mkdir()
    shutil.move(
        source_profile / "ops/sdk-overlay",
        source_profile / "ops/a/sdk-overlay",
    )
    shutil.move(
        source_profile / "ops/sdk-wheelhouse",
        source_profile / "ops/b/sdk-wheelhouse",
    )
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["overlay"]["relative_path"] = "ops/a/sdk-overlay"
    manifest_payload["wheelhouse"]["relative_path"] = "ops/b/sdk-wheelhouse"
    manifest.write_text(
        json.dumps(manifest_payload, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: source_profile.resolve()
    )
    public = tmp_path / "public"
    receipts = tmp_path / "receipts"
    public.mkdir()
    receipts.mkdir()
    bundle = public / "sdk-bundle"
    portability.export_public_sdk_bundle(
        manifest,
        sha(manifest),
        bundle,
        confirmation=portability.EXPORT_CONFIRMATION,
        receipt_out=receipts / "nested-export.json",
    )

    destination = tmp_path / "destination-profile"
    destination.mkdir()
    monkeypatch.setattr(
        portability,
        "EXPECTED_SDK_MANIFEST_SHA256",
        sha(bundle / portability.SDK_MANIFEST_NAME),
    )
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: destination.resolve()
    )
    result = portability.import_public_sdk_bundle(
        bundle,
        confirmation=portability.IMPORT_CONFIRMATION,
        receipt_out=receipts / "nested-import.json",
    )

    assert result["result"] == "CREATED"
    assert (destination / "ops/a/sdk-overlay").is_dir()
    assert (destination / "ops/b/sdk-wheelhouse").is_dir()
    assert not list((destination / "ops").glob(".*.staging-*"))


def test_import_failure_removes_staging_and_empty_parents_for_retry(
    tmp_path, monkeypatch, supported_host
):
    _source, _manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )
    destination = tmp_path / "destination-profile"
    destination.mkdir()
    monkeypatch.setattr(
        portability,
        "EXPECTED_SDK_MANIFEST_SHA256",
        sha(bundle / portability.SDK_MANIFEST_NAME),
    )
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: destination.resolve()
    )

    def fail_validation(*_args, **_kwargs):
        raise portability.LiveSdkPortabilityError("injected staging failure")

    monkeypatch.setattr(
        portability,
        "_validate_sdk_component_exact",
        fail_validation,
    )
    with pytest.raises(portability.LiveSdkPortabilityError, match="staging failure"):
        portability.import_public_sdk_bundle(
            bundle,
            confirmation=portability.IMPORT_CONFIRMATION,
            receipt_out=tmp_path / "receipts/failed-import.json",
        )

    assert not list(destination.rglob(".international-live-sdk.staging-*"))
    assert not (destination / "ops").exists()


def test_import_pre_staging_failure_removes_new_destination_parents(
    tmp_path, monkeypatch, supported_host
):
    _source, _manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )
    destination = tmp_path / "destination-profile"
    destination.mkdir()
    monkeypatch.setattr(
        portability,
        "EXPECTED_SDK_MANIFEST_SHA256",
        sha(bundle / portability.SDK_MANIFEST_NAME),
    )
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: destination.resolve()
    )
    original_directory_validator = portability._absolute_existing_directory

    def fail_shared_parent(path, *, label):
        if label == "SDK shared destination parent":
            raise portability.LiveSdkPortabilityError("injected parent failure")
        return original_directory_validator(path, label=label)

    monkeypatch.setattr(
        portability,
        "_absolute_existing_directory",
        fail_shared_parent,
    )
    with pytest.raises(portability.LiveSdkPortabilityError, match="parent failure"):
        portability.import_public_sdk_bundle(
            bundle,
            confirmation=portability.IMPORT_CONFIRMATION,
            receipt_out=tmp_path / "receipts/failed-parent-import.json",
        )

    assert not (destination / "ops").exists()


def test_import_refuses_unbound_empty_directory_in_existing_overlay(
    tmp_path, monkeypatch, supported_host
):
    _source, _manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )
    destination = tmp_path / "destination-profile"
    destination.mkdir()
    monkeypatch.setattr(
        portability,
        "EXPECTED_SDK_MANIFEST_SHA256",
        sha(bundle / portability.SDK_MANIFEST_NAME),
    )
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: destination.resolve()
    )
    portability.import_public_sdk_bundle(
        bundle,
        confirmation=portability.IMPORT_CONFIRMATION,
        receipt_out=tmp_path / "receipts/import-empty-dir-setup.json",
    )
    (destination / "ops/sdk-overlay/unbound-empty").mkdir()

    with pytest.raises(portability.LiveSdkPortabilityError, match="empty directory"):
        portability.import_public_sdk_bundle(
            bundle,
            confirmation=portability.IMPORT_CONFIRMATION,
            receipt_out=tmp_path / "receipts/import-empty-dir-block.json",
        )


@pytest.mark.parametrize("present_component", ["sdk-overlay", "sdk-wheelhouse"])
def test_import_recovers_only_missing_root_after_exact_partial_hard_termination(
    tmp_path, monkeypatch, supported_host, present_component
):
    _source, _manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )
    destination = tmp_path / "destination-profile"
    destination_ops = destination / "ops"
    destination_ops.mkdir(parents=True)
    source_root = bundle / f"profile/ops/{present_component}"
    existing_root = destination_ops / present_component
    shutil.copytree(source_root, existing_root)
    before = {
        path.relative_to(existing_root).as_posix(): sha(path)
        for path in existing_root.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(
        portability,
        "EXPECTED_SDK_MANIFEST_SHA256",
        sha(bundle / portability.SDK_MANIFEST_NAME),
    )
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: destination.resolve()
    )

    recovered = portability.import_public_sdk_bundle(
        bundle,
        confirmation=portability.IMPORT_CONFIRMATION,
        receipt_out=tmp_path / f"receipts/recover-{present_component}.json",
    )

    after = {
        path.relative_to(existing_root).as_posix(): sha(path)
        for path in existing_root.rglob("*")
        if path.is_file()
    }
    missing_component = (
        "sdk-wheelhouse" if present_component == "sdk-overlay" else "sdk-overlay"
    )
    assert recovered["result"] == "RECOVERED_EXACT_PARTIAL"
    assert recovered["evidence"]["recovered_missing_component"] == (
        "wheelhouse" if present_component == "sdk-overlay" else "overlay"
    )
    assert recovered["public_filesystem_mutations"][
        "destination_sdk_root_count_created"
    ] == 1
    assert recovered["public_filesystem_mutations"][
        "partial_exact_recovery_performed"
    ] is True
    assert after == before
    assert (destination_ops / missing_component).is_dir()

    exact = portability.import_public_sdk_bundle(
        bundle,
        confirmation=portability.IMPORT_CONFIRMATION,
        receipt_out=tmp_path / f"receipts/recovered-exact-{present_component}.json",
    )
    assert exact["result"] == "ALREADY_PRESENT_EXACT"
    assert exact["public_filesystem_mutations"][
        "destination_sdk_root_count_created"
    ] == 0


def test_import_refuses_partial_or_tampered_destination_without_repair(
    tmp_path, monkeypatch, supported_host
):
    _source, _manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )
    destination = tmp_path / "destination-profile"
    partial = destination / "ops/sdk-overlay"
    partial.mkdir(parents=True)
    marker = partial / "owner.txt"
    marker.write_text("unchanged", encoding="utf-8")
    monkeypatch.setattr(
        portability,
        "EXPECTED_SDK_MANIFEST_SHA256",
        sha(bundle / portability.SDK_MANIFEST_NAME),
    )
    monkeypatch.setattr(
        portability, "_current_profile_root", lambda: destination.resolve()
    )

    with pytest.raises(portability.LiveSdkPortabilityError, match="partial"):
        portability.import_public_sdk_bundle(
            bundle,
            confirmation=portability.IMPORT_CONFIRMATION,
            receipt_out=tmp_path / "receipts/import-block.json",
        )

    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert not (destination / "ops/sdk-wheelhouse").exists()


def test_bundle_tamper_extra_file_and_duplicate_json_are_rejected(
    tmp_path, monkeypatch, supported_host
):
    _source, _manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )
    extra = bundle / "profile/extra.txt"
    extra.write_text("extra", encoding="utf-8")
    with pytest.raises(portability.LiveSdkPortabilityError, match="unexpected"):
        portability.validate_public_sdk_bundle(
            bundle,
            expected_sdk_manifest_sha256=sha(bundle / portability.SDK_MANIFEST_NAME),
        )
    extra.unlink()

    manifest = bundle / portability.BUNDLE_MANIFEST_NAME
    manifest.write_text('{"schema_version":"x","schema_version":"y"}\n')
    with pytest.raises(portability.LiveSdkPortabilityError, match="duplicate"):
        portability.validate_public_sdk_bundle(
            bundle,
            expected_sdk_manifest_sha256=sha(bundle / portability.SDK_MANIFEST_NAME),
        )


def test_bundle_manifest_must_retain_canonical_exact_bytes(
    tmp_path, monkeypatch, supported_host
):
    _source, _manifest, bundle, _receipt, _result = export_fixture(
        tmp_path, monkeypatch, supported_host
    )
    manifest = bundle / portability.BUNDLE_MANIFEST_NAME
    payload = json.loads(manifest.read_text(encoding="ascii"))
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")

    with pytest.raises(portability.LiveSdkPortabilityError, match="canonical JSON"):
        portability.validate_public_sdk_bundle(
            bundle,
            expected_sdk_manifest_sha256=sha(bundle / portability.SDK_MANIFEST_NAME),
        )


def test_receipt_refuses_changed_existing_output(
    tmp_path, monkeypatch, supported_host
):
    profile, manifest = build_sdk(tmp_path / "source")
    receipt = tmp_path / "receipt.json"
    receipt.write_text("owner data", encoding="utf-8")
    with pytest.raises(portability.LiveSdkPortabilityError, match="overwrite"):
        portability.audit_installed_sdk(
            manifest,
            sha(manifest),
            profile_root=profile,
            receipt_out=receipt,
        )
    assert receipt.read_text(encoding="utf-8") == "owner data"


def test_host_gate_requires_windows_x64_cpython_311(monkeypatch):
    monkeypatch.setattr(portability.os, "name", "posix")
    monkeypatch.setattr(portability.platform, "system", lambda: "Linux")
    monkeypatch.setattr(portability.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(portability.platform, "python_implementation", lambda: "PyPy")

    with pytest.raises(portability.LiveSdkPortabilityError, match="Windows x64"):
        portability._host_evidence()


def test_wheel_target_gate_rejects_incompatible_native_wheel():
    payload = {
        "wheelhouse": {
            "ordered_file_names": [
                "future-1.0.0-cp312-cp312-win_amd64.whl",
            ]
        }
    }

    with pytest.raises(portability.LiveSdkPortabilityError, match="incompatible"):
        portability._validate_wheel_target_contract(payload)


def test_unc_paths_are_rejected_before_filesystem_validation():
    with pytest.raises(portability.LiveSdkPortabilityError, match="network or device"):
        portability._reject_nonlocal_path(
            Path(r"\\server\share\sdk-bundle"),
            label="test bundle",
        )


def test_cli_exposes_no_credential_network_scheduler_capture_or_exchange_options():
    help_text = portability._parser().format_help().lower()
    assert "credential" not in help_text
    assert "network" not in help_text
    assert "scheduler" not in help_text
    assert "capture" not in help_text
    assert "exchange" not in help_text
