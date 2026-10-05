"""Landing preflight: judge a head on the night's cumulative merge before handover.

The workstation runs this before handing production a head.  It merges current
``origin/master`` with every head scheduled earlier the same night and then the
head itself, as deterministic two-parent synthetic commits in a scratch object
store, checks out the landing commit in a detached scratch worktree, runs the
registered checks against it and writes a ``landing_preflight_v0.1`` verdict.

It never modifies the caller's checkout, index, ``HEAD``, branches or remotes
(the scratch store borrows the caller's objects through ``alternates``), never
takes the capture-host lease and refuses to run on the dedicated capture host.
The verdict is pre-evidence only: production's own gates still bind.

Exit codes: 0 PASS, 1 FAIL, 2 ERROR, 3 CONFLICT, 4 TESTS_NOT_RUN, 5 SUPERSEDED.

Check runners plug in through :class:`CheckRegistry` (see ``default_registry``);
each returns a :class:`CheckResult` with a status, attribution and evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import REPO_ROOT

SCHEMA = "landing_preflight_v0.1"
NIGHT_PLAN_SCHEMA = "landing_night_plan_v0.1"

EXIT_PASS, EXIT_FAIL, EXIT_ERROR, EXIT_CONFLICT, EXIT_TESTS_NOT_RUN, EXIT_SUPERSEDED = range(6)
VERDICT_EXIT_CODES = {
    "PASS": EXIT_PASS,
    "FAIL": EXIT_FAIL,
    "ERROR": EXIT_ERROR,
    "CONFLICT": EXIT_CONFLICT,
    "TESTS_NOT_RUN": EXIT_TESTS_NOT_RUN,
    "SUPERSEDED": EXIT_SUPERSEDED,
}

# Check statuses.  FAIL, ERROR and NOT_RUN decide the verdict; WARN is listed;
# INFO is evidence only; SKIP means a prerequisite did not pass.
PASS, FAIL, WARN, SKIP, ERROR, INFO, NOT_RUN = "PASS", "FAIL", "WARN", "SKIP", "ERROR", "INFO", "NOT_RUN"
CHECK_STATUSES = frozenset({PASS, FAIL, WARN, SKIP, ERROR, INFO, NOT_RUN})
_SATISFIED = frozenset({PASS, WARN, INFO})

# Phases a registered check may run in, in order.
PHASE_OBJECTS = "objects"    # after merge_chain; git objects only, ctx.worktree is None
PHASE_WORKTREE = "worktree"  # after import_probe; ctx.worktree is the landing checkout
PHASE_TESTS = "tests"        # heavy phase (direct focused run or workstation_heavy -Queue)
PHASES = (PHASE_OBJECTS, PHASE_WORKTREE, PHASE_TESTS)

# Check ids owned by this core module; plug-ins may not register them.
CORE_CHECK_IDS = (
    "host_identity", "git_version", "disk_floor", "refs", "already_landed",
    "containment", "merge_chain", "worktree", "import_probe",
)

MIN_GIT_VERSION = (2, 38)
DISK_FLOOR_BYTES = 10 * 1024**3
GIT_TIMEOUT_SECONDS = 900
SYNTHETIC_IDENTITY = ("landing-preflight", "landing-preflight@invalid")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EARLIER = re.compile(r"^(?P<label>[^@\s]+)@(?P<sha>[0-9a-fA-F]{40})$")

# Child-environment scrub: the same name rules as bounded_worktree_test_suite.ps1
# (Test-WeatherQualificationSensitiveEnvironmentName and the ambient git names).
_SENSITIVE_EXACT = frozenset({
    "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL",
    "GH_TOKEN", "GITHUB_TOKEN", "HF_TOKEN", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "NO_PROXY", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS", "PIP_CERT", "PIP_PROXY", "PIP_TRUSTED_HOST", "SSH_AUTH_SOCK",
    "GIT_ASKPASS", "SSH_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND",
})
_SENSITIVE_PREFIX = re.compile(r"^(POLYMARKET_|POLYMM_|OPENAI_|ANTHROPIC_|CLOUDFLARE_|AWS_|AZURE_|GOOGLE_|GCM_|GIT_SSL_)")
_SENSITIVE_WORD = re.compile(
    r"(?:^|_)(?:TOKEN|PASSWORD|PASSWD|SECRET|PRIVATE_KEY|API_KEY|ACCESS_KEY|CLIENT_SECRET|"
    r"CREDENTIALS?|CONNECTION_STRING|URL|URI|DSN|AUTH|COOKIE|KEY|CERT)(?:$|_)"
)
_AMBIENT_EXACT = frozenset({
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "CURL_CA_BUNDLE",
    "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "PAGER", "EDITOR", "VISUAL",
    "LC_ALL", "LANG", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONSAFEPATH",
})
KEPT_SENSITIVE_NAMES = frozenset({"WEATHER_INTEGRATION_TEST_SECRET_POLICY"})


def is_sensitive_env_name(name: str) -> bool:
    upper = name.upper()
    if upper in KEPT_SENSITIVE_NAMES:
        return False
    return bool(upper in _SENSITIVE_EXACT or _SENSITIVE_PREFIX.match(upper) or _SENSITIVE_WORD.search(upper))


def is_ambient_env_name(name: str) -> bool:
    upper = name.upper()
    return upper.startswith(("GIT_", "GCM_", "SSH_")) or upper in _AMBIENT_EXACT


def scrubbed_child_env(base: dict[str, str], worktree: Path | None) -> tuple[dict[str, str], list[str]]:
    """Return the offline child environment and the (sorted) names removed."""

    env: dict[str, str] = {}
    removed: list[str] = []
    for name, value in base.items():
        upper = name.upper()
        drop = is_sensitive_env_name(name) or is_ambient_env_name(name)
        if upper.startswith("WEATHER_") and upper not in KEPT_SENSITIVE_NAMES:
            drop = True  # caller overrides must not redirect branch code
        if drop:
            removed.append(name)
        else:
            env[name] = value
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1",
        "WEATHER_INTEGRATION_TEST_OFFLINE": "1",
    })
    if worktree is not None:
        env["PYTHONPATH"] = os.pathsep.join([str(worktree / "src"), str(worktree)])
    return env, sorted(removed)


# --------------------------------------------------------------------------- interface


class PreflightAbort(Exception):
    """Raised by a core phase to stop the run with a terminal verdict."""

    def __init__(self, check_id: str, status: str, summary: str, verdict: str, **evidence: Any):
        super().__init__(summary)
        self.check_id, self.status, self.summary, self.verdict, self.evidence = check_id, status, summary, verdict, evidence


@dataclass
class CheckResult:
    """What a check returns.  ``attribution`` rows are ``{item, introduced_by}``."""

    status: str
    summary: str = ""
    details: list[Any] = field(default_factory=list)
    attribution: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    command: list[str] | None = None
    exit_code: int | None = None
    output_tail: str = ""
    duration_s: float = 0.0
    owner: str = "core"

    def __post_init__(self) -> None:
        if self.status not in CHECK_STATUSES:
            raise ValueError(f"unknown check status {self.status!r}")


@dataclass(frozen=True)
class CheckSpec:
    """A named check.  ``run(ctx)`` must not mutate the caller's repository."""

    id: str
    phase: str
    run: Callable[["PreflightContext"], CheckResult]
    owner: str
    requires: tuple[str, ...] = ()
    description: str = ""


