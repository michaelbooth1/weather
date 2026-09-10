"""Exact original reclaim on synthetic archives; no production data or cloud access."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import copy
import json
import os
from pathlib import Path
import time

import pytest

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_reclaim as subject
from weather.operations import production_cold_archive_reclaim_cli as cli
from weather.operations import production_cold_archive_stage as archive
from weather.schema_registry import schema_version
from tests.operations import test_cold_archive_catalog as fixtures
from tests.operations.test_cold_archive_catalog import corpus

APPROVAL_SHA = "b" * 64
BACKUP_HOST = "c" * 64
TARGET = 100_000_000_000


@pytest.fixture(autouse=True)
def native_source_metadata(monkeypatch, request):
    if request.node.name.startswith("test_native"):
        if os.name != "nt":
            pytest.skip("native original removal requires Windows")

        def native(path):
            with archive._ArchiveSource(path) as source:
                return source.metadata()

        monkeypatch.setattr(fixtures, "metadata", native)


def record(path, value, *, sealed=True):
    if sealed:
        path.write_bytes(locations.canonical(locations.sealed(value)) + b"\n")
    else:
        path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": fixtures.sha(path)}


def amend(spec, change, *, sealed=True):
    path = Path(spec["path"])
    value = json.loads(path.read_bytes())
    change(value)
    spec.update(record(path, value, sealed=sealed))


def reclaim_args(corpus, monkeypatch, *, native=False, target=TARGET):
    restore = fixtures.catalog.publish_restore(**fixtures.recovery(corpus))
    entry, _ = locations.read_record(corpus.entry_path, corpus.entry_sha)
    now = datetime.now(timezone.utc)
    proof = record(corpus.tmp / "protected-evidence.json",
                   {"fixture_only": True, "closed": True, "open_references": []}, sealed=False)
    checks = {name: {"status": "PASS", "evidence": [proof]} for name in subject.SELECTION_CHECKS}
    checks["market_day_closed"]["closed"] = True
    checks["settlement_final"].update(settled=True, settlement_state="settled_countable")
    for name in checks:
        if name.endswith("_clear"):
            checks[name]["open_references"] = []
    review = record(corpus.tmp / "source-review.json", {
        "schema_version": schema_version("cold_archive_source_review"), "status": "PASS",
        "archive_id": entry["archive_id"], "entry_sha256": corpus.entry_sha,
        "files": [{"path": row["path"], "sha256": row["sha256"]} for row in entry["files"]],
        "checked_at_utc": (now - timedelta(seconds=1)).isoformat(),
        "expires_at_utc": (now + timedelta(minutes=4)).isoformat(), "checks": checks})
    custody = record(corpus.tmp / "custody.json", {
        "schema_version": schema_version("cold_archive_custody"), "status": "PASS",
        "entry_sha256": corpus.entry_sha, "restore_record_sha256": restore["record_sha256"],
        "backup_execution_host_id": BACKUP_HOST,
        "verified_backups": {
            "catalog_entry": {"path": "fixture-backup/catalog.json", "sha256": corpus.entry_sha},
            "restore_record": {"path": "fixture-backup/restore.json", "sha256": restore["record_sha256"]}},
        "recovery_key_custody": {"confirmed": True, "outside_both_pcs": True,
                                 "approved_by": "fixture owner", "storage_reference": "fixture password manager",
                                 "confirmed_at_utc": now.isoformat()}})
    # The independent approval tests below exercise actual proposal/plan binding.
    monkeypatch.setattr(subject, "_approval", lambda *args: (
        {"approved_by": "fixture owner", "owner_instruction": "fixture archive reclaim"},
        APPROVAL_SHA, "primary", target))
    monkeypatch.setattr(subject, "verify_consumer_adoption", lambda *args: None)
    if not native:
        monkeypatch.setattr(subject, "_removal_pin", fixtures.FixtureRemoval)
    return dict(
        request={"attempt_id": "reclaim-fixture-a1",
                 "catalog_entry": {"path": str(corpus.entry_path), "sha256": corpus.entry_sha},
                 "source_review": review,
                 "restore_record": {"path": restore["record_path"], "sha256": restore["record_sha256"]},
                 "custody_record": custody},
        source_root=corpus.tmp, production_root=corpus.tmp, backup_host_id=BACKUP_HOST,
        capture_loops=[], admission=lambda: True, deadline_monotonic=time.monotonic() + 30)


def campaign(corpus):
    return corpus.root / "cold_archive" / "catalog" / "reclaims" / APPROVAL_SHA


def assert_sources_retained(corpus):
    assert all((corpus.day / name).read_bytes() == content for name, content in corpus.contents.items())



MULTI_FILES = {"order_books_long.csv": b"a,b\n1,2\n",
              "../highest-temperature-in-nyc-on-june-16-2026/order_books_long.csv": b"a,b\n3,4\n"}


def multi_day_args(corpus, monkeypatch, *, native=False):
    args = reclaim_args(corpus, monkeypatch, native=native)
    entry, _ = locations.read_record(corpus.entry_path, corpus.entry_sha)
    days = []
    for event in sorted({Path(row["path"]).parts[1] for row in entry["files"]}):
        target = subject.event_date(event).isoformat()
        evidence = record(corpus.root / "snapshots" / event / "settlement.json", {
            "target_date": target, "polymarket_reconciliation": {
                "event_closed": True, "status": "match",
                "winning_markets": [{"closed": True, "resolved": True}]}}, sealed=False)
        days.append({"event_slug": event, "target_date": target, "settlement": evidence})
    amend(args["request"]["source_review"], lambda value: value.update(market_days=days))
    return args


@pytest.mark.parametrize("corpus", [MULTI_FILES], indirect=True)
def test_native_multiday_reclaim_requires_each_settlement_and_retains_locations(corpus, monkeypatch):
    args = multi_day_args(corpus, monkeypatch, native=True)
    result = subject.reclaim_chunk(**args)
    assert result["status"] == "PASS" and result["deleted_files"] == 2
    for row in corpus.manifest["files"]:
        path = corpus.root / row["path"]
        assert not path.exists()
        assert locations.load_location(path).entry_sha256 == corpus.entry_sha
        assert (path.parent / "settlement.json").is_file()


@pytest.mark.parametrize("corpus", [MULTI_FILES], indirect=True)
@pytest.mark.parametrize("fault", ["missing", "omitted_day", "duplicate_day", "wrong_date",
                                   "wrong_path", "changed_evidence", "unmatched", "open_winner"])
def test_multiday_reclaim_refuses_incomplete_or_changed_settlement(corpus, monkeypatch, fault):
    args = multi_day_args(corpus, monkeypatch)
    spec = args["request"]["source_review"]
    value = json.loads(Path(spec["path"]).read_bytes())
    days = value["market_days"]
    if fault == "missing":
        value.pop("market_days")
    elif fault == "omitted_day":
        days.pop()
    elif fault == "duplicate_day":
        days[1] = copy.deepcopy(days[0])
    elif fault == "wrong_date":
        days[1]["target_date"] = "2026-06-17"
    elif fault == "wrong_path":
        days[1]["settlement"] = days[0]["settlement"]
    else:
        evidence = days[1]["settlement"]
        payload = json.loads(Path(evidence["path"]).read_bytes())
        if fault == "open_winner":
            payload["polymarket_reconciliation"]["winning_markets"][0]["resolved"] = False
        else:
            payload["polymarket_reconciliation"]["status"] = "mismatch"
        updated = record(Path(evidence["path"]), payload, sealed=False)
        if fault != "changed_evidence":
            evidence.update(updated)
    spec.update(record(Path(spec["path"]), value))
    with pytest.raises((ValueError, RuntimeError)):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)


def test_original_reclaim_preserves_locations_and_complete_recovery_evidence(corpus, monkeypatch):
    args = reclaim_args(corpus, monkeypatch)
    before = {str(path): fixtures.sha(path) for path in corpus.entry_path.parent.rglob("*.json")}
    result = subject.reclaim_chunk(**args)
    assert result["status"] == "PASS" and result["deleted_files"] == len(corpus.contents)
    assert result["reclaimed_allocated_bytes"] == sum(row["allocated_bytes"] for row in corpus.manifest["files"])
    assert all(not (corpus.day / name).exists() for name in corpus.contents)
    assert all(fixtures.sha(Path(path)) == digest for path, digest in before.items())
    for name in corpus.contents:
        assert locations.load_location(corpus.day / name).entry_sha256 == corpus.entry_sha
        with pytest.raises(locations.ArchivedInputRequired):
            locations.resolve_local_path(corpus.day / name)
    state, _ = locations.read_record(campaign(corpus) / "progress.json")
    assert state["status"] == "READY" and state["deleted_files"] == len(corpus.contents)
    assert state["reclaimed_allocated_bytes"] == result["reclaimed_allocated_bytes"]
    assert (corpus.root / "cold_archive" / "WHERE_DATA_IS.md").exists()
    assert Path(result["retained_recovery"]["restore_record"]).is_file()
    assert Path(result["retained_recovery"]["custody_record"]).is_file()


@pytest.mark.parametrize("fault", [
    "changed_content", "changed_allocation", "missing_source", "wrong_marker",
    "open_reference", "missing_check", "unsettled", "open_day", "stale_review",
    "future_review", "missing_review_evidence", "changed_review_evidence",
    "wrong_backup_host", "no_external_key", "wrong_backup_hash", "missing_custody",
    "missing_restore", "wrong_entry", "expired_deadline", "admission_block",
])
def test_reclaim_refuses_before_any_deletion(corpus, monkeypatch, fault):
    args = reclaim_args(corpus, monkeypatch)
    req = args["request"]
    last = corpus.day / sorted(corpus.contents)[-1]
    first = corpus.day / sorted(corpus.contents)[0]
    if fault == "changed_content":
        info = last.stat()
        last.write_bytes(b"x" * info.st_size)
        os.utime(last, ns=(info.st_atime_ns, info.st_mtime_ns))
    elif fault == "changed_allocation":
        class Changed(fixtures.FixtureRemoval):
            def metadata(self):
                return {**super().metadata(), "allocated_bytes": 999999}
        monkeypatch.setattr(subject, "_removal_pin", Changed)
    elif fault == "missing_source":
        last.unlink()
    elif fault == "wrong_marker":
        locations.marker_path(last).write_bytes(b"{}")
    elif fault == "open_reference":
        amend(req["source_review"], lambda v: v["checks"]["queues_clear"].update(open_references=["open-job"]))
    elif fault == "missing_check":
        amend(req["source_review"], lambda v: v["checks"].pop("barriers_clear"))
    elif fault == "unsettled":
        amend(req["source_review"], lambda v: v["checks"]["settlement_final"].update(settled=False))
    elif fault == "open_day":
        amend(req["source_review"], lambda v: v["checks"]["market_day_closed"].update(closed=False))
    elif fault == "stale_review":
        amend(req["source_review"], lambda v: v.update(expires_at_utc=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()))
    elif fault == "future_review":
        amend(req["source_review"], lambda v: v.update(checked_at_utc=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()))
    elif fault in {"missing_review_evidence", "changed_review_evidence"}:
        path = corpus.tmp / "protected-evidence.json"
        if fault == "missing_review_evidence":
            path.unlink()
        else:
            path.write_bytes(b'{"changed": true}')
    elif fault == "wrong_backup_host":
        amend(req["custody_record"], lambda v: v.update(backup_execution_host_id="0" * 64))
    elif fault == "no_external_key":
        amend(req["custody_record"], lambda v: v["recovery_key_custody"].update(outside_both_pcs=False))
    elif fault == "wrong_backup_hash":
        amend(req["custody_record"], lambda v: v["verified_backups"]["catalog_entry"].update(sha256="0" * 64))
    elif fault in {"missing_custody", "missing_restore"}:
        Path(req["custody_record" if fault == "missing_custody" else "restore_record"]["path"]).unlink()
    elif fault == "wrong_entry":
        req["catalog_entry"]["sha256"] = "0" * 64
    elif fault == "expired_deadline":
        args["deadline_monotonic"] = time.monotonic() - 1
    elif fault == "admission_block":
        args["admission"] = lambda: False
    with pytest.raises((RuntimeError, ValueError, OSError)):
        subject.reclaim_chunk(**args)
    assert first.exists()
    assert not (campaign(corpus) / req["attempt_id"] / "intent.json").exists()


def rewrite_restore(spec, key, change):
    value = json.loads(Path(spec["path"]).read_bytes())
    proof = fixtures.catalog._unpack(value[key])
    change(proof)
    proof = archive._seal({k: v for k, v in proof.items() if k != "receipt_hash"}, "receipt_hash")
    raw = archive._canonical(proof) + b"\n"
    # Catalog stores original proof bytes, not a reserialized dictionary.
    import base64
    import hashlib
    value[key]["base64"] = base64.b64encode(raw).decode()
    value[key]["sha256"] = hashlib.sha256(raw).hexdigest()
    value[key]["bytes"] = len(raw)
    spec.update(record(Path(spec["path"]), value))


@pytest.mark.parametrize("fault", ["old_restore", "future_restore", "incomplete_restore",
                                   "wrong_cloud", "wrong_cipher", "not_independent"])
def test_reclaim_revalidates_embedded_complete_restore(corpus, monkeypatch, fault):
    args = reclaim_args(corpus, monkeypatch)
    spec = args["request"]["restore_record"]
    key = "transport" if fault == "not_independent" else "restore"
    def change(value):
        if fault == "old_restore":
            value["completed_at_utc"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        elif fault == "future_restore":
            value["completed_at_utc"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        elif fault == "incomplete_restore":
            value["restored_members"].pop()
        elif fault == "wrong_cloud":
            value["drive"]["object_id"] = "other_object"
        elif fault == "wrong_cipher":
            value["ciphertext"]["sha256"] = "0" * 64
        else:
            value["independent_download"] = False
    rewrite_restore(spec, key, change)
    if fault == "not_independent":
        transport_sha = json.loads(Path(spec["path"]).read_bytes())["transport"]["sha256"]
        rewrite_restore(spec, "restore", lambda v: v.update(transport_receipt_sha256=transport_sha))
    with pytest.raises((RuntimeError, ValueError), match="restore|recovery|independent"):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)


@pytest.mark.parametrize("failure", ["second_remove", "inventory"])
def test_partial_failure_is_journaled_and_blocks_next_attempt(corpus, monkeypatch, failure):
    args = reclaim_args(corpus, monkeypatch)
    if failure == "second_remove":
        class Interrupted(fixtures.FixtureRemoval):
            calls = 0
            def remove(self):
                type(self).calls += 1
                if self.calls == 2:
                    raise OSError("fixture interruption")
                super().remove()
        monkeypatch.setattr(subject, "_removal_pin", Interrupted)
    else:
        def fail_inventory(**kwargs):
            raise OSError("fixture interruption")
        monkeypatch.setattr(fixtures.catalog, "write_inventory", fail_inventory)
    with pytest.raises(OSError, match="fixture interruption"):
        subject.reclaim_chunk(**args)
    path = campaign(corpus)
    attempt = path / args["request"]["attempt_id"]
    assert (attempt / "intent.json").exists() and (attempt / "file-00000.json").exists()
    assert not (attempt / "receipt.json").exists()
    state, _ = locations.read_record(path / "progress.json")
    assert state["status"] == "IN_PROGRESS"
    args["request"]["attempt_id"] = "reclaim-fixture-a2"
    with pytest.raises(RuntimeError, match="reconciliation"):
        subject.reclaim_chunk(**args)


def test_target_stops_at_whole_file_and_refuses_further_reclaim(corpus, monkeypatch):
    args = reclaim_args(corpus, monkeypatch, target=1)
    result = subject.reclaim_chunk(**args)
    assert result["deleted_files"] == 1
    assert sum((corpus.day / name).exists() for name in corpus.contents) == len(corpus.contents) - 1
    args["request"]["attempt_id"] = "reclaim-fixture-a2"
    with pytest.raises(RuntimeError, match="target is already reached"):
        subject.reclaim_chunk(**args)


def approved_plan(tmp_path, kind="primary", target=TARGET, grouping=archive.SELECTIVE_GROUPING):
    root = tmp_path / "data"
    row = {"path": "snapshots/highest-temperature-in-toronto-on-june-15-2026/order_books_long.csv",
           "size_bytes": 4, "mtime_ns": 1, "device": 1, "file_id": 2, "allocated_bytes": 4096}
    proposal = {"schema_version": schema_version("archive_target_owner_review_proposal"),
                "selection_kind": kind, "source_root": str(root), "files": [row]}
    proposal_spec = record(tmp_path / "approved-proposal.json", proposal, sealed=False)
    approval = {"schema_version": schema_version("archive_target_owner_approval"),
                "approved_by": "fixture owner", "owner_instruction": "fixture approval",
                "primary": {"sha256": proposal_spec["sha256"]},
                "conditional_reserve": {"sha256": proposal_spec["sha256"],
                    "use_only_if_qualified_primary_reclaim_is_below_bytes": target}}
    approval_spec = record(tmp_path / "approved-owner.json", approval, sealed=False)
    selection = {"schema_version": schema_version("large_archive_candidate_selection"),
                 "status": "MEASURED_CANDIDATE_NOT_DELETE_AUTHORITY",
                 "source_root": str(root), "files": [row], "file_count": 1,
                 "logical_bytes": 4, "allocated_bytes": 4096,
                 "source_review_proposal_sha256": proposal_spec["sha256"],
                 "owner_approval_sha256": approval_spec["sha256"]}
    selection_spec = record(tmp_path / "approved-selection.json", selection, sealed=False)
    plan_path = tmp_path / "approved-plan.json"
    archive.plan_selection(selection_spec["path"], selection_spec["sha256"], plan_path,
                           chunk_grouping=grouping)
    request = {"owner_approval": approval_spec, "proposal": proposal_spec,
               "selection": selection_spec, "plan": {"path": str(plan_path), "sha256": fixtures.sha(plan_path)}}
    entry = {"source_root": str(root), "files": [{**row, "sha256": "a" * 64}],
             "chunk_id": "chunk-00000", "plan_sha256": request["plan"]["sha256"]}
    return request, entry


@pytest.mark.parametrize("grouping", [archive.SELECTIVE_GROUPING, archive.MARKET_DAY_GROUPING,
                                        archive.PARTITIONED_GROUPING])
@pytest.mark.parametrize("proposal_kind,expected_kind", [("primary", "primary"), ("standby", "conditional_reserve")])
def test_approval_binds_exact_proposal_selection_and_plan(tmp_path, monkeypatch, proposal_kind, expected_kind, grouping):
    monkeypatch.setattr(subject.bridge, "_file_pin", fixtures.FixturePin)
    request, entry = approved_plan(tmp_path, kind=proposal_kind, grouping=grouping)
    with ExitStack() as stack:
        _, digest, kind, target = subject._approval(request, stack, entry)
    assert digest == request["owner_approval"]["sha256"] and kind == expected_kind and target == TARGET


@pytest.mark.parametrize("fault", ["owner_hash", "proposal_hash", "selection_files", "selection_root",
                                   "plan_regroup", "chunk_files", "target_bool"])
def test_approval_refuses_resealed_scope_changes(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(subject.bridge, "_file_pin", fixtures.FixturePin)
    request, entry = approved_plan(tmp_path)
    if fault == "owner_hash":
        request["owner_approval"]["sha256"] = "0" * 64
    elif fault == "proposal_hash":
        amend(request["owner_approval"], lambda v: v["primary"].update(sha256="0" * 64), sealed=False)
    elif fault == "selection_files":
        amend(request["selection"], lambda v: v["files"][0].update(file_id=44), sealed=False)
    elif fault == "selection_root":
        amend(request["selection"], lambda v: v.update(source_root=str(tmp_path / "other")), sealed=False)
    elif fault == "chunk_files":
        entry["files"][0]["file_id"] = 44
    elif fault == "target_bool":
        amend(request["owner_approval"], lambda v: v["conditional_reserve"].update(
            use_only_if_qualified_primary_reclaim_is_below_bytes=True), sealed=False)
    else:
        plan_path = Path(request["plan"]["path"])
        value = json.loads(plan_path.read_bytes())
        value["chunks"][0]["logical_bytes"] = 99
        plan_path.write_bytes(archive._canonical(archive._seal(value, "plan_hash")) + b"\n")
        request["plan"]["sha256"] = fixtures.sha(plan_path)
        entry["plan_sha256"] = request["plan"]["sha256"]
    with ExitStack() as stack, pytest.raises((RuntimeError, ValueError)):
        subject._approval(request, stack, entry)


@pytest.mark.parametrize("target", [True, 0, -1, "100000000000", 1024**4 + 1])
def test_owner_target_must_be_a_positive_bounded_byte_count(tmp_path, monkeypatch, target):
    monkeypatch.setattr(subject.bridge, "_file_pin", fixtures.FixturePin)
    request, entry = approved_plan(tmp_path, target=target)
    with ExitStack() as stack, pytest.raises(RuntimeError, match="target is invalid"):
        subject._approval(request, stack, entry)


def test_conditional_reserve_does_not_inherit_primary_execution(corpus, monkeypatch):
    args = reclaim_args(corpus, monkeypatch)
    monkeypatch.setattr(subject, "_approval", lambda *args: (
        {"approved_by": "fixture owner", "owner_instruction": "fixture reserve"},
        APPROVAL_SHA, "conditional_reserve", TARGET))
    with pytest.raises(RuntimeError, match="conditional reserve"):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)


def test_consumer_source_must_be_adopted_with_current_three_loop_identities(tmp_path, monkeypatch):
    path = "src/weather/example.py"
    source, production = tmp_path / "reviewed", tmp_path / "production"
    for root in (source, production):
        file = root / path
        file.parent.mkdir(parents=True)
        file.write_text("reviewed = True\n")
    monkeypatch.setattr(subject, "CONSUMER_FILES", (path,))
    monkeypatch.setattr(subject.bridge, "_file_pin", fixtures.FixturePin)
    monkeypatch.setattr(subject.runtime_identity, "current_identity_for", lambda value, **kwargs: value)
    monkeypatch.setattr(subject.runtime_identity, "identities_match", lambda left, right: left == right)
    loops = [{"runtime_identity": {"source_scope_files": [path]}} for _ in range(3)]
    with ExitStack() as stack:
        subject.verify_consumer_adoption(source, production, stack, loops)
    (production / path).write_text("reviewed = False\n")
    with ExitStack() as stack, pytest.raises(RuntimeError, match="not been adopted"):
        subject.verify_consumer_adoption(source, production, stack, loops)
    (production / path).write_text("reviewed = True\n")
    monkeypatch.setattr(subject.runtime_identity, "identities_match", lambda *args: False)
    with ExitStack() as stack, pytest.raises(RuntimeError, match="capture has not adopted"):
        subject.verify_consumer_adoption(source, production, stack, loops)
    monkeypatch.setattr(subject.runtime_identity, "identities_match", lambda left, right: left == right)
    loops[0]["runtime_identity"]["source_scope_files"] = ["../outside.py"]
    with ExitStack() as stack, pytest.raises(RuntimeError):
        subject.verify_consumer_adoption(source, production, stack, loops)


def test_native_original_reclaim_removes_exact_files_after_real_identity_checks(corpus, monkeypatch):
    args = reclaim_args(corpus, monkeypatch, native=True)
    result = subject.reclaim_chunk(**args)
    assert result["deleted_files"] == len(corpus.contents)
    assert result["reclaimed_allocated_bytes"] == sum(row["allocated_bytes"] for row in corpus.manifest["files"])
    assert all(not (corpus.day / name).exists() for name in corpus.contents)


def test_native_busy_original_is_refused_before_first_delete(corpus, monkeypatch):
    args = reclaim_args(corpus, monkeypatch, native=True)
    with (corpus.day / sorted(corpus.contents)[-1]).open("rb"), pytest.raises(OSError):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)
    assert not (campaign(corpus) / args["request"]["attempt_id"] / "intent.json").exists()


def test_native_hardlinked_original_is_refused(corpus, monkeypatch):
    args = reclaim_args(corpus, monkeypatch, native=True)
    os.link(corpus.day / sorted(corpus.contents)[-1], corpus.tmp / "alias")
    with pytest.raises((RuntimeError, ValueError, OSError), match="hardlink"):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)


def cli_request(tmp_path):
    now = datetime.now(timezone.utc)
    return {
        "schema_version": schema_version("production_cold_archive_reclaim_request"),
        "production_repo_root": str(tmp_path), "execution_host_id": "e" * 64,
        "operation": "reclaim", "approved_by": "fixture owner",
        "approved_at_utc": (now - timedelta(seconds=1)).isoformat(),
        "expires_at_utc": (now + timedelta(hours=1)).isoformat(),
        "source_git_sha": "f" * 40, "attempt_id": "fixture-a1",
        **{field: {"path": str(tmp_path / (field + ".json")), "sha256": "a" * 64}
           for field in cli.EVIDENCE_FIELDS}}


@pytest.mark.skipif(os.name != "nt", reason="native Windows path equivalence")
def test_transfer_manifest_accepts_same_windows_root_with_forward_slashes(tmp_path):
    from weather.operations import production_cold_archive_transfer as transfer
    row = {"path": "snapshots/highest-temperature-in-toronto-on-june-15-2026/order_books_long.csv",
           "size_bytes": 4, "mtime_ns": 1, "device": 1, "file_id": 2, "allocated_bytes": 4096}
    plan = {"source_root": (tmp_path / "data").as_posix(), "plan_hash": "a" * 64}
    manifest = {"source_root": str(tmp_path / "data"), "plan_hash": "a" * 64,
                "chunk_id": "chunk-00000", "files": [row]}
    chunk = {"chunk_id": "chunk-00000", "files": [row]}
    transfer.validate_manifest_plan(manifest, plan, chunk)
    manifest["source_root"] = str(tmp_path / "other")
    with pytest.raises(ValueError):
        transfer.validate_manifest_plan(manifest, plan, chunk)


def test_reclaim_cli_request_has_exact_scope(tmp_path):
    request = cli_request(tmp_path)
    assert cli.validate_request(request, production_root=tmp_path, now=datetime.now(timezone.utc),
                                source_git_sha="f" * 40) == request


@pytest.mark.parametrize("fault", ["mode", "extra", "missing_proof", "relative_proof", "wrong_hash",
                                   "wrong_tip", "expired", "unnamed_owner"])
def test_reclaim_cli_rejects_ambiguous_request(tmp_path, fault):
    request = cli_request(tmp_path)
    if fault == "mode":
        request["operation"] = "delete_all"
    elif fault == "extra":
        request["ignore_disk_floor"] = True
    elif fault == "missing_proof":
        request.pop("source_review")
    elif fault == "relative_proof":
        request["custody_record"]["path"] = "relative.json"
    elif fault == "wrong_hash":
        request["restore_record"]["sha256"] = "wrong"
    elif fault == "wrong_tip":
        request["source_git_sha"] = "a" * 40
    elif fault == "expired":
        request["expires_at_utc"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    else:
        request["approved_by"] = ""
    with pytest.raises((ValueError, RuntimeError)):
        cli.validate_request(request, production_root=tmp_path, now=datetime.now(timezone.utc),
                             source_git_sha="f" * 40)


def spool_reclaim_args(corpus, monkeypatch, *, native=False):
    args = reclaim_args(corpus, monkeypatch, native=native)
    req = args["request"]
    entry, _ = locations.read_record(corpus.entry_path, corpus.entry_sha)
    ingress = corpus.tmp / "scratch" / "production_cold_archive_ingress" / entry["archive_id"] / "archive.rclone.bin"
    downloaded = (corpus.tmp / "scratch" / "production_cold_archive_transfer" / "fixture-download-a1"
                  / "transfer" / ("downloaded-" + entry["archive_id"] + ".rclone.bin"))
    for path in (ingress, downloaded):
        path.parent.mkdir(parents=True)
        path.write_bytes(fixtures.CIPHER_BYTES)
    spec = req["restore_record"]
    rewrite_restore(spec, "transport", lambda v: v.update(downloaded_file={
        "path": str(downloaded), "bytes": downloaded.stat().st_size, "sha256": fixtures.sha(downloaded)}))
    transport_sha = json.loads(Path(spec["path"]).read_bytes())["transport"]["sha256"]
    rewrite_restore(spec, "restore", lambda v: v.update(transport_receipt_sha256=transport_sha))
    def update_custody(value):
        value["restore_record_sha256"] = spec["sha256"]
        value["verified_backups"]["restore_record"]["sha256"] = spec["sha256"]
    amend(req["custody_record"], update_custody)
    staged = Path(corpus.args["production_manifest"]).parent / "archive.tar.gz"
    paths = (staged, ingress, downloaded)
    rows = [{"role": role, "path": path.relative_to(corpus.tmp).as_posix(),
             "sha256": fixtures.sha(path), **fixtures.metadata(path)}
            for role, path in zip(subject.spool.ROLES, paths)]
    req["spool_inventory"] = record(corpus.tmp / "spool-inventory.json", {
        "schema_version": schema_version("cold_archive_spool_inventory"),
        "archive_id": entry["archive_id"], "entry_sha256": corpus.entry_sha, "files": rows})
    if not native:
        monkeypatch.setattr(subject.spool, "_removal_pin", fixtures.FixtureRemoval)
    return args, paths


def test_reclaim_with_spool_preserves_all_recovery_metadata_and_separates_counters(corpus, monkeypatch):
    args, paths = spool_reclaim_args(corpus, monkeypatch)
    metadata = {path: fixtures.sha(path) for path in corpus.tmp.rglob("*.json")}
    result = subject.reclaim_chunk(**args)
    assert all(not path.exists() for path in paths)
    assert all(path.exists() and fixtures.sha(path) == digest for path, digest in metadata.items())
    assert result["spool_cleanup"]["deleted_files"] == 3
    assert result["spool_cleanup"]["originals_deleted"] == 0
    assert result["deleted_files"] == len(corpus.contents)
    state, _ = locations.read_record(campaign(corpus) / "progress.json")
    assert state["reclaimed_allocated_bytes"] == sum(row["allocated_bytes"] for row in corpus.manifest["files"])
    assert state["status"] == "READY"
    assert all(path.parent.is_dir() for path in paths)


@pytest.mark.parametrize("fault", ["changed_payload", "changed_identity", "changed_allocation",
                                   "source_path", "metadata_path", "duplicate_role", "missing_role",
                                   "wrong_archive", "wrong_entry", "wrong_sha", "missing_file"])
def test_spool_fault_retains_every_original_before_any_reclaim(corpus, monkeypatch, fault):
    args, paths = spool_reclaim_args(corpus, monkeypatch)
    spec = args["request"]["spool_inventory"]
    if fault == "changed_payload":
        info = paths[-1].stat()
        paths[-1].write_bytes(b"z" * info.st_size)
        os.utime(paths[-1], ns=(info.st_atime_ns, info.st_mtime_ns))
    elif fault == "missing_file":
        paths[-1].unlink()
    else:
        def change(value):
            rows = value["files"]
            if fault == "changed_identity":
                rows[-1]["file_id"] += 1
            elif fault == "changed_allocation":
                rows[-1]["allocated_bytes"] += 4096
            elif fault == "source_path":
                rows[-1]["path"] = (corpus.day / sorted(corpus.contents)[0]).relative_to(corpus.tmp).as_posix()
            elif fault == "metadata_path":
                rows[-1]["path"] = corpus.entry_path.relative_to(corpus.tmp).as_posix()
            elif fault == "duplicate_role":
                rows[-1]["role"] = rows[0]["role"]
            elif fault == "missing_role":
                rows.pop()
            elif fault == "wrong_archive":
                value["archive_id"] = "different-a1"
            elif fault == "wrong_entry":
                value["entry_sha256"] = "0" * 64
            else:
                rows[-1]["sha256"] = "0" * 64
        amend(spec, change)
    with pytest.raises((RuntimeError, ValueError, OSError)):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)
    assert paths[0].exists() and paths[1].exists()
    assert not (campaign(corpus) / args["request"]["attempt_id"] / "intent.json").exists()


def test_partial_spool_cleanup_journals_progress_and_blocks_automatic_retry(corpus, monkeypatch):
    args, paths = spool_reclaim_args(corpus, monkeypatch)
    class FailsSecond(fixtures.FixtureRemoval):
        def remove(self):
            if self.path == paths[1]:
                raise OSError("fixture second temporary removal failure")
            super().remove()
    monkeypatch.setattr(subject.spool, "_removal_pin", FailsSecond)
    with pytest.raises(OSError):
        subject.reclaim_chunk(**args)
    assert not paths[0].exists() and paths[1].exists() and paths[2].exists()
    assert_sources_retained(corpus)
    attempt = campaign(corpus) / args["request"]["attempt_id"]
    assert (attempt / "spool-file-00000.json").is_file()
    assert not (attempt / "spool-receipt.json").exists()
    state, _ = locations.read_record(campaign(corpus) / "progress.json")
    assert state["status"] == "IN_PROGRESS" and state["reclaimed_allocated_bytes"] == 0
    args["request"]["attempt_id"] = "reclaim-fixture-a2"
    with pytest.raises(RuntimeError, match="reconciliation"):
        subject.reclaim_chunk(**args)


def test_native_reclaim_with_spool_deletes_exact_payloads_under_real_ntfs_handles(corpus, monkeypatch):
    args, paths = spool_reclaim_args(corpus, monkeypatch, native=True)
    result = subject.reclaim_chunk(**args)
    assert result["status"] == "PASS" and all(not path.exists() for path in paths)
    assert result["spool_cleanup"]["deleted_files"] == 3
    assert result["reclaimed_allocated_bytes"] == sum(row["allocated_bytes"] for row in corpus.manifest["files"])


def test_native_busy_spool_refuses_before_deleting_any_original_or_payload(corpus, monkeypatch):
    args, paths = spool_reclaim_args(corpus, monkeypatch, native=True)
    with paths[-1].open("rb"), pytest.raises(OSError):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)
    assert all(path.exists() for path in paths)


def test_native_hardlinked_spool_refuses_before_deleting_any_original(corpus, monkeypatch):
    args, paths = spool_reclaim_args(corpus, monkeypatch, native=True)
    os.link(paths[-1], corpus.tmp / "spool-alias")
    with pytest.raises((RuntimeError, ValueError, OSError), match="hardlink|unsupported"):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)
    assert all(path.exists() for path in paths)


def test_reclaim_cli_accepts_only_hash_bound_spool_inventory(tmp_path):
    request = cli_request(tmp_path)
    request["spool_inventory"] = {"path": str(tmp_path / "spool.json"), "sha256": "a" * 64}
    cli.validate_request(request, production_root=tmp_path, now=datetime.now(timezone.utc), source_git_sha="f" * 40)
    request["spool_inventory"]["path"] = "relative.json"
    with pytest.raises(ValueError, match="absolute"):
        cli.validate_request(request, production_root=tmp_path, now=datetime.now(timezone.utc), source_git_sha="f" * 40)


def test_reclaim_failure_locations_exclude_exception_text_and_full_paths():
    try:
        raise ValueError("fixture-private-value-must-not-be-published")
    except ValueError as exc:
        rows = cli._failure_locations(exc)
    assert rows and all(set(row) == {"module", "line"} for row in rows)
    assert all(row["module"] == "test_cold_archive_reclaim.py" for row in rows)
    assert "fixture-private-value" not in json.dumps(rows)

def workstation_spool_args(corpus, monkeypatch, *, native=False):
    args, paths = spool_reclaim_args(corpus, monkeypatch, native=native)
    req = args["request"]
    # The extra synthetic production download is deliberately retained: it is
    # not selected by the workstation-backed inventory.
    remote_root = corpus.tmp.parent / (corpus.tmp.name + "-ws")
    remote_download = (remote_root / "scratch" / "production_cold_archive_transport" / "wd1"
                       / "transfer" / ("downloaded-" + corpus.bound["archive_id"] + ".rclone.bin"))
    spec = req["restore_record"]
    rewrite_restore(spec, "transport", lambda value: value["downloaded_file"].update(path=str(remote_download)))
    transport_sha = json.loads(Path(spec["path"]).read_bytes())["transport"]["sha256"]
    rewrite_restore(spec, "restore", lambda value: value.update(
        transport_receipt_sha256=transport_sha, restore_id="wr1",
        restored_archive=str(remote_root / "scratch" / "ac-rest" / "wr1" / "archive" / "archive.tar.gz")))
    def update_custody(value):
        value["restore_record_sha256"] = spec["sha256"]
        value["verified_backups"]["restore_record"]["sha256"] = spec["sha256"]
    amend(req["custody_record"], update_custody)
    amend(req["spool_inventory"], lambda value: value["files"].pop())
    return args, paths, remote_root


def assert_workstation_spool_reclaim(corpus, monkeypatch, *, native):
    args, paths, remote = workstation_spool_args(corpus, monkeypatch, native=native)
    result = subject.reclaim_chunk(**args)
    assert result["status"] == "PASS"
    assert result["spool_cleanup"]["deleted_files"] == 2
    assert not paths[0].exists() and not paths[1].exists()
    assert paths[2].read_bytes() == fixtures.CIPHER_BYTES
    assert not remote.exists()  # Metadata proof did not access/create a remote tree.
    assert result["reclaimed_allocated_bytes"] == sum(row["allocated_bytes"] for row in corpus.manifest["files"])


def test_workstation_transport_reclaims_only_two_local_spools(corpus, monkeypatch):
    assert_workstation_spool_reclaim(corpus, monkeypatch, native=False)


def test_native_workstation_transport_reclaims_only_two_local_spools(corpus, monkeypatch):
    assert_workstation_spool_reclaim(corpus, monkeypatch, native=True)


@pytest.mark.parametrize("fault", ["third_role", "wrong_download_root", "wrong_restore_layout"])
def test_workstation_spool_host_or_role_mismatch_prevents_all_deletion(corpus, monkeypatch, fault):
    args, paths, remote = workstation_spool_args(corpus, monkeypatch)
    req = args["request"]
    if fault == "third_role":
        amend(req["spool_inventory"], lambda value: value["files"].append({
            "role": "downloaded_ciphertext", "path": paths[2].relative_to(corpus.tmp).as_posix(),
            "sha256": fixtures.sha(paths[2]), **fixtures.metadata(paths[2])}))
    else:
        spec = req["restore_record"]
        if fault == "wrong_download_root":
            rewrite_restore(spec, "transport", lambda value: value["downloaded_file"].update(
                path=str(remote.parent / "wrong" / "downloaded.rclone.bin")))
            transport_sha = json.loads(Path(spec["path"]).read_bytes())["transport"]["sha256"]
            rewrite_restore(spec, "restore", lambda value: value.update(transport_receipt_sha256=transport_sha))
        else:
            rewrite_restore(spec, "restore", lambda value: value.update(
                restored_archive=str(remote / "scratch" / "failed" / "wr1" / "archive" / "archive.tar.gz")))
        def update_custody(value):
            value["restore_record_sha256"] = spec["sha256"]
            value["verified_backups"]["restore_record"]["sha256"] = spec["sha256"]
        amend(req["custody_record"], update_custody)
    with pytest.raises((RuntimeError, ValueError, OSError)):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)
    assert all(path.exists() for path in paths)
    assert not (campaign(corpus) / req["attempt_id"] / "intent.json").exists()


def assert_single_production_stage(corpus, monkeypatch, *, native):
    args, paths, remote = workstation_spool_args(corpus, monkeypatch, native=native)
    paths[1].unlink()  # This topology never placed ciphertext on production.
    amend(args["request"]["spool_inventory"], lambda value: value["files"].pop())
    result = subject.reclaim_chunk(**args)
    assert result["status"] == "PASS" and result["spool_cleanup"]["deleted_files"] == 1
    assert not paths[0].exists() and not remote.exists()
    assert paths[2].read_bytes() == fixtures.CIPHER_BYTES
    assert result["reclaimed_allocated_bytes"] == sum(row["allocated_bytes"] for row in corpus.manifest["files"])


def test_workstation_only_transport_reclaims_sole_production_stage(corpus, monkeypatch):
    assert_single_production_stage(corpus, monkeypatch, native=False)


def test_native_workstation_only_transport_reclaims_sole_production_stage(corpus, monkeypatch):
    assert_single_production_stage(corpus, monkeypatch, native=True)


def test_single_spool_cannot_hide_existing_production_ciphertext(corpus, monkeypatch):
    args, paths, _ = workstation_spool_args(corpus, monkeypatch)
    amend(args["request"]["spool_inventory"], lambda value: value["files"].pop())
    with pytest.raises((ValueError, RuntimeError), match="ordered payload roles"):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)
    assert all(path.exists() for path in paths)


def test_single_spool_rejects_different_path_even_without_production_ciphertext(corpus, monkeypatch):
    args, paths, _ = workstation_spool_args(corpus, monkeypatch)
    paths[1].unlink()
    def change(value):
        value["files"].pop()
        value["files"][0]["path"] = paths[2].relative_to(corpus.tmp).as_posix()
    amend(args["request"]["spool_inventory"], change)
    with pytest.raises((ValueError, RuntimeError), match="path, content or size"):
        subject.reclaim_chunk(**args)
    assert_sources_retained(corpus)
    assert paths[0].exists() and paths[2].exists()
