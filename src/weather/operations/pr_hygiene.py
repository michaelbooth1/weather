"""Read-only open-PR hygiene report; it never closes, merges, pushes or fetches.

Runbook: docs/operations/pr-hygiene.md. Per open PR: ancestry into the base ref,
merge-tree conflicts, age, linked work records and handoffs, a file-class roll
heuristic and a proposed action. Every external command passes one allow-list.
The roll class is a heuristic; ``scripts/ops/roll_verdict.ps1`` stays authoritative.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

from weather.paths import REPO_ROOT, data_path

PR_FIELDS = ("number,title,headRefName,headRefOid,baseRefName,isDraft,createdAt,updatedAt,author,"
             "mergeable,statusCheckRollup,url,body")
SHA = re.compile(r"[0-9a-f]{40}\Z")
REF = re.compile(r"[A-Za-z0-9._/-]{1,200}\Z")
HANDOFF_ID = re.compile(r"\b(\d{2,3}[a-z])\b")
STALE_DAYS = 14
FAR_BEHIND = 150


class CommandRefused(RuntimeError):
    """An external command outside the read-only allow-list."""


def check_command(argv):
    """The single allow-list: exact read-only gh and git shapes, validated arguments."""
    ok = False
    if argv[:3] == ["gh", "pr", "list"]:
        ok = argv[3:] == ["--state", "open", "--limit", argv[6] if len(argv) > 6 else "", "--json", PR_FIELDS] and (
            len(argv) == 9 and argv[6].isdigit() and 1 <= int(argv[6]) <= 200)
    elif argv[:3] == ["git", "merge-base", "--is-ancestor"]:
        ok = len(argv) == 5 and SHA.fullmatch(argv[3]) and REF.fullmatch(argv[4])
    elif argv[:3] == ["git", "rev-list", "--count"]:
        ok = len(argv) == 4 and re.fullmatch(r"[0-9a-f]{40}\.\.[A-Za-z0-9._/-]{1,200}", argv[3])
    elif argv[:2] == ["git", "cat-file"]:
        ok = len(argv) == 4 and argv[2] == "-e" and SHA.fullmatch(argv[3].removesuffix("^{commit}"))
    elif argv[:5] == ["git", "merge-tree", "--write-tree", "--name-only", "--no-messages"]:
        ok = len(argv) == 7 and REF.fullmatch(argv[5]) and SHA.fullmatch(argv[6])
    elif argv[:3] == ["git", "diff", "--name-only"]:
        ok = len(argv) == 4 and re.fullmatch(r"[A-Za-z0-9._/-]{1,200}\.\.\.[0-9a-f]{40}", argv[3])
    elif argv[:3] == ["git", "rev-parse", "--verify"]:
        ok = len(argv) == 5 and argv[3] == "--quiet" and REF.fullmatch(argv[4])
    if not ok:
        raise CommandRefused("command_refused: " + " ".join(argv[:3]))


def run_readonly(argv, *, cwd=REPO_ROOT, runner=subprocess.run, timeout=60):
    check_command(argv)
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0"}
    return runner(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False, env=env)


def classify_files(paths):
    """File-class roll heuristic; the loaded-module closure verdict is not derived here."""
    classes = {"docs": 0, "config": 0, "ps1": 0, "tests": 0, "src_python": 0, "schema_registry": 0, "other": 0}
    for path in paths:
        if re.fullmatch(r"src/weather/schema_registry[a-z_]*\.py", path):
            classes["schema_registry"] += 1
        elif path.startswith("src/") and path.endswith(".py"):
            classes["src_python"] += 1
        elif path.startswith("tests/"):
            classes["tests"] += 1
        elif path.endswith(".md") or path.startswith("docs/"):
            classes["docs"] += 1
        elif path.startswith("config/"):
            classes["config"] += 1
        elif path.endswith(".ps1"):
            classes["ps1"] += 1
        else:
            classes["other"] += 1
    if classes["schema_registry"]:
        roll = "sensitive_all_closures"
    elif classes["src_python"]:
        roll = "possibly_sensitive"
    elif classes["other"]:
        roll = "unclassified"
    else:
        roll = "roll_free"
    return {k: v for k, v in classes.items() if v}, roll


def work_records(root):
    """Tracker records (JSON content in ``W-*.yaml``); absent before the tracker lands."""
    folder = Path(root) / "docs" / "roadmap" / "work"
    records = []
    for path in sorted(folder.glob("W-*.yaml")) if folder.is_dir() else []:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def linked_work(pr, records, root):
    ids = sorted({r.get("id") for r in records if r.get("pr") == pr["number"] or r.get("branch") == pr["headRefName"]}
                 - {None})
    handoffs = []
    for handoff in sorted(set(HANDOFF_ID.findall(pr["title"] + " " + pr["headRefName"]))):
        handoffs += sorted(p.relative_to(root).as_posix()
                           for p in (Path(root) / "docs" / "roadmap").glob(f"workstation-handoff-2026-*-{handoff}-*.md"))
    return ids, handoffs


def ci_state(rollup):
    states = []
    for check in rollup or []:
        value = check.get("conclusion") or check.get("state") or check.get("status")
        states.append(str(value).upper() if value else "PENDING")
    if not states:
        return "none"
    if any(s in {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"} for s in states):
        return "failing"
    if any(s in {"PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "WAITING", "REQUESTED"} for s in states):
        return "pending"
    return "passing"


def propose(row):
    if row["merged_by_ancestry"]:
        return "close_as_already_in_base"
    if row["head_available"] is False:
        return "fetch_then_rerun"
    if row["conflicts"]:
        return "merge_base_into_branch_and_resolve"
    if row["ci"] == "failing":
        return "fix_ci"
    if row["ci"] in {"pending", "none"}:
        return "wait_for_ci"
    if (row["age_days_since_update"] or 0) >= STALE_DAYS:
        return "review_or_close_stale"
    if (row["behind_base"] or 0) >= FAR_BEHIND:
        return "merge_base_into_branch"
    if row["roll_class"] == "roll_free":
        return "production_review_then_land_any_hour"
    return "production_review_then_roll_verdict_and_quiet_window"


def inspect_pr(pr, *, base, now, records, root, run):
    row = dict(number=pr["number"], title=pr["title"], url=pr.get("url"), branch=pr["headRefName"],
               head=pr["headRefOid"], draft=pr.get("isDraft"), author=(pr.get("author") or {}).get("login"),
               github_mergeable=pr.get("mergeable"), ci=ci_state(pr.get("statusCheckRollup")),
               age_days=None, age_days_since_update=None, head_available=None, merged_by_ancestry=None,
               behind_base=None, conflicts=None, conflicted_files=[], changed_files=None, file_classes={},
               roll_class=None, work_records=[], handoffs=[], errors=[])
    for key, field in (("age_days", "createdAt"), ("age_days_since_update", "updatedAt")):
        try:
            row[key] = round((now - datetime.fromisoformat(pr[field].replace("Z", "+00:00"))).total_seconds() / 86400, 1)
        except (KeyError, AttributeError, ValueError):
            row["errors"].append(field + "_unreadable")
    row["work_records"], row["handoffs"] = linked_work(pr, records, root)
    head = row["head"]
    if not isinstance(head, str) or not SHA.fullmatch(head):
        row["errors"].append("head_sha_unreadable")
        row["proposed_action"] = "inspect_manually"
        return row
    row["head_available"] = run(["git", "cat-file", "-e", head + "^{commit}"]).returncode == 0
    if row["head_available"]:
        ancestry = run(["git", "merge-base", "--is-ancestor", head, base]).returncode
        row["merged_by_ancestry"] = ancestry == 0
        if ancestry not in (0, 1):
            row["errors"].append("ancestry_unreadable")
        behind = run(["git", "rev-list", "--count", f"{head}..{base}"])
        row["behind_base"] = int(behind.stdout.strip()) if behind.returncode == 0 and behind.stdout.strip().isdigit() else None
        merge = run(["git", "merge-tree", "--write-tree", "--name-only", "--no-messages", base, head])
        if merge.returncode in (0, 1):
            row["conflicts"] = merge.returncode == 1
            row["conflicted_files"] = [line for line in merge.stdout.splitlines()[1:] if line.strip()]
        else:
            row["errors"].append("merge_tree_unavailable")
        diff = run(["git", "diff", "--name-only", f"{base}...{head}"])
        if diff.returncode == 0:
            files = [line for line in diff.stdout.splitlines() if line.strip()]
            row["changed_files"] = len(files)
            row["file_classes"], row["roll_class"] = classify_files(files)
        else:
            row["errors"].append("diff_unavailable")
    row["proposed_action"] = propose(row)
    return row


def build_report(*, base="origin/master", limit=100, root=REPO_ROOT, now=None, runner=subprocess.run):
    now = now or datetime.now(timezone.utc)

    def run(argv):
        return run_readonly(argv, cwd=root, runner=runner)
    if run(["git", "rev-parse", "--verify", "--quiet", base]).returncode != 0:
        raise CommandRefused("base_ref_unavailable")
    listed = run(["gh", "pr", "list", "--state", "open", "--limit", str(limit), "--json", PR_FIELDS])
    if listed.returncode != 0:
        raise CommandRefused("gh_pr_list_failed")
    prs = json.loads(listed.stdout)
    records = work_records(root)
    rows = [inspect_pr(pr, base=base, now=now, records=records, root=Path(root), run=run)
            for pr in sorted(prs, key=lambda p: p["number"])]
    actions = {}
    for row in rows:
        actions[row["proposed_action"]] = actions.get(row["proposed_action"], 0) + 1
    return dict(report="pr_hygiene", generated_at_utc=now.isoformat(), base=base, open_prs=len(rows),
                limit_reached=len(prs) >= limit, work_records_available=bool(records),
                action_counts=actions, prs=rows,
                notes=["read_only_no_fetch_no_close_no_merge_no_push", "roll_class_is_file_class_heuristic",
                       "authoritative_roll_verdict_is_scripts/ops/roll_verdict.ps1",
                       "merge_tree_writes_only_unreferenced_tree_objects"])


def render_markdown(report):
    lines = [f"# Open PR hygiene - {report['generated_at_utc'][:16]}Z", "",
             f"Base `{report['base']}`; {report['open_prs']} open PRs"
             + ("; **list limit reached**" if report["limit_reached"] else "")
             + ("" if report["work_records_available"] else "; no work records in this checkout") + ".",
             "Read-only: nothing was fetched, closed, merged or pushed. Roll class is a file-class heuristic;",
             "`scripts/ops/roll_verdict.ps1` is authoritative.", "",
             "| PR | Branch | Age (d) | Idle (d) | CI | In base | Behind | Conflicts | Roll class | Work | Proposed action |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["prs"]:
        flag = lambda value: "?" if value is None else ("yes" if value else "no")
        work = ", ".join(row["work_records"] + [Path(h).name.split("-")[4] if h.count("-") > 4 else h
                                                 for h in row["handoffs"]]) or "-"
        conflicts = flag(row["conflicts"]) + (f" ({len(row['conflicted_files'])})" if row["conflicted_files"] else "")
        lines.append(f"| [#{row['number']}]({row['url']}) {row['title'][:60].replace('|', '/')} | `{row['branch']}` | "
                     f"{row['age_days']} | {row['age_days_since_update']} | {row['ci']} | {flag(row['merged_by_ancestry'])} | "
                     f"{'?' if row['behind_base'] is None else row['behind_base']} | {conflicts} | {row['roll_class'] or '?'} | "
                     f"{work} | **{row['proposed_action']}** |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/master", help="Base ref (default origin/master; fetch it yourself first)")
    parser.add_argument("--limit", type=int, default=100, help="Maximum open PRs listed (1-200; default 100)")
    parser.add_argument("--out", type=Path, default=data_path("pr_hygiene"), help="Output directory (default data/pr_hygiene)")
    args = parser.parse_args(argv)
    if not REF.fullmatch(args.base) or not 1 <= args.limit <= 200:
        print(json.dumps({"error": "pr_hygiene_arguments_refused"}))
        return 2
    try:
        report = build_report(base=args.base, limit=args.limit)
    except (CommandRefused, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": "pr_hygiene_failed", "reason": str(exc)[:120]}))
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(report["generated_at_utc"]).strftime("%Y%m%dT%H%M%SZ")
    for name, text in ((f"pr_hygiene_{stamp}.json", json.dumps(report, indent=1) + "\n"),
                       (f"pr_hygiene_{stamp}.md", render_markdown(report))):
        temp = args.out / (name + ".tmp")
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, args.out / name)
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
