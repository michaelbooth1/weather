"""HARNESS v3 control arm: served probabilities handed back (identity; no inputs)."""
NAME = "served_identity"
FAMILY = "serving_identity_control"
READS_NBM_GUIDANCE = False
INPUTS = ()


def build(snaps, bands):
    out = bands[["row_key", "band_index"]].copy()
    out["p"] = bands.p_served.to_numpy(float)
    return out
