"""M5 shadow dual run: record preflight + CI next to the host bounded suite, per ROLL-FREE landing.

Pilot (owner-approved, non-binding).  M5 would let a ROLL-FREE tip land without the
host bounded suite when CI (including the Windows ``native-launch`` lane) and the
workstation preflight are green.  Before anyone may rely on that, every ROLL-FREE
landing that production still runs **with** the bounded suite is recorded here:

* the preflight verdict for the exact tip (its receipt digest re-verified),
* the CI conclusion at that SHA (Windows lane and the rest), and
* the host bounded-suite outcome the production agent hands back (an input file),

and one JSON line is appended to a concordance ledger on the workstation.  A row is
*concordant* when "CI + preflight would have let it land" equals "the host suite
passed".  Rows a disqualifier hits are recorded but never counted:

* a changed **host-only** test, or a changed ``src`` module a host-only test imports
  directly (:func:`host_only_tests` derives the set mechanically from the tree, plus
  optional JUnit evidence from :func:`junit_host_only_nodeids`);
* a changed **hash-pinned** script (``landing_preflight_pilots.hash_frozen_paths``);
* a host roll verdict other than ROLL-FREE (M5 never applies).

``progress`` reports the owner's threshold: the later of 5 concordant landings or
14 days since the current run began; any discordance resets both.  Everything is
``binding: false``: it grants nothing and changes no gate.

Commands::

    python -m weather.operations.landing_preflight_m5 record --preflight <verdict.json> \\
        --host-outcome <handback.json> (--ci-checks <json> | --fetch-ci) [--ledger <jsonl>]
    python -m weather.operations.landing_preflight_m5 progress [--ledger <jsonl>]
    python -m weather.operations.landing_preflight_m5 host-only --ref <sha> [--host-junit X --ci-junit Y ...]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from weather.operations import landing_preflight as lp
from weather.operations.landing_preflight_pilots import (
    GitBytes,
    git_bytes_runner,
    hash_frozen_paths,
    texts_of,
    tree_listing,
)
from weather.paths import REPO_ROOT

LEDGER_SCHEMA = "landing_preflight_m5_concordance_v0.1"
DEFAULT_LEDGER = REPO_ROOT / "data" / "workstation" / "landing_preflight" / "m5_concordance.jsonl"
THRESHOLD_LANDINGS = 5
THRESHOLD_DAYS = 14
PREDICTED_PASS = frozenset({"PASS", "PASS_NO_TESTS"})
WINDOWS_LANE = re.compile(r"^(native-launch\b|windows)", re.I)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
EXIT_OK, EXIT_REFUSED = 0, 2

# --------------------------------------------------------------------------- host-only tests (mechanical)

_WINDOWS_ONLY = re.compile(
    r"os\.name\s*!=\s*['\"]nt['\"]|sys\.platform\s*!=\s*['\"]win32['\"]|not\s+sys\.platform\.startswith\(\s*['\"]win"
    r"|platform\.system\(\)\s*!=\s*['\"]Windows['\"]")
_CI_SKIP = re.compile(r"GITHUB_ACTIONS|environ(?:\.get)?\(\s*['\"]CI['\"]|environ\[\s*['\"]CI['\"]\s*\]")
_HOST_IDENTITY = re.compile(r"icacls|whoami|USERDOMAIN|MachineGuid|Register-ScheduledTask|schtasks|ProgramData|\bS4U\b",
                            re.I)
WINDOWS_WORKFLOW = ".github/workflows/windows-qualification.yml"


def _is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return path.startswith("tests/") and name.startswith("test_") and name.endswith(".py")


def host_only_tests(git: GitBytes, tree: str, junit_files: Iterable[str] = ()) -> dict[str, list[str]]:
    """Test files that run on the capture host but not (or not equivalently) in CI.  Mechanical rules:

    * ``windows_only_not_in_ci_windows_lane``: a Windows-only skip condition (``os.name != "nt"``,
      ``sys.platform != "win32"`` ...) and the file is in no shard of ``windows-qualification.yml``,
      so Linux CI skips it and the Windows lane never runs it;
    * ``skipped_on_ci``: a condition on ``GITHUB_ACTIONS`` or the ``CI`` environment variable;
    * ``host_identity_api``: the file names a host-identity, ACL or Scheduler surface
      (``icacls``, ``whoami``, ``USERDOMAIN``, ``MachineGuid``, ``Register-ScheduledTask``,
      ``schtasks``, ``ProgramData``, ``S4U``): the 10-04 icacls 1332 class;
    * ``junit_host_only``: ``junit_files`` (from :func:`junit_host_only_nodeids`) name it.
    """

    from weather.operations.landing_preflight_checks import shard_plan_files

    listing = tree_listing(git, tree, "tests", WINDOWS_WORKFLOW)
    workflow = texts_of(git, {WINDOWS_WORKFLOW: listing[WINDOWS_WORKFLOW]}).get(WINDOWS_WORKFLOW, "") \
        if WINDOWS_WORKFLOW in listing else ""
    sharded = set(shard_plan_files(workflow)) if workflow else set()
    texts = texts_of(git, {p: o for p, o in listing.items() if _is_test_file(p)})
    found: dict[str, list[str]] = {}
    for path, text in texts.items():
        reasons = []
        if _WINDOWS_ONLY.search(text) and path not in sharded:
            reasons.append("windows_only_not_in_ci_windows_lane")
        if _CI_SKIP.search(text):
            reasons.append("skipped_on_ci")
        if _HOST_IDENTITY.search(text):
            reasons.append("host_identity_api")
        if reasons:
            found[path] = reasons
    for path in junit_files:
        found.setdefault(path, []).append("junit_host_only")
    return dict(sorted(found.items()))


def _junit_cases(path: Path) -> dict[str, str]:
    """``{nodeid: outcome}`` (passed, failed, skipped) from one JUnit XML file."""

    cases: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        nodeid = f"{case.get('classname', '')}::{case.get('name', '')}"
        if case.find("skipped") is not None:
            outcome = "skipped"
        elif case.find("failure") is not None or case.find("error") is not None:
            outcome = "failed"
        else:
            outcome = "passed"
        cases[nodeid] = outcome
    return cases


def junit_host_only_nodeids(host_junit: Sequence[Path], ci_junit: Sequence[Path]) -> list[str]:
    """Node ids the host ran (passed or failed) that every CI JUnit skipped or never listed."""

    host: dict[str, str] = {}
    for path in host_junit:
        host.update(_junit_cases(path))
    ran_on_ci: set[str] = set()
    for path in ci_junit:
        ran_on_ci.update(n for n, outcome in _junit_cases(path).items() if outcome != "skipped")
    return sorted(n for n, outcome in host.items() if outcome != "skipped" and n not in ran_on_ci)


def nodeid_files(nodeids: Iterable[str], test_paths: Iterable[str]) -> list[str]:
    """Map JUnit ``classname::name`` ids to test files (longest dotted prefix that is a file)."""

    known = set(test_paths)
    files = set()
    for nodeid in nodeids:
        parts = nodeid.split("::", 1)[0].split(".")
        for cut in range(len(parts), 0, -1):
            candidate = "/".join(parts[:cut]) + ".py"
            if candidate in known:
                files.add(candidate)
                break
    return sorted(files)


def _module_of(path: str) -> str | None:
    if not (path.startswith("src/") and path.endswith(".py")):
        return None
    dotted = path[4:-3].replace("/", ".")
    return dotted[: -len(".__init__")] if dotted.endswith(".__init__") else dotted


def _imports_module(text: str, module: str) -> bool:
    head, _, leaf = module.rpartition(".")
    if re.search(rf"\b{re.escape(module)}\b", text):
        return True
    return bool(head and re.search(rf"from\s+{re.escape(head)}\s+import\s+[^\n]*\b{re.escape(leaf)}\b", text))


def disqualifiers_for(git: GitBytes, base: str, head: str, junit_files: Iterable[str] = ()) -> tuple[list[dict[str, str]], list[str]]:
    """M5 disqualifiers for the tip's own change (``merge-base(base, head)..head``)."""

    merge_base = git("merge-base", base, head).decode().strip()
    changed = [p for p in git("diff", "--name-only", "-z", "--no-renames", merge_base, head).decode(
        "utf-8", "surrogateescape").split("\0") if p]
    head_tree = git("rev-parse", f"{head}^{{tree}}").decode().strip()
    rows: list[dict[str, str]] = []
    host_only = host_only_tests(git, head_tree, junit_files)
    for path in changed:
        if path in host_only:
            rows.append({"reason": "host_only_test_changed", "path": path, "why": ",".join(host_only[path])})
    modules = {p: m for p in changed if (m := _module_of(p))}
    if modules:
        texts = texts_of(git, {p: o for p, o in tree_listing(git, head_tree, *host_only).items()}) if host_only else {}
        for path, module in sorted(modules.items()):
            users = sorted(t for t, text in texts.items() if _imports_module(text, module))
            if users:
                rows.append({"reason": "host_only_test_imports", "path": path, "why": ", ".join(users[:5])})
    frozen = hash_frozen_paths(git, head_tree)
    frozen.update({k: v for k, v in hash_frozen_paths(git, git("rev-parse", f"{merge_base}^{{tree}}").decode().strip()).items()
                   if k not in frozen})
    for path in changed:
        if path in frozen:
            rows.append({"reason": "hash_pinned_script", "path": path, "why": frozen[path]})
    return rows, changed


