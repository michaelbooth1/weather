"""Deduplicated repository operations for tape backup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from weather.operations.tape_backup_manifest import *  # noqa: F403


def _tail_text(text, limit=4000):
    text = str(text or "")
    if len(text) <= int(limit):
        return text
    return text[-int(limit):]


def _path_relative_to_root(path, root):
    path = Path(path).resolve()
    root = Path(root).resolve()
    return path.relative_to(root).as_posix()


def _dedup_env(repository=None, password_file=None, env=None):
    merged = dict(os.environ if env is None else env)
    repo = (
        str(repository or "").strip()
        or str(merged.get("WEATHER_TAPE_DEDUP_REPOSITORY") or "").strip()
        or str(merged.get("RESTIC_REPOSITORY") or "").strip()
    )
    if repo:
        merged["RESTIC_REPOSITORY"] = repo
    if password_file:
        merged["RESTIC_PASSWORD_FILE"] = str(password_file)
    elif merged.get("WEATHER_TAPE_DEDUP_PASSWORD_FILE") and not merged.get("RESTIC_PASSWORD_FILE"):
        merged["RESTIC_PASSWORD_FILE"] = str(merged["WEATHER_TAPE_DEDUP_PASSWORD_FILE"])
    if (
        merged.get("WEATHER_TAPE_DEDUP_PASSWORD")
        and not merged.get("RESTIC_PASSWORD")
        and not merged.get("RESTIC_PASSWORD_FILE")
        and not merged.get("RESTIC_PASSWORD_COMMAND")
    ):
        merged["RESTIC_PASSWORD"] = str(merged["WEATHER_TAPE_DEDUP_PASSWORD"])
    return merged, repo


def _restic_credential_sources(env):
    return [
        name for name in ("RESTIC_PASSWORD_FILE", "RESTIC_PASSWORD_COMMAND", "RESTIC_PASSWORD")
        if env.get(name)
    ]


def dedup_repository_preflight(
    *,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    env=None,
):
    merged_env, repo = _dedup_env(repository=repository, password_file=password_file, env=env)
    backend = str(backend or "").strip().lower()
    credential_sources = _restic_credential_sources(merged_env)
    binary_path = shutil.which(str(executable), path=merged_env.get("PATH"))
    failures = []
    if backend != DEDUP_BACKEND_RESTIC:
        failures.append({"check": "backend", "reason": f"unsupported backend {backend or '-'}"})
    if not repo:
        failures.append({
            "check": "repository",
            "reason": "set WEATHER_TAPE_DEDUP_REPOSITORY or RESTIC_REPOSITORY",
        })
    if not credential_sources:
        failures.append({
            "check": "credentials",
            "reason": "set RESTIC_PASSWORD_FILE, RESTIC_PASSWORD_COMMAND, or RESTIC_PASSWORD",
        })
    if not binary_path:
        failures.append({"check": "restic_binary", "reason": f"{executable} was not found on PATH"})
    return {
        "status": "PASS" if not failures else "CONFIGURATION_INCOMPLETE",
        "backend": backend,
        "repository": repo,
        "executable": str(executable),
        "binary_path": binary_path,
        "credential_sources": credential_sources,
        "credential_material_present": bool(credential_sources),
        "failures": failures,
    }, merged_env


def _run_restic(executable, args, *, cwd=None, env=None, timeout_seconds=3600):
    command = [str(executable), *[str(arg) for arg in args]]
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "status": "MISSING_RESTIC_BINARY",
            "command": command,
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": str(exc),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "TIMEOUT",
            "command": command,
            "returncode": None,
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr or f"timed out after {timeout_seconds}s"),
        }
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stdout_tail": _tail_text(completed.stdout),
        "stderr_tail": _tail_text(completed.stderr),
    }


def _parse_restic_snapshots(stdout):
    try:
        payload = json.loads(stdout or "[]")
    except json.JSONDecodeError as exc:
        return [], str(exc)
    if isinstance(payload, dict):
        payload = payload.get("snapshots") or []
    if not isinstance(payload, list):
        return [], "restic snapshots JSON was not a list"
    snapshots = [row for row in payload if isinstance(row, dict)]
    return snapshots, None


def _latest_restic_snapshot(stdout):
    snapshots, error = _parse_restic_snapshots(stdout)
    if error:
        return None, snapshots, error
    latest = None
    latest_time = None
    for row in snapshots:
        parsed = _parse_time(row.get("time"))
        if parsed is None:
            continue
        if latest_time is None or parsed > latest_time:
            latest = row
            latest_time = parsed
    if latest is None and snapshots:
        latest = snapshots[-1]
    return latest, snapshots, None


def _snapshot_id_from_backup_output(stdout):
    snapshot_id = None
    for line in str(stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            snapshot_id = row.get("snapshot_id") or row.get("id") or snapshot_id
    return snapshot_id


def load_dedup_restore_drill_status(path=DEFAULT_DEDUP_RESTORE_OUT):
    path = Path(path)
    if not path.exists():
        return {"exists": False, "path": str(path), "status": "MISSING"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"exists": True, "path": str(path), "status": "UNREADABLE", "error": str(exc)}
    payload["exists"] = True
    payload["path"] = str(path)
    generated = _parse_time(payload.get("generated_at_utc"))
    if generated:
        payload["age_hours"] = round((utc_now() - generated).total_seconds() / 3600.0, 3)
    return payload


def dedup_restore_drill_sla_status(restore, snapshot_id=None, max_restore_age_hours=168):
    restore = restore or {}
    if not restore.get("exists"):
        return "RESTORE_DRILL_MISSING", "no dedup repository restore drill evidence recorded"
    if restore.get("status") in {"UNREADABLE", "FAIL"}:
        return "RESTORE_DRILL_FAIL", restore.get("error") or "dedup repository restore drill failed"
    if restore.get("status") != "PASS":
        return "RESTORE_DRILL_FAIL", f"unexpected restore drill status {restore.get('status')}"
    if snapshot_id and restore.get("snapshot_id") != snapshot_id:
        return "RESTORE_DRILL_STALE", "restore drill snapshot does not match latest dedup repository snapshot"
    age_hours = restore.get("age_hours")
    if age_hours is not None and float(age_hours) > float(max_restore_age_hours):
        return "RESTORE_DRILL_STALE", f"restore drill age {age_hours}h exceeds SLA {max_restore_age_hours}h"
    return "OK", "dedup repository restore drill evidence is current"


def dedup_repository_status(
    *,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    restore_drill_path=DEFAULT_DEDUP_RESTORE_OUT,
    max_age_hours=26,
    max_restore_age_hours=168,
    require_restore_drill=True,
    env=None,
    timeout_seconds=300,
):
    preflight, merged_env = dedup_repository_preflight(
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        env=env,
    )
    payload = {
        "schema_version": DEDUP_REPOSITORY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "kind": "status",
        "status": preflight["status"],
        "backend": preflight["backend"],
        "repository": preflight["repository"],
        "preflight": preflight,
        "snapshot_tag": DEDUP_RESTIC_TAG,
        "snapshot_count": 0,
        "latest_snapshot": None,
        "latest_snapshot_age_hours": None,
        "commands": {},
        "last_restore_drill": load_dedup_restore_drill_status(restore_drill_path),
        "restore_drill_sla_status": "-",
        "restore_drill_sla_detail": "restore drill not checked",
    }
    if preflight["status"] != "PASS":
        return payload
    snapshots = _run_restic(
        executable,
        ["snapshots", "--json", "--tag", DEDUP_RESTIC_TAG],
        env=merged_env,
        timeout_seconds=timeout_seconds,
    )
    payload["commands"]["snapshots"] = snapshots
    if snapshots["status"] != "PASS":
        payload["status"] = "REPOSITORY_UNREACHABLE"
        return payload
    latest, parsed_snapshots, parse_error = _latest_restic_snapshot(snapshots.get("stdout") or snapshots.get("stdout_tail") or "")
    payload["snapshot_count"] = len(parsed_snapshots)
    if parse_error:
        payload["status"] = "SNAPSHOT_STATUS_UNREADABLE"
        payload["snapshot_parse_error"] = parse_error
        return payload
    if not latest:
        payload["status"] = "NO_SNAPSHOTS"
        return payload
    generated = _parse_time(latest.get("time"))
    age_hours = None
    if generated:
        age_hours = round((utc_now() - generated).total_seconds() / 3600.0, 3)
    payload["latest_snapshot"] = latest
    payload["latest_snapshot_age_hours"] = age_hours
    payload["status"] = "OK"
    if age_hours is not None and age_hours > float(max_age_hours):
        payload["status"] = "STALE"
    if require_restore_drill:
        restore_status, restore_detail = dedup_restore_drill_sla_status(
            payload["last_restore_drill"],
            snapshot_id=latest.get("id") or latest.get("short_id"),
            max_restore_age_hours=max_restore_age_hours,
        )
        payload["restore_drill_sla_status"] = restore_status
        payload["restore_drill_sla_detail"] = restore_detail
        if payload["status"] == "OK" and restore_status != "OK":
            payload["status"] = restore_status
    return payload


def write_dedup_status_report(path, payload):
    latest = payload.get("latest_snapshot") or {}
    lines = [
        "# Deduplicated Tape Repository Status",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Backend: `{payload.get('backend')}`",
        f"Repository: `{payload.get('repository') or '-'}`",
        f"Snapshot tag: `{payload.get('snapshot_tag')}`",
        f"Snapshot count: `{payload.get('snapshot_count')}`",
        f"Latest snapshot: `{latest.get('id') or latest.get('short_id') or '-'}`",
        f"Latest snapshot age hours: `{payload.get('latest_snapshot_age_hours')}`",
        f"Restore drill SLA: **{payload.get('restore_drill_sla_status') or '-'}**",
        f"Restore drill detail: `{payload.get('restore_drill_sla_detail') or '-'}`",
        "",
        "## Preflight",
        "",
    ]
    failures = (payload.get("preflight") or {}).get("failures") or []
    if failures:
        lines.extend(f"- `{row.get('check')}`: {row.get('reason')}" for row in failures)
    else:
        lines.append("- configuration complete")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_dedup_backup_report(path, payload):
    lines = [
        "# Deduplicated Tape Repository Backup",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Backend: `{payload.get('backend')}`",
        f"Repository: `{payload.get('repository') or '-'}`",
        f"Snapshot id: `{payload.get('snapshot_id') or '-'}`",
        f"Manifest hash: `{payload.get('manifest_hash') or '-'}`",
        f"Files listed: `{payload.get('files_from_count') or 0}`",
        f"Total bytes: `{payload.get('total_bytes') or 0}`",
        "",
        "## Missing Critical Classes",
        "",
    ]
    lines.extend(f"- {name}" for name in payload.get("missing_critical_classes") or ["-"])
    failures = (payload.get("preflight") or {}).get("failures") or []
    if failures:
        lines += ["", "## Preflight Failures", ""]
        lines.extend(f"- `{row.get('check')}`: {row.get('reason')}" for row in failures)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_dedup_backup(
    *,
    source_root=REPO_ROOT,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    manifest_out=None,
    out=DEFAULT_DEDUP_BACKUP_OUT,
    report=DEFAULT_DEDUP_BACKUP_REPORT,
    env=None,
    timeout_seconds=3600,
):
    source_root = Path(source_root)
    preflight, merged_env = dedup_repository_preflight(
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        env=env,
    )
    payload = {
        "schema_version": DEDUP_REPOSITORY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "kind": "backup",
        "status": preflight["status"],
        "backend": preflight["backend"],
        "repository": preflight["repository"],
        "source_root": str(source_root),
        "preflight": preflight,
        "snapshot_tag": DEDUP_RESTIC_TAG,
        "commands": {},
    }
    if preflight["status"] != "PASS":
        write_json(out, payload)
        _write_dedup_backup_report(report, payload)
        return payload

    manifest = build_backup_manifest(source_root)
    manifest_out = Path(manifest_out) if manifest_out else default_dedup_manifest_path(source_root)
    manifest_rel = _path_relative_to_root(manifest_out, source_root)
    write_json(manifest_out, manifest)
    file_paths = [row["path"] for row in manifest.get("files") or []]
    if manifest_rel not in file_paths:
        file_paths.append(manifest_rel)
    file_paths = sorted(dict.fromkeys(file_paths))

    probe = _run_restic(
        executable,
        ["snapshots", "--json", "--tag", DEDUP_RESTIC_TAG],
        env=merged_env,
        timeout_seconds=timeout_seconds,
    )
    payload["commands"]["repository_probe"] = probe
    payload.update({
        "manifest_path": str(manifest_out),
        "manifest_rel_path": manifest_rel,
        "manifest_hash": manifest.get("manifest_hash"),
        "file_count": (manifest.get("summary") or {}).get("file_count"),
        "files_from_count": len(file_paths),
        "total_bytes": (manifest.get("summary") or {}).get("total_bytes"),
        "missing_critical_classes": (manifest.get("summary") or {}).get("missing_critical_classes") or [],
    })
    if probe["status"] != "PASS":
        payload["status"] = "REPOSITORY_UNREACHABLE"
        write_json(out, payload)
        _write_dedup_backup_report(report, payload)
        return payload

    with tempfile.TemporaryDirectory(prefix="weather-tape-restic-files-") as tmp:
        files_from = Path(tmp) / "files-from.txt"
        files_from.write_text("\n".join(file_paths) + "\n", encoding="utf-8")
        backup = _run_restic(
            executable,
            [
                "backup",
                "--files-from",
                str(files_from),
                "--tag",
                DEDUP_RESTIC_TAG,
                "--tag",
                POLICY_VERSION,
                "--json",
            ],
            cwd=source_root,
            env=merged_env,
            timeout_seconds=timeout_seconds,
        )
    payload["commands"]["backup"] = backup
    payload["snapshot_id"] = _snapshot_id_from_backup_output(backup.get("stdout_tail") or "")
    payload["status"] = "PASS" if backup["status"] == "PASS" else "BACKUP_FAILED"
    write_json(out, payload)
    _write_dedup_backup_report(report, payload)
    return payload


def _first_path_matching(entries, predicate):
    for entry in entries:
        path = entry.get("path") or ""
        if predicate(path, entry):
            return path
    return None


def select_dedup_restore_drill_paths(manifest, *, control_manifest_rel_path=None):
    entries = manifest.get("files") or []
    categories = {
        "raw_order_book_jsonl": _first_path_matching(
            entries,
            lambda path, entry: path.endswith("order_books.jsonl"),
        ) or _first_path_matching(
            entries,
            lambda path, entry: path.endswith(".jsonl") and bool(_critical_classes(entry.get("classes") or [])),
        ),
        "parquet_partition": _first_path_matching(entries, lambda path, entry: path.endswith(".parquet")),
        "archive_manifest": _first_path_matching(
            entries,
            lambda path, entry: path.endswith("closed_market_day_archive_manifest.json"),
        ) or _first_path_matching(entries, lambda path, entry: path.endswith("/manifest.json")),
        "replay_artifact": _first_path_matching(
            entries,
            lambda path, entry: path.startswith("artifacts/"),
        ) or _first_path_matching(
            entries,
            lambda path, entry: path.endswith("replay_inputs.jsonl") or path.endswith("replay_inputs_reconstructed.jsonl"),
        ),
    }
    paths = []
    if control_manifest_rel_path:
        paths.append(control_manifest_rel_path)
    for path in categories.values():
        if path:
            paths.append(path)
    return {
        "categories": categories,
        "missing_categories": [name for name, path in categories.items() if not path],
        "paths": sorted(dict.fromkeys(paths)),
    }


def _closed_archive_parquet_expectations(restore_root, selected_paths):
    restore_root = Path(restore_root)
    expectations = {}
    for rel in selected_paths:
        if not str(rel).endswith("closed_market_day_archive_manifest.json"):
            continue
        path = restore_root / rel
        if not path.exists():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for family in manifest.get("artifact_families") or []:
            parquet = family.get("parquet") or {}
            parquet_rel = parquet.get("path")
            if not parquet_rel:
                continue
            try:
                key = (path.parent / parquet_rel).relative_to(restore_root).as_posix()
            except ValueError:
                continue
            expectations[key] = parquet.get("row_count")
    return expectations


def _parquet_row_count(path):
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        return {"status": "skipped", "reason": f"pyarrow unavailable: {exc}"}
    try:
        return {"status": "ok", "row_count": int(pq.ParquetFile(path).metadata.num_rows)}
    except Exception as exc:  # noqa: BLE001 - row-count validation must report the parser failure
        return {"status": "fail", "reason": str(exc)}


def _verify_dedup_restored_paths(restore_root, manifest, selected):
    restore_root = Path(restore_root)
    manifest_entries = _manifest_entry_map(manifest)
    expectations = _closed_archive_parquet_expectations(restore_root, selected)
    failures = []
    schema_checks = []
    parquet_checks = []
    verified = 0
    for rel in selected:
        if rel not in manifest_entries:
            continue
        entry = manifest_entries[rel]
        path = restore_root / rel
        if not path.exists():
            failures.append({"path": rel, "reason": "missing_restored_file"})
            continue
        verified += 1
        actual_sha = sha256_file(path)
        if actual_sha != entry.get("sha256"):
            failures.append({
                "path": rel,
                "reason": "restored_sha256_mismatch",
                "expected": entry.get("sha256"),
                "actual": actual_sha,
            })
        check = _schema_check(path)
        if check:
            schema_checks.append(check)
        if rel.endswith(".parquet"):
            parquet_check = {"path": rel, **_parquet_row_count(path)}
            expected = expectations.get(rel)
            if expected is not None and parquet_check.get("status") == "ok":
                parquet_check["expected_row_count"] = int(expected)
                if int(expected) != int(parquet_check.get("row_count") or -1):
                    parquet_check["status"] = "fail"
                    parquet_check["reason"] = "row_count_mismatch"
            parquet_checks.append(parquet_check)
    schema_failures = [row for row in schema_checks if row.get("status") not in {"ok"}]
    parquet_failures = [row for row in parquet_checks if row.get("status") == "fail"]
    return {
        "verified_files": verified,
        "checksum_failures": failures,
        "schema_checks": schema_checks,
        "schema_failures": schema_failures,
        "parquet_checks": parquet_checks,
        "parquet_failures": parquet_failures,
    }


def _write_dedup_restore_report(path, payload):
    lines = [
        "# Deduplicated Tape Repository Restore Drill",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Backend: `{payload.get('backend')}`",
        f"Repository: `{payload.get('repository') or '-'}`",
        f"Snapshot id: `{payload.get('snapshot_id') or '-'}`",
        f"Restore root: `{payload.get('restore_root') or '-'}`",
        f"Manifest hash: `{payload.get('manifest_hash') or '-'}`",
        f"Verified files: `{payload.get('verified_files') or 0}`",
        "",
        "## Drill Categories",
        "",
    ]
    for name, rel in (payload.get("drill_selection") or {}).get("categories", {}).items():
        lines.append(f"- `{name}`: `{rel or 'MISSING'}`")
    failures = (
        (payload.get("checksum_failures") or [])
        + (payload.get("schema_failures") or [])
        + (payload.get("parquet_failures") or [])
    )
    lines += ["", "## Failures", ""]
    if failures:
        lines.extend(f"- `{row.get('path')}`: {row.get('reason') or row.get('status')}" for row in failures)
    else:
        lines.append("- none")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_dedup_restore_drill(
    *,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    snapshot_id=None,
    manifest_rel_path=f"data/backtest/{DEFAULT_DEDUP_MANIFEST_NAME}",
    restore_root=None,
    keep_restore=False,
    out=DEFAULT_DEDUP_RESTORE_OUT,
    report=DEFAULT_DEDUP_RESTORE_REPORT,
    env=None,
    timeout_seconds=3600,
):
    status_payload = dedup_repository_status(
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        require_restore_drill=False,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    latest = status_payload.get("latest_snapshot") or {}
    snapshot_id = snapshot_id or latest.get("id") or latest.get("short_id")
    temp_ctx = None
    if restore_root is None:
        temp_ctx = tempfile.TemporaryDirectory(prefix="weather-tape-dedup-restore-")
        restore_root = Path(temp_ctx.name)
    else:
        restore_root = Path(restore_root)
        restore_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": DEDUP_REPOSITORY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "kind": "restore_drill",
        "status": "FAIL",
        "backend": status_payload.get("backend"),
        "repository": status_payload.get("repository"),
        "snapshot_tag": DEDUP_RESTIC_TAG,
        "snapshot_id": snapshot_id,
        "restore_root": str(restore_root),
        "keep_restore": bool(keep_restore),
        "repository_status": status_payload,
        "commands": {},
        "manifest_rel_path": manifest_rel_path,
        "manifest_valid": False,
        "manifest_detail": "not restored",
        "manifest_hash": None,
        "verified_files": 0,
        "drill_selection": {"categories": {}, "missing_categories": [], "paths": []},
        "checksum_failures": [],
        "schema_checks": [],
        "schema_failures": [],
        "parquet_checks": [],
        "parquet_failures": [],
    }
    try:
        if status_payload.get("status") not in {"OK", "STALE"} or not snapshot_id:
            payload["failure_reason"] = "dedup repository has no restorable snapshot"
            write_json(out, payload)
            _write_dedup_restore_report(report, payload)
            return payload
        preflight, merged_env = dedup_repository_preflight(
            backend=backend,
            repository=repository,
            executable=executable,
            password_file=password_file,
            env=env,
        )
        if preflight["status"] != "PASS":
            payload["preflight"] = preflight
            payload["failure_reason"] = "dedup repository configuration incomplete"
            write_json(out, payload)
            _write_dedup_restore_report(report, payload)
            return payload
        restore_manifest = _run_restic(
            executable,
            ["restore", snapshot_id, "--target", str(restore_root), "--include", manifest_rel_path],
            env=merged_env,
            timeout_seconds=timeout_seconds,
        )
        payload["commands"]["restore_manifest"] = restore_manifest
        manifest_path = restore_root / manifest_rel_path
        if restore_manifest["status"] != "PASS" or not manifest_path.exists():
            payload["failure_reason"] = "control manifest was not restored"
            write_json(out, payload)
            _write_dedup_restore_report(report, payload)
            return payload
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        valid, detail = validate_manifest(manifest)
        payload["manifest_valid"] = valid
        payload["manifest_detail"] = detail
        payload["manifest_hash"] = manifest.get("manifest_hash")
        selection = select_dedup_restore_drill_paths(
            manifest,
            control_manifest_rel_path=manifest_rel_path,
        )
        payload["drill_selection"] = selection
        include_args = []
        for rel in selection.get("paths") or []:
            include_args.extend(["--include", rel])
        restore_selected = _run_restic(
            executable,
            ["restore", snapshot_id, "--target", str(restore_root), *include_args],
            env=merged_env,
            timeout_seconds=timeout_seconds,
        )
        payload["commands"]["restore_selected"] = restore_selected
        verification = _verify_dedup_restored_paths(
            restore_root,
            manifest,
            [rel for rel in selection.get("paths") or [] if rel != manifest_rel_path],
        )
        payload.update(verification)
        failures = (
            not valid
            or restore_selected["status"] != "PASS"
            or selection.get("missing_categories")
            or verification.get("checksum_failures")
            or verification.get("schema_failures")
            or verification.get("parquet_failures")
        )
        payload["status"] = "FAIL" if failures else "PASS"
        write_json(out, payload)
        _write_dedup_restore_report(report, payload)
        return payload
    finally:
        if temp_ctx is not None and not keep_restore:
            temp_ctx.cleanup()


def run_dedup_job(
    *,
    source_root=REPO_ROOT,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    manifest_out=None,
    backup_out=DEFAULT_DEDUP_BACKUP_OUT,
    backup_report=DEFAULT_DEDUP_BACKUP_REPORT,
    restore_out=DEFAULT_DEDUP_RESTORE_OUT,
    restore_report=DEFAULT_DEDUP_RESTORE_REPORT,
    status_out=DEFAULT_DEDUP_STATUS_OUT,
    status_report=DEFAULT_DEDUP_STATUS_REPORT,
    restore_root=None,
    keep_restore=False,
    env=None,
    timeout_seconds=3600,
):
    backup = run_dedup_backup(
        source_root=source_root,
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        manifest_out=manifest_out,
        out=backup_out,
        report=backup_report,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    restore = {"status": "SKIPPED", "reason": "backup did not pass"}
    if backup.get("status") == "PASS":
        restore = run_dedup_restore_drill(
            backend=backend,
            repository=repository,
            executable=executable,
            password_file=password_file,
            snapshot_id=backup.get("snapshot_id") or None,
            manifest_rel_path=backup.get("manifest_rel_path") or f"data/backtest/{DEFAULT_DEDUP_MANIFEST_NAME}",
            restore_root=restore_root,
            keep_restore=keep_restore,
            out=restore_out,
            report=restore_report,
            env=env,
            timeout_seconds=timeout_seconds,
        )
    status = dedup_repository_status(
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        restore_drill_path=restore_out,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    write_json(status_out, status)
    write_dedup_status_report(status_report, status)
    return {
        "schema_version": DEDUP_REPOSITORY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "kind": "job",
        "status": "PASS" if backup.get("status") == "PASS" and restore.get("status") == "PASS" and status.get("status") == "OK" else "FAIL",
        "backup": backup,
        "restore_drill": restore,
        "repository_status": status,
        "backup_out": str(backup_out),
        "backup_report": str(backup_report),
        "restore_out": str(restore_out),
        "restore_report": str(restore_report),
        "status_out": str(status_out),
        "status_report": str(status_report),
    }


__all__ = [
    "_tail_text",
    "_path_relative_to_root",
    "_dedup_env",
    "_restic_credential_sources",
    "dedup_repository_preflight",
    "_run_restic",
    "_parse_restic_snapshots",
    "_latest_restic_snapshot",
    "_snapshot_id_from_backup_output",
    "load_dedup_restore_drill_status",
    "dedup_restore_drill_sla_status",
    "dedup_repository_status",
    "write_dedup_status_report",
    "_write_dedup_backup_report",
    "run_dedup_backup",
    "_first_path_matching",
    "select_dedup_restore_drill_paths",
    "_closed_archive_parquet_expectations",
    "_parquet_row_count",
    "_verify_dedup_restored_paths",
    "_write_dedup_restore_report",
    "run_dedup_restore_drill",
    "run_dedup_job",
]
