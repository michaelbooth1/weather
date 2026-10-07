"""Generate the correspondence inventory from source text and Git addition history.

The inventory is sharded by Git-added month (``correspondence-index/<YYYY-MM>.md``)
under a small root that only lists the months, so a new report touches its own
month's shard (and the root only when a new month starts). Rows not yet committed
land in ``uncommitted.md`` until the report's first commit.

Branches never commit this output (it conflicted whenever two PRs touched the
same month: the answers column rewrites sibling rows). The closeout regenerates
it once after the night's landings, as a docs light-path commit. So there are
two checks:

- ``--check-structure`` (PR CI, the bounded suite, ``agent_docs_audit``): every
  committed row matches its source and sits in order in the right shard; a
  source without a row yet is allowed and counted as pending; an answers cell
  may lag (list a subset of the same-id reports) but never name a wrong one.
- ``--check`` (strict, closeout and ``documentation_transaction complete``):
  full byte parity.
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
        "Branches do not commit this output; the closeout regenerates it after landings.",
        "`--check` is strict parity, `--check-structure` the branch check. Full Git history is required; added dates are Git author dates,",
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


LINK_RE = re.compile(r"\[[^\]]*\]\(\.\./([^)]+)\)")
ROOT_LINK_RE = re.compile(r"^- \[([^\]]+)\]\(correspondence-index/([^)]+)\.md\)$")
TABLE_RULE = "| --- | --- | --- | --- | --- | --- | --- |"


def _split_shard(text: str) -> tuple[list[str], list[str]]:
    lines = text.rstrip("\n").split("\n")
    if TABLE_RULE not in lines:
        return lines, []
    cut = lines.index(TABLE_RULE) + 1
    return lines[:cut], lines[cut:]


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split(" | ")]


def _source_name(line: str) -> str | None:
    cells = _cells(line)
    if len(cells) != 7:
        return None
    match = LINK_RE.search(cells[2])
    return match[1] if match else None


def _answer_names(cell: str) -> list[str] | None:
    if cell == "none in tree":
        return []
    names = LINK_RE.findall(cell)
    return names or None


def structural_check(repo_root: Path) -> tuple[list[str], int]:
    """Branch check: committed rows are correct, missing rows are pending.

    Returns ``(errors, pending_rows)``. Never writes.
    """
    try:
        expected = render_outputs(repo_root)
    except (OSError, ValueError) as exc:
        return [str(exc)], 0
    fix = "run python -m weather.reporting.roadmap.correspondence_index (closeout) or drop the hunk"
    errors: list[str] = []
    expected_rows: dict[str, tuple[str, int, str]] = {}  # source -> (shard, position, line)
    for relative, content in expected.items():
        if relative == OUTPUT:
            continue
        for position, line in enumerate(_split_shard(content)[1]):
            expected_rows[_source_name(line)] = (relative, position, line)

    present = 0
    for relative in sorted(_existing_shards(repo_root)):
        text = (repo_root / relative).read_text(encoding="utf-8-sig")
        header, rows = _split_shard(text)
        if relative not in expected:
            errors.append(f"{relative}: no longer generated; {fix}")
            continue
        if header != _split_shard(expected[relative])[0]:
            errors.append(f"{relative}: header differs from the generator; {fix}")
        last = -1
        seen: set[str] = set()
        for line in rows:
            name = _source_name(line)
            where = expected_rows.get(name)
            if name is None or where is None:
                errors.append(f"{relative}: row has no source in tree: {line[:80]}")
                continue
            if name in seen:
                errors.append(f"{relative}: duplicate row for {name}")
                continue
            seen.add(name)
            shard, position, wanted = where
            if shard != relative:
                errors.append(f"{relative}: row for {name} belongs in {shard}")
                continue
            have, want = _cells(line), _cells(wanted)
            answers, wanted_answers = _answer_names(have[4]), _answer_names(want[4])
            if answers is None or not set(answers) <= set(wanted_answers or []):
                errors.append(f"{relative}: answers for {name} name a report that does not share its id")
            elif have[:4] + have[5:] != want[:4] + want[5:]:
                errors.append(f"{relative}: row for {name} differs from its source; {fix}")
            if position < last:
                errors.append(f"{relative}: row for {name} is out of order")
            last = max(last, position)
            present += 1

    root = repo_root / OUTPUT
    if root.is_file():
        keys = [match[2] for line in root.read_text(encoding="utf-8-sig").splitlines()
                if (match := ROOT_LINK_RE.match(line))]
        expected_keys = [match[2] for line in expected[OUTPUT].splitlines()
                         if (match := ROOT_LINK_RE.match(line))]
        for key in keys:
            if key not in expected_keys:
                errors.append(f"{OUTPUT}: lists {key}, which is no longer generated; {fix}")
            elif not (repo_root / SHARD_DIR / f"{key}.md").is_file():
                errors.append(f"{OUTPUT}: lists {key}, whose shard is missing")
        listed = [key for key in keys if key in expected_keys]
        if listed != [key for key in expected_keys if key in listed]:
            errors.append(f"{OUTPUT}: months are out of order")
    return errors, len(expected_rows) - present


def structural_errors(repo_root: Path) -> list[str]:
    return structural_check(repo_root)[0]


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="strict byte parity (closeout, master)")
    mode.add_argument("--check-structure", action="store_true",
                      help="branch check: committed rows correct; missing rows are pending")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    if args.check_structure:
        errors, pending = structural_check(root)
        print("\n".join(errors) if errors else
              f"Correspondence index: structure OK ({pending} rows pending closeout regeneration)")
        return int(bool(errors))
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
