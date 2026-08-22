from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.operations import international_live_session_runner as runner
from weather.operations import international_live_wrapper_sealer as sealer


NOW = datetime.fromisoformat("2026-08-23T01:00:00-04:00")
CONDITION = "0x" + "7" * 64
TOKEN = "7001"


@pytest.fixture(autouse=True)
def private_attempt_root(monkeypatch):
    monkeypatch.setattr(
        runner,
        "validate_private_attempt_root",
        lambda path: {"status": "PASS", "path": str(path)},
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict):
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(str(payload), encoding="utf-8")
    return path


def candidate(now=NOW, *, remaining_seconds=120):
    current = now.astimezone(timezone.utc)
    paper_generated = current
    created = current
    expires = current + timedelta(seconds=remaining_seconds)
    payload = {
        "schema_version": sealer.CANDIDATE_SCHEMA_VERSION,
        "status": "PASS",
        "created_at_utc": created.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "target_date": now.date().isoformat(),
        "selection_is_trading_authorization": False,
        "selection_policy": {
            "expected_bootstrap_scope": {
                "condition_id": CONDITION,
                "token_id": TOKEN,
            }
        },
        "selected": {
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "tick_size": 0.01,
            "order_min_size": 5,
            "stage1_intent": {
                "side": "BUY",
                "price": 0.01,
                "size": 5,
                "notional_pusd": 0.05,
                "post_only": True,
            },
            "paper_quote_proof": {
                "condition_id": CONDITION,
                "token_id": TOKEN,
                "generated_at_utc": paper_generated.isoformat(),
                "expires_at_utc": expires.isoformat(),
                "quote_ttl_seconds": remaining_seconds,
                "quote_permission": True,
                "live_trade_permission": False,
            },
        },
    }
    payload["plan_sha256"] = sealer._canonical_payload_sha256(
        payload, omit="plan_sha256"
    )
    return payload


def session_fixture(tmp_path: Path, stage: str, *, remaining_seconds=120):
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    identity = write(
        attempt / sealer.INPUT_LAYOUTS[stage]["identity"],
        {"schema_version": "mm_stage0_client_identity_v0.2"},
    )
    credential = write(tmp_path / "credential.json", {"status": "PASS"})
    references = write(tmp_path / "references.json", {"status": "PASS"})
    reviewed_source = write(tmp_path / "production/source", {"reviewed": True})
    if stage != "stage0":
        lineage_paths = [
            "stage0/bootstrap.json",
            "stage0/command-receipt.json",
            "seal/stage0-seal-receipt.json",
            "session/stage0-run-receipt.json",
            "session/stage0-run-receipt.json.sha256",
            "stage0/wrapper-execution-receipt.json",
        ]
        if stage == "stage1_dead_man":
            lineage_paths.extend(
                [
                    "seal/stage1-cancel-all-seal-receipt.json",
                    "session/stage1_cancel_all-run-receipt.json",
                    "session/stage1_cancel_all-run-receipt.json.sha256",
                    "stage1-cancel-all/wrapper-execution-receipt.json",
                    "stage1-cancel-all/command-receipt.json",
                    "stage1-cancel-all/result.json",
                    "stage1-cancel-all/lifecycle.jsonl",
                ]
            )
        for relative in lineage_paths:
            write(attempt / relative, {"status": "PASS"})
    payload = {
        "schema_version": runner.SESSION_SCHEMA_VERSION,
        "manifest_sha256": None,
        "stage": stage,
        "production": {
            "root": str(tmp_path / "production"),
            "branch": "master",
            "commit": "a" * 40,
            "tree": "b" * 40,
            "python": str(tmp_path / "production/venv/Scripts/python.exe"),
        },
        "scope": {
            "target_date": NOW.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "attempt_root": str(attempt.resolve()),
            "lease_workload": f"session-{stage}",
            "max_session_seconds": 120,
        },
        "inputs": {
            "identity": {"path": str(identity.resolve()), "sha256": sha(identity)},
            "credential_import_receipt": {
                "path": str(credential.resolve()),
                "sha256": sha(credential),
            },
            "credential_reference_manifest": {
                "path": str(references.resolve()),
                "sha256": sha(references),
            },
        },
        "reviewed_status_flags": [],
        "template_sha256": {"python": "c" * 64, "launcher": "d" * 64},
        "source_sha256": {"source": sha(reviewed_source)},
    }
    payload["manifest_sha256"] = runner._canonical_payload_sha256(payload)
    manifest = write(
        attempt / "inputs" / f"{stage}-session-manifest.json",
        payload,
    )
    manifest.with_suffix(manifest.suffix + ".sha256").write_text(
        f"{sha(manifest)}  {manifest.name}\n",
        encoding="ascii",
    )
    source_candidate = write(
        tmp_path / f"fresh-{stage}.json",
        candidate(remaining_seconds=remaining_seconds),
    )
    return attempt, manifest, source_candidate


