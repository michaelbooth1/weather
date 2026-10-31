"""Synthetic tests for the C3 frozen-tool launcher: fake git and fake children only (no frozen tool, no data).

Guards: master ruling (d) for C3 (fixed argv, frozen d937b34 import origin, -E -s with PYTHONPATH/PYTHONHOME scrubbed,
tree re-check before each child, stop on first failure, child-tree kill on timeout, receipt fields).
"""
from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path

import pytest

from weather.calibration import c3_frozen_launcher as fl

FROZEN = "d937b34ab1d50cd4b8e35e80901184f7f0f82a9f"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    tree, data = tmp_path / "scorer", tmp_path / "data"
    tree.mkdir()
    data.mkdir()
    monkeypatch.setattr(fl, "SCORER_TREE", tree)
    monkeypatch.setattr(fl, "DATA_ROOT", data)
    return tmp_path, tree, data


class Fake:
    """Fake git + children. `heads`/`dirty` are per-call sequences; `fail_at` makes that step exit non-zero."""

    def __init__(self, tree, head=FROZEN, dirty="", fail_at=None, preflight=None, dirty_after_calls=None):
        self.tree, self.head, self.dirty, self.fail_at = tree, head, dirty, fail_at
        self.preflight, self.dirty_after_calls = preflight or {}, dirty_after_calls
        self.calls, self.envs, self.git_calls = [], [], 0

    def git(self, *args):
        self.git_calls += 1
        if args[0] == "rev-parse":
            return self.head + "\n"
        if self.dirty_after_calls is not None and self.git_calls > self.dirty_after_calls:
            return "?? stray.txt\n"
        return self.dirty

    def run(self, argv, cwd, env, timeout_s, stdout_path, stderr_path):
        self.envs.append(env)
        assert Path(cwd) == self.tree / "src"
        Path(stderr_path).write_bytes(b"")
        if "-c" in argv:
            found = dict(weather=str(self.tree / "weather" / "__init__.py"),
                         maker_core=str(self.tree / "src" / "maker_core" / "__init__.py"),
                         maker_core_replay_bundle=str(self.tree / "src" / "maker_core" / "replay" / "bundle.py"),
                         module_origin=str(self.tree / "src" / "x.py"), repo_root=str(self.tree),
                         flags=dict(ignore_environment=1, no_user_site=1, isolated=0))
            found.update(self.preflight)
            Path(stdout_path).write_text(json.dumps(found) + "\n", encoding="utf-8")
            return dict(pid=1, exit_code=0, timed_out=False, runtime_s=0.0, peak_working_set_bytes=1)
        self.calls.append(argv)
        Path(stdout_path).write_bytes(b"{}\n")
        target = Path(argv[argv.index("--out") + 1])
        target.mkdir()
        (target / "bundle.json").write_bytes(f"bundle {len(self.calls)}".encode())
        code = 2 if self.fail_at == len(self.calls) else 0
        return dict(pid=100 + len(self.calls), exit_code=code, timed_out=False, runtime_s=0.01,
                    peak_working_set_bytes=12345)


def _receipt(out):
    return json.loads((out / "launcher_receipt.json").read_text(encoding="utf-8"))


def test_plan_is_the_exact_fixed_argv_list(env):
    tmp, tree, data = env
    out = tmp / "out"
    py = Path(r"C:\py\python.exe")
    argvs = [fl.child_argv(py, s) for s in fl.plan(out)]
    assert len(argvs) == 28
    markets = ["toronto", "nyc", "atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles",
               "miami", "san-francisco", "seattle"]
    assert argvs[0] == [str(py), "-E", "-s", "-m", "weather.market.maker_replay_bundle", "bundle", "--date",
                        "2026-09-25", "--data-root", str(data), "--markets", *markets,
                        "--out", str(out / "passA" / "2026-09-25")]
    assert argvs[12][7] == "2026-10-07" and argvs[13][-1] == str(out / "passB" / "2026-09-25")
    assert argvs[25][-1] == str(out / "passB" / "2026-10-07")
    days = [f"2026-09-{d}" for d in range(25, 31)] + [f"2026-10-0{d}" for d in range(1, 8)]
    expected_score = [str(py), "-E", "-s", "-m", "weather.market.maker_fair_value_score",
                      *[a for d in days for a in ("--bundle", str(out / "passA" / d))]]
    assert argvs[26] == [*expected_score, "--out", str(out / "report1")]
    assert argvs[27] == [*expected_score, "--out", str(out / "report2")]
    assert all("-I" not in a for a in argvs)


def test_full_fake_run_writes_every_receipt_field(env):
    tmp, tree, _ = env
    fake = Fake(tree)
    out = tmp / "out"
    assert fl.main(["--out", str(out)], runner=fake, python=sys.executable) == fl.EXIT_OK
    r = _receipt(out)
    assert r["status"] == "COMPLETE" and len(r["steps"]) == 28 and len(fake.calls) == 28
    for key in ("launcher_sha256", "frozen_commit", "scorer_tree", "python", "flags", "env_keys_removed",
                "pth_trap_note", "absent_days", "absent_note", "markets", "timeouts_s", "plan", "start_tree"):
        assert key in r
    assert r["absent_days"] == ["2026-09-23", "2026-09-24"] and "-E -s" in r["pth_trap_note"]
    assert r["child_cwd"] == str(tree / "src")
    for step in r["steps"]:
        for key in ("argv", "exit_code", "runtime_s", "peak_working_set_bytes", "outputs", "preflight", "timed_out"):
            assert key in step
        assert step["outputs"] and len(step["outputs"][0]["sha256"]) == 64
        assert step["preflight"]["tree"] == {"head": FROZEN, "porcelain_empty": True}
        assert step["preflight"]["imports"]["repo_root"] == str(tree)
        assert step["cwd"] == str(tree / "src")


