"""Small synthetic chunks, mocked transport, and optional installed-rclone proof."""
from contextlib import nullcontext
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import time
import tarfile

import pytest

from weather.operations import bulk_cold_archive_crypt as bulk
from weather.operations import production_cold_archive_stage as core
from weather.operations import workstation_cold_archive_stage as stage
from weather.schema_registry import schema_version

NATIVE_FILE_PIN = bulk._file_pin
NATIVE_DIRECTORY_PIN = core._directory_pin


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_evidence(path, value, field="receipt_hash"):
    value = dict(value)
    value.pop(field, None)
    core._write(path, core._seal(value, field))
    return sha(path)


class FixturePin:
    opened = []

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.opened.append(self.path)
        return self

    def __exit__(self, *args):
        pass

    def metadata(self):
        return stage._regular_identity(self.path, label="fixture pin")


class Runner:
    """A local-only byte wrapper standing in for native crypt, not encryption."""
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.config_extra = ""
        self.after = lambda command: None
        self.corrupt = False

    @staticmethod
    def mapping(logical):
        return "/".join("e-" + part for part in logical.split("/"))

    def __call__(self, args, environment, timeout_seconds, capture_stdout):
        assert 0 < timeout_seconds <= bulk.DEADLINE_SECONDS
        assert {k for k in environment if k.upper().startswith("RCLONE_")} == {"RCLONE_CONFIG_PASS"}
        assert environment["RCLONE_CONFIG_PASS"] == "synthetic-secret"
        command = list(args[8:])
        self.calls.append(command)
        stdout, code = b"", 0
        if command[:3] == ["config", "encryption", "check"]:
            pass
        elif command[:2] == ["config", "redacted"]:
            stdout = (f"[localcrypt]\ntype = crypt\nremote = {self.root}\n"
                      + self.config_extra).encode()
        elif command[0] == "version":
            stdout = b"rclone v1.70.0\n"
        elif command[0] == "cryptdecode":
            stdout = f"{command[-1]} {self.mapping(command[-1])}\n".encode()
        elif command[0] == "lsjson":
            logical = command[-1].split(":", 1)[1]
            code = 0 if (self.root / self.mapping(logical)).exists() else 3
        elif command[0] == "copy":
            if command[1].startswith("localcrypt:"):
                ciphertext = self.root / self.mapping(command[1].split(":", 1)[1])
                output = Path(command[2]) / "archive.tar.gz"
                with output.open("xb") as stream:
                    stream.write(ciphertext.read_bytes()[32:])
            else:
                source = Path(command[1])
                assert source.name == "archive.tar.gz" and source.is_file()
                logical = command[2].split(":", 1)[1] + "/archive.tar.gz"
                destination = self.root / self.mapping(logical)
                with destination.open("xb") as stream:
                    data = source.read_bytes()
                    stream.write(b"RCLONE\0\0" + bytes(24) + (data + b"bad" if self.corrupt else data))
                assert "--immutable" in command
        elif command[0] == "cryptcheck":
            assert command[command.index("--include") + 1] == "/archive.tar.gz"
            source = Path(command[1]) / "archive.tar.gz"
            logical = command[2].split(":", 1)[1] + "/archive.tar.gz"
            code = 0 if source.read_bytes() == (self.root / self.mapping(logical)).read_bytes()[32:] else 1
        else:
            pytest.fail("unexpected archive child")
        self.after(command)
        return stage.ChildResult(code, stdout)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    FixturePin.opened = []
    monkeypatch.setattr(bulk, "_file_pin", FixturePin)
    monkeypatch.setattr(core, "_directory_pin", lambda path: nullcontext())
    for name in ("inbox", "cipher", "out", "restore-cipher", "restore-out", "downloads", "support"):
        (tmp_path / name).mkdir()
    paths = {}
    for key in ("rclone_executable", "rclone_config", "dpapi_secret"):
        paths[key] = tmp_path / "support" / key
        paths[key].write_bytes(b"synthetic fixture support")
    members = {"event/a.csv": b"a,b\n1,2\n" * 20, "event/nested/b.jsonl": b'{"x":1}\n' * 30,
               "other/empty.csv": b""}
    archive = tmp_path / "inbox/archive.tar.gz"
    rows = []
    with archive.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="",
                                               mtime=0, compresslevel=1) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT,
                          encoding="utf-8") as output:
            for index, (name, data) in enumerate(sorted(members.items())):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o600, 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                output.addfile(info, io.BytesIO(data))
                rows.append({"path": name, "size_bytes": len(data), "mtime_ns": 1,
                             "device": 1, "file_id": index + 1, "allocated_bytes": len(data),
                             "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"schema_version": schema_version("production_cold_archive_manifest"),
                "format": core.FORMAT, "plan_hash": "a" * 64, "plan_sha256": "b" * 64,
                "chunk_id": "chunk-00000", "source_root": "C:/production/data",
                "files": rows, "archive_bytes": archive.stat().st_size, "archive_sha256": sha(archive),
                "source_proof": "native_pinned_bytes_during_staging", **core.RETENTION}
    manifest_path = tmp_path / "inbox/manifest.json"
    manifest_sha = write_evidence(manifest_path, manifest, "manifest_hash")
    manifest = json.loads(manifest_path.read_text())
    receipt = {"schema_version": schema_version("production_cold_archive_receipt"),
               "status": "PASS", "plan_sha256": "b" * 64, "plan_hash": "a" * 64,
               "chunk_id": "chunk-00000", "manifest_hash": manifest["manifest_hash"],
               "verification": {"status": "PASS", "file_count": len(rows), "archive_sha256": sha(archive)},
               **core.RETENTION}
    receipt_path = tmp_path / "inbox/receipt.json"
    receipt_sha = write_evidence(receipt_path, receipt)
    runner = Runner(tmp_path / "cipher")
    tool = {"tool": bulk.TOOL, "module_sha256": "c" * 64, "module_bytes": 1,
            "git_commit": "d" * 40, "git_tree": "e" * 40, "git_branch": "fixture",
            "git_dirty": False, "python": "3.12"}
    arguments = dict(archive_file=archive, production_manifest=manifest_path,
                     production_manifest_sha256=manifest_sha, production_receipt=receipt_path,
                     production_receipt_sha256=receipt_sha, plan_sha256="b" * 64,
                     archive_id="chunk-test-a1", ciphertext_root=tmp_path / "cipher",
                     output_root=tmp_path / "out", crypt_remote_name="localcrypt", **paths,
                     tool_identity=tool, wrapper_active=True, repo_root=tmp_path / "repo",
                     repo_data_root=tmp_path / "repo/data", runner=runner,
                     secret_loader=lambda path: stage.SecretMaterial.from_text("synthetic-secret"))
    return tmp_path, members, arguments, runner


def encrypted(corpus):
    base, _, args, _ = corpus
    result = bulk.run("encrypt", **args)
    return result, base / "out" / args["archive_id"] / "receipt.json"


def restore_args(corpus):
    base, _, args, runner = corpus
    crypt, crypt_path = encrypted(corpus)
    cipher = crypt["ciphertext"]
    downloaded = base / "downloads/object.bin"
    downloaded.write_bytes((base / "cipher" / cipher["path_relative_to_ciphertext_root"]).read_bytes())
    transport = {"schema_version": schema_version("production_cold_archive_transport_receipt"),
                 "status": "PASS", "crypt_receipt_sha256": sha(crypt_path),
                 "production_manifest_sha256": crypt["production_manifest_sha256"],
                 "plan_sha256": crypt["plan_sha256"], "chunk_id": crypt["chunk_id"],
                 "archive_id": crypt["archive_id"], "ciphertext": {k: cipher[k] for k in ("bytes", "sha256")},
                 "drive": {"root_folder_id": "root", "object_id": "object", "remote_key": "batch/object"},
                 "downloaded_file": {"path": "C:/controller/download/object.bin",
                                     **{k: cipher[k] for k in ("bytes", "sha256")}},
                 "independent_download": True}
    transport_path = base / "downloads/transport.json"
    transport_sha = write_evidence(transport_path, transport)
    runner.root = base / "restore-cipher"
    return {**args, "restore_id": "restore-a1", "ciphertext_root": runner.root,
            "output_root": base / "restore-out", "original_ciphertext_root": base / "cipher",
            "crypt_receipt": crypt_path, "crypt_receipt_sha256": sha(crypt_path),
            "transport_receipt": transport_path, "transport_receipt_sha256": transport_sha,
            "downloaded_file": downloaded}


def test_exact_multimember_copy_and_independent_materialized_restore(corpus, monkeypatch):
    base, members, args, runner = corpus
    monkeypatch.setenv("RCLONE_CONFIG", "ambient-must-not-leak")
    monkeypatch.setenv("RCLONE_PASSWORD_COMMAND", "ambient-must-not-run")
    restored = bulk.run("restore", **restore_args(corpus))
    assert restored["status"] == "PASS"
    assert restored["verified_file_count"] == len(members)
    assert all(value == "PASS" for value in restored["checks"].values())
    for name, content in members.items():
        assert (base / "restore-out/restore-a1/members" / name).read_bytes() == content
    assert restored["source_retained"] is True
    assert restored["cleanup_eligible"] is restored["deletion_authorized"] is False
    assert restored["fresh_production_identity_proved"] is False
    assert restored["drive_provenance"] == "controller_evidence_only"
    assert Path(restored["restored_archive"]).read_bytes() == args["archive_file"].read_bytes()
    assert not any("sync" in call or "delete" in call for call in runner.calls)
    core._check_seal(restored, "receipt_hash")


def test_secret_preflight_precedes_archive_pin_and_spends_attempt(corpus):
    base, _, args, runner = corpus
    def refuse(path):
        raise RuntimeError("do not expose secret or raw diagnostic")
    with pytest.raises(stage.ArchiveStageError):
        bulk.run("encrypt", **{**args, "secret_loader": refuse})
    assert args["archive_file"] not in FixturePin.opened
    assert not runner.calls
    receipt = json.loads((base / "out/chunk-test-a1/receipt.json").read_text())
    assert receipt["checks"]["archive_members"] == "NOT_RUN"
    assert "do not expose" not in json.dumps(receipt)
    with pytest.raises(FileExistsError):
        bulk.run("encrypt", **args)


@pytest.mark.parametrize("kind", ["plan", "receipt_count", "duplicate_key", "manifest_seal", "format"])
def test_bad_production_evidence_rejected_before_secret(corpus, kind):
    base, _, args, runner = corpus
    args = dict(args)
    if kind == "plan":
        args["plan_sha256"] = "0" * 64
    elif kind == "duplicate_key":
        path = base / "inbox/duplicate.json"
        path.write_bytes(b'{"schema_version":"x","schema_version":"y"}')
        args.update(production_manifest=path, production_manifest_sha256=sha(path))
    else:
        key = "production_receipt" if kind == "receipt_count" else "production_manifest"
        value = json.loads(args[key].read_text())
        if kind == "receipt_count":
            value["verification"]["file_count"] += 1
        elif kind == "format":
            value["format"] = stage.ARCHIVE_FORMAT
        else:
            value["manifest_hash"] = "0" * 64
        path = base / "inbox/changed.json"
        if kind == "manifest_seal":
            path.write_text(json.dumps(value))
            digest = sha(path)
        else:
            digest = write_evidence(path, value, "receipt_hash" if key.endswith("receipt") else "manifest_hash")
        args[key], args[key + "_sha256"] = path, digest
    secret_calls = []
    def forbidden(path):
        secret_calls.append(path)
        raise RuntimeError("unexpected secret recovery")
    with pytest.raises(stage.ArchiveStageError):
        bulk.run("encrypt", **{**args, "secret_loader": forbidden})
    assert not runner.calls
    assert not secret_calls


@pytest.mark.parametrize("damage", ["archive", "ciphertext", "support_drift", "no_encryption", "magic"])
def test_corruption_or_support_drift_retains_source_and_fails(corpus, damage):
    base, _, args, runner = corpus
    original = args["archive_file"].read_bytes()
    if damage == "archive":
        args["archive_file"].write_bytes(original + b"unexpected")
    elif damage == "ciphertext":
        runner.corrupt = True
    elif damage == "no_encryption":
        runner.config_extra = "no_data_encryption = true\n"
    else:
        def after(command):
            if command[0] == "copy":
                if damage == "support_drift":
                    args["rclone_config"].write_bytes(b"changed configuration")
                else:
                    cipher = base / "cipher" / Runner.mapping(args["archive_id"] + "/archive.tar.gz")
                    cipher.write_bytes(b"PLAINTXT" + cipher.read_bytes()[8:])
        runner.after = after
    with pytest.raises(stage.ArchiveStageError):
        bulk.run("encrypt", **args)
    assert args["archive_file"].exists()
    receipt = json.loads((base / "out/chunk-test-a1/receipt.json").read_text())
    assert receipt["status"] == "FAIL_CLOSED" and receipt["source_retained"] is True


def test_cipher_namespace_collision_preserves_all_prior_bytes(corpus):
    base, _, args, _ = corpus
    namespace = base / "cipher" / Runner.mapping(args["archive_id"])
    namespace.mkdir()
    sentinel = namespace / "retained.partial"
    sentinel.write_bytes(b"prior spent attempt")
    with pytest.raises(stage.ArchiveStageError):
        bulk.run("encrypt", **args)
    assert sentinel.read_bytes() == b"prior spent attempt"
    assert list(namespace.iterdir()) == [sentinel]


@pytest.mark.parametrize("change", ["download", "transport_sha", "independence", "binding", "original_inode"])
def test_restore_rejects_unbound_or_nonindependent_download(corpus, change):
    base, _, _, _ = corpus
    args = restore_args(corpus)
    if change == "download":
        args["downloaded_file"].write_bytes(args["downloaded_file"].read_bytes() + b"x")
    elif change == "transport_sha":
        args["transport_receipt_sha256"] = "0" * 64
    elif change == "original_inode":
        crypt = json.loads(args["crypt_receipt"].read_text())
        args["downloaded_file"] = base / "cipher" / crypt["ciphertext"]["path_relative_to_ciphertext_root"]
    else:
        value = json.loads(args["transport_receipt"].read_text())
        if change == "independence":
            value["independent_download"] = False
        else:
            value["chunk_id"] = "chunk-00001"
        path = base / "downloads/changed-transport.json"
        args["transport_receipt_sha256"] = write_evidence(path, value)
        args["transport_receipt"] = path
    with pytest.raises(stage.ArchiveStageError):
        bulk.run("restore", **args)
    assert not (base / "restore-out/restore-a1/members").exists()


def test_wrapper_and_paths_are_mandatory(corpus):
    base, _, args, _ = corpus
    with pytest.raises(stage.ArchiveStageError, match="wrapper"):
        bulk.run("encrypt", **{**args, "wrapper_active": False})
    with pytest.raises(stage.ArchiveStageError, match="overlap"):
        bulk.run("encrypt", **{**args, "repo_data_root": base / "cipher"})
    assert not (base / "out/chunk-test-a1").exists()


def test_native_new_client_file_copy_filter_and_restore(tmp_path):
    configured = os.environ.get("WEATHER_TEST_RCLONE_EXECUTABLE")
    if configured is None:
        pytest.skip("explicit installed rclone required for native local-only fixture")
    executable = Path(configured)
    assert executable.is_absolute() and executable.is_file()
    source, cipher, output = (tmp_path / name for name in ("source", "cipher", "output"))
    for path in (source, cipher, output):
        path.mkdir()
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("RCLONE_")}
    config = tmp_path / "fixture.conf"
    config.write_bytes(b"")
    obscured = stage._subprocess_runner(
        [str(executable), "--config", str(config), "obscure", "public-synthetic-fixture-password"],
        environment, 30, True)
    assert obscured.returncode == 0
    config.write_text("[fixture]\ntype = crypt\nremote = " + cipher.as_posix()
                      + "\nno_data_encryption = false\npassword = "
                      + obscured.stdout.decode().strip() + "\n", encoding="utf-8")
    def bounded(arguments, env, timeout, capture):
        return stage._subprocess_runner(arguments, env, min(timeout, 30), capture)
    client = bulk._Client(executable=executable, config=config, remote_name="fixture",
                          environment=environment, runner=bounded)
    client.require_local_ciphertext_root(cipher)
    payload = source / "archive.tar.gz"
    payload.write_bytes(b"synthetic exact copied archive bytes" * 100)
    (source / "unrelated.txt").write_bytes(b"must not enter ciphertext")
    logical = "fixture-a1/archive.tar.gz"
    mapped = client.encrypted_relative_path(logical)
    client.require_destination_absent("fixture-a1")
    destination = cipher / mapped
    destination.parent.mkdir()
    client.encrypt_file(payload, "fixture-a1", payload.stat().st_size)
    assert set(destination.parent.iterdir()) == {destination}
    assert destination.read_bytes().startswith(b"RCLONE\0\0")
    client.check_file(payload, "fixture-a1")
    client.decrypt_archive(logical, output, payload.stat().st_size)
    assert (output / "archive.tar.gz").read_bytes() == payload.read_bytes()
    with pytest.raises(stage.ArchiveStageError):
        client.require_destination_absent("fixture-a1")


