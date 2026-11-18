"""Offline paired intervention on the captured input to a specific floor operator."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from weather.market.metar_reports import aware_utc, header_station, parse_metar
from weather.market.metar_settlement import MetarSettlementAdapter
from weather.market.venue_settlement_rules import native_decimal, settlement_bucket
from weather.sources.metar_history import report_temperature_c


def _instant(value):
    return aware_utc(datetime.fromisoformat(value))


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _degree_mass(values):
    mass = {}
    for key, value in values.items():
        degree = int(key)
        if str(degree) != str(key) or degree in mass:
            raise ValueError("prior needs unique native integer degree keys")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid prior mass")
        mass[degree] = value
    if not math.isclose(math.fsum(mass.values()), 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError("prior must sum to one")
    return mass


def _apply(mass, bound, family, stage):
    excluded = {k for k in mass if bound is not None and (k < bound if family == "highest" else k > bound)}
    before_mass = math.fsum(mass[k] for k in excluded)
    if stage == "input_to_apply_lockin_observed_floor":
        weights = {k: 0.0 if k in excluded else p for k, p in mass.items()}
        if bound is not None:
            weights[bound] = weights.get(bound, 0.0) + before_mass
    else:
        weights = {k: p * 0.000001 if k in excluded else p for k, p in mass.items()}
    total = math.fsum(weights.values())
    if total == 0:
        raise ValueError("stage has no numerically representable mass")
    after = {k: p / total for k, p in weights.items()}
    after_mass = math.fsum(after[k] for k in excluded)
    return dict(bound=bound, mass=after, positive_prior_on_feasible_side=any(
                    p > 0 for k, p in mass.items() if k not in excluded), excluded_prior_mass=before_mass,
                excluded_after_mass=after_mass, probability_moved=before_mass - after_mass)


def evaluate_floor_shadow(packet, spec):
    """Compare two bounds on one captured prior, without fetching or serving.

    The caller supplies a reviewed, independently verified rule spec and packet
    provenance. A valid running result remains conditional on future revisions.
    Invalid packet structure raises ValueError/KeyError. Unusable evidence
    returns a reason without producing a candidate forecast.
    """
    prior = packet["prior"]
    family, day = packet["family"], date.fromisoformat(packet["target_date"])
    as_of, zone = _instant(packet["as_of"]), ZoneInfo(spec.timezone)
    evidence, rule = packet["evidence"], packet["rule"]
    identity = ("market", "station", "unit", "family", "target_date", "as_of")
    if any(prior[k] != packet[k] for k in identity):
        raise ValueError("captured prior identity mismatch")
    if (packet["market"], packet["station"], packet["unit"]) != (spec.slug, spec.station_id, spec.market_unit):
        raise ValueError("rule station, market or unit mismatch")
    if any(rule[k] != packet[k] for k in ("market", "station", "unit", "family")):
        raise ValueError("reviewed rule identity mismatch")
    if prior["stage"] not in {"post_live_signals", "input_to_apply_lockin_observed_floor"} or not all(_hash(x) for x in
            (prior["capture_sha256"], prior["model_sha256"], rule["sha256"], evidence["capture_sha256"])):
        raise ValueError("requires captured operator input and source/rule identities")
    mass = _degree_mass(prior["mass"])
    incumbent = packet["incumbent_bound"]
    if incumbent is not None and type(incumbent) is not int:
        raise ValueError("incumbent bound must be a native integer or null")
    status = dict(market=spec.slug, station=spec.station_id, target_date=day.isoformat(), family=family,
                  unit=spec.market_unit, as_of=as_of.isoformat(), rule_basis=rule["basis"],
                  rule_sha256=rule["sha256"], prior_capture_sha256=prior["capture_sha256"], model_sha256=prior["model_sha256"],
                  evidence_capture_sha256=evidence["capture_sha256"], stage=prior["stage"])

    def abstain(reason):
        return dict(**status, status="abstained", reason=reason)

    if spec.settlement_kind != "metar_routine" or family not in {"highest", "lowest"} or family not in spec.families:
        return abstain("unsupported_rule_or_family")
    if rule["basis"] == "dated_event":
        if (_instant(rule["recorded_at"]) > as_of or date.fromisoformat(rule["effective_from"]) > day
                or (rule.get("effective_to") and day > date.fromisoformat(rule["effective_to"]))):
            return abstain("rule_not_yet_admissible")
    elif rule["basis"] != "retrospective_current_rule":
        return abstain("unreviewed_rule_basis")
    if as_of.astimezone(zone).date() < day:
        return abstain("before_target_local_day")
    if evidence["source"] != "awc_raw_metar" or evidence["station"] != spec.station_id:
        return abstain("wrong_source_or_station")
    start, end = _instant(evidence["from"]), _instant(evidence["through"])
    local_midnight = aware_utc(datetime.combine(day, time(), zone))
    if evidence["complete"] is not True or start > local_midnight or end != as_of or start > end:
        return abstain("incomplete_asof_capture")
    reports = []
    for row in evidence["reports"]:
        if not row.get("receipt_time"):
            return abstain("receipt_missing")
        receipt = _instant(row["receipt_time"])
        if receipt > as_of:
            continue
        report = parse_metar(row["raw"], start, end, receipt_time=receipt, station_ids=(spec.station_id,))
        if report.station is None and header_station(row["raw"])[0] is None:
            return abstain("unattributable_station")
        if report.station == spec.station_id and report.routine and report.observation_time:
            if report.observation_time > receipt:
                return abstain("receipt_predates_observation")
            if report.observation_time.astimezone(zone).date() == day:
                # Built-in labels also have a legacy raw parser. An abbreviated
                # or ambiguous T-group must not silently select a different value.
                legacy, _ = report_temperature_c(report.raw)
                if (None if legacy is None else native_decimal(legacy, "C")) != report.temperature_c:
                    return abstain("raw_parser_disagreement")
        reports.append(report)
    kwargs = {}
    wu = evidence.get("wu")
    if wu is not None:
        if (wu["station"], wu["unit"], wu["target_date"]) != (spec.station_id, spec.market_unit, day.isoformat()):
            return abstain("fallback_identity_mismatch")
        read_at = _instant(wu["read_at"])
        if read_at <= as_of:
            kwargs["wu_read_at"] = read_at
            if wu["status"] == "published":
                high, low = Decimal(str(wu["high"])), Decimal(str(wu["low"]))
                if not (high.is_finite() and low.is_finite() and high >= low):
                    raise ValueError("invalid native WU extrema")
                kwargs["wu_values"] = (high, low)
            elif wu["status"] == "confirmed_empty":
                kwargs["wu_empty"] = True
            else:
                return abstain("unverified_fallback")
    result = MetarSettlementAdapter().evaluate(spec, day, reports, as_of=as_of, family=family, **kwargs)
    state = result.status_for(family)
    if state == "wu_fallback" and result.source_read_at < result.fallback_deadline:
        return abstain("fallback_read_before_deadline")
    if state not in {"running", "final", "wu_fallback", "missing"}:
        return abstain(state)
    bound = result.maximum if family == "highest" else result.minimum
    # Fallback values already use native units; only apply the shared tie rule.
    if bound is not None:
        bound = settlement_bucket(bound, "C") if state == "wu_fallback" else int(bound)
    witness = result.maximum_observation if family == "highest" else result.minimum_observation
    condition, revisions = result.condition_for(family)
    return dict(**status, status=state, source=result.source, conditional_until=condition.isoformat(),
                invalidating_events=list(revisions), routine_count=result.observation_count,
                witness_observation=witness.observation_time.isoformat() if witness else None,
                witness_receipt=witness.receipt_time.isoformat() if witness else None,
                witness_corrected=witness.corrected if witness else None,
                witness_value_basis=witness.value_basis if witness else None,
                incumbent=_apply(mass, incumbent, family, prior["stage"]),
                candidate=_apply(mass, bound, family, prior["stage"]))