def fake_sealer(attempt: Path, stage: str):
    def seal(spec_path, **_kwargs):
        spec_path = Path(spec_path).resolve()
        spec = json.loads(spec_path.read_text())
        wrapper = attempt / sealer.OUTPUT_LAYOUTS[stage]["python_wrapper"]
        launcher = attempt / sealer.OUTPUT_LAYOUTS[stage]["launcher"]
        launcher.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text("# sealed wrapper\n", encoding="utf-8")
        launcher.write_text("# sealed launcher\n", encoding="utf-8")
        seal_path = attempt / sealer.OUTPUT_LAYOUTS[stage]["seal_receipt"]
        seal_payload = {
            "schema_version": sealer.RECEIPT_SCHEMA_VERSION,
            "status": "PASS",
            "stage": stage,
            "production": spec["production"],
            "scope": {
                **spec["scope"],
                "cancellation_mode": (
                    "not_applicable"
                    if stage == "stage0"
                    else ("cancel_all" if stage == "stage1_cancel_all" else "dead_man")
                ),
                "reviewed_status_flags": spec["reviewed_status_flags"],
            },
            "wrapper": {"path": str(wrapper.resolve()), "sha256": sha(wrapper)},
            "launcher": {"path": str(launcher.resolve()), "sha256": sha(launcher)},
            "seal_spec": {"path": str(spec_path), "sha256": sha(spec_path)},
            "inputs": spec["inputs"],
        }
        write(seal_path, seal_payload)
        return {
            "status": "PASS",
            "stage": stage,
            "wrapper": {
                "path": str(wrapper.resolve()),
                "sha256": sha(wrapper),
            },
            "launcher": {
                "path": str(launcher.resolve()),
                "sha256": sha(launcher),
            },
            "seal_receipt": {
                "path": str(seal_path.resolve()),
                "sha256": sha(seal_path),
            },
        }

    return seal


