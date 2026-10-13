"""MG-1 shadow stage ``nbm_v2_guidance_read_v1``: rule, eligibility and frozen constants.

Guards: MG-1 pre-registration §1 (signed b044e0f1) and item 190 owner Q1 (2026-10-08).
"""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from weather.model import nbm_guidance_read as stage
from weather.model.nbm_guidance_read import Band, NbmV2Read
from weather.model.source_adapters import FETCH_META_KEY
from weather.sources.nbm_probabilistic_tmax import NBM_NBP_PARSER_V1, NBM_NBP_PARSER_V2

CAPTURED = "2026-10-20T14:05:00+00:00"
TARGET = "2026-10-20"


def _item(**overrides):
    payload = {
        "parser_version": NBM_NBP_PARSER_V2,
        "available": True,
        "period_kind": "maximum",
        "target_date": TARGET,
        "issued_at": "2026-10-20T07:00:00+00:00",
        "valid_time_utc": "2026-10-21T00:00:00+00:00",
        "mean_native": 71.4,
        "stddev_native": 2.2,
        FETCH_META_KEY: {
            "parser_version": NBM_NBP_PARSER_V2,
            "fetched_at": "2026-10-20T08:10:00+00:00",
            "response_received_at": "2026-10-20T08:10:01+00:00",
            "cache_status": "live",
            "stale": False,
        },
    }
    meta = overrides.pop("meta", None)
    if meta is not None:
        payload[FETCH_META_KEY] = meta
    payload.update(overrides)
    return {"ok": True, "stale": False, "cache_status": "live", "data": payload}


def _bands(lo=66, hi=77):
    """Polymarket-style support: lte lo, 2-degree eq bands, gte hi."""

    out = [Band("lte", lo, lo)]
    k = lo + 1
    while k + 1 < hi:
        out.append(Band("eq", k, k + 1))
        k += 2
    out.append(Band("gte", hi, hi))
    return out


def _eligible(mean=71.4, sd=2.2):
    return NbmV2Read(True, None, v2_mean=mean, v2_stddev=sd)


# --------------------------------------------------------------------------- frozen constants


def test_constants_are_the_preregistered_values():
    assert stage.STAGE_ID == "nbm_v2_guidance_read_v1"
    assert stage.SIGMA_FLOOR_F == 1.0
    assert stage.LOOKBACK_HOURS == 24
    assert stage.REQUIRED_PARSER == 2
    assert stage.FLOOR_FIELDS == ("guidance_physical_floor", "high_so_far", "trusted_current_max")


def test_config_hash_is_frozen():
    # Changing any constant is a new stage version, never an edit of v1.
    assert stage.stage_config_sha256() == GOLDEN_CONFIG_SHA256


GOLDEN_CONFIG_SHA256 = "daa71db98dd7af14de5b74237fdb218e8a4464fe39c94f3e9ac1c837aa97063b"


def test_code_hash_is_hex_and_stable():
    first, second = stage.stage_code_sha256(), stage.stage_code_sha256()
    assert first == second and len(first) == 64 and int(first, 16) >= 0


# --------------------------------------------------------------------------- read eligibility


def test_eligible_read_carries_provenance():
    read = stage.read_v2(_item(), CAPTURED, TARGET)
    assert read.eligible and read.reason is None
    assert (read.v2_mean, read.v2_stddev, read.parser_version) == (71.4, 2.2, 2)
    assert read.available_basis == "response_received_at"
    assert read.available_at == "2026-10-20T08:10:01+00:00"
    assert read.period_kind == "maximum" and read.cache_status == "live" and read.stale is False


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"parser_version": NBM_NBP_PARSER_V1}, "parser_version_not_2"),
        ({"parser_version": None}, "parser_version_not_2"),
        ({"parser_version": "nbm-probabilistic-tmax-parser-v9"}, "parser_version_unknown"),
        ({"available": False}, "read_not_available"),
        ({"period_kind": "minimum"}, "period_kind_not_maximum"),
        ({"target_date": "2026-10-21"}, "target_date_mismatch"),
        ({"issued_at": "not-a-time"}, "issued_at_invalid"),
        ({"issued_at": "2026-10-20T07:00:00"}, "issued_at_invalid"),
        ({"issued_at": "2026-10-19T13:00:00+00:00"}, "outside_lookback"),
        ({"mean_native": None}, "mean_or_stddev_not_finite"),
        ({"stddev_native": float("nan")}, "mean_or_stddev_not_finite"),
        ({"meta": {}}, "availability_missing"),
    ],
)
def test_ineligible_reads(overrides, reason):
    read = stage.read_v2(_item(**overrides), CAPTURED, TARGET)
    assert not read.eligible and read.reason == reason and read.pit_violation is False


