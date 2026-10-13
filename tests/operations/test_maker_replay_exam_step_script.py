"""Native fixture tests for scripts/ops/maker_replay_exam_step.ps1.

The real script, lease and Job helpers run against a disposable Git repository whose locked,
detached worktree carries stub exam CLIs. Only the fixture clock, the lease mutex namespace and
the lease policy window change. No exam module is imported here: the stubs stand in for the
hashed ``maker_core`` / ``weather.market.maker_plugin`` trees, which this script must not touch.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import venv

import pytest

from tests.git_template import commit_fixture_tree

from weather.operations.process_lock_identity import observe_process_identity
from weather.paths import repo_path


pytestmark = pytest.mark.skipif(os.name != "nt", reason="real Windows PowerShell/Job/lease orchestration")

MODULE = "ab" * 32
CAL = ["2026-09-27", "2026-09-28", "2026-09-29"]
PANEL = [f"2026-{d}" for d in ["09-30"] + [f"10-{n:02d}" for n in range(1, 15)]]
EXAM_ON_SCORING_DAY = "2026-10-15T12:00:00Z"   # 08:00 Toronto

# One recorder shared by every stub: argv, interpreter flags, PYTHONPATH and cwd of each child.
RECORD = r'''
import json, os, sys
def record(kind):
    path = os.environ.get("FIXTURE_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(kind=kind, argv=sys.argv[1:], safe_path=bool(sys.flags.safe_path),
                dont_write_bytecode=bool(sys.dont_write_bytecode), pythonpath=os.environ.get("PYTHONPATH"),
                cwd=os.getcwd())) + "\n")
def mode():
    return os.environ.get("FIXTURE_MODE", "")
def value(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else None
def values(flag):
    return [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == flag]
def hang():
    import subprocess, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    with open(os.environ["FIXTURE_HANG"], "w") as handle:
        json.dump(dict(pid=child.pid, worker_pid=os.getpid()), handle)
    time.sleep(300)
'''

EXPORT = r'''
import hashlib, json, os, sys
from pathlib import Path
from weather._fixture_record import record, mode, value, values, hang
record("export")
command = sys.argv[1]
if command == "module-hash":
    print(json.dumps({"module_sha256": os.environ.get("FIXTURE_MODULE", "ab" * 32)}))
    raise SystemExit(0)
if command == "universe":
    Path(value("--out")).write_text(json.dumps(sorted(values("--bundle"))))
    raise SystemExit(0)
day, out = value("--day"), Path(value("--out"))
if mode() == "hang":
    hang()
(out / day / "bundle").mkdir(parents=True)
refused = mode() == "refuse:" + day
receipt = dict(day=day, status="REFUSED" if refused else "SEALED", module_sha256=os.environ.get("FIXTURE_MODULE", "ab" * 32),
               bundle={"bytes": 100, "records": 10, "trade_clock_skew": {"leading_capture": 0, "max_us": 0}},
               peak_memory_bytes=1)
(out / day / "receipt.json").write_text(json.dumps(receipt))
(out / "panel-ledger.jsonl").open("a").write(json.dumps(receipt) + "\n")
raise SystemExit(2 if refused else 0)
'''

PACK = r'''
import hashlib, json, os, sys
from pathlib import Path
from weather._fixture_record import record, mode, value, values
record("pack")
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
command = sys.argv[1]
if command == "quote_markets":
    Path(value("--out")).write_text("[]")
elif command == "calibrate_hazard":
    doc = {"global_fallback": "city" if mode() == "fallback" else None, "quote_markets": []}
    if mode() == "binding_status":
        doc["binding_status"] = "UNBOUND"
    Path(value("--out")).write_text(json.dumps(doc))
elif command == "rehearse":
    Path(value("--out")).write_text(json.dumps({"detail": {"calibration_sha256": sha(value("--calibration"))}}))
elif command == "derive_ceilings":
    key = json.loads(Path(values("--rehearsal")[0]).read_text())["detail"]["calibration_sha256"]
    executable = mode() != "not_executable"
    Path(value("--out")).write_text(json.dumps({"calibration_sha256": "0" * 64 if mode() == "other_calibration" else key,
                                                "derived": {"executable": executable}}))
    print("ceiling_measurement_sha256=x; executable_on_host=" + str(executable))
    raise SystemExit(0 if executable else 3)
elif command == "manifest" and sys.argv[2] == "build":
    ceilings = dict(max_input_bytes=1, max_records=1, max_seconds=60.0, max_output_bytes=1, max_memory_bytes=1)
    ceilings.update(json.loads(os.environ.get("FIXTURE_CEILINGS", "{}")))
    Path(value("--out")).write_text(json.dumps({"ceilings": ceilings}))
elif command == "manifest" and sys.argv[2] == "verify":
    assert sha(value("--manifest")) == value("--manifest-sha256")
    if mode() != "verify_silent":
        print("manifest_sha256=" + value("--manifest-sha256") + "; VERIFIED_PREFLIGHT_ONLY; enrollment gates separate")
elif command == "run":
    attempts = Path(value("--pre-registration")).parent / "attempts"
    attempts.mkdir(exist_ok=True)
    Path(value("--out")).mkdir()
    (attempts / "maker-replay-2026-10-15-v3.json").write_text("{}")
    if mode() != "look_stopped":
        (attempts / "maker-replay-2026-10-15-v3.completed.json").write_text("{}")
'''

DOCUMENTS = ["maker-replay-hurdles-preregistration-2026-09-27.md", "maker-replay-execution-addendum-2026-09-27.md",
             "maker-replay-clarification-1-2026-09-27.md", "maker-replay-clarification-2-2026-09-29.md",
             "maker-replay-clarification-3-2026-10-01.md"]


def git(*args):
    result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def replace_once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def exam(tmp_path, tmp_path_factory, request):
    variant = getattr(request, "param", "")
    repo, pin, root = tmp_path / "production", tmp_path / "pinned", tmp_path / "exam"
    ops = repo / "scripts/ops"
    ops.mkdir(parents=True)
    shutil.copy2(repo_path("scripts/ops/windows_kill_on_close_job.ps1"), ops)
    mutex = "Local\\ExamStepFixture-" + uuid.uuid4().hex
    admission = repo_path("scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    admission = admission.replace("Global\\WeatherProjectHeavyWorkloadV1", mutex)
    admission += "\nfunction Get-WeatherHeavyWorkloadPolicyWindow { return 'fixture-clock-only' }\n"
    write(ops / "workload_admission.ps1", admission)
    script = repo_path("scripts/ops/maker_replay_exam_step.ps1").read_text(encoding="utf-8-sig")
    script = replace_once(script, "function Get-ExamUtcNow { return [DateTime]::UtcNow }",
        "function Get-ExamUtcNow { return [DateTime]::Parse($env:FIXTURE_UTC_NOW).ToUniversalTime() }")
    script = replace_once(script, "$HardStopGrace = 300 ", "$HardStopGrace = 0 ")
    script = replace_once(script, "$MinimumSeconds = 60", "$MinimumSeconds = 1")
    write(ops / "maker_replay_exam_step.ps1", script)
    venv.EnvBuilder(with_pip=False).create(repo / "venv")
    write(repo / "docs/operations/DECISION_LOG.md", "# fixture decision log\n")
    write(repo / ".gitignore", "data/\n__pycache__/\n")
    src = repo / "src"
    for package in ("weather", "weather/market", "weather/market/maker_plugin", "maker_core", "maker_core/replay"):
        write(src / package / "__init__.py", "")
    write(src / "weather/_fixture_record.py", RECORD)
    write(src / "weather/paths.py", "")
    write(src / "weather/market/maker_replay_night.py", "")
    write(src / "weather/market/maker_plugin/replay_export.py", EXPORT)
    write(src / "maker_core/replay/ceilings.py", "")
    write(src / "maker_core/replay/approved_registrations.py", "")
    write(src / "maker_core/replay/__main__.py", PACK)
    for name in DOCUMENTS:
        write(repo / "docs/research" / name, "signed fixture\n")
    if variant == "decoy":
        # maker_core resolves from site-packages, outside the pinned worktree.
        site = next((repo / "venv/Lib").glob("site-packages"))
        shutil.copytree(src / "maker_core", site / "maker_core")
        shutil.rmtree(src / "maker_core")
    # Same one-commit checkout as git init/add/commit; see tests/git_template.py.
    head = commit_fixture_tree(repo, cache_root=tmp_path_factory.getbasetemp() / "git-templates", quiet=True,
                               config=("user.name=Fixture", "user.email=fixture@example.invalid",
                                       "commit.gpgSign=false"), message="exam fixture", timeout=60)
    git("-C", str(repo), "worktree", "add", "--detach", str(pin), head)
    if variant != "unlocked":
        git("-C", str(repo), "worktree", "lock", str(pin), "--reason", "fixture")
    return dict(repo=repo, pin=pin, root=root, head=head, mutex=mutex, log=tmp_path / "children.jsonl",
                hang=tmp_path / "hang.json")


def run(exam, step, *, now=EXAM_ON_SCORING_DAY, mode="", ceilings=None, module=MODULE, timeout=180, **params):
    arguments = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                 str(exam["repo"] / "scripts/ops/maker_replay_exam_step.ps1"), "-Step", step,
                 "-Worktree", str(exam["pin"]), "-Pin", params.pop("pin", exam["head"]), "-RepoRoot", str(exam["repo"])]
    if step != "module_hash":
        arguments += ["-ExamRoot", str(exam["root"])]
    for name, item in params.items():
        arguments.append("-" + name)
        arguments += item if isinstance(item, list) else [str(item)]
    env = {**os.environ, "FIXTURE_UTC_NOW": now, "FIXTURE_MODE": mode, "FIXTURE_LOG": str(exam["log"]),
           "FIXTURE_MODULE": module, "FIXTURE_HANG": str(exam["hang"]), "FIXTURE_CEILINGS": json.dumps(ceilings or {})}
    env.pop("PYTHONPATH", None)
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, env=env, cwd=exam["repo"])
    return result.returncode, result.stdout + result.stderr


def children(exam):
    if not exam["log"].exists():
        return []
    return [json.loads(line) for line in exam["log"].read_text(encoding="utf-8").splitlines()]


def stepped(exam, kind):
    """Child launches of the stub CLIs, excluding the module-hash helper and the probe."""
    return [c for c in children(exam) if c["kind"] == kind and c["argv"][:1] != ["module-hash"]]


def flag(child, name):
    return child["argv"][child["argv"].index(name) + 1]


def only_root(exam, prefix):
    roots = sorted(p for p in exam["root"].iterdir() if p.name.startswith(prefix + "-"))
    assert len(roots) == 1, roots
    return roots[0]


def prepare_through_ceilings(exam):
    code, log = run(exam, "calibration", DataRoot=exam["repo"].parent / "data", ModuleSha256=MODULE)
    assert code == 0, log
    calibration = only_root(exam, "calibration")
    code, log = run(exam, "night", Kind="rehearsal-panel", DataRoot=exam["repo"].parent / "data",
                    ReleaseRoot=exam["repo"].parent / "releases", ModuleSha256=MODULE)
    assert code == 0, log
    rehearsal = only_root(exam, "rehearsal-panel")
    for step in ("quote_markets", "calibrate_hazard"):
        code, log = run(exam, step, CalibrationRoot=calibration)
        assert code == 0, log
    code, log = run(exam, "rehearse", RehearsalRoot=rehearsal)
    assert code == 0, log
    return calibration, rehearsal


def prepare_through_verify(exam):
    calibration, _ = prepare_through_ceilings(exam)
    code, log = run(exam, "derive_ceilings")
    assert code == 0, log
    code, log = run(exam, "night", Kind="panel", DataRoot=exam["repo"].parent / "data",
                    ReleaseRoot=exam["repo"].parent / "releases", ModuleSha256=MODULE)
    assert code == 0, log
    panel = only_root(exam, "panel")
    code, log = run(exam, "universe", PanelRoot=panel)
    assert code == 0, log
    (exam["root"] / "owner-decision.json").write_bytes(
        json.dumps({"authorization_id": "maker-replay-2026-10-15-v3"}).encode())
    binding = dict(CalibrationRoot=calibration, PanelRoot=panel)
    return binding


def test_full_line_runs_every_step_pinned_leased_and_bound(exam):
    code, log = run(exam, "module_hash")
    assert code == 0 and MODULE in log, log
    binding = prepare_through_verify(exam)
    for step in ("manifest_build", "manifest_verify", "prelook", "look"):
        code, log = run(exam, step, **binding)
        assert code == 0, log
    assert "outcome COMPLETED" in log, log
    launched = children(exam)
    # Every child, probe included, ran -P -B from the worktree src with cwd at the production root.
    assert launched and all(c["safe_path"] and c["dont_write_bytecode"] for c in launched)
    assert {c["pythonpath"] for c in launched} == {str(exam["pin"] / "src")}
    assert {os.path.normcase(c["cwd"]) for c in launched} == {os.path.normcase(str(exam["repo"]))}
    exports = stepped(exam, "export")
    days = [flag(c, "--day") for c in exports if c["argv"][0] in ("calibration", "night")]
    assert days == CAL + CAL + PANEL
    # 08:00 Toronto leaves 3,000 s before 08:50: the 11,000 s export bound is capped to it.
    assert {flag(c, "--max-seconds") for c in exports if "--max-seconds" in c["argv"]} == {"3000"}
    assert all(flag(c, "--expected-module-sha256") == MODULE for c in exports if "--day" in c["argv"])
    packs = {c["argv"][0] + ("_" + c["argv"][1] if c["argv"][0] == "manifest" else ""): c for c in stepped(exam, "pack")}
    assert flag(packs["quote_markets"], "--max-seconds") == "2700"
    assert flag(packs["quote_markets"], "--max-input-bytes") == "300"
    assert flag(packs["quote_markets"], "--max-records") == "30"
    look = packs["run"]
    assert "--max-seconds" not in look["argv"]          # the manifest ceiling governs the look
    assert flag(look, "--clarification-3").endswith("maker-replay-clarification-3-2026-10-01.md")
    assert flag(look, "--decision-log") == str(exam["repo"] / "docs/operations/DECISION_LOG.md").replace("/", "\\")
    assert len([a for a in look["argv"] if a == "--bundle"]) == 15
    receipts = list((exam["root"] / "operator").glob("*.step.json"))
    assert receipts and all(json.loads(p.read_text())["teardown_proved"] for p in receipts)
    assert not list(exam["pin"].rglob("__pycache__"))
    assert git("-C", str(exam["pin"]), "status", "--porcelain") == ""


def test_max_seconds_is_capped_to_0850_and_refused_outside(exam):
    data = exam["repo"].parent / "data"
    code, log = run(exam, "calibration", now="2026-10-15T12:40:00Z", Day="2026-09-27", DataRoot=data, ModuleSha256=MODULE)
    assert code == 0, log
    assert flag(stepped(exam, "export")[-1], "--max-seconds") == "600"
    for now in ("2026-10-15T12:50:00Z", "2026-10-15T04:20:00Z"):     # 08:50 and 00:20 Toronto
        before = len(children(exam))
        code, log = run(exam, "calibration", now=now, Day="2026-09-28", DataRoot=data, ModuleSha256=MODULE)
        assert code != 0 and "outside 00:30-08:50" in log, log
        assert len(children(exam)) == before


def test_refused_day_stops_the_line_and_is_never_retried_in_place(exam):
    data = exam["repo"].parent / "data"
    code, log = run(exam, "calibration", mode="refuse:2026-09-28", DataRoot=data, ModuleSha256=MODULE)
    assert code != 0 and "REFUSED, not SEALED" in log, log
    assert [flag(c, "--day") for c in stepped(exam, "export")] == CAL[:2]
    root = only_root(exam, "calibration")
    code, log = run(exam, "calibration", Day="2026-09-29", AttemptRoot=root, DataRoot=data, ModuleSha256=MODULE)
    assert code != 0 and "REFUSED, not SEALED" in log, log
    assert len(stepped(exam, "export")) == 2


def test_a_sealed_root_continues_with_new_days_only_under_one_module_hash(exam):
    data, releases = exam["repo"].parent / "data", exam["repo"].parent / "releases"
    night = dict(Kind="panel", DataRoot=data, ReleaseRoot=releases)
    code, log = run(exam, "night", Day="2026-09-30", ModuleSha256=MODULE, **night)
    assert code == 0, log
    root = only_root(exam, "panel")
    code, log = run(exam, "night", Day="2026-10-01", AttemptRoot=root, ModuleSha256=MODULE, **night)
    assert code == 0, log
    code, log = run(exam, "night", Day="2026-10-01", AttemptRoot=root, ModuleSha256=MODULE, **night)
    assert code != 0 and "never retry in place" in log, log
    other = "cd" * 32
    code, log = run(exam, "night", Day="2026-10-02", AttemptRoot=root, ModuleSha256=other, module=other, **night)
    assert code != 0 and "another module hash" in log, log
    code, log = run(exam, "night", Day="2026-10-02", ModuleSha256=MODULE, module=other, **night)
    assert code != 0 and "not -ModuleSha256" in log, log
    code, log = run(exam, "night", now="2026-10-14T12:00:00Z", Day="2026-10-14", ModuleSha256=MODULE, **night)
    assert code != 0 and "has not closed" in log, log
    assert [flag(c, "--day") for c in stepped(exam, "export") if "--day" in c["argv"]] == ["2026-09-30", "2026-10-01"]


@pytest.mark.parametrize("exam", ["decoy"], indirect=True)
def test_probe_refuses_an_import_outside_the_pinned_worktree(exam):
    code, log = run(exam, "module_hash")
    assert code != 0 and "module-path probe failed" in log, log
    assert stepped(exam, "export") == []


@pytest.mark.parametrize("exam", ["unlocked"], indirect=True)
def test_an_unlocked_worktree_is_refused(exam):
    code, log = run(exam, "module_hash")
    assert code != 0 and "is not a locked worktree" in log, log


def test_wrong_pin_and_dirty_worktree_are_refused(exam):
    code, log = run(exam, "module_hash", pin="0" * 40)
    assert code != 0 and "is not the pin" in log, log
    (exam["pin"] / "stray.txt").write_text("x")
    code, log = run(exam, "module_hash")
    assert code != 0 and "not clean" in log, log
    assert children(exam) == []


def test_exam_root_inside_a_repository_is_refused(exam):
    exam = dict(exam, root=exam["repo"] / "exam")
    code, log = run(exam, "prelook")
    assert code != 0 and "inside a repository" in log, log


@pytest.mark.parametrize("mode,message", [("fallback", "global_fallback=city"), ("binding_status", "binding_status=UNBOUND")])
def test_calibration_with_a_fallback_or_binding_status_is_refused(exam, mode, message):
    code, log = run(exam, "calibration", DataRoot=exam["repo"].parent / "data", ModuleSha256=MODULE)
    assert code == 0, log
    calibration = only_root(exam, "calibration")
    code, log = run(exam, "quote_markets", CalibrationRoot=calibration)
    assert code == 0, log
    code, log = run(exam, "calibrate_hazard", mode=mode, CalibrationRoot=calibration)
    assert code != 0 and message in log, log


def test_derive_ceilings_not_executable_exits_3_and_other_calibration_refuses(exam):
    prepare_through_ceilings(exam)
    code, log = run(exam, "derive_ceilings", mode="not_executable")
    assert code == 3 and "NOT_EXECUTABLE_ON_THIS_HOST" in log, log
    (exam["root"] / "ceiling-measurement.json").unlink()
    code, log = run(exam, "derive_ceilings", mode="other_calibration")
    assert code != 0 and "ceilings rehearsed on another calibration" in log, log


def test_manifest_steps_refuse_before_the_toronto_scoring_date(exam):
    code, log = run(exam, "manifest_build", now="2026-10-15T03:59:00Z")    # 10-14 23:59 Toronto
    assert code != 0 and "on or after 2026-10-15" in log, log


def test_verify_must_print_the_marker_and_the_look_needs_a_verify_from_this_pin(exam):
    binding = prepare_through_verify(exam)
    code, log = run(exam, "manifest_build", **binding)
    assert code == 0, log
    code, log = run(exam, "look", **binding)
    assert code != 0 and "no VERIFIED_PREFLIGHT_ONLY manifest_verify from pin" in log, log
    code, log = run(exam, "manifest_verify", mode="verify_silent", **binding)
    assert code != 0 and "did not print VERIFIED_PREFLIGHT_ONLY" in log, log
    code, log = run(exam, "prelook", **binding)
    assert code != 0 and "no VERIFIED_PREFLIGHT_ONLY" in log, log
    assert not [c for c in stepped(exam, "pack") if c["argv"][0] == "run"]


@pytest.mark.parametrize("now,ceilings,message", [
    ("2026-10-15T12:00:00Z", {"max_seconds": 3001.0}, "does not fit before 08:50"),
    ("2026-10-15T12:00:00Z", {"max_memory_bytes": 2 ** 50}, "available RAM"),
    ("2026-10-15T12:00:00Z", {"max_output_bytes": 2 ** 52}, "2x report cap"),
])
def test_prelook_refuses_runtime_ram_and_report_margins(exam, now, ceilings, message):
    binding = prepare_through_verify(exam)
    for step in ("manifest_build", "manifest_verify"):
        code, log = run(exam, step, ceilings=ceilings, **binding)
        assert code == 0, log
    code, log = run(exam, "look", now=now, **binding)
    assert code != 0 and message in log, log
    assert not [c for c in stepped(exam, "pack") if c["argv"][0] == "run"]


def test_a_reserved_look_is_never_started_again(exam):
    binding = prepare_through_verify(exam)
    for step in ("manifest_build", "manifest_verify"):
        code, log = run(exam, step, **binding)
        assert code == 0, log
    code, log = run(exam, "look", mode="look_stopped", **binding)
    assert code == 0 and "CONSUMED_STOPPED" in log, log
    code, log = run(exam, "look", **binding)
    assert code != 0 and "look already reserved" in log, log
    assert len([c for c in stepped(exam, "pack") if c["argv"][0] == "run"]) == 1


def test_busy_lease_refuses_before_any_child(exam):
    holder = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        f"$m=[Threading.Mutex]::new($false,'{exam['mutex']}'); $null=$m.WaitOne(); 'held'; Start-Sleep 60"],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        code, log = run(exam, "calibration", Day="2026-09-27", DataRoot=exam["repo"].parent / "data", ModuleSha256=MODULE)
        assert code != 0 and "lease busy" in log, log
        assert stepped(exam, "export") == []
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_hard_stop_at_the_boundary_kills_the_child_tree_and_releases_the_lease(exam):
    data = exam["repo"].parent / "data"
    started = time.monotonic()
    code, log = run(exam, "calibration", now="2026-10-15T12:49:50Z", mode="hang", Day="2026-09-27",
                    DataRoot=data, ModuleSha256=MODULE, timeout=90)
    assert code != 0 and "hard-stopped" in log, log
    assert time.monotonic() - started < 60
    for pid in json.loads(exam["hang"].read_text()).values():
        assert observe_process_identity(pid)["state"] == "not_found"
    record = json.loads(next((exam["root"] / "operator").glob("*.step.json")).read_text())
    assert record["hard_stop"] is True and record["teardown_proved"] is True
    # The lease was released, not poisoned: the next step admits.
    code, log = run(exam, "calibration", Day="2026-09-28", DataRoot=data, ModuleSha256=MODULE)
    assert code == 0, log


def test_script_lives_outside_the_hashed_exam_trees():
    script = repo_path("scripts/ops/maker_replay_exam_step.ps1")
    text = script.read_text(encoding="utf-8-sig")
    assert "Set-Content" not in text and "Out-File" not in text
    # It launches the exam CLIs as children; it never names a source file under src/.
    assert "src\\maker_core" not in text and "src\\weather" not in text