def write_execution(
    attempt: Path,
    stage: str,
    *,
    status="PASS",
    mutation=False,
    credential=True,
    wrapper_override=None,
):
    wrapper = attempt / sealer.OUTPUT_LAYOUTS[stage]["python_wrapper"]
    path = attempt / sealer.OUTPUT_LAYOUTS[stage]["wrapper_execution_receipt"]
    layout = sealer.OUTPUT_LAYOUTS[stage]
    doctor = write(attempt / layout["doctor_receipt"], {"status": "PASS"})
    stream = attempt / layout["user_stream_journal"]
    stream.parent.mkdir(parents=True, exist_ok=True)
    stream.write_text('{"event_type":"stream_stopped"}\n', encoding="utf-8")
    command_path = attempt / layout["command_receipt"]
    artifacts = {
        "doctor_receipt_out": {"path": str(doctor.resolve()), "sha256": sha(doctor)},
        "user_stream_journal_out": {
            "path": str(stream.resolve()),
            "sha256": sha(stream),
        },
    }
    command_paths = {
        "receipt": str(command_path.resolve()),
        "user_stream_journal": str(stream.resolve()),
    }
    if stage == "stage0":
        bootstrap = write(attempt / layout["bootstrap"], {"status": "PASS"})
        artifacts["bootstrap_out"] = {
            "path": str(bootstrap.resolve()),
            "sha256": sha(bootstrap),
        }
        command_paths["bootstrap"] = str(bootstrap.resolve())
    else:
        candidate_path = attempt / sealer.INPUT_LAYOUTS[stage]["candidate_plan"]
        candidate_payload = json.loads(candidate_path.read_text())
        journal = attempt / layout["lifecycle_journal"]
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text('{"event_type":"probe_passed"}\n', encoding="utf-8")
        mode = "cancel_all" if stage == "stage1_cancel_all" else "dead_man"
        result = write(
            attempt / layout["result"],
            {
                "schema_version": "mm_live_lifecycle_probe_v0.2",
                "status": "PASS",
                "platform": "polymarket_global",
                "settlement_unit": "pUSD",
                "cancellation_mode": mode,
                "condition_id": CONDITION,
                "token_id": TOKEN,
                "candidate_plan_sha256": sha(candidate_path),
                "candidate_semantic_plan_sha256": candidate_payload["plan_sha256"],
                "bootstrap_schema_version": "mm_platform_bootstrap_v0.3",
                "bootstrap_sha256": sha(attempt / "stage0/bootstrap.json"),
                "heartbeat_acknowledged": True,
                "starting_zero_open_orders_verified": True,
                "starting_zero_positions_verified": True,
                "intent": {
                    "token_id": TOKEN,
                    "side": "BUY",
                    "price": 0.01,
                    "size": 5.0,
                },
                "order_notional_usdc": 0.05,
                "order_id": f"{mode}-order",
                "placement_status": "live",
                "open_order_observed": True,
                "authoritative_user_event_observed": True,
                "cancellation_observed": True,
                "zero_open_orders_verified": True,
                "zero_positions_verified": True,
                "no_trade_lifecycle_event_observed": True,
                "terminal_user_event_observed": True,
                "secret_values_redacted": True,
                "cancel_response_present": mode == "cancel_all",
                "cancellation_elapsed_seconds": 0 if mode == "cancel_all" else 12,
                "journal_path": str(journal.resolve()),
                "journal_sha256": sha(journal),
            },
        )
        artifacts.update(
            {
                "result_out": {"path": str(result.resolve()), "sha256": sha(result)},
                "lifecycle_journal_out": {
                    "path": str(journal.resolve()),
                    "sha256": sha(journal),
                },
            }
        )
        command_paths.update(
            {
                "result": str(result.resolve()),
                "lifecycle_journal": str(journal.resolve()),
            }
        )
    command = {
        "schema_version": "mm_live_pilot_command_receipt_v0.1",
        "status": "PASS",
        "command": "stage0" if stage == "stage0" else "stage1",
        "target_date": NOW.date().isoformat(),
        "condition_id": CONDITION,
        "token_id": TOKEN,
        "requested_budget_pusd": 10,
        "cleanup": {"ok": True},
        "credential_values_read_in_memory": True,
        "exception_type": None,
        "paths": command_paths,
    }
    if stage == "stage0":
        command["exchange_mutation_attempted"] = False
    else:
        command["cancellation_mode"] = mode
        command["exchange_mutation_attempted"] = True
    write(command_path, command)
    artifacts["command_receipt_out"] = {
        "path": str(command_path.resolve()),
        "sha256": sha(command_path),
    }
    host_attestations = [
        {
            "checked_at_local": NOW.isoformat(),
            "status_json_sha256": "9" * 64,
            "status_flag_sha256": [],
        }
        for _index in range(2 if stage == "stage0" else 3)
    ]
    write(
        path,
        {
            "schema_version": "international_live_fixed_scope_execution_v0.3",
            "status": status,
            "stage": stage,
            "phase": "complete" if status == "PASS" else "stage1_command",
            "production_tip": "a" * 40,
            "target_date": NOW.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "cancellation_mode": (
                None
                if stage == "stage0"
                else ("cancel_all" if stage == "stage1_cancel_all" else "dead_man")
            ),
            "wrapper": wrapper_override
            or {"path": str(wrapper.resolve()), "sha256": sha(wrapper)},
            "artifacts": artifacts,
            "live_mutation_attempted": mutation,
            "credential_values_read_in_memory": credential,
            "confirmation_scope_display_sha256": "8" * 64,
            "host_attestations": host_attestations,
            "exception_type": None if status == "PASS" else "RuntimeError",
        },
    )


@pytest.mark.parametrize("stage", sealer.STAGES)
def test_composer_accepts_only_manifest_and_fresh_candidate_for_each_stage(
    tmp_path, stage
):
    attempt, manifest, fresh = session_fixture(tmp_path, stage)
    launched = []

    result = runner.compose_and_run_live_session(
        manifest,
        fresh,
        expected_session_manifest_sha256=sha(manifest),
        now=NOW,
        seal_function=fake_sealer(attempt, stage),
        launcher_runner=lambda path: (
            launched.append(path)
            or write_execution(attempt, stage, mutation=stage != "stage0")
            or subprocess.CompletedProcess([str(path)], 0, "", "")
        ),
    )

    assert result["status"] == "PASS"
    assert result["stage"] == stage
    assert len(launched) == 1
    assert (attempt / "session" / f"{stage}-composition-receipt.json").is_file()
    assert (attempt / "session" / f"{stage}-run-receipt.json").is_file()


