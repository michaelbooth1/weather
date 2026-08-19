from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.operations.documentation_transaction import (
    COMPLETION_SCHEMA,
    LATEST_SCHEMA,
    RECEIPT_SCHEMA,
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
