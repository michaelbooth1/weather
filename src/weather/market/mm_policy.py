"""Pure shadow market-making policy and quote-intent tape writer.

This module has no execution adapter and no private-key dependency. It turns
latest fair values, promotion state, book freshness, observation-trigger
health, and risk caps into auditable quote or no-quote intents.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.io import normalize_csv_row, read_csv_rows as io_read_csv_rows
from weather.paths import data_path

from weather.market.clob_recon import (
    DEFAULT_JSON_OUT as DEFAULT_CLOB_RECON,
    policy_overrides_from_recon,
)
from weather.market.info_event_calendar import (
    DEFAULT_CONFIG_PATH as DEFAULT_INFORMATION_EVENT_CALENDAR,
    event_gate_for_row,
    load_calendar_config,
    quote_event_gate_fields,
    summarize_event_gate_rows,
)
from weather.market.market_microstructure_features import snapshot_band_key
from weather.market.market_registry import REGISTRY, spec_for_id, spec_for_slug
from weather.market.live_observation_normalization import (
    current_high_probability_summary,
    normalized_high_fields,
    normalized_high_for_market,
)
from weather.market.snapshot_cadence_quality import (
    cadence_adjusted_probability,
    snapshot_cadence_quality,
)


SCHEMA_VERSION = "mm_quote_intent_v0.2"
POLICY_VERSION = "mm_policy_v0.2"
EARLY_HOUR_GUARDRAIL_SCHEMA_VERSION = "early_hour_market_guardrail_v0.1"
DEFAULT_PROMOTION_REFRESH = data_path() / "backtest" / "f_family_promotion_refresh.json"
DEFAULT_KNOWN_EDGE_MAP = data_path() / "backtest" / "mm_known_edge_map.json"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_OBSERVATION_STATUS = DEFAULT_SNAPSHOTS_ROOT / "observation_trigger_status.json"
DEFAULT_OUT = data_path() / "backtest" / "quotes_long.csv"
DEFAULT_JSON_OUT = data_path() / "backtest" / "mm_policy_shadow.json"

DEFAULT_POLICY_CONFIG = {
    "policy_version": POLICY_VERSION,
    "tick_size": 0.001,
    "min_price": 0.001,
    "max_price": 0.999,
    "quote_size": 5.0,
    "harvest_half_spread": 0.01,
    "max_book_age_seconds": 120.0,
    "max_model_age_seconds": 900.0,
    "max_watcher_age_seconds": 120.0,
    "max_harvest_spread": 0.08,
    "max_edge_spread": 0.12,
    "min_depth_1pct_total": 1.0,
    "shadow_disagreement_stand_down": 0.08,
    "edge_min_advantage": 0.03,
    "edge_fee_buffer": 0.005,
    "adverse_selection_buffer": 0.01,
    "max_event_notional": 25.0,
    "max_band_notional": 10.0,
    "max_daily_loss": 25.0,
    "information_event_calendar_enabled": True,
    "information_event_calendar_path": str(DEFAULT_INFORMATION_EVENT_CALENDAR),
    "event_gate_widen_buffer": 0.01,
    "event_gate_exception_enabled": False,
    "event_gate_exception_event_classes": "",
    "event_gate_exception_evidence_status": "",
    "event_gate_exception_evidence_id": "",
    "event_gate_exception_risk_cap_usdc": 0.0,
    "clob_recon_policy_enabled": True,
    "clob_recon_path": str(DEFAULT_CLOB_RECON),
    "hourly_trust_multiplier_00_08": 0.35,
    "hourly_trust_multiplier_09_14": 0.85,
    "hourly_trust_multiplier_15_19": 1.0,
    "hourly_trust_multiplier_20_23": 0.75,
    "early_hour_guardrail_enabled": True,
    "early_hour_guardrail_market_weight": 0.35,
    "early_hour_guardrail_size_multiplier": 0.35,
    "early_hour_guardrail_quote_widen_buffer": 0.01,
    "early_hour_guardrail_min_edge_multiplier": 1.5,
    "early_hour_guardrail_override_min_edge": 0.10,
    "early_hour_guardrail_override_source_states": "all_fresh",
    "early_hour_guardrail_override_count_buckets": "normal_count,high_count,full_count",
    "early_hour_guardrail_override_disagreement_buckets": "low_disagreement,moderate_disagreement",
    "early_hour_guardrail_override_max_forecast_disagreement": 1.5,
    "snapshot_cadence_quality_enabled": True,
    "max_snapshot_cadence_gap_seconds": 900.0,
    "snapshot_cadence_stale_model_seconds": 900.0,
    "snapshot_cadence_confidence_haircut": 0.75,
    "snapshot_cadence_degraded_permission": "deny",
    "snapshot_cadence_quote_size_multiplier": 0.5,
    "snapshot_cadence_quote_widen_buffer": 0.01,
    "current_high_trust_gate_enabled": True,
    "current_high_trust_gate_start_hour_local": 15,
    "current_high_trust_gate_edge_action": "deny",
    "current_high_trust_gate_harvest_size_multiplier": 0.5,
    "current_high_trust_gate_quote_widen_buffer": 0.01,
}

HOURLY_TRUST_BANDS = [
    ("early_00_08", 0, 8, "hourly_trust_multiplier_00_08"),
    ("midday_09_14", 9, 14, "hourly_trust_multiplier_09_14"),
    ("late_15_19", 15, 19, "hourly_trust_multiplier_15_19"),
    ("closing_20_23", 20, 23, "hourly_trust_multiplier_20_23"),
]

QUOTE_COLUMNS = [
    "schema_version",
    "generated_at_utc",
    "policy_version",
    "policy_hash",
    "shadow_mode",
    "live_trade_permission",
    "quote_permission",
    "action",
    "regime",
    "side",
    "reason_code",
    "reason_detail",
    "event_gate_schema_version",
    "event_gate_status",
    "event_gate_action",
    "event_gate_reason_code",
    "event_gate_reason_detail",
    "event_gate_event_id",
    "event_gate_event_class",
    "event_gate_source",
    "event_gate_starts_at_utc",
    "event_gate_ends_at_utc",
    "event_gate_next_event_id",
    "event_gate_next_event_class",
    "event_gate_next_event_at_utc",
    "event_gate_exception_id",
    "event_gate_exception_risk_cap_usdc",
    "market_id",
    "event_slug",
    "snapshot_id",
    "captured_at_utc",
    "model_version",
    "promotion_state",
    "known_edge_taxonomy",
    "known_edge_allowed",
    "known_edge_permission",
    "known_edge_reason",
    "known_edge_record_key",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "clob_token_id",
    "condition_id",
    "fair_probability",
    "market_mid",
    "market_yes",
    "uncertainty",
    "edge",
    "bid_price",
    "bid_size",
    "ask_price",
    "ask_size",
    "inventory_notional",
    "event_notional",
    "band_notional",
    "event_risk_remaining",
    "book_spread",
    "book_depth_1pct_total",
    "book_imbalance_1pct",
    "book_age_seconds",
    "model_age_seconds",
    "watcher_age_seconds",
    "snapshot_cadence",
    "snapshot_cadence_quality_state",
    "snapshot_cadence_gap_count",
    "snapshot_cadence_max_gap_seconds",
    "snapshot_cadence_last_model_age_seconds",
    "snapshot_cadence_confidence_multiplier",
    "snapshot_cadence_permission",
    "snapshot_cadence_quote_size_multiplier",
    "snapshot_cadence_quote_widen_buffer",
    "snapshot_cadence_reason",
    "cadence_adjusted_fair_probability",
    "raw_current_high",
    "raw_current_high_bucket",
    "settlement_current_high",
    "high_source",
    "revision_state",
    "settlement_bin_key",
    "raw_current_high_bin_key",
    "probability_on_raw_current_high",
    "probability_on_settlement_current_high",
    "current_max_state",
    "current_max_disposition",
    "current_max_gap_to_wu_history",
    "current_max_gap_to_current_temp",
    "current_high_trusted",
    "current_high_guard_reason",
    "current_high_trust_gate_status",
    "current_high_trust_gate_action",
    "current_high_trust_gate_reason",
    "current_high_trust_gate_aggressive",
    "current_high_trust_gate_size_multiplier",
    "current_high_trust_gate_quote_widen_buffer",
    "capture_hour_utc",
    "capture_hour_local",
    "capture_timezone",
    "hourly_trust_band",
    "hourly_trust_multiplier",
    "source_fresh",
    "source_freshness_state",
    "heartbeat_ok",
    "latency_budget_status",
    "expected_reward_score",
    "expected_rebate_value",
    "adverse_selection_buffer",
    "early_hour_guardrail_schema_version",
    "early_hour_guardrail_status",
    "early_hour_guardrail_reason",
    "early_hour_guardrail_min_edge",
    "early_hour_guardrail_size_multiplier",
    "early_hour_guardrail_quote_widen_buffer",
    "early_hour_guardrail_override_allowed",
    "early_hour_guardrail_market_weight",
    "market_aware_overlay_probability",
    "market_aware_overlay_edge",
    "market_aware_overlay_used_for_risk_only",
    "final_size_limiter",
]


def maybe_float(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def first_present(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def clamp_probability(value):
    number = maybe_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_now(value=None):
    parsed = parse_time(value)
    return parsed or datetime.now(timezone.utc)


def bool_value(value, default=False):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ok", "pass"}


def _csv_tokens(value):
    return {
        normalize_token(item)
        for item in str(value or "").replace(";", ",").split(",")
        if normalize_token(item)
    }


def _market_spec_for_row(row):
    market_id = row.get("market_id")
    if market_id:
        return spec_for_id(market_id)
    return spec_for_slug(row.get("event_slug")) or spec_for_id(None)


def _row_capture_time(row, now=None):
    return parse_time(first_present(
        row,
        "generated_at_utc",
        "quote_time_utc",
        "captured_at_utc",
        "fill_time_utc",
    )) or parse_time(now)


def _hour_from_text(value):
    if value in (None, ""):
        return None
    text = str(value).strip().upper().replace("Z", "")
    if ":" in text:
        text = text.split(":", 1)[0]
    try:
        hour = int(float(text))
    except ValueError:
        return None
    return hour if 0 <= hour <= 23 else None


def hourly_trust_state(row, config=None, now=None):
    """Return the market-local hour bucket used for quote-risk controls."""
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    parsed = _row_capture_time(row, now=now)
    spec = _market_spec_for_row(row)
    timezone_name = getattr(spec, "timezone", "UTC")
    hour_utc = parsed.hour if parsed is not None else _hour_from_text(row.get("hour_utc"))
    hour_local = _hour_from_text(row.get("capture_hour_local"))
    if hour_local is None and parsed is not None:
        try:
            hour_local = parsed.astimezone(spec.tz).hour
        except Exception:
            hour_local = parsed.hour
    if hour_local is None:
        hour_local = hour_utc

    band_name = "unknown"
    multiplier = 1.0
    if hour_local is not None:
        for name, start, end, key in HOURLY_TRUST_BANDS:
            if start <= hour_local <= end:
                band_name = name
                multiplier = float(config.get(key, 1.0))
                break
    return {
        "capture_hour_utc": hour_utc,
        "capture_hour_local": hour_local,
        "capture_timezone": timezone_name,
        "hourly_trust_band": band_name,
        "hourly_trust_multiplier": multiplier,
    }


def _forecast_count_bucket(row):
    return normalize_token(first_present(
        row,
        "forecast_source_count_bucket",
        "source_count_bucket",
        "forecast_count_bucket",
    ))


def _forecast_disagreement_bucket(row):
    return normalize_token(first_present(
        row,
        "forecast_disagreement_bucket",
        "source_disagreement_bucket",
    ))


def _strong_early_hour_override(row, config, edge):
    if edge is None or abs(edge) < float(config["early_hour_guardrail_override_min_edge"]):
        return False, "edge_below_override_minimum"
    source_state = _row_source_freshness_state(row)
    source_states = _csv_tokens(config.get("early_hour_guardrail_override_source_states"))
    if source_state not in source_states:
        return False, "source_freshness_not_override_eligible"
    if not bool_value(row.get("source_fresh"), False):
        return False, "source_fresh_false"

    count_bucket = _forecast_count_bucket(row)
    count_buckets = _csv_tokens(config.get("early_hour_guardrail_override_count_buckets"))
    if count_bucket not in count_buckets:
        return False, "forecast_source_count_not_override_eligible"

    disagreement_bucket = _forecast_disagreement_bucket(row)
    disagreement_buckets = _csv_tokens(config.get("early_hour_guardrail_override_disagreement_buckets"))
    if disagreement_bucket not in disagreement_buckets:
        return False, "forecast_disagreement_not_override_eligible"

    disagreement = maybe_float(row.get("forecast_disagreement"))
    if disagreement is not None and disagreement > float(config["early_hour_guardrail_override_max_forecast_disagreement"]):
        return False, "forecast_disagreement_above_override_max"
    return True, "strong_source_agreement_override"


def early_hour_guardrail_state(row, config=None, now=None):
    """Risk-only market-aware guardrail metadata for quote decisions."""
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    trust = hourly_trust_state(row, config=config, now=now)
    fair = clamp_probability(first_present(row, "fair_probability", "model_probability", "candidate_p"))
    mid = _midpoint(row)
    edge = fair - mid if fair is not None and mid is not None else None
    market_weight = max(0.0, min(1.0, float(config["early_hour_guardrail_market_weight"])))
    overlay = None
    overlay_edge = None
    if fair is not None and mid is not None:
        overlay = (1.0 - market_weight) * fair + market_weight * mid
        overlay_edge = overlay - mid
    base_min_edge = (
        float(config["edge_min_advantage"])
        + float(config["edge_fee_buffer"])
        + float(config["adverse_selection_buffer"])
    )
    min_edge = base_min_edge * float(config["early_hour_guardrail_min_edge_multiplier"])
    enabled = bool_value(config.get("early_hour_guardrail_enabled"), True)
    status = "disabled"
    reason = "guardrail_disabled"
    size_multiplier = 1.0
    widen = 0.0
    override_allowed = False
    if enabled:
        if trust["hourly_trust_band"] != "early_00_08":
            status = "inactive"
            reason = "outside_early_hour_band"
        else:
            override_allowed, reason = _strong_early_hour_override(row, config, edge)
            if override_allowed:
                status = "override_allowed"
                size_multiplier = 1.0
            else:
                status = "active"
                size_multiplier = min(
                    float(config["early_hour_guardrail_size_multiplier"]),
                    float(trust["hourly_trust_multiplier"]),
                )
                widen = float(config["early_hour_guardrail_quote_widen_buffer"])
    return {
        **trust,
        "early_hour_guardrail_schema_version": EARLY_HOUR_GUARDRAIL_SCHEMA_VERSION,
        "early_hour_guardrail_status": status,
        "early_hour_guardrail_reason": reason,
        "early_hour_guardrail_min_edge": min_edge,
        "early_hour_guardrail_size_multiplier": max(0.0, min(1.0, size_multiplier)),
        "early_hour_guardrail_quote_widen_buffer": max(0.0, widen),
        "early_hour_guardrail_override_allowed": override_allowed,
        "early_hour_guardrail_market_weight": market_weight,
        "market_aware_overlay_probability": overlay,
        "market_aware_overlay_edge": overlay_edge,
        "market_aware_overlay_used_for_risk_only": True,
    }


def current_high_trust_gate_state(row, config=None, now=None, edge=None, mode=None):
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    state = {
        "current_high_trust_gate_status": "clear",
        "current_high_trust_gate_action": "allow",
        "current_high_trust_gate_reason": "",
        "current_high_trust_gate_aggressive": False,
        "current_high_trust_gate_size_multiplier": 1.0,
        "current_high_trust_gate_quote_widen_buffer": 0.0,
    }
    if not bool_value(config.get("current_high_trust_gate_enabled"), True):
        state.update({
            "current_high_trust_gate_status": "disabled",
            "current_high_trust_gate_reason": "current-high trust gate disabled",
        })
        return state
    if bool_value(row.get("current_high_trusted"), True):
        state["current_high_trust_gate_reason"] = "current-high state trusted"
        return state

    trust = hourly_trust_state(row, config=config, now=now)
    hour = trust.get("capture_hour_local")
    start_hour = float(config.get("current_high_trust_gate_start_hour_local") or 15)
    late_window = hour is None or float(hour) >= start_hour
    aggressive = str(mode or "").lower() == "edge"
    if not aggressive and edge is not None:
        threshold = (
            float(config["edge_min_advantage"])
            + float(config["edge_fee_buffer"])
            + float(config["adverse_selection_buffer"])
        )
        aggressive = abs(float(edge)) >= threshold
    reason_bits = [
        "untrusted_current_high",
        f"hour:{int(hour) if hour is not None else 'missing'}",
        f"current_max_state:{row.get('current_max_state') or 'unknown'}",
    ]
    if row.get("current_high_guard_reason"):
        reason_bits.append(f"guard:{row.get('current_high_guard_reason')}")
    state["current_high_trust_gate_reason"] = ";".join(reason_bits)
    state["current_high_trust_gate_aggressive"] = bool(aggressive)
    if not late_window:
        state["current_high_trust_gate_status"] = "observe"
        state["current_high_trust_gate_action"] = "allow_pre_late_window"
        return state
    if aggressive and str(config.get("current_high_trust_gate_edge_action") or "deny") == "deny":
        state["current_high_trust_gate_status"] = "blocked"
        state["current_high_trust_gate_action"] = "deny_aggressive_edge"
        return state
    state["current_high_trust_gate_status"] = "capped"
    state["current_high_trust_gate_action"] = "cap_and_widen"
    state["current_high_trust_gate_size_multiplier"] = max(
        0.0,
        min(1.0, float(config.get("current_high_trust_gate_harvest_size_multiplier") or 0.5)),
    )
    state["current_high_trust_gate_quote_widen_buffer"] = max(
        0.0,
        float(config.get("current_high_trust_gate_quote_widen_buffer") or 0.0),
    )
    return state


def policy_hash(config):
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def calendar_config_for_policy(config):
    if isinstance(config.get("_information_event_calendar_config"), dict):
        return config["_information_event_calendar_config"]
    overrides = {
        "enabled": bool_value(config.get("information_event_calendar_enabled"), True),
    }
    return load_calendar_config(
        config.get("information_event_calendar_path") or DEFAULT_INFORMATION_EVENT_CALENDAR,
        overrides=overrides,
    )


def row_with_event_gate(row, config, now):
    calendar_config = calendar_config_for_policy(config)
    gate = event_gate_for_row(row, now=now, config=calendar_config, policy_config=config)
    merged = dict(row)
    merged["_event_gate"] = gate
    return merged, gate


def config_with_clob_recon(config):
    enabled = bool_value(config.get("clob_recon_policy_enabled"), True)
    overrides, diagnostics = policy_overrides_from_recon(
        config.get("clob_recon_path") or DEFAULT_CLOB_RECON,
        enabled=enabled,
    )
    if overrides:
        config = {**config, **overrides}
    return config, diagnostics


def age_seconds(timestamp, now):
    parsed = parse_time(timestamp)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def promotion_state_from_action(action, verdict=None):
    action = str(action or "").upper()
    verdict = str(verdict or "").upper()
    if action == "PROMOTE_CANDIDATE" or verdict == "PASS":
        return "PASS"
    if action == "BLOCK_CANDIDATE" or verdict == "BLOCK":
        return "BLOCK"
    if action == "KEEP_SHADOW" or verdict == "SHADOW":
        return "SHADOW"
    return "BLOCK"


def normalize_token(value):
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip().lower()


def load_known_edge_map(path=DEFAULT_KNOWN_EDGE_MAP):
    path = Path(path) if path else None
    if path is None:
        return [], {"path": None, "exists": False, "record_count": 0}
    if not path.exists():
        return [], {"path": str(path), "exists": False, "record_count": 0}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    records = payload.get("records") or []
    return records, {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "record_count": len(records),
        "summary": payload.get("summary") or {},
    }


def known_edge_record_key(record):
    fields = [
        "market_id",
        "cutoff",
        "hour_utc",
        "band_distance_bucket",
        "band_type",
        "casebook_taxonomy",
        "regime",
        "source_fresh",
        "source_freshness_state",
        "book_imbalance_bucket",
    ]
    return "|".join(normalize_token(record.get(field)) or "*" for field in fields)


def _wildcard(value):
    return normalize_token(value) in {"", "*", "any", "all"}


def _row_hour_utc(row):
    value = first_present(row, "hour_utc", "utc_hour")
    if value not in (None, ""):
        return normalize_token(value)
    parsed = parse_time(first_present(row, "captured_at_utc", "generated_at_utc"))
    if parsed is None:
        return ""
    return str(parsed.hour)


def _row_cutoff(row):
    return normalize_token(first_present(row, "cutoff", "cutoff_hour", "effective_cutoff_hour"))


def _row_source_fresh(row):
    if "source_fresh" not in row:
        return ""
    return "true" if bool_value(row.get("source_fresh"), False) else "false"


def _row_source_freshness_state(row):
    value = first_present(row, "source_freshness_state", "known_edge_source_freshness_state")
    if value not in (None, ""):
        return normalize_token(value)
    source_fresh = _row_source_fresh(row)
    if source_fresh == "true":
        return "all_fresh"
    if source_fresh == "false":
        return "stale_or_failed"
    return ""


def known_edge_row_dimensions(row):
    return {
        "market_id": normalize_token(row.get("market_id")),
        "cutoff": _row_cutoff(row),
        "hour_utc": _row_hour_utc(row),
        "band_distance_bucket": normalize_token(row.get("band_distance_bucket")),
        "band_type": normalize_token(first_present(row, "band_type", "bin_kind", "bin_type")),
        "casebook_taxonomy": normalize_token(first_present(row, "casebook_taxonomy", "known_edge_taxonomy")),
        "regime": normalize_token(row.get("regime")),
        "source_fresh": _row_source_fresh(row),
        "source_freshness_state": _row_source_freshness_state(row),
        "book_imbalance_bucket": normalize_token(row.get("book_imbalance_bucket")),
    }


def _record_matches_dimensions(record, dimensions):
    market_id = normalize_token(record.get("market_id"))
    if market_id not in {"*", dimensions.get("market_id")}:
        return False
    for field in (
        "hour_utc",
        "band_distance_bucket",
        "band_type",
        "casebook_taxonomy",
        "regime",
        "source_fresh",
        "source_freshness_state",
        "book_imbalance_bucket",
    ):
        record_value = record.get(field)
        if _wildcard(record_value):
            continue
        row_value = dimensions.get(field)
        if not row_value or normalize_token(record_value) != row_value:
            return False
    cutoff = normalize_token(record.get("cutoff"))
    if cutoff and cutoff not in {"*", "paper_slice"}:
        row_cutoff = dimensions.get("cutoff")
        if not row_cutoff or cutoff != row_cutoff:
            return False
    return True


def _record_specificity(record):
    fields = [
        "market_id",
        "cutoff",
        "hour_utc",
        "band_distance_bucket",
        "band_type",
        "casebook_taxonomy",
        "regime",
        "source_fresh",
        "source_freshness_state",
        "book_imbalance_bucket",
    ]
    score = 0
    for field in fields:
        value = normalize_token(record.get(field))
        if value and value not in {"*", "paper_slice"}:
            score += 1
    return score


def _permission_rank(record):
    ranks = {
        "no_quote": 0,
        "harvest_only": 1,
        "edge_research": 2,
        "edge_allowed": 3,
    }
    return ranks.get(normalize_token(record.get("permission")), 0)


def resolve_known_edge_record(row, records):
    dimensions = known_edge_row_dimensions(row)
    matches = [
        record for record in records
        if _record_matches_dimensions(record, dimensions)
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda record: (-_record_specificity(record), _permission_rank(record)))[0]


def apply_known_edge_permission(row, record=None, map_loaded=False):
    out = dict(row)
    if record is None:
        if map_loaded:
            out.update({
                "known_edge_allowed": False,
                "known_edge_permission": "no_quote",
                "known_edge_reason": "missing_known_edge_record",
                "known_edge_record_key": "",
            })
        else:
            out.update({
                "known_edge_allowed": False,
                "known_edge_permission": "harvest_only",
                "known_edge_reason": "known_edge_map_missing",
                "known_edge_record_key": "",
            })
        return out
    permission = normalize_token(record.get("permission")) or "no_quote"
    taxonomy = record.get("casebook_taxonomy")
    out.update({
        "known_edge_allowed": permission == "edge_allowed",
        "known_edge_permission": permission,
        "known_edge_reason": record.get("reason") or "",
        "known_edge_record_key": known_edge_record_key(record),
    })
    if not _wildcard(taxonomy):
        out["known_edge_taxonomy"] = taxonomy
    return out


def known_edge_allowed_from_row(row):
    permission = normalize_token(row.get("known_edge_permission"))
    if permission:
        return permission == "edge_allowed"
    return bool_value(row.get("known_edge_allowed"), False)


def load_promotion_states(path=DEFAULT_PROMOTION_REFRESH):
    path = Path(path)
    if not path.exists():
        return {}, {"path": str(path), "exists": False}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    states = {}
    allowlist = payload.get("promotion_allowlist") or {}
    allowlist_rows = allowlist.get("markets") or []
    decision_rows = ((payload.get("decisions") or {}).get("markets") or [])
    rows = allowlist_rows or decision_rows
    for row in rows:
        market_id = row.get("market_id")
        if not market_id:
            continue
        action = row.get("action")
        verdict = row.get("verdict")
        states[market_id] = {
            "promotion_state": promotion_state_from_action(action, verdict),
            "action": action,
            "verdict": verdict,
            "reason": row.get("blocker_reason") or row.get("reason"),
            "candidate_id": row.get("candidate_id") or allowlist.get("candidate_id"),
            "candidate_serving_allowed": row.get("candidate_serving_allowed"),
            "candidate_permission_allowed": row.get("candidate_permission_allowed"),
            "promotion_allowlist_enforced": bool(allowlist_rows),
        }
    micro_gate = (((payload.get("candidate") or {}).get("microstructure") or {}).get("gate") or {})
    return states, {
        "path": str(path),
        "exists": True,
        "market_count": len(states),
        "promotion_allowlist_enforced": bool(allowlist_rows),
        "promotion_allowlist_schema_version": allowlist.get("schema_version"),
        "promotion_allowlist_path": allowlist.get("path"),
        "microstructure_gate": micro_gate,
    }


def load_observation_status(path=DEFAULT_OBSERVATION_STATUS, now=None, config=None):
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    now = utc_now(now)
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "fresh": False,
            "heartbeat_ok": False,
            "watcher_age_seconds": None,
            "reason": "missing observation watcher status",
        }
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    watcher_age = age_seconds(payload.get("last_heartbeat"), now)
    consecutive_errors = int(payload.get("consecutive_errors") or 0)
    fresh = (
        watcher_age is not None
        and watcher_age <= float(config["max_watcher_age_seconds"])
        and consecutive_errors == 0
    )
    markets = payload.get("markets") or {}
    market_normalization = {
        market_id: normalized_high_for_market({"markets": markets}, market_id)
        for market_id in markets
    }
    return {
        "path": str(path),
        "exists": True,
        "fresh": fresh,
        "heartbeat_ok": fresh,
        "watcher_age_seconds": watcher_age,
        "last_heartbeat": payload.get("last_heartbeat"),
        "consecutive_errors": consecutive_errors,
        "markets": markets,
        "market_normalization": market_normalization,
        "reason": "fresh" if fresh else "stale or erroring observation watcher",
    }


def _midpoint(row):
    for key in ("market_mid", "clob_midpoint"):
        value = clamp_probability(row.get(key))
        if value is not None:
            return value
    bid = clamp_probability(first_present(row, "clob_best_bid", "best_bid"))
    ask = clamp_probability(first_present(row, "clob_best_ask", "best_ask"))
    if bid is not None and ask is not None and ask >= bid:
        return (bid + ask) / 2.0
    return clamp_probability(row.get("market_yes"))


def _book_spread(row):
    spread = maybe_float(first_present(row, "book_spread", "clob_spread"))
    if spread is not None:
        return max(0.0, spread)
    bid = clamp_probability(first_present(row, "clob_best_bid", "best_bid"))
    ask = clamp_probability(first_present(row, "clob_best_ask", "best_ask"))
    if bid is not None and ask is not None and ask >= bid:
        return ask - bid
    return None


def _book_age(row, now):
    for key in ("book_age_seconds", "clob_book_age_seconds"):
        value = maybe_float(row.get(key))
        if value is not None:
            return max(0.0, value)
    return age_seconds(row.get("clob_book_captured_at_utc"), now)


def _risk_limited_size(row, config, price):
    desired = float(config["quote_size"])
    price = max(float(config["min_price"]), min(float(config["max_price"]), float(price or 0.0)))
    current_event = maybe_float(row.get("event_notional")) or 0.0
    current_band = maybe_float(row.get("band_notional")) or 0.0
    daily_loss = maybe_float(row.get("daily_loss")) or 0.0
    event_remaining = max(0.0, float(config["max_event_notional"]) - current_event)
    band_remaining = max(0.0, float(config["max_band_notional"]) - current_band)
    loss_remaining = max(0.0, float(config["max_daily_loss"]) + daily_loss)
    candidates = [
        ("configured_size", desired),
        ("event_notional_cap", event_remaining / price),
        ("band_notional_cap", band_remaining / price),
        ("daily_loss_cap", loss_remaining / price),
    ]
    exception = ((row.get("_event_gate") or {}).get("exception") or {})
    exception_cap = maybe_float(exception.get("risk_cap_usdc"))
    if exception_cap is not None:
        candidates.append(("event_gate_exception_risk_cap", max(0.0, exception_cap) / price))
    limiter, size = min(candidates, key=lambda item: item[1])
    return max(0.0, size), limiter, event_remaining


def _base_output(row, config, now, reason_code, reason_detail):
    fair = clamp_probability(first_present(row, "fair_probability", "model_probability", "candidate_p"))
    mid = _midpoint(row)
    edge = fair - mid if fair is not None and mid is not None else None
    guardrail = early_hour_guardrail_state(row, config=config, now=now)
    uncertainty = maybe_float(row.get("uncertainty"))
    if uncertainty is None and fair is not None:
        uncertainty = math.sqrt(max(0.0, fair * (1.0 - fair)))
    book_age = _book_age(row, now)
    model_age = maybe_float(row.get("model_age_seconds"))
    if model_age is None:
        model_age = age_seconds(row.get("captured_at_utc"), now)
    watcher_age = maybe_float(row.get("watcher_age_seconds"))
    cadence = snapshot_cadence_quality({
        **row,
        "model_age_seconds": model_age,
    }, config=config, now=now)
    cadence_adjusted_fair = cadence_adjusted_probability(
        fair,
        mid,
        cadence.get("snapshot_cadence_confidence_multiplier"),
    )
    current_high_gate = current_high_trust_gate_state(row, config=config, now=now, edge=edge, mode="none")
    output = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": policy_hash(config),
        "shadow_mode": True,
        "live_trade_permission": False,
        "quote_permission": False,
        "action": "NO_QUOTE",
        "regime": "none",
        "side": "-",
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "market_id": row.get("market_id") or "",
        "event_slug": row.get("event_slug") or "",
        "snapshot_id": row.get("snapshot_id") or "",
        "captured_at_utc": row.get("captured_at_utc") or "",
        "model_version": row.get("model_version") or "",
        "promotion_state": row.get("promotion_state") or "BLOCK",
        "known_edge_taxonomy": row.get("known_edge_taxonomy") or row.get("casebook_taxonomy") or "",
        "known_edge_allowed": known_edge_allowed_from_row(row),
        "known_edge_permission": row.get("known_edge_permission") or "",
        "known_edge_reason": row.get("known_edge_reason") or "",
        "known_edge_record_key": row.get("known_edge_record_key") or "",
        "range_label": row.get("range_label") or "",
        "bin_kind": row.get("bin_kind") or row.get("bin_type") or "",
        "bin_value": row.get("bin_value") or row.get("bin_value_c") or "",
        "bin_value_hi": row.get("bin_value_hi") or "",
        "clob_token_id": row.get("clob_token_id") or row.get("clob_yes_token_id") or "",
        "condition_id": row.get("condition_id") or "",
        "fair_probability": fair,
        "market_mid": mid,
        "market_yes": clamp_probability(row.get("market_yes")),
        "uncertainty": uncertainty,
        "edge": edge,
        "bid_price": None,
        "bid_size": 0.0,
        "ask_price": None,
        "ask_size": 0.0,
        "inventory_notional": maybe_float(row.get("inventory_notional")) or 0.0,
        "event_notional": maybe_float(row.get("event_notional")) or 0.0,
        "band_notional": maybe_float(row.get("band_notional")) or 0.0,
        "event_risk_remaining": max(0.0, float(config["max_event_notional"]) - (maybe_float(row.get("event_notional")) or 0.0)),
        "book_spread": _book_spread(row),
        "book_depth_1pct_total": maybe_float(first_present(row, "book_depth_1pct_total", "clob_depth_1pct_total")),
        "book_imbalance_1pct": maybe_float(first_present(row, "book_imbalance_1pct", "clob_imbalance_1pct")),
        "book_age_seconds": book_age,
        "model_age_seconds": model_age,
        "watcher_age_seconds": watcher_age,
        **cadence,
        "cadence_adjusted_fair_probability": cadence_adjusted_fair,
        "raw_current_high": row.get("raw_current_high"),
        "raw_current_high_bucket": row.get("raw_current_high_bucket"),
        "settlement_current_high": row.get("settlement_current_high"),
        "high_source": row.get("high_source") or "",
        "revision_state": row.get("revision_state") or "",
        "settlement_bin_key": row.get("settlement_bin_key") or "",
        "raw_current_high_bin_key": row.get("raw_current_high_bin_key") or "",
        "probability_on_raw_current_high": maybe_float(row.get("probability_on_raw_current_high")),
        "probability_on_settlement_current_high": maybe_float(row.get("probability_on_settlement_current_high")),
        "current_max_state": row.get("current_max_state") or "",
        "current_max_disposition": row.get("current_max_disposition") or "",
        "current_max_gap_to_wu_history": maybe_float(row.get("current_max_gap_to_wu_history")),
        "current_max_gap_to_current_temp": maybe_float(row.get("current_max_gap_to_current_temp")),
        "current_high_trusted": bool_value(row.get("current_high_trusted"), True),
        "current_high_guard_reason": row.get("current_high_guard_reason") or "",
        **current_high_gate,
        "capture_hour_utc": guardrail["capture_hour_utc"],
        "capture_hour_local": guardrail["capture_hour_local"],
        "capture_timezone": guardrail["capture_timezone"],
        "hourly_trust_band": guardrail["hourly_trust_band"],
        "hourly_trust_multiplier": guardrail["hourly_trust_multiplier"],
        "source_fresh": bool_value(row.get("source_fresh"), False),
        "source_freshness_state": row.get("source_freshness_state") or "",
        "heartbeat_ok": bool_value(row.get("heartbeat_ok"), False),
        "latency_budget_status": "blocked",
        "expected_reward_score": 0.0,
        "expected_rebate_value": 0.0,
        "adverse_selection_buffer": float(config["adverse_selection_buffer"]),
        "early_hour_guardrail_schema_version": guardrail["early_hour_guardrail_schema_version"],
        "early_hour_guardrail_status": guardrail["early_hour_guardrail_status"],
        "early_hour_guardrail_reason": guardrail["early_hour_guardrail_reason"],
        "early_hour_guardrail_min_edge": guardrail["early_hour_guardrail_min_edge"],
        "early_hour_guardrail_size_multiplier": guardrail["early_hour_guardrail_size_multiplier"],
        "early_hour_guardrail_quote_widen_buffer": guardrail["early_hour_guardrail_quote_widen_buffer"],
        "early_hour_guardrail_override_allowed": guardrail["early_hour_guardrail_override_allowed"],
        "early_hour_guardrail_market_weight": guardrail["early_hour_guardrail_market_weight"],
        "market_aware_overlay_probability": guardrail["market_aware_overlay_probability"],
        "market_aware_overlay_edge": guardrail["market_aware_overlay_edge"],
        "market_aware_overlay_used_for_risk_only": guardrail["market_aware_overlay_used_for_risk_only"],
        "final_size_limiter": "-",
    }
    output.update(quote_event_gate_fields(row.get("_event_gate")))
    return output


def _no_quote(row, config, now, reason_code, reason_detail):
    return _base_output(row, config, now, reason_code, reason_detail)


def _quote(row, config, now, regime, side, reason_code, bid_price=None, ask_price=None):
    output = _base_output(row, config, now, reason_code, "quote permitted by shadow policy")
    current_high_gate = current_high_trust_gate_state(
        row,
        config=config,
        now=now,
        edge=output.get("edge"),
        mode=regime,
    )
    output.update(current_high_gate)
    widen = maybe_float(output.get("early_hour_guardrail_quote_widen_buffer")) or 0.0
    cadence_degraded = output.get("snapshot_cadence_quality_state") in {"gappy", "stale", "missing", "blocked"}
    if cadence_degraded:
        widen += maybe_float(output.get("snapshot_cadence_quote_widen_buffer")) or 0.0
    if output.get("current_high_trust_gate_status") == "capped":
        widen += maybe_float(output.get("current_high_trust_gate_quote_widen_buffer")) or 0.0
    if widen > 0.0:
        min_price = float(config["min_price"])
        max_price = float(config["max_price"])
        if bid_price is not None:
            bid_price = max(min_price, float(bid_price) - widen)
        if ask_price is not None:
            ask_price = min(max_price, float(ask_price) + widen)
    price_for_size = 0.0
    if bid_price is not None:
        price_for_size += max(0.0, float(bid_price))
    if ask_price is not None:
        price_for_size += max(0.0, 1.0 - float(ask_price))
    if price_for_size <= 0:
        price_for_size = bid_price if bid_price is not None else ask_price
    size, limiter, event_remaining = _risk_limited_size(row, config, price_for_size)
    size_multiplier = maybe_float(output.get("early_hour_guardrail_size_multiplier")) or 1.0
    if output.get("early_hour_guardrail_status") == "active" and size_multiplier < 1.0:
        size *= max(0.0, size_multiplier)
        limiter = "early_hour_market_guardrail"
    cadence_size_multiplier = maybe_float(output.get("snapshot_cadence_quote_size_multiplier")) or 1.0
    if cadence_degraded and cadence_size_multiplier < 1.0:
        size *= max(0.0, cadence_size_multiplier)
        limiter = (
            "snapshot_cadence_quality"
            if limiter == "configured_size"
            else f"{limiter}+snapshot_cadence_quality"
        )
    current_high_size_multiplier = maybe_float(output.get("current_high_trust_gate_size_multiplier")) or 1.0
    if output.get("current_high_trust_gate_status") == "capped" and current_high_size_multiplier < 1.0:
        size *= max(0.0, current_high_size_multiplier)
        limiter = (
            "current_high_trust_gate"
            if limiter == "configured_size"
            else f"{limiter}+current_high_trust_gate"
        )
    if size <= 0:
        return _no_quote(row, config, now, "NO_QUOTE_RISK_CAP", f"{limiter} leaves no quote size")
    output.update({
        "quote_permission": True,
        "action": "QUOTE",
        "regime": regime,
        "side": side,
        "bid_price": bid_price,
        "bid_size": size if bid_price is not None else 0.0,
        "ask_price": ask_price,
        "ask_size": size if ask_price is not None else 0.0,
        "event_risk_remaining": event_remaining,
        "latency_budget_status": "ok",
        "expected_reward_score": min(1.0, max(0.0, (output.get("book_depth_1pct_total") or 0.0) / 1000.0)),
        "final_size_limiter": limiter,
    })
    return output


def decide_quote(row, config=None, now=None):
    """Pure policy function: one input band -> one quote/no-quote intent."""
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    now = utc_now(now)
    row, event_gate = row_with_event_gate(row, config, now)
    promotion_state = str(row.get("promotion_state") or "BLOCK").upper()
    known_edge_permission = normalize_token(row.get("known_edge_permission"))
    if known_edge_permission == "no_quote":
        return _no_quote(
            row,
            config,
            now,
            "NO_QUOTE_KNOWN_EDGE_PERMISSION",
            row.get("known_edge_reason") or "known-edge map permission is no_quote",
        )
    if promotion_state == "BLOCK":
        return _no_quote(row, config, now, "NO_QUOTE_BLOCKED_PROMOTION", "promotion state is BLOCK")
    if not bool_value(row.get("heartbeat_ok"), False):
        return _no_quote(row, config, now, "NO_QUOTE_STALE_WATCHER", "observation watcher heartbeat is stale")
    if not bool_value(row.get("source_fresh"), False):
        return _no_quote(row, config, now, "NO_QUOTE_SOURCE_STALE", "source freshness gate is false")
    if bool_value(row.get("near_decisive_window"), False):
        return _no_quote(row, config, now, "NO_QUOTE_NEAR_DECISIVE_WINDOW", "decisive observation window")
    if str(row.get("market_status") or "active").lower() not in {"active", "open", ""}:
        return _no_quote(row, config, now, "NO_QUOTE_MARKET_INACTIVE", "market is not active")
    if event_gate.get("action") == "suppress":
        return _no_quote(
            row,
            config,
            now,
            "NO_QUOTE_INFORMATION_EVENT",
            event_gate.get("reason_detail") or "information-event quote-pull window",
        )
    if event_gate.get("action") == "widen":
        config = {
            **config,
            "adverse_selection_buffer": (
                float(config["adverse_selection_buffer"])
                + float(config.get("event_gate_widen_buffer") or 0.0)
            ),
        }

    fair = clamp_probability(first_present(row, "fair_probability", "model_probability", "candidate_p"))
    mid = _midpoint(row)
    spread = _book_spread(row)
    book_age = _book_age(row, now)
    model_age = maybe_float(row.get("model_age_seconds"))
    if model_age is None:
        model_age = age_seconds(row.get("captured_at_utc"), now)
    watcher_age = maybe_float(row.get("watcher_age_seconds"))
    cadence = snapshot_cadence_quality({
        **row,
        "model_age_seconds": model_age,
    }, config=config, now=now)
    depth = maybe_float(first_present(row, "book_depth_1pct_total", "clob_depth_1pct_total")) or 0.0
    if fair is None:
        return _no_quote(row, config, now, "NO_QUOTE_MISSING_FAIR", "missing fair probability")
    if mid is None:
        return _no_quote(row, config, now, "NO_QUOTE_MISSING_BOOK", "missing book midpoint")
    if spread is None:
        return _no_quote(row, config, now, "NO_QUOTE_MISSING_BOOK", "missing book spread")
    if book_age is None or book_age > float(config["max_book_age_seconds"]):
        return _no_quote(row, config, now, "NO_QUOTE_STALE_BOOK", "book age exceeds latency budget")
    if model_age is None or model_age > float(config["max_model_age_seconds"]):
        return _no_quote(row, config, now, "NO_QUOTE_STALE_MODEL", "model age exceeds latency budget")
    if cadence.get("snapshot_cadence_permission") == "deny":
        return _no_quote(
            row,
            config,
            now,
            "NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED",
            cadence.get("snapshot_cadence_reason") or "snapshot cadence quality gate denied quote permission",
        )
    if watcher_age is None or watcher_age > float(config["max_watcher_age_seconds"]):
        return _no_quote(row, config, now, "NO_QUOTE_STALE_WATCHER", "watcher age exceeds latency budget")
    if depth < float(config["min_depth_1pct_total"]):
        return _no_quote(row, config, now, "NO_QUOTE_THIN_DEPTH", "book depth below minimum")

    fair_for_edge = cadence_adjusted_probability(
        fair,
        mid,
        cadence.get("snapshot_cadence_confidence_multiplier"),
    )
    if fair_for_edge is None:
        fair_for_edge = fair
    edge = fair_for_edge - mid
    tick = float(config["tick_size"])
    min_price = float(config["min_price"])
    max_price = float(config["max_price"])
    known_edge_allowed = known_edge_allowed_from_row(row)
    edge_threshold = (
        float(config["edge_min_advantage"])
        + float(config["edge_fee_buffer"])
        + float(config["adverse_selection_buffer"])
    )
    guardrail = early_hour_guardrail_state(row, config=config, now=now)
    current_high_edge_gate = current_high_trust_gate_state(
        row,
        config=config,
        now=now,
        edge=edge,
        mode="edge",
    )

    if promotion_state == "PASS" and known_edge_allowed and abs(edge) >= edge_threshold:
        if current_high_edge_gate.get("current_high_trust_gate_status") == "blocked":
            return _no_quote(
                row,
                config,
                now,
                "NO_QUOTE_CURRENT_HIGH_TRUST_GATE",
                current_high_edge_gate.get("current_high_trust_gate_reason")
                or "untrusted current-high state blocks aggressive edge quote",
            )
        if (
            guardrail.get("early_hour_guardrail_status") == "active"
            and abs(edge) < float(guardrail["early_hour_guardrail_min_edge"])
        ):
            return _no_quote(
                row,
                config,
                now,
                "NO_QUOTE_EARLY_HOUR_GUARDRAIL_MIN_EDGE",
                "early-hour guardrail requires stronger no-market edge or source-agreement override",
            )
        if spread > float(config["max_edge_spread"]):
            return _no_quote(row, config, now, "NO_QUOTE_WIDE_SPREAD", "spread too wide for edge mode")
        best_bid = clamp_probability(first_present(row, "clob_best_bid", "best_bid"))
        best_ask = clamp_probability(first_present(row, "clob_best_ask", "best_ask"))
        if edge > 0:
            ceiling = (best_ask - tick) if best_ask is not None else max_price
            bid_price = max(min_price, min(ceiling, fair_for_edge - float(config["adverse_selection_buffer"])))
            if best_ask is not None and bid_price >= best_ask:
                return _no_quote(row, config, now, "NO_QUOTE_POST_ONLY_CROSS", "edge bid would cross ask")
            if best_bid is not None and bid_price <= best_bid:
                return _no_quote(row, config, now, "NO_QUOTE_EDGE_TOO_SMALL", "edge does not improve resting bid")
            return _quote(row, config, now, "edge", "YES_BID", "QUOTE_EDGE_MODEL", bid_price=bid_price)
        floor = (best_bid + tick) if best_bid is not None else min_price
        ask_price = min(max_price, max(floor, fair_for_edge + float(config["adverse_selection_buffer"])))
        if best_bid is not None and ask_price <= best_bid:
            return _no_quote(row, config, now, "NO_QUOTE_POST_ONLY_CROSS", "edge ask would cross bid")
        if best_ask is not None and ask_price >= best_ask:
            return _no_quote(row, config, now, "NO_QUOTE_EDGE_TOO_SMALL", "edge does not improve resting ask")
        return _quote(row, config, now, "edge", "YES_ASK", "QUOTE_EDGE_MODEL", ask_price=ask_price)

    if abs(edge) >= float(config["shadow_disagreement_stand_down"]):
        return _no_quote(row, config, now, "NO_QUOTE_DISAGREEMENT_SHADOW", "model-market disagreement exceeds harvest veto")
    if spread > float(config["max_harvest_spread"]):
        return _no_quote(row, config, now, "NO_QUOTE_WIDE_SPREAD", "spread too wide for harvest mode")
    half_spread = float(config["harvest_half_spread"])
    bid_price = max(min_price, min(mid - tick, mid - half_spread))
    ask_price = min(max_price, max(mid + tick, mid + half_spread))
    if bid_price >= ask_price:
        return _no_quote(row, config, now, "NO_QUOTE_POST_ONLY_CROSS", "harvest quote would cross")
    return _quote(row, config, now, "harvest", "TWO_SIDED", "QUOTE_HARVEST_MID", bid_price=bid_price, ask_price=ask_price)


def _band_key(row):
    kind, value, value_hi = snapshot_band_key(row)
    token = row.get("clob_token_id") or row.get("clob_yes_token_id") or ""
    return (row.get("snapshot_id"), kind, value, value_hi, str(token))


def _band_key_without_token(row):
    kind, value, value_hi = snapshot_band_key(row)
    return (row.get("snapshot_id"), kind, value, value_hi)


def source_status_kind(item):
    item = item or {}
    status = normalize_token(item.get("status"))
    degradation = normalize_token(item.get("degradation_state"))
    if status in {"expected_current_day_unavailable", "expected_unavailable"} or degradation in {
        "expected_current_day_unavailable",
        "expected_unavailable",
    }:
        return "expected_unavailable"
    ok = None
    if item.get("ok") not in (None, ""):
        ok = bool_value(item.get("ok"), None)
    stale = None
    if item.get("stale") not in (None, ""):
        stale = bool_value(item.get("stale"), None)
    if ok is False or status in {"failed", "error", "missing", "rate_limited"}:
        return "failed"
    if stale is True or status in {"stale", "stale_cache", "rate_limited_cache", "expired"}:
        return "stale"
    if ok is True or status in {"fresh", "fresh_cache", "ok", "available"}:
        return "fresh"
    return "unknown"


def source_list_label(sources, limit=3):
    names = sorted(str(source) for source in sources if source not in (None, ""))
    if len(names) <= limit:
        return ",".join(names)
    head = ",".join(names[:limit])
    return f"{head},+{len(names) - limit}"


def source_freshness_state_from_rows(rows):
    if not rows:
        return "missing_sources"
    by_state = {}
    for row in rows:
        source = row.get("source") or "unknown"
        state = source_status_kind(row)
        if state == "fresh":
            continue
        by_state.setdefault(state, []).append(source)
    parts = []
    for state in ("failed", "expected_unavailable", "stale", "unknown"):
        if by_state.get(state):
            parts.append(f"{state}:{source_list_label(by_state[state])}")
    return ";".join(parts) if parts else "all_fresh"


def load_latest_snapshot_rows(folder):
    path = Path(folder) / "snapshots_long.csv"
    rows = io_read_csv_rows(path, attach_diagnostics=True)
    if not rows:
        return []
    latest = max(rows, key=lambda row: parse_time(row.get("captured_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))
    latest_snapshot_id = latest.get("snapshot_id")
    return [row for row in rows if row.get("snapshot_id") == latest_snapshot_id]


def load_clob_feature_index(folder):
    path = Path(folder) / "clob_features_long.csv"
    by_token = {}
    by_band = {}
    for row in io_read_csv_rows(path, attach_diagnostics=True):
        by_token[_band_key(row)] = row
        by_band[_band_key_without_token(row)] = row
    return by_token, by_band


def load_source_status_rows(folder, snapshot_id):
    path = Path(folder) / "source_status_long.csv"
    if not snapshot_id:
        return []
    rows = []
    for row in io_read_csv_rows(path, attach_diagnostics=True):
        if row.get("snapshot_id") == snapshot_id:
            rows.append(row)
    return rows


def latest_folders_by_market(root=DEFAULT_SNAPSHOTS_ROOT, markets=None):
    root = Path(root)
    wanted = set(markets or REGISTRY.keys())
    latest = {}
    if not root.exists():
        return latest
    for child in root.iterdir():
        if not child.is_dir() or not (child / "snapshots_long.csv").exists():
            continue
        spec = spec_for_slug(child.name)
        if not spec or spec.id not in wanted:
            continue
        current = latest.get(spec.id)
        if current is None or child.stat().st_mtime > current.stat().st_mtime:
            latest[spec.id] = child
    return latest


def assemble_policy_inputs(
    promotion_states,
    observation_status,
    known_edge_records=None,
    known_edge_map_loaded=False,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    markets=None,
    now=None,
):
    now = utc_now(now)
    rows = []
    for market_id, folder in sorted(latest_folders_by_market(snapshots_root, markets=markets).items()):
        snapshot_rows = load_latest_snapshot_rows(folder)
        high_assessment = current_high_probability_summary(
            snapshot_rows,
            normalized_high_for_market(observation_status, market_id),
        )
        snapshot_id = snapshot_rows[0].get("snapshot_id") if snapshot_rows else None
        source_freshness_state = source_freshness_state_from_rows(
            load_source_status_rows(folder, snapshot_id)
        )
        clob_by_token, clob_by_band = load_clob_feature_index(folder)
        promotion = promotion_states.get(market_id, {"promotion_state": "BLOCK"})
        for snapshot_row in snapshot_rows:
            clob_row = clob_by_token.get(_band_key(snapshot_row)) or clob_by_band.get(_band_key_without_token(snapshot_row)) or {}
            merged = dict(snapshot_row)
            merged.update({key: value for key, value in clob_row.items() if value not in (None, "")})
            merged["market_id"] = market_id
            merged["promotion_state"] = promotion.get("promotion_state", "BLOCK")
            merged["fair_probability"] = merged.get("model_probability")
            merged["market_mid"] = merged.get("clob_midpoint") or merged.get("market_yes")
            merged["book_spread"] = merged.get("clob_spread") or (
                (maybe_float(merged.get("best_ask")) or 0.0) - (maybe_float(merged.get("best_bid")) or 0.0)
                if maybe_float(merged.get("best_ask")) is not None and maybe_float(merged.get("best_bid")) is not None
                else ""
            )
            merged["book_age_seconds"] = merged.get("clob_book_age_seconds")
            merged["watcher_age_seconds"] = observation_status.get("watcher_age_seconds")
            merged["heartbeat_ok"] = observation_status.get("heartbeat_ok", False)
            merged["source_fresh"] = observation_status.get("fresh", False)
            merged["source_freshness_state"] = source_freshness_state
            merged.update(normalized_high_fields(high_assessment))
            record = resolve_known_edge_record(merged, known_edge_records or [])
            merged = apply_known_edge_permission(
                merged,
                record=record,
                map_loaded=known_edge_map_loaded,
            )
            rows.append(merged)
    return rows


def write_quote_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUOTE_COLUMNS, extrasaction="ignore", restval="")
        writer.writeheader()
        for row in rows:
            writer.writerow(normalize_csv_row(row))
    return str(path)


def run_policy_snapshot(
    promotion_refresh=DEFAULT_PROMOTION_REFRESH,
    known_edge_map=DEFAULT_KNOWN_EDGE_MAP,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    observation_status_path=DEFAULT_OBSERVATION_STATUS,
    out=DEFAULT_OUT,
    json_out=DEFAULT_JSON_OUT,
    markets=None,
    config=None,
    now=None,
):
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    config, clob_recon_diag = config_with_clob_recon(config)
    now = utc_now(now)
    promotion_states, promotion_diag = load_promotion_states(promotion_refresh)
    known_edge_records, known_edge_diag = load_known_edge_map(known_edge_map)
    observation = load_observation_status(observation_status_path, now=now, config=config)
    inputs = assemble_policy_inputs(
        promotion_states,
        observation,
        known_edge_records=known_edge_records,
        known_edge_map_loaded=known_edge_diag.get("exists", False),
        snapshots_root=snapshots_root,
        markets=markets,
        now=now,
    )
    quote_rows = [decide_quote(row, config=config, now=now) for row in inputs]
    csv_path = write_quote_csv(out, quote_rows)
    reason_counts = Counter(row.get("reason_code") for row in quote_rows)
    regime_counts = Counter(row.get("regime") for row in quote_rows)
    event_gate = summarize_event_gate_rows(quote_rows)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": policy_hash(config),
        "shadow_mode": True,
        "promotion": promotion_diag,
        "known_edge_map": known_edge_diag,
        "clob_recon": clob_recon_diag,
        "observation_status": observation,
        "snapshots_root": str(snapshots_root),
        "csv_out": csv_path,
        "row_count": len(quote_rows),
        "quote_permission_rows": sum(1 for row in quote_rows if row.get("quote_permission")),
        "live_trade_permission_rows": sum(1 for row in quote_rows if row.get("live_trade_permission")),
        "reason_counts": dict(sorted(reason_counts.items())),
        "regime_counts": dict(sorted(regime_counts.items())),
        "information_event_gate": event_gate,
        "rows": quote_rows,
    }
    json_out = Path(json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    payload["json_out"] = str(json_out)
    return payload


def parse_config_overrides(items):
    config = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --config override {item!r}; expected key=value")
        key, value = item.split("=", 1)
        if key not in DEFAULT_POLICY_CONFIG:
            raise SystemExit(f"Unknown policy config key {key!r}")
        default = DEFAULT_POLICY_CONFIG[key]
        if isinstance(default, bool):
            config[key] = bool_value(value)
        elif isinstance(default, (int, float)):
            config[key] = float(value)
        else:
            config[key] = value
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write keyless shadow market-making quote intents.")
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--known-edge-map", default=str(DEFAULT_KNOWN_EDGE_MAP))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--observation-status", default=str(DEFAULT_OBSERVATION_STATUS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--markets", default="all", help="'all' or comma-separated market ids.")
    parser.add_argument("--now", default=None, help="Override policy timestamp for replay/testing.")
    parser.add_argument("--config", action="append", default=[], help="Policy config override, key=value.")
    args = parser.parse_args(argv)

    markets = None
    if args.markets != "all":
        markets = [item.strip() for item in args.markets.split(",") if item.strip()]
    payload = run_policy_snapshot(
        promotion_refresh=args.promotion_refresh,
        known_edge_map=args.known_edge_map,
        snapshots_root=args.snapshots_root,
        observation_status_path=args.observation_status,
        out=args.out,
        json_out=args.json_out,
        markets=markets,
        config=parse_config_overrides(args.config),
        now=args.now,
    )
    print(
        "MM policy shadow: "
        f"{payload['quote_permission_rows']} quote rows, "
        f"{payload['row_count'] - payload['quote_permission_rows']} no-quote rows -> "
        f"{payload['csv_out']}"
    )
    return payload


if __name__ == "__main__":
    main()