def test_v1_payload_without_version_is_ineligible():
    item = _item()
    del item["data"]["parser_version"]
    assert stage.read_v2(item, CAPTURED, TARGET).reason == "parser_version_not_2"


def test_availability_after_capture_is_a_pit_violation():
    meta = {"response_received_at": "2026-10-20T14:05:00.000001+00:00"}
    read = stage.read_v2(_item(meta=meta), CAPTURED, TARGET)
    assert not read.eligible and read.reason == "available_after_capture" and read.pit_violation


def test_issue_after_capture_is_a_pit_violation():
    read = stage.read_v2(_item(issued_at="2026-10-20T15:00:00+00:00"), CAPTURED, TARGET)
    assert read.reason == "issued_after_capture" and read.pit_violation


def test_availability_basis_order():
    meta = {"fetched_at": "2026-10-20T08:00:00+00:00"}
    assert stage.read_v2(_item(meta=meta), CAPTURED, TARGET).available_basis == "fetched_at"
    read = stage.read_v2(_item(meta={}, first_seen_at="2026-10-20T08:30:00+00:00"), CAPTURED, TARGET)
    assert read.available_basis == "first_seen_at" and read.eligible


def test_failed_source_item_is_ineligible():
    assert stage.read_v2({"ok": False}, CAPTURED, TARGET).reason == "source_not_ok"
    assert stage.read_v2(None, CAPTURED, TARGET).reason == "source_not_ok"
    assert stage.read_v2(_item(), "garbage", TARGET).reason == "captured_at_invalid"


def test_floor_value_is_max_of_finite_fields():
    assert stage.floor_value({"guidance_physical_floor": 61.0, "high_so_far": 63.4,
                              "trusted_current_max": float("nan")}) == 63.4
    assert stage.floor_value({"high_so_far": None, "unrelated": 99}) is None
    assert stage.floor_value(None) is None


# --------------------------------------------------------------------------- band mapping


def test_band_from_row_matches_the_extract_mapping():
    assert stage.band_from_row({"bin_kind": "lte", "bin_value_c": 66}) == Band("lte", 66, 66)
    assert stage.band_from_row({"bin_kind": "eq", "bin_value_c": 67, "bin_value_hi_c": 68}) == Band("eq", 67, 68)
    assert stage.band_from_row({"bin_kind": "gte", "bin_value_c": 77.0}) == Band("gte", 77, 77)
    with pytest.raises(ValueError):
        stage.band_from_row({"bin_kind": "eq", "bin_value_c": 67.5})
    with pytest.raises(ValueError):
        stage.band_from_row({"bin_kind": "between", "bin_value_c": 67})


# --------------------------------------------------------------------------- rule


def test_band_probs_matches_t5_reference_on_random_grids():
    t5 = pytest.importorskip("tools.research.model_parity.t5_nbh_latest")
    rng = random.Random(20261013)
    for _ in range(400):
        lo = rng.randint(30, 90)
        bands = _bands(lo, lo + 2 * rng.randint(2, 7) + 1)
        bucket = rng.randint(lo - 6, bands[-1].high + 4)
        mu, sigma = rng.uniform(lo - 8, lo + 20), max(rng.uniform(0.0, 6.0), 1.0)
        ours = stage.band_probs(bands, bucket, mu, sigma)
        ref = t5.band_probs([b.kind for b in bands], [b.low for b in bands], [b.high for b in bands],
                            bucket, mu, sigma)
        assert np.allclose(ours, ref, rtol=0, atol=1e-12)


def _reference_flow(bands, served, mu, sd, floor):
    """``d1_t5_prereg.build_c1`` then ``harness._candidate_vector`` for one snapshot."""

    t5 = pytest.importorskip("tools.research.model_parity.t5_nbh_latest")
    bucket = math.floor(floor + .5)
    p = t5.band_probs([b.kind for b in bands], [b.low for b in bands], [b.high for b in bands],
                      bucket, mu, max(sd, t5.SIG_MIN))
    if not p.sum() > 0:
        return np.asarray(served, float)
    p = p / p.sum()
    p[[b.kind != "gte" and b.high < bucket for b in bands]] = 0.0
    total = p.sum()
    if not total > 0:
        return np.asarray(served, float)
    return p / total if abs(total - 1.0) > 1e-12 else p


