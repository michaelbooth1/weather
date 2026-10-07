"""B0w: weather-kind input provenance for the shadow-vs-replay gate (descriptor, view and info-event records).

Spec: D-shadow-gate-spec-v3 §6.2 ("Tier B0 and B0w: input provenance", V2), kept by v3.1 and v3.2; failure
classes ``FAIL`` (any B0w mismatch) and ``REFUSED (raw_missing)`` (v3 §10); the stored raw inputs are the API JSON
bodies only, never a page body or URL (v3.1 §4.8 rule 1); ``b0w_result`` goes through the sealed writer (v3.1 §4.8
rule 3); module path per v3 §14.

What B0w does (v3 §6.2):
- From the tape's stored raw inputs (Gamma bodies, NBP texts, observation API JSON bodies) it rebuilds every
  ``descriptor``, ``outcome_view`` and ``info_event`` record at its recorded instant. Each rebuilt payload must be
  byte-equal (``canonical_bytes``) to the recorded payload, else a mismatch (``FAIL``).
- A record without its stored raw input is ``REFUSED (raw_missing)``. A stored raw whose SHA-256 differs from the
  record's reference is the same failure (the input the record names is not stored).
- It writes a canonical ``b0w_result`` (``maker_core.shadow.b0w_result``): verdict, mismatch list (identities and
  hashes only) and its own module hash, bound to the tape's seal SHA.

Import boundary (v3 §6.2, enforced by ``tests/maker_core/test_gate_import_closure.py``): B0w may import only
``weather.market.maker_plugin.{universe,fair_value,clock,exposure,inputs,nbp}``,
``weather.operations.observation_trigger.detect_observation_triggers`` and ``maker_core.contracts``, plus the
gate-infrastructure modules it needs to serialise (``maker_core.evidence.journal.canonical_bytes``,
``maker_core.shadow.b0w_result``, ``maker_core.shadow.secrets``). It **never** imports
``weather.market.maker_shadow``, so it rebuilds independently of how S1 wires the shadow's providers.

NOT built here, by instruction (Swarm M Wave 2 gate-infra brief) and fail-closed instead:
- the plugin-bound rebuilders: ``weather.market.maker_plugin`` is not on this branch (``b31185d6b``) and the tape
  v0.3 raw-block layout (S1) is not yet defined. Until they are bound, every run is
  ``REFUSED (b0w_rebuilders_unbound)``;
- the reopen (``reopen: true``, v3.2 §3.1) and local-midnight ``derived`` descriptor (v3.2 §4.3) acceptance rules,
  which wait for the day-open/refresh design fixes F1-F3 (``D-v3.2-defender.md``). Such a record is refused with
  ``reopen_or_derived_rule_pending``; it is never accepted unchecked.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from maker_core.evidence.journal import canonical_bytes
from maker_core.shadow import b0w_result
from maker_core.shadow.secrets import SealedWriter

KINDS = b0w_result.KINDS
RAW_MISSING = "raw_missing"
REBUILDERS_UNBOUND = "b0w_rebuilders_unbound"
REOPEN_PENDING = "reopen_or_derived_rule_pending"
PATH_CLASS = "b0w_result"


def module_sha256():
    """This module's own hash, bound in the cohort and named in every ``b0w_result`` (v3 §6.2, v3 §12)."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _plugin_rebuilders():
    """Map kind -> ``rebuild(identity, raw_bodies) -> payload`` from the bound plugin modules (v3 §6.2).

    Returns None while the binding is pending (see the module docstring); ``run`` then refuses. Tests replace this
    function; there is deliberately no public injection parameter, so the shadow's wiring cannot supply builders.
    """
    return None


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _identity(record):
    return {"kind": record.get("kind"), "condition_id": str(record.get("condition_id")), "at": str(record.get("at"))}


def run(records, raw, *, seal_sha256):
    """Check every weather-kind record; returns the ``b0w_result`` dict.

    ``records``: tape ``record`` rows as dicts with ``kind``, ``condition_id``, ``at`` (the recorded instant),
    ``payload`` (plain JSON) and ``raw`` (the SHA-256 list of the stored raw inputs it was built from); optional
    ``reopen`` and ``derived`` flags. ``raw``: mapping SHA-256 -> stored bytes. Venue kinds are B0's and are skipped.
    """
    module_hash = module_sha256()
    rebuilders = _plugin_rebuilders()
    weather_rows = [r for r in records if r.get("kind") in KINDS]
    if rebuilders is None or set(rebuilders) != set(KINDS):
        return b0w_result.build_result(module_sha256=module_hash, seal_sha256=seal_sha256, records_checked=0,
                                       refusals=[{"reason": REBUILDERS_UNBOUND}])
    mismatches, refusals, checked = [], [], 0
    for record in weather_rows:
        identity = _identity(record)
        if record.get("reopen") or record.get("derived"):
            refusals.append({"reason": REOPEN_PENDING, **identity})
            continue
        refs = record.get("raw")
        if not isinstance(refs, (list, tuple)) or not refs:
            refusals.append({"reason": RAW_MISSING, **identity, "cause": "no_raw_reference"})
            continue
        bodies, missing = [], None
        for ref in refs:
            stored = raw.get(ref) if isinstance(ref, str) else None
            if stored is None:
                missing = {"reason": RAW_MISSING, **identity, "cause": "absent"}
            elif _sha(stored) != ref:
                missing = {"reason": RAW_MISSING, **identity, "cause": "sha256_mismatch"}
            if missing:
                if isinstance(ref, str) and len(ref) == 64 and all(c in "0123456789abcdef" for c in ref):
                    missing["raw_sha256"] = ref
                break
            bodies.append(stored)
        if missing:
            refusals.append(missing)
            continue
        checked += 1
        recorded = _sha(canonical_bytes(record.get("payload")))
        try:
            rebuilt = _sha(canonical_bytes(rebuilders[identity["kind"]](identity, tuple(bodies))))
        except Exception as error:  # the bound plugin cannot reproduce the record: a mismatch, class name only
            mismatches.append({**identity, "recorded_sha256": recorded, "rebuilt_sha256": None,
                               "error_class": type(error).__name__})
            continue
        if rebuilt != recorded:
            mismatches.append({**identity, "recorded_sha256": recorded, "rebuilt_sha256": rebuilt})
    return b0w_result.build_result(module_sha256=module_hash, seal_sha256=seal_sha256, records_checked=checked,
                                   mismatches=mismatches, refusals=refusals)


def write_result(path, result, *, writer: SealedWriter):
    """Persist ``b0w_result`` through the sealed writer: scanned in memory before the first byte is written."""
    return writer.write_new(path, b0w_result.result_bytes(result), path_class=PATH_CLASS)


__all__ = ["KINDS", "RAW_MISSING", "REBUILDERS_UNBOUND", "REOPEN_PENDING", "module_sha256", "run", "write_result"]
