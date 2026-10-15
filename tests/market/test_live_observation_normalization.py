"""Settlement-band containment table for ``band_contains_value`` (test-suite review K, role 18).

Inclusive tails and the range upper bound decide which band a settled value falls in; a missing or
non-finite value is never inside any band.

Guards: settlement band containment in the native unit (docs/operations/AGENT_CONTEXT.md settlement semantics)
  - inclusive tails, range upper bound, non-finite values in no band.
"""
import pytest

from weather.market.live_observation_normalization import band_contains_value


@pytest.mark.parametrize("row,value,expected", [
    ({"bin_kind": "range", "bin_value": "80", "bin_value_hi": "81"}, 80, True),
    ({"bin_kind": "range", "bin_value": "80", "bin_value_hi": "81"}, 81, True),
    ({"bin_kind": "range", "bin_value": "80", "bin_value_hi": "81"}, 81.5, False),
    ({"bin_kind": "range", "bin_value": "80", "bin_value_hi": "81"}, 79.5, False),
    ({"bin_kind": "lte", "bin_value": "-5"}, -5, True),
    ({"bin_kind": "lte", "bin_value": "-5"}, -4, False),
    ({"bin_kind": "gte", "bin_value": "90"}, 90, True),
    ({"bin_kind": "gte", "bin_value": "90"}, 89, False),
    ({"bin_kind": "eq", "bin_value": "80"}, float("nan"), False),
    ({"bin_kind": "eq", "bin_value": "80"}, None, False),
])
def test_band_contains_value_table(row, value, expected):
    assert band_contains_value(row, value) is expected
