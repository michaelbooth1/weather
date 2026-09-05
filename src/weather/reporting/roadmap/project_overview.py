"""Project context from the canonical state note and maker work ledger."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from weather.paths import REPO_ROOT


MAKER_ITEM = "docs/roadmap/items/item-330-maker-economics-refocus-master-plan.md"


def _read(path):
    try:
        if path.stat().st_size > 256 * 1024:
            return ""
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""


def _section(text, heading):
    match = re.search(r"^## " + re.escape(heading) + r"\s*\n(.*?)(?=^## |\Z)",
                      text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def collect_project_overview(repo_root=REPO_ROOT):
    root = Path(repo_root)
    state = _read(root / "docs/operations/STATE_OF_PLAY.md")
    maker = _read(root / MAKER_ITEM)
    objective = re.search(r"\*\*Objectives?:\*\*\s*(.*?)(?:\n\n|\Z)", state, re.DOTALL)
    updated = re.search(r"\*\*Last rewritten:\s*(.*?)\*\*", state)
    critical = next((_section(state, heading) for heading in (
        "Ordered non-live critical path", "Ordered critical path", "Critical path",
    ) if _section(state, heading)), "")
    steps = [" ".join(part.split()) for part in re.split(r"^\d+\.\s+", critical,
              flags=re.MULTILINE)[1:]]
    names = dict(re.findall(r"^### (W\d+) [—–-] (.+)$", maker, re.MULTILINE))
    workstreams = []
    for line in maker.splitlines():
        if not re.match(r"^\| W\d+", line):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) != 3:
            continue
        code, evidence, next_action = cells
        status = re.match(r"^(PARTIAL|COMPLETE|OPEN|BLOCKED)\b", evidence)
        workstreams.append({"code": code, "title": names.get(code, code),
                            "status": status.group(1) if status else "Recorded update",
                            "evidence": evidence, "next_action": next_action})
    source = {"head": None, "dirty": None, "commits": []}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "-8", "--format=%H%x09%cs%x09%s"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=3, check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    source["commits"].append(dict(zip(("sha", "date", "title"), parts)))
            if source["commits"]:
                source["head"] = source["commits"][0]["sha"]
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3, check=False,
        )
        if status.returncode == 0:
            source["dirty"] = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return {"available": bool(state), "updated": updated.group(1) if updated else None,
            "objective": " ".join(objective.group(1).split()) if objective else "Project objective is not recorded.",
            "next_steps": steps[:5], "workstreams": workstreams,
            "source": source, "root": str(root)}
