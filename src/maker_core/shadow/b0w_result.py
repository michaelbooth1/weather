"""The ``b0w_result`` data contract between B0w (``weather.*``) and the core gate (``maker_core``).

Spec: D-shadow-gate-spec-v3 §6.2 "Import boundary": the CLI runs B0w first and writes a canonical ``b0w_result``
object (its verdict, the mismatch list and its own module hash); that object is passed to the ``maker_core`` gate
**as data**; the gate verifies that ``b0w_result`` names the bound B0w module hash and the tape's seal SHA.
v3.1 §4.8 rule 8's "identities and hashes only" is applied to every list entry here, and the result is persisted
through the sealed writer (v3.1 §4.8 rule 3 lists ``b0w_result``).

This module holds the schema, the canonical bytes and the binding check only. It imports no ``weather.*`` (the
gate-package ratchet, v3 §6.2) and contains no tier comparison or day-verdict logic.
"""
from __future__ import annotations

import re

from maker_core.evidence.journal import canonical_bytes

SCHEMA = "maker_core.shadow.b0w_result.v0.1"
VERDICTS = ("PASS", "FAIL", "REFUSED")  # FAIL: any B0w mismatch (v3 §10); REFUSED: raw_missing (v3 §6.2)
KINDS = ("descriptor", "outcome_view", "info_event")  # the weather kinds B0w owns (v3 §6.2)
MISMATCH_FIELDS = frozenset({"kind", "condition_id", "at", "recorded_sha256", "rebuilt_sha256", "error_class"})
REFUSAL_FIELDS = frozenset({"reason", "kind", "condition_id", "at", "raw_sha256", "cause"})
RESULT_FIELDS = frozenset({"schema_version", "verdict", "module_sha256", "seal_sha256", "records_checked",
                           "mismatches", "refusals"})
_SHA = re.compile(r"[0-9a-f]{64}")


class B0wResultInvalid(ValueError):
    """The result is malformed or not bound to the expected module hash and tape seal."""


def build_result(*, module_sha256, seal_sha256, records_checked, mismatches=(), refusals=()):
    mismatches, refusals = [dict(m) for m in mismatches], [dict(r) for r in refusals]
    verdict = "REFUSED" if refusals else "FAIL" if mismatches else "PASS"
    result = {"schema_version": SCHEMA, "verdict": verdict, "module_sha256": module_sha256,
              "seal_sha256": seal_sha256, "records_checked": records_checked,
              "mismatches": mismatches, "refusals": refusals}
    validate(result)
    return result


def result_bytes(result):
    validate(result)
    return canonical_bytes(result)


def validate(result):
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS or result["schema_version"] != SCHEMA:
        raise B0wResultInvalid("b0w_result_schema")
    if result["verdict"] not in VERDICTS:
        raise B0wResultInvalid("b0w_result_verdict")
    for name in ("module_sha256", "seal_sha256"):
        if not isinstance(result[name], str) or not _SHA.fullmatch(result[name]):
            raise B0wResultInvalid("b0w_result_hash_field")
    count = result["records_checked"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise B0wResultInvalid("b0w_result_count")
    for rows, allowed in ((result["mismatches"], MISMATCH_FIELDS), (result["refusals"], REFUSAL_FIELDS)):
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not set(r) <= allowed for r in rows):
            raise B0wResultInvalid("b0w_result_entry_fields")
        for row in rows:
            if row.get("kind") is not None and row["kind"] not in KINDS:
                raise B0wResultInvalid("b0w_result_entry_kind")
            for name in ("recorded_sha256", "rebuilt_sha256", "raw_sha256"):
                if row.get(name) is not None and not _SHA.fullmatch(str(row[name])):
                    raise B0wResultInvalid("b0w_result_entry_hash")
    expected = "REFUSED" if result["refusals"] else "FAIL" if result["mismatches"] else "PASS"
    if result["verdict"] != expected:
        raise B0wResultInvalid("b0w_result_verdict_inconsistent")
    return result


def verify_binding(result, *, bound_module_sha256, seal_sha256):
    """The gate's check (v3 §6.2): the result names the bound B0w module hash and this tape's seal SHA."""
    validate(result)
    if result["module_sha256"] != bound_module_sha256:
        raise B0wResultInvalid("b0w_module_unbound")
    if result["seal_sha256"] != seal_sha256:
        raise B0wResultInvalid("b0w_seal_mismatch")
    return result["verdict"]


__all__ = ["B0wResultInvalid", "KINDS", "SCHEMA", "VERDICTS", "build_result", "result_bytes", "validate",
           "verify_binding"]
