"""Bounded recent settlement-hole check for the production status monitor."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from weather.paths import REPO_ROOT
from weather.schema_registry import schema_version


def tail_lines(path: Path, count: int, *, chunk_bytes: int = 1024 * 1024) -> list[str]:
    """Return up to ``count`` UTF-8 lines by seeking from EOF, not scanning the file."""
    if count <= 0:
        return []
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        blocks: list[bytes] = []
        newlines = 0
        while position > 0 and newlines <= count:
            take = min(chunk_bytes, position)
            position -= take
            handle.seek(position)
            block = handle.read(take)
            blocks.append(block)
            newlines += block.count(b"\n")
    lines = b"".join(reversed(blocks)).splitlines()
    if position > 0 and lines:
        lines = lines[1:]
    return [line.decode("utf-8", errors="replace") for line in lines[-count:]]


def _settled_dates(lines: Iterable[str], start: date, end: date) -> dict[str, bool]:
    seen: dict[str, bool] = {}
    for line in lines:
        try:
            record: dict[str, Any] = json.loads(line)
            target_text = str(record.get("target_date") or "")
            target = date.fromisoformat(target_text)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not start <= target < end:
            continue
        source = str(record.get("settlement_source") or "")
        seen[target_text] = bool(
            source and source != "none" and record.get("settlement_high") is not None
        )
    return seen


def check_settlement_holes(
    repo_root: Path,
    *,
    now: datetime | None = None,
    window_days: int = 14,
    tail_line_count: int = 400,
) -> dict[str, Any]:
    local_now = now or datetime.now().astimezone()
    today = local_now.date()
    start = today - timedelta(days=window_days)
    root = Path(repo_root).resolve() / "data" / "settlements"
    markets: dict[str, dict[str, bool]] = {}
    errors: list[str] = []
    if root.is_dir():
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            ledger = directory / "ledger.jsonl"
            if not ledger.is_file():
                continue
            try:
                markets[directory.name] = _settled_dates(
                    tail_lines(ledger, tail_line_count), start, today
                )
            except OSError as exc:
                errors.append(f"{directory.name}:{type(exc).__name__}")

    holes: list[dict[str, Any]] = []
    for days_ago in range(window_days, 0, -1):
        target = today - timedelta(days=days_ago)
        if days_ago == 1 and local_now.hour < 12:
            continue
        key = target.isoformat()
        missing = sorted(name for name, seen in markets.items() if not seen.get(key, False))
        if missing:
            holes.append({"date": key, "markets": len(missing), "missing_markets": missing})

    return {
        "schema_version": schema_version("settlement_hole_check"),
        "checked_at": local_now.isoformat(),
        "window_days": window_days,
        "tail_lines": tail_line_count,
        "market_count": len(markets),
        "holes": holes,
        "errors": errors,
        "ok": not errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--window-days", type=int, default=14)
    parser.add_argument("--tail-lines", type=int, default=400)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = check_settlement_holes(
        args.repo_root,
        window_days=args.window_days,
        tail_line_count=args.tail_lines,
    )
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("PASS" if result["ok"] and not result["holes"] else "ATTENTION")
        for hole in result["holes"]:
            print(f"{hole['date']}: {hole['markets']} market(s) missing")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