@pytest.mark.skipif(os.name != "nt", reason="native file and ancestor pins require Windows")
def test_native_pin_denies_source_write_and_ancestor_rename(tmp_path):
    parent = tmp_path / "native-source"
    parent.mkdir()
    source = parent / "archive.tar.gz"
    source.write_bytes(b"bounded native pin fixture")
    with bulk._file_pin(source) as pin:
        before = pin.metadata()
        with pytest.raises(OSError):
            source.write_bytes(b"must not modify")
        with pytest.raises(OSError):
            parent.rename(tmp_path / "renamed")
        assert pin.metadata() == before
        assert source.read_bytes() == b"bounded native pin fixture"




def test_native_complete_restore_after_local_originals_are_removed(corpus, monkeypatch):
    """Real local crypt and full production bridge; synthetic controller/DPAPI evidence."""
    import subprocess
    import sys

    configured = os.environ.get("WEATHER_TEST_RCLONE_EXECUTABLE")
    if configured is None:
        pytest.skip("explicit installed rclone required for native local-only fixture")
    executable = Path(configured)
    assert executable.is_absolute() and executable.is_file()
    base, members, args, _ = corpus
    monkeypatch.setattr(bulk, "_file_pin", NATIVE_FILE_PIN)
    monkeypatch.setattr(core, "_directory_pin", NATIVE_DIRECTORY_PIN)
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("RCLONE_")}
    config = base / "support" / "native-encrypt.conf"
    config.write_bytes(b"")
    obscured = stage._subprocess_runner(
        [str(executable), "--config", str(config), "--ask-password=false",
         "obscure", "public-synthetic-archive-data-password"],
        environment, 30, True)
    assert obscured.returncode == 0

    # Rclone's documented config-encryption command consumes this public fixture
    # password through a tiny local helper. No provisioned credential is read.
    # https://rclone.org/commands/rclone_config_encryption_set/
    helper = base / "support" / "public_fixture_password.py"
    helper.write_text('print("synthetic-secret")\n', encoding="utf-8")
    password_command = subprocess.list2cmdline([sys.executable, str(helper)])

    def create_encrypted_config(path, ciphertext_root):
        path.write_text("[localcrypt]\ntype = crypt\nremote = " + ciphertext_root.as_posix()
                        + "\nfilename_encryption = standard\ndirectory_name_encryption = true"
                        + "\nno_data_encryption = false\npassword = "
                        + obscured.stdout.decode("ascii").strip() + "\n", encoding="utf-8")
        result = stage._subprocess_runner(
            [str(executable), "--config", str(path), "--ask-password=false",
             "--password-command", password_command, "config", "encryption", "set"],
            environment, 30, False)
        assert result.returncode == 0
        assert b"RCLONE_ENCRYPT_V0:" in path.read_bytes()

    def bounded(arguments, env, timeout, capture):
        return stage._subprocess_runner(arguments, env, min(timeout, 30), capture)

    create_encrypted_config(config, base / "cipher")
    args.update(rclone_executable=executable, rclone_config=config, runner=bounded)
    crypt = bulk.run("encrypt", **args)
    crypt_path = base / "out" / args["archive_id"] / "receipt.json"
    cipher = crypt["ciphertext"]
    original_cipher = base / "cipher" / cipher["path_relative_to_ciphertext_root"]
    downloaded = base / "downloads" / "native-object.bin"
    downloaded.write_bytes(original_cipher.read_bytes())
    transport = {
        "schema_version": schema_version("production_cold_archive_transport_receipt"),
        "status": "PASS", "crypt_receipt_sha256": sha(crypt_path),
        "production_manifest_sha256": crypt["production_manifest_sha256"],
        "plan_sha256": crypt["plan_sha256"], "chunk_id": crypt["chunk_id"],
        "archive_id": crypt["archive_id"],
        "ciphertext": {key: cipher[key] for key in ("bytes", "sha256")},
        "drive": {"root_folder_id": "fixture-root", "object_id": "fixture-object",
                  "remote_key": "fixture/native-object"},
        "downloaded_file": {"path": "C:/synthetic-controller/native-object.bin",
                            **{key: cipher[key] for key in ("bytes", "sha256")}},
        "independent_download": True,
    }
    transport_path = base / "downloads" / "native-transport.json"
    transport_sha = write_evidence(transport_path, transport)
    args["archive_file"].unlink()
    original_cipher.unlink()
    restore_config = base / "support" / "native-restore.conf"
    create_encrypted_config(restore_config, base / "restore-cipher")
    restored_args = {**args, "rclone_config": restore_config,
                     "ciphertext_root": base / "restore-cipher",
                     "output_root": base / "restore-out", "restore_id": "native-restore",
                     "crypt_receipt": crypt_path, "crypt_receipt_sha256": sha(crypt_path),
                     "transport_receipt": transport_path, "transport_receipt_sha256": transport_sha,
                     "downloaded_file": downloaded}
    restored_args.pop("archive_file")
    restored = bulk.run("restore", **restored_args)
    assert restored["status"] == "PASS"
    assert restored["checks"] == dict.fromkeys(bulk.RESTORE_CHECKS, "PASS")
    assert restored["original_archive_required"] is False
    assert restored["original_ciphertext_required"] is False
    for name, content in members.items():
        assert (base / "restore-out/native-restore/members" / name).read_bytes() == content


