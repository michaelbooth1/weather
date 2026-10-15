"""Registration §9 ceiling rule for the v2 scored run (U2): N = 16, memory 2x carried plus baseline, §8 limits."""
from __future__ import annotations

import pytest

from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.v2 import ceilings

GIB = 1024**3


def measured(**overrides):
    row = dict(input_bytes=300 * 1024**2, records=1_000_000, wakes=2_000_000, decisions=50_000, span_runs=40_000,
               report_bytes=20 * 1024**2, sidecar_bytes=100 * 1024**2, runtime_seconds=900.5,
               peak_memory_above_baseline_bytes=400 * 1024**2, baseline_memory_bytes=150 * 1024**2)
    row.update(overrides)
    return row


def per_date(**by_day):
    return {d.isoformat(): measured(**by_day.get(d.isoformat(), {})) for d in CALIBRATION_DATES}


CANDIDATES = 3_000  # a carried rehearsal's pull-candidate count (fabricated)


def derive(days, carried, pull_candidates=CANDIDATES):
    return ceilings.derive(days, carried, pull_candidates=pull_candidates)


def test_rule_is_n16_next_power_of_two_of_the_largest_per_date_value():
    days = per_date(**{"2026-09-28": dict(records=3_000_000, runtime_seconds=1_000.0)})
    derived = derive(days, measured())
    c = derived["ceilings"]
    assert ceilings.N == 16 and derived["n"] == 16
    assert c["records"] == 2**26  # 16 x 3,000,000 = 48,000,000 -> 67,108,864
    assert c["runtime_seconds"] == 16_384  # 16 x 1,000 s
    assert c["input_bytes"] == 8 * GIB  # 16 x 300 MiB = 4.6875 GiB -> 8 GiB
    assert c["wakes"] == 2**25 and c["decisions"] == 2**20 and c["span_runs"] == 2**20
    assert derived["executable"] and derived["verdict"] == ceilings.EXECUTABLE


def test_a_power_of_two_product_is_not_doubled():
    derived = derive(per_date(), measured())
    assert derive(per_date(**{d.isoformat(): dict(records=2**20) for d in CALIBRATION_DATES}),
                           measured())["ceilings"]["records"] == 2**24
    assert derived["ceilings"]["sidecar_bytes"] == 2 * GIB  # 16 x 100 MiB = 1600 MiB -> 2 GiB


def test_memory_is_two_times_the_carried_peak_rounded_then_the_baseline_added_not_multiplied():
    days = per_date(**{"2026-09-27": dict(peak_memory_above_baseline_bytes=900 * 1024**2,
                                          baseline_memory_bytes=200 * 1024**2)})
    derived = derive(days, measured(peak_memory_above_baseline_bytes=600 * 1024**2,
                                             baseline_memory_bytes=180 * 1024**2))
    # the carried run's peak (600 MiB), not the largest per-date peak (900 MiB): 2 x 600 MiB -> 2 GiB
    assert derived["ceilings"]["memory_bytes"] == 2 * GIB + 200 * 1024**2  # plus the largest baseline, once
    assert derived["baseline_memory_bytes"] == 200 * 1024**2


@pytest.mark.parametrize("name, value, limit", [
    ("input_bytes", 1 * GIB + 1, "input_bytes"),  # E2's 1 GiB per date is exactly the 16 GiB input limit
    ("runtime_seconds", 2_048.5, "runtime_seconds"),  # each date <= 2,048 s
    ("report_bytes", 64 * 1024**2 + 1, "report_bytes"),
    ("sidecar_bytes", 512 * 1024**2 + 1, "sidecar_bytes"),
    ("records", 2**27 + 1, "records"),
    ("wakes", 2**27 + 1, "wakes"),
])
def test_each_host_limit_binds_and_is_never_clipped(name, value, limit):
    derived = derive(per_date(**{"2026-09-29": {name: value}}), measured())
    assert derived["host_limit_binding"] == [limit] and not derived["executable"]
    assert derived["verdict"] == ceilings.NOT_EXECUTABLE
    assert derived["ceilings"][limit] > ceilings.HOST_LIMITS[limit]  # reported as derived, not truncated
    with pytest.raises(BundleError, match="not_executable_on_host:" + limit):
        ceilings.run_limits(derived)


