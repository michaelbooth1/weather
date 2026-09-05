from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from weather.operations import workstation_cold_archive_stage as stage


TOOL_IDENTITY = {
    "tool": stage.TOOL,
    "module_sha256": "1" * 64,
    "module_bytes": 123,
    "git_commit": "2" * 40,
    "git_tree": "3" * 40,
    "git_branch": "codex/test",
    "git_dirty": False,
    "python": "3.11.9",
}


class FakeRclone:
    def __init__(self, layout: dict[str, Path]):
        self.layout = layout
        self.calls: list[tuple[list[str], dict[str, str], int, bool]] = []
        self.remote_exists = False
        self.config_fails = False
        self.config_type = "crypt"
        self.config_remote: Path | None = layout["ciphertext"]
        self.cryptcheck_fails = False
        self.copy_error: stage.ArchiveStageError | None = None
        self.expected_ciphertext = "encrypted-dir/encrypted-object"
        self.extra_ciphertexts: list[str] = []
        self.change_preexisting = False
        self.remove_preexisting = False
        self.drift_source_after_copy = False

    def __call__(
        self,
        arguments: list[str] | tuple[str, ...],
        environment: dict[str, str],
        timeout_seconds: int,
        capture_stdout: bool,
    ) -> stage.ChildResult:
        argv = list(arguments)
        env = dict(environment)
        self.calls.append((argv, env, timeout_seconds, capture_stdout))
        assert stage.CONFIG_PASS_ENV in env
        assert env[stage.CONFIG_PASS_ENV] == "fixture-passphrase"
        command = argv[8:]
        if command[:3] == ["config", "encryption", "check"]:
            return stage.ChildResult(1 if self.config_fails else 0)
        if command[:2] == ["config", "redacted"]:
            configured_remote = str(self.config_remote or "fixture_cloud:")
            output = (
                f"[{command[2]}]\n"
                f"type = {self.config_type}\n"
                f"remote = {configured_remote}\n"
                "password = XXX\n"
            ).encode()
            return stage.ChildResult(0, output)
        if command[:1] == ["version"]:
            return stage.ChildResult(0, b"rclone v1.72.0\n- fixture\n")
        if command[:1] == ["cryptdecode"]:
            logical = command[-1]
            output = f"{logical}\t{self.expected_ciphertext}\n".encode()
            return stage.ChildResult(0, output)
        if command[:1] == ["lsjson"]:
            return stage.ChildResult(0 if self.remote_exists else 3)
        if command[:1] == ["copy"]:
            if self.copy_error is not None:
                raise self.copy_error
            target = self.layout["ciphertext"] / self.expected_ciphertext
            target.parent.mkdir(parents=True, exist_ok=True)
            archive = self.layout["staging"] / self.layout["archive_id"] / stage.ARCHIVE_FILENAME
            target.write_bytes(b"encrypted-fixture:" + archive.read_bytes())
            for relative in self.extra_ciphertexts:
                extra = self.layout["ciphertext"] / relative
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_bytes(b"unexpected")
            preexisting = self.layout["ciphertext"] / "preexisting.bin"
            if self.change_preexisting:
                preexisting.write_bytes(b"changed-existing")
            if self.remove_preexisting:
                preexisting.unlink()
            if self.drift_source_after_copy:
                self.layout["source"].write_bytes(b"post-copy drift")
            return stage.ChildResult(0)
        if command[:1] == ["cryptcheck"]:
            return stage.ChildResult(1 if self.cryptcheck_fails else 0)
        raise AssertionError(f"unexpected fake rclone command: {command}")


