"""Durable, owner-cleared PAUSE/HALT latch: create-only hash-chained records.

The guard may only trip the latch. ``owner_clear`` is reachable from this command
alone and needs the current tip hash. An absent, uninitialized or damaged latch
directory reads as an error, which the guard treats as HALT.
"""
import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

from maker_core.evidence.journal import canonical_bytes

LATCH_SCHEMA = "maker_guard_latch_v0.1"
CLEAR, PAUSED, HALTED = "CLEAR", "PAUSED", "HALTED"


def _directory(state_dir):
    path = Path(state_dir)
    info = path.lstat()
    if (path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or not path.is_dir()):
        raise ValueError("latch_directory_refused")
    return path


def verify_records(state_dir):
    previous, records = None, []
    for index, path in enumerate(sorted(_directory(state_dir).glob("*.json"))):
        if path.is_symlink() or path.name != f"{index:08d}.json":
            raise ValueError("latch_sequence_invalid")
        raw = path.read_bytes()
        row = json.loads(raw)
        kind, state = row.get("kind"), row.get("state")
        valid = {"init": index == 0 and state == CLEAR,
                 "trip": index > 0 and state in (PAUSED, HALTED),
                 "clear": bool(records) and records[-1]["state"] != CLEAR and state == CLEAR
                 and row.get("cleared_sha256") == previous}.get(kind, False)
        if (row.get("schema_version") != LATCH_SCHEMA or row.get("sequence") != index
                or row.get("previous_sha256") != previous or canonical_bytes(row) != raw or not valid):
            raise ValueError("latch_chain_invalid")
        previous = hashlib.sha256(raw).hexdigest()
        records.append(row)
    if not records:
        raise ValueError("latch_uninitialized")
    return records, previous


def read_state(state_dir):
    return verify_records(state_dir)[0][-1]["state"]


def safe_tip(state_dir):
    try:
        return verify_records(state_dir)[1]
    except (ValueError, OSError):
        return None


def _append(directory, kind, state, now, **payload):
    lock = directory / ".writer.lock"
    handle = lock.open("xb")
    try:
        if kind == "init":
            if any(directory.glob("*.json")):
                raise FileExistsError("latch_already_initialized")
            records, previous = [], None
        else:
            records, previous = verify_records(directory)
        if kind == "clear" and payload["cleared_sha256"] != previous:
            raise ValueError("latch_confirmation_stale")
        if kind == "clear" and records[-1]["state"] == CLEAR:
            raise ValueError("latch_not_set")
        row = dict(schema_version=LATCH_SCHEMA, sequence=len(records), previous_sha256=previous,
                   kind=kind, state=state, recorded_at_utc=now.isoformat(), **payload)
        raw = canonical_bytes(row)
        with (directory / f"{len(records):08d}.json").open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        return hashlib.sha256(raw).hexdigest()
    finally:
        handle.close()
        lock.unlink()


def initialize(state_dir, now):
    directory = Path(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return _append(_directory(directory), "init", CLEAR, now)


def trip(state_dir, state, decision, now):
    if state not in (PAUSED, HALTED):
        raise ValueError("latch_state_invalid")
    decision = asdict(decision) if is_dataclass(decision) else dict(decision)
    return _append(_directory(state_dir), "trip", state, now, decision=decision)


def owner_clear(state_dir, *, confirm_sha256, pause_file, now):
    """Owner command only. Clearing never allows trading by itself: the next check
    re-evaluates the ledger, cash age and pause file from scratch."""
    if Path(pause_file).exists() or Path(pause_file).is_symlink():
        raise ValueError("pause_file_present")
    return _append(_directory(state_dir), "clear", CLEAR, now,
                   cleared_sha256=confirm_sha256, cleared_by="owner_command")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "clear"):
        command = sub.add_parser(name)
        command.add_argument("--state-dir", required=True, type=Path)
        if name == "clear":
            command.add_argument("--pause-file", required=True, type=Path)
            command.add_argument("--confirm", required=True, help="Current tip SHA-256 from `status`")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        if args.command == "init":
            print(json.dumps(dict(state=CLEAR, tip_sha256=initialize(args.state_dir, now))))
        elif args.command == "status":
            records, tip = verify_records(args.state_dir)
            print(json.dumps(dict(state=records[-1]["state"], tip_sha256=tip, last=records[-1]), sort_keys=True))
        else:
            tip = owner_clear(args.state_dir, confirm_sha256=args.confirm, pause_file=args.pause_file, now=now)
            print(json.dumps(dict(state=CLEAR, tip_sha256=tip)))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error)[:120]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
