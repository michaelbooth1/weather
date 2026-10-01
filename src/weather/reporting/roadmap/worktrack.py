"""Offline per-record mission registry; no runtime, exchange, or capture IO."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import tempfile

from weather.paths import docs_path


WORKSTREAMS = ("maker", "wallet", "model", "storage", "repo-health", "youtube", "ops", "canon")
STATUSES = ("proposed", "handed-off", "in-progress", "handback-received", "verified", "queued", "landed", "blocked", "dormant", "closed")
OWNERS = ("production", "workstation", "owner")
FIELDS = ("id", "title", "workstream", "status", "owner", "handoff", "handbacks", "branch", "tip", "pr", "roll", "depends_on", "landing_slot", "needs_owner", "item", "questions", "updated", "notes")
DEFAULT_ROOT = docs_path("roadmap", "work")
DEFAULT_DECISIONS = docs_path("operations", "DECISION_LOG.md")
DEFAULT_BOARD = docs_path("roadmap", "work-board.md")
ID_RE = re.compile(r"W-\d{4}\Z")


class RegistryError(ValueError):
    """Invalid registry input; CLI reports it without a traceback."""


def _mapping(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError(f"duplicate YAML key: {key!r}")
        result[key] = value
    return result


def read_yaml(text):
    """Use YAML 1.2's JSON subset, without adding a runtime YAML dependency."""
    try:
        return json.loads(text, object_pairs_hook=_mapping)
    except ValueError as exc:
        raise RegistryError(f"invalid JSON-compatible YAML: {exc}") from exc


def _assignment(value):
    if value.startswith(('{', '[', '"')) or value in ("null", "true", "false"):
        return read_yaml(value)
    return value


def instant(value):
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime.combine(value, datetime.min.time(), timezone.utc)
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            if len(str(value)) != 10:
                raise ValueError("timestamp requires timezone")
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise RegistryError(f"invalid date/timestamp: {value!r}") from exc


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise RegistryError(f"{label}: expected exactly {', '.join(keys)}")