def test_limits_hold_at_the_boundary():
    days = per_date(**{"2026-09-29": dict(input_bytes=1 * GIB, runtime_seconds=2_048, report_bytes=64 * 1024**2,
                                          sidecar_bytes=512 * 1024**2, records=2**27)})
    derived = derive(days, measured())
    assert derived["executable"], derived["host_limit_binding"]


def test_memory_limit_is_on_the_derived_ceiling_including_the_baseline():
    # 2 x 4 GiB -> 8 GiB: within; 2 x (4 GiB + 1) -> 16 GiB, plus a baseline -> over 16 GiB: binds
    ok = derive(per_date(), measured(peak_memory_above_baseline_bytes=4 * GIB))
    assert ok["executable"]
    over = derive(per_date(), measured(peak_memory_above_baseline_bytes=4 * GIB + 1))
    assert over["host_limit_binding"] == ["memory_bytes"]


def test_run_limits_bind_every_ceiling():
    derived = derive(per_date(), measured())
    c = derived["ceilings"]
    assert ceilings.run_limits(derived) == dict(
        max_input_bytes=c["input_bytes"], max_records=c["records"], max_seconds=float(c["runtime_seconds"]),
        max_output_bytes=c["report_bytes"], max_sidecar_bytes=c["sidecar_bytes"], max_memory_bytes=c["memory_bytes"],
        max_wakes=c["wakes"], max_outputs=c["decisions"] + c["span_runs"],
        max_pull_candidates=c["pull_candidates"])
    with pytest.raises(BundleError, match="invalid_ceiling_derivation"):
        ceilings.run_limits(dict(derived, format="maker_core.replay.ceiling_measurement.v3"))
    with pytest.raises(BundleError, match="not_executable_on_host"):
        ceilings.run_limits(dict(derived, executable=False))


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("2026-09-27"),
    lambda d: d.update({"2026-09-30": measured()}),  # a non-calibration date
    lambda d: d["2026-09-28"].pop("wakes"),
    lambda d: d["2026-09-28"].update(fills=3),  # a scored quantity smuggled into a measurement
    lambda d: d["2026-09-28"].update(final_cash=1.0),
    lambda d: d["2026-09-28"].update(records=-1),
    lambda d: d["2026-09-28"].update(records=float("nan")),
    lambda d: d["2026-09-28"].update(records=True),
])
def test_incomplete_or_scored_measurements_refuse(mutate):
    days = per_date()
    mutate(days)
    with pytest.raises(BundleError, match="incomplete_ceiling_measurement|invalid_measurement_value"):
        derive(days, measured())


def test_carried_measurement_is_checked_like_a_date():
    with pytest.raises(BundleError, match="incomplete_ceiling_measurement"):
        derive(per_date(), dict(measured(), fills=1))


