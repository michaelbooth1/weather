"""Generate the correspondence inventory from source text and Git addition history.

The inventory is sharded by Git-added month (``correspondence-index/<YYYY-MM>.md``)
under a small root that only lists the months, so a new report touches its own
month's shard (and the root only when a new month starts). Rows not yet committed
land in ``uncommitted.md`` until the report's first commit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

from weather.paths import REPO_ROOT

OUTPUT = "docs/roadmap/correspondence-index.md"
SHARD_DIR = "docs/roadmap/correspondence-index"
UNCOMMITTED = "uncommitted"
NAME_RE = re.compile(
    r"^(workstation-handoff|agent-report|agent-work-order)-"
    r"(\d{4}-\d{2}-\d+[a-z]*)(?:-.*)?\.md$"
)
KINDS = {"workstation-handoff": "handoff", "agent-report": "report", "agent-work-order": "work order"}
SECTION_ID = r"\d+[a-z]*(?:-bis)?"
EF_RE = re.compile(
    rf"\b(?:EF|ESTABLISHED_FINDINGS(?:\.md)?)\s*§\s*{SECTION_ID}"
    rf"(?:\s*(?:,|and|&)\s*§\s*{SECTION_ID})*", re.I,
)


def ef_sections(text: str) -> list[str]:
    """Include shorthand continuations (EF §1, §1c), but never RF/HW sections."""
    prose = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text).replace("`", "").replace("*", "")
    sections = {section.lower() for group in EF_RE.findall(prose)
                for section in re.findall(rf"§\s*({SECTION_ID})", group, re.I)}
    sections.update(re.findall(rf"ESTABLISHED_FINDINGS\.md#({SECTION_ID})(?=-|\))", text, re.I))
    return sorted(sections, key=lambda section: (int(re.match(r"\d+", section)[0]), section))


def git_added_dates(repo_root: Path) -> dict[str, str]:
    """One bounded history query; never substitute filename dates or the clock."""
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args], capture_output=True,
            text=True, encoding="utf-8", check=False,
        )
        if result.returncode:
            raise ValueError(f"correspondence history unavailable: {result.stderr.strip()}")
        return result.stdout

    if git("rev-parse", "--is-shallow-repository").strip() == "true":
        raise ValueError("correspondence history is shallow; fetch full history before generation/check")
    history = git(
        "-c", "core.quotepath=false", "log", "--reverse", "--diff-filter=A",
        "--no-renames", "--format=@%ad", "--date=short", "--name-only", "--",
        "docs/roadmap/workstation-handoff-*.md", "docs/roadmap/agent-report-*.md",
        "docs/roadmap/agent-work-order-*.md",
    )
    dates: dict[str, str] = {}
    date = ""
    for line in history.splitlines():
        if re.fullmatch(r"@\d{4}-\d{2}-\d{2}", line):
            date = line[1:]
        elif line.startswith("docs/roadmap/") and date:
            dates.setdefault(line, date)
    return dates


def correspondence_rows(repo_root: Path, dates: dict[str, str]) -> list[dict[str, str]]:
    rows = []
    for path in sorted((repo_root / "docs/roadmap").glob("*.md")):
        match = NAME_RE.fullmatch(path.name)
        if not match:
            if path.name.startswith(tuple(f"{prefix}-" for prefix in KINDS)):
                raise ValueError(f"unparseable correspondence filename: {path.name}")
            continue
        text = path.read_text(encoding="utf-8-sig")
        title = re.search(r"^#\s+(.+?)\s*#*\s*$", text, re.M)
        items = set(re.findall(r"\bitem-(\d+)(?:-|\b)", text, re.I))
        for group in re.findall(r"\bitems?\s+\d+(?:\s*[,/]\s*\d+)*", text, re.I):
            items.update(re.findall(r"\d+", group))
        rows.append({
            "name": path.name, "id": match[2], "kind": KINDS[match[1]],
            "title": title[1] if title else "(no H1 in source)",
            "added": dates.get(path.relative_to(repo_root).as_posix(), "uncommitted"),
            "ef": ", ".join(ef_sections(text)) or "—",
            "items": ", ".join(sorted(items, key=int)) or "—",
        })
    # Actual addition date is the chronology. Filenames only break same-day ties.
    return sorted(rows, key=lambda row: (row["added"], row["name"]))


def _shard_key(row: dict[str, str]) -> str:
    return UNCOMMITTED if row["added"] == UNCOMMITTED else row["added"][:7]


def _cell(text: str) -> str:
    return text.replace("&", "&amp;").replace("|", "&#124;").replace("[", "&#91;").replace("]", "&#93;").replace("<", "&lt;").replace(">", "&gt;")


def render_outputs(repo_root: Path, dates: dict[str, str] | None = None) -> dict[str, str]:
    """Every generated file (the root index and one shard per month), keyed by repo-relative path."""
    rows = correspondence_rows(repo_root, git_added_dates(repo_root) if dates is None else dates)
    reports: dict[str, list[str]] = {}
    shards: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row["kind"] == "report":
            reports.setdefault(row["id"], []).append(row["name"])
        shards.setdefault(_shard_key(row), []).append(row)

    def link(name: str, label: str) -> str:
        return f"[{_cell(label)}](../{quote(name)})"

    keys = sorted(key for key in shards if key != UNCOMMITTED)
    keys += [UNCOMMITTED] if UNCOMMITTED in shards else []
    root = [
        "# Correspondence index", "",
        "Generated by `python -m weather.reporting.roadmap.correspondence_index`; do not hand-edit.",
        "Use `--check` for read-only parity. Full Git history is required; added dates are Git author dates,",
        "not mission labels. One shard per Git-added month; rows sort by added date, then filename.",
        "Same-id reports are candidates, not proof of acceptance; legacy collisions may have several answers.",
        "Citations are extracted, not validated historical claims. `uncommitted` lists files not yet",
        "committed; regenerate after their first commit.", "",
        *[f"- [{key}](correspondence-index/{key}.md)" for key in keys],
    ]
    outputs = {OUTPUT: "\n".join(root) + "\n"}
    for key in keys:
        lines = [
            f"# Correspondence index: {key}", "",
            "Generated shard of the [correspondence index](../correspondence-index.md); do not hand-edit.", "",
            "| Mission id | Type | Title / source | Git-added date | Answering report (same id) | EF sections cited | Items cited |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in shards[key]:
            answers = "; ".join(link(name, name) for name in reports.get(row["id"], [])) or "none in tree"
            lines.append(f"| {row['id']} | {row['kind']} | {link(row['name'], row['title'])} | {row['added']} | {answers} | {row['ef']} | {row['items']} |")
        outputs[f"{SHARD_DIR}/{key}.md"] = "\n".join(lines) + "\n"
    return outputs


def _existing_shards(repo_root: Path) -> set[str]:
    folder = repo_root / SHARD_DIR
    return {f"{SHARD_DIR}/{path.name}" for path in folder.glob("*.md")} if folder.is_dir() else set()


def parity_errors(repo_root: Path) -> list[str]:
    try:
        expected = render_outputs(repo_root)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    errors = []
    for relative, content in expected.items():
        path = repo_root / relative
        if not path.is_file() or path.read_text(encoding="utf-8-sig") != content:
            errors.append(f"{relative}: stale or missing; run python -m weather.reporting.roadmap.correspondence_index")
    for relative in sorted(_existing_shards(repo_root) - set(expected)):
        errors.append(f"{relative}: no longer generated; run python -m weather.reporting.roadmap.correspondence_index")
    return errors


def write_outputs(repo_root: Path) -> list[str]:
    """Write only files whose content changed; remove shards that are no longer generated."""
    expected = render_outputs(repo_root)
    changed = []
    for relative, content in expected.items():
        path = repo_root / relative
        if path.is_file() and path.read_text(encoding="utf-8-sig") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        changed.append(relative)
    for relative in sorted(_existing_shards(repo_root) - set(expected)):
        (repo_root / relative).unlink()
        changed.append(relative)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    if args.check:
        errors = parity_errors(root)
        print("\n".join(errors) if errors else "Correspondence index: OK")
        return int(bool(errors))
    try:
        changed = write_outputs(root)
    except (OSError, ValueError) as exc:
        print(str(exc))
        return 1
    print("\n".join(f"Wrote {relative}" for relative in changed) or "Correspondence index: unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