def test_composer_refuses_candidate_without_launch_reserve(tmp_path):
    attempt, manifest, fresh = session_fixture(
        tmp_path, "stage0", remaining_seconds=20
    )

    with pytest.raises(runner.SessionCompositionError, match="too little"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, "stage0"),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_composer_rechecks_candidate_after_seal_before_launch(tmp_path):
    attempt, manifest, fresh = session_fixture(tmp_path, "stage1_cancel_all")
    destination = attempt / sealer.INPUT_LAYOUTS["stage1_cancel_all"]["candidate_plan"]

    with pytest.raises(runner.SessionCompositionError, match="changed before launch"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, "stage1_cancel_all"),
            before_launch=lambda: destination.write_text("tampered", encoding="utf-8"),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_composer_uses_effective_cutoff_after_one_second_composition(tmp_path):
    stage = "stage0"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    result = runner.compose_and_run_live_session(
        manifest,
        fresh,
        expected_session_manifest_sha256=sha(manifest),
        now=NOW,
        clock=lambda: NOW + timedelta(seconds=1),
        seal_function=fake_sealer(attempt, stage),
        launcher_runner=lambda path: (
            write_execution(attempt, stage, mutation=False)
            or subprocess.CompletedProcess([str(path)], 0, "", "")
        ),
    )

    assert result["effective_deadline_remaining_seconds_before_launch"] == 119


def test_composer_refuses_after_composition_consumes_launch_reserve(tmp_path):
    stage = "stage0"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    with pytest.raises(runner.SessionCompositionError, match="pre-submit launch reserve"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            clock=lambda: NOW + timedelta(seconds=31),
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_composer_parser_has_no_scope_or_budget_overrides():
    parser = runner.build_parser()
    destinations = {action.dest for action in parser._actions}
    assert destinations == {
        "help",
        "session_manifest",
        "candidate",
        "expected_session_manifest_sha256",
    }
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "AssignProcessToJobObject" in source
    assert "KILL_ON_JOB_CLOSE" in source
    assert "CREATE_SUSPENDED" in source


@pytest.mark.parametrize("mutation", [False, True])
def test_runner_propagates_nonzero_child_pre_or_post_submit_facts(
    tmp_path, mutation
):
    stage = "stage1_cancel_all"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    def launch(path):
        write_execution(
            attempt,
            stage,
            status="FAIL",
            mutation=mutation,
            credential=True,
        )
        return subprocess.CompletedProcess([str(path)], 1, "", "")

    with pytest.raises(runner.SessionCompositionError, match="validated PASS"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=launch,
        )

    receipt = json.loads(
        (attempt / "session/stage1_cancel_all-run-receipt.json").read_text()
    )
    assert receipt["status"] == "FAIL"
    assert receipt["live_mutation_attempted"] is mutation
    assert receipt["credential_values_read_in_memory"] is True


@pytest.mark.parametrize("tampered", [False, True])
def test_runner_marks_missing_or_tampered_execution_receipt_unknown(
    tmp_path, tampered
):
    stage = "stage0"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    def launch(path):
        if tampered:
            write_execution(
                attempt,
                stage,
                wrapper_override={"path": "wrong", "sha256": "0" * 64},
            )
        return subprocess.CompletedProcess([str(path)], 0, "", "")

    with pytest.raises(runner.SessionCompositionError, match="validated PASS"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=launch,
        )

    receipt = json.loads(
        (attempt / "session/stage0-run-receipt.json").read_text()
    )
    assert receipt["status"] == "UNKNOWN"
    assert receipt["live_mutation_attempted"] == "UNKNOWN"
    assert receipt["child_execution"]["validation"] in {"UNKNOWN", "FAIL"}


def test_runner_emits_terminal_unknown_on_keyboard_interrupt(tmp_path):
    stage = "stage1_dead_man"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    with pytest.raises(KeyboardInterrupt):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=lambda _path: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    receipt = json.loads(
        (attempt / "session/stage1_dead_man-run-receipt.json").read_text()
    )
    assert receipt["status"] == "INTERRUPTED"
    assert receipt["launcher_exception_type"] == "KeyboardInterrupt"
    assert receipt["live_mutation_attempted"] == "UNKNOWN"


@pytest.mark.parametrize(
    "tamper",
    ["missing_artifact", "phase", "credential", "mutation", "scope"],
)
def test_runner_rejects_under_validated_pass_execution_receipt(tmp_path, tamper):
    stage = "stage1_cancel_all"
    attempt, manifest, fresh = session_fixture(tmp_path, stage)

    def launch(path):
        write_execution(attempt, stage, status="PASS", mutation=True, credential=True)
        execution_path = attempt / sealer.OUTPUT_LAYOUTS[stage][
            "wrapper_execution_receipt"
        ]
        payload = json.loads(execution_path.read_text())
        if tamper == "missing_artifact":
            del payload["artifacts"]["user_stream_journal_out"]
        elif tamper == "phase":
            payload["phase"] = "stage1_command"
        elif tamper == "credential":
            payload["credential_values_read_in_memory"] = "UNKNOWN"
        elif tamper == "mutation":
            payload["live_mutation_attempted"] = False
        else:
            payload["production_tip"] = "b" * 40
        execution_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess([str(path)], 0, "", "")

    with pytest.raises(runner.SessionCompositionError, match="validated PASS"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, stage),
            launcher_runner=launch,
        )

    receipt = json.loads(
        (attempt / "session/stage1_cancel_all-run-receipt.json").read_text()
    )
    assert receipt["status"] == "UNKNOWN"
    assert receipt["child_execution"]["validation"] == "FAIL"


