"""Closed-tape, decision/lifecycle agreement only. No economic scorer imports.

Panel economics remain NOT_RUN, including after the embargo expires: future
scoring still requires the separate Phase 2 admission and owner-reviewed look.
"""
from pathlib import Path
from types import SimpleNamespace

from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.replay.bundle import regular_path, timestamp
from maker_core.replay.lifecycle import DecisionEvent
from maker_core.replay.parity import compare_journal
from maker_core.shadow.runner import Runner
from maker_core.shadow.session import Tape, verified, write_bytes


def evaluate(source, receipt_digest, output):
    source, output = regular_path(source), regular_path(output)
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("input_output_overlap")
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": "maker_shadow_agreement_v0.1",
              "status": "INCOMPLETE", "economics": "NOT_RUN", "policy_comparison": "NOT_RUN",
              "embargo_until": "2026-10-15", "source_receipt": receipt_digest,
              "qualified_dates": 0, "qualification": "PENDING_88A_ADMISSION"}
    try:
        manifest, expected, artifacts, receipt = verified(source, receipt_digest)
        tape = Tape(output / "replay", manifest)
        runner = Runner(manifest, tape)
        final = None
        for row in expected:
            if row["event"] == "provenance":
                tape.record("provenance", artifact=tape.artifact(artifacts[row["artifact"]]))
                continue
            if row["event"] != "command":
                continue
            if row["operation"] == "advance":
                command = artifacts[row["artifact"]]
                runner.advance(command["at"], command["rows"])
            elif row["operation"] == "stop":
                final = runner.stop(timestamp(row["at"]), row["reason"])
            else:
                raise ValueError("unknown_command")
        if final is None:
            tape.abort()
            raise ValueError("missing_stop")
        _, actual, _, _ = verified(output / "replay", final)
        decisions = [DecisionEvent(timestamp(r["at"]), r["condition_id"], r["decision"])
                     for r in actual if r["event"] == "decision"]
        wanted = [{"at": r["at"], "condition_id": r["condition_id"], "decision": r["decision"]}
                  for r in expected if r["event"] == "decision"]
        comparison = compare_journal(SimpleNamespace(decisions=decisions), wanted)
        exact = canonical_bytes(actual) == canonical_bytes(expected) and final == receipt_digest
        report.update(status="PASS" if exact and comparison["status"] == "PASS" else "FAIL",
                      decision_agreement=comparison, full_trace_equal=exact,
                      minutes=sum(r["event"] == "minute" for r in actual),
                      gaps=sum(r["event"] == "gap" for r in actual),
                      replay_receipt=final, manifest_digest=receipt["manifest_digest"],
                      mode=manifest.mode)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        report["failure_type"] = type(exc).__name__
    write_bytes(output / "agreement.json", canonical_bytes(report))
    return report
