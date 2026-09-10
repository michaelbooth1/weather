"""Recovery handback publication on isolated fixtures; no production or cloud."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_recovery_publication as subject
from weather.operations import cold_archive_reclaim as reclaim
from weather.schema_registry import schema_version
from tests.operations import test_cold_archive_catalog as fixtures
from tests.operations.test_cold_archive_catalog import corpus

HOST = "c" * 64
PRINCIPAL = "d" * 64


@pytest.fixture
def tmp_path(tmp_path_factory):
    # Publication exercises two catalog layouts below this directory on Windows.
    return tmp_path_factory.mktemp("r")


def publication_args(corpus):
    recovery = fixtures.recovery(corpus)
    root = corpus.tmp / "scratch" / "production_cold_archive_recovery" / "p1" / "data"
    root.mkdir(parents=True)
    key_path = corpus.tmp / "key-custody.json"
    key_path.write_text(json.dumps({
        "schema_version": schema_version("cold_archive_key_custody"),
        "confirmed": True, "outside_both_pcs": True, "approved_by": "fixture owner",
        "confirmed_at_utc": datetime.now(timezone.utc).isoformat(),
        "storage_reference": "fixture independent password manager"}))
    return dict(
        **recovery, key_custody=key_path, key_custody_sha256=fixtures.sha(key_path),
        recovery_data_root=root, attempt_id="handback-a1", repo_root=corpus.tmp,
        backup_host_id=HOST)


def assert_originals(corpus):
    assert all((corpus.day / name).read_bytes() == content for name, content in corpus.contents.items())


def test_publishes_exact_recovery_and_verified_custody_without_original_mutation(corpus):
    args = publication_args(corpus)
    result = subject.publish_recovery(**args)
    assert result["status"] == "PUBLISHED_RECOVERY"
    assert result["originals_deleted"] == result["remote_objects_deleted"] == 0
    assert_originals(corpus)
    assert Path(result["catalog_entry"]["path"]).is_relative_to(args["recovery_data_root"])
    entry, digest = locations.read_record(result["catalog_entry"]["path"], result["catalog_entry"]["sha256"])
    assert digest == corpus.entry_sha
    assert entry["source_root"] == str(corpus.root)
    with ExitStack() as stack:
        restore, restore_sha = reclaim._restore(result["restore_record"], stack, entry, digest, datetime.now(timezone.utc))
        custody, _ = reclaim._custody(result["custody_record"], stack, digest, restore_sha, HOST, datetime.now(timezone.utc))
        assert custody["verified_backups"]["catalog_entry"] == result["catalog_entry"]
        assert restore["verified_file_count"] == len(corpus.contents)
    for name in corpus.contents:
        recovered = args["recovery_data_root"] / (corpus.day / name).relative_to(corpus.root)
        assert not recovered.exists()
        assert locations.load_location(recovered).entry_sha256 == digest
    assert (args["recovery_data_root"] / "cold_archive" / "WHERE_DATA_IS.md").is_file()
    with pytest.raises(FileExistsError):
        subject.publish_recovery(**args)


@pytest.mark.parametrize("fault", ["unconfirmed", "local_key", "no_owner", "no_location",
                                   "future", "extra_key", "wrong_schema", "changed_hash"])
def test_invalid_key_custody_refuses_before_claim(corpus, fault):
    args = publication_args(corpus)
    path = args["key_custody"]
    value = json.loads(path.read_bytes())
    if fault == "unconfirmed":
        value["confirmed"] = False
    elif fault == "local_key":
        value["outside_both_pcs"] = False
    elif fault == "no_owner":
        value["approved_by"] = ""
    elif fault == "no_location":
        value["storage_reference"] = ""
    elif fault == "future":
        value["confirmed_at_utc"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    elif fault == "extra_key":
        value["key_material"] = "not allowed"
    elif fault == "wrong_schema":
        value["schema_version"] = "unknown"
    path.write_text(json.dumps(value))
    if fault != "changed_hash":
        args["key_custody_sha256"] = fixtures.sha(path)
    else:
        args["key_custody_sha256"] = "0" * 64
    with pytest.raises((RuntimeError, ValueError)):
        subject.publish_recovery(**args)
    assert not (args["recovery_data_root"].parent / "handbacks").exists()
    assert_originals(corpus)


@pytest.mark.parametrize("fault", ["bad_restore", "bad_download", "expired", "refused", "wrong_root"])
def test_invalid_recovery_retains_sources_and_preserves_spent_attempt(corpus, fault):
    args = publication_args(corpus)
    if fault in {"bad_restore", "bad_download"}:
        key = "restore_receipt" if fault == "bad_restore" else "transport_receipt"
        value = json.loads(Path(args[key]).read_bytes())
        value["restore_performed" if fault == "bad_restore" else "independent_download"] = False
        changed = corpus.tmp / ("bad-" + key + ".json")
        args[key + "_sha256"] = fixtures.save(changed, value)
        args[key] = changed
    elif fault == "expired":
        args["deadline_monotonic"] = time.monotonic() - 1
    elif fault == "refused":
        args["admission"] = lambda: False
    else:
        args["recovery_data_root"] = corpus.root
    with pytest.raises((RuntimeError, ValueError)):
        subject.publish_recovery(**args)
    assert_originals(corpus)
    if fault in {"bad_restore", "bad_download"}:
        attempt = args["recovery_data_root"].parent / "handbacks" / args["attempt_id"]
        assert (attempt / "claim.json").is_file() and (attempt / "failure.json").is_file()
        assert not (attempt / "receipt.json").exists()


def test_publication_cli_requires_native_wrapper(corpus, monkeypatch):
    monkeypatch.setattr(subject, "os", SimpleNamespace(name="nt", environ={}))
    with pytest.raises(ValueError, match="wrapper"):
        subject.run_publication(SimpleNamespace())


def cli_args(corpus, monkeypatch):
    args = publication_args(corpus)
    args = {key: value for key, value in args.items()
            if key not in {"repo_root", "backup_host_id", "admission", "deadline_monotonic"}}
    assignment = {
        "schema_version": subject.execution_host.EXECUTION_HOST_ASSIGNMENT_SCHEMA_VERSION,
        "assignment_status": "ASSIGNED", "active_portable_execution_host_id": HOST,
        "active_portable_execution_principal_id": PRINCIPAL,
        "dedicated_capture_execution_host_id": "e" * 64}
    path = corpus.tmp / subject.execution_host.EXECUTION_HOST_ASSIGNMENT_RELATIVE_PATH
    path.parent.mkdir()
    path.write_text(json.dumps(assignment))
    monkeypatch.setattr(subject, "repo_path", lambda: corpus.tmp)
    monkeypatch.setattr(subject, "os", SimpleNamespace(name="nt", environ={subject.bridge.stage.WRAPPER_ENV: "1"}))
    monkeypatch.setattr(subject.execution_host, "current_execution_host_id", lambda: HOST)
    monkeypatch.setattr(subject.execution_host, "current_execution_principal_id", lambda: PRINCIPAL)
    return SimpleNamespace(**args), path


def test_publication_cli_binds_host_and_principal(corpus, monkeypatch):
    args, _ = cli_args(corpus, monkeypatch)
    result = subject.run_publication(args)
    assert result["status"] == "PUBLISHED_RECOVERY" and result["backup_execution_host_id"] == HOST


@pytest.mark.parametrize("field", ["active_portable_execution_host_id", "active_portable_execution_principal_id",
                                   "dedicated_capture_execution_host_id"])
def test_publication_cli_refuses_wrong_host_assignment(corpus, monkeypatch, field):
    args, path = cli_args(corpus, monkeypatch)
    value = json.loads(path.read_bytes())
    value[field] = HOST if field == "dedicated_capture_execution_host_id" else "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="assigned non-capture"):
        subject.run_publication(args)
    assert_originals(corpus)


def test_publication_admission_rechecks_pinned_assignment(corpus, monkeypatch):
    args, path = cli_args(corpus, monkeypatch)
    def changed_assignment(**kwargs):
        path.write_text("{}")
        kwargs["admission"]()
    monkeypatch.setattr(subject, "publish_recovery", changed_assignment)
    with pytest.raises((RuntimeError, ValueError), match="SHA-256"):
        subject.run_publication(args)


def test_workstation_restore_routes_publication_without_starting_restore(monkeypatch):
    from weather.operations import workstation_cold_archive_restore as dispatcher
    called = []
    monkeypatch.setattr(subject, "main", lambda argv: called.append(argv) or 0)
    assert dispatcher.main(["--publish-recovery", "--entry-path", "fixture.json"]) == 0
    assert called == [["--entry-path", "fixture.json"]]