class CheckRegistry:
    """Ordered registry of named checks; registration order is run order within a phase."""

    def __init__(self) -> None:
        self._specs: dict[str, CheckSpec] = {}

    def register(self, spec: CheckSpec) -> None:
        if spec.phase not in PHASES:
            raise ValueError(f"check {spec.id!r}: unknown phase {spec.phase!r}")
        if spec.id in CORE_CHECK_IDS or spec.id in self._specs or spec.id in ("verdict", "receipt"):
            raise ValueError(f"check id {spec.id!r} is already taken")
        self._specs[spec.id] = spec

    def specs(self, phase: str | None = None) -> list[CheckSpec]:
        return [s for s in self._specs.values() if phase is None or s.phase == phase]

    def ids(self) -> list[str]:
        return list(self._specs)


@dataclass
class CommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False

    def tail(self, limit: int = 4000) -> str:
        text = (self.stdout or "") + (("\n" + self.stderr) if self.stderr else "")
        return text[-limit:]


CommandRunner = Callable[..., CommandResult]


def run_command(argv: Sequence[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
                timeout: float | None = None, input_text: str | None = None) -> CommandResult:
    """Run one child process with captured UTF-8 output; never raises on exit status."""

    started = time.monotonic()
    try:
        proc = subprocess.run(
            list(argv), cwd=str(cwd) if cwd else None, env=env, input=input_text,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return CommandResult(list(argv), 124, out, "timeout", time.monotonic() - started, True)
    except OSError as exc:
        return CommandResult(list(argv), 127, "", str(exc), time.monotonic() - started)
    return CommandResult(list(argv), proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)


@dataclass
class ChainStep:
    step: int
    label: str
    sha: str
    role: str  # "earlier" | "head"
    result: str = "pending"  # clean | conflict | already_in_chain | skipped
    conflicts: list[str] = field(default_factory=list)
    conflicts_fix_class: dict[str, str] = field(default_factory=dict)
    pairwise_conflicts: list[dict[str, Any]] = field(default_factory=list)
    tree: str | None = None
    synthetic_commit: str | None = None
    prs: list[Any] = field(default_factory=list)
    known_fix: Any = None


@dataclass
class PreflightContext:
    """Everything a check may read.  Fields are filled as the core phases advance."""

    repo: Path                      # caller repository (read-only)
    options: argparse.Namespace
    scratch_root: Path
    run_dir: Path
    git_dir: Path | None = None     # scratch bare store (alternates -> caller objects)
    git_version: str = ""
    plan: dict[str, Any] = field(default_factory=dict)
    plan_sha256: str | None = None
    base_ref: str = ""
    base_sha: str = ""
    head_ref: str = ""
    head_sha: str = ""
    earlier: list[dict[str, Any]] = field(default_factory=list)   # [{label, sha, prs, known_fix, ...}]
    chain: list[ChainStep] = field(default_factory=list)
    base_tree: str | None = None
    landing_tree: str | None = None
    landing_commit: str | None = None
    pre_head_commit: str | None = None   # chain commit before the head step (F6 test base)
    changed_files: list[dict[str, Any]] = field(default_factory=list)
    worktree: Path | None = None
    python: str = ""
    child_env: dict[str, str] = field(default_factory=dict)
    results: dict[str, CheckResult] = field(default_factory=dict)
    runner: CommandRunner = run_command
    commands: list[list[str]] = field(default_factory=list)

    def run(self, argv: Sequence[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
            timeout: float | None = None) -> CommandResult:
        """Run a child with the scrubbed environment (default) and the check timeout."""

        self.commands.append(list(argv))
        return self.runner(argv, cwd=cwd or self.worktree, env=env if env is not None else self.child_env,
                           timeout=timeout if timeout is not None else self.options.check_timeout_seconds)

    def git(self, *args: str, check: bool = True, env_extra: dict[str, str] | None = None) -> CommandResult:
        """Run git against the scratch store (object reads/writes, never the caller's refs)."""

        if self.git_dir is None:
            raise RuntimeError("scratch store is not initialised")
        return _git(["--git-dir", str(self.git_dir), *args], check=check, env_extra=env_extra)


def _git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                                                                              "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT"))}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "LC_ALL": "C"})
    env.update(extra or {})
    return env