def test_e5_ratio_boundary_is_exact():
    days = per_date(**{"2026-09-27": dict(peak_memory_above_baseline_bytes=800),
                       "2026-09-28": dict(peak_memory_above_baseline_bytes=640),
                       "2026-09-29": dict(peak_memory_above_baseline_bytes=700)})
    largest = 800
    ok = measured(peak_memory_above_baseline_bytes=largest * 5 // 4)  # exactly 1.25x
    assert ceilings.e5_memory(days, ok, derive(days, ok))["status"] == "PASS"
    bad = measured(peak_memory_above_baseline_bytes=largest * 5 // 4 + 1)
    result = ceilings.e5_memory(days, bad, derive(days, bad))
    assert result["status"] == "FAIL" and not result["days_do_not_accumulate"]


def test_e5_fails_when_the_memory_ceiling_exceeds_16_gib():
    days = per_date(**{d.isoformat(): dict(peak_memory_above_baseline_bytes=8 * GIB) for d in CALIBRATION_DATES})
    carried = measured(peak_memory_above_baseline_bytes=8 * GIB)
    result = ceilings.e5_memory(days, carried, derive(days, carried))
    assert result == dict(status="FAIL", days_do_not_accumulate=True, memory_ceiling_within_limit=False)


@pytest.mark.parametrize("value, expected", [(0, 1), (1, 1), (1.5, 2), (2, 2), (3, 4), (4, 4), (5, 8),
                                             (2**40, 2**40), (2**40 + 1, 2**41), (2_048.5 * 16, 32_768 * 2)])
def test_next_power_of_two(value, expected):
    assert ceilings.next_power_of_two(value) == expected


# -- E6 = A (owner ruling, DECISION_LOG 2026-10-15): the §9 MEASURED pull-candidate ceiling -------------------------

def test_pull_candidate_ceiling_is_the_carried_count_times_14_floordiv_3():
    derived = derive(per_date(), measured(), pull_candidates=1_000)
    assert ceilings.QUOTE_DATES == 14 and len(CALIBRATION_DATES) == 3
    assert derived["ceilings"]["pull_candidates"] == 4_666  # 14_000 // 3, not rounded up, not a power of two
    assert derived["carried_pull_candidates"] == 1_000 and derived["executable"]
    assert derive(per_date(), measured(), pull_candidates=3)["ceilings"]["pull_candidates"] == 14
    assert derive(per_date(), measured(), pull_candidates=0)["ceilings"]["pull_candidates"] == 0
    assert ceilings.run_limits(derived)["max_pull_candidates"] == 4_666
    assert ceilings.HOST_LIMITS["pull_candidates"] == ceilings.COUNT_LIMIT


@pytest.mark.parametrize("value", [None, -1, 1.0, True, "3000"])
def test_missing_or_invalid_pull_candidates_refuse(value):
    with pytest.raises(BundleError, match="incomplete_ceiling_measurement:pull_candidates"):
        derive(per_date(), measured(), pull_candidates=value)
    with pytest.raises(BundleError, match="incomplete_ceiling_measurement:pull_candidates"):
        ceilings.derive(per_date(), measured())  # the keyword is required in substance: None refuses


def test_pull_candidate_ceiling_above_the_count_limit_binds():
    over = 2**31 * 3 // 14 + 1  # the smallest count whose ceiling exceeds 2^31
    derived = derive(per_date(), measured(), pull_candidates=over)
    assert derived["ceilings"]["pull_candidates"] > ceilings.COUNT_LIMIT
    assert derived["host_limit_binding"] == ["pull_candidates"] and not derived["executable"]
    assert derive(per_date(), measured(), pull_candidates=over - 1)["executable"]


def test_e6_boundary_equal_passes_and_one_above_fails():
    derived = derive(per_date(), measured(), pull_candidates=1_000)
    ceiling = derived["ceilings"]["pull_candidates"]
    at = ceilings.e6_pull_candidates(ceiling, derived)
    assert at == dict(status="PASS", pull_candidates=ceiling, max_pull_candidates=ceiling, within_ceiling=True,
                      ceilings_executable=True)
    assert ceilings.e6_pull_candidates(ceiling - 1, derived)["status"] == "PASS"
    above = ceilings.e6_pull_candidates(ceiling + 1, derived)
    assert above["status"] == "FAIL" and above["within_ceiling"] is False


def test_e6_fails_when_the_ceilings_are_not_executable_even_within():
    derived = derive(per_date(**{"2026-09-29": dict(wakes=2**27 + 1)}), measured(), pull_candidates=1_000)
    result = ceilings.e6_pull_candidates(0, derived)
    assert result["status"] == "FAIL" and result["within_ceiling"] and not result["ceilings_executable"]


@pytest.mark.parametrize("count", [None, -1, 2.0, False])
def test_e6_refuses_a_missing_count(count):
    with pytest.raises(BundleError, match="incomplete_ceiling_measurement:pull_candidates"):
        ceilings.e6_pull_candidates(count, derive(per_date(), measured()))


def test_e6_refuses_a_derivation_without_the_pull_candidate_ceiling():
    derived = derive(per_date(), measured())
    stale = dict(derived, ceilings={k: v for k, v in derived["ceilings"].items() if k != "pull_candidates"})
    for bad in (stale, dict(derived, format="maker_core.replay.v2.ceiling_measurement.v0.1"), None):
        with pytest.raises(BundleError, match="invalid_ceiling_derivation"):
            ceilings.e6_pull_candidates(1, bad)
