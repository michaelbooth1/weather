"""Completeness and generated-view checks for the agent knowledge indexes."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from weather.reporting.roadmap import correspondence_index, roadmap_backlog

OPS = "docs/operations/"
EF = OPS + "ESTABLISHED_FINDINGS.md"
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def visible_text(text: str) -> str:
    """Blank fenced code while preserving all prose and line boundaries.

    PowerShell casts such as ``[string](...)`` have Markdown-link syntax but
    are executable examples, not links. Link auditing fenced code therefore
    produces false missing-file findings. Supporting both CommonMark fence
    characters and longer closing fences keeps the scanner deterministic
    without trying to parse the rest of Markdown.
    """
    fence: tuple[str, int] | None = None
    visible: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        indent = len(body) - len(body.lstrip(" "))
        candidate = body[indent:] if indent <= 3 else ""
        marker = candidate[:1]
        run_length = 0
        if marker in {"`", "~"}:
            run_length = len(candidate) - len(candidate.lstrip(marker))

        if fence is None:
            if run_length >= 3:
                fence = (marker, run_length)
                visible.append("\n" if line.endswith(("\n", "\r")) else "")
            else:
                visible.append(line)
            continue

        if (
            marker == fence[0]
            and run_length >= fence[1]
            and not candidate[run_length:].strip()
        ):
            fence = None
        visible.append("\n" if line.endswith(("\n", "\r")) else "")
    return "".join(visible)


def headings(text: str) -> list[str]:
    return re.findall(r"^#{1,6}\s+(.+?)(?:\s+#+)?\s*$", visible_text(text), re.M)


def anchors(text: str) -> set[str]:
    """GitHub heading slugs, including duplicate-heading suffixes and explicit ids."""
    result = set(re.findall(r'<(?:a|h[1-6])\b[^>]*\bid=[\"\']([^\"\']+)', text, re.I))
    counts: dict[str, int] = {}
    for heading in headings(text):
        heading = re.sub(r"<[^>]+>", "", heading).lower()
        slug = re.sub(r"[^\w\-\s]", "", heading).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(f"{slug}-{count}" if count else slug)
    return result


def table_rows(text: str) -> list[tuple[int, list[str]]]:
    result = []
    for number, line in enumerate(visible_text(text).splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if cells and not all(re.fullmatch(r"[:\-\s]+", cell) for cell in cells):
            result.append((number, cells))
    return result


def read_required(root: Path, relative: str, errors: list[str]) -> str:
    path = root / relative
    if not path.is_file():
        errors.append(f"{relative}: missing knowledge index source")
        return ""
    return visible_text(path.read_text(encoding="utf-8-sig"))


def audit_index_errors(root: Path) -> list[str]:
    errors: list[str] = []
    relative = "docs/roadmap/audits/README.md"
    text = read_required(root, relative, errors)
    directory = root / "docs/roadmap/audits"
    indexed = set()
    for _, cells in table_rows(text):
        for target in LINK_RE.findall(" | ".join(cells)):
            indexed.add((directory / unquote(target.split("#", 1)[0])).resolve())
    for path in sorted(directory.iterdir()) if directory.is_dir() else []:
        if path.name == "README.md" or not (path.is_dir() or path.suffix == ".md"):
            continue
        if path.resolve() not in indexed:
            errors.append(f"{relative}: missing audit row for {path.name}")
    return errors


def ef_citation_errors(root: Path) -> list[str]:
    errors: list[str] = []
    ef = read_required(root, EF, errors)
    digest_path = OPS + "FINDINGS_DIGEST.md"
    digest = read_required(root, digest_path, errors)
    ids = {match[1].lower() for heading in headings(ef)
           if (match := re.match(rf"^({correspondence_index.SECTION_ID})\.", heading, re.I))}
    for section in correspondence_index.ef_sections(digest):
        if section not in ids:
            errors.append(f"{digest_path}: dangling EF §{section} (no EF heading)")
    return errors


def question_errors(root: Path) -> list[str]:
    errors: list[str] = []
    relative = OPS + "OPEN_QUESTIONS.md"
    text = read_required(root, relative, errors)
    ef = read_required(root, EF, errors)
    ef_ids = {match[1].lower() for heading in headings(ef)
              if (match := re.match(rf"^({correspondence_index.SECTION_ID})\.", heading, re.I))}
    seen = set()
    for number, cells in table_rows(text):
        if cells[0].lower() == "id":
            continue
        question_id = cells[0].strip("`* ")
        label = f"{relative}:{number}"
        if not re.fullmatch(r"Q-\d{2}", question_id):
            errors.append(f"{label}: invalid question id {question_id!r}; expected Q-nn")
        if question_id in seen:
            errors.append(f"{label}: duplicate question id {question_id}")
        seen.add(question_id)
        answer_links = set(LINK_RE.findall(cells[-1]))
        ef_answer_link = False
        for target in LINK_RE.findall(" | ".join(cells)):
            parts = urlsplit(target.strip("<>"))
            if parts.scheme or parts.netloc:
                continue
            path = ((root / relative).parent / unquote(parts.path)).resolve() if parts.path else root / relative
            try:
                path.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{label}: pointer escapes repository: {target}")
                continue
            if not path.exists():
                errors.append(f"{label}: missing pointer: {target}")
                continue
            if parts.fragment:
                if not path.is_file() or unquote(parts.fragment) not in anchors(path.read_text(encoding="utf-8-sig")):
                    errors.append(f"{label}: missing pointer anchor: {target}")
                    continue
                if path == (root / EF).resolve() and target in answer_links:
                    ef_answer_link = True
        sections = correspondence_index.ef_sections(" | ".join(cells))
        for section in sections:
            if section not in ef_ids:
                errors.append(f"{label}: dangling EF §{section}")
        status = cells[-1]
        if re.match(r"\W*ANSWERED\b", status, re.I):
            answer_sections = correspondence_index.ef_sections(status)
            # A citation elsewhere in the evidence columns cannot stand in for an answer.
            if not any(section in ef_ids for section in answer_sections) and not ef_answer_link:
                errors.append(f"{label}: ANSWERED row must cite an existing EF anchor in its status")
    return errors


def decision_errors(root: Path) -> list[str]:
    errors: list[str] = []
    state = read_required(root, OPS + "STATE_OF_PLAY.md", errors)
    log = read_required(root, OPS + "DECISION_LOG.md", errors)
    dates = {cells[0] for _, cells in table_rows(log)
             if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", cells[0])}
    for date in sorted(set(re.findall(r"\bOwner\s+(20\d{2}-\d{2}-\d{2})\b", state, re.I))):
        if date not in dates:
            errors.append(f"{OPS}DECISION_LOG.md: no dated decision row for Owner {date} in STATE_OF_PLAY.md")
    return errors


def generated_index_errors(root: Path) -> list[str]:
    errors = correspondence_index.parity_errors(root)
    # Share exactly the CLI's --check parity and --fail-on-lint implementation, without writes.
    payload = roadmap_backlog.build_payload(root / "docs/roadmap")
    if payload["status"] != "OK":
        errors.append("docs/roadmap/active-backlog.md: roadmap_backlog --fail-on-lint failed")
    if roadmap_backlog.markdown_parity_diff(root / "docs/roadmap/active-backlog.md", payload):
        errors.append("docs/roadmap/active-backlog.md: stale or missing; run roadmap_backlog --fail-on-lint")
    return errors


def knowledge_structure_errors(root: Path) -> list[str]:
    return [error for check in (audit_index_errors, ef_citation_errors, question_errors,
                                decision_errors, generated_index_errors) for error in check(root)]
