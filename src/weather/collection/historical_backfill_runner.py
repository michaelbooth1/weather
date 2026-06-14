"""Run item-29 historical backfill plans with durable resume state.

The planner says which source chunks are still missing. This runner executes
those concrete commands in bounded batches and records each attempt in an
append-only JSONL ledger so interrupted backfills can continue without guessing.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "historical_backfill_run_v1"
STATUS_SCHEMA_VERSION = "historical_backfill_status_v1"
DEFAULT_PLAN = Path("data") / "backtest" / "historical_backfill_plan.json"
DEFAULT_STATE = Path("data") / "backtest" / "historical_backfill_runs.jsonl"
DEFAULT_SUMMARY = Path("data") / "backtest" / "historical_backfill_run_summary.json"
SUCCESS = "success"
FAILED = "failed"


def utc_now():
    return datetime.now(timezone.utc)


def parse_csv(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def read_plan(path=DEFAULT_PLAN):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def command_text(command):
    return subprocess.list2cmdline([str(part) for part in command])


def item_key(item):
    stable = {
        "source": item.get("source"),
        "market_id": item.get("market_id"),
        "station": item.get("station"),
        "detail": item.get("detail"),
        "command": item.get("command"),
    }
    blob = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def tail_text(value, max_chars=4000):
    text = value or ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def load_state(path=DEFAULT_STATE):
    path = Path(path)
    latest = {}
    events = []
    if not path.exists():
        return latest, events
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = row.get("item_key")
            if not key:
                continue
            events.append(row)
            latest[key] = row
    return latest, events


def append_event(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def source_market_key(item):
    return f"{item.get('source')}:{item.get('market_id')}"


def queue_counts(items):
    by_source = Counter(item.get("source") for item in items)
    by_market_source = Counter(source_market_key(item) for item in items)
    return {
        "by_source": dict(sorted(by_source.items())),
        "by_market_source": dict(sorted(by_market_source.items())),
    }


def filter_items(items, sources=None, markets=None):
    sources = set(sources or [])
    markets = set(markets or [])
    selected = []
    for item in items:
        if sources and item.get("source") not in sources:
            continue
        if markets and item.get("market_id") not in markets:
            continue
        selected.append(item)
    return selected


def status_summary(plan_path=DEFAULT_PLAN, state_path=DEFAULT_STATE, sources=None, markets=None):
    plan = read_plan(plan_path)
    items = filter_items(plan.get("queue", []), sources=sources, markets=markets)
    latest, events = load_state(state_path)
    succeeded = set()
    failed = set()
    status_by_source = defaultdict(Counter)
    for item in items:
        key = item_key(item)
        row = latest.get(key)
        status = row.get("status") if row else "not_started"
        if status == SUCCESS:
            succeeded.add(key)
        elif status == FAILED:
            failed.add(key)
        status_by_source[item.get("source")][status] += 1
    remaining = [item for item in items if item_key(item) not in succeeded]
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "plan_path": str(plan_path),
        "state_path": str(state_path),
        "queue_count": len(items),
        "queue_counts": queue_counts(items),
        "event_count": len(events),
        "success_count": len(succeeded),
        "failed_count": len(failed),
        "remaining_count": len(remaining),
        "remaining_counts": queue_counts(remaining),
        "status_by_source": {
            source: dict(sorted(counts.items()))
            for source, counts in sorted(status_by_source.items())
        },
    }


def write_summary(path, payload):
    if not path:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_item(item, state_path, run_id, cwd=None):
    started = utc_now()
    command = [str(part) for part in item["command"]]
    process = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    finished = utc_now()
    row = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "item_key": item_key(item),
        "status": SUCCESS if process.returncode == 0 else FAILED,
        "source": item.get("source"),
        "market_id": item.get("market_id"),
        "station": item.get("station"),
        "unit": item.get("unit"),
        "detail": item.get("detail"),
        "command": command,
        "command_text": command_text(command),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "exit_code": process.returncode,
        "stdout_tail": tail_text(process.stdout),
        "stderr_tail": tail_text(process.stderr),
    }
    append_event(state_path, row)
    return row


def run_plan(
    plan_path=DEFAULT_PLAN,
    state_path=DEFAULT_STATE,
    summary_path=DEFAULT_SUMMARY,
    max_items=0,
    dry_run=False,
    fail_fast=False,
    rerun_succeeded=False,
    sources=None,
    markets=None,
    cwd=None,
):
    plan = read_plan(plan_path)
    all_items = filter_items(plan.get("queue", []), sources=sources, markets=markets)
    latest, _events = load_state(state_path)
    skipped_succeeded = 0
    pending = []
    for item in all_items:
        key = item_key(item)
        if not rerun_succeeded and latest.get(key, {}).get("status") == SUCCESS:
            skipped_succeeded += 1
            continue
        pending.append(item)
    selected = pending[:max_items] if max_items else pending
    run_id = utc_now().strftime("%Y%m%dT%H%M%SZ")
    rows = []
    for item in selected:
        if dry_run:
            rows.append({
                "item_key": item_key(item),
                "status": "dry_run",
                "source": item.get("source"),
                "market_id": item.get("market_id"),
                "detail": item.get("detail"),
                "command": item.get("command"),
                "command_text": command_text(item.get("command", [])),
            })
            continue
        row = run_item(item, state_path, run_id, cwd=cwd)
        rows.append(row)
        if row["status"] == FAILED and fail_fast:
            break
    success_count = sum(1 for row in rows if row.get("status") == SUCCESS)
    failed_count = sum(1 for row in rows if row.get("status") == FAILED)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "plan_path": str(plan_path),
        "state_path": str(state_path),
        "dry_run": dry_run,
        "queue_count": len(all_items),
        "pending_count_before_limit": len(pending),
        "selected_count": len(selected),
        "skipped_succeeded_count": skipped_succeeded,
        "success_count": success_count,
        "failed_count": failed_count,
        "max_items": max_items,
        "filters": {
            "sources": list(sources or []),
            "markets": list(markets or []),
        },
        "selected_counts": queue_counts(selected),
        "rows": rows,
    }
    if not dry_run:
        summary["status_after_run"] = status_summary(plan_path, state_path, sources=sources, markets=markets)
    write_summary(summary_path, summary)
    return summary


def print_status(payload):
    print(f"Queue: {payload['queue_count']} item(s)")
    print(f"Succeeded: {payload['success_count']}")
    print(f"Failed latest attempts: {payload['failed_count']}")
    print(f"Remaining: {payload['remaining_count']} ({payload['remaining_counts']['by_source']})")


def cmd_run(args):
    summary = run_plan(
        plan_path=args.plan,
        state_path=args.state,
        summary_path=args.summary,
        max_items=args.max_items,
        dry_run=args.dry_run,
        fail_fast=args.fail_fast,
        rerun_succeeded=args.rerun_succeeded,
        sources=parse_csv(args.sources),
        markets=parse_csv(args.markets),
        cwd=args.cwd or None,
    )
    mode = "Dry run" if args.dry_run else "Run"
    print(f"{mode} selected {summary['selected_count']} item(s)")
    print(f"Success: {summary['success_count']}; failed: {summary['failed_count']}")
    if "status_after_run" in summary:
        print_status(summary["status_after_run"])
    else:
        print(f"Pending before limit: {summary['pending_count_before_limit']}")


def cmd_status(args):
    payload = status_summary(
        plan_path=args.plan,
        state_path=args.state,
        sources=parse_csv(args.sources),
        markets=parse_csv(args.markets),
    )
    write_summary(args.summary, payload)
    print_status(payload)


def add_common_filters(parser):
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--sources", default="")
    parser.add_argument("--markets", default="")


def build_parser():
    parser = argparse.ArgumentParser(description="Run historical backfill queue items with resume state.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    add_common_filters(run)
    run.add_argument("--max-items", type=int, default=0, help="0 means all pending items.")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--fail-fast", action="store_true")
    run.add_argument("--rerun-succeeded", action="store_true")
    run.add_argument("--cwd", default="")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status")
    add_common_filters(status)
    status.set_defaults(func=cmd_status)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
