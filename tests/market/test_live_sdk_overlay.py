from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from weather.market import live_sdk_overlay as overlay


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_fixture(tmp_path: Path, monkeypatch):
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
        "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        encoding="utf-8",
    )
    wheel_names = [
        "polymarket_client-0.6.0-py3-none-any.whl",
        "websockets-15.0.1-py3-none-any.whl",
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
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(overlay, "_profile_root", lambda: profile.resolve())
    return manifest, root, wheelhouse


def test_validator_binds_complete_overlay_and_ordered_wheelhouse(tmp_path, monkeypatch):
    manifest, root, wheelhouse = build_fixture(tmp_path, monkeypatch)

    result = overlay.validate_live_sdk_overlay(manifest, sha(manifest))

    assert result["status"] == "PASS"
    assert result["overlay"]["root"] == str(root.resolve())
    assert result["wheelhouse"]["root"] == str(wheelhouse.resolve())
    assert result["shared_environment_mutated"] is False

    file_hashes = overlay.validated_live_sdk_overlay_file_hashes(
        manifest, sha(manifest)
    )
    assert len(file_hashes) == result["overlay"]["file_count"]
    package_init = (root / "polymarket/__init__.py").resolve()
    assert file_hashes[str(package_init)] == sha(package_init)


def test_validator_accepts_explicit_profile_root_without_changing_runtime_root(
    tmp_path, monkeypatch
):
    manifest, root, wheelhouse = build_fixture(tmp_path, monkeypatch)
    explicit_profile = root.parents[1]
    monkeypatch.setattr(
        overlay,
        "_profile_root",
        lambda: (_ for _ in ()).throw(AssertionError("current profile was consulted")),
    )

    result = overlay.validate_live_sdk_overlay(
        manifest,
        sha(manifest),
        profile_root=explicit_profile,
    )

    assert result["overlay"]["root"] == str(root.resolve())
    assert result["wheelhouse"]["root"] == str(wheelhouse.resolve())
    assert "profile_root" not in inspect.signature(
        overlay.activate_live_sdk_overlay
    ).parameters


def test_explicit_profile_root_must_be_absolute_and_present(tmp_path, monkeypatch):
    manifest, _root, _wheelhouse = build_fixture(tmp_path, monkeypatch)

    with pytest.raises(overlay.LiveSdkOverlayError, match="absolute"):
        overlay.validate_live_sdk_overlay(
            manifest,
            sha(manifest),
            profile_root=Path("relative-profile"),
        )
    with pytest.raises(overlay.LiveSdkOverlayError, match="absent"):
        overlay.validate_live_sdk_overlay(
            manifest,
            sha(manifest),
            profile_root=(tmp_path / "absent").resolve(),
        )


def test_current_profile_rejects_ambient_profile_conflict(tmp_path, monkeypatch):
    profile = (tmp_path / "token-profile").resolve()
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "other-profile"))

    with pytest.raises(overlay.LiveSdkOverlayError, match="USERPROFILE"):
        overlay._reject_ambient_profile_conflict(profile)


@pytest.mark.parametrize("target", ["overlay", "wheelhouse", "manifest"])
def test_validator_rejects_every_tamper_class(tmp_path, monkeypatch, target):
    manifest, root, wheelhouse = build_fixture(tmp_path, monkeypatch)
    expected = sha(manifest)
    if target == "overlay":
        (root / "polymarket/__init__.py").write_text("tampered", encoding="utf-8")
    elif target == "wheelhouse":
        next(wheelhouse.iterdir()).write_bytes(b"tampered")
    else:
        manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(overlay.LiveSdkOverlayError):
        overlay.validate_live_sdk_overlay(manifest, expected)


def test_activation_proves_real_import_origin_and_post_import_tree(tmp_path, monkeypatch):
    manifest, root, _wheelhouse = build_fixture(tmp_path, monkeypatch)
    original_path = list(sys.path)
    monkeypatch.setattr(overlay, "_ACTIVATION", None)
    monkeypatch.setattr(overlay.importlib.util, "find_spec", lambda _name: None)
    sys.modules.pop("polymarket", None)
    try:
        result = overlay.activate_live_sdk_overlay(manifest, sha(manifest))
        assert result["process_path_activated"] is True
        assert result["post_import_revalidation"] == "PASS"
        assert Path(result["package_path"]).is_relative_to(root)
    finally:
        sys.path[:] = original_path
        sys.modules.pop("polymarket", None)
        overlay._ACTIVATION = None


def test_activation_rejects_tree_change_during_import(tmp_path, monkeypatch):
    manifest, root, _wheelhouse = build_fixture(tmp_path, monkeypatch)
    original_path = list(sys.path)
    original_import = overlay.importlib.import_module
    monkeypatch.setattr(overlay, "_ACTIVATION", None)
    monkeypatch.setattr(overlay.importlib.util, "find_spec", lambda _name: None)
    sys.modules.pop("polymarket", None)

    def changing_import(name):
        result = original_import(name)
        (root / "polymarket/__init__.py").write_text(
            '__version__ = "0.6.0"\n# changed during import\n',
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(overlay.importlib, "import_module", changing_import)
    try:
        with pytest.raises(overlay.LiveSdkOverlayError, match="changed"):
            overlay.activate_live_sdk_overlay(manifest, sha(manifest))
    finally:
        sys.path[:] = original_path
        sys.modules.pop("polymarket", None)
        overlay._ACTIVATION = None
