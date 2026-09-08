"""Cold recovery entrypoints remain subject to the host-load launch guard."""
from datetime import datetime
import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("cold_recovery_host_guard", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


@pytest.mark.parametrize("module", [
    "weather.operations.cold_snapshot_compression",
    "weather.operations.storage_recovery_inventory_cli",
])
@pytest.mark.parametrize("switch", ["-m ", "-Bm", "-BIm "])
def test_direct_cold_recovery_launch_is_denied_in_protected_window(module, switch):
    result = HOOK.evaluate(
        {"tool_name": "Bash", "tool_input": {"command": f"python {switch}{module} --request example.json"}},
        now=datetime(2026, 9, 9, 14, tzinfo=ZoneInfo("America/Toronto")),
        constrained_capture_host=True,
    )
    assert result is not None
    assert "00:30-09:00" in result["hookSpecificOutput"]["permissionDecisionReason"]


def test_current_docs_audit():
    from weather.operations.agent_docs_audit import audit_repo
    assert audit_repo(ROOT) == []
