from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.operations import documentation_transaction
from weather.operations.documentation_transaction import (
    COMPLETION_SCHEMA,
    LATEST_SCHEMA,
    RECEIPT_SCHEMA,
    REQUIRED_DISPOSITION_DOCUMENTS,
    REQUIRED_REVIEWED_DOCUMENTS,
    begin_transaction,
    complete_transaction,
    transaction_status,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "master")
    _git(tmp_path, "config", "user.email", "docs@example.invalid")
    _git(tmp_path, "config", "user.name", "Docs Test")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(tmp_path, "add", "seed.txt")
    _git(tmp_path, "commit", "-m", "seed")
    return tmp_path


def test_begin_stacks_exact_integrations_and_matching_receipt_clears_status(tmp_path):
    root = _repo(tmp_path)
    first = _git(root, "rev-parse", "HEAD")
    now = datetime(2026, 8, 19, 1, 15, tzinfo=timezone.utc)
    begin_transaction(root, integration_tip=first, branch="parent", now=now)

    (root / "second.txt").write_text("second\n", encoding="utf-8")
    _git(root, "add", "second.txt")
    _git(root, "commit", "-m", "second")
    second = _git(root, "rev-parse", "HEAD")
    pending = begin_transaction(root, integration_tip=second, branch="successor", now=now)

    assert [row["integration_tip"] for row in pending["integrations"]] == [first, second]
    assert len(list((root / "data/alerts/documentation_transactions").glob("pending-*.json"))) == 2
    assert transaction_status(root, now=now)["state"] == "PENDING"

    transaction_dir = root / "data/alerts/documentation_transactions"
    immutable = transaction_dir / "receipt.json"
    immutable.write_text(
        json.dumps(
            {
                "schema_version": RECEIPT_SCHEMA,
                "status": "PASS",
                "pending_sha256": pending["pending_sha256"],
                "integration_tips": [first, second],
                "documentation_tip": second,
            }
        ),
        encoding="utf-8",
    )
    immutable_hash = hashlib.sha256(immutable.read_bytes()).hexdigest().upper()
    latest = root / "data/alerts/documentation_transaction_latest.json"
    latest.write_text(
        json.dumps(
            {
                "schema_version": LATEST_SCHEMA,
                "status": "PASS",
                "pending_sha256": pending["pending_sha256"],
                "documentation_tip": second,
                "immutable_receipt_path": str(immutable),
                "immutable_receipt_sha256": immutable_hash,
            }
        ),
        encoding="utf-8",
    )
    assert transaction_status(root, now=now)["state"] == "COMPLETE"

    (root / "third.txt").write_text("third\n", encoding="utf-8")
    _git(root, "add", "third.txt")
    _git(root, "commit", "-m", "third")
    third = _git(root, "rev-parse", "HEAD")
    next_pending = begin_transaction(root, integration_tip=third, branch="next", now=now)
    assert [row["integration_tip"] for row in next_pending["integrations"]] == [third]


