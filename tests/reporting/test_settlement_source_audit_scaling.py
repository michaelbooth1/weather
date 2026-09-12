"""A bounded synthetic revision-history regression, with retained measurements.

The input has a fixed 256 events and growing superseded history. Empty lineage
paths deliberately isolate revision selection, aggregation and serialization
from repeated external-file hashing; this is not a production-corpus benchmark.
"""

from __future__ import annotations

from contextlib import nullcontext
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import tracemalloc

from weather.operations.windows_process_metrics import windows_process_memory_metrics
from weather.reporting.source_gates import settlement_source_audit as audit


def _memory():
    if os.name == "nt":
        metrics = windows_process_memory_metrics(os.getpid())
        if metrics is None:
            raise RuntimeError("Native memory measurement is unavailable")
        return metrics
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"private_bytes": int(rss if sys.platform == "darwin" else rss * 1024),
            "working_set_bytes": int(rss if sys.platform == "darwin" else rss * 1024)}


def _profile(root: Path, history_rows: int):
    root.mkdir()
    ledgers = root / "settlements"
    ledger = ledgers / "atlanta/ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    row = {
        "market_id": "atlanta", "target_date": "2026-06-19",
        "settlement_bucket": "80", "quality_grade": "complete",
        "settlement_source": "daily_summary", "reconciliation_status": "match",
        "ledger_path": "", "note": "p" * 1024,
    }
    with ledger.open("w", encoding="utf-8", newline="\n") as handle:
        for ordinal in range(history_rows):
            row["event_slug"] = f"event-{ordinal % 256:04}"
            handle.write(json.dumps(row) + "\n")
    gc.collect()
    initial = _memory()
    peaks = {"private_bytes": initial["private_bytes"], "rss": initial["working_set_bytes"]}
    finished = threading.Event()

    def sample():
        while not finished.wait(0.01):
            memory = _memory()
            peaks["private_bytes"] = max(peaks["private_bytes"], memory["private_bytes"])
            peaks["rss"] = max(peaks["rss"], memory["working_set_bytes"])

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    tracemalloc.start()
    started = time.perf_counter()
    try:
        arguments = dict(labels_csv=root / "absent.csv", ledger_root=ledgers,
                         generated_at_utc="2026-09-12T00:00:00+00:00")
        if hasattr(audit, "open_settlement_source_audit"):
            scope = audit.open_settlement_source_audit(**arguments, scratch_root=root)
        else:
            scope = nullcontext(audit.build_settlement_source_audit(**arguments))
        with scope as payload:
            assert payload["summary"]["label_count"] == 256
            assert audit.settlement_label_gate_for_target_dates(payload, ["2026-06-19"])["status"] == "PASS"
            audit.write_outputs(payload, json_out=root / "audit.json", report_out=root / "audit.md")
        _, peak_python = tracemalloc.get_traced_memory()
    finally:
        elapsed = time.perf_counter() - started
        tracemalloc.stop()
        finished.set()
        sampler.join(timeout=5)
    assert not sampler.is_alive()
    output = (root / "audit.json").read_text(encoding="utf-8")
    normalized = json.loads(output)
    normalized["labels_csv"] = "<LABELS>"
    normalized["ledger_root"] = "<LEDGERS>"
    output_digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    record = {
        "scope": "synthetic_fixed_event_count_revision_history",
        "history_rows": history_rows, "event_count": 256,
        "input_bytes": ledger.stat().st_size,
        "source_sha256": hashlib.sha256(Path(audit.__file__).read_bytes()).hexdigest(),
        "wall_seconds": round(elapsed, 6), "peak_traced_python_bytes": peak_python,
        "sampled_peak_private_bytes": peaks["private_bytes"], "sampled_peak_rss_bytes": peaks["rss"],
        "private_metric": "Windows private bytes" if os.name == "nt" else "lifetime RSS fallback",
        "output_bytes": (root / "audit.json").stat().st_size,
        "semantic_sha256": output_digest,
        "tracemalloc_enabled": True,
    }
    (root / "measurement.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print("AUDIT_SCALING", json.dumps(record, sort_keys=True))
    return record


def test_superseded_history_does_not_accumulate_in_python_memory(tmp_path):
    small = _profile(tmp_path / "small", 2048)
    large = _profile(tmp_path / "large", 16384)
    assert small["semantic_sha256"] == large["semantic_sha256"]
    # Eight times the obsolete history must not require eight times the heap.
    # This generous allowance covers parser buffers and variation across Python
    # builds; process/SQLite memory receives separate off-host qualification.
    assert large["peak_traced_python_bytes"] <= small["peak_traced_python_bytes"] + 8 * 1024 * 1024