def _git(args: Sequence[str], *, cwd: Path | None = None, check: bool = True,
         env_extra: dict[str, str] | None = None) -> CommandResult:
    argv = ["git", "-c", "core.quotepath=false", *args]
    result = run_command(argv, cwd=cwd, env=_git_env(env_extra), timeout=GIT_TIMEOUT_SECONDS)
    if check and result.exit_code != 0:
        raise RuntimeError(f"{' '.join(argv)} exited {result.exit_code}: {result.tail(800)}")
    return result


def _caller_git(ctx: PreflightContext, *args: str, check: bool = True) -> CommandResult:
    """Read-only git against the caller repository (rev-parse, merge-base, fetch)."""

    return _git(["-C", str(ctx.repo), *args], check=check)


# --------------------------------------------------------------------------- night plan


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def plan_content_sha256(plan: dict[str, Any]) -> str:
    """The embedded ``plan_sha256``: canonical JSON of the plan without that key."""

    return hashlib.sha256(canonical_json_bytes({k: v for k, v in plan.items() if k != "plan_sha256"})).hexdigest()


def _slot_label(slot: dict[str, Any]) -> str:
    prs = slot.get("prs") or []
    if prs:
        return "+".join(f"#{p}" for p in prs)
    return str(slot.get("head") or slot.get("sha"))