def _text(value, label, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{label}: expected nonempty text")


def validate(record):
    _keys(record, FIELDS, "record (unknown/missing fields)")
    for key in ("id", "title", "workstream", "status", "owner", "roll"):
        _text(record[key], key)
    if not ID_RE.fullmatch(record["id"]):
        raise RegistryError("id must be W-####")
    for key, choices in (("workstream", WORKSTREAMS), ("status", STATUSES), ("owner", OWNERS), ("roll", ("free", "sensitive", "unknown"))):
        if record[key] not in choices:
            raise RegistryError(f"{key}: choose from {', '.join(choices)}")
    for key in ("handoff", "branch", "tip", "pr", "item"):
        _text(record[key], key, nullable=True)
    if record["branch"] and (record["branch"].startswith("origin/") or not re.fullmatch(r"[A-Za-z0-9_./-]+", record["branch"])):
        raise RegistryError("branch must be a branch name without origin/ or whitespace")
    if record["tip"] and not re.fullmatch(r"[0-9a-f]{7,40}", record["tip"]):
        raise RegistryError("tip must be a 7..40 character lowercase Git hash")
    for key in ("handbacks", "depends_on", "needs_owner", "questions", "notes"):
        if not isinstance(record[key], list):
            raise RegistryError(f"{key}: expected list")
    for key in ("depends_on", "questions", "notes"):
        for value in record[key]:
            _text(value, key)
        if len(set(record[key])) != len(record[key]):
            raise RegistryError(f"{key}: duplicate values")
    for dependency in record["depends_on"]:
        if not ID_RE.fullmatch(dependency) or dependency == record["id"]:
            raise RegistryError(f"invalid dependency: {dependency}")
    instant(record["updated"])
    slot = record["landing_slot"]
    if slot is not None:
        _keys(slot, ("date", "window"), "landing_slot")
        try:
            date.fromisoformat(str(slot["date"]))
        except ValueError as exc:
            raise RegistryError("landing_slot.date must be YYYY-MM-DD") from exc
        _text(slot["window"], "landing_slot.window")
    for handback in record["handbacks"]:
        _keys(handback, ("path", "received", "verified"), "handback")
        _text(handback["path"], "handback.path")
        instant(handback["received"])
        if type(handback["verified"]) is not bool:
            raise RegistryError("handback.verified must be boolean")
    if record["status"] == "handback-received" and not record["handbacks"]:
        raise RegistryError("handback-received requires a dated handback")
    for need in record["needs_owner"]:
        _keys(need, ("question", "status", "since", "decision"), "needs_owner entry")
        _text(need["question"], "needs_owner.question")
        if need["status"] not in ("pending", "approved", "declined"):
            raise RegistryError("needs_owner.status must be pending, approved, or declined")
        instant(need["since"])
        if need["decision"] is not None:
            _keys(need["decision"], ("date", "text"), "decision")
            instant(need["decision"]["date"])
            _text(need["decision"]["text"], "decision.text")


def load_records(root=DEFAULT_ROOT):
    root = Path(root)
    if not root.is_dir():
        raise RegistryError(f"registry directory does not exist: {root}")
    records = {}
    for path in sorted(root.glob("*.yaml")):
        record = read_yaml(path.read_text(encoding="utf-8-sig"))
        try:
            validate(record)
        except RegistryError as exc:
            raise RegistryError(f"{path.name}: {exc}") from exc
        if path.stem != record["id"]:
            raise RegistryError(f"{path.name}: filename must match id {record['id']}")
        records[record["id"]] = record
    return records


def graph_issues(records):
    issues = []
    visited, visiting = set(), set()

    def visit(key):
        if key in visiting:
            issues.append(f"{key}: dependency cycle")
            return
        if key in visited:
            return
        visiting.add(key)
        for dep in records[key]["depends_on"]:
            if dep not in records:
                issues.append(f"{key}: dangling depends_on {dep}")
            else:
                visit(dep)
        visiting.remove(key)
        visited.add(key)

    for key in sorted(records):
        visit(key)
    return issues


def decision_rows(path):
    """Match an actual Markdown table row's first two cells, never prose."""
    path = Path(path)
    if not path.exists():
        return set()
    rows = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) >= 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
            rows.add((cells[0], cells[1]))
    return rows


def _approved(need, rows):
    decision = need["decision"]
    return need["status"] == "approved" and decision is not None and (str(decision["date"]), decision["text"]) in rows


def check(records, rows, now):
    issues = graph_issues(records)
    for key, record in sorted(records.items()):
        if instant(record["updated"]) > now:
            issues.append(f"{key}: updated is in the future")
        for need in record["needs_owner"]:
            since = instant(need["since"])
            if since > now:
                issues.append(f"{key}: needs_owner date is in the future")
            if need["status"] == "pending" and now - since > timedelta(days=3):
                issues.append(f"{key}: needs_owner older than 3 days: {need['question']}")
            if need["status"] == "approved" and not _approved(need, rows):
                issues.append(f"{key}: approved needs_owner has no matching DECISION_LOG row: {need['question']}")
        for handback in record["handbacks"]:
            received = instant(handback["received"])
            if received > now:
                issues.append(f"{key}: handback received in the future")
            if record["status"] == "handback-received" and not handback["verified"] and now - received > timedelta(days=2):
                issues.append(f"{key}: handback-received unverified for more than 2 days: {handback['path']}")
    return issues


def blockers(record, records, rows):
    reasons = []
    if record["status"] not in ("verified", "queued"):
        reasons.append(f"status {record['status']}")
    if record["branch"] is None or record["tip"] is None:
        reasons.append("branch/tip missing")
    if record["roll"] == "unknown":
        reasons.append("roll unknown")
    if any(not hb["verified"] for hb in record["handbacks"]):
        reasons.append("unverified handback")
    for dep in record["depends_on"]:
        if dep not in records or records[dep]["status"] not in ("landed", "closed"):
            reasons.append(f"waiting for {dep}")
    for need in record["needs_owner"]:
        if not _approved(need, rows):
            reasons.append(f"owner: {need['question']}")
    return reasons


