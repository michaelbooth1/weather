"""Compare the actual probability masses in two replay distributions."""

import math
from collections.abc import Mapping

from weather.model.continuous_density import density_f_from_payload


def _mass_by_coordinate(values, *, continuous):
    if not isinstance(values, Mapping) or not values:
        raise ValueError("missing or invalid probability map")
    result = {}
    for key, value in values.items():
        try:
            coordinate, mass = float(key), float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("invalid coordinate or mass") from exc
        if isinstance(key, bool) or not math.isfinite(coordinate) or (not continuous and not coordinate.is_integer()):
            raise ValueError("invalid coordinate for this probability map")
        if coordinate in result or isinstance(value, bool) or not math.isfinite(mass) or mass < 0:
            raise ValueError("duplicate coordinate or invalid probability mass")
        result[coordinate] = mass
    if not any(result.values()):
        raise ValueError("probability map has no positive mass")
    return result


def distribution_l1(left, right):
    """Raw L1 on native whole buckets or on the common canonical-F grid.

    JSON may stringify the coordinates; extra zero-weight points do not change
    the distance. Empty, invalid or mixed representations are incomparable.
    """
    left_density = density_f_from_payload(left)
    right_density = density_f_from_payload(right)
    if (left_density is None) != (right_density is None):
        raise ValueError("mixed native and continuous probability maps")
    continuous = left_density is not None
    a = _mass_by_coordinate(left_density if continuous else left, continuous=continuous)
    b = _mass_by_coordinate(right_density if continuous else right, continuous=continuous)
    return sum(abs(a.get(key, 0.0) - b.get(key, 0.0)) for key in a.keys() | b.keys())
