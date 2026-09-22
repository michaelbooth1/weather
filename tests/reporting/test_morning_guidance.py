"""Collect the mission's pure-function contracts from its requested tool folder."""
from tools.research.morning_guidance.test_morning_guidance import (  # noqa: F401
    test_mass_floor_and_exact_fixed_pool,
    test_bad_guidance_keeps_every_served_value,
    test_missing_floor_falls_back_and_trusted_floor_wins,
    test_native_celsius_translation_is_equivariant,
    test_invalid_served_support_refuses_instead_of_normalizing,
    test_cdf_duplicate_quantiles_keep_mass,
    test_fixed_market_uncertainty_does_not_shrink_with_dates,
    test_zero_delta_negative_control_and_nonbeneficial_planning,
    test_recorded_valid_without_floor_is_not_eligible,
    test_day_means_and_ratio_are_not_snapshot_weighted,
)
