"""PL-4/PL-5/PL-6 evidence host: pause rules, supervision, code identity and isolation from capture.

Guards: docs/operations/EVIDENCE_HOST.md (DLv2 plan S4 verify row "optional channels pause in
09:30-11:55"; PL-6 supervision: cap kill receipts and per-day disable, crash backoff, explicit restart
adoption (owner Q11), host stop file, parent cap; PL-4 running-vs-disk code identity; the evidence
package stays outside every capture loop's static import closure and imports no order or signing
client).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, time, timezone
from pathlib import Path

import pytest

from weather.evidence import host as host_module
from weather.evidence.child import Channel, ChildRunner, in_window, pause_reason
from weather.evidence.code_identity import capture_identity, disk_drift, identity_manifest
from weather.evidence.config import load_config, load_locations
from weather.evidence.journal import iter_segment_rows, segment_dirs

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG, CONFIG_SHA = load_config()
OPTIONAL_WINDOWS = CONFIG["host"]["optional_pause_local"]
GIB = 1024**3


def _pause(channel, hhmm, *, available=64 * GIB, band="green"):
    hour, minute = map(int, hhmm.split(":"))
    return pause_reason(channel, now_local=time(hour, minute), optional_windows=OPTIONAL_WINDOWS,
                        available_bytes=available, required_available_bytes=6 * GIB, disk_band_name=band)


@pytest.mark.parametrize(("hhmm", "optional", "expected"), [
    ("09:29", True, None), ("09:30", True, "optional_pause_window"), ("11:54", True, "optional_pause_window"),
    ("11:55", True, None), ("10:00", False, None),
])
def test_optional_channels_pause_in_the_stage_a_window(hhmm, optional, expected):
    assert OPTIONAL_WINDOWS == [["09:30", "11:55"]]
    assert _pause(Channel("c", 60, None, optional=optional), hhmm) == expected


def test_memory_disk_and_quiet_window_pause_rules():
    optional, required = Channel("o", 60, None), Channel("r", 60, None, optional=False)
    quiet = Channel("q", 60, None, quiet_local=(("12:00", "18:00"),))
    assert _pause(optional, "03:00", available=5 * GIB) == "low_available_memory"
    assert _pause(required, "03:00", available=1 * GIB) is None
    assert _pause(optional, "03:00", band="red") == "disk_red" and _pause(required, "03:00", band="red") is None
    assert _pause(required, "03:00", band="critical") == "disk_critical"
    assert _pause(quiet, "12:00") == "channel_quiet_window" and _pause(quiet, "18:00") is None
    assert in_window(time(23, 30), "23:00", "01:00") and not in_window(time(2, 0), "23:00", "01:00")


def test_child_journals_pause_and_resume_transitions(tmp_path):
    config = json.loads(json.dumps(CONFIG))
    family = config["families"]["fc1_openmeteo_meta"]
    family["channels"]["run_meta"]["models"] = ["m_a"]
    local = [datetime(2026, 1, 2, 10, 0)]
    clock = lambda: datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)  # noqa: E731
    mono = [0.0]

    def sleep(_seconds):
        mono[0] += 1900.0
        local[0] = datetime(2026, 1, 2, 13, 0) if mono[0] < 2000 else datetime(2026, 1, 2, 19, 0)

    from weather.evidence.fetch import Response
    runner = ChildRunner("fc1_openmeteo_meta", config=config, config_sha256=CONFIG_SHA, root=tmp_path,
                         repo_root=tmp_path, locations=load_locations(),
                         transport=lambda u, h, t, m: Response(u, 200, b"{}"), clock=clock,
                         local_clock=lambda: local[0], sleep=sleep, available_memory=lambda: 64 * GIB,
                         disk_free=lambda: 500 * GIB, monotonic=lambda: mono[0])
    runner.run(max_iterations=3)
    events = []
    for segment in segment_dirs(tmp_path / "fc1_openmeteo_meta" / "2026-01-02"):
        events += [r for name, r in iter_segment_rows(segment) if name == "events.jsonl"]
    kinds = [(e["kind"], e.get("reason") or e.get("after")) for e in events if e["kind"] in ("pause", "resume")]
    assert kinds == [("pause", "optional_pause_window"), ("pause", "channel_quiet_window"),
                     ("resume", "channel_quiet_window")]
    status = json.loads((tmp_path / "fc1_openmeteo_meta" / "status.json").read_text())
    assert status["schema_version"] == "evidence_family_status_v1"
    assert status["code_identity"]["adoption"] == "explicit_restart"


# --------------------------------------------------------------------------------------------- PL-6
def _result(returncode=0, *, exceeded=None, stderr=""):
    return {"returncode": returncode, "pid": 4242, "duration_seconds": 1.0, "resource_limit_exceeded": exceeded,
            "stderr": stderr, "stdout": "", "containment": {"status": "PASS"}, "termination": None}


class FakeRunner:
    def __init__(self, results, on_call=None):
        self.results, self.calls, self.on_call = list(results), [], on_call

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        kwargs["on_started"]({"pid": 4242, "containment": {"status": "PASS"}})
        if self.on_call:
            self.on_call(len(self.calls))
        return self.results.pop(0)


def _supervisor(tmp_path, runner, family="ob1_metar"):
    return host_module.FamilySupervisor(family, config=CONFIG, config_path="cfg.json", root=tmp_path, runner=runner,
                                        python="py", clock=lambda: datetime(2026, 1, 2, 3, 0, tzinfo=timezone.utc),
                                        sleep=lambda _s: None)


def test_child_runs_inside_the_hard_commit_cap_with_one_blas_thread(tmp_path):
    runner = FakeRunner([_result(0)])
    assert _supervisor(tmp_path, runner).step() == "exit"
    command, kwargs = runner.calls[0]
    assert command == ["py", "-m", "weather.evidence.child", "--family", "ob1_metar", "--config", "cfg.json"]
    assert kwargs["private_memory_max_bytes"] == CONFIG["families"]["ob1_metar"]["ram_cap_mib"] * 1024**2
    assert kwargs["env"]["OPENBLAS_NUM_THREADS"] == "1" and kwargs["timeout_seconds"] is None


def test_cap_kills_leave_receipts_and_disable_the_family_for_the_day(tmp_path):
    over = _result(1, exceeded={"resource": "private_memory_bytes", "limit_bytes": 1}, stderr="MemoryError")
    limit = CONFIG["host"]["max_cap_kills_per_day"]
    runner = FakeRunner([over] * limit)
    supervisor = _supervisor(tmp_path, runner)
    outcomes = [supervisor.step() for _ in range(limit + 1)]
    assert outcomes == ["cap_kill"] * limit + ["disabled"]
    receipts = sorted((tmp_path / "kill_receipts").glob("*.json"))
    assert len(receipts) == limit
    receipt = json.loads(receipts[0].read_text())
    assert receipt["schema_version"] == "evidence_kill_receipt_v1" and receipt["memory_error_in_stderr"]
    assert supervisor.state["disabled_day"] == "2026-01-02"


def test_crash_backoff_doubles_and_explicit_restart_relaunches_at_once(tmp_path):
    restart = tmp_path / "control" / "ob1_metar.restart"

    def on_call(n):
        if n == 3:
            restart.parent.mkdir(parents=True, exist_ok=True)
            restart.write_text("x")

    supervisor = _supervisor(tmp_path, FakeRunner([_result(1), _result(1), _result(0)], on_call))
    assert [supervisor.step(), supervisor.state["backoff_seconds"]] == ["crash", 5.0]
    assert [supervisor.step(), supervisor.state["backoff_seconds"]] == ["crash", 10.0]
    assert supervisor.step() == "restart" and not restart.exists()
    assert supervisor.state["backoff_seconds"] == 0.0


def test_host_stop_file_stops_supervision_and_respawns(tmp_path):
    (tmp_path / "control").mkdir()
    (tmp_path / "control" / "host.stop").write_text("stop")
    runner = FakeRunner([])
    host = host_module.EvidenceHost(config=CONFIG, config_sha256=CONFIG_SHA, config_path="cfg.json", root=tmp_path,
                                    runner=runner, memory_probe=lambda: {"private_bytes": 1})
    assert host.run(max_seconds=5) == 0 and runner.calls == []
    status = json.loads((tmp_path / "host_status.json").read_text())
    assert status["stop_reason"] == "host_stop_file" and status["schema_version"] == "evidence_host_status_v1"


def test_parent_over_its_cap_stops_everything(tmp_path):
    host = host_module.EvidenceHost(config=CONFIG, config_sha256=CONFIG_SHA, config_path="cfg.json", root=tmp_path,
                                    runner=FakeRunner([]), memory_probe=lambda: {"private_bytes": 65 * 1024**2})
    assert host.parent_cap == 64 * 1024**2 == host_module.PARENT_RAM_CAP_BYTES
    assert host.check_parent_cap(host.status_payload())
    assert (tmp_path / "control" / "host.stop").read_text().startswith("parent_ram_cap_exceeded")


# --------------------------------------------------------------------------------------------- PL-4
def test_code_identity_reports_disk_drift_after_an_edit(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("x = 1\n")
    manifest = identity_manifest(repo, ["src/a.py"])
    assert disk_drift(repo, manifest) == []
    (repo / "src" / "a.py").write_text("x = 2\n")
    assert disk_drift(repo, manifest) == ["src/a.py"]
    sha, live = capture_identity(tmp_path / "evidence", REPO_ROOT)
    assert "src/weather/evidence/code_identity.py" in live["files"]
    assert (tmp_path / "evidence" / "identity" / f"{sha}.json.gz").exists()


# --------------------------------------------------------------------------------------------- isolation
def test_no_capture_loop_reaches_the_evidence_package():
    from weather.operations.landing_preflight_rollclass_graph import GraphOptions, TreeView, static_closure_files
    paths = {}
    for base in ("src", "weather"):
        for path in (REPO_ROOT / base).rglob("*.py"):
            relative = path.relative_to(REPO_ROOT).as_posix()
            if "__pycache__" not in relative:
                paths[relative] = relative
    view = TreeView("worktree", paths, lambda key: (REPO_ROOT / key).read_bytes())
    closure = set(static_closure_files(view, GraphOptions()))
    assert closure, "the capture-loop closure must not be empty"
    assert sorted(p for p in closure if p.startswith("src/weather/evidence/")) == []


def test_evidence_package_imports_no_order_wallet_or_signing_client():
    forbidden = re.compile(r"^\s*(from|import)\s+(py_clob_client|eth_account|web3|weather\.execution|"
                           r"weather\.market\.(live|order|international_live)\w*|maker_core\.(runtime|live)\w*)",
                           re.M)
    hits = [p.name for p in (REPO_ROOT / "src" / "weather" / "evidence").rglob("*.py")
            if forbidden.search(p.read_text(encoding="utf-8"))]
    assert hits == []