def test_runner_rejects_rewritten_manifest_even_with_new_self_hash(tmp_path):
    _attempt, manifest, fresh = session_fixture(tmp_path, "stage0")
    reviewed_sha256 = sha(manifest)
    payload = json.loads(manifest.read_text())
    payload["scope"]["requested_budget_pusd"] = 11
    payload["manifest_sha256"] = runner._canonical_payload_sha256(payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(runner.SessionCompositionError, match="reviewed session manifest"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=reviewed_sha256,
            now=NOW,
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_runner_atomically_claims_terminal_namespace_before_launch(tmp_path):
    attempt, manifest, fresh = session_fixture(tmp_path, "stage0")
    terminal = attempt / "session/stage0-run-receipt.json"

    with pytest.raises(runner.SessionCompositionError, match="namespace is already spent"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            expected_session_manifest_sha256=sha(manifest),
            now=NOW,
            seal_function=fake_sealer(attempt, "stage0"),
            before_launch=lambda: terminal.write_text("raced", encoding="utf-8"),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )

    assert terminal.read_text(encoding="utf-8") == "raced"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_default_launcher_runner_executes_safe_child_inside_job(tmp_path):
    script = tmp_path / "safe-exit.ps1"
    script.write_text("exit 0\n", encoding="utf-8")

    result = runner._default_launcher_runner(script)

    assert result.returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_default_runner_allows_cooperative_ctrl_break_cleanup(tmp_path):
    script = tmp_path / "cooperative.ps1"
    script.write_text(
        "Start-Sleep -Milliseconds 1500\nexit 3\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    absolute_deadline = datetime.now().astimezone() + timedelta(seconds=1)
    with pytest.raises(runner.LauncherControlError) as caught:
        runner._default_launcher_runner(
            script,
            timeout_seconds=5,
            absolute_deadline=absolute_deadline,
            cleanup_grace_seconds=3,
        )

    assert caught.value.cooperative is True
    assert caught.value.forced is False
    assert time.monotonic() - started < 4


@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_default_runner_forces_unresponsive_contained_tree(tmp_path):
    code = (
        "import signal,time;"
        "signal.signal(signal.SIGBREAK,signal.SIG_IGN);"
        "time.sleep(30)"
    )
    script = tmp_path / "unresponsive.ps1"
    script.write_text(
        f"& '{sys.executable}' -c \"{code}\"\nexit $LASTEXITCODE\n",
        encoding="utf-8",
    )

    with pytest.raises(runner.LauncherControlError) as caught:
        runner._default_launcher_runner(
            script,
            timeout_seconds=1,
            cleanup_grace_seconds=1,
        )

    assert caught.value.cooperative is False
    assert caught.value.forced is True


@pytest.mark.skipif(os.name != "nt", reason="Windows share-mode locking is Windows-only")
def test_default_runner_denies_write_delete_race_for_sealed_artifact(tmp_path):
    script = tmp_path / "bounded.ps1"
    script.write_text("Start-Sleep -Seconds 2\nexit 0\n", encoding="utf-8")
    protected = tmp_path / "sealed-wrapper.py"
    protected.write_text("# sealed\n", encoding="utf-8")
    outcome = {}

    def run():
        outcome["result"] = runner._default_launcher_runner(
            script,
            protected_files={protected: sha(protected)},
            timeout_seconds=5,
        )

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.5)
    with pytest.raises(PermissionError):
        protected.write_text("tampered", encoding="utf-8")
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert outcome["result"].returncode == 0
    assert protected.read_text() == "# sealed\n"
