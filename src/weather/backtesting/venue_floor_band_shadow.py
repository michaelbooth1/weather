"""Offline comparison of an exact native-degree floor and its public highest-temperature bins."""

import hashlib
import json
import math
from types import SimpleNamespace

from weather.backtesting.venue_floor_shadow import _degree_mass, _hash, _instant, evaluate_floor_shadow
from weather.model.model_presentation import PresentationMixin
from weather.units import parse_temperature_band


def presentation_sha256(presentation):
    """Canonical digest of the independently retained, price-free capture projection."""
    encoded = json.dumps(presentation, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ladder(rows, unit):
    bins = []
    for row in rows:
        if set(row) != {"label", "kind", "value", "value_hi", "model_probability"}:
            return None
        band = parse_temperature_band(row["label"], expected_unit=unit)
        p = row["model_probability"]
        lo = row["value"]
        hi = lo if row["value_hi"] is None else row["value_hi"]
        if (band is None or type(lo) is not int or type(hi) is not int
                or (row["kind"], lo, hi) != (band.kind, band.value, band.value_hi)
                or type(p) not in (int, float) or not 0 <= p <= 1):
            return None
        bins.append((band, row["label"], p))
    bins.sort(key=lambda entry: entry[0].value)
    if len(bins) < 2 or bins[0][0].kind != "lte" or bins[-1][0].kind != "gte":
        return None
    if any(band.kind != "eq" for band, _, _ in bins[1:-1]):
        return None
    if any(right[0].value != left[0].value_hi + 1 for left, right in zip(bins, bins[1:])):
        return None
    return [dict(kind=b.kind, value=b.value, value_hi=b.value_hi, unit=unit, label=label)
            for b, label, _ in bins], [p for _, _, p in bins]


def _same_probability(left, right):
    # Zero was the defining observation in the historical comparison.
    if left in (0, 1) or right in (0, 1):
        return left == right
    return math.isclose(left, right, rel_tol=1e-11, abs_tol=0)


def _public_arm(client, mass, bins, context, native):
    public = [client.bin_probability(mass, band, calibration_context=context) for band in bins]
    added = math.fsum(max(p - raw, 0) for p, raw in zip(public, native))
    removed = math.fsum(max(raw - p, 0) for p, raw in zip(public, native))
    total = math.fsum(public)
    # A higher retained context may drop a positive band without redistributing it.
    # A forced upper tail instead assigns 1 to it and 0 to all lower bands.
    certain_tail = public[-1] == 1 and all(p == 0 for p in public[:-1])
    scoreable = math.isclose(total, 1, rel_tol=0, abs_tol=1e-12) and (
        not removed or added > 0 or certain_tail
    )
    return dict(public=public, total=total, added=added, removed=removed, scoreable_pmf=scoreable)


def evaluate_floor_band_shadow(packet, spec, presentation):
    """Replay four degree/presentation floor combinations on one closed incumbent.

    The caller independently attests the presentation digest and resolved
    artifact digest on the captured prior. The numeric model_bin_probability
    writer uses the same bin_probability function. No event or price is read.
    """
    def abstain(reason):
        return {"status": "abstained", "reason": reason}

    prior = packet["prior"]
    if packet["family"] != "highest" or prior["stage"] != "pre_calibration_model":
        return abstain("unsupported_family_or_stage")
    if presentation.get("distribution_kind") != "native_integer" or presentation.get("boundary_active") is not False:
        return abstain("unsupported_distribution_or_intervening_guard")
    cal = prior["calibration"]
    keys = ("market", "station", "unit", "family", "target_date", "as_of")
    if (any(presentation.get(k) != packet[k] for k in keys)
            or presentation.get("prior_capture_sha256") != prior["capture_sha256"]
            or presentation.get("model_sha256") != prior["model_sha256"]
            or presentation.get("calibration_capture_sha256") != cal["capture_sha256"]
            or not _hash(cal.get("artifact_sha256"))
            or presentation.get("artifact_sha256") != cal["artifact_sha256"]
            or presentation.get("exact_distribution") != cal["exact_distribution"]
            or presentation_sha256(presentation) != prior.get("presentation_sha256")):
        return abstain("unbound_presentation")
    if _instant(presentation["recorded_at"]) > _instant(packet["as_of"]):
        return abstain("presentation_after_decision")
    if "market_bin" not in presentation or not isinstance(presentation["market_bin"], dict):
        return abstain("unknown_market_bin_configuration")
    config = presentation["market_bin"]
    if any(type(config[k]) is not bool for k in ("enabled", "preserve_distribution_coherence") if k in config):
        return abstain("unknown_market_bin_configuration")
    if config.get("enabled", True) and not config.get("preserve_distribution_coherence", True):
        return abstain("unsupported_noncoherent_market_bin_route")
    context = presentation.get("context") or {}
    if ("observed_floor_bucket" not in context or context["observed_floor_bucket"] != packet["incumbent_bound"]
            or (context["observed_floor_bucket"] is not None and type(context["observed_floor_bucket"]) is not int)
            or context.get("cutoff_hour") != cal["cutoff_hour"] or context.get("lockin_strength") != cal["resolution_weight"]):
        return abstain("unmatched_presentation_context")
    ladder = _ladder(presentation["bands"], packet["unit"])
    if ladder is None:
        return abstain("incomplete_or_invalid_native_ladder")
    bins, recorded = ladder
    shadow = evaluate_floor_shadow(packet, spec)
    if shadow["status"] not in {"running", "final", "wu_fallback"}:
        return abstain(shadow.get("reason", shadow["status"]))
    incumbent, candidate = shadow["incumbent"], shadow["candidate"]
    closed = _degree_mass(presentation["final_degree_mass"])
    if closed.keys() != incumbent["mass"].keys() or any(
        not _same_probability(p, incumbent["mass"][degree]) for degree, p in closed.items()
    ):
        return abstain("incumbent_final_degree_mismatch")

    client = PresentationMixin()
    client.spec = SimpleNamespace(display_unit=packet["unit"])
    client.probability_calibration = {}
    native = {
        name: [client.bin_probability(arm["mass"], band, calibration_context={}) for band in bins]
        for name, arm in (("incumbent", incumbent), ("candidate", candidate))
    }
    client.probability_calibration = {"market_bin": config}
    old = _public_arm(client, incumbent["mass"], bins, context, native["incumbent"])
    if any(not _same_probability(p, observed) for p, observed in zip(old["public"], recorded)):
        return abstain("incumbent_public_band_mismatch")
    joint_context = {**context, "observed_floor_bucket": candidate["bound"]}
    return dict(
        status="closed_incumbent", rule_status=shadow["status"], rule_basis=shadow["rule_basis"],
        rule_sha256=shadow["rule_sha256"], evidence_capture_sha256=shadow["evidence_capture_sha256"],
        as_of=shadow["as_of"], presentation_sha256=prior["presentation_sha256"], artifact_sha256=cal["artifact_sha256"],
        incumbent_bound=incumbent["bound"], candidate_bound=candidate["bound"],
        bands=[band["label"] for band in bins], native=native,
        incumbent=old,
        degree_only=_public_arm(client, candidate["mass"], bins, context, native["candidate"]),
        presentation_only=_public_arm(client, incumbent["mass"], bins, joint_context, native["incumbent"]),
        joint=_public_arm(client, candidate["mass"], bins, joint_context, native["candidate"]),
    )
