"""Paired research projection of the flagship's soft evening temperature shaper."""

import math
from datetime import timedelta
from zoneinfo import ZoneInfo

from weather.backtesting.venue_floor_shadow import _degree_mass, _instant, evaluate_floor_shadow
from weather.market.metar_reports import parse_metar
from weather.market.venue_settlement_rules import native_decimal
from weather.model.model_constants import SOURCE_CACHE_TTL_MINUTES
from weather.model.model_distribution import DistributionMixin
from weather.units import round_half_up


class _TemperatureShaper(DistributionMixin):
    round_half_up = staticmethod(round_half_up)

    def __init__(self, serving_spec):
        self.spec = serving_spec


def evaluate_cold_upper_shadow(floor_packet, stage, venue_spec, serving_spec):
    """Evaluate only the positive upper-tail operator on its own captured prior.

    The paired floor packet supplies independently validated running-rule evidence.
    Its probability vector is never used as the input to the upper-tail operator.
    """
    stage_name = "input_to_apply_late_day_lockin"
    prior = floor_packet["prior"]
    identity = ("market", "station", "unit", "family", "target_date", "as_of", "capture_sha256", "model_sha256")
    if (stage["stage"] != stage_name or not stage["event_id"] or stage["event_id"] != floor_packet["event_id"]
            or any(stage[k] != prior[k] for k in identity)):
        raise ValueError("requires both stages from the same recorded event, capture, clock and model")
    if prior["stage"] != "input_to_apply_lockin_observed_floor":
        raise ValueError("requires the captured companion hard-floor stage")
    mass = _degree_mass(stage["mass"])
    evidence = evaluate_floor_shadow(floor_packet, venue_spec)
    result = dict(status="unchanged", stage=stage_name, event_id=stage["event_id"],
                  **{k: stage[k] for k in identity}, rule_sha256=evidence["rule_sha256"],
                  evidence_capture_sha256=evidence["evidence_capture_sha256"],
                  incumbent=mass, candidate=dict(mass), total_variation=0.0)

    def unchanged(reason):
        return dict(result, reason=reason)

    if evidence["status"] != "running":
        return unchanged(evidence.get("reason", evidence["status"]))
    if (stage["family"] != "highest" or stage["unit"] != "F"
            or (serving_spec.icao, serving_spec.display_unit, serving_spec.timezone)
                != (venue_spec.station_id, venue_spec.market_unit, venue_spec.timezone)):
        return unchanged("unsupported_family_unit_or_station")
    now = _instant(stage["as_of"])
    zone = ZoneInfo(venue_spec.timezone)
    local = now.astimezone(zone)
    if local.date().isoformat() != stage["target_date"]:
        return unchanged("outside_target_day")
    if local.month not in (1, 2, 12):
        return unchanged("outside_evaluated_winter_months")
    if stage.get("temperature_quality") != "accepted_as_of_capture":
        return unchanged("temperature_quality_unverified")
    if (stage["wu_history_state"] != "empty_at_effective_cutoff" or stage["incumbent_anchor"] is not None
            or stage["selected_current_source"] != "metar" or stage["official_current_stale"] is not False
            or stage["incumbent_lockin_strength"] != 0):
        return unchanged("incumbent_context_not_isolated")
    bound = evidence["candidate"]["bound"]
    if bound is None or bound != evidence["incumbent"]["bound"]:
        return unchanged("hard_floor_not_already_rescued")

    # Only a running result on the same local day reaches here. The receipt-aware
    # adapter already rejected ambiguous revisions, an unsupported rule or an
    # incomplete stream. Select the latest admissible observation and revision.
    raw = floor_packet["evidence"]
    start = _instant(raw["from"])
    latest = None
    anchor = None
    for row in raw["reports"]:
        receipt = _instant(row["receipt_time"])
        if receipt > now:
            continue
        rpt = parse_metar(row["raw"], start, now, receipt_time=receipt, station_ids=(venue_spec.station_id,))
        if (rpt.station != venue_spec.station_id or not rpt.routine or rpt.observation_time is None
                or rpt.observation_time.astimezone(zone).date() != local.date()):
            continue
        if (rpt.observation_time.isoformat() == evidence["witness_observation"]
                and receipt.isoformat() == evidence["witness_receipt"]):
            anchor = rpt
        if latest is None or (rpt.observation_time, receipt) > (latest.observation_time, latest.receipt_time):
            latest = rpt
    if anchor is None or anchor.temperature_c is None or latest is None or latest.temperature_c is None:
        return unchanged("missing_numeric_routine_pair")
    if now - latest.observation_time > timedelta(minutes=SOURCE_CACHE_TTL_MINUTES["metar"]):
        return unchanged("latest_routine_too_old")
    high = float(native_decimal(anchor.temperature_c, "F"))
    current = float(native_decimal(latest.temperature_c, "F"))
    if not -49 <= high < 30 or not -49 <= current <= high:
        return unchanged("outside_cold_range")
    if (not isinstance(stage["current_native"], (float, int)) or isinstance(stage["current_native"], bool)
            or not math.isclose(current, stage["current_native"], rel_tol=0, abs_tol=0.0001)
            or _instant(stage["current_observation_time"]) != latest.observation_time):
        return unchanged("captured_current_does_not_match_latest_routine")
    shaper = _TemperatureShaper(serving_spec)
    strength = shaper.late_day_lockin_strength(local.hour, current, high)
    if strength <= 0:
        return unchanged("no_evening_drop")
    candidate = shaper.apply_late_day_lockin(mass, high, current, local.hour, strength=strength)
    if any((mass[k] > 0) != (candidate[k] > 0) for k in mass):
        return unchanged("numeric_support_loss")
    return dict(result, status="projected", candidate=candidate, strength=strength,
                unchanged_hard_bound=bound, high_native=high, current_native=current,
                high_observation=anchor.observation_time.isoformat(), high_receipt=anchor.receipt_time.isoformat(),
                current_observation=latest.observation_time.isoformat(), current_receipt=latest.receipt_time.isoformat(),
                conditional_until=evidence["conditional_until"], invalidating_events=evidence["invalidating_events"],
                total_variation=math.fsum(abs(candidate[k] - p) for k, p in mass.items()) / 2)
