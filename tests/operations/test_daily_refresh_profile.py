import json
from pathlib import Path
import sys
import time
import tracemalloc
from types import SimpleNamespace
import warnings

import pytest

from weather.operations import daily_refresh_profile as profiling
from weather.operations.daily_refresh_resources import prepare_step_child_invocation
from weather.operations.daily_refresh_step_child import run_child
from weather.operations import daily_refresh_step_child as child


def args(tmp_path, **kwargs):
    return SimpleNamespace(profile_steps=True, profile_out=str(tmp_path / "profiles"),
                           backtest_root=str(tmp_path), **kwargs)


class FakeProfiler:
    def __init__(self, interval):
        assert interval == 0.01
    def start(self): pass
    def stop(self): pass
    def output_text(self, **kwargs): return "fixture profile\n"


def reports(tmp_path):
    return [json.loads(path.read_text()) for path in (tmp_path / "profiles").glob("*.json")]


def test_disabled_profiling_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(profiling, "current_private_bytes", lambda: (_ for _ in ()).throw(AssertionError()))
    value = object()
    assert profiling.run_profiled("fixture", lambda _: value, SimpleNamespace()) is value
    assert not list(tmp_path.iterdir())


def test_enabled_profile_has_wall_private_trace_and_optional_sampler(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyinstrument", SimpleNamespace(Profiler=FakeProfiler))
    monkeypatch.setattr(profiling, "current_private_bytes", lambda: 123456)
    held = []
    def runner(_):
        held.append(bytearray(1024 * 1024))
        time.sleep(0.12)
        return {"fixture": "unchanged"}
    assert profiling.run_profiled("fixture", runner, args(tmp_path)) == {"fixture": "unchanged"}
    report = reports(tmp_path)[0]
    assert report["wall_seconds"] >= 0.12
    assert report["peak_private_bytes"] == 123456
    assert report["traced_peak_bytes"] >= 1024 * 1024
    assert report["top_allocations"]
    assert report["pyinstrument"] == "captured"
    assert Path(report["pyinstrument_path"]).read_text() == "fixture profile\n"
    assert not tracemalloc.is_tracing()


def test_missing_optional_dependency_and_memory_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyinstrument", None)
    monkeypatch.setattr(profiling, "current_private_bytes", lambda: None)
    assert profiling.run_profiled("fixture", lambda _: 42, args(tmp_path)) == 42
    report = reports(tmp_path)[0]
    assert report["peak_private_bytes"] is None
    assert report["private_memory_available"] is False
    assert report["pyinstrument"] == "unavailable"
    assert report["errors"]


def test_error_outcome_preserved_and_preexisting_tracer_not_stopped(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyinstrument", SimpleNamespace(Profiler=FakeProfiler))
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="runner failure"):
            profiling.run_profiled("fixture", lambda _: (_ for _ in ()).throw(ValueError("runner failure")), args(tmp_path))
        assert tracemalloc.is_tracing()
        report = reports(tmp_path)[0]
        assert report["status"] == "error"
        assert report["tracemalloc_scope"] == "existing process tracer"
    finally:
        tracemalloc.stop()


def test_profile_write_failure_cannot_change_step_result(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyinstrument", SimpleNamespace(Profiler=FakeProfiler))
    monkeypatch.setattr(profiling, "write_json_atomic", lambda *a, **k: (_ for _ in ()).throw(OSError("disk fixture")))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert profiling.run_profiled("fixture", lambda _: "ok", args(tmp_path)) == "ok"


def test_profile_flag_reaches_isolated_runner_not_just_parent_wait(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyinstrument", SimpleNamespace(Profiler=FakeProfiler))
    invocation = prepare_step_child_invocation(args(tmp_path), "maker_paper_score", run_id="fixture")
    manifest = json.loads(Path(invocation["args_json"]).read_text())
    assert manifest["args"]["profile_steps"] is True
    monkeypatch.setattr(child, "_runner_for_step", lambda name: lambda options: {"ok": True})
    assert run_child("maker_paper_score", invocation["args_json"], invocation["result_json"]) == 0
    report = reports(tmp_path)[0]
    assert report["scope"] == "isolated_step"
    assert report["step"] == "maker_paper_score"


def test_cli_profile_flags_default_off_and_enable_explicitly(tmp_path):
    from weather.operations import daily_refresh
    parser = daily_refresh.build_parser()
    default = parser.parse_args(["run"])
    assert default.profile_steps is False
    explicit = parser.parse_args(["run", "--profile-steps", "--profile-out", str(tmp_path)])
    assert explicit.profile_steps is True
    assert explicit.profile_out == str(tmp_path)


def test_real_optional_pyinstrument_api(tmp_path):
    pytest.importorskip("pyinstrument")
    result = profiling.run_profiled("real_fixture", lambda _: time.sleep(0.03), args(tmp_path))
    assert result is None
    report = reports(tmp_path)[0]
    assert report["pyinstrument"] == "captured"
    assert Path(report["pyinstrument_path"]).stat().st_size > 0
