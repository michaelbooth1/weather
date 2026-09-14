"""Fixed host audit phases, called only inside the adopted native envelope.

These functions produce computation evidence, never host acceptance or merge
authority. The native parent owns admission, deadlines, process accounting,
source/environment checks and a fresh complete current-generation validation.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time

from .contracts import Graph, fields, record, sequence, text
from .inputs import ReadBudget, SourceRoots, Stager, _input_object, verified_input
from .records import checked_root, integer, publish, reference, require, timestamp, utc_now
from .settlement_inputs import SealedAuditReader, load_entries, prepare, validate_current_generation


MAX_AUDIT_BYTES = 128 * 1024**2


def source_roots(value):
    fields(value, {"roots", "prefixes", "relative_root"})
    return SourceRoots({key: Path(path) for key, path in value["roots"].items()},
                       value["prefixes"], relative_root=value["relative_root"])


def limits(value):
    fields(value, {"read_bytes", "staged_bytes", "files", "seconds"})
    integer(value["read_bytes"], minimum=1, maximum=1024 * 1024**3)
    integer(value["staged_bytes"], minimum=1, maximum=128 * 1024**3)
    integer(value["files"], minimum=1, maximum=20_000)
    integer(value["seconds"], minimum=1, maximum=1200)
    return value


def new_budget(value, *, previously_read=0, seconds_remaining=None):
    limits(value)
    integer(previously_read, maximum=value["read_bytes"])
    seconds = value["seconds"] if seconds_remaining is None else min(value["seconds"], seconds_remaining)
    require(seconds > 0, "host audit has no remaining execution budget")
    return ReadBudget(value["read_bytes"], time.monotonic() + seconds, previously_read)


def stage(*, output, roots, labels, ledgers, markets, maximum):
    """Complete strict input pass with an explicit caller-reviewed topology."""
    output = checked_root(output)
    budget = new_budget(maximum)
    stager = Stager(source_roots(roots), output, budget,
                    maximum_files=maximum["files"], maximum_bytes=maximum["staged_bytes"])
    started = utc_now()
    preparation = prepare(stager, labels_identity=labels, ledger_root_identity=ledgers, markets=markets)
    inputs_ref = stager.seal()
    return publish(output, "preparation.json", {"schema": "qualification_audit_preparation_v2",
        "started_at": started, "completed_at": utc_now(), "inputs": inputs_ref,
        "preparation": preparation, "read_bytes": budget.observed_bytes})


def preparation(graph, ref):
    value = record(graph.get(ref), "qualification_audit_preparation_v2",
                   {"started_at", "completed_at", "inputs", "preparation", "read_bytes"})
    require(timestamp(value["started_at"]) <= timestamp(value["completed_at"]), "reversed preparation interval")
    integer(value["read_bytes"])
    reference(value["inputs"])
    details = fields(value["preparation"], {"labels_identity", "ledger_root_identity", "markets", "counts", "index_bytes"})
    text(details["labels_identity"], maximum=4096)
    text(details["ledger_root_identity"], maximum=4096)
    counts = fields(details["counts"], {"labels", "ledgers", "merged_rows"})
    for key in ("labels", "merged_rows"):
        integer(counts[key], maximum=2_000_000)
    require(type(counts["ledgers"]) is dict and set(counts["ledgers"]) == set(details["markets"]),
            "preparation market counts differ")
    for count in counts["ledgers"].values():
        integer(count, maximum=2_000_000)
    integer(details["index_bytes"])
    entries = load_entries(graph, value["inputs"])
    manifest = graph.get(value["inputs"])
    require(len(manifest["topologies"]) == 1 and manifest["topologies"][0]["markets"] == details["markets"],
            "preparation differs from complete sealed topology")
    require(sum(item["kind"] == "labels" for item in entries) == 1 and
            sum(item["kind"] == "ledger" for item in entries) == len(details["markets"]),
            "preparation does not bind exactly one projection and all ledgers")
    require(value["read_bytes"] == manifest["validation"]["read_bytes"], "preparation read accounting differs")
    return value


def write_payload(root, name, value, budget):
    """Stream finite domain JSON; metadata's integer-only codec stays strict."""
    root = checked_root(root)
    require(name in {"audit.json", "consumer.json"}, "unsupported fixed audit output")
    hasher, count = hashlib.sha256(), 0
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with (root / name).open("xb") as handle:
        for chunk in encoder.iterencode(value):
            budget.charge()
            raw = chunk.encode("utf-8")
            count += len(raw)
            require(count <= MAX_AUDIT_BYTES, "complete audit output exceeds reviewed bound")
            handle.write(raw)
            hasher.update(raw)
        handle.write(b"\n")
        hasher.update(b"\n")
        count += 1
        require(count <= MAX_AUDIT_BYTES, "complete audit output exceeds reviewed bound")
        handle.flush()
        os.fsync(handle.fileno())
    return {"path": name, "size": count, "sha256": hasher.hexdigest()}


