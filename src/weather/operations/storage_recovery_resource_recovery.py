"""Classify bounded resource waits; never turn refused capture admission into PASS."""
from __future__ import annotations

import math

from weather.operations import cold_snapshot_compression as compression
from weather.operations import storage_recovery_night_contract as contract


def classify_resources(**kwargs):
    """Classify recoverable timestamp staleness without changing admission."""
    result = compression.check_resources(**kwargs)
    reasons = set(result["reasons"]) - contract.MEMORY_REASONS
    allowed = {"capture_unhealthy:snapshot", "capture_unhealthy:clob",
               "capture_unhealthy:observation_trigger",
               "snapshot_clean_iteration_missing_or_stale"}
    if not reasons or not reasons <= allowed:
        return result
    # Re-evaluate only to classify the refusal. Never return this hypothetical
    # PASS as actual admission. Missing/future clocks and every non-clock health
    # or native-identity disagreement remain terminal.
    refreshed = []
    for row in kwargs["loops"]:
        probe = dict(row)
        keys = ["heartbeat_age_seconds"]
        if row.get("name") == "snapshot":
            keys.append("last_clean_iteration_age_seconds")
        for key in keys:
            age = row.get(key)
            if type(age) not in (int, float) or not math.isfinite(age) or age < 0:
                return result
            probe[key] = 0
        probe["heartbeat_fresh"] = True
        refreshed.append(probe)
    probe = compression.check_resources(**{**kwargs, "loops": refreshed})
    if not set(probe["reasons"]) - contract.MEMORY_REASONS:
        result["waitable_capture_reasons"] = sorted(reasons)
    return result


def recoverable_refusal(result):
    """Require native observation evidence before retrying a clock-only failure.

    The caller must separately prove wrapper teardown and receipt bindings.
    Memory refusal retains its existing explicit-error contract. Clock waits
    require the complete native observation to reproduce the exact refusal;
    a string mentioning a stale heartbeat is never retry authority.
    """
    if not isinstance(result, dict):
        return False
    if contract.memory_refusal(result.get("error")):
        return True
    observed = result.get("final_admission")
    if (result.get("status") != "FAILED_RETAIN_AND_INSPECT"
            or not isinstance(observed, dict) or observed.get("status") != "BLOCK"):
        return False
    try:
        classified = classify_resources(
            now=contract.utc(observed["checked_at_utc"]),
            available=observed["available_memory_bytes"], commit=observed["host_commit_percent"],
            free_disk=observed["free_disk_bytes"], loops=observed["capture_loops"],
            owner_approved_exception=result.get("owner_approved_exception", ""))
        reasons = observed["reasons"]
        return (classified["status"] == "BLOCK" and classified["reasons"] == reasons
                and bool(classified.get("waitable_capture_reasons"))
                and set(reasons) - contract.MEMORY_REASONS == set(classified["waitable_capture_reasons"])
                and result.get("error") == "capture admission refused: " + ",".join(reasons))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False
