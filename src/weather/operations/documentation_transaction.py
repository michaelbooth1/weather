"""Bind post-integration documentation closeout to exact Git and receipt evidence.

Guarded merges call ``begin`` after capture recovery and before publication. Multiple
merges may accumulate in one overnight stack. A morning closeout commits and pushes
the documentation, supplies a small manifest, and calls ``complete``; the resulting
receipt covers the exact pending-state hash and therefore cannot clear later work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from weather.paths import REPO_ROOT


PENDING_SCHEMA = "documentation_transaction_pending_v0.1"
COMPLETION_SCHEMA = "documentation_transaction_completion_manifest_v0.1"
RECEIPT_SCHEMA = "documentation_transaction_receipt_v0.1"
LATEST_SCHEMA = "documentation_transaction_latest_v0.1"
ACTION_REQUIRED_LEAD = timedelta(hours=2)
ACTION_REQUIRED_LEAD_MINUTES = int(ACTION_REQUIRED_LEAD.total_seconds() // 60)
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_REVIEWED_DOCUMENTS = frozenset(
    {
        "docs/operations/STATE_OF_PLAY.md",
        "docs/operations/ESTABLISHED_FINDINGS.md",
        "docs/operations/RETRACTED_AND_FALSE_LEADS.md",
        "docs/roadmap/active-backlog.md",
    }
)
REQUIRED_CHANGED_DOCUMENTS = frozenset(
    {
        "docs/operations/STATE_OF_PLAY.md",
        "docs/roadmap/active-backlog.md",
    }
)


def _paths(repo_root: Path) -> dict[str, Path]:
    alerts = repo_root / "data" / "alerts"
    history = alerts / "documentation_transactions"
    return {
        "pending": alerts / "documentation_transaction_pending.json",
        "latest": alerts / "documentation_transaction_latest.json",
        "history": history,
    }


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _due_at(now: datetime) -> datetime:
    due = datetime.combine(now.date(), time(hour=9), tzinfo=now.tzinfo)
    return due if now < due else due + timedelta(days=1)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _git(repo_root: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _validate_full_commit(repo_root: Path, value: str, *, field: str) -> str:
    value = value.strip().lower()
    if not FULL_SHA_RE.fullmatch(value):
        raise ValueError(f"{field} must be a full 40-character Git SHA")
    resolved = _git(repo_root, "rev-parse", f"{value}^{{commit}}").lower()
    if resolved != value:
        raise ValueError(f"{field} does not resolve to its exact commit")
    return value


def _validate_pending(payload: dict[str, Any]) -> list[dict[str, str]]:
    if payload.get("schema_version") != PENDING_SCHEMA:
        raise ValueError("unsupported documentation pending schema")
    if payload.get("status") != "PENDING":
        raise ValueError("documentation pending state is not PENDING")
    integrations = payload.get("integrations")
    if not isinstance(integrations, list) or not integrations:
        raise ValueError("documentation pending state has no integrations")
    for entry in integrations:
        if not isinstance(entry, dict) or not FULL_SHA_RE.fullmatch(
            str(entry.get("integration_tip", ""))
        ):
            raise ValueError("documentation pending integration identity is invalid")
        if not str(entry.get("branch", "")).strip():
            raise ValueError("documentation pending integration branch is absent")
    datetime.fromisoformat(str(payload["created_at_local"]))
    datetime.fromisoformat(str(payload["due_at_local"]))
    return integrations


def begin_transaction(
    repo_root: Path,
    *,
    integration_tip: str,
    branch: str,
    expected_tip: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    integration_tip = _validate_full_commit(
        repo_root, integration_tip, field="integration_tip"
    )
    if _git(repo_root, "rev-parse", "HEAD").lower() != integration_tip:
        raise ValueError("integration_tip must equal the current local HEAD")
    if not branch.strip():
        raise ValueError("branch must be nonempty")
    if expected_tip:
        expected_tip = _validate_full_commit(repo_root, expected_tip, field="expected_tip")
        if subprocess.run(
            [
                "git", "-C", str(repo_root), "merge-base", "--is-ancestor",
                expected_tip, integration_tip,
            ],
            capture_output=True,
            check=False,
        ).returncode != 0:
            raise ValueError("expected_tip is not contained in the integration commit")

    paths = _paths(repo_root)
    current_time = now or _now_local()
    current_state = transaction_status(repo_root, now=current_time)
    if current_state["state"] == "COMPLETE":
        # The prior pending bytes remain preserved by their content-addressed snapshot and
        # immutable completion receipt. A new integration starts a new bounded transaction;
        # carrying completed tips forever would make every later closeout re-prove history.
        pending = {
            "schema_version": PENDING_SCHEMA,
            "status": "PENDING",
            "created_at_local": current_time.isoformat(),
            "due_at_local": _due_at(current_time).isoformat(),
            "integrations": [],
        }
        integrations = pending["integrations"]
    elif paths["pending"].is_file():
        pending = _read_object(paths["pending"])
        integrations = _validate_pending(pending)
    else:
        pending = {
            "schema_version": PENDING_SCHEMA,
            "status": "PENDING",
            "created_at_local": current_time.isoformat(),
            "due_at_local": _due_at(current_time).isoformat(),
            "integrations": [],
        }
        integrations = pending["integrations"]

    if not any(entry["integration_tip"] == integration_tip for entry in integrations):
        integrations.append(
            {
                "integration_tip": integration_tip,
                "branch": branch.strip(),
                "expected_tip": expected_tip or None,
                "recorded_at_local": current_time.isoformat(),
            }
        )
    pending["latest_integration_tip"] = integrations[-1]["integration_tip"]
    _atomic_json(paths["pending"], pending)
    pending_hash = _sha256_file(paths["pending"])
    snapshot = paths["history"] / f"pending-{pending_hash}.json"
    if not snapshot.exists():
        _atomic_json(snapshot, pending)
    return {**pending, "pending_sha256": pending_hash}


def transaction_status(
    repo_root: Path, *, now: datetime | None = None
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    paths = _paths(repo_root)
    if not paths["pending"].is_file():
        return {
            "state": "NO_PENDING",
            "valid": True,
            "overdue": False,
            "action_required": False,
            "action_lead_minutes": ACTION_REQUIRED_LEAD_MINUTES,
        }
    try:
        pending = _read_object(paths["pending"])
        integrations = _validate_pending(pending)
        pending_hash = _sha256_file(paths["pending"])
        due_at = datetime.fromisoformat(str(pending["due_at_local"]))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {
            "state": "INVALID",
            "valid": False,
            "overdue": True,
            "action_required": True,
            "action_lead_minutes": ACTION_REQUIRED_LEAD_MINUTES,
            "detail": str(exc),
        }

    current_time = now or _now_local()
    action_required_at = due_at - ACTION_REQUIRED_LEAD
    result: dict[str, Any] = {
        "state": "PENDING",
        "valid": True,
        "overdue": current_time >= due_at,
        "action_required": current_time >= action_required_at,
        "action_required_at_local": action_required_at.isoformat(),
        "action_lead_minutes": ACTION_REQUIRED_LEAD_MINUTES,
        "minutes_until_due": round((due_at - current_time).total_seconds() / 60, 1),
        "due_at_local": due_at.isoformat(),
        "pending_sha256": pending_hash,
        "integration_count": len(integrations),
        "integration_tips": [entry["integration_tip"] for entry in integrations],
    }
    if not paths["latest"].is_file():
        return result
    try:
        latest = _read_object(paths["latest"])
        immutable_path = Path(str(latest.get("immutable_receipt_path", "")))
        if not immutable_path.is_absolute():
            immutable_path = repo_root / immutable_path
        receipt = _read_object(immutable_path)
        documentation_tip = str(receipt.get("documentation_tip", "")).lower()
        receipt_valid = (
            latest.get("schema_version") == LATEST_SCHEMA
            and latest.get("pending_sha256") == pending_hash
            and latest.get("documentation_tip") == documentation_tip
            and latest.get("immutable_receipt_sha256") == _sha256_file(immutable_path)
            and receipt.get("schema_version") == RECEIPT_SCHEMA
            and receipt.get("status") == "PASS"
            and receipt.get("pending_sha256") == pending_hash
            and receipt.get("integration_tips")
            == [entry["integration_tip"] for entry in integrations]
            and FULL_SHA_RE.fullmatch(documentation_tip)
            and subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "merge-base",
                    "--is-ancestor",
                    documentation_tip,
                    "HEAD",
                ],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, ValueError, json.JSONDecodeError):
        receipt_valid = False
    if receipt_valid:
        result.update(
            {
                "state": "COMPLETE",
                "overdue": False,
                "action_required": False,
                "documentation_tip": documentation_tip,
                "receipt_path": str(immutable_path),
                "receipt_sha256": _sha256_file(immutable_path),
            }
        )
    return result


def _run_check(command: list[str], *, repo_root: Path, timeout: int = 180) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "exit_code": completed.returncode,
        "command": command,
        "output": output[-8000:],
    }


def _completion_checks(repo_root: Path, first_integration: str) -> dict[str, Any]:
    python = repo_root / "venv" / "Scripts" / "python.exe"
    if not python.is_file():
        python = Path(sys.executable)
    commands = {
        "git_diff_check": [
            "git", "-C", str(repo_root), "diff", "--check", f"{first_integration}..HEAD"
        ],
        "agent_docs_audit": [
            str(python), "-m", "weather.operations.agent_docs_audit", "--repo-root", str(repo_root)
        ],
        "roadmap_parity": [
            str(python), "-m", "weather.reporting.roadmap.roadmap_backlog",
            "--fail-on-lint", "--check",
        ],
        "focused_tests": [
            str(python), "-m", "pytest",
            "tests/operations/test_agent_docs_audit.py",
            "tests/operations/test_operating_reference.py",
            "tests/reporting/test_roadmap_backlog.py", "-q",
        ],
    }
    results = {
        name: _run_check(command, repo_root=repo_root)
        for name, command in commands.items()
    }
    failed = [name for name, result in results.items() if result["status"] != "PASS"]
    if failed:
        raise ValueError(f"documentation verification failed: {', '.join(failed)}")
    return results


def complete_transaction(
    repo_root: Path,
    *,
    manifest_path: Path,
    run_checks: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    paths = _paths(repo_root)
    if not paths["pending"].is_file():
        raise ValueError("no pending documentation transaction exists")
    pending = _read_object(paths["pending"])
    integrations = _validate_pending(pending)
    pending_hash = _sha256_file(paths["pending"])
    manifest = _read_object(manifest_path)
    if manifest.get("schema_version") != COMPLETION_SCHEMA:
        raise ValueError("unsupported documentation completion manifest schema")
    if manifest.get("pending_sha256") != pending_hash:
        raise ValueError("completion manifest does not bind the current pending state")

    documentation_tip = _validate_full_commit(
        repo_root, str(manifest.get("documentation_tip", "")), field="documentation_tip"
    )
    head = _git(repo_root, "rev-parse", "HEAD").lower()
    origin = _git(repo_root, "rev-parse", "origin/master").lower()
    if documentation_tip != head or documentation_tip != origin:
        raise ValueError("documentation tip must equal local master and origin/master")

    pending_tips = [entry["integration_tip"] for entry in integrations]
    manifest_tips = [str(value).lower() for value in manifest.get("integration_tips", [])]
    if manifest_tips != pending_tips:
        raise ValueError("completion manifest integration tips do not exactly match pending state")
    for tip in pending_tips:
        if subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", tip, documentation_tip],
            capture_output=True,
            check=False,
        ).returncode != 0:
            raise ValueError(f"integration tip is not an ancestor of documentation tip: {tip}")

    reviewed = {str(path).replace("\\", "/") for path in manifest.get("documents_reviewed", [])}
    missing_review = sorted(REQUIRED_REVIEWED_DOCUMENTS - reviewed)
    if missing_review:
        raise ValueError(f"required canonical documents were not reviewed: {missing_review}")
    changed = {
        line.replace("\\", "/")
        for line in _git(
            repo_root, "diff", "--name-only", f"{pending_tips[-1]}..{documentation_tip}"
        ).splitlines()
        if line
    }
    missing_changes = sorted(REQUIRED_CHANGED_DOCUMENTS - changed)
    if missing_changes:
        raise ValueError(f"post-integration documentation did not change: {missing_changes}")

    evidence: list[dict[str, str]] = []
    for raw_path in manifest.get("evidence_paths", []):
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = repo_root / path
        if not path.is_file():
            raise ValueError(f"documentation evidence path is absent: {path}")
        evidence.append({"path": str(path), "sha256": _sha256_file(path)})
    if not evidence:
        raise ValueError("at least one durable evidence path is required")

    checks = _completion_checks(repo_root, pending_tips[0]) if run_checks else {}
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "PASS",
        "completed_at_local": (now or _now_local()).isoformat(),
        "pending_sha256": pending_hash,
        "integration_tips": pending_tips,
        "documentation_tip": documentation_tip,
        "summary": str(manifest.get("summary", "")).strip(),
        "documents_reviewed": sorted(reviewed),
        "documents_changed": sorted(changed),
        "evidence": evidence,
        "verification": checks,
    }
    if not receipt["summary"]:
        raise ValueError("completion summary must be nonempty")
    immutable = paths["history"] / (
        f"receipt-{documentation_tip[:12]}-{pending_hash[:12]}.json"
    )
    if immutable.exists():
        raise ValueError(f"immutable documentation receipt already exists: {immutable}")
    _atomic_json(immutable, receipt)
    immutable_hash = _sha256_file(immutable)
    _atomic_json(
        paths["latest"],
        {
            "schema_version": LATEST_SCHEMA,
            "status": "PASS",
            "pending_sha256": pending_hash,
            "documentation_tip": documentation_tip,
            "immutable_receipt_path": str(immutable),
            "immutable_receipt_sha256": immutable_hash,
        },
    )
    return {
        **receipt,
        "immutable_receipt_path": str(immutable),
        "immutable_receipt_sha256": immutable_hash,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    begin = subparsers.add_parser("begin")
    begin.add_argument("--integration-tip", required=True)
    begin.add_argument("--branch", required=True)
    begin.add_argument("--expected-tip", default="")

    subparsers.add_parser("status")

    complete = subparsers.add_parser("complete")
    complete.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "begin":
            payload = begin_transaction(
                args.repo_root,
                integration_tip=args.integration_tip,
                branch=args.branch,
                expected_tip=args.expected_tip,
            )
        elif args.command == "complete":
            payload = complete_transaction(args.repo_root, manifest_path=args.manifest)
        else:
            payload = transaction_status(args.repo_root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"state": "INVALID", "valid": False, "detail": str(exc)}))
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