def landing_slots(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Slots that land a head: those carrying a 40-hex ``sha``, in plan order."""

    slots = plan.get("slots")
    if not isinstance(slots, list):
        raise ValueError("night plan has no 'slots' list")
    rows = []
    for slot in slots:
        if not isinstance(slot, dict) or slot.get("sha") in (None, ""):
            continue
        sha = str(slot["sha"]).lower()
        if not _SHA40.match(sha):
            raise ValueError(f"night plan slot sha is not 40 hex: {slot.get('sha')!r}")
        rows.append({**slot, "sha": sha, "label": _slot_label(slot)})
    return rows


def load_night_plan(path: Path, expect_sha256: str | None) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()
    if expect_sha256 and expect_sha256.lower() != file_sha:
        raise ValueError(f"night plan sha256 {file_sha} != --expect-plan-sha256 {expect_sha256}")
    plan = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(plan, dict) or plan.get("schema") != NIGHT_PLAN_SCHEMA:
        raise ValueError(f"night plan schema must be {NIGHT_PLAN_SCHEMA}")
    embedded = plan.get("plan_sha256")
    if embedded is not None and embedded != plan_content_sha256(plan):
        raise ValueError("night plan's embedded plan_sha256 does not match its content")
    landing_slots(plan)
    return plan, file_sha


def plan_from_earlier(entries: Sequence[str]) -> dict[str, Any]:
    """Build a plan from ``--earlier n@sha`` entries (the convenience form of ``--night-plan``)."""

    slots = []
    for entry in entries:
        match = _EARLIER.match(entry.strip())
        if not match:
            raise ValueError(f"--earlier must be <label>@<sha40>, got {entry!r}")
        label = match["label"].lstrip("#")
        slot: dict[str, Any] = {"kind": "earlier", "head": label, "sha": match["sha"].lower()}
        slot["prs"] = [int(label)] if label.isdigit() else []
        slots.append(slot)
    plan: dict[str, Any] = {"schema": NIGHT_PLAN_SCHEMA, "source": "landing_preflight --earlier", "slots": slots}
    plan["plan_sha256"] = plan_content_sha256(plan)
    return plan


# --------------------------------------------------------------------------- core phases


def default_host_id() -> str:
    from weather.execution_host import current_execution_host_id

    return current_execution_host_id()


def _phase_host_identity(ctx: PreflightContext, host_id_fn: Callable[[], str]) -> CheckResult:
    path = Path(ctx.options.host_assignment) if ctx.options.host_assignment else ctx.repo / "config" / "international_live_execution_host.json"
    try:
        assignment = json.loads(path.read_text(encoding="utf-8"))
        capture_id = str(assignment["dedicated_capture_execution_host_id"])
        if not _HEX64.match(capture_id):
            raise ValueError("dedicated_capture_execution_host_id is not 64 hex")
        host_id = host_id_fn()
    except Exception as exc:  # fail closed: an unknown host is not a workstation
        raise PreflightAbort("host_identity", ERROR, f"host identity unavailable: {exc}", "ERROR")
    if host_id == capture_id:
        raise PreflightAbort("host_identity", ERROR, "refused: this is the dedicated capture host", "ERROR",
                             assignment=str(path))
    return CheckResult(PASS, "not the dedicated capture host", evidence={"assignment": str(path)})


def _parse_git_version(text: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\.(\d+)", text)
    return (int(match[1]), int(match[2])) if match else (0, 0)


def _phase_git_version(ctx: PreflightContext) -> CheckResult:
    result = _git(["--version"], check=False)
    ctx.git_version = result.stdout.strip()
    if result.exit_code != 0 or _parse_git_version(ctx.git_version) < MIN_GIT_VERSION:
        raise PreflightAbort("git_version", ERROR, f"git >= 2.38 required, found {ctx.git_version!r}", "ERROR")
    return CheckResult(PASS, ctx.git_version)


def _phase_disk_floor(ctx: PreflightContext) -> CheckResult:
    probe = ctx.scratch_root
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    floor = ctx.options.disk_floor_gib * 1024**3
    if free < floor:
        raise PreflightAbort("disk_floor", ERROR, f"{free / 1024**3:.1f} GiB free < {ctx.options.disk_floor_gib} GiB", "ERROR")
    return CheckResult(PASS, f"{free / 1024**3:.1f} GiB free on {probe}", evidence={"free_bytes": free})


def _resolve(ctx: PreflightContext, ref: str) -> str | None:
    result = _caller_git(ctx, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    sha = result.stdout.strip().lower()
    return sha if result.exit_code == 0 and _SHA40.match(sha) else None


def _is_ancestor(ctx: PreflightContext, a: str, b: str, *, store: bool = False) -> bool:
    args = ("merge-base", "--is-ancestor", a, b)
    result = ctx.git(*args, check=False) if store else _caller_git(ctx, *args, check=False)
    if result.exit_code not in (0, 1):
        raise RuntimeError(f"merge-base --is-ancestor {a} {b}: {result.tail(400)}")
    return result.exit_code == 0


def _phase_refs(ctx: PreflightContext) -> CheckResult:
    opts, warnings, details = ctx.options, [], []
    fetch_ok = None
    if not opts.no_fetch and not opts.dry_run:
        fetch = _caller_git(ctx, "fetch", "--quiet", "origin", check=False)
        fetch_ok = fetch.exit_code == 0
        if not fetch_ok:
            raise PreflightAbort("refs", ERROR, f"git fetch origin failed: {fetch.tail(400)}", "ERROR")
    ctx.base_ref = opts.base
    base_sha = _resolve(ctx, opts.base)
    if base_sha is None:
        raise PreflightAbort("refs", ERROR, f"base {opts.base!r} does not resolve", "ERROR")
    if opts.base in ("master", "refs/heads/master"):
        origin = _resolve(ctx, "origin/master")
        if origin and origin != base_sha:
            if _is_ancestor(ctx, base_sha, origin):
                warnings.append(f"local master {base_sha[:12]} is behind origin/master; judged against origin/master")
                base_sha, ctx.base_ref = origin, "origin/master"
            elif not _is_ancestor(ctx, origin, base_sha):
                raise PreflightAbort("refs", ERROR, "local master and origin/master have diverged", "ERROR")
    if opts.expect_base and opts.expect_base.lower() != base_sha:
        raise PreflightAbort("refs", ERROR, f"base resolved {base_sha}, --expect-base {opts.expect_base}", "ERROR")
    ctx.base_sha = base_sha

    ctx.head_ref = opts.head
    head_sha = _resolve(ctx, opts.head)
    if head_sha is None:
        raise PreflightAbort("refs", ERROR, f"head {opts.head!r} does not resolve", "ERROR")
    if opts.expect_head and opts.expect_head.lower() != head_sha:
        raise PreflightAbort("refs", ERROR, f"head resolved {head_sha}, --expect-head {opts.expect_head}", "ERROR")
    ctx.head_sha = head_sha

    slots = landing_slots(ctx.plan)
    head_index = next((i for i, s in enumerate(slots) if s["sha"] == head_sha), None)
    if head_index is None:
        by_ref = [i for i, s in enumerate(slots) if s.get("head") in (opts.head, opts.head.removeprefix("origin/"))]
        if by_ref:
            raise PreflightAbort("refs", ERROR, f"plan slot for {opts.head!r} binds {slots[by_ref[0]]['sha']}, head is {head_sha}",
                                 "ERROR")
        if slots and opts.night_plan:
            warnings.append("head is not in the night plan; every plan slot is treated as earlier")
        head_index = len(slots)
    earlier = slots[:head_index]
    for slot in earlier:
        sha = slot["sha"]
        if _caller_git(ctx, "cat-file", "-e", f"{sha}^{{commit}}", check=False).exit_code != 0:
            prs = [p for p in slot.get("prs") or [] if str(p).isdigit()]
            if prs and not opts.no_fetch and not opts.dry_run:
                _caller_git(ctx, "fetch", "--quiet", "origin", f"refs/pull/{prs[-1]}/head", check=False)
            if _caller_git(ctx, "cat-file", "-e", f"{sha}^{{commit}}", check=False).exit_code != 0:
                raise PreflightAbort("refs", ERROR, f"earlier {slot['label']} commit {sha} is not available", "ERROR")
        moved = _resolve(ctx, f"origin/{slot['head']}") if slot.get("head") and not str(slot["head"]).isdigit() else None
        if moved and moved != sha:
            warnings.append(f"earlier {slot['label']}: branch now at {moved[:12]}, plan binds {sha[:12]} (head drift)")
        details.append({"label": slot["label"], "sha": sha})
    ctx.earlier = earlier
    status = WARN if warnings else PASS
    return CheckResult(status, f"base {ctx.base_sha[:12]} head {head_sha[:12]} earlier {len(earlier)}",
                       details=details, evidence={"fetch_ok": fetch_ok, "warnings": warnings})


def _phase_already_landed(ctx: PreflightContext) -> CheckResult:
    if _is_ancestor(ctx, ctx.head_sha, ctx.base_sha):
        raise PreflightAbort("already_landed", INFO, f"head {ctx.head_sha[:12]} is already an ancestor of base", "SUPERSEDED")
    return CheckResult(PASS, "head is not an ancestor of base")


def _phase_containment(ctx: PreflightContext) -> CheckResult:
    rows, status = [], PASS
    for slot in ctx.earlier:
        if _is_ancestor(ctx, slot["sha"], ctx.base_sha):
            rows.append({"item": slot["label"], "relation": "earlier_already_in_base"})
            status = WARN if status == PASS else status
        elif _is_ancestor(ctx, ctx.head_sha, slot["sha"]):
            rows.append({"item": slot["label"], "relation": "lands_via"})
            status = WARN if status == PASS else status
        elif _is_ancestor(ctx, slot["sha"], ctx.head_sha):
            rows.append({"item": slot["label"], "relation": "order_inverted"})
            status = FAIL
    return CheckResult(status, f"{len(rows)} containment relation(s)", details=rows,
                       attribution=[{"item": r["relation"], "introduced_by": r["item"]} for r in rows])


def classify_fix(path: str) -> str:
    """Default ``fix_class`` for a conflicted path (refined by landing_preflight_checks)."""

    try:
        from weather.operations import landing_preflight_checks as plug

        return plug.classify_conflict_path(path)
    except (ImportError, AttributeError):
        return "src"


def _init_scratch_store(ctx: PreflightContext) -> None:
    common = _caller_git(ctx, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    objects = Path(common) / "objects"
    ctx.git_dir = ctx.run_dir / "store.git"
    _git(["init", "--quiet", "--bare", str(ctx.git_dir)])
    (ctx.git_dir / "objects" / "info").mkdir(parents=True, exist_ok=True)
    alternates = (str(objects).replace("\\", "/") + "\n").encode("utf-8")
    (ctx.git_dir / "objects" / "info" / "alternates").write_bytes(alternates)  # LF only: git reads CR as part of the path
    hooks = ctx.run_dir / "no-hooks"
    hooks.mkdir(exist_ok=True)
    ctx.git("config", "core.hooksPath", str(hooks))
    ctx.git("config", "gc.auto", "0")


def _merge_tree(ctx: PreflightContext, ours: str, theirs: str) -> tuple[str | None, list[str]]:
    result = ctx.git("merge-tree", "--write-tree", "-z", "--name-only", "--no-messages", ours, theirs, check=False)
    if result.exit_code not in (0, 1):
        raise RuntimeError(f"merge-tree {ours} {theirs}: {result.tail(600)}")
    parts = [p for p in result.stdout.split("\0") if p]
    tree = parts[0].strip() if parts else None
    return tree, ([] if result.exit_code == 0 else sorted(set(parts[1:])))


def _commit_tree(ctx: PreflightContext, tree: str, parents: Sequence[str], message: str, date: str) -> str:
    name, email = SYNTHETIC_IDENTITY
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": date}
    args = ["commit-tree", tree]
    for parent in parents:
        args += ["-p", parent]
    return ctx.git(*args, "-m", message, env_extra=env).stdout.strip()


def _phase_merge_chain(ctx: PreflightContext) -> CheckResult:
    """Two-parent, pinned-date synthetic chain base -> earlier... -> head (F3)."""

    _init_scratch_store(ctx)
    date = ctx.git("log", "-1", "--format=%at", ctx.head_sha).stdout.strip() + " +0000"
    ctx.base_tree = ctx.git("rev-parse", f"{ctx.base_sha}^{{tree}}").stdout.strip()
    steps = [ChainStep(i + 1, s["label"], s["sha"], "earlier", prs=list(s.get("prs") or []), known_fix=s.get("known_fix"))
             for i, s in enumerate(ctx.earlier)]
    steps.append(ChainStep(len(steps) + 1, ctx.head_ref, ctx.head_sha, "head"))
    ctx.chain = steps
    cur = ctx.base_sha
    for step in steps:
        if _is_ancestor(ctx, step.sha, cur, store=True):
            step.result, step.synthetic_commit = "already_in_chain", cur
            step.tree = ctx.git("rev-parse", f"{cur}^{{tree}}").stdout.strip()
        else:
            tree, conflicts = _merge_tree(ctx, cur, step.sha)
            if conflicts:
                step.result, step.conflicts = "conflict", conflicts
                step.conflicts_fix_class = {p: classify_fix(p) for p in conflicts}
                step.pairwise_conflicts = _pairwise(ctx, step, steps, date)
                for later in steps[step.step:]:
                    later.result = "skipped"
                raise PreflightAbort(
                    "merge_chain", FAIL, f"conflict merging {step.label} @{step.sha[:12]}: {', '.join(conflicts[:8])}",
                    "CONFLICT", conflicts=conflicts, step=step.step)
            step.tree = tree
            step.synthetic_commit = _commit_tree(ctx, tree, [cur, step.sha],
                                                 f"landing-preflight step {step.step}: merge {step.sha}", date)
            step.result = "clean"
        if step.role == "head":
            ctx.pre_head_commit = cur
        cur = step.synthetic_commit
    ctx.landing_commit, ctx.landing_tree = cur, steps[-1].tree
    ctx.changed_files = _changed_files(ctx)
    return CheckResult(PASS, f"{len(steps)} step(s) clean; landing {ctx.landing_commit[:12]}",
                       evidence={"landing_commit": ctx.landing_commit, "landing_tree": ctx.landing_tree})


def _pairwise(ctx: PreflightContext, failing: ChainStep, steps: list[ChainStep], date: str) -> list[dict[str, Any]]:
    """Attribute a chain conflict to pairs: base vs the step, and base+earlier_j vs the step."""

    rows = []
    _, with_base = _merge_tree(ctx, ctx.base_sha, failing.sha)
    rows.append({"with": "base", "paths": with_base})
    for other in steps[: failing.step - 1]:
        if other.result == "already_in_chain":
            continue
        tree, conflicts = _merge_tree(ctx, ctx.base_sha, other.sha)
        if conflicts or tree is None:
            rows.append({"with": other.label, "paths": [], "note": "earlier conflicts with base alone"})
            continue
        pair_base = _commit_tree(ctx, tree, [ctx.base_sha, other.sha], f"landing-preflight pair base+{other.sha}", date)
        _, paths = _merge_tree(ctx, pair_base, failing.sha)
        if paths:
            rows.append({"with": other.label, "sha": other.sha, "paths": paths})
    return rows


def _changed_files(ctx: PreflightContext) -> list[dict[str, Any]]:
    touched: dict[str, list[str]] = {}
    prev = ctx.base_tree
    for step in ctx.chain:
        if step.tree and step.tree != prev:
            names = ctx.git("diff", "--name-only", "-z", "--no-renames", prev, step.tree).stdout.split("\0")
            for name in filter(None, names):
                touched.setdefault(name, []).append(step.label)
        prev = step.tree or prev
    out = ctx.git("diff", "--name-status", "-z", "-M", ctx.base_tree, ctx.landing_tree).stdout.split("\0")
    rows, i = [], 0
    while i < len(out) and out[i]:
        status = out[i]
        if status[:1] in ("R", "C"):
            old, new = out[i + 1], out[i + 2]
            rows.append({"path": new, "old_path": old, "status": status[:1],
                         "introduced_by": sorted(set(touched.get(new, []) + touched.get(old, [])))})
            i += 3
        else:
            rows.append({"path": out[i + 1], "status": status[:1], "introduced_by": touched.get(out[i + 1], [])})
            i += 2
    return rows


def default_python(repo: Path) -> str:
    candidate = repo / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(candidate) if candidate.exists() else sys.executable


def _phase_worktree(ctx: PreflightContext) -> CheckResult:
    wt = ctx.run_dir / "wt"
    add = ctx.git("worktree", "add", "--detach", "--quiet", str(wt), ctx.landing_commit, check=False)
    if add.exit_code != 0:
        raise PreflightAbort("worktree", ERROR, f"worktree add failed: {add.tail(600)}", "ERROR")
    ctx.worktree = wt
    status = _git(["-C", str(wt), "status", "--porcelain", "--untracked-files=no"], check=False)
    if status.exit_code != 0 or status.stdout.strip():
        raise PreflightAbort("worktree", ERROR, f"scratch worktree is not clean: {status.tail(600)}", "ERROR")
    head = _git(["-C", str(wt), "rev-parse", "HEAD"]).stdout.strip()
    if head != ctx.landing_commit:
        raise PreflightAbort("worktree", ERROR, f"worktree HEAD {head} != landing commit", "ERROR")
    return CheckResult(PASS, f"detached worktree at {ctx.landing_commit[:12]}", evidence={"path": str(wt)})


_PROBE = (
    "import json, os, weather, weather.paths as p; "
    "print(json.dumps({'weather': os.path.realpath(weather.__file__), 'repo_root': os.path.realpath(str(p.REPO_ROOT))}))"
)


def _phase_import_probe(ctx: PreflightContext) -> CheckResult:
    ctx.child_env, removed = scrubbed_child_env(dict(os.environ), ctx.worktree)
    result = ctx.run([ctx.python, "-c", _PROBE], cwd=ctx.worktree, timeout=120)
    root = os.path.realpath(str(ctx.worktree))
    evidence: dict[str, Any] = {"python": ctx.python, "scrubbed_env_names": removed}
    try:
        probe = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise PreflightAbort("import_probe", ERROR, f"import probe failed: {result.tail(800)}", "ERROR", **evidence)
    evidence.update(probe)
    inside = all(os.path.normcase(str(probe.get(k, ""))).startswith(os.path.normcase(root) + os.sep)
                 or os.path.normcase(str(probe.get(k, ""))) == os.path.normcase(root) for k in ("weather", "repo_root"))
    if result.exit_code != 0 or not inside:
        raise PreflightAbort("import_probe", ERROR, f"weather resolves outside the scratch worktree: {probe}", "ERROR", **evidence)
    return CheckResult(PASS, "weather and REPO_ROOT resolve inside the scratch worktree", evidence=evidence)


# --------------------------------------------------------------------------- registry


def default_registry() -> CheckRegistry:
    """The registry with every plug-in module's checks (L-P2, L-P3, L-P4)."""

    registry = CheckRegistry()
    from weather.operations import landing_preflight_checks, landing_preflight_rollclass, landing_preflight_routing

    for module in (landing_preflight_checks, landing_preflight_rollclass, landing_preflight_routing):
        module.register_checks(registry)
    return registry


def _run_registered(ctx: PreflightContext, registry: CheckRegistry, phase: str) -> None:
    for spec in registry.specs(phase):
        unmet = [r for r in spec.requires if ctx.results.get(r) is None or ctx.results[r].status not in _SATISFIED]
        if unmet:
            ctx.results[spec.id] = CheckResult(SKIP, f"prerequisite not satisfied: {', '.join(unmet)}", owner=spec.owner)
            continue
        started = time.monotonic()
        try:
            result = spec.run(ctx)
            if not isinstance(result, CheckResult):
                raise TypeError(f"check {spec.id} returned {type(result).__name__}")
        except Exception as exc:  # a crashing check is ERROR, never PASS
            result = CheckResult(ERROR, f"{type(exc).__name__}: {exc}", output_tail=traceback.format_exc()[-2000:])
        result.owner = spec.owner
        result.duration_s = round(time.monotonic() - started, 3)
        ctx.results[spec.id] = result


# --------------------------------------------------------------------------- verdict


def decide_verdict(results: dict[str, CheckResult], terminal: str | None = None) -> tuple[str, list[str], list[str]]:
    failing = sorted(k for k, r in results.items() if r.status == FAIL)
    errors = sorted(k for k, r in results.items() if r.status == ERROR)
    warnings = sorted(k for k, r in results.items() if r.status == WARN)
    not_run = sorted(k for k, r in results.items() if r.status == NOT_RUN)
    if terminal in ("SUPERSEDED", "CONFLICT"):
        status = terminal
    elif failing:
        status = "FAIL"
    elif errors or terminal == "ERROR":
        status = "ERROR"
    elif not_run:
        status = "TESTS_NOT_RUN"
    else:
        status = "PASS"
    return status, failing + errors + not_run, warnings


def _result_json(result: CheckResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["duration_s"] = round(result.duration_s, 3)
    return payload


def build_document(ctx: PreflightContext, registry: CheckRegistry, terminal: str | None, started: float) -> dict[str, Any]:
    all_ids = list(CORE_CHECK_IDS) + registry.ids()
    all_ids += [k for k in ctx.results if k not in all_ids]
    for check_id in all_ids:
        ctx.results.setdefault(check_id, CheckResult(SKIP, "not reached", owner="core" if check_id in CORE_CHECK_IDS else
                                                     next((s.owner for s in registry.specs() if s.id == check_id), "")))
    status, blocking, warnings = decide_verdict(ctx.results, terminal)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_version": ctx.git_version,
        "python": ctx.python,
        "host": "workstation",
        "elapsed_s": round(time.monotonic() - started, 3),
        "inputs": {
            "repo": str(ctx.repo), "base_ref": ctx.base_ref, "base_sha": ctx.base_sha, "head_ref": ctx.head_ref,
            "head_sha": ctx.head_sha, "earlier": [{"label": e["label"], "sha": e["sha"], "prs": e.get("prs") or []}
                                                  for e in ctx.earlier],
            "tests_mode": ctx.options.tests, "scratch": str(ctx.scratch_root), "dry_run": ctx.options.dry_run,
            "plan_source": ctx.options.night_plan or ("--earlier" if ctx.options.earlier else None),
        },
        "plan_sha256": ctx.plan_sha256,
        "closure_snapshot_sha256": _file_sha256(ctx.options.closure_snapshot),
        "chain": [asdict(s) for s in ctx.chain],
        "landing": {"tree": ctx.landing_tree, "commit": ctx.landing_commit, "pre_head_commit": ctx.pre_head_commit,
                    "changed_files": ctx.changed_files},
        "checks": {k: _result_json(ctx.results[k]) for k in all_ids},
        "verdict": {"status": status, "exit_code": VERDICT_EXIT_CODES[status], "failing_checks": blocking,
                    "warnings": warnings,
                    "valid_while": f"origin/master == {ctx.base_sha or '?'} and the plan's earlier SHAs land unchanged"},
    }


def _file_sha256(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def finalize_receipt(document: dict[str, Any], out_path: Path) -> dict[str, Any]:
    """Bind the receipt: sha256 over the canonical JSON without the receipt block."""

    body = {k: v for k, v in document.items() if k != "receipt"}
    digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    inputs = document["inputs"]
    line = (f"landing_preflight {document['verdict']['status']} sha256={digest} head={inputs['head_sha']} "
            f"earlier=[{','.join(e['sha'] for e in inputs['earlier'])}] base={inputs['base_sha']} "
            f"plan={document.get('plan_sha256')} landing={document['landing']['commit']} git={document['git_version']}")
    document["receipt"] = {"out_path": str(out_path), "sha256": digest, "handback_line": line}
    return document


def receipt_digest(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes({k: v for k, v in document.items() if k != "receipt"})).hexdigest()


def write_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=False)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------- cleanup and driver


def _rmtree(path: Path) -> None:
    def _chmod_retry(func, target, *_exc):  # read-only pack files on Windows
        os.chmod(target, 0o700)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_chmod_retry)
    else:  # pragma: no cover - older interpreters
        shutil.rmtree(path, onerror=_chmod_retry)


