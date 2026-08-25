from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = REPO_ROOT / ".github" / "workflows"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
RETRAIN_WORKFLOW_PATH = WORKFLOW_ROOT / "retrain.yml"
CHECKOUT_ACTION = (
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
)
SETUP_PYTHON_ACTION = (
    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"
)
ACTION_SHA_PATTERN = re.compile(r"^[^\s@]+@[0-9a-f]{40}(?:\s+#\s+\S.*)?$")


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _mapping_block(text: str, key: str, indentation: int) -> str:
    lines = text.splitlines()
    marker = f"{' ' * indentation}{key}:"
    try:
        start = lines.index(marker) + 1
    except ValueError as exc:
        raise AssertionError(f"missing workflow mapping: {key}") from exc

    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        current_indentation = len(line) - len(line.lstrip())
        if current_indentation <= indentation:
            end = index
            break
    return "\n".join(lines[start:end])


def _step_block(job: str, name: str) -> str:
    lines = job.splitlines()
    marker = f"      - name: {name}"
    try:
        start = lines.index(marker) + 1
    except ValueError as exc:
        raise AssertionError(f"missing workflow step: {name}") from exc

    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index]
        if line.startswith("      - name: "):
            end = index
            break
    return "\n".join(lines[start:end])


def _folded_command(step: str) -> list[str]:
    lines = step.splitlines()
    assert "        run: >-" in lines
    return [
        line.strip()
        for line in lines[lines.index("        run: >-") + 1 :]
        if line.startswith("          ") and line.strip()
    ]


def test_ci_runs_for_pull_requests_master_and_codex_topic_pushes() -> None:
    trigger = _mapping_block(_workflow_text(), "on", 0)

    assert "  pull_request:" in trigger
    assert (
        "  push:\n"
        "    branches:\n"
        "      - master\n"
        "      - 'codex/**'"
    ) in trigger
    assert "paths:" not in trigger
    assert "paths-ignore:" not in trigger


def test_every_external_workflow_action_is_pinned_to_an_immutable_commit() -> None:
    action_uses: list[tuple[Path, int, str]] = []
    for workflow in sorted(WORKFLOW_ROOT.glob("*.y*ml")):
        for line_number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped.startswith("uses: "):
                continue
            action = stripped.removeprefix("uses: ").strip()
            if action.startswith("./"):
                continue
            action_uses.append((workflow, line_number, action))

    assert action_uses
    mutable = [
        f"{path.relative_to(REPO_ROOT)}:{line_number}: {action}"
        for path, line_number, action in action_uses
        if not ACTION_SHA_PATTERN.fullmatch(action)
    ]
    assert mutable == []


def test_every_workflow_token_is_globally_read_only() -> None:
    invalid: list[str] = []
    for workflow in sorted(WORKFLOW_ROOT.glob("*.y*ml")):
        text = workflow.read_text(encoding="utf-8")
        if text.count("permissions:\n  contents: read") != 1 or re.search(
            r"(?m)^\s+[A-Za-z-]+:\s+write\s*$", text
        ):
            invalid.append(str(workflow.relative_to(REPO_ROOT)))

    assert invalid == []


def test_every_workflow_checkout_is_full_history_and_discards_its_write_credential() -> None:
    checkout_steps: list[tuple[Path, str]] = []
    for workflow in sorted(WORKFLOW_ROOT.glob("*.y*ml")):
        step_lines: list[str] = []
        for line in workflow.read_text(encoding="utf-8").splitlines() + [
            "      - name: __sentinel__"
        ]:
            if line.startswith("      - name: ") and step_lines:
                step = "\n".join(step_lines)
                if "uses: actions/checkout@" in step:
                    checkout_steps.append((workflow, step))
                step_lines = []
            if line.startswith("      "):
                step_lines.append(line)

    assert checkout_steps
    missing = [
        str(path.relative_to(REPO_ROOT))
        for path, step in checkout_steps
        if step.count("persist-credentials: false") != 1
        or step.count("fetch-depth: 0") != 1
        or step.count("lfs: false") != 1
    ]
    assert missing == []