def _cell(value):
    return str(value or "—").replace("|", "\\|").replace("\n", "<br>").replace("\r", "")


def _table(records):
    lines = ["| Work | Title | Owner | Branch / tip | Slot |", "| --- | --- | --- | --- | --- |"]
    for record in records:
        slot = record["landing_slot"]
        values = (record["id"], record["title"], record["owner"], f"{record['branch'] or '—'} @ {record['tip'] or '—'}", f"{slot['date']} {slot['window']}" if slot else None)
        lines.append("| " + " | ".join(map(_cell, values)) + " |")
    return lines if records else ["None."]


def night_plan(records, rows, night):
    """Proposal only: dependencies must already be landed/closed, never assumed."""
    lines = [f"# Work night plan {night}", "", "Generated proposal; production must re-run roll_verdict and its landing gates.", ""]
    for record in sorted(records.values(), key=lambda row: row["id"]):
        slot = record["landing_slot"]
        if slot and str(slot["date"]) == str(night):
            why = blockers(record, records, rows)
            lines += [f"- {record['id']} — {_cell(record['title'])} ({slot['window']}): " + ("BLOCKED: " + "; ".join(why) if why else "READY for production review")]
    return "\n".join(lines) + "\n"


def board(records, rows, now, night):
    issues = check(records, rows, now)
    lines = ["# Work board", "", "Generated by `python -m weather.reporting.roadmap.worktrack board` in production's docs step.", f"As of {now.isoformat()}; tonight = {night}. Read records for evidence and scope.", "", "## Registry checks", ""]
    lines += [f"- {_cell(issue)}" for issue in issues] or ["PASS"]
    for field, choices, title in (("status", STATUSES, "By status"), ("workstream", WORKSTREAMS, "Per workstream")):
        lines += ["", f"## {title}"]
        for choice in choices:
            group = [r for _, r in sorted(records.items()) if r[field] == choice]
            if group:
                lines += ["", f"### {choice}", ""] + _table(group)
    lines += ["", "## Waiting on owner", ""]
    waiting = [f"- {key}: {_cell(need['question'])} ({need['status']}, since {need['since']})" for key, record in sorted(records.items()) for need in record["needs_owner"] if need["status"] == "pending" or (need["status"] == "approved" and not _approved(need, rows))]
    lines += waiting or ["None."]
    lines += ["", "## Ready to land tonight", ""]
    ready = [r for _, r in sorted(records.items()) if r["landing_slot"] and str(r["landing_slot"]["date"]) == str(night) and not blockers(r, records, rows)]
    lines += _table(ready) if not issues else ["Registry check failed; resolve the issues above before declaring readiness."]
    return "\n".join(lines) + "\n"


def handoff_prompt(record):
    if not record["branch"] or not record["handoff"]:
        raise RegistryError(f"{record['id']}: branch and handoff required; author the handoff first")
    return f"Execute {record['id']} from origin/{record['branch']} (tip {record['tip'] or 'not pinned'}). Read {record['handoff']}. Update this work record and link the handback; follow the delegation contract.\n"


def new_record(key, title, workstream, owner, now):
    record = dict.fromkeys(FIELDS)
    record.update(id=key, title=title, workstream=workstream, owner=owner, status="proposed", roll="unknown", updated=now.isoformat())
    for field in ("handbacks", "depends_on", "needs_owner", "questions", "notes"):
        record[field] = []
    validate(record)
    return record