def _layout(tmp_path: Path, *, archive_id: str = "archive-001") -> dict[str, Path]:
    paths = {
        "source_root": tmp_path / "source",
        "staging": tmp_path / "staging",
        "ciphertext": tmp_path / "ciphertext",
        "receipts": tmp_path / "receipts",
        "repo": tmp_path / "repo",
        "repo_data": tmp_path / "repo" / "data",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    source = paths["source_root"] / "rotated.log"
    source.write_bytes((b"fixture weather archive bytes\n" * 200) + b"tail")
    mtime_ns = 1_700_000_000_123_456_700
    os.utime(source, ns=(mtime_ns, mtime_ns))
    for name in ("config", "secret", "rclone"):
        filename = "rclone.exe" if name == "rclone" else f"{name}.bin"
        target = tmp_path / filename
        target.write_bytes(name.encode())
        paths[name] = target
    paths["source"] = source
    paths["archive_id"] = archive_id  # type: ignore[assignment]
    return paths


def _arguments(layout: dict[str, Path]) -> dict[str, object]:
    source = layout["source"]
    return {
        "provisional_mirror_copy": True,
        "source_root": layout["source_root"],
        "source_file": source,
        "source_size": source.stat().st_size,
        "source_mtime_utc": stage._format_mtime_utc(source.stat().st_mtime_ns),
        "staging_root": layout["staging"],
        "ciphertext_root": layout["ciphertext"],
        "receipt_root": layout["receipts"],
        "rclone_config": layout["config"],
        "dpapi_secret": layout["secret"],
        "rclone_executable": layout["rclone"],
        "crypt_remote_name": "fixture_crypt",
        "archive_id": layout["archive_id"],
        "repo_root": layout["repo"],
        "repo_data_root": layout["repo_data"],
        "secret_loader": lambda _path: stage.SecretMaterial.from_text(
            "fixture-passphrase"
        ),
        "tool_identity": TOOL_IDENTITY,
        "wrapper_active": True,
    }


def _run(layout: dict[str, Path], fake: FakeRclone | None = None, **overrides):
    fake = fake or FakeRclone(layout)
    arguments = _arguments(layout)
    arguments.update(overrides)
    arguments["runner"] = fake
    return stage.stage_provisional_mirror_copy(**arguments), fake


def _receipt(layout: dict[str, Path]) -> dict:
    return json.loads(
        (
            layout["receipts"] / f"{layout['archive_id']}.receipt.json"
        ).read_text(encoding="utf-8")
    )


def _protect_windows_powershell_fixture(
    tmp_path: Path, plaintext: str
) -> Path:
    """Use the real default PowerShell DPAPI format for synthetic text only."""

    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    assert powershell.is_file(), "Windows PowerShell fixture producer is required"
    script = tmp_path / "protect-fixture.ps1"
    secret_path = tmp_path / "fixture-pass.dpapi"
    script.write_text(
        r'''
param([string]$OutputPath, [string]$FixtureUtf16Base64)
$ErrorActionPreference = "Stop"
$fixtureBytes = [Convert]::FromBase64String($FixtureUtf16Base64)
$fixtureText = [Text.Encoding]::Unicode.GetString($fixtureBytes)
$fixtureSecure = ConvertTo-SecureString -String $fixtureText -AsPlainText -Force
try {
    $protected = ConvertFrom-SecureString -SecureString $fixtureSecure
    [IO.File]::WriteAllText($OutputPath, $protected + "`r`n", [Text.Encoding]::ASCII)
}
finally {
    $fixtureSecure.Dispose()
    [Array]::Clear($fixtureBytes, 0, $fixtureBytes.Length)
    $fixtureText = ""
}
'''.lstrip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            str(secret_path),
            base64.b64encode(plaintext.encode("utf-16-le")).decode("ascii"),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env={
            name: value
            for name, value in os.environ.items()
            if not name.upper().startswith("RCLONE_")
        },
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == b""
    return secret_path


@pytest.mark.skipif(os.name != "nt", reason="real CurrentUser DPAPI requires Windows")
@pytest.mark.parametrize("plaintext", ("fixture-passphrase", "fixture-\u00e9-\u96e8-\U0001f512"))
def test_dpapi_recovers_real_windows_powershell_fixtures(
    tmp_path: Path, plaintext: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _protect_windows_powershell_fixture(tmp_path, plaintext)
    protected_before = path.read_bytes()

    material = stage._load_dpapi_secret(path)
    try:
        assert material.text() == plaintext
        assert path.read_bytes() == protected_before
    finally:
        material.wipe()
    assert material.utf16_bytes == bytearray(len(plaintext.encode("utf-16-le")))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.skipif(os.name != "nt", reason="real CurrentUser DPAPI requires Windows")
def test_native_dpapi_failure_retains_numeric_error_without_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = _layout(tmp_path)
    # Valid ASCII hex, deliberately too short to be a native DPAPI blob.
    # This exercises CryptUnprotectData itself, not a substituted loader.
    layout["secret"].write_text("00", encoding="ascii")
    fake = FakeRclone(layout)
    with pytest.raises(stage.ArchiveStageError) as caught:
        _run(layout, fake, secret_loader=stage._load_dpapi_secret)

    error = caught.value
    assert isinstance(error, stage._DpapiRecoveryError)
    assert error.code == "dpapi_decryption_failed"
    assert type(error.winerror) is int and error.winerror > 0
    assert str(error) == f"DPAPI CurrentUser recovery failed (winerror={error.winerror})"
    receipt = _receipt(layout)
    assert receipt["dpapi_winerror"] == error.winerror
    assert receipt["status"] == "FAIL_CLOSED"
    assert stage.receipt_hash_valid(receipt)
    assert receipt["encrypted_object"]["state"] == "copy_not_attempted"
    assert receipt["verification"]["source_initial_hash_stable"] == "NOT_RUN"
    assert receipt["verification"]["deterministic_compression"] == "NOT_RUN"
    assert not (layout["staging"] / layout["archive_id"]).exists()
    assert receipt["source_retained"] is True
    assert receipt["cleanup_eligible"] is False
    assert receipt["deletion_authorized"] is False
    assert layout["source"].exists()
    assert layout["secret"].read_bytes() == b"00"
    assert not fake.calls
    assert "error_message" not in receipt
    assert str(layout["secret"]) not in json.dumps(receipt)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_dpapi_receipt_retains_only_allowlisted_numeric_diagnostic(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    with pytest.raises(TypeError, match="must be an integer"):
        stage._DpapiRecoveryError("fixture-secret")  # type: ignore[arg-type]

    def fail_dpapi(_path: Path) -> stage.SecretMaterial:
        error = stage._DpapiRecoveryError(13)
        # Even an accidental exception message must never enter public evidence.
        error.args = ("fixture-passphrase raw-blob must-not-be-persisted",)
        raise error

    with pytest.raises(stage.ArchiveStageError):
        _run(layout, fake, secret_loader=fail_dpapi)

    receipt = _receipt(layout)
    assert receipt["error_code"] == "dpapi_decryption_failed"
    assert receipt["dpapi_winerror"] == 13
    assert receipt["schema_version"] == stage.RECEIPT_SCHEMA_VERSION
    assert stage.receipt_hash_valid(receipt)
    assert "fixture-passphrase" not in json.dumps(receipt)
    assert "raw-blob" not in json.dumps(receipt)
    assert not fake.calls


def test_default_off_and_wrapper_required(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    arguments = _arguments(layout)
    with pytest.raises(stage.ArchiveStageError, match="provisional"):
        stage.stage_provisional_mirror_copy(
            **{**arguments, "provisional_mirror_copy": False}
        )
    with pytest.raises(stage.ArchiveStageError, match="wrapper"):
        stage.stage_provisional_mirror_copy(**{**arguments, "wrapper_active": False})
    assert not any(layout["staging"].iterdir())


def test_source_escape_directory_and_special_are_rejected(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    outside = tmp_path / "outside.log"
    outside.write_bytes(b"outside")
    with pytest.raises(stage.ArchiveStageError, match="escapes"):
        _run(
            layout,
            source_file=outside,
            source_size=outside.stat().st_size,
            source_mtime_utc=stage._format_mtime_utc(outside.stat().st_mtime_ns),
        )
    source_directory = layout["source_root"] / "directory"
    source_directory.mkdir()
    with pytest.raises(stage.ArchiveStageError, match="regular file"):
        _run(
            layout,
            source_file=source_directory,
            source_size=0,
            source_mtime_utc=stage._format_mtime_utc(
                source_directory.stat().st_mtime_ns
            ),
        )


def test_source_reparse_is_rejected_when_supported(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    link = layout["source_root"] / "link.log"
    try:
        link.symlink_to(layout["source"])
    except OSError:
        pytest.skip("test host cannot create a symlink")
    with pytest.raises(stage.ArchiveStageError, match="redirected"):
        _run(
            layout,
            source_file=link,
            source_size=layout["source"].stat().st_size,
            source_mtime_utc=stage._format_mtime_utc(
                layout["source"].stat().st_mtime_ns
            ),
        )


def test_output_root_reparse_is_rejected_when_supported(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    real_staging = tmp_path / "real-staging"
    real_staging.mkdir()
    linked_staging = tmp_path / "linked-staging"
    try:
        linked_staging.symlink_to(real_staging, target_is_directory=True)
    except OSError:
        pytest.skip("test host cannot create a directory symlink")
    with pytest.raises(stage.ArchiveStageError, match="redirected"):
        _run(layout, staging_root=linked_staging)
    assert not any(real_staging.iterdir())


def test_special_source_identity_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    special = os.stat_result((0o010000, 0, 0, 1, 0, 0, 0, 0, 0, 0))
    monkeypatch.setattr(stage, "_lstat", lambda *_a, **_k: special)
    with pytest.raises(stage.ArchiveStageError, match="regular file"):
        stage._regular_identity(tmp_path / "special", label="source file")


@pytest.mark.parametrize("field", ("source_size", "source_mtime_utc"))
def test_source_size_and_mtime_pins_must_match(tmp_path: Path, field: str) -> None:
    layout = _layout(tmp_path)
    override = {field: 1 if field == "source_size" else "2000-01-01T00:00:00Z"}
    with pytest.raises(stage.ArchiveStageError, match="pin does not match"):
        _run(layout, **override)


def test_source_size_pin_has_a_fixed_one_gib_bound(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    with pytest.raises(stage.ArchiveStageError) as caught:
        _run(layout, source_size=stage.MAX_SOURCE_BYTES + 1)
    assert caught.value.code == "source_size_pin_invalid"


def test_repository_source_is_rejected(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    source = layout["repo"] / "tracked.log"
    source.write_bytes(b"repo source")
    with pytest.raises(stage.ArchiveStageError, match="repository paths"):
        _run(
            layout,
            source_root=layout["repo"],
            source_file=source,
            source_size=source.stat().st_size,
            source_mtime_utc=stage._format_mtime_utc(source.stat().st_mtime_ns),
        )


@pytest.mark.parametrize("kind", ("source", "repo_data", "other_output"))
def test_output_roots_cannot_overlap_protected_paths(
    tmp_path: Path, kind: str
) -> None:
    layout = _layout(tmp_path)
    if kind == "source":
        override = {"staging_root": layout["source_root"]}
    elif kind == "repo_data":
        override = {"receipt_root": layout["repo_data"]}
    else:
        override = {"ciphertext_root": layout["staging"]}
    with pytest.raises(stage.ArchiveStageError, match="overlap"):
        _run(layout, **override)


@pytest.mark.parametrize("collision", ("archive_id", "manifest", "receipt"))
def test_every_local_output_collision_is_rejected(
    tmp_path: Path, collision: str
) -> None:
    layout = _layout(tmp_path)
    if collision == "archive_id":
        (layout["staging"] / layout["archive_id"]).mkdir()
    else:
        (layout["receipts"] / f"{layout['archive_id']}.{collision}.json").write_text(
            "occupied", encoding="utf-8"
        )
    with pytest.raises(stage.ArchiveStageError, match="collision"):
        _run(layout)


def test_mapped_ciphertext_and_remote_collisions_are_rejected(tmp_path: Path) -> None:
    layout = _layout(tmp_path / "mapped")
    fake = FakeRclone(layout)
    mapped = layout["ciphertext"] / fake.expected_ciphertext
    mapped.parent.mkdir(parents=True)
    mapped.write_bytes(b"occupied")
    with pytest.raises(stage.ArchiveStageError, match="already exists"):
        _run(layout, fake)

    other = _layout(tmp_path / "remote")
    remote_fake = FakeRclone(other)
    remote_fake.remote_exists = True
    with pytest.raises(stage.ArchiveStageError, match="already exists"):
        _run(other, remote_fake)


@pytest.mark.parametrize("suffix", (".partial.cold", ".partial.cold-stage"))
def test_preexisting_rclone_partial_is_rejected_before_copy(
    tmp_path: Path, suffix: str
) -> None:
    layout = _layout(tmp_path)
    partial = layout["ciphertext"] / f"orphan.123456{suffix}"
    partial.write_bytes(b"retained partial")
    fake = FakeRclone(layout)
    with pytest.raises(stage.ArchiveStageError) as caught:
        _run(layout, fake)
    assert caught.value.code == "rclone_partial_collision"
    assert partial.read_bytes() == b"retained partial"
    assert not any(call[0][8] == "copy" for call in fake.calls)


def test_archive_bytes_are_deterministic_and_normalized(tmp_path: Path) -> None:
    source = tmp_path / "input.bin"
    source.write_bytes(b"same deterministic bytes" * 100)
    digest = stage._hash_regular_file(source, label="source")[1]
    outputs = [tmp_path / "one.tar.gz", tmp_path / "two.tar.gz"]
    for output in outputs:
        with source.open("rb") as handle:
            stage._write_deterministic_archive(
                handle,
                output,
                source_bytes=source.stat().st_size,
                expected_sha256=digest,
            )
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    with tarfile.open(outputs[0], "r:gz") as archive:
        members = archive.getmembers()
        assert len(members) == 1
        member = members[0]
        assert member.name == stage.ARCHIVE_MEMBER_NAME
        assert member.mtime == 0
        assert member.uid == member.gid == 0
        assert member.uname == member.gname == ""
        assert member.mode == 0o600


def test_dpapi_and_config_validation_fail_closed(tmp_path: Path) -> None:
    layout = _layout(tmp_path / "dpapi")

    def fail_dpapi(_path: Path) -> stage.SecretMaterial:
        raise stage.ArchiveStageError("dpapi_decryption_failed", "DPAPI failed")

    with pytest.raises(stage.ArchiveStageError, match="DPAPI failed"):
        _run(layout, secret_loader=fail_dpapi)
    receipt = _receipt(layout)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["error_code"] == "dpapi_decryption_failed"
    assert "dpapi_winerror" not in receipt

    config_layout = _layout(tmp_path / "config")
    fake = FakeRclone(config_layout)
    fake.config_fails = True
    with pytest.raises(stage.ArchiveStageError, match="encrypted-config"):
        _run(config_layout, fake)
    assert _receipt(config_layout)["error_code"] == "rclone_config_encryption_failed"


@pytest.mark.parametrize("failure", ("dpapi", "encrypted_config", "remote_binding"))
def test_encryption_preflight_refuses_before_any_source_content_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    material = stage.SecretMaterial.from_text("fixture-passphrase")
    expected_code = {
        "dpapi": "dpapi_decryption_failed",
        "encrypted_config": "rclone_config_encryption_failed",
        "remote_binding": "rclone_remote_not_local_crypt",
    }[failure]

    def secret_loader(_path: Path) -> stage.SecretMaterial:
        if failure == "dpapi":
            raise stage._DpapiRecoveryError(5)
        return material

    if failure == "encrypted_config":
        fake.config_fails = True
    elif failure == "remote_binding":
        fake.config_remote = None

    original_open = Path.open

    def refuse_source_open(path, *args, **kwargs):
        if path == layout["source"]:
            pytest.fail("source was opened before encryption preflight passed")
        return original_open(path, *args, **kwargs)

    def refuse_source_work(*_args, **_kwargs):
        pytest.fail("source hashing or compression ran before encryption preflight passed")

    monkeypatch.setattr(Path, "open", refuse_source_open)
    monkeypatch.setattr(stage, "_hash_open_handle", refuse_source_work)
    monkeypatch.setattr(stage, "_write_deterministic_archive", refuse_source_work)
    with pytest.raises(stage.ArchiveStageError) as caught:
        _run(layout, fake, secret_loader=secret_loader)
    assert caught.value.code == expected_code

    receipt = _receipt(layout)
    assert stage.receipt_hash_valid(receipt)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["verification"]["source_initial_hash_stable"] == "NOT_RUN"
    assert receipt["verification"]["deterministic_compression"] == "NOT_RUN"
    assert receipt["encrypted_object"]["state"] == "copy_not_attempted"
    assert receipt["source_retained"] is True
    assert receipt["cleanup_eligible"] is False
    assert receipt["deletion_authorized"] is False
    assert not (layout["staging"] / layout["archive_id"]).exists()
    assert not any(call[0][8] == "copy" for call in fake.calls)
    assert stage.CONFIG_PASS_ENV not in os.environ
    if failure == "dpapi":
        assert not fake.calls
    else:
        assert material.utf16_bytes == bytearray(len("fixture-passphrase") * 2)
    # A preflight failure still spends the immutable receipt namespace.
    with pytest.raises(stage.ArchiveStageError, match="collision"):
        _run(layout, fake, secret_loader=secret_loader)


@pytest.mark.parametrize("changed_input", ("config", "secret", "rclone"))
def test_supporting_input_drift_during_compression_blocks_later_client_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_input: str
) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    material = stage.SecretMaterial.from_text("fixture-passphrase")
    original_archive = stage._write_deterministic_archive

    def change_supporting_input(*args, **kwargs):
        result = original_archive(*args, **kwargs)
        layout[changed_input].write_bytes(b"changed supporting input with a new size")
        fake.config_remote = None
        return result

    monkeypatch.setattr(stage, "_write_deterministic_archive", change_supporting_input)
    with pytest.raises(stage.ArchiveStageError) as caught:
        _run(layout, fake, secret_loader=lambda _path: material)
    assert caught.value.code == "supporting_input_drift"
    assert [call[0][8] for call in fake.calls] == ["config", "version", "config"]
    receipt = _receipt(layout)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["encrypted_object"]["state"] == "copy_not_attempted"
    assert receipt["verification"]["deterministic_compression"] == "PASS"
    assert receipt["verification"]["supporting_inputs_stable"] == "NOT_RUN"
    assert receipt["source_retained"] is True
    assert receipt["deletion_authorized"] is False
    assert stage.receipt_hash_valid(receipt)
    assert material.utf16_bytes == bytearray(len("fixture-passphrase") * 2)


@pytest.mark.parametrize("misbinding", ("cloud", "wrong_root"))
def test_root_binding_is_rechecked_after_compression_without_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, misbinding: str
) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    config_before = stage._regular_identity(layout["config"], label="fixture config")
    material = stage.SecretMaterial.from_text("fixture-passphrase")
    other_root = tmp_path / "other-ciphertext"
    other_root.mkdir()
    original_archive = stage._write_deterministic_archive

    def change_returned_root(*args, **kwargs):
        result = original_archive(*args, **kwargs)
        fake.config_remote = None if misbinding == "cloud" else other_root
        return result

    monkeypatch.setattr(stage, "_write_deterministic_archive", change_returned_root)
    with pytest.raises(stage.ArchiveStageError) as caught:
        _run(layout, fake, secret_loader=lambda _path: material)
    assert caught.value.code == (
        "rclone_remote_not_local_crypt" if misbinding == "cloud"
        else "rclone_ciphertext_root_mismatch"
    )
    assert stage._regular_identity(layout["config"], label="fixture config") == config_before
    assert [call[0][8] for call in fake.calls] == [
        "config", "version", "config", "config", "config"
    ]
    receipt = _receipt(layout)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["encrypted_object"]["state"] == "copy_not_attempted"
    assert receipt["verification"]["rclone_local_ciphertext_root"] == "NOT_RUN"
    assert receipt["verification"]["supporting_inputs_stable"] == "NOT_RUN"
    assert receipt["source_retained"] is True
    assert receipt["deletion_authorized"] is False
    assert stage.receipt_hash_valid(receipt)
    assert material.utf16_bytes == bytearray(len("fixture-passphrase") * 2)


@pytest.mark.parametrize("misbinding", ("cloud", "wrong_root", "wrong_type"))
def test_crypt_remote_must_wrap_the_exact_local_ciphertext_root(
    tmp_path: Path, misbinding: str
) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    if misbinding == "cloud":
        fake.config_remote = None
    elif misbinding == "wrong_root":
        wrong_root = tmp_path / "other-ciphertext"
        wrong_root.mkdir()
        fake.config_remote = wrong_root
    else:
        fake.config_type = "drive"
    with pytest.raises(stage.ArchiveStageError) as caught:
        _run(layout, fake)
    assert caught.value.code in {
        "rclone_remote_not_local_crypt",
        "rclone_ciphertext_root_mismatch",
    }
    assert not any(call[0][8] == "copy" for call in fake.calls)
    receipt = _receipt(layout)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["Drive_upload_performed"] is False


def test_forbidden_rclone_verb_never_reaches_child(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    called = False

    def runner(*_args):
        nonlocal called
        called = True
        return stage.ChildResult(0)

    client = stage._RcloneClient(
        executable=layout["rclone"],
        config=layout["config"],
        remote_name="fixture_crypt",
        environment={stage.CONFIG_PASS_ENV: "fixture-passphrase"},
        runner=runner,
    )
    for verb in sorted(stage.FORBIDDEN_RCLONE_VERBS):
        with pytest.raises(stage.ArchiveStageError, match="forbidden"):
            client._invoke((verb, "source", "dest"), timeout_key="copy")
    assert called is False


def test_timeout_kills_child(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePipe(io.BytesIO):
        pass

    class FakeProcess:
        def __init__(self):
            self.stdout = FakePipe()
            self.killed = False
            self.wait_count = 0

        def wait(self, timeout: int) -> int:
            self.wait_count += 1
            if self.wait_count == 1:
                raise stage.subprocess.TimeoutExpired("rclone", timeout)
            return 1

        def kill(self) -> None:
            self.killed = True

    process = FakeProcess()
    monkeypatch.setattr(stage.subprocess, "Popen", lambda *_a, **_k: process)
    with pytest.raises(stage.ArchiveStageError, match="timed out and was killed"):
        stage._subprocess_runner(["rclone", "version"], {}, 1, True)
    assert process.killed is True


def test_timeout_fails_closed_when_root_termination_is_not_proved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        def __init__(self):
            self.stdout = io.BytesIO()
            self.killed = False

        def wait(self, timeout: int) -> int:
            raise stage.subprocess.TimeoutExpired("rclone", timeout)

        def kill(self) -> None:
            self.killed = True

    process = FakeProcess()
    monkeypatch.setattr(stage.subprocess, "Popen", lambda *_a, **_k: process)
    with pytest.raises(stage.ArchiveStageError) as caught:
        stage._subprocess_runner(["rclone", "version"], {}, 1, True)
    assert caught.value.code == "rclone_termination_unproved"
    assert process.killed is True


def test_copy_timeout_writes_fail_closed_receipt(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    fake.copy_error = stage.ArchiveStageError(
        "rclone_timeout", "bounded rclone child timed out and was killed"
    )
    with pytest.raises(stage.ArchiveStageError, match="timed out"):
        _run(layout, fake)
    receipt = _receipt(layout)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["encrypted_object"]["state"] == "creation_state_ambiguous_retained"


def test_cryptcheck_difference_retains_ciphertext_and_receipts_failure(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    fake.cryptcheck_fails = True
    with pytest.raises(stage.ArchiveStageError, match="cryptcheck"):
        _run(layout, fake)
    ciphertext = layout["ciphertext"] / fake.expected_ciphertext
    assert ciphertext.is_file()
    receipt = _receipt(layout)
    assert stage.receipt_hash_valid(receipt)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["encrypted_object"]["state"] == "created_retained_unverified"
    assert receipt["encrypted_object"]["identity"]["sha256"]
    assert receipt["cleanup_eligible"] is False
    assert receipt["deletion_authorized"] is False


@pytest.mark.parametrize("failure", ("unexpected", "multiple", "changed", "removed"))
def test_ciphertext_delta_rejects_unexpected_multiple_or_changed_files(
    tmp_path: Path, failure: str
) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    preexisting = layout["ciphertext"] / "preexisting.bin"
    preexisting.write_bytes(b"existing")
    if failure == "unexpected":
        fake.expected_ciphertext = "different-than-mapped.bin"
        # Return mapping to the normal name, but create the changed fake name.
        mapped = "encrypted-dir/encrypted-object"

        original = fake.__call__

        def mismatched(arguments, environment, timeout_seconds, capture_stdout):
            command = list(arguments)[8:]
            if command[:1] == ["cryptdecode"]:
                logical = command[-1]
                return stage.ChildResult(0, f"{logical}\t{mapped}\n".encode())
            return original(arguments, environment, timeout_seconds, capture_stdout)

        runner = mismatched
    elif failure == "multiple":
        fake.extra_ciphertexts = ["extra.bin"]
        runner = fake
    elif failure == "changed":
        fake.change_preexisting = True
        runner = fake
    else:
        fake.remove_preexisting = True
        runner = fake
    with pytest.raises(stage.ArchiveStageError, match="ciphertext"):
        _run(layout, runner)  # type: ignore[arg-type]
    assert _receipt(layout)["status"] == "FAIL_CLOSED"


def test_source_post_drift_fails_after_verified_ciphertext(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    fake.drift_source_after_copy = True
    with pytest.raises(stage.ArchiveStageError, match="source changed"):
        _run(layout, fake)
    receipt = _receipt(layout)
    assert receipt["encrypted_object"]["state"] == "verified_retained"
    assert receipt["production_identity_not_proved"] is True


def test_source_drift_during_initial_hash_fails_before_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    original_hash = stage._hash_open_handle
    calls = 0

    def drift_after_hash(handle):
        nonlocal calls
        calls += 1
        result = original_hash(handle)
        if calls == 1:
            layout["source"].write_bytes(b"changed while initial hash completed")
        return result

    monkeypatch.setattr(stage, "_hash_open_handle", drift_after_hash)
    with pytest.raises(stage.ArchiveStageError, match="initial hash"):
        _run(layout, fake)
    assert [call[0][8] for call in fake.calls] == ["config", "version", "config"]
    assert not any(call[0][8] == "copy" for call in fake.calls)
    assert _receipt(layout)["status"] == "FAIL_CLOSED"


def test_manifest_write_failure_cannot_emit_a_pass_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)

    def fail_manifest(*_args, **_kwargs):
        raise stage.ArchiveStageError(
            "manifest_write_failed", "manifest publication failed"
        )

    monkeypatch.setattr(stage, "_write_json_create_only", fail_manifest)
    with pytest.raises(stage.ArchiveStageError, match="manifest publication failed"):
        _run(layout)
    receipt = _receipt(layout)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["error_code"] == "manifest_write_failed"
    assert receipt["encrypted_object"]["state"] == "verified_retained"
    assert stage.receipt_hash_valid(receipt)


def test_success_never_deletes_and_writes_self_hashed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)
    fake = FakeRclone(layout)
    source_before = layout["source"].read_bytes()
    ambient = "ambient-must-be-removed"
    monkeypatch.setenv(stage.CONFIG_PASS_ENV, ambient)
    result, fake = _run(layout, fake)
    assert result["status"] == "PASS"
    assert layout["source"].read_bytes() == source_before
    assert layout["source"].exists()
    assert stage.CONFIG_PASS_ENV not in os.environ
    assert all("fixture-passphrase" not in token for call in fake.calls for token in call[0])
    copy_call = next(call[0] for call in fake.calls if call[0][8] == "copy")
    partial_suffix = copy_call[copy_call.index("--partial-suffix") + 1]
    assert 0 < len(partial_suffix.encode("utf-8")) <= 16
    for token in (
        "--immutable",
        "--ignore-times",
        "--error-on-no-transfer",
        "--transfers",
        "--checkers",
    ):
        assert token in copy_call
    assert "sync" not in copy_call
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert stage.manifest_hash_valid(manifest)
    assert stage.receipt_hash_valid(receipt)
    assert receipt["manifest"]["manifest_hash"] == manifest["manifest_hash"]
    assert manifest["source"]["path_relative_to_source_root"] == "rotated.log"
    assert manifest["source"]["sha256"]
    assert manifest["compression"]["sha256"]
    assert manifest["ciphertext"]["sha256"]
    assert set(manifest["verification"].values()) == {"PASS"}
    for payload in (manifest, receipt):
        assert payload["source_retained"] is True
        assert payload["Drive_upload_performed"] is False
        assert payload["restore_performed"] is False
        assert payload["production_identity_not_proved"] is True
        assert payload["cleanup_eligible"] is False
        assert payload["deletion_authorized"] is False


def test_ambient_config_password_is_removed_before_early_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)
    monkeypatch.setenv(stage.CONFIG_PASS_ENV, "ambient-must-not-reach-any-child")
    with pytest.raises(stage.ArchiveStageError):
        _run(layout, source_size=stage.MAX_SOURCE_BYTES + 1)
    assert stage.CONFIG_PASS_ENV not in os.environ


def test_module_contains_no_source_cleanup_executor() -> None:
    source = Path(stage.__file__).read_text(encoding="utf-8")
    assert ".unlink(" not in source
    assert ".rmdir(" not in source
    assert "os.remove(" not in source
    assert "os.unlink(" not in source
    assert "shutil" not in source
    assert "source_file.unlink" not in source
    assert "source_file.rename" not in source
    assert "source_file.replace" not in source
    assert "shutil.move" not in source
    assert "rclone sync" not in source
    assert "rclone delete" not in source
    assert "rclone purge" not in source


def test_ambient_rclone_overrides_never_reach_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)
    monkeypatch.setenv("RCLONE_CONFIG_FIXTURE_CRYPT_REMOTE", "unintended_cloud:")
    monkeypatch.setenv("RCLONE_CRYPT_REMOTE", "unintended_cloud:")
    monkeypatch.setenv("RCLONE_DUMP", "bodies,auth")
    monkeypatch.setenv("RCLONE_LOG_FILE", "unintended-secret-log")
    result, fake = _run(layout)
    assert result["status"] == "PASS"
    for _, environment, _, _ in fake.calls:
        assert {
            name for name in environment if name.upper().startswith("RCLONE_")
        } == {stage.CONFIG_PASS_ENV}


@pytest.mark.parametrize("kind", ("manifest", "receipt"))
def test_corrupt_saved_evidence_never_returns_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    layout = _layout(tmp_path)
    original = stage._read_stable_bytes
    corrupt_path = layout["receipts"] / f"{layout['archive_id']}.{kind}.json"

    def corrupt_before_readback(path, **kwargs):
        if path == corrupt_path:
            raw = path.read_bytes()
            hash_field = b'"' + kind.encode() + b'_hash": "'
            offset = raw.index(hash_field) + len(hash_field)
            digit = b"0" if raw[offset:offset + 1] != b"0" else b"1"
            path.write_bytes(raw[:offset] + digit + raw[offset + 1:])
        return original(path, **kwargs)

    monkeypatch.setattr(stage, "_read_stable_bytes", corrupt_before_readback)
    with pytest.raises(stage.ArchiveStageError) as caught:
        _run(layout)
    assert caught.value.code == "evidence_readback_mismatch"
    assert layout["source"].exists()
    assert corrupt_path.exists()
    receipt = _receipt(layout)
    if kind == "manifest":
        assert receipt["status"] == "FAIL_CLOSED"
        assert stage.receipt_hash_valid(receipt)
    else:
        # The spent corrupted receipt is retained; it cannot be rewritten.
        assert not stage.receipt_hash_valid(receipt)