def test_completion_requires_exact_pending_hash_and_canonical_doc_changes(tmp_path):
    root = _repo(tmp_path)
    integration_tip = _git(root, "rev-parse", "HEAD")
    pending = begin_transaction(root, integration_tip=integration_tip, branch="parent")

    for relative in REQUIRED_REVIEWED_DOCUMENTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"reviewed {relative}\n", encoding="utf-8")
    evidence = root / "data/alerts/merge.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text('{"ok": true}\n', encoding="utf-8")
    _git(root, "add", "docs")
    _git(root, "commit", "-m", "close documentation")
    documentation_tip = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/master", documentation_tip)

    manifest = root / "manifest.json"
    payload = {
        "schema_version": COMPLETION_SCHEMA,
        "pending_sha256": pending["pending_sha256"],
        "integration_tips": [integration_tip],
        "documentation_tip": documentation_tip,
        "documents_reviewed": sorted(REQUIRED_REVIEWED_DOCUMENTS),
        "evidence_paths": [str(evidence)],
        "summary": "Canonical state reconciled to the exact integration receipt.",
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    receipt = complete_transaction(root, manifest_path=manifest, run_checks=False)

    assert receipt["status"] == "PASS"
    assert receipt["immutable_receipt_sha256"]
    assert transaction_status(root)["state"] == "COMPLETE"

    immutable = Path(receipt["immutable_receipt_path"])
    immutable.write_text(immutable.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert transaction_status(root)["state"] == "PENDING"

    payload["pending_sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="does not bind"):
        complete_transaction(root, manifest_path=manifest, run_checks=False)


def _unchanged_completion(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = _repo(tmp_path)
    for relative in REQUIRED_REVIEWED_DOCUMENTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Accurate contract for {relative}\n", encoding="utf-8")
    _git(root, "add", "docs")
    _git(root, "commit", "-m", "integration with accurate documentation")
    tip = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/master", tip)
    pending = begin_transaction(root, integration_tip=tip, branch="reviewed-cleanup")
    evidence = root / "data/alerts/merge.json"
    evidence.write_text('{"recovered": true}\n', encoding="utf-8")
    payload = {
        "schema_version": COMPLETION_SCHEMA,
        "pending_sha256": pending["pending_sha256"],
        "integration_tips": [tip],
        "documentation_tip": tip,
        "documents_reviewed": sorted(REQUIRED_REVIEWED_DOCUMENTS),
        "documents_unchanged": {
            path: {
                "blob_oid": _git(root, "rev-parse", f"{tip}:{path}"),
                "reason": "The integrated cleanup leaves this document's facts and acceptance unchanged.",
            }
            for path in sorted(REQUIRED_DISPOSITION_DOCUMENTS)
        },
        "evidence_paths": [str(evidence)],
        "summary": "Reviewed accurate documentation against the integrated cleanup and recovery receipt.",
    }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return root, manifest, payload


def test_completion_accepts_bound_unchanged_docs_without_followup_commit(tmp_path, monkeypatch):
    root, manifest, payload = _unchanged_completion(tmp_path)
    checked = []

    def checks(repo_root, first_integration):
        checked.append((repo_root, first_integration))
        return {"roadmap_parity": {"status": "PASS"}}

    monkeypatch.setattr(documentation_transaction, "_completion_checks", checks)
    receipt = complete_transaction(root, manifest_path=manifest)

    assert receipt["documents_changed"] == []
    assert receipt["documents_unchanged"] == payload["documents_unchanged"]
    assert receipt["documentation_tip"] == payload["integration_tips"][-1]
    assert checked == [(root.resolve(), payload["integration_tips"][0])]
    assert transaction_status(root)["state"] == "COMPLETE"


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("missing_disposition", "need an update or bound unchanged review"),
        ("missing_review", "were not reviewed"),
        ("blank_reason", "reason must be nonempty"),
        ("stale_blob", "does not bind the committed blob"),
        ("malformed_dispositions", "must be an object"),
        ("unpublished_edit", "unpublished changes"),
        ("staged_edit_with_restored_worktree", "unpublished changes"),
        ("unpublished_deletion", "unpublished changes"),
        ("missing_evidence", "at least one durable evidence"),
        ("stale_origin", "must equal local master"),
    ],
)
def test_unchanged_completion_refuses_unbound_or_incomplete_review(tmp_path, defect, message):
    root, manifest, payload = _unchanged_completion(tmp_path)
    path = "docs/operations/STATE_OF_PLAY.md"
    if defect == "missing_disposition":
        payload["documents_unchanged"].pop(path)
    elif defect == "missing_review":
        payload["documents_reviewed"].remove(path)
    elif defect == "blank_reason":
        payload["documents_unchanged"][path]["reason"] = " "
    elif defect == "stale_blob":
        payload["documents_unchanged"][path]["blob_oid"] = "0" * 40
    elif defect == "malformed_dispositions":
        payload["documents_unchanged"] = []
    elif defect == "unpublished_edit":
        (root / path).write_text("Required factual correction not yet published.\n", encoding="utf-8")
    elif defect == "staged_edit_with_restored_worktree":
        committed_bytes = (root / path).read_bytes()
        (root / path).write_text("Required factual correction staged for publication.\n", encoding="utf-8")
        _git(root, "add", path)
        (root / path).write_bytes(committed_bytes)
        assert not _git(root, "diff", "--name-only", "HEAD", "--", path)
        assert _git(root, "diff", "--cached", "--name-only", "HEAD", "--", path) == path
    elif defect == "unpublished_deletion":
        (root / path).unlink()
    elif defect == "missing_evidence":
        payload["evidence_paths"] = []
    elif defect == "stale_origin":
        _git(root, "update-ref", "refs/remotes/origin/master", "HEAD^")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        complete_transaction(root, manifest_path=manifest, run_checks=False)
    assert transaction_status(root)["state"] == "PENDING"
    assert not list((root / "data/alerts/documentation_transactions").glob("receipt-*.json"))


def test_completion_combines_published_updates_with_unchanged_reviews(tmp_path):
    root, manifest, payload = _unchanged_completion(tmp_path)
    path = "docs/operations/STATE_OF_PLAY.md"
    (root / path).write_text("Updated blocker after the integration.\n", encoding="utf-8")
    _git(root, "add", path)
    _git(root, "commit", "-m", "publish required factual update")
    tip = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/master", tip)
    payload["documentation_tip"] = tip
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="have no post-integration diff"):
        complete_transaction(root, manifest_path=manifest, run_checks=False)

    payload["documents_unchanged"].pop(path)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    receipt = complete_transaction(root, manifest_path=manifest, run_checks=False)
    assert receipt["documents_changed"] == [path]
    assert set(receipt["documents_unchanged"]) == {"docs/roadmap/active-backlog.md"}


def test_unchanged_review_cannot_bypass_documentation_verification(tmp_path, monkeypatch):
    root, manifest, _payload = _unchanged_completion(tmp_path)

    def stale_backlog(*args):
        raise ValueError("documentation verification failed: roadmap_parity")

    monkeypatch.setattr(documentation_transaction, "_completion_checks", stale_backlog)
    with pytest.raises(ValueError, match="roadmap_parity"):
        complete_transaction(root, manifest_path=manifest)
    assert transaction_status(root)["state"] == "PENDING"


def test_unchanged_completion_requires_local_master_equality(tmp_path):
    root, manifest, _payload = _unchanged_completion(tmp_path)
    _git(root, "checkout", "-b", "other")
    _git(root, "update-ref", "refs/heads/master", "HEAD^")

    with pytest.raises(ValueError, match="must equal local master"):
        complete_transaction(root, manifest_path=manifest, run_checks=False)
