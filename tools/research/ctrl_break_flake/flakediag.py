"""Untracked diagnostic plugin: on a failing ctrl-break test, dump the frame locals that the assertion order hides."""
import json, os, time

OUT = os.environ.get("FLAKEDIAG_OUT", r"C:\wt\workstation-chat\l-data\flake\diag.jsonl")


def pytest_runtest_makereport(item, call):
    if call.when != "call" or not ("ctrl_break" in item.name or "stdin_open" in item.name):
        return
    rec = {"t": time.strftime("%H:%M:%S"), "test": item.name, "outcome": "passed" if call.excinfo is None else "failed"}
    if call.excinfo is not None:
        rec["error"] = str(call.excinfo.value)[:300]
        tb = call.excinfo.tb
        while tb is not None:
            if tb.tb_frame.f_code.co_name == item.originalname:
                loc = tb.tb_frame.f_locals
                caught = loc.get("caught")
                v = getattr(caught, "value", None) if caught is not None else None
                rec.update(
                    elapsed=loc.get("elapsed"),
                    deadline_ms=loc.get("deadline_ms"),
                    release_ms=loc.get("release_ms"),
                    child_stdin=repr(loc.get("child_stdin")),
                    cooperative=getattr(v, "cooperative", None),
                    forced=getattr(v, "forced", None),
                    exit_code=getattr(v, "exit_code", None),
                )
                m = loc.get("started_marker")
                try:
                    rec["marker_ms"] = int(m.read_text(encoding="utf-8")) if m else None
                except Exception as e:
                    rec["marker_ms"] = repr(e)
            tb = tb.tb_next
    with open(OUT, "a", encoding="utf-8") as h:
        h.write(json.dumps(rec) + "\n")


import pytest


def pytest_addoption(parser):
    parser.addoption("--flake-repeat", type=int, default=1)


@pytest.fixture
def flake_rep(request):
    return request.param


def pytest_generate_tests(metafunc):
    n = metafunc.config.getoption("--flake-repeat")
    if n > 1:
        metafunc.fixturenames.append("flake_rep")
        metafunc.parametrize("flake_rep", range(n), indirect=True)
