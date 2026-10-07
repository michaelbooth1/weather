"""Every Windows-only test runs in exactly one Windows qualification shard.

Guards: pinned Windows qualification shard plan and Windows-only coverage (owner decision 2026-10-04, item K Defender condition).

Shards are rebalanced by time, so file lists move between them. These checks
prove by real pytest collection that no move can drop or duplicate a test:

* the matrix equals the pinned plan below, so any move is an explicit edit;
* each file is in exactly one shard, except a ``split_file`` shared by several
  shards whose ``split_select`` expressions partition its tests exactly and
  never filter another file in the same shard;
* every test file that skips (or returns early) off Windows is in some shard,
  so a Windows-only regression cannot be invisible to CI.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "windows-qualification.yml"

# Pinned shard plan: name -> (split_file, split_select, files). Moving, adding or
# dropping a file must edit this table in the same change (item K Defender
# condition), so a merge cannot silently lose a Windows-executed file.
EXPECTED_SHARDS = {
    "status-evidence": (
        "test_status_script.py",
        "invalid_reconciliation_evidence and not origin",
        [
            "tests/operations/test_status_script.py",
            "tests/operations/test_live_wrapper_credential_launcher.py",
            "tests/operations/test_integration_attempt_registration_safety.py",
        ],
    ),
    "status-rest": (
        "test_status_script.py",
        "not invalid_reconciliation_evidence or origin",
        [
            "tests/operations/test_status_script.py",
            "tests/operations/test_replay_cache_compression_wrapper.py",
            "tests/operations/test_cold_archive_reclaim.py",
            "tests/operations/test_ops_script_ratchets.py",
            "tests/collection/test_forecast_payload_cross_process_fanout.py",
            "tests/operations/test_integration_attempt_evidence_recovery_hardening.py",
        ],
    ),
    "archive": (
        "",
        "",
        [
            "tests/operations/test_production_cold_archive_wrapper.py",
            "tests/operations/test_storage_recovery_inventory_wrapper.py",
            "tests/operations/test_integration_attempt_scripts.py",
            "tests/operations/test_windows_job_output_capture.py",
            "tests/operations/test_integration_launch_diagnostics.py",
            "tests/operations/test_ops_alarm_path.py",
            "tests/operations/test_workstation_space_scripts.py",
            "tests/operations/test_cold_snapshot_nightly_verification.py",
            "tests/operations/test_memory_commit_guard_execution.py",
            "tests/operations/test_daily_refresh_wrapper_execution.py",
            "tests/operations/test_guidance_all_hours_admission.py",
            "tests/operations/test_ps_script_root_param_defaults.py",
        ],
    ),
    "launch": (
        "",
        "",
        [
            "tests/operations/test_maker_replay_exam_step_script.py",
            "tests/operations/test_cold_snapshot_compression_wrapper.py",
            "tests/operations/test_integration_phase_output.py",
            "tests/operations/test_health_watchdog_script.py",
            "tests/operations/test_bounded_worktree_test_suite_script.py",
            "tests/operations/test_powershell_host_guard.py",
            "tests/operations/test_quiet_window_merge_execution.py",
            "tests/operations/test_landing_preflight.py",
        ],
    ),
    "windows-lane-a": (
        "",
        "",
        [
            "tests/operations/test_production_baseline_reconciliation.py",
            "tests/operations/test_production_baseline_scheduler_rpc.py",
            "tests/operations/test_monitoring_fixes.py",
            "tests/operations/test_bulk_cold_archive_crypt.py",
            "tests/operations/test_cold_snapshot_nightly.py",
            "tests/operations/test_cold_snapshot_nightly_schedule.py",
            "tests/operations/test_workload_admission_script.py",
            "tests/operations/test_long_job_guard.py",
            "tests/operations/test_replay_cache_compression.py",
            "tests/operations/test_wait_pr_ci_script.py",
            "tests/operations/test_storage_daytime_exception.py",
            "tests/operations/test_cold_snapshot_verification.py",
            "tests/operations/test_live_path_security.py",
            "tests/operations/test_supervisor.py",
            "tests/operations/test_wu_orphan_cleanup.py",
            "tests/operations/test_daily_refresh_script.py",
            "tests/operations/test_cold_snapshot_compression.py",
            "tests/operations/test_memory_commit_guard_script.py",
            "tests/operations/test_storage_inventory_scope.py",
            "tests/operations/test_cold_snapshot_nightly_status_race.py",
        ],
    ),
    "windows-lane-b": (
        "",
        "",
        [
            "tests/operations/test_international_live_session_launcher_sealer.py",
            "tests/operations/test_storage_recovery_night_wrapper.py",
            "tests/operations/test_docs_light_path_script.py",
            "tests/operations/test_international_live_session_runner.py",
            "tests/operations/test_live_runner_console_guards.py",
            "tests/operations/test_international_live_session_runner_stdin.py",
            "tests/operations/test_cold_archive_catalog.py",
            "tests/market/test_wallet_reader_logon_task.py",
            "tests/operations/test_reconcile_ordinary_quiet_merge.py",
            "tests/operations/test_workstation_cold_archive_stage.py",
            "tests/operations/test_producer_provenance.py",
            "tests/operations/test_workload_admission_service_allowlist.py",
            "tests/operations/test_international_live_execution_host_status_script.py",
            "tests/operations/test_production_cold_archive_stage.py",
            "tests/operations/test_training_window_script.py",
            "tests/operations/test_storage_recovery_inventory.py",
            "tests/operations/test_tiering_registration_scripts.py",
            "tests/operations/test_storage_recovery_inventory_cli.py",
            "tests/operations/test_production_cold_archive_stage_cli.py",
            "tests/market/test_mm_credential_import_cli.py",
            "tests/operations/test_codex_host_load_hook_focused_exemption.py",
            "tests/operations/test_workstation_heavy_queue.py",
            "tests/operations/test_thin_ensure.py",
        ],
    ),
    "reconciler-1": (
        "test_production_baseline_reconciler_execution.py",
        "reconciliation_failure",
        [
            "tests/operations/test_production_baseline_reconciler_execution.py",
        ],
    ),
    "reconciler-2": (
        "test_production_baseline_reconciler_execution.py",
        "marker_replacement or special_inputs",
        [
            "tests/operations/test_production_baseline_reconciler_execution.py",
        ],
    ),
    "reconciler-3": (
        "test_production_baseline_reconciler_execution.py",
        "reconciliation_adversarial or with_claimed or normal_helper",
        [
            "tests/operations/test_production_baseline_reconciler_execution.py",
        ],
    ),
    "reconciler-4": (
        "test_production_baseline_reconciler_execution.py",
        "roll_verdict or post_replace or scheduler_read",
        [
            "tests/operations/test_production_baseline_reconciler_execution.py",
        ],
    ),
    "reconciler-5": (
        "test_production_baseline_reconciler_execution.py",
        (
            "reconciliation_success or start_hung or scheduler_helper or "
            "persistent_stop or late_start"
        ),
        [
            "tests/operations/test_production_baseline_reconciler_execution.py",
        ],
    ),
    "reconciler-6": (
        "test_production_baseline_reconciler_execution.py",
        (
            "on_demand or reconciliation_refuses or with_lost or remote_drift "
            "or midflight_quiet"
        ),
        [
            "tests/operations/test_production_baseline_reconciler_execution.py",
        ],
    ),
    "reconciler-7": (
        "test_production_baseline_reconciler_execution.py",
        (
            "not (reconciliation_failure or marker_replacement or "
            "special_inputs or reconciliation_adversarial or with_claimed or "
            "normal_helper or roll_verdict or post_replace or scheduler_read or "
            "reconciliation_success or start_hung or scheduler_helper or "
            "persistent_stop or late_start or on_demand or "
            "reconciliation_refuses or with_lost or remote_drift or "
            "midflight_quiet)"
        ),
        [
            "tests/operations/test_production_baseline_reconciler_execution.py",
        ],
    ),
}
# Test files that skip off Windows but are deliberately in no shard, with the
# reason. Empty: every Windows-only file runs in CI (owner decision 2026-10-04).
# Adding an entry is an owner decision.
WINDOWS_ONLY_OUTSIDE_CI: dict[str, str] = {}

_WINDOWS = {("os.name", "nt"), ("sys.platform", "win32"), ("__import__('os').name", "nt")}
_MATRIX_ENTRY = re.compile(
    r"^\s+- shard: (?P<name>\S+)\n"
    r"\s+split_file: (?P<split_file>.*)\n"
    r"\s+split_select: (?P<split_select>.*)\n"
    r"\s+files: >-\n(?P<files>(?:\s+tests/\S+\.py\n)+)",
    re.MULTILINE,
)


def _shards() -> list[dict]:
    text = WORKFLOW.read_text(encoding="utf-8")

    def value(raw: str) -> str:
        raw = raw.strip()
        return "" if raw == "''" else raw

    shards = [
        {
            "name": match["name"],
            "split_file": value(match["split_file"]),
            "split_select": value(match["split_select"]),
            "files": match["files"].split(),
        }
        for match in _MATRIX_ENTRY.finditer(text)
    ]
    assert len(shards) == text.count("- shard: "), "unparsed matrix entry"
    return shards


def _job_select(shard: dict) -> str:
    # Mirrors the job env: format('({0}) or not {1}', split_select, split_file).
    if not shard["split_select"]:
        return ""
    return f"({shard['split_select']}) or not {shard['split_file']}"


def _collect(files: list[str], select: str) -> set[str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q",
               "-p", "no:cacheprovider", *files]
    if select:
        command += ["-k", select]
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True,
                            text=True, timeout=300, check=False)
    assert result.returncode in (0, 5), result.stdout[-2000:] + result.stderr[-2000:]
    return {line.strip() for line in result.stdout.splitlines() if "::" in line}


def _platform_compare(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return None
    right = node.comparators[0]
    if isinstance(right, ast.Constant) and (ast.unparse(node.left), right.value) in _WINDOWS:
        return type(node.ops[0]).__name__
    return None


def _skips_off_windows(tree: ast.AST) -> bool:
    """`<platform> != windows` anywhere, or `skipUnless(<platform> == windows)`."""
    for node in ast.walk(tree):
        if _platform_compare(node) == "NotEq":
            return True
        if (isinstance(node, ast.Call) and node.args
                and ast.unparse(node.func).endswith("skipUnless")
                and any(_platform_compare(sub) == "Eq" for sub in ast.walk(node.args[0]))):
            return True
    return False


def test_workflow_matrix_matches_the_pinned_shard_plan():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "SHARD_SELECT: ${{ matrix.split_select && format('({0}) or not {1}', "
        "matrix.split_select, matrix.split_file) || '' }}"
    ) in workflow
    assert "if ($env:SHARD_SELECT) { $pytestArgs += @('-k', $env:SHARD_SELECT) }" in workflow
    actual = {s["name"]: (s["split_file"], s["split_select"], s["files"]) for s in _shards()}
    assert actual == EXPECTED_SHARDS


def test_each_file_is_in_exactly_one_shard_except_partitioned_split_files():
    seen: dict[str, str] = {}
    split_owners: dict[str, list[str]] = {}
    for shard in _shards():
        assert shard["files"] and len(shard["files"]) == len(set(shard["files"])), shard["name"]
        assert bool(shard["split_file"]) == bool(shard["split_select"]), shard["name"]
        for file in shard["files"]:
            assert (REPO_ROOT / file).is_file(), file
            if shard["split_file"] and Path(file).name == shard["split_file"]:
                split_owners.setdefault(file, []).append(shard["name"])
                continue
            assert file not in seen, f"{file} is in {seen.get(file)} and {shard['name']}"
            seen[file] = shard["name"]
        if shard["split_file"]:
            assert any(Path(f).name == shard["split_file"] for f in shard["files"]), shard["name"]
    assert not set(split_owners) & set(seen)
    assert split_owners and all(len(owners) >= 2 for owners in split_owners.values())


def test_split_selections_partition_their_file_and_spare_other_files():
    shards = _shards()
    for split_file in sorted({s["split_file"] for s in shards if s["split_file"]}):
        owners = [s for s in shards if s["split_file"] == split_file]
        files = sorted({f for s in owners for f in s["files"]})
        baseline = _collect(files, "")
        path = next(f for f in files if Path(f).name == split_file)
        split_ids = {node for node in baseline if node.startswith(path + "::")}
        assert split_ids, split_file
        selected: set[str] = set()
        for shard in owners:
            chosen = _collect(shard["files"], _job_select(shard))
            for file in shard["files"]:
                if file != path:
                    expected = {node for node in baseline if node.startswith(file + "::")}
                    assert expected and expected <= chosen, f"{shard['name']} filtered {file}"
            mine = {node for node in chosen if node.startswith(path + "::")}
            assert mine, f"{shard['name']} selects nothing from {split_file}"
            assert not mine & selected, f"{shard['name']} overlaps another {split_file} shard"
            selected |= mine
        assert selected == split_ids, f"{split_file} tests in no shard: {sorted(split_ids - selected)}"


def test_every_windows_only_test_file_runs_in_some_ci_shard():
    in_ci = {file for shard in _shards() for file in shard["files"]}
    windows_only = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "tests").rglob("test_*.py"))
        if _skips_off_windows(ast.parse(path.read_text(encoding="utf-8-sig")))
    }
    assert "tests/operations/test_production_baseline_reconciler_execution.py" in windows_only
    missing = sorted(windows_only - in_ci - set(WINDOWS_ONLY_OUTSIDE_CI))
    assert not missing, f"Windows-only test files in no Windows CI shard: {missing}"
    assert not set(WINDOWS_ONLY_OUTSIDE_CI) & in_ci