# --------------------------------------------------------------------------- CI conclusions


def normalize_ci(payload: Any, sha: str) -> dict[str, Any]:
    """Accept ``gh api .../commits/<sha>/check-runs`` or ``gh pr checks --json name,state,bucket``."""

    runs_in = payload.get("check_runs") if isinstance(payload, dict) else payload
    if not isinstance(runs_in, list):
        raise ValueError("CI checks JSON must be a list or carry check_runs")
    runs = []
    for run in runs_in:
        if run.get("head_sha") and str(run["head_sha"]).lower() != sha:
            raise ValueError(f"CI check {run.get('name')} is for {run['head_sha']}, not {sha}")
        raw = (run.get("conclusion") or run.get("bucket") or run.get("state") or run.get("status") or "").lower()
        conclusion = {"pass": "success", "success": "success", "fail": "failure", "failure": "failure",
                      "cancel": "cancelled", "cancelled": "cancelled", "skipping": "skipped", "skipped": "skipped",
                      "neutral": "neutral", "timed_out": "failure", "action_required": "failure"}.get(raw, "pending")
        runs.append({"name": str(run.get("name", "")), "conclusion": conclusion})

    def lane(rows: list[dict[str, str]]) -> str:
        if not rows:
            return "absent"
        if any(r["conclusion"] in ("failure", "cancelled") for r in rows):
            return "failure"
        if any(r["conclusion"] == "pending" for r in rows):
            return "pending"
        return "success"

    windows = [r for r in runs if WINDOWS_LANE.match(r["name"])]
    other = [r for r in runs if not WINDOWS_LANE.match(r["name"])]
    return {"sha": sha, "windows_lane": lane(windows), "other_lanes": lane(other), "runs": runs}


