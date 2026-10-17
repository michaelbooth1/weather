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

Pull candidates (owner ruling E6 = A, DECISION_LOG 2026-10-15): §9 also derives a MEASURED pull-candidate ceiling,
``pull_candidates`` = the carried rehearsal's policy-free pull-candidate count x 14 // 3 (``QUOTE_DATES`` quote dates
per calibration date, the panel-scale projection gate E6 already showed), held to the 2^31 count limit. Gate E6
(``e6_pull_candidates``) passes iff the ceilings are executable and the projected (or, later, the scored) candidate
count is at or below it. It is not a power of two: the ruling fixes the projection itself as the ceiling.

The per-date and carried measurements are the rehearsal's ``measured`` block (``rehearsal`` whitelist, §9): no
fill, P&L, reward, markout or contrast is accepted here; an unknown key refuses. The carried pull-candidate count is
the rehearsal document's top-level ``pull_candidates`` (carried mode only), passed separately.
"""
from __future__ import annotations

import math

from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES

FORMAT = "maker_core.replay.v2.ceiling_measurement.v0.2"
RULE = ("registration_v2_s9_n16_next_power_of_two_memory_2x_carried_plus_baseline_host_limited"
        "_pull_candidates_carried_x14_floordiv_3")
N = 16
QUOTE_DATES = 14  # registration §9: the scored run's quote dates (N less the 2 settlement-only dates)
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
                   memory_bytes=16 * GIB, pull_candidates=COUNT_LIMIT)
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


def pull_candidate_ceiling(pull_candidates):
    """The §9 pull-candidate ceiling from the carried rehearsal's count: ``pull_candidates x 14 // 3``.

    A missing (None), non-int, boolean or negative count refuses; the ceiling is never derived from nothing."""
    if type(pull_candidates) is not int or pull_candidates < 0:
        raise BundleError("incomplete_ceiling_measurement:pull_candidates")
    return pull_candidates * QUOTE_DATES // len(CALIBRATION_DATES)


def derive(per_date, carried, *, pull_candidates=None):
    """``per_date`` = {ISO calibration date: measured} for exactly the three calibration dates; ``carried`` = the
    single carried 3-date run's measured block; ``pull_candidates`` = that run's top-level pull-candidate count
    (required; None refuses). Returns the derived document (``executable`` False when any host limit binds; the
    binding names are listed, never clipped)."""
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
    ceilings["pull_candidates"] = pull_candidate_ceiling(pull_candidates)
    binding = sorted(name for name, limit in HOST_LIMITS.items() if ceilings[name] > limit)
    return dict(format=FORMAT, rule=RULE, n=N, memory_factor=MEMORY_FACTOR, host=HOST, host_limits=HOST_LIMITS,
                largest_per_date=largest, carried_peak_above_baseline_bytes=carried["peak_memory_above_baseline_bytes"],
                baseline_memory_bytes=baseline, carried_pull_candidates=pull_candidates, ceilings=ceilings, host_limit_binding=binding,
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
                max_outputs=min(c["decisions"] + c["span_runs"], COUNT_LIMIT),
                max_pull_candidates=c["pull_candidates"])


def e5_memory(per_date, carried, derived):
    """Gate E5: the carried run's peak <= 1.25 x the largest single-date peak, and the memory ceiling <= 16 GiB.
    The ratio is compared exactly (4 x carried <= 5 x largest), so 1.25 passes and anything above fails."""
    largest = max(_measured(m)["peak_memory_above_baseline_bytes"] for m in per_date.values())
    peak = _measured(carried)["peak_memory_above_baseline_bytes"]
    streams = 4 * peak <= 5 * largest
    within = derived["ceilings"]["memory_bytes"] <= HOST_LIMITS["memory_bytes"]
    return dict(status="PASS" if streams and within else "FAIL", days_do_not_accumulate=streams,
                memory_ceiling_within_limit=within)


def e6_pull_candidates(count, derived):
    """Gate E6's pull-candidate clause: PASS iff the ceilings are executable and ``count`` (the panel-projected or the
    scored pull-candidate count) <= the derived ``pull_candidates`` ceiling; the boundary passes, one above fails. A
    count that is not a non-negative int, or a derivation without that ceiling, refuses."""
    if type(count) is not int or count < 0:
        raise BundleError("incomplete_ceiling_measurement:pull_candidates")
    if (not isinstance(derived, dict) or derived.get("format") != FORMAT
            or "pull_candidates" not in (derived.get("ceilings") or {})):
        raise BundleError("invalid_ceiling_derivation")
    ceiling = derived["ceilings"]["pull_candidates"]
    executable = derived.get("executable") is True and not derived.get("host_limit_binding")
    within = count <= ceiling
    return dict(status="PASS" if executable and within else "FAIL", pull_candidates=count,
                max_pull_candidates=ceiling, within_ceiling=within, ceilings_executable=executable)