def read_payload(root, ref, budget):
    integer(ref["size"], minimum=1, maximum=MAX_AUDIT_BYTES)
    with verified_input(root, ref, budget) as handle:
        raw = handle.read(MAX_AUDIT_BYTES + 1)
    require(len(raw) == ref["size"] and raw.endswith(b"\n"), "incomplete audit output")
    return _input_object(raw)


def validate_counts(payload, expected_rows):
    """Full-output integrity only; classification stays with the domain owner."""
    require(type(payload) is dict and type(payload.get("summary")) is dict and type(payload.get("rows")) is list,
            "audit output lacks its complete rows/summary")
    rows = payload["rows"]
    require(len(rows) == expected_rows, "audit omitted or added a merged input row")
    slugs, statuses, blocked, proof = [], Counter(), 0, 0
    for row in rows:
        require(type(row) is dict, "audit row is not an object")
        slugs.append(text(row.get("event_slug"), maximum=4096))
        statuses[text(row.get("status"))] += 1
        require(type(row.get("promotion_blocker")) is bool and type(row.get("proof_grade_label")) is bool and
                row["promotion_blocker"] != row["proof_grade_label"], "audit proof/blocker contradiction")
        blocked += int(row["promotion_blocker"])
        proof += int(row["proof_grade_label"])
    require(slugs == sorted(set(slugs)), "audit row identity/order differs")
    summary = payload["summary"]
    require(type(summary.get("label_count")) is int and summary["label_count"] == len(rows) and
            type(summary.get("promotion_blocked_label_count")) is int and summary["promotion_blocked_label_count"] == blocked and
            type(summary.get("proof_grade_label_count")) is int and summary["proof_grade_label_count"] == proof and
            summary.get("status_counts") == dict(sorted(statuses.items())), "audit complete-row totals contradict summary")
    require(payload.get("status") == ("MISSING" if not rows else "BLOCK" if blocked else "PASS"),
            "audit semantic status was changed")
    return {"row_count": len(rows), "semantic_status": payload["status"], "blocked_rows": blocked}


def run(*, input_graph, preparation_ref, roots, output, maximum, candidate_audit):
    """Use the fixed candidate audit imported by the trusted child bootstrap.

    candidate_audit is never selected by an input record. It is the one module
    hard-coded in qualification_host_child.py, with a source-byte witness.
    No current source file is opened through this candidate-facing resolver.
    """
    prepared = preparation(input_graph, preparation_ref)
    details = prepared["preparation"]
    budget = new_budget(maximum, previously_read=prepared["read_bytes"])
    reader = SealedAuditReader(input_graph, prepared["inputs"], source_roots(roots), budget)
    started = utc_now()
    payload = candidate_audit.build_settlement_source_audit(
        labels_csv=Path(details["labels_identity"]), ledger_root=Path(details["ledger_root_identity"]),
        generated_at_utc=started, input_reader=reader)
    counts = validate_counts(payload, details["counts"]["merged_rows"])
    # Exercise the existing consumer with every output date, including the tail.
    dates = sorted({str(row["target_date"]) for row in payload["rows"] if row.get("target_date")})
    consumer = candidate_audit.settlement_label_gate_for_target_dates(payload, dates)
    audit_ref = write_payload(output, "audit.json", payload, budget)
    reread = read_payload(output, audit_ref, budget)
    require(reread == payload and validate_counts(reread, details["counts"]["merged_rows"]) == counts,
            "audit output round-trip changed complete rows")
    require(candidate_audit.settlement_label_gate_for_target_dates(reread, dates) == consumer,
            "consumer behavior changed after complete output read")
    consumer_ref = write_payload(output, "consumer.json", consumer, budget)
    require(read_payload(output, consumer_ref, budget) == consumer, "consumer output round-trip differs")
    reader.verify_staged()
    budget.charge()
    return publish(output, "audit-computation.json", {"schema": "qualification_audit_computation_v2",
        "started_at": started, "completed_at": utc_now(), "preparation_sha256": preparation_ref["sha256"],
        "inputs_sha256": prepared["inputs"]["sha256"], "audit": audit_ref, "consumer": consumer_ref,
        "counts": counts, "read_bytes": budget.observed_bytes, "current_validation_required": True})


def revalidate(*, input_graph, preparation_ref, roots, maximum, previously_read):
    """Trusted parent only: complete live generations and explicit absences."""
    prepared = preparation(input_graph, preparation_ref)
    require(previously_read >= prepared["read_bytes"], "input read accounting moved backward")
    budget = new_budget(maximum, previously_read=previously_read)
    entries = load_entries(input_graph, prepared["inputs"])
    topologies = input_graph.get(prepared["inputs"])["topologies"]
    result = validate_current_generation(source_roots(roots), entries, topologies, budget)
    input_graph.fresh()
    return result