def fetch_ci(sha: str, repo: Path) -> Any:  # pragma: no cover - network; tests pass --ci-checks
    proc = subprocess.run(["gh", "api", f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100"],
                          cwd=str(repo), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ValueError(f"gh api check-runs failed: {proc.stderr.strip()[-400:]}")
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------- record and progress


def verify_preflight(document: dict[str, Any], tip: str) -> list[str]:
    problems = []
    if document.get("schema") != lp.SCHEMA:
        problems.append(f"not a {lp.SCHEMA} verdict")
    receipt = document.get("receipt") or {}
    if receipt.get("sha256") != lp.receipt_digest(document):
        problems.append("receipt digest does not match the verdict body")
    if (document.get("inputs") or {}).get("head_sha") != tip:
        problems.append(f"preflight head {(document.get('inputs') or {}).get('head_sha')} is not the tip {tip}")
    return problems


def load_host_outcome(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tip = str(data.get("tip_sha", "")).lower()
    if not _SHA40.match(tip):
        raise ValueError("host outcome: tip_sha must be a 40-hex SHA")
    suite = data.get("bounded_suite") or {}
    if suite.get("outcome") not in ("PASS", "FAIL"):
        raise ValueError("host outcome: bounded_suite.outcome must be PASS or FAIL")
    if not data.get("roll_verdict"):
        raise ValueError("host outcome: roll_verdict is required (production roll_verdict.ps1 result)")
    if not data.get("landed_at"):
        raise ValueError("host outcome: landed_at is required (ISO 8601)")
    datetime.fromisoformat(str(data["landed_at"]))
    return {**data, "tip_sha": tip}


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def progress(rows: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """The owner threshold: the later of 5 concordant landings or 14 days; any discordance resets."""

    now = now or datetime.now(timezone.utc)
    count, start, discordances, last_reset = 0, None, 0, None
    for row in sorted((r for r in rows if r.get("counted")), key=lambda r: r["host"]["landed_at"]):
        landed = datetime.fromisoformat(row["host"]["landed_at"])
        if row["concordant"]:
            count += 1
            start = start or landed
        else:
            discordances += 1
            count, start, last_reset = 0, None, row["tip_sha"]
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    days = (now - start) / timedelta(days=1) if start else 0.0
    return {"concordant_since_reset": count, "days_since_run_start": round(days, 2),
            "run_started_at": start.isoformat() if start else None, "discordances": discordances,
            "last_reset_by": last_reset, "recorded_rows": len(rows),
            "counted_rows": sum(1 for r in rows if r.get("counted")),
            "threshold": f"later of {THRESHOLD_LANDINGS} concordant landings or {THRESHOLD_DAYS} days; "
                         "any discordance resets",
            "threshold_met": count >= THRESHOLD_LANDINGS and days >= THRESHOLD_DAYS, "binding": False}


def build_row(preflight: dict[str, Any], host: dict[str, Any], ci: dict[str, Any],
              disqualifiers: list[dict[str, str]], changed: list[str], master_sha: str) -> dict[str, Any]:
    tip = host["tip_sha"]
    status = preflight["verdict"]["status"]
    roll_free = str(host["roll_verdict"]).upper() in ("ROLL-FREE", "ROLL_FREE", "0")
    applicable = roll_free and ci["windows_lane"] != "pending" and ci["other_lanes"] != "pending"
    predicted = status in PREDICTED_PASS and ci["windows_lane"] == "success" and ci["other_lanes"] == "success"
    actual = host["bounded_suite"]["outcome"] == "PASS"
    counted = applicable and not disqualifiers
    return {
        "schema": LEDGER_SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "master_sha": master_sha, "tip_sha": tip, "binding": False,
        "preflight": {"status": status, "receipt_sha256": preflight["receipt"]["sha256"],
                      "base_sha": preflight["inputs"]["base_sha"], "plan_sha256": preflight.get("plan_sha256"),
                      "tests_mode": preflight["inputs"].get("tests_mode")},
        "ci": ci, "host": {k: host[k] for k in ("roll_verdict", "bounded_suite", "landed_at") if k in host}
        | {"landing_sha": host.get("landing_sha"), "source": host.get("source")},
        "changed_files": changed[:500], "disqualifiers": disqualifiers,
        "applicable": applicable, "predicted_suite_pass": predicted, "host_suite_pass": actual,
        "concordant": predicted == actual, "counted": counted,
        "not_counted_because": None if counted else (
            "host roll verdict is not ROLL-FREE" if not roll_free else
            "CI still pending at that SHA" if not applicable else "disqualified"),
    }


def _capture_host_refusal(repo: Path, host_id_fn: Callable[[], str]) -> str | None:
    try:
        assignment = json.loads((repo / "config" / "international_live_execution_host.json").read_text(encoding="utf-8"))
        if host_id_fn() == str(assignment["dedicated_capture_execution_host_id"]):
            return "refused: this is the dedicated capture host (the recorder is workstation-only)"
    except Exception as exc:  # fail closed
        return f"refused: host identity unavailable: {exc}"
    return None


def record(args: argparse.Namespace, *, host_id_fn: Callable[[], str] | None = None) -> tuple[int, dict[str, Any]]:
    repo = Path(args.repo).resolve()
    refusal = _capture_host_refusal(repo, host_id_fn or lp.default_host_id)
    if refusal:
        return EXIT_REFUSED, {"error": refusal}
    try:
        host = load_host_outcome(Path(args.host_outcome))
        preflight = json.loads(Path(args.preflight).read_text(encoding="utf-8"))
        problems = verify_preflight(preflight, host["tip_sha"])
        if problems:
            raise ValueError("; ".join(problems))
        ledger = Path(args.ledger)
        if any(r.get("tip_sha") == host["tip_sha"] for r in read_ledger(ledger)):
            raise ValueError(f"tip {host['tip_sha']} is already in the ledger")
        ci_payload = json.loads(Path(args.ci_checks).read_text(encoding="utf-8")) if args.ci_checks else fetch_ci(
            host["tip_sha"], repo)
        ci = normalize_ci(ci_payload, host["tip_sha"])
        git = git_bytes_runner(["-C", str(repo)])
        junit_files: list[str] = []
        if args.host_only_nodeids:
            ids = json.loads(Path(args.host_only_nodeids).read_text(encoding="utf-8"))
            ids = ids.get("host_only_nodeids", []) if isinstance(ids, dict) else ids
            tree = git("rev-parse", f"{host['tip_sha']}^{{tree}}").decode().strip()
            junit_files = nodeid_files(ids, tree_listing(git, tree, "tests"))
        disqualifiers, changed = disqualifiers_for(git, preflight["inputs"]["base_sha"], host["tip_sha"], junit_files)
        master = git("rev-parse", "--verify", "--quiet", "origin/master", ok=(0, 1)).decode().strip()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        return EXIT_REFUSED, {"error": f"{type(exc).__name__}: {exc}"}
    row = build_row(preflight, host, ci, disqualifiers, changed, master)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return EXIT_OK, {"row": row, "progress": progress(read_ledger(ledger))}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m weather.operations.landing_preflight_m5",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="append one concordance row for a ROLL-FREE tip landed with the bounded suite")
    rec.add_argument("--preflight", required=True, help="landing_preflight_v0.1 verdict JSON for the exact tip")
    rec.add_argument("--host-outcome", required=True, help="production handback: tip_sha, roll_verdict, "
                     "bounded_suite.outcome (PASS|FAIL), landed_at")
    ci = rec.add_mutually_exclusive_group(required=True)
    ci.add_argument("--ci-checks", help="gh check-runs JSON (or gh pr checks --json name,state,bucket) at the tip")
    ci.add_argument("--fetch-ci", action="store_true", help="read the check runs at the tip with gh api")
    rec.add_argument("--host-only-nodeids", help="JSON list from `host-only --host-junit ... --ci-junit ...`")
    prog = sub.add_parser("progress", help="report the threshold progress (binding: false)")
    only = sub.add_parser("host-only", help="list host-only test files at a ref (and JUnit host-only node ids)")
    only.add_argument("--ref", default="HEAD")
    only.add_argument("--host-junit", action="append", default=[])
    only.add_argument("--ci-junit", action="append", default=[])
    for p in (rec, prog, only):
        p.add_argument("--repo", default=str(REPO_ROOT))
        p.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "record":
        code, payload = record(args)
    elif args.command == "progress":
        code, payload = EXIT_OK, progress(read_ledger(Path(args.ledger)))
    else:
        git = git_bytes_runner(["-C", str(Path(args.repo).resolve())])
        tree = git("rev-parse", f"{args.ref}^{{tree}}").decode().strip()
        ids = junit_host_only_nodeids([Path(p) for p in args.host_junit], [Path(p) for p in args.ci_junit]) \
            if args.host_junit else []
        files = nodeid_files(ids, tree_listing(git, tree, "tests"))
        code, payload = EXIT_OK, {"ref": args.ref, "host_only_nodeids": ids,
                                  "host_only_tests": host_only_tests(git, tree, files), "binding": False}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    from weather.operations.landing_preflight_m5 import main as _package_main

    sys.exit(_package_main())