def _cleanup(ctx: PreflightContext) -> dict[str, Any]:
    state: dict[str, Any] = {"kept": bool(ctx.options.keep_scratch), "scratch_removed": False, "worktree_pruned": False}
    if ctx.options.keep_scratch or not ctx.run_dir.exists():
        state["scratch_removed"] = not ctx.run_dir.exists()
        return state
    try:
        if ctx.worktree is not None and ctx.git_dir is not None:
            ctx.git("worktree", "remove", "--force", str(ctx.worktree), check=False)
        _rmtree(ctx.run_dir)
    except OSError as exc:
        state["error"] = f"{type(exc).__name__}: {exc}"
    state["scratch_removed"] = not ctx.run_dir.exists()
    state["worktree_pruned"] = state["scratch_removed"]  # the store holding the worktree record is gone with it
    return state


def run_preflight(options: argparse.Namespace, *, registry: CheckRegistry | None = None,
                  runner: CommandRunner | None = None, host_id_fn: Callable[[], str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run the preflight; returns ``(exit_code, document)``.  Seams are for tests."""

    started = time.monotonic()
    repo = Path(options.repo).resolve()
    scratch_root = Path(options.scratch).resolve() if options.scratch else Path(tempfile.gettempdir()) / "weather-landing-preflight"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ctx = PreflightContext(repo=repo, options=options, scratch_root=scratch_root,
                           run_dir=scratch_root / f"run-{stamp}-{os.getpid()}", runner=runner or run_command,
                           python=options.python or default_python(repo))
    terminal: str | None = None
    registry = registry if registry is not None else default_registry()
    try:
        try:
            ctx.results["host_identity"] = _phase_host_identity(ctx, host_id_fn or default_host_id)
            ctx.results["git_version"] = _phase_git_version(ctx)
            ctx.results["disk_floor"] = _phase_disk_floor(ctx)
            if options.night_plan and options.earlier:
                raise PreflightAbort("refs", ERROR, "--night-plan and --earlier are mutually exclusive", "ERROR")
            try:
                if options.night_plan:
                    ctx.plan, ctx.plan_sha256 = load_night_plan(Path(options.night_plan), options.expect_plan_sha256)
                else:
                    ctx.plan = plan_from_earlier(options.earlier or [])
                    ctx.plan_sha256 = ctx.plan["plan_sha256"]
            except (OSError, ValueError) as exc:
                raise PreflightAbort("refs", ERROR, f"night plan: {exc}", "ERROR")
            ctx.results["refs"] = _phase_refs(ctx)
            ctx.results["already_landed"] = _phase_already_landed(ctx)
            ctx.results["containment"] = _phase_containment(ctx)
            if options.dry_run:
                terminal = "DRY_RUN"
                return EXIT_PASS, _dry_run_document(ctx, registry)
            ctx.run_dir.mkdir(parents=True, exist_ok=False)
            ctx.results["merge_chain"] = _phase_merge_chain(ctx)
            _run_registered(ctx, registry, PHASE_OBJECTS)
            ctx.results["worktree"] = _phase_worktree(ctx)
            ctx.results["import_probe"] = _phase_import_probe(ctx)
            _run_registered(ctx, registry, PHASE_WORKTREE)
            _run_registered(ctx, registry, PHASE_TESTS)
        except PreflightAbort as abort:
            ctx.results[abort.check_id] = CheckResult(abort.status, abort.summary, evidence=abort.evidence)
            terminal = abort.verdict
        except Exception as exc:  # fail closed
            ctx.results["preflight"] = CheckResult(ERROR, f"{type(exc).__name__}: {exc}",
                                                   output_tail=traceback.format_exc()[-2000:])
            terminal = "ERROR"
    finally:
        cleanup = _cleanup(ctx) if terminal != "DRY_RUN" else {"scratch_removed": True, "worktree_pruned": True}
    document = build_document(ctx, registry, terminal, started)
    document["cleanup"] = cleanup
    out = Path(options.out) if options.out else scratch_root / f"landing_preflight-{(ctx.head_sha or 'unresolved')[:12]}-{stamp}.json"
    document = finalize_receipt(document, out)
    write_atomic(out, document)
    return document["verdict"]["exit_code"], document


def _dry_run_document(ctx: PreflightContext, registry: CheckRegistry) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "dry_run": True, "base_sha": ctx.base_sha, "head_sha": ctx.head_sha,
        "plan_sha256": ctx.plan_sha256, "earlier": [{"label": e["label"], "sha": e["sha"]} for e in ctx.earlier],
        "phases": {phase: [{"id": s.id, "owner": s.owner, "requires": list(s.requires)} for s in registry.specs(phase)]
                   for phase in PHASES},
        "core_checks": list(CORE_CHECK_IDS),
        "results": {k: _result_json(v) for k, v in ctx.results.items()},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m weather.operations.landing_preflight",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--head", required=True, help="head ref (branch, origin/branch or SHA)")
    parser.add_argument("--expect-head", help="freeze the head: 40-hex SHA it must resolve to")
    parser.add_argument("--night-plan", help="landing_night_plan_v0.1 JSON; its sha256 is bound")
    parser.add_argument("--expect-plan-sha256", help="sha256 the --night-plan file bytes must have")
    parser.add_argument("--earlier", action="append", default=[], metavar="N@SHA",
                        help="convenience: build a plan from heads landing earlier, in order")
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--expect-base", help="40-hex SHA the base must resolve to")
    parser.add_argument("--closure-snapshot", help="production closure snapshot JSON (roll-class prediction)")
    parser.add_argument("--tests", choices=("affected", "changed", "none", "full"), default="affected")
    parser.add_argument("--out", help="verdict JSON path (default under the scratch root)")
    parser.add_argument("--scratch", help="scratch root; a run-* directory inside it is created and removed")
    parser.add_argument("--keep-scratch", action="store_true")
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--queue-timeout-seconds", type=int, default=14400)
    parser.add_argument("--check-timeout-seconds", type=int, default=900)
    parser.add_argument("--pr-list", help="optional triage export used only for annotations")
    parser.add_argument("--dry-run", action="store_true", help="resolve refs and print the plan; run no check")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="caller repository (read-only)")
    parser.add_argument("--python", help="interpreter for worktree checks (default: the repo venv)")
    parser.add_argument("--host-assignment", help=argparse.SUPPRESS)
    parser.add_argument("--disk-floor-gib", type=float, default=DISK_FLOOR_BYTES / 1024**3, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    code, document = run_preflight(options)
    if options.dry_run:
        print(json.dumps(document, indent=2))
        return code
    verdict = document["verdict"]
    for check_id, check in document["checks"].items():
        if check["status"] not in (PASS, SKIP):
            print(f"[{check['status']}] {check_id}: {check['summary']}")
    print(document["receipt"]["handback_line"])
    print(f"verdict {verdict['status']} (exit {verdict['exit_code']}) -> {document['receipt']['out_path']}")
    return code


if __name__ == "__main__":
    # Plug-ins import this module by its package name; run that copy, not ``__main__``,
    # so CheckResult/CheckSpec identities match.
    from weather.operations.landing_preflight import main as _package_main

    raise SystemExit(_package_main())
