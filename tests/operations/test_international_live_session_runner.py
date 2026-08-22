from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.operations import international_live_session_runner as runner
from weather.operations import international_live_wrapper_sealer as sealer


NOW = datetime.fromisoformat("2026-08-23T01:00:00-04:00")
CONDITION = "0x" + "7" * 64
TOKEN = "7001"


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
    if stage != "stage0":
        for relative in (
            "stage0/bootstrap.json",
            "stage0/command-receipt.json",
            "seal/stage0-seal-receipt.json",
            "stage0/wrapper-execution-receipt.json",
        ):
            write(attempt / relative, {"status": "PASS"})
    payload = {
        "schema_version": runner.SESSION_SCHEMA_VERSION,
        "manifest_sha256": None,
        "stage": stage,
        "production": {
            "root": str(tmp_path / "production"),
            "branch": "master",
            "commit": "a" * 64,
            "tree": "b" * 64,
            "python": str(tmp_path / "production/venv/Scripts/python.exe"),
        },
        "scope": {
            "target_date": NOW.date().isoformat(),
            "condition_id": CONDITION,
            "token_id": TOKEN,
            "requested_budget_pusd": 10,
            "attempt_root": str(attempt.resolve()),
            "lease_workload": f"session-{stage}",
            "max_session_seconds": 90,
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
        "source_sha256": {"source": "e" * 64},
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
    def seal(_spec_path, **_kwargs):
        wrapper = attempt / sealer.OUTPUT_LAYOUTS[stage]["python_wrapper"]
        launcher = attempt / sealer.OUTPUT_LAYOUTS[stage]["launcher"]
        launcher.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text("# sealed wrapper\n", encoding="utf-8")
        launcher.write_text("# sealed launcher\n", encoding="utf-8")
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
    write(
        path,
        {
            "schema_version": "international_live_fixed_scope_execution_v0.2",
            "status": status,
            "stage": stage,
            "phase": "complete" if status == "PASS" else "stage1_command",
            "wrapper": wrapper_override
            or {"path": str(wrapper.resolve()), "sha256": sha(wrapper)},
            "artifacts": {},
            "live_mutation_attempted": mutation,
            "credential_values_read_in_memory": credential,
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
            now=NOW,
            seal_function=fake_sealer(attempt, "stage1_cancel_all"),
            before_launch=lambda: destination.write_text("tampered", encoding="utf-8"),
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )


def test_composer_parser_has_no_scope_or_budget_overrides():
    parser = runner.build_parser()
    destinations = {action.dest for action in parser._actions}
    assert destinations == {"help", "session_manifest", "candidate"}
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


def test_runner_rejects_rewritten_manifest_even_with_new_self_hash(tmp_path):
    _attempt, manifest, fresh = session_fixture(tmp_path, "stage0")
    payload = json.loads(manifest.read_text())
    payload["scope"]["requested_budget_pusd"] = 11
    payload["manifest_sha256"] = runner._canonical_payload_sha256(payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(runner.SessionCompositionError, match="sidecar"):
        runner.compose_and_run_live_session(
            manifest,
            fresh,
            now=NOW,
            launcher_runner=lambda _path: pytest.fail("launcher must not run"),
        )