def write_record(root, record, *, create=False):
    validate(record)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{record['id']}.yaml"
    text = json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n"
    if create:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        return
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=root, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--decision-log", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--now", help="Explicit UTC timestamp/date for reproducible checks")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new")
    new.add_argument("--id")
    new.add_argument("--title", required=True)
    new.add_argument("--workstream", required=True, choices=WORKSTREAMS)
    new.add_argument("--owner", default="workstation", choices=OWNERS)
    change = commands.add_parser("set")
    change.add_argument("id")
    change.add_argument("assignments", nargs="*", help="FIELD=text or FIELD=JSON (quote the entire argument)")
    change.add_argument("--file", type=Path, help="JSON-compatible YAML mapping patch for nested values")
    link = commands.add_parser("link")
    link.add_argument("id")
    link.add_argument("field", choices=("handoff", "handbacks", "branch", "pr", "depends_on", "item", "questions"))
    link.add_argument("value")
    commands.add_parser("check")
    render = commands.add_parser("board")
    render.add_argument("--actor", required=True, choices=("production",), help="Production docs step only; declared role, not host authentication")
    render.add_argument("--output", type=Path, default=DEFAULT_BOARD)
    render.add_argument("--night", type=date.fromisoformat, required=True)
    night = commands.add_parser("night-plan")
    night.add_argument("--night", type=date.fromisoformat, required=True)
    prompt = commands.add_parser("handoff-prompt")
    prompt.add_argument("id")
    args = parser.parse_args(argv)
    try:
        now = instant(args.now) if args.now else datetime.now(timezone.utc)
        records = load_records(args.root) if args.root.exists() or args.command != "new" else {}
        rows = decision_rows(args.decision_log)
        if args.command in ("new", "set", "link"):
            if args.command == "new":
                key = args.id or f"W-{max((int(k[2:]) for k in records), default=0) + 1:04d}"
                record = new_record(key, args.title, args.workstream, args.owner, now)
            else:
                if args.id not in records:
                    raise RegistryError(f"unknown work id: {args.id}")
                record = deepcopy(records[args.id])
                if args.command == "set":
                    patch = read_yaml(args.file.read_text(encoding="utf-8-sig")) if args.file else {}
                    if not isinstance(patch, dict):
                        raise RegistryError("patch must be a mapping")
                    for assignment in args.assignments:
                        key, separator, value = assignment.partition("=")
                        if not separator or key in patch:
                            raise RegistryError(f"invalid/duplicate assignment: {assignment}")
                        patch[key] = _assignment(value)
                    if not patch or set(patch) - (set(FIELDS) - {"id", "updated"}):
                        raise RegistryError("patch empty or has unknown/immutable fields (id, updated)")
                    record.update(patch)
                elif args.field == "handbacks":
                    if not any(hb["path"] == args.value for hb in record["handbacks"]):
                        record["handbacks"].append(dict(path=args.value, received=now.isoformat(), verified=False))
                        record["status"] = "handback-received"
                elif isinstance(record[args.field], list):
                    if args.value not in record[args.field]:
                        record[args.field].append(args.value)
                else:
                    record[args.field] = args.value
                record["updated"] = now.isoformat()
            validate(record)
            proposed = dict(records, **{record["id"]: record})
            errors = graph_issues(proposed)
            if errors:
                raise RegistryError("; ".join(errors))
            write_record(args.root, record, create=args.command == "new")
            print(record["id"])
        elif args.command == "check":
            errors = check(records, rows, now)
            print("\n".join(errors) if errors else f"PASS: {len(records)} work records")
            return int(bool(errors))
        elif args.command == "board":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(board(records, rows, now, args.night), encoding="utf-8")
            print(args.output)
            return int(bool(check(records, rows, now)))
        elif args.command == "night-plan":
            errors = check(records, rows, now)
            if errors:
                raise RegistryError("; ".join(errors))
            print(night_plan(records, rows, args.night), end="")
        else:
            if args.id not in records:
                raise RegistryError(f"unknown work id: {args.id}")
            print(handoff_prompt(records[args.id]), end="")
    except (RegistryError, OSError) as exc:
        print(f"worktrack: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