@pytest.mark.parametrize("head, dirty", [("0" * 40, ""), (FROZEN, " M src/x.py\n")])
def test_refuses_at_start_on_wrong_head_or_dirty_tree(env, head, dirty):
    tmp, tree, _ = env
    fake = Fake(tree, head=head, dirty=dirty)
    out = tmp / "out"
    assert fl.main(["--out", str(out)], runner=fake) == fl.EXIT_REFUSED
    assert fake.calls == [] and not out.exists()


def test_rechecks_the_tree_before_each_child(env):
    tmp, tree, _ = env
    fake = Fake(tree, dirty_after_calls=6)    # start check + 2 pre-flights' git checks stay clean
    out = tmp / "out"
    assert fl.main(["--out", str(out)], runner=fake) == fl.EXIT_REFUSED
    r = _receipt(out)
    assert r["status"] == "REFUSED" and "dirty" in r["refusal"] and len(fake.calls) == 2


@pytest.mark.parametrize("key", ["weather", "maker_core", "maker_core_replay_bundle", "module_origin", "repo_root"])
def test_preflight_path_outside_the_frozen_tree_refuses(env, key):
    tmp, tree, _ = env
    fake = Fake(tree, preflight={key: r"C:\Users\Michael\Documents\github\weather\src\weather\__init__.py"})
    out = tmp / "out"
    assert fl.main(["--out", str(out)], runner=fake) == fl.EXIT_REFUSED
    r = _receipt(out)
    assert fake.calls == [] and key in r["refusal"] and r["steps"][0]["refused"]


def test_preflight_missing_module_or_wrong_flags_refuses(env):
    tmp, tree, _ = env
    for i, pre in enumerate(({"module_origin": None}, {"flags": {"ignore_environment": 0, "no_user_site": 1}})):
        fake = Fake(tree, preflight=pre)
        out = tmp / f"out{i}"
        assert fl.main(["--out", str(out)], runner=fake) == fl.EXIT_REFUSED
        assert fake.calls == []


def test_stops_at_the_first_non_zero_exit_without_retry(env):
    tmp, tree, _ = env
    fake = Fake(tree, fail_at=3)
    out = tmp / "out"
    assert fl.main(["--out", str(out)], runner=fake) == fl.EXIT_CHILD_FAILED
    r = _receipt(out)
    assert len(fake.calls) == 3 and r["status"] == "STOPPED" and r["stopped_at"] == "build_A_2026-09-27"
    assert r["steps"][-1]["exit_code"] == 2 and len(r["steps"]) == 3


def test_refuses_an_existing_or_overlapping_out(env):
    tmp, tree, data = env
    fake = Fake(tree)
    (tmp / "exists").mkdir()
    assert fl.main(["--out", str(tmp / "exists")], runner=fake) == fl.EXIT_REFUSED
    assert fl.main(["--out", str(data / "inside")], runner=fake) == fl.EXIT_REFUSED
    assert fl.main(["--out", str(tree / "inside")], runner=fake) == fl.EXIT_REFUSED
    assert fake.calls == []


def test_env_scrub_removes_pythonpath_and_pythonhome_in_any_case(env, monkeypatch):
    scrubbed, removed = fl.child_env({"PYTHONPATH": "a", "pythonhome": "b", "PATH": "p", "PYTHONUTF8": "1"})
    assert scrubbed == {"PATH": "p", "PYTHONUTF8": "1"} and removed == ["PYTHONPATH", "pythonhome"]
    tmp, tree, _ = env
    monkeypatch.setenv("PYTHONPATH", "x")
    monkeypatch.setenv("PYTHONHOME", "y")
    fake = Fake(tree)
    out = tmp / "out"
    assert fl.main(["--out", str(out)], runner=fake) == fl.EXIT_OK
    assert all(not {k.upper() for k in e} & {"PYTHONPATH", "PYTHONHOME"} for e in fake.envs)
    assert sorted(k.upper() for k in _receipt(out)["env_keys_removed"]) == ["PYTHONHOME", "PYTHONPATH"]


def test_timeout_kills_the_whole_child_tree(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    code = ("import subprocess, sys, time\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            f"open(r'{pidfile}', 'w').write(str(p.pid))\n"
            "time.sleep(120)\n")
    rec = fl.run_child([sys.executable, "-c", code], tmp_path, None, 8, tmp_path / "o.txt", tmp_path / "e.txt")
    assert rec["timed_out"] is True and rec["exit_code"] != 0
    grandchild = int(pidfile.read_text())
    deadline = time.monotonic() + 10
    while fl.pid_alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not fl.pid_alive(grandchild) and not fl.pid_alive(rec["pid"])


def test_run_child_records_exit_code_and_peak(tmp_path):
    rec = fl.run_child([sys.executable, "-c", "import sys; sys.exit(4)"], tmp_path, None, 60,
                       tmp_path / "o.txt", tmp_path / "e.txt")
    assert rec["exit_code"] == 4 and rec["timed_out"] is False
    if sys.platform == "win32":
        assert rec["peak_working_set_bytes"] > 0


def test_imports_are_stdlib_only_and_offline():
    tree = ast.parse(Path(fl.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            names.add(node.module.split(".")[0])
    imports = sorted(names)
    assert imports == ["argparse", "ctypes", "datetime", "hashlib", "json", "os", "pathlib", "subprocess", "sys",
                       "time"]
