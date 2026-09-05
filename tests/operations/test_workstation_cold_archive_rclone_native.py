"""Opt-in native rclone checks using tiny, synthetic, local-only crypt data.

Set WEATHER_TEST_RCLONE_EXECUTABLE to an absolute executable path to run.
An absent setting skips; an explicitly invalid setting fails. No provisioned
archive config, DPAPI material, network remote, or real attempt is used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import pytest

from weather.operations import workstation_cold_archive_stage as stage


EXECUTABLE_ENV = "WEATHER_TEST_RCLONE_EXECUTABLE"
LEGACY_PARTIAL_SUFFIX = ".partial.cold-stage"
NATIVE_TIMEOUT_SECONDS = 30
SYNTHETIC_PASSWORD = "weather-native-rclone-fixture-not-a-secret"
PAYLOAD = b"synthetic native rclone archive fixture\n" * 32
ARCHIVE_ID = "synthetic-native-archive"


def _bounded_native_runner(
    arguments: Sequence[str],
    environment: Mapping[str, str],
    timeout_seconds: int,
    capture_stdout: bool,
) -> stage.ChildResult:
    # Reuse the real subprocess boundary: shell=False, hidden Windows child,
    # discarded stderr, and at most 64 KiB of captured stdout. Tiny fixtures
    # get a much shorter deadline than production copy/cryptcheck operations.
    assert not any(name.upper().startswith("RCLONE_") for name in environment)
    return stage._subprocess_runner(
        arguments,
        environment,
        min(timeout_seconds, NATIVE_TIMEOUT_SECONDS),
        capture_stdout,
    )


@dataclass(frozen=True)
class NativeCrypt:
    client: stage._RcloneClient
    source: Path
    ciphertext: Path
    version: str


@pytest.fixture
def native_crypt(tmp_path: Path) -> NativeCrypt:
    configured = os.environ.get(EXECUTABLE_ENV)
    if configured is None:
        pytest.skip(f"native rclone requires explicit {EXECUTABLE_ENV}")
    executable = Path(configured)
    if not configured.strip() or not executable.is_absolute():
        pytest.fail(f"{EXECUTABLE_ENV} must name an absolute regular executable")
    try:
        stage._regular_identity(executable, label="configured test rclone")
    except (OSError, stage.ArchiveStageError):
        pytest.fail(f"{EXECUTABLE_ENV} is not a usable regular executable")

    source = tmp_path / "source"
    ciphertext = tmp_path / "ciphertext"
    temporary = tmp_path / "child-temp"
    for directory in (source, ciphertext, temporary):
        directory.mkdir()
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("RCLONE_")
    }
    for name in ("TMP", "TEMP", "TMPDIR"):
        environment[name] = str(temporary)

    config = tmp_path / "synthetic-rclone.conf"
    config.write_text("", encoding="utf-8")
    # This public fixture string is intentionally safe in argv. Obscure uses
    # only this empty fixture config, never the attending user's config.
    obscured_result = _bounded_native_runner(
        [
            str(executable), "--config", str(config), "--ask-password=false",
            "--log-level", "ERROR", "--stats", "0",
            "obscure", SYNTHETIC_PASSWORD,
        ],
        environment,
        NATIVE_TIMEOUT_SECONDS,
        True,
    )
    assert obscured_result.returncode == 0, "native fixture password obscuring failed"
    obscured = obscured_result.stdout.decode("ascii").strip()
    assert obscured and "\n" not in obscured and "\r" not in obscured
    config.write_text(
        "[synthetic_crypt]\n"
        "type = crypt\n"
        f"remote = {ciphertext.as_posix()}\n"
        "filename_encryption = standard\n"
        "directory_name_encryption = true\n"
        "no_data_encryption = false\n"
        f"password = {obscured}\n",
        encoding="utf-8",
    )
    client = stage._RcloneClient(
        executable=executable,
        config=config,
        remote_name="synthetic_crypt",
        environment=environment,
        runner=_bounded_native_runner,
    )
    version = client.version()
    client.require_local_ciphertext_root(ciphertext)
    return NativeCrypt(client, source, ciphertext, version)


def _ciphertext_bytes(root: Path) -> dict[str, bytes]:
    # These tiny fixtures must never turn a verification failure into an
    # unbounded read of a destination tree or object.
    result = {}
    for index, path in enumerate(root.rglob("*")):
        assert index < 16, "unexpected native fixture ciphertext entry count"
        assert not path.is_symlink()
        if path.is_file():
            assert path.stat().st_size <= 64 * 1024
            with path.open("rb") as handle:
                content = handle.read(64 * 1024 + 1)
            assert len(content) <= 64 * 1024
            result[path.relative_to(root).as_posix()] = content
    return result


def test_native_legacy_partial_suffix_is_rejected(
    native_crypt: NativeCrypt, monkeypatch: pytest.MonkeyPatch
) -> None:
    (native_crypt.source / stage.ARCHIVE_FILENAME).write_bytes(PAYLOAD)
    assert len(LEGACY_PARTIAL_SUFFIX.encode("ascii")) > 16
    # Exercise the exact current client, substituting only the historical
    # invalid value. Every create-only flag stays in the native command.
    monkeypatch.setattr(stage, "RCLONE_PARTIAL_SUFFIX", LEGACY_PARTIAL_SUFFIX)
    with pytest.raises(stage.ArchiveStageError) as caught:
        native_crypt.client.copy_create_only(native_crypt.source, ARCHIVE_ID)
    assert caught.value.code == "rclone_create_only_copy_failed"
    assert not list(native_crypt.ciphertext.iterdir())
    assert (native_crypt.source / stage.ARCHIVE_FILENAME).read_bytes() == PAYLOAD


def test_native_fresh_copy_and_cryptcheck_pass(
    native_crypt: NativeCrypt, record_testsuite_property
) -> None:
    record_testsuite_property("rclone_version", native_crypt.version)
    assert 0 < len(stage.RCLONE_PARTIAL_SUFFIX.encode("ascii")) <= 16
    (native_crypt.source / stage.ARCHIVE_FILENAME).write_bytes(PAYLOAD)
    native_crypt.client.require_destination_absent(ARCHIVE_ID)
    native_crypt.client.copy_create_only(native_crypt.source, ARCHIVE_ID)
    native_crypt.client.cryptcheck(native_crypt.source, ARCHIVE_ID)
    ciphertext = _ciphertext_bytes(native_crypt.ciphertext)
    assert len(ciphertext) == 1
    encrypted = next(iter(ciphertext.values()))
    assert len(encrypted) > len(PAYLOAD)
    assert PAYLOAD not in encrypted
    assert (native_crypt.source / stage.ARCHIVE_FILENAME).read_bytes() == PAYLOAD


@pytest.mark.parametrize("change_source", [False, True], ids=["identical", "changed"])
def test_native_existing_destination_is_rejected_without_modification(
    native_crypt: NativeCrypt, change_source: bool
) -> None:
    source_file = native_crypt.source / stage.ARCHIVE_FILENAME
    source_file.write_bytes(PAYLOAD)
    native_crypt.client.copy_create_only(native_crypt.source, ARCHIVE_ID)
    native_crypt.client.cryptcheck(native_crypt.source, ARCHIVE_ID)
    before = _ciphertext_bytes(native_crypt.ciphertext)
    assert len(before) == 1
    expected_source = PAYLOAD + b"changed" if change_source else PAYLOAD
    if change_source:
        source_file.write_bytes(expected_source)
    # This deliberate collision is confined to this test's synthetic data.
    # Call copy directly so the native flags, rather than the earlier absence
    # guard, must refuse both matching and differing pre-existing ciphertext.
    with pytest.raises(stage.ArchiveStageError) as caught:
        native_crypt.client.copy_create_only(native_crypt.source, ARCHIVE_ID)
    assert caught.value.code == "rclone_create_only_copy_failed"
    assert _ciphertext_bytes(native_crypt.ciphertext) == before
    assert source_file.read_bytes() == expected_source


def test_native_empty_source_is_rejected(native_crypt: NativeCrypt) -> None:
    with pytest.raises(stage.ArchiveStageError) as caught:
        native_crypt.client.copy_create_only(native_crypt.source, ARCHIVE_ID)
    assert caught.value.code == "rclone_create_only_copy_failed"
    assert _ciphertext_bytes(native_crypt.ciphertext) == {}
    assert not list(native_crypt.source.iterdir())