def test_restore_from_download_without_local_originals(corpus):
    base, members, args, _ = corpus
    request = restore_args(corpus)
    crypt = json.loads(request["crypt_receipt"].read_text())
    original = base / "cipher" / crypt["ciphertext"]["path_relative_to_ciphertext_root"]
    args["archive_file"].unlink()
    original.unlink()
    request.pop("archive_file")
    request.pop("original_ciphertext_root")
    restored = bulk.run("restore", **request)
    assert restored["status"] == "PASS"
    assert restored["original_archive_required"] is False
    assert restored["original_ciphertext_required"] is False
    assert restored["checks"] == dict.fromkeys(bulk.RESTORE_CHECKS, "PASS")
    for name, content in members.items():
        assert (base / "restore-out/restore-a1/members" / name).read_bytes() == content
    assert not args["archive_file"].exists() and not original.exists()


def test_restore_without_original_rejects_corrupt_download(corpus):
    _, _, args, _ = corpus
    request = restore_args(corpus)
    args["archive_file"].unlink()
    request.pop("archive_file")
    request.pop("original_ciphertext_root")
    with request["downloaded_file"].open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(stage.ArchiveStageError):
        bulk.run("restore", **request)


@pytest.mark.parametrize("field,value", [("inode", True), ("mode", 0), ("bytes", 1)])
def test_restore_requires_valid_recorded_original_identity(corpus, field, value):
    _, _, _, _ = corpus
    request = restore_args(corpus)
    request.pop("archive_file")
    request.pop("original_ciphertext_root")
    crypt = json.loads(request["crypt_receipt"].read_text())
    crypt["ciphertext"]["file_identity"][field] = value
    # Fixture-only alteration of upstream records; no production receipt is changed.
    request["crypt_receipt"].unlink()
    request["crypt_receipt_sha256"] = write_evidence(request["crypt_receipt"], crypt)
    transport = json.loads(request["transport_receipt"].read_text())
    transport["crypt_receipt_sha256"] = request["crypt_receipt_sha256"]
    request["transport_receipt"].unlink()
    request["transport_receipt_sha256"] = write_evidence(request["transport_receipt"], transport)
    with pytest.raises(stage.ArchiveStageError):
        bulk.run("restore", **request)
