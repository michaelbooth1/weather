"""Frozen v2 feature substitution for 111h; pure, no outcome or market input."""
from __future__ import annotations

from tools.research.missing_information.extract import finite

PERCENTILES = (10, 25, 50, 75, 90)
V2_FIELDS = {**{f"nbm_prob_tmax_p{p}": f"v2_p{p}" for p in PERCENTILES},
             "nbm_prob_tmax_mean": "v2_mean", "nbm_prob_tmax_stddev": "v2_stddev"}
FLAGS = ("nbm_prob_tmax_physical_valid_flag", "nbm_prob_tmax_impossible_flag")
# FeatureModelMixin.guidance_physical_margin: max(0.1, scale_delta(0.5)); 0.5 C = 0.9 F.
MARGIN = {"F": 0.9, "C": 0.5}


def v2_valid(values, floor, unit):
    """FeatureModelMixin.guidance_physical_state status == 'valid' for the NBM set."""
    cleaned = {k: v for k, v in values.items() if v is not None}
    representative = (cleaned.get("nbm_prob_tmax_p90") or cleaned.get("nbm_prob_tmax_mean")
                      or cleaned.get("nbm_prob_tmax_p50"))
    if representative is None and cleaned:
        representative = max(cleaned.values())
    if representative is None:
        return False
    if floor is None:
        return True
    margin = MARGIN[unit]
    impossible = [k for k, v in cleaned.items() if v < floor - margin]
    return not impossible and not representative - floor < -margin


def v2_features(row):
    """Captured features with only the seven NBM values and two validity flags replaced."""
    features = dict(row.get("features") or {})
    for key in (*V2_FIELDS, *FLAGS):
        features.pop(key, None)
    if row.get("v2_status") != "available":
        return features
    for key, source in V2_FIELDS.items():
        value = finite(row.get(source))
        if value is not None:
            features[key] = value
    # The builder sets flags whenever an NBM row is present; stddev is not a checked value.
    checked = {k: features.get(k) for k in V2_FIELDS if k != "nbm_prob_tmax_stddev"}
    valid = v2_valid(checked, finite(features.get("guidance_physical_floor")), row["unit"])
    features[FLAGS[0]] = 1.0 if valid else 0.0
    features[FLAGS[1]] = 0.0 if valid else 1.0
    return features
