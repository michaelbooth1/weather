"""Registration §9 ceilings for the v2 scored run, derived from score-free calibration rehearsals (W6, U2).

Rule (registration draft §9, fixed before any value is read): N = 16, the bundles in the scored run (14 quote
dates and 2 settlement-only). Each of input bytes, records, wakes, decisions, span runs, report bytes, sidecar
bytes and runtime is the next power of two at or above N x the largest **per-date** value. Memory is the next
power of two at or above 2 x the **carried 3-date** run's peak above baseline, plus the largest measured baseline
(added, never multiplied; the Clarification 2 precedent in ``maker_core.replay.ceilings``).

Host limits (§8, the 32 GB workstation): memory 16 GiB, runtime 32,768 s, input 16 GiB, scored report 1 GiB,
sidecar 8 GiB, every count 2^31. A ceiling above its limit makes the run not executable on this host (gate E6 and,
for memory, E5); the panel is never sampled, truncated or split to fit. The memory comparison is on the derived
ceiling itself (power of two plus baseline), the stricter reading of "the derived memory ceiling <= 16 GiB" (E5).

The per-date and carried measurements are the rehearsal's ``measured`` block (``rehearsal`` whitelist, §9): no
fill, P&L, reward, markout or contrast is accepted here; an unknown key refuses.
"""
from __future__ import annotations

import math

from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES

FORMAT = "maker_core.replay.v2.ceiling_measurement.v0.1"
RULE = "registration_v2_s9_n16_next_power_of_two_memory_2x_carried_plus_baseline_host_limited"
N = 16
MEMORY_FACTOR = 2
GIB = 1024**3
COUNT_LIMIT = 2**31
# Quantities multiplied by N from the largest per-date value, each in its own unit.
MULTIPLIED = ("input_bytes", "records", "wakes", "decisions", "span_runs", "report_bytes", "sidecar_bytes",
              "runtime_seconds")
MEMORY = ("peak_memory_above_baseline_bytes", "baseline_memory_bytes")
MEASURED = (*MULTIPLIED, *MEMORY)
HOST_LIMITS = dict(input_bytes=16 * GIB, records=COUNT_LIMIT, wakes=COUNT_LIMIT, decisions=COUNT_LIMIT,
                   span_runs=COUNT_LIMIT, report_bytes=1 * GIB, sidecar_bytes=8 * GIB, runtime_seconds=32_768,
                   memory_bytes=16 * GIB)
HOST = dict(host_id="DESKTOP-RFCD2GH", memory_percent_of_physical=70, whole_run_hours=12, free_bytes_at_start=100 * GIB)
NOT_EXECUTABLE = "not executable on this host"
EXECUTABLE = "executable on this host"


def next_power_of_two(value):
    """The least power of two >= ``value`` (1 for values <= 1); a non-finite, negative or boolean value refuses."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise BundleError("invalid_measurement_value")
    if value <= 1:
        return 1
    power = 1 << (math.ceil(value) - 1).bit_length()  # exact for ints; ceil first for float runtimes
    return power


def _measured(value):
    if not isinstance(value, dict) or set(value) != set(MEASURED):
        raise BundleError("incomplete_ceiling_measurement")
    for name in MEASURED:
        next_power_of_two(value[name])  # type and range check only
    return value


def derive(per_date, carried):
    """``per_date`` = {ISO calibration date: measured} for exactly the three calibration dates; ``carried`` = the
    single carried 3-date run's measured block. Returns the derived document (``executable`` False when any
    host limit binds; the binding names are listed, never clipped)."""
    expected = [d.isoformat() for d in CALIBRATION_DATES]
    if not isinstance(per_date, dict) or sorted(per_date) != expected:
        raise BundleError("incomplete_ceiling_measurement")
    rows = {day: _measured(per_date[day]) for day in expected}
    carried = _measured(carried)
    largest = {name: max(rows[day][name] for day in expected) for name in MEASURED}
    ceilings = {name: next_power_of_two(largest[name] * N) for name in MULTIPLIED}
    baseline = max(largest["baseline_memory_bytes"], carried["baseline_memory_bytes"])
    ceilings["memory_bytes"] = (next_power_of_two(MEMORY_FACTOR * carried["peak_memory_above_baseline_bytes"])
                                + int(math.ceil(baseline)))
    binding = sorted(name for name, limit in HOST_LIMITS.items() if ceilings[name] > limit)
    return dict(format=FORMAT, rule=RULE, n=N, memory_factor=MEMORY_FACTOR, host=HOST, host_limits=HOST_LIMITS,
                largest_per_date=largest, carried_peak_above_baseline_bytes=carried["peak_memory_above_baseline_bytes"],
                baseline_memory_bytes=baseline, ceilings=ceilings, host_limit_binding=binding,
                executable=not binding, verdict=NOT_EXECUTABLE if binding else EXECUTABLE)


def run_limits(derived):
    """The resource limits a scored run is bound to; refuses when any host limit binds (never truncates)."""
    if not isinstance(derived, dict) or derived.get("format") != FORMAT:
        raise BundleError("invalid_ceiling_derivation")
    if derived.get("executable") is not True or derived.get("host_limit_binding"):
        raise BundleError("not_executable_on_host:" + ",".join(derived.get("host_limit_binding") or ())
                          + " (" + NOT_EXECUTABLE + ")")
    c = derived["ceilings"]
    return dict(max_input_bytes=c["input_bytes"], max_records=c["records"], max_seconds=float(c["runtime_seconds"]),
                max_output_bytes=c["report_bytes"], max_sidecar_bytes=c["sidecar_bytes"],
                max_memory_bytes=c["memory_bytes"], max_wakes=c["wakes"],
                max_outputs=min(c["decisions"] + c["span_runs"], COUNT_LIMIT))


def e5_memory(per_date, carried, derived):
    """Gate E5: the carried run's peak <= 1.25 x the largest single-date peak, and the memory ceiling <= 16 GiB.
    The ratio is compared exactly (4 x carried <= 5 x largest), so 1.25 passes and anything above fails."""
    largest = max(_measured(m)["peak_memory_above_baseline_bytes"] for m in per_date.values())
    peak = _measured(carried)["peak_memory_above_baseline_bytes"]
    streams = 4 * peak <= 5 * largest
    within = derived["ceilings"]["memory_bytes"] <= HOST_LIMITS["memory_bytes"]
    return dict(status="PASS" if streams and within else "FAIL", days_do_not_accumulate=streams,
                memory_ceiling_within_limit=within)
