"""Consume a complete native pytest event stream with explicit tail accounting."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath

from .contracts import fields, sequence, text
from .coverage import node_id
from .records import decode, digest, integer, open_record, relative_path, require


EVENT_FIELDS = {
    "session_start": {"root", "invocation"},
    "collection_problem": {"nodeid", "outcome", "reason"},
    "deselected": {"nodes"},
    "collected_node": {"nodeid"},
    "collection_finish": {"count"},
    "test_start": {"nodeid"},
    "test_phase": {"nodeid", "when", "outcome", "wasxfail", "reason"},
    "test_finish": {"nodeid"},
    "session_finish": {"exit_code", "tests_collected", "tests_failed"},
}


def _outcome(phases):
    for phase in phases:
        if phase["outcome"] == "failed":
            return "fail", phase["reason"]
    for phase in phases:
        if phase["outcome"] == "skipped":
            return ("xfail" if phase["wasxfail"] else "skip"), phase["reason"]
    if any(phase["wasxfail"] for phase in phases):
        return "xpass", next(phase["reason"] for phase in phases if phase["wasxfail"])
    return "pass", None


def execution_root(value, platform):
    value = str(value)
    require(platform in {"windows", "linux"} and 0 < len(value) <= 1024 and
            not any(ord(char) < 32 for char in value), "invalid execution root")
    parsed = PureWindowsPath(value) if platform == "windows" else PurePosixPath(value)
    require(parsed.is_absolute() and ".." not in parsed.parts, "absolute candidate root required")
    if platform == "windows":
        require(len(parsed.drive) == 2 and parsed.drive[1] == ":", "local Windows candidate volume required")
    return parsed


def consume(root, ref, *, candidate_root, native_exit_code, collect_only=False, platform=None):
    fields(ref, {"path", "sha256", "size"})
    relative_path(ref["path"])
    digest(ref["sha256"])
    integer(ref["size"], minimum=1, maximum=128 * 1024**2)
    integer(native_exit_code, minimum=-(2**31), maximum=2**32 - 1)
    platform = platform or ("windows" if os.name == "nt" else "linux")
    expected_root = execution_root(candidate_root, platform)
    collected, deselected, problems, started, completed, results = [], [], [], [], [], []
    collected_set = set()
    active, phases, tail = None, [], None
    collection_finished = False
    last_ns, ordinal, byte_count = 0, 0, 0
    hasher = hashlib.sha256()
    with open_record(root, ref["path"]) as handle:
        while line := handle.readline(1024 * 1024 + 1):
            ordinal += 1
            byte_count += len(line)
            require(ordinal <= 200_000 and byte_count <= ref["size"] and line.endswith(b"\n") and
                    len(line) <= 1024 * 1024, "partial/oversized event stream")
            require(tail is None, "events after terminal tail")
            hasher.update(line)
            event = decode(line, maximum=1024 * 1024)
            kind = event.get("event")
            require(type(kind) is str and kind in EVENT_FIELDS, "unknown journal event")
            fields(event, {"event", "ordinal", "monotonic_ns", *EVENT_FIELDS[kind]})
            require(integer(event["ordinal"], minimum=1) == ordinal, "missing/duplicate journal ordinal")
            elapsed = integer(event["monotonic_ns"], minimum=1)
            require(elapsed >= last_ns, "journal clock reversed")
            last_ns = elapsed
            if ordinal == 1:
                require(kind == "session_start" and execution_root(event["root"], platform) == expected_root,
                        "journal source root mismatch")
                for arg in sequence(event["invocation"], minimum=1):
                    text(arg, maximum=8192)
                continue
            require(kind != "session_start", "duplicate session start")
            if kind in {"collected_node", "collection_problem", "deselected", "collection_finish"}:
                require(not collection_finished, "collection event after collection finished")
                if kind == "collected_node":
                    name = node_id(event["nodeid"])
                    require(name not in collected_set, "duplicate collected node")
                    collected.append(name)
                    collected_set.add(name)
                elif kind == "deselected":
                    deselected.extend(node_id(name) for name in sequence(event["nodes"]))
                elif kind == "collection_problem":
                    require(event["outcome"] in {"skipped", "failed"}, "invalid collection problem")
                    problems.append({key: event[key] for key in ("nodeid", "outcome", "reason")})
                else:
                    require(integer(event["count"]) == len(collected), "collection totals contradict nodes")
                    collection_finished = True
            elif kind == "test_start":
                require(collection_finished and not collect_only and active is None, "unexpected/overlapping test")
                require(len(started) < len(collected) and event["nodeid"] == collected[len(started)],
                        "started node differs from collection order")
                active, phases = event["nodeid"], []
                started.append(active)
            elif kind == "test_phase":
                require(active is not None and event["nodeid"] == active, "test phase outside active node")
                when = event["when"]
                expected = [] if not phases else [phase["when"] for phase in phases]
                allowed = {(): {"setup"}, ("setup",): {"call", "teardown"}, ("setup", "call"): {"teardown"}}
                require(when in allowed.get(tuple(expected), set()), "missing/duplicate/out-of-order test phase")
                require(event["outcome"] in {"passed", "skipped", "failed"} and type(event["wasxfail"]) is bool,
                        "invalid test report")
                require(event["reason"] is None or type(event["reason"]) is str, "invalid report reason")
                if when == "call":
                    require(phases[0]["outcome"] == "passed", "call after unsuccessful setup")
                if when == "teardown" and len(phases) == 1:
                    require(phases[0]["outcome"] != "passed", "successful setup missing call phase")
                phases.append({key: event[key] for key in ("when", "outcome", "wasxfail", "reason")})
            elif kind == "test_finish":
                require(active is not None and event["nodeid"] == active and phases and
                        phases[-1]["when"] == "teardown", "test completed without full teardown report")
                outcome, reason = _outcome(phases)
                results.append({"nodeid": active, "outcome": outcome, "reason": reason,
                                "phases": [{key: value for key, value in phase.items() if key != "reason"}
                                           for phase in phases]})
                completed.append(active)
                active, phases = None, []
            else:
                require(kind == "session_finish" and active is None, "unexpected or unfinished terminal tail")
                require(integer(event["exit_code"], maximum=255) == native_exit_code,
                        "native exit disagrees with terminal event")
                require(integer(event["tests_collected"]) == len(collected), "terminal collection total mismatch")
                integer(event["tests_failed"])
                tail = event
    require(byte_count == ref["size"] and hasher.hexdigest() == ref["sha256"], "journal bytes changed")
    require(tail is not None and collection_finished, "missing collection/terminal tail")
    require(collect_only or completed == collected, "unexecuted tests in terminal stream")
    require(not collect_only or (not started and not completed and not results), "execution events in collection-only stream")
    success = bool(collected) and native_exit_code == 0 and tail["tests_failed"] == 0 and not problems and not deselected
    if not collect_only:
        success = success and all(item["outcome"] in {"pass", "skip", "xfail"} for item in results)
    return {"status": "PASS" if success else "FAIL", "collected": collected, "deselected": deselected,
            "collection_errors": problems, "started": started, "completed": completed, "results": results,
            "exit_code": native_exit_code}
