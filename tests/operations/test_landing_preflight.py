"""Landing preflight: the cumulative-merge gate the workstation runs before handing production a head.

Guards: the landing-preflight contract (Swarm L AGREED §3; COORDINATION rulings R-1, R-2, R-9, R-10, R-11)
and the first-attempt landing traps it exists to catch: a missing ``Guards:`` line (#205), an EOF blank
line (#223), a generated-index-only conflict, a fixture changed by an earlier tip (#189 after #191), and an
advanced script deriving ``-RepoRoot`` from ``$PSScriptRoot`` in ``param()`` (#216/#222).

Fixture repositories are built with git plumbing under ``tmp_path``; git-object logic is real. No test
starts PowerShell (Linux CI runs this module); the ``.ps1`` trap is the static check only. The mutation
table these tests kill lives with the Swarm L preflight record (``l-data/p5/mutations.md``).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from weather.operations import landing_preflight as lp
from weather.operations import landing_preflight_checks as checks
from weather.operations import landing_preflight_rollclass as rollclass
from weather.operations import landing_preflight_routing as routing

CAPTURE_HOST = "c" * 64
WORKSTATION = "d" * 64
BASE_TS = 1_700_000_000

GUARDED_TEST = '"""Guards: fixture contract."""\n'
BASE_FILES: dict[str, str] = {
    "src/weather/__init__.py": "",
    "src/weather/paths.py": "from pathlib import Path\nREPO_ROOT = Path(__file__).resolve().parents[2]\n",
    "src/weather/collection/__init__.py": "",
    "src/weather/collection/snapshot_tracker.py": "from weather import loopdep\n",
    "src/weather/market/__init__.py": "",
    "src/weather/market/market_microstructure.py": "X = 1\n",
    "src/weather/market/execution_tape_capture.py": "X = 1\n",
    "src/weather/operations/__init__.py": "",
    "src/weather/operations/observation_trigger.py": "X = 1\n",
    "src/weather/operations/execution_tape_supervisor.py": "X = 1\n",
    "src/weather/loopdep.py": "LOOP = 1\n",
    "src/weather/free.py": 'MODE = "obs"\n',
    "src/weather/schema_registry_data.py": 'R = (\n    SchemaSpec("a", "a_v1", "m", "active", "x"),\n)\n',
    "config/international_live_execution_host.json": json.dumps({"dedicated_capture_execution_host_id": CAPTURE_HOST}),
    "docs/x.md": "x\n",
    "docs/roadmap/active-backlog.md": "# Backlog\n\nStatus: `OK`\n",
    "docs/operations/STATE_OF_PLAY.md": "# State\n",
    "README.md": "# Fixture\n",
    "tests/__init__.py": "",
    "tests/test_free.py": GUARDED_TEST + "from weather.free import MODE\n\n\ndef test_mode():\n    assert MODE\n",
    "tests/test_hygiene_ratchet.py": GUARDED_TEST + (
        "import ast\nimport pathlib\n\n\ndef test_guards_lines():\n"
        "    root = pathlib.Path(__file__).parent\n"
        "    missing = sorted('tests/' + p.name for p in root.glob('test_*.py')\n"
        "                     if 'Guards:' not in (ast.get_docstring(ast.parse(p.read_text())) or ''))\n"
        "    assert not missing, f'missing Guards: line: {missing}'\n"
    ),
}


# --------------------------------------------------------------------------- fixture repository


def _run_git(repo: Path, *args: str, env: dict[str, str] | None = None, stdin: bytes | None = None) -> str:
    full = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
    full.update({"GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0", **(env or {})})
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=full, input=stdin, check=True)
    return proc.stdout.decode("utf-8").strip()


class FixtureRepo:
    """A caller repository whose commits are written with plumbing (pinned identity and dates)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "caller"
        self.repo.mkdir(parents=True)
        self.scratch = root / "scratch"
        self.tick = 0
        _run_git(self.repo, "init", "-q", "-b", "master")
        for key, value in (("core.autocrlf", "false"), ("commit.gpgsign", "false"), ("user.name", "f"),
                           ("user.email", "f@invalid")):
            _run_git(self.repo, "config", key, value)
        self.base = self.commit(None, BASE_FILES, "base")
        _run_git(self.repo, "update-ref", "refs/heads/master", self.base)
        _run_git(self.repo, "checkout", "-q", "-f", "master")

    def commit(self, parent: str | None, files: dict[str, str | bytes | None], message: str,
               renames: dict[str, str] | None = None, modes: dict[str, str] | None = None) -> str:
        self.tick += 1
        stamp = f"{BASE_TS + 100 * self.tick} +0000"
        index = self.root / f"index-{self.tick}"
        env = {"GIT_INDEX_FILE": str(index), "GIT_AUTHOR_NAME": "f", "GIT_AUTHOR_EMAIL": "f@invalid",
               "GIT_COMMITTER_NAME": "f", "GIT_COMMITTER_EMAIL": "f@invalid",
               "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        if parent:
            _run_git(self.repo, "read-tree", parent, env=env)
        for old, new in (renames or {}).items():
            mode, oid = _run_git(self.repo, "ls-files", "-s", "--", old, env=env).split()[:2]
            _run_git(self.repo, "update-index", "--force-remove", "--", old, env=env)
            _run_git(self.repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{new}", env=env)
        for path, text in files.items():
            if text is None:
                _run_git(self.repo, "update-index", "--force-remove", "--", path, env=env)
                continue
            data = text if isinstance(text, bytes) else text.encode("utf-8")
            oid = _run_git(self.repo, "hash-object", "-w", "--stdin", "--no-filters", stdin=data)
            mode = (modes or {}).get(path, "100644")
            _run_git(self.repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}", env=env)
        for path, mode in (modes or {}).items():
            if path not in files:
                oid = _run_git(self.repo, "rev-parse", f"{parent}:{path}")
                _run_git(self.repo, "update-index", "--cacheinfo", f"{mode},{oid},{path}", env=env)
        tree = _run_git(self.repo, "write-tree", env=env)
        index.unlink(missing_ok=True)
        args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
        return _run_git(self.repo, *args, env=env)

    def state(self) -> list[object]:
        """Everything the preflight must leave untouched in the caller."""

        return [_run_git(self.repo, "rev-parse", "HEAD"), _run_git(self.repo, "status", "--porcelain"),
                _run_git(self.repo, "for-each-ref"), _run_git(self.repo, "worktree", "list", "--porcelain"),
                _run_git(self.repo, "remote", "-v"), _run_git(self.repo, "count-objects", "-v"),
                (self.repo / ".git" / "index").read_bytes()]

    def options(self, head: str, *extra: str, tests: str = "none", out: str = "out.json") -> object:
        return lp.build_parser().parse_args([
            "--head", head, "--repo", str(self.repo), "--base", "master", "--no-fetch",
            "--scratch", str(self.scratch), "--out", str(self.root / out), "--tests", tests,
            "--python", sys.executable, "--disk-floor-gib", "0.01", *extra])

    def plan(self, slots: list[dict[str, object]], name: str = "plan.json") -> Path:
        plan: dict[str, object] = {"schema": lp.NIGHT_PLAN_SCHEMA, "slots": slots}
        plan["plan_sha256"] = lp.plan_content_sha256(plan)
        path = self.root / name
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    def scratch_runs(self) -> list[Path]:
        return list(self.scratch.glob("run-*")) if self.scratch.exists() else []


@pytest.fixture
def fx(tmp_path: Path) -> FixtureRepo:
    return FixtureRepo(tmp_path)


def registry_of(*check_ids: str) -> lp.CheckRegistry:
    """The default registry restricted to ``check_ids`` (registration order kept)."""

    full = lp.default_registry()
    registry = lp.CheckRegistry()
    for spec in full.specs():
        if spec.id in check_ids:
            registry.register(spec)
    return registry


OBJECT_CHECKS = ("roll_class", "landing_path", "diff_check", "schema_additive", "docs_transaction", "whitespace_only")


def run(fx: FixtureRepo, options: object, registry: lp.CheckRegistry | None = None, host: str = WORKSTATION,
        runner: lp.CommandRunner | None = None) -> tuple[int, dict]:
    return lp.run_preflight(options, registry=registry if registry is not None else registry_of(*OBJECT_CHECKS),
                            runner=runner, host_id_fn=lambda: host)


# --------------------------------------------------------------------------- exit 0, determinism, caller untouched


@pytest.mark.spawns
def test_clean_chain_passes_deterministically_and_leaves_caller_untouched(fx):
    a = fx.commit(fx.base, {"src/weather/b.py": "B = 1\n"}, "a")
    b = fx.commit(fx.base, {"docs/y.md": "y\n"}, "b")
    before = fx.state()
    code1, doc1 = run(fx, fx.options(b, "--earlier", f"1@{a}", out="1.json"))
    code2, doc2 = run(fx, fx.options(b, "--earlier", f"1@{a}", out="2.json"))

    assert (code1, code2) == (lp.EXIT_PASS, lp.EXIT_PASS), doc1["verdict"]
    assert doc1["verdict"]["status"] == "PASS"
    assert doc1["landing"]["commit"] == doc2["landing"]["commit"]
    assert doc1["landing"]["tree"] == doc2["landing"]["tree"]
    assert [s["result"] for s in doc1["chain"]] == ["clean", "clean"]
    assert {r["path"]: r["introduced_by"] for r in doc1["landing"]["changed_files"]} == {
        "src/weather/b.py": ["#1"], "docs/y.md": [b]}
    assert doc1["checks"]["import_probe"]["status"] == "PASS"
    assert fx.state() == before
    assert fx.scratch_runs() == []
    assert doc1["cleanup"]["scratch_removed"] is True
    written = json.loads((fx.root / "1.json").read_text(encoding="utf-8"))
    assert written["receipt"]["sha256"] == lp.receipt_digest(written)


@pytest.mark.spawns
def test_keep_scratch_landing_commit_has_two_parents(fx):
    a = fx.commit(fx.base, {"src/weather/b.py": "B = 1\n"}, "a")
    b = fx.commit(fx.base, {"docs/y.md": "y\n"}, "b")
    code, doc = run(fx, fx.options(b, "--earlier", f"1@{a}", "--keep-scratch"))

    assert code == lp.EXIT_PASS
    (run_dir,) = fx.scratch_runs()
    store = run_dir / "store.git"
    landing = doc["landing"]["commit"]
    parents = _run_git(fx.repo, "--git-dir", str(store), "rev-list", "--parents", "-n", "1", landing).split()[1:]
    assert parents == [doc["chain"][0]["synthetic_commit"], b]
    first = _run_git(fx.repo, "--git-dir", str(store), "rev-list", "--parents", "-n", "1",
                     doc["chain"][0]["synthetic_commit"]).split()[1:]
    assert first == [fx.base, a]


# --------------------------------------------------------------------------- exit 3 CONFLICT


@pytest.mark.spawns
def test_conflict_with_an_earlier_head_on_a_later_step_exits_3(fx):
    unrelated = fx.commit(fx.base, {"docs/y.md": "y\n"}, "unrelated")
    earlier = fx.commit(fx.base, {"src/weather/free.py": 'MODE = "earlier"\n'}, "earlier")
    head = fx.commit(fx.base, {"src/weather/free.py": 'MODE = "head"\n'}, "head")
    before = fx.state()
    code, doc = run(fx, fx.options(head, "--earlier", f"1@{unrelated}", "--earlier", f"2@{earlier}"))

    assert code == lp.EXIT_CONFLICT and doc["verdict"]["status"] == "CONFLICT"
    step = doc["chain"][2]
    assert step["result"] == "conflict" and step["conflicts"] == ["src/weather/free.py"]
    assert step["conflicts_fix_class"] == {"src/weather/free.py": "src"}
    pairs = {row["with"]: row["paths"] for row in step["pairwise_conflicts"]}
    assert pairs["base"] == [] and pairs["#2"] == ["src/weather/free.py"] and "#1" not in pairs
    assert doc["checks"]["merge_chain"]["status"] == "FAIL"
    assert doc["checks"]["diff_check"]["status"] == "SKIP"
    assert fx.state() == before and fx.scratch_runs() == []


@pytest.mark.spawns
def test_generated_index_only_conflict_still_exits_3(fx):
    path = "docs/roadmap/active-backlog.md"
    earlier = fx.commit(fx.base, {path: "# Backlog\n\nStatus: `A`\n"}, "earlier")
    head = fx.commit(fx.base, {path: "# Backlog\n\nStatus: `B`\n"}, "head")
    code, doc = run(fx, fx.options(head, "--earlier", f"7@{earlier}"))

    assert code == lp.EXIT_CONFLICT
    assert doc["chain"][-1]["conflicts_fix_class"] == {path: "regenerate_index"}


@pytest.mark.parametrize(("path", "fix_class"), [
    ("docs/roadmap/active-backlog.md", "regenerate_index"),
    ("docs/roadmap/correspondence-index/2026-10.md", "regenerate_index"),
    ("config/location_market_events.json", "generated_config"),
    ("config/foo.generated.json", "generated_config"),
    (".github/workflows/ci.yml", "ci_matrix"),
    ("./.github/workflows/windows-qualification.yml", "ci_matrix"),
    (".gitignore", "docs"),
    ("docs/operations/STATE_OF_PLAY.md", "docs"),
    ("pytest.ini", "tests"),
    ("tests/operations/test_x.py", "tests"),
    ("config/markets.json", "src"),
    ("src/weather/free.py", "src"),
])
def test_conflict_fix_class(path, fix_class):
    assert checks.classify_conflict_path(path) == fix_class


# --------------------------------------------------------------------------- exit 1 FAIL: diff hygiene


@pytest.mark.spawns
@pytest.mark.parametrize(("head_file", "head_text", "kind"), [
    ("docs/x.md", "x  \n", "trailing_whitespace"),
    ("docs/crlf.md", "line\r\n", "trailing_whitespace"),
])
def test_eof_blank_line_and_whitespace_fail_with_step_attribution(fx, head_file, head_text, kind):
    earlier = fx.commit(fx.base, {"README.md": "# Fixture\n\n"}, "earlier: blank line at EOF")
    head = fx.commit(fx.base, {head_file: head_text}, "head: whitespace")
    code, doc = run(fx, fx.options(head, "--earlier", f"early@{earlier}"))

    check = doc["checks"]["diff_check"]
    assert code == lp.EXIT_FAIL and check["status"] == "FAIL"
    assert {a["item"].split(":")[0]: a["introduced_by"] for a in check["attribution"]} == {
        "README.md": "early", head_file: head}
    assert {d["path"]: d["kind"] for d in check["details"]} == {"README.md": "eof_blank_line", head_file: kind}
    assert "diff_check" in doc["verdict"]["failing_checks"]


@pytest.mark.spawns
def test_whitespace_fixed_by_a_later_step_is_a_warning_not_a_failure(fx):
    earlier = fx.commit(fx.base, {"README.md": "# Fixture\n\n"}, "earlier")
    head = fx.commit(earlier, {"README.md": "# Fixture\n"}, "head fixes it")
    code, doc = run(fx, fx.options(head, "--earlier", f"early@{earlier}"))

    assert code == lp.EXIT_PASS
    assert doc["checks"]["diff_check"]["status"] == "WARN"
    assert doc["checks"]["containment"]["details"] == [{"item": "early", "relation": "stacked_on_earlier"}]


# --------------------------------------------------------------------------- exit 2 ERROR and host refusal


@pytest.mark.spawns
def test_capture_host_is_refused_before_any_git_object_is_written(fx):
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")
    before = fx.state()
    code, doc = run(fx, fx.options(head), host=CAPTURE_HOST)

    assert code == lp.EXIT_ERROR and doc["verdict"]["status"] == "ERROR"
    assert doc["checks"]["host_identity"]["status"] == "ERROR"
    assert "capture host" in doc["checks"]["host_identity"]["summary"]
    assert doc["checks"]["merge_chain"]["status"] == "SKIP"
    assert fx.state() == before and fx.scratch_runs() == []


@pytest.mark.spawns
def test_unknown_host_identity_fails_closed(fx):
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")

    def broken() -> str:
        raise OSError("no MachineGuid")

    code, doc = lp.run_preflight(fx.options(head), registry=lp.CheckRegistry(), host_id_fn=broken)
    assert code == lp.EXIT_ERROR and doc["checks"]["host_identity"]["status"] == "ERROR"


@pytest.mark.spawns
def test_expect_head_mismatch_is_an_error(fx):
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")
    code, doc = run(fx, fx.options(head, "--expect-head", fx.base))
    assert code == lp.EXIT_ERROR and doc["checks"]["refs"]["status"] == "ERROR"


@pytest.mark.spawns
def test_a_crashing_check_is_an_error_never_a_pass(fx):
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")
    registry = lp.CheckRegistry()

    def boom(ctx):
        raise ValueError("check crashed")

    registry.register(lp.CheckSpec("boom", lp.PHASE_OBJECTS, boom, "test", ("merge_chain",)))
    code, doc = run(fx, fx.options(head), registry=registry)
    assert code == lp.EXIT_ERROR and doc["checks"]["boom"]["status"] == "ERROR"


# --------------------------------------------------------------------------- night plan binding (R-2, R-3)


@pytest.mark.spawns
def test_night_plan_hash_is_bound_and_tamper_is_refused(fx):
    a = fx.commit(fx.base, {"src/weather/b.py": "B = 1\n"}, "a")
    b = fx.commit(fx.base, {"docs/y.md": "y\n"}, "b")
    slots = [{"kind": "rs", "head": "a", "sha": a, "prs": [1]}, {"kind": "rf", "head": "b", "sha": b, "prs": [2]},
             {"kind": "replay"}]
    path = fx.plan(slots)
    content_sha = lp.plan_content_sha256(json.loads(path.read_text(encoding="utf-8")))

    code, doc = run(fx, fx.options(b, "--night-plan", str(path), "--expect-plan-sha256", content_sha))
    assert code == lp.EXIT_PASS and [s["label"] for s in doc["chain"]] == ["#1", "#2"]
    assert doc["plan_sha256"] == content_sha
    assert doc["inputs"]["plan_file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()

    code, doc = run(fx, fx.options(b, "--night-plan", str(path), "--expect-plan-sha256", "0" * 64))
    assert code == lp.EXIT_ERROR

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["slots"] = list(reversed(tampered["slots"]))
    path.write_text(json.dumps(tampered), encoding="utf-8")
    code, doc = run(fx, fx.options(b, "--night-plan", str(path)))
    assert code == lp.EXIT_ERROR and "plan_sha256" in doc["checks"]["refs"]["summary"]


def test_plan_hash_is_canonical_json_without_its_own_key():
    plan = {"schema": lp.NIGHT_PLAN_SCHEMA, "slots": [{"sha": "a" * 40, "prs": [5]}], "note": "ü"}
    expected = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                              .encode("utf-8")).hexdigest()
    assert lp.plan_content_sha256({**plan, "plan_sha256": "x"}) == expected
    built = lp.plan_from_earlier([f"#12@{'B' * 40}"])
    assert built["slots"] == [{"kind": "earlier", "head": "12", "sha": "b" * 40, "prs": [12]}]
    assert built["plan_sha256"] == lp.plan_content_sha256(built)
    assert lp.landing_slots({"slots": [{"kind": "replay"}, {"sha": "C" * 40}]})[0]["sha"] == "c" * 40
    with pytest.raises(ValueError):
        lp.landing_slots({"slots": [{"sha": "abc"}]})


# --------------------------------------------------------------------------- exit 5 SUPERSEDED and containment (R-1)


@pytest.mark.spawns
def test_head_already_in_base_is_superseded(fx):
    code, doc = run(fx, fx.options(fx.base))
    assert code == lp.EXIT_SUPERSEDED and doc["verdict"]["status"] == "SUPERSEDED"
    assert doc["checks"]["already_landed"]["status"] == "INFO"


@pytest.mark.spawns
def test_earlier_head_containing_this_head_is_superseded(fx):
    a = fx.commit(fx.base, {"src/weather/b.py": "B = 1\n"}, "a")
    a2 = fx.commit(a, {"src/weather/z.py": "Z = 1\n"}, "a2")
    code, doc = run(fx, fx.options(a, "--earlier", f"1@{a2}"))
    assert code == lp.EXIT_SUPERSEDED
    assert doc["checks"]["containment"]["evidence"]["relation"] == "lands_via"


@pytest.mark.spawns
def test_head_stacked_on_an_earlier_head_is_info(fx):
    a = fx.commit(fx.base, {"src/weather/b.py": "B = 1\n"}, "a")
    a2 = fx.commit(a, {"src/weather/z.py": "Z = 1\n"}, "a2")
    code, doc = run(fx, fx.options(a2, "--earlier", f"1@{a}"))
    assert code == lp.EXIT_PASS
    assert doc["checks"]["containment"]["status"] == "INFO"
    assert doc["checks"]["containment"]["details"] == [{"item": "#1", "relation": "stacked_on_earlier"}]


@pytest.mark.spawns
def test_plan_landing_a_head_before_its_own_ancestor_is_order_inverted(fx):
    a = fx.commit(fx.base, {"src/weather/b.py": "B = 1\n"}, "a")
    a2 = fx.commit(a, {"src/weather/z.py": "Z = 1\n"}, "a2")
    path = fx.plan([{"head": "a2", "sha": a2, "prs": [2]}, {"head": "a", "sha": a, "prs": [1]}])
    code, doc = run(fx, fx.options(a2, "--night-plan", str(path)))
    assert code == lp.EXIT_FAIL and doc["checks"]["containment"]["status"] == "FAIL"
    assert [r["relation"] for r in doc["checks"]["containment"]["details"]] == ["order_inverted"]


# --------------------------------------------------------------------------- exit 4 TESTS_NOT_RUN and routing


@pytest.mark.spawns
def test_full_suite_without_the_queue_wrapper_is_tests_not_run(fx):
    head = fx.commit(fx.base, {"src/weather/free.py": 'MODE = "x"\n'}, "head")
    code, doc = run(fx, fx.options(head, tests="full"), registry=registry_of("tests"))
    check = doc["checks"]["tests"]
    assert code == lp.EXIT_TESTS_NOT_RUN and doc["verdict"]["status"] == "TESTS_NOT_RUN"
    assert check["status"] == "NOT_RUN" and check["evidence"]["route"] == "wrapper"


@pytest.mark.spawns
def test_selection_over_the_wrapper_cap_escalates_to_full_never_truncates(fx):
    many = {f"tests/test_gen_{i:03d}.py": GUARDED_TEST + "def test_x():\n    pass\n" for i in range(120)}
    head = fx.commit(fx.base, many, "head adds 120 test files")
    code, doc = run(fx, fx.options(head, tests="affected"), registry=registry_of("tests"))
    check = doc["checks"]["tests"]
    assert check["evidence"]["mode_effective"] == "full"
    assert any("binding cap" in w for w in check["evidence"]["warnings"])
    assert check["evidence"]["route"] == "wrapper" and code == lp.EXIT_TESTS_NOT_RUN


def test_route_for_keeps_direct_runs_inside_the_focused_exemption():
    assert routing.route_for(25, {}, None, False)[0] == "direct"
    assert routing.route_for(26, {}, None, False)[0] == "wrapper"
    assert routing.route_for(1, {"tests/a.py": "marked serial"}, None, False)[0] == "wrapper"
    assert routing.route_for(1, {"tests/a.py": None}, "portable live stage holds the mutex", False)[0] == "wrapper"
    assert routing.route_for(1, {}, None, True) == ("wrapper", "full suite never runs directly")


def test_wrapper_availability_needs_the_landing_tree_queue_switch(tmp_path):
    reason = routing.wrapper_available(tmp_path)
    assert reason is not None
    if os.name == "nt":
        assert "absent" in reason


def test_ratchet_selection_from_ci_yml_and_static_fallback(tmp_path):
    (tmp_path / "tests" / "operations").mkdir(parents=True)
    for name in ("tests/test_hygiene_ratchet.py", "tests/operations/test_schema_registry.py", "tests/test_b.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert routing.ratchet_selection(tmp_path) == (
        ["tests/operations/test_schema_registry.py", "tests/test_hygiene_ratchet.py"], [], "static list")
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    ratchet: cheap gate\n", encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("jobs:\n  audit:\n    steps:\n      - run: >-\n          python -m pytest -q -m ratchet\n"
                        "          tests/test_b.py tests/test_missing.py\n      - run: echo done\n", encoding="utf-8")
    assert routing.ci_ratchet_files(workflow) == ["tests/test_b.py", "tests/test_missing.py"]
    assert routing.ratchet_selection(tmp_path) == (["tests/test_b.py"], ["-m", "ratchet"], "ci.yml -m ratchet")


def test_serial_and_powershell_files_never_join_a_direct_run(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_serial.py").write_text("import pytest\npytestmark = pytest.mark.serial\n", encoding="utf-8")
    (tests / "helper_ps.py").write_text("import subprocess\nEXE = 'powershell.exe'\n", encoding="utf-8")
    (tests / "test_via_helper.py").write_text("from tests import helper_ps\n", encoding="utf-8")
    (tests / "test_plain.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    assert "marked serial" in routing.serial_reason_fallback(tmp_path, "tests/test_serial.py")
    assert "helper_ps.py" in routing.serial_reason_fallback(tmp_path, "tests/test_via_helper.py")
    assert routing.serial_reason_fallback(tmp_path, "tests/test_plain.py") is None


def test_parse_junit_and_fallback_selection(tmp_path):
    junit = tmp_path / "j.xml"
    junit.write_text('<testsuite><testcase classname="tests.test_a" name="test_ok"/>'
                     '<testcase classname="tests.test_a" name="test_bad" file="tests/test_a.py">'
                     '<failure message="boom"/></testcase><testcase classname="tests.test_a" name="test_s">'
                     '<skipped/></testcase></testsuite>', encoding="utf-8")
    parsed = routing.parse_junit(junit, tmp_path)
    assert parsed["tests"] == 3 and parsed["skipped"] == 1
    assert parsed["failures"] == [{"nodeid": "tests/test_a.py::test_bad", "file": "tests/test_a.py",
                                   "kind": "failure", "message": "boom"}]
    assert routing.parse_junit(tmp_path / "absent.xml", tmp_path)["present"] is False
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_user.py").write_text("from weather.free import MODE\n", encoding="utf-8")
    (tmp_path / "tests" / "test_other.py").write_text("import json\n", encoding="utf-8")
    picked = routing.fallback_selection(tmp_path, ["src/weather/free.py", "tests/conftest.py"])
    assert [row["file"] for row in picked["tests"]] == ["tests/test_user.py"]
    assert picked["full_suite"] is True and picked["full_suite_reasons"] == ["tests/conftest.py"]


# --------------------------------------------------------------------------- brief traps: Guards line, interaction


def _scripted_runner(calls: list[list[str]]) -> lp.CommandRunner:
    def runner(argv, **kwargs):
        calls.append(list(argv))
        return lp.run_command(argv, **kwargs)
    return runner


@pytest.mark.spawns
def test_missing_guards_line_fails_the_ratchets_and_names_the_head(fx):
    head = fx.commit(fx.base, {"tests/test_new.py": "def test_new():\n    assert True\n"}, "head without Guards")
    calls: list[list[str]] = []
    code, doc = run(fx, fx.options(head), registry=registry_of("ratchets"), runner=_scripted_runner(calls))

    check = doc["checks"]["ratchets"]
    assert code == lp.EXIT_FAIL and check["status"] == "FAIL", check["summary"]
    assert check["evidence"]["route"] == "direct" and check["evidence"]["files"] == ["tests/test_hygiene_ratchet.py"]
    assert check["attribution"] == [{"item": "tests/test_hygiene_ratchet.py::test_guards_lines",
                                     "introduced_by": head}]
    pytest_argv = next(c for c in calls if c[1:3] == ["-m", "pytest"])
    assert any(arg.startswith("--basetemp=") for arg in pytest_argv) and "-p" in pytest_argv


@pytest.mark.spawns
def test_fixture_changed_by_an_earlier_tip_is_an_interaction_failure(fx):
    earlier = fx.commit(fx.base, {
        "tests/fixtures/keying.json": '{"keying": "obs"}\n',
        "tests/test_keying.py": GUARDED_TEST + (
            "import json\nimport pathlib\n\nfrom weather.free import MODE\n\n\ndef test_keying_matches_fixture():\n"
            "    data = json.loads((pathlib.Path(__file__).parent / 'fixtures' / 'keying.json').read_text())\n"
            "    assert MODE == data['keying']\n")}, "earlier (#191 shape)")
    head = fx.commit(fx.base, {"src/weather/free.py": 'MODE = "report_time"\n'}, "head (#189 shape)")
    code, doc = run(fx, fx.options(head, "--earlier", f"191@{earlier}", tests="affected"),
                    registry=registry_of("tests"))

    check = doc["checks"]["tests"]
    assert code == lp.EXIT_FAIL and check["status"] == "FAIL", check["summary"]
    assert "tests/test_keying.py" in check["evidence"]["files"]
    (failure,) = check["details"]
    assert failure["nodeid"] == "tests/test_keying.py::test_keying_matches_fixture"
    assert failure["class"] == "interaction" and failure["introduced_by"] == ["#191"]
    assert doc["landing"]["pre_head_commit"] == doc["chain"][0]["synthetic_commit"]


# --------------------------------------------------------------------------- brief trap: -RepoRoot from $PSScriptRoot


ADVANCED_BAD = "[CmdletBinding()]\nparam(\n  [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)\n)\n"


def test_ps1_param_default_detector_static():
    good = ("[CmdletBinding()]\nparam(\n  [string]$RepoRoot = \"\"\n)\n"
            "if (-not $RepoRoot) { $RepoRoot = Split-Path $PSCommandPath }\n")
    simple = "param(\n  [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)\n)\n"
    commented = "[CmdletBinding()]\nparam(\n  # $PSScriptRoot is empty here\n  [string]$RepoRoot = \"\"\n)\n"
    assert checks.ps1_param_default_offender(ADVANCED_BAD)
    assert not checks.ps1_param_default_offender(good)
    assert not checks.ps1_param_default_offender(simple)
    assert not checks.ps1_param_default_offender(commented)


@pytest.mark.spawns
def test_changed_advanced_script_with_psscriptroot_default_warns_then_fails_after_222(fx):
    script = "scripts/ops/new_tool" + ".ps1"
    head = fx.commit(fx.base, {script: ADVANCED_BAD}, "head adds an advanced script")
    code, doc = run(fx, fx.options(head), registry=registry_of("ps1_param_defaults"))
    check = doc["checks"]["ps1_param_defaults"]
    assert check["status"] == "WARN" and check["evidence"]["touched_offenders"] == [script]
    assert check["attribution"] == [{"item": script, "introduced_by": head}] and code == lp.EXIT_PASS

    post = fx.commit(head, {checks.PS1_RATCHET_TEST: GUARDED_TEST}, "after #222")
    code, doc = run(fx, fx.options(post), registry=registry_of("ps1_param_defaults"))
    assert code == lp.EXIT_FAIL and doc["checks"]["ps1_param_defaults"]["status"] == "FAIL"


# --------------------------------------------------------------------------- roll class (non-binding) and landing path


@pytest.mark.spawns
@pytest.mark.parametrize(("files", "expected", "route", "sensitive"), [
    ({"src/weather/loopdep.py": "LOOP = 2\n"}, "EXPECTED-ROLL-SENSITIVE", "ROLL_SENSITIVE", ["src/weather/loopdep.py"]),
    ({"src/weather/free.py": 'MODE = "y"\n'}, "EXPECTED-ROLL-FREE", "ROLL_FREE_GUARDED", []),
    ({"docs/y.md": "y\n"}, "EXPECTED-ROLL-FREE", "DOCS_LIGHT", []),
    ({"src/weather/schema_registry_data.py": 'R = ()\n'}, "EXPECTED-ROLL-SENSITIVE", "ROLL_SENSITIVE",
     ["src/weather/schema_registry_data.py"]),
])
def test_roll_class_prediction_and_landing_path(fx, files, expected, route, sensitive):
    head = fx.commit(fx.base, files, "head")
    code, doc = run(fx, fx.options(head))
    roll, path = doc["checks"]["roll_class"], doc["checks"]["landing_path"]
    assert roll["evidence"]["expected"] == expected and roll["evidence"]["binding"] is False
    assert roll["evidence"]["sensitive_files"] == sensitive
    assert path["evidence"]["path"] == route and path["evidence"]["binding"] is False
    assert roll["evidence"]["light_path_eligible"] is (route == "DOCS_LIGHT")
    assert roll["status"] == "WARN"  # no --closure-snapshot: static graph only is always WARNed
    assert code == lp.EXIT_PASS  # roll class never blocks


@pytest.mark.spawns
def test_stale_snapshot_is_undecidable_and_declared_roll_free_mismatch_warns(fx):
    head = fx.commit(fx.base, {"src/weather/free.py": 'MODE = "y"\n'}, "head")
    snapshot = fx.root / "closure.json"
    snapshot.write_text(json.dumps({"captured_local": "2026-09-01T00:00:00", "union_files": []}), encoding="utf-8")
    options = fx.options(head, "--closure-snapshot", str(snapshot), "--declared-roll-class", "DOCS_LIGHT")
    options.rollclass_as_of = "2026-10-05T12:00:00"
    code, doc = run(fx, options)
    roll = doc["checks"]["roll_class"]
    assert roll["evidence"]["expected"] == "EXPECTED-UNDECIDABLE" and roll["status"] == "WARN"
    assert roll["evidence"]["snapshot"]["stale"] is True
    assert any("declared DOCS_LIGHT" in w for w in roll["evidence"]["warnings"])
    assert doc["checks"]["landing_path"]["evidence"]["path"] == "ROLL_SENSITIVE"
    assert doc["closure_snapshot_sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()

    options = fx.options(head, "--closure-snapshot", str(snapshot), "--no-execution-tape")
    options.rollclass_as_of = "2026-09-03T12:00:00"
    code, doc = run(fx, options)
    assert doc["checks"]["roll_class"]["evidence"]["expected"] == "EXPECTED-ROLL-FREE"
    assert doc["checks"]["roll_class"]["evidence"]["execution_tape_entries"] == []


@pytest.mark.spawns
@pytest.mark.parametrize(("text", "status", "check_status"), [
    ('R = (\n    SchemaSpec("a", "a_v1", "m", "active", "x"),\n    SchemaSpec("b", "b_v1", "m", "active", "y"),\n)\n',
     "ADDITIVE", "INFO"),
    ('R = (\n    SchemaSpec("b", "b_v1", "m", "active", "y"),\n)\n', "NOT_ADDITIVE", "WARN"),
])
def test_schema_additive_uses_the_single_rollclass_implementation(fx, text, status, check_status):
    head = fx.commit(fx.base, {"src/weather/schema_registry_data.py": text}, "head")
    code, doc = run(fx, fx.options(head))
    check = doc["checks"]["schema_additive"]
    assert check["status"] == check_status and check["evidence"]["status"] == status
    assert check["evidence"]["implementation"] == "landing_preflight_rollclass.schema_additive_between"
    assert doc["checks"]["roll_class"]["evidence"]["schema_additive"]["status"] == status
    assert not hasattr(checks, "schema_entries") and not hasattr(checks, "classify_schema_change")


# --------------------------------------------------------------------------- whitespace_only (M13 evidence)


def _blank_eof_base(fx: FixtureRepo) -> str:
    files = {f"docs/ws/{i:02d}.md": f"line {i}\n\n" for i in range(37)}
    files["scripts/ops/tool.ps1"] = "Write-Output 1\n\n"
    files["src/weather/loopdep.py"] = "LOOP = 1\n\n"
    return fx.commit(fx.base, files, "files ending in a blank line")


@pytest.mark.spawns
def test_whitespace_only_true_for_37_trailing_blank_line_deletions(fx):
    base = _blank_eof_base(fx)
    _run_git(fx.repo, "update-ref", "refs/heads/master", base)
    head = fx.commit(base, {f"docs/ws/{i:02d}.md": f"line {i}\n" for i in range(37)}, "drop EOF blank lines")
    code, doc = run(fx, fx.options(head))
    check = doc["checks"]["whitespace_only"]
    assert check["status"] == "INFO" and check["evidence"]["whitespace_only"] is True, check["summary"]
    assert (check["evidence"]["file_count"], check["evidence"]["lines_deleted"], check["evidence"]["lines_added"]) == (
        37, 37, 0)
    assert code == lp.EXIT_PASS


@pytest.mark.spawns
@pytest.mark.parametrize(("case", "reason", "path"), [
    ("ps1_content", "non_whitespace_change", "scripts/ops/tool.ps1"),
    ("added", "added", "docs/new.md"),
    ("renamed", "renamed", "docs/ws/00.md -> docs/ws/renamed.md"),
    ("roll_sensitive", "roll_class_expected-roll-sensitive", ""),
    ("diff_check_hit", "diff_check_fail", "docs/ws/01.md"),
])
def test_whitespace_only_disqualifiers_name_the_path(fx, case, reason, path):
    base = _blank_eof_base(fx)
    _run_git(fx.repo, "update-ref", "refs/heads/master", base)
    files: dict[str, str | None] = {f"docs/ws/{i:02d}.md": f"line {i}\n" for i in range(2, 37)}
    renames = None
    if case == "ps1_content":
        files["scripts/ops/tool.ps1"] = "Write-Output 2\n\n"
    elif case == "added":
        files["docs/new.md"] = "new\n"
    elif case == "renamed":
        renames = {"docs/ws/00.md": "docs/ws/renamed.md"}
    elif case == "roll_sensitive":
        files["src/weather/loopdep.py"] = "LOOP = 1\n"
    elif case == "diff_check_hit":
        files["docs/ws/01.md"] = "line 1   \n\n"
    head = fx.commit(base, files, f"whitespace plus {case}", renames=renames)
    code, doc = run(fx, fx.options(head))
    check = doc["checks"]["whitespace_only"]
    assert check["evidence"]["whitespace_only"] is False
    rows = [(d["reason"], d["path"]) for d in check["evidence"]["disqualifiers"]]
    assert (reason, path) in rows, rows
    assert check["summary"].startswith("false:")


# --------------------------------------------------------------------------- docs transaction, dry run, cleanup, env


@pytest.mark.spawns
def test_docs_transaction_binds_the_final_planned_tip(fx):
    sop = "docs/operations/STATE_OF_PLAY.md"
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")
    later = fx.commit(head, {sop: "# State\nlater edit\n"}, "later docs tip")
    path = fx.plan([{"head": "h", "sha": head, "prs": [1]}, {"head": "l", "sha": later, "prs": [2]}])
    code, doc = run(fx, fx.options(head, "--night-plan", str(path)))
    check = doc["checks"]["docs_transaction"]
    rows = {r["path"]: r for r in check["evidence"]["documents"]}
    assert check["status"] == "WARN" and rows[sop]["stale_if_bound_at_this_head"] is True
    assert rows[sop]["final_tip_oid"] == _run_git(fx.repo, "rev-parse", f"{later}:{sop}")
    assert rows[sop]["landing_oid"] == _run_git(fx.repo, "rev-parse", f"{fx.base}:{sop}")


@pytest.mark.spawns
def test_dry_run_executes_no_check_and_creates_no_scratch(fx):
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")
    calls: list[list[str]] = []
    code, doc = run(fx, fx.options(head, "--dry-run"), registry=lp.default_registry(), runner=_scripted_runner(calls))
    assert code == lp.EXIT_PASS and doc["dry_run"] is True and calls == []
    assert fx.scratch_runs() == []
    assert [c["id"] for c in doc["phases"]["objects"]][:2] == ["roll_class", "landing_path"]
    assert "whitespace_only" in [c["id"] for c in doc["phases"]["objects"]]


@pytest.mark.spawns
def test_interrupt_inside_a_check_still_removes_the_scratch_and_spares_the_caller(fx):
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")
    before = fx.state()
    registry = lp.CheckRegistry()

    def interrupted(ctx):
        raise KeyboardInterrupt

    registry.register(lp.CheckSpec("interrupt", lp.PHASE_OBJECTS, interrupted, "test", ("merge_chain",)))
    with pytest.raises(KeyboardInterrupt):
        run(fx, fx.options(head), registry=registry)
    assert fx.scratch_runs() == [] and fx.state() == before


def test_child_environment_is_scrubbed_and_offline():
    env, removed = lp.scrubbed_child_env({"GH_TOKEN": "x", "POLYMARKET_KEY": "x", "MY_SECRET": "x", "PATH": "p",
                                          "WEATHER_DATA_ROOT": "d", "GIT_DIR": "g", "HTTPS_PROXY": "h"}, Path("w"))
    assert set(removed) == {"GH_TOKEN", "POLYMARKET_KEY", "MY_SECRET", "WEATHER_DATA_ROOT", "GIT_DIR", "HTTPS_PROXY"}
    assert env["PATH"] == "p" and env["WEATHER_INTEGRATION_TEST_OFFLINE"] == "1" and env["GIT_TERMINAL_PROMPT"] == "0"


def test_verdict_precedence():
    r = lp.CheckResult
    assert lp.decide_verdict({"a": r("FAIL"), "b": r("ERROR")})[0] == "FAIL"
    assert lp.decide_verdict({"a": r("PASS"), "b": r("ERROR")})[0] == "ERROR"
    assert lp.decide_verdict({"a": r("NOT_RUN"), "b": r("WARN")})[0] == "TESTS_NOT_RUN"
    assert lp.decide_verdict({"a": r("WARN"), "b": r("INFO")}) == ("PASS", [], ["a"])
    assert lp.decide_verdict({"a": r("FAIL")}, "CONFLICT")[0] == "CONFLICT"
    assert lp.decide_verdict({"a": r("PASS")}, "SUPERSEDED")[0] == "SUPERSEDED"
    assert sorted(lp.VERDICT_EXIT_CODES.values()) == [0, 1, 2, 3, 4, 5]


def test_cli_accepts_the_roll_class_options():
    options = lp.build_parser().parse_args(["--head", "h", "--no-execution-tape", "--declared-roll-class", "RF"])
    assert options.no_execution_tape is True and options.declared_roll_class == "RF"
    assert rollclass.normalize_declared("roll-free") == "EXPECTED-ROLL-FREE"


def test_shard_plan_parser_reads_folded_file_lists():
    text = "jobs:\n  w:\n    strategy:\n      matrix:\n        include:\n          - name: a\n            files: >-\n" \
           "              tests/a/test_one.py\n              tests/a/test_two.py\n          - name: b\n" \
           "            files: >-\n              tests/b/test_three.py\n"
    assert checks.shard_plan_files(text) == ["tests/a/test_one.py", "tests/a/test_two.py", "tests/b/test_three.py"]