def test_apply_matches_the_development_flow():
    rng = random.Random(4)
    for _ in range(300):
        bands = _bands(60, 75)
        served = np.asarray([rng.random() for _ in bands])
        served = served / served.sum()
        mu, sd, floor = rng.uniform(55, 80), rng.uniform(0.2, 5), rng.uniform(50, 78)
        result = stage.apply(bands, served, _eligible(mu, sd), floor)
        assert np.allclose(result.vector, _reference_flow(bands, served, mu, sd, floor), rtol=0, atol=1e-12)


def test_output_is_a_probability_vector_with_floor_collapse():
    bands = _bands(66, 77)
    served = [1 / len(bands)] * len(bands)
    result = stage.apply(bands, served, _eligible(mean=64.0, sd=2.0), floor=70.6)
    assert result.status == "mg1" and result.floor_bucket == 71
    assert abs(sum(result.vector) - 1.0) <= 1e-12
    # every band wholly below the floor bucket is impossible; the floor band absorbs X < B
    for band, value in zip(bands, result.vector):
        if band.kind != "gte" and band.high < 71:
            assert value == 0.0
    assert result.vector[[b.low for b in bands].index(71)] > 0.9


def test_sigma_floor_applies():
    bands = _bands(66, 77)
    narrow = stage.apply(bands, [1 / len(bands)] * len(bands), _eligible(70.0, 0.1), floor=60.0)
    floored = stage.apply(bands, [1 / len(bands)] * len(bands), _eligible(70.0, 1.0), floor=60.0)
    assert narrow.sigma == 1.0 and narrow.vector == floored.vector


def test_edge_rules():
    bands = [Band("lte", 66, 66), Band("eq", 67, 68), Band("eq", 69, 70), Band("gte", 71, 71)]
    # low <= B opens the lower edge; high < B (non-gte) gets 0; gte is open above
    p = stage.band_probs(bands, floor_bucket=69, mu=69.0, sigma=1.0)
    assert p[0] == 0.0 and p[1] == 0.0
    assert math.isclose(p[2], stage._ndtr(1.5), abs_tol=1e-15)
    assert math.isclose(p[3], 1 - stage._ndtr(1.5), abs_tol=1e-15)


@pytest.mark.parametrize(
    "read, floor, unit, reason",
    [
        (NbmV2Read(False, "parser_version_not_2"), 60.0, "F", "parser_version_not_2"),
        (_eligible(), None, "F", "missing_floor"),
        (_eligible(), float("nan"), "F", "missing_floor"),
        (_eligible(), 60.0, "C", "unit_not_fahrenheit"),
    ],
)
def test_fallback_is_the_served_vector_bit_exact(read, floor, unit, reason):
    bands = _bands(66, 77)
    served = [0.1, 0.2, 0.3, 0.05, 0.05, 0.1, 0.2]
    assert len(served) == len(bands)
    result = stage.apply(bands, served, read, floor, unit=unit)
    assert result.status == "fallback" and result.reason == reason
    assert result.vector == tuple(served)


def test_zero_mass_falls_back_to_unmasked_served():
    bands = [Band("lte", 60, 60), Band("eq", 61, 62), Band("gte", 63, 63)]
    served = [0.5, 0.3, 0.2]
    # mean far below a floor; ndtr underflows only far in the tail, so force it with a huge gap
    result = stage.apply(bands, served, _eligible(mean=-1e6, sd=1.0), floor=61.0)
    assert result.status == "mg1"  # mass collapses onto the floor band, not zero
    result = stage.apply([Band("eq", 61, 62)], [1.0], _eligible(mean=1e6, sd=1.0), floor=61.0)
    assert result.status == "fallback" and result.reason == "zero_mass" and result.vector == (1.0,)


def test_vector_already_summing_to_one_is_kept_bit_exact():
    bands = _bands(66, 77)
    result = stage.apply(bands, [1 / len(bands)] * len(bands), _eligible(71.0, 2.0), floor=50.0)
    p = stage.band_probs(bands, 50, 71.0, 2.0)
    total = sum(p)
    assert result.vector == tuple(value / total for value in p)


def test_length_mismatch_refuses():
    with pytest.raises(ValueError):
        stage.apply(_bands(66, 77), [1.0], _eligible(), 60.0)