def test_every_python_test_workflow_isolated_uses_module_pip_and_installs_live_sdk() -> None:
    invalid: list[str] = []
    for workflow in sorted(WORKFLOW_ROOT.glob("*.y*ml")):
        text = workflow.read_text(encoding="utf-8")
        if "python -m pytest" not in text:
            continue
        isolated_environment = (
            "PYTHONNOUSERSITE: '1'",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'",
            "PYTHONUTF8: '1'",
        )
        dependency_installs = text.count("python -m pip install -r requirements.txt")
        live_installs = text.count('python -m pip install -e ".[test,live]"')
        if (
            any(text.count(value) != 1 for value in isolated_environment)
            or dependency_installs < 1
            or live_installs != dependency_installs
        ):
            invalid.append(str(workflow.relative_to(REPO_ROOT)))
        if re.search(r"(?m)^\s+pip install\s", text):
            invalid.append(str(workflow.relative_to(REPO_ROOT)))
        if text.count("WEATHER_INTEGRATION_TEST_OFFLINE: '1'") != text.count(
            "python -m pytest"
        ):
            invalid.append(str(workflow.relative_to(REPO_ROOT)))
        for step in re.split(r"(?m)^\s{6}- name: ", text)[1:]:
            if "python -m pytest" in step:
                assert "WEATHER_INTEGRATION_TEST_OFFLINE: '1'" in step
                assert "GIT_ALLOW_PROTOCOL: file" in step
                assert "GIT_TERMINAL_PROMPT: '0'" in step
            else:
                assert "WEATHER_INTEGRATION_TEST_OFFLINE: '1'" not in step
                assert "GIT_ALLOW_PROTOCOL: file" not in step

    assert invalid == []


def test_candidate_build_remains_manual_only() -> None:
    text = RETRAIN_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "  workflow_dispatch:" in text
    assert not re.search(r"(?m)^\s+schedule:\s*$", text)


def test_ci_jobs_are_full_history_bounded_and_named_non_production() -> None:
    workflow = _workflow_text()
    jobs = {
        "linux-cross-platform": (30, "ubuntu-latest"),
        "windows-full": (60, "windows-latest"),
    }
    jobs_block = _mapping_block(workflow, "jobs", 0)
    actual_jobs = [
        line.strip().removesuffix(":")
        for line in jobs_block.splitlines()
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":")
    ]

    assert actual_jobs == list(jobs)

    for job_name, (timeout, runner) in jobs.items():
        job = _mapping_block(workflow, job_name, 2)
        checkout = _step_block(job, "Checkout Repository")
        setup_python = _step_block(job, "Set up Python")
        display_name = job.splitlines()[0]

        assert display_name.startswith("    name: ")
        assert display_name.endswith(" (non-production)")
        assert f"    runs-on: {runner}" in job
        assert f"    timeout-minutes: {timeout}" in job
        assert job.count("uses: actions/checkout") == 1
        assert checkout.count(f"uses: {CHECKOUT_ACTION}") == 1
        assert checkout.count("fetch-depth: 0") == 1
        assert checkout.count("persist-credentials: false") == 1
        assert job.count("uses: actions/setup-python") == 1
        assert setup_python.count(f"uses: {SETUP_PYTHON_ACTION}") == 1


def test_linux_ci_uses_the_reviewed_cross_platform_inventory() -> None:
    workflow = _workflow_text()
    linux = _mapping_block(workflow, "linux-cross-platform", 2)
    step = _step_block(linux, "Run Explicit Cross-Platform Test Inventory")
    expected_command = [
        "python -m pytest -q",
        "tests/app",
        "tests/backtesting",
        "tests/calibration",
        "tests/collection",
        "tests/market",
        "tests/model",
        "tests/reporting",
        "tests/sources",
        "tests/test_artifacts.py",
        "tests/test_io_streaming.py",
        "tests/test_release_serving.py",
        "tests/operations/test_agent_docs_audit.py",
        "tests/operations/test_ci_workflow_contract.py",
        "tests/operations/test_dependency_pins.py",
        "tests/operations/test_import_architecture.py",
        "tests/operations/test_module_size_audit.py",
        "tests/operations/test_offline_test_boundary.py",
        "tests/operations/test_quiet_window_merge_script.py",
        "tests/operations/test_schema_registry.py",
    ]

    assert _folded_command(step) == expected_command
    assert linux.count("python -m pytest") == 1
    for path in expected_command[1:]:
        assert (REPO_ROOT / path).exists(), path


def test_windows_ci_runs_the_complete_test_inventory_without_exclusions() -> None:
    workflow = _workflow_text()
    windows = _mapping_block(workflow, "windows-full", 2)
    step = _step_block(windows, "Run Complete Windows Test Inventory")
    commands = [line.strip() for line in step.splitlines() if line.strip()]

    assert commands == ["run: python -m pytest -q"]
    assert windows.count("python -m pytest") == 1
    assert "--ignore" not in windows
    assert "--deselect" not in windows
    assert "-k " not in windows
