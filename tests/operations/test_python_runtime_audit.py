from weather.operations import daily_refresh_steps
from weather.operations import python_runtime_audit as audit
from weather.paths import REPO_ROOT


def _ruff_finding(path, code, message, row=1):
    return {
        "filename": str(REPO_ROOT / path),
        "code": code,
        "message": message,
        "location": {"row": row, "column": 1},
        "end_location": {"row": row, "column": 1},
    }


def test_ruff_baseline_allows_injected_cli_globals_but_blocks_new_undefined_name():
    injected = _ruff_finding(
        "src/weather/operations/daily_refresh_cli.py",
        "F821",
        "Undefined name `DEFAULT_STATUS_OUT`",
    )
    new_runtime_hazard = _ruff_finding(
        "src/weather/operations/daily_refresh_steps.py",
        "F821",
        "Undefined name `utc_now`",
    )

    allowed = audit.classify_ruff_findings([injected])
    blocked = audit.classify_ruff_findings([injected, new_runtime_hazard])

    assert allowed["status"] == "PASS"
    assert allowed["baselined_count"] == 1
    assert blocked["status"] == "BLOCK"
    assert blocked["unowned_findings"][0]["path"] == "src/weather/operations/daily_refresh_steps.py"
    assert blocked["unowned_findings"][0]["symbol"] == "utc_now"


def test_ruff_baseline_does_not_allow_deleted_f811_redefinitions():
    payload = audit.load_baseline()

    assert not any(
        row.get("code") == "F811"
        for row in payload.get("ruff_baseline") or []
    )


def test_daily_refresh_step_smoke_catches_missing_required_helper():
    globals_map = daily_refresh_steps.run_reanalysis_recent_refresh_step.__globals__
    original = globals_map.pop("utc_now")
    try:
        payload = audit.daily_refresh_step_smoke()
    finally:
        globals_map["utc_now"] = original

    assert payload["status"] == "BLOCK"
    assert payload["blockers"][0]["step"] == "reanalysis_recent_refresh"
    assert payload["blockers"][0]["missing_globals"] == ["utc_now"]


def test_log_signature_audit_routes_known_streamlit_pd_traceback(tmp_path):
    log_path = tmp_path / "streamlit_stderr.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-06-25 09:00:00.000 Uncaught app execution",
                "Traceback (most recent call last):",
                '  File "C:\\repo\\app\\views\\single_market.py", line 682, in live_dashboard',
                "    pd.to_datetime([])",
                "UnboundLocalError: cannot access local variable 'pd' where it is not associated with a value",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = audit.log_signature_audit(
        log_sources={"streamlit": log_path},
        incidents_path=tmp_path / "incidents.jsonl",
        as_of="2026-06-25T14:00:00+00:00",
    )

    assert payload["status"] == "PASS"
    assert payload["current_signature_count"] == 2
    assert payload["routed_signature_count"] == 2
    assert payload["unowned_signature_count"] == 0


def test_log_signature_audit_blocks_unowned_current_traceback(tmp_path):
    log_path = tmp_path / "daily_refresh.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-06-25T14:00:00+00:00 step failed",
                "Traceback (most recent call last):",
                '  File "C:\\repo\\src\\weather\\operations\\daily_refresh_steps.py", line 1, in run',
                "    missing_helper()",
                "NameError: name 'missing_helper' is not defined",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = audit.log_signature_audit(
        log_sources={"daily_refresh": log_path},
        incidents_path=tmp_path / "incidents.jsonl",
        as_of="2026-06-25T14:10:00+00:00",
    )

    assert payload["status"] == "BLOCK"
    assert payload["unowned_signature_count"] == 2
    assert any("NameError" in row["normalized_message"] for row in payload["unowned_signatures"])


def test_streamlit_two_page_route_smoke_has_no_runtime_exception():
    payload = audit.streamlit_route_smoke()

    assert payload["status"] == "PASS"
    assert payload["routes"] == ["control", "roadmap"]
    assert payload["exception_count"] == 0


def test_python_runtime_audit_payload_can_pass_with_injected_components(tmp_path, monkeypatch):
    monkeypatch.setattr(
        audit,
        "run_ruff_audit",
        lambda **_kwargs: {"status": "PASS", "finding_count": 0, "unowned_count": 0},
    )
    monkeypatch.setattr(
        audit,
        "daily_refresh_step_smoke",
        lambda: {"status": "PASS", "blocker_count": 0},
    )
    monkeypatch.setattr(
        audit,
        "streamlit_route_smoke",
        lambda: {"status": "PASS", "exception_count": 0},
    )
    monkeypatch.setattr(
        audit,
        "log_signature_audit",
        lambda **_kwargs: {"status": "PASS", "unowned_signature_count": 0},
    )

    payload = audit.build_payload(log_incidents_path=tmp_path / "incidents.jsonl")

    assert payload["schema_version"] == "python_runtime_audit_v0.1"
    assert payload["status"] == "PASS"
    assert payload["summary"]["blocker_count"] == 0
