"""CI-only deadline scale for the reconciler harness (tests/ci_timing.py).

Guards: wall-clock budgets scale only under CI and stay exact locally (test-suite review K, #218 Defender C1/C2).
"""

from tests.ci_timing import (
    CI_DEADLINE_SCALE,
    ci_deadline_scale,
    ci_scaled_seconds,
    ci_scaled_timeout,
)

CI = {"GITHUB_ACTIONS": "true"}


def test_scale_is_exactly_one_and_values_unchanged_outside_ci():
    for environ in ({}, {"GITHUB_ACTIONS": "false"}, {"GITHUB_ACTIONS": "TRUE"}, {"CI": "true"}):
        assert ci_deadline_scale(environ) == 1.0
        for seconds, cap in ((3, 15), (10, 20), (3, 20), (7, None)):
            value = ci_scaled_seconds(seconds, cap=cap, environ=environ)
            assert value == seconds and type(value) is int
        for timeout in (20, 60, 90, 60.5):
            value = ci_scaled_timeout(timeout, environ=environ)
            assert value == timeout and type(value) is type(timeout)


def test_scale_is_the_documented_value_on_github_actions():
    assert CI_DEADLINE_SCALE == 2.5
    assert ci_deadline_scale(CI) == 2.5
    # The reconciler harness allowances: read 3 -> 8, push containment 10 -> 20
    # (capped at production's 20), Stop/terminal read 3 -> 8.
    assert ci_scaled_seconds(3, cap=15, environ=CI) == 8
    assert ci_scaled_seconds(10, cap=20, environ=CI) == 20
    assert ci_scaled_seconds(3, cap=20, environ=CI) == 8
    assert ci_scaled_seconds(7, environ=CI) == 18
    assert ci_scaled_timeout(60, environ=CI) == 150.0
