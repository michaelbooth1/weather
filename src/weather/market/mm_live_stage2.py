"""Bounded, library-only Stage 2 International maker session.

This module deliberately exposes no CLI and resolves no credentials.  An
eligible-host wrapper must supply an already-authenticated official adapter, a
fresh passing v0.4 platform gate, and one current quote decision whose complete
preflight passed together with matching paper and public-capture evidence. The
executor permits one backed post-only BUY submission and always converges to
zero open orders before returning.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from weather.market.mm_official_adapter import (
    CONDITION_ID_RE,
    EVM_ADDRESS_RE,
    OFFICIAL_CLOB_DISTRIBUTION,
    OFFICIAL_CLOB_VERSION,
    exact_current_positions_evidence,
)
from weather.market.mm_policy import bool_value


ENVELOPE_SCHEMA_VERSION = "mm_live_stage2_session_envelope_v0.2"
JOURNAL_SCHEMA_VERSION = "mm_live_stage2_session_journal_v0.1"
RESULT_SCHEMA_VERSION = "mm_live_stage2_session_result_v0.1"
PAPER_COUNTERFACTUAL_SCHEMA_VERSION = (
    "mm_live_stage2_paper_counterfactual_v0.2"
)
CONFIRMATION = "INTERNATIONAL_POLYMARKET_STAGE2_ONE_BAND_MAKER"
MAX_OPERATOR_BUDGET_PUSD = Decimal("100")
MAX_DAILY_LOSS_PUSD = Decimal("25")
MAX_EVENT_NOTIONAL_PUSD = Decimal("25")
MAX_BAND_NOTIONAL_PUSD = Decimal("10")
MAX_ORDER_NOTIONAL_PUSD = Decimal("10")
MAX_QUOTE_TTL_SECONDS = Decimal("120")
MAX_HEARTBEAT_INTERVAL_SECONDS = Decimal("5")
MAX_PUBLIC_CAPTURE_AGE_SECONDS = Decimal("10")
MAX_PUBLIC_CAPTURE_PROBE_AGE_SECONDS = Decimal("86400")
ATOMIC_COLLATERAL_SCALE = Decimal("1000000")
MODEL_STAGE2_PREFLIGHT_GATES = frozenset({
    "active_event",
    "snapshot_model_rows",
    "model_freshness",
    "source_status_rows",
    "source_status_fresh",
    "source_status_degradation",
    "clob_discovery",
    "clob_tokens",
    "clob_books",
    "clob_features",
    "clob_freshness",
    "observation_trigger",
    "promotion_state",
    "reward_metadata",
    "data_layer_live_gate",
    "platform_verification_gate",
    "exchange_economics_gate",
})
MARKET_HARVEST_STAGE2_PREFLIGHT_GATES = frozenset(
    MODEL_STAGE2_PREFLIGHT_GATES
    - {"snapshot_model_rows", "model_freshness", "promotion_state"}
    | {"market_harvest_paper_only"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(now=None) -> str:
    value = now or _utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _canonical_hash(payload) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decimal(value, label, *, allow_zero=False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} must be numeric") from exc
    lower_ok = number >= 0 if allow_zero else number > 0
    if not number.is_finite() or not lower_ok:
        qualifier = "nonnegative" if allow_zero else "greater than zero"
        raise RuntimeError(f"{label} must be finite and {qualifier}")
    return number


def _parse_utc(value, label) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _value(payload, *names):
    for name in names:
        value = payload.get(name) if isinstance(payload, dict) else getattr(payload, name, None)
        if value is not None and value != "":
            return value
    return None


def _source_permission_profile(row):
    explicit = str((row or {}).get("permission_profile") or "").strip().lower()
    known_edge = str((row or {}).get("known_edge_permission") or "").strip().lower()
    if explicit:
        if explicit not in {"model", "market_harvest"}:
            raise RuntimeError("Stage 2 quote has an unsupported permission profile")
        if explicit == "market_harvest" and known_edge != "market_harvest":
            raise RuntimeError("Stage 2 market_harvest quote lacks its exact profile marker")
        return explicit
    return "market_harvest" if known_edge == "market_harvest" else "model"


def _order_id(payload):
    value = _value(payload, "orderID", "order_id", "id")
    return str(value) if value else None


def _contains_order(rows, order_id):
    return any(_order_id(row) == order_id for row in rows or [])


def _scoped_events(rows, order_id):
    return [dict(row) for row in rows or [] if _order_id(row) == order_id]


def _event_summary(rows):
    confirmed_by_trade = {}
    pending_trade_ids = set()
    failed_trade_ids = set()
    cancellation_observed = False
    order_observed = False
    taker_observed = False
    invalid_event_evidence = False
    for row in rows:
        event_type = str(row.get("event_type") or "").strip().lower()
        official_type = str(row.get("official_event_type") or "").strip().lower()
        trade_id = str(row.get("trade_id") or "").strip()
        if not _is_sha256(row.get("raw_event_sha256")):
            invalid_event_evidence = True
        if official_type == "order":
            if event_type not in {"order", "canceled"}:
                invalid_event_evidence = True
            order_observed = True
            cancellation_observed = cancellation_observed or event_type == "canceled"
        elif official_type == "trade":
            if not trade_id or event_type not in {
                "trade_pending",
                "rejected",
                "trade",
            }:
                invalid_event_evidence = True
        else:
            invalid_event_evidence = True
            continue
        if official_type != "trade":
            continue
        taker_observed = taker_observed or str(
            row.get("liquidity_role") or ""
        ).upper() == "TAKER"
        if event_type == "trade_pending":
            pending_trade_ids.add(trade_id)
        elif event_type == "rejected":
            failed_trade_ids.add(trade_id)
        elif event_type == "trade":
            if (
                trade_id in confirmed_by_trade
                and _canonical_hash(confirmed_by_trade[trade_id])
                != _canonical_hash(row)
            ):
                invalid_event_evidence = True
            confirmed_by_trade[trade_id] = row
    resolved = set(confirmed_by_trade) | failed_trade_ids
    return {
        "order_observed": order_observed,
        "cancellation_observed": cancellation_observed,
        "taker_observed": taker_observed,
        "invalid_event_evidence": invalid_event_evidence,
        "confirmed": list(confirmed_by_trade.values()),
        "failed_trade_ids": sorted(value for value in failed_trade_ids if value),
        "unresolved_trade_ids": sorted(
            value for value in pending_trade_ids - resolved if value
        ),
    }


class Stage2Journal:
    """Append-only, flush-on-event Stage 2 evidence without secret material."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError(f"Stage 2 journal already exists: {self.path}")
        self.record("journal_opened")

    def record(self, event_type, **fields):
        row = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "recorded_at_utc": _utc_iso(),
            "event_type": str(event_type),
            **fields,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def sha256(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


def _verified_exact_positions(adapter):
    positions = adapter.positions()
    evidence = adapter.position_evidence(positions)
    if not exact_current_positions_evidence(
        evidence,
        maker_address=getattr(adapter, "maker_address", ""),
        condition_id=getattr(adapter, "condition_id", ""),
        rows=positions,
    ):
        raise RuntimeError("Stage 2 position read lacks exact-scope response evidence")
    return positions, evidence


def _positive_positions(rows):
    positive = []
    for row in rows or []:
        size = _decimal(row.get("size"), "position size", allow_zero=True)
        if size > 0:
            positive.append((str(row.get("asset") or ""), size, dict(row)))
    return positive


def _atomic_collateral_to_pusd(value, label):
    try:
        atomic = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} must be an integer atomic collateral amount") from exc
    if not atomic.is_finite() or atomic < 0 or atomic != atomic.to_integral_value():
        raise RuntimeError(f"{label} must be an integer atomic collateral amount")
    return atomic / ATOMIC_COLLATERAL_SCALE


def _verified_collateral(adapter):
    evidence = adapter.refresh_collateral_evidence()
    if not isinstance(evidence, dict):
        raise RuntimeError("Stage 2 collateral read lacks content-bound evidence")
    allowances = evidence.get("allowances_atomic")
    if not isinstance(allowances, dict) or not allowances:
        raise RuntimeError("Stage 2 collateral evidence has no allowance map")
    if not all((
        evidence.get("status") == "OBSERVED",
        evidence.get("query_scope")
        == "authenticated_collateral_balance_allowance",
        _is_sha256(evidence.get("response_sha256")),
    )):
        raise RuntimeError("Stage 2 collateral read lacks content-bound evidence")
    balance = _atomic_collateral_to_pusd(
        evidence.get("balance_atomic"),
        "collateral balance",
    )
    allowance_values = [
        _atomic_collateral_to_pusd(value, "collateral allowance")
        for value in allowances.values()
    ]
    return {
        "balance_pusd": balance,
        "minimum_allowance_pusd": min(allowance_values),
        "response_sha256": str(evidence.get("response_sha256")).lower(),
    }


def _gate_binding(adapter, platform_gate, session_budget):
    gate = dict(platform_gate or {})
    checks = gate.get("checks")
    sdk = gate.get("sdk_contract") or {}
    heartbeat = gate.get("dead_man_heartbeat") or {}
    requested = _decimal(gate.get("requested_budget_usdc"), "verified requested budget")
    wallet_cap = _decimal(gate.get("pilot_wallet_max_funding_usdc"), "verified wallet cap")
    budget = _decimal(session_budget, "Stage 2 session budget")
    heartbeat_count = _decimal(
        heartbeat.get("acknowledgment_count"),
        "verified heartbeat acknowledgment count",
    )
    heartbeat_cadence = _decimal(
        heartbeat.get("cadence_seconds"),
        "verified heartbeat cadence",
    )
    binding = {
        "required": gate.get("required") is True,
        "ok": gate.get("ok") is True,
        "schema": gate.get("schema_version") == "mm_platform_verification_v0.4",
        "platform": gate.get("platform") == "polymarket_global",
        "settlement_unit": gate.get("settlement_unit") == "pUSD",
        "checks": isinstance(checks, dict) and bool(checks)
        and all(value is True for value in checks.values()),
        "missing": gate.get("missing") == [],
        "artifact_hash": len(str(gate.get("artifact_sha256") or "")) == 64,
        "condition": str(gate.get("condition_id") or "").lower()
        == str(getattr(adapter, "condition_id", "") or "").lower(),
        "token": str(gate.get("token_id") or "")
        == str(getattr(adapter, "token_id", "") or ""),
        "maker": str(gate.get("funder_address") or "").lower()
        == str(getattr(adapter, "maker_address", "") or "").lower(),
        "condition_format": CONDITION_ID_RE.fullmatch(
            str(gate.get("condition_id") or "").lower()
        ) is not None,
        "maker_format": EVM_ADDRESS_RE.fullmatch(
            str(gate.get("funder_address") or "")
        ) is not None,
        "stage1_bundle": len(
            str(gate.get("stage1_lifecycle_bundle_sha256") or "")
        ) == 64,
        "sdk": (
            sdk.get("distribution") == OFFICIAL_CLOB_DISTRIBUTION
            and sdk.get("version") == OFFICIAL_CLOB_VERSION
            and sdk.get("exact_version_verified") is True
        ),
        "heartbeat_contract": all((
            heartbeat.get("endpoint") == "/heartbeats",
            heartbeat.get("endpoint_verified") is True,
            heartbeat.get("request_body_absent_verified") is True,
            heartbeat.get("two_acknowledgments_verified") is True,
            heartbeat_count >= Decimal("2"),
            heartbeat.get("acknowledgment_verified") is True,
            Decimal("0") < heartbeat_cadence <= MAX_HEARTBEAT_INTERVAL_SECONDS,
            heartbeat.get("stale_placement_disarm_verified") is True,
            heartbeat.get("automatic_cancel_verified") is True,
        )),
        "budget": budget <= requested <= wallet_cap <= MAX_OPERATOR_BUDGET_PUSD,
    }
    missing = [name for name, valid in binding.items() if not valid]
    if missing:
        raise RuntimeError("Stage 2 platform binding failed: " + ", ".join(missing))
    return gate, budget


def _is_sha256(value):
    text = str(value or "").lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _is_policy_hash(value):
    text = str(value or "").lower()
    return len(text) in {16, 64} and all(
        character in "0123456789abcdef" for character in text
    )


def _is_git_sha(value):
    text = str(value or "").lower()
    return len(text) == 40 and all(character in "0123456789abcdef" for character in text)


def _json_object_bytes(value, label):
    if not isinstance(value, (bytes, bytearray)):
        raise RuntimeError(f"{label} must be retained JSON artifact bytes")
    raw = bytes(value)
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must contain a JSON mapping")
    return raw, payload


def _paper_counterfactual_binding(
    source_row,
    evidence,
    *,
    current,
    source_profile,
):
    raw_artifact, payload = _json_object_bytes(
        evidence,
        "Stage 2 paper counterfactual artifact",
    )
    paper_row = dict(payload.get("quote_row") or {})
    source_generated = _parse_utc(
        source_row.get("generated_at_utc"),
        "source quote generated_at_utc",
    )
    paper_generated = _parse_utc(
        paper_row.get("generated_at_utc"),
        "paper quote generated_at_utc",
    )
    recorded = _parse_utc(
        payload.get("artifact_recorded_at_utc"),
        "paper artifact_recorded_at_utc",
    )
    paper_ttl = _decimal(paper_row.get("quote_ttl_seconds"), "paper quote TTL")
    paper_expires = paper_generated + timedelta(seconds=float(paper_ttl))
    textual_fields = [
        "target_date",
        "market_id",
        "event_slug",
        "condition_id",
        "clob_token_id",
        "range_label",
        "snapshot_id",
        "policy_version",
        "policy_hash",
    ]
    numeric_fields = [
        "bid_price",
        "bid_size",
        "ask_price",
        "ask_size",
        "quote_ttl_seconds",
    ]
    if source_profile == "model":
        textual_fields.extend((
            "model_version",
            "served_model_version",
            "model_variant_id",
            "model_variant_artifact_hash",
        ))
        numeric_fields.append("fair_probability")
    exact_text = all(
        str(paper_row.get(field) or "") == str(source_row.get(field) or "")
        for field in textual_fields
    )
    try:
        exact_numbers = all(
            _decimal(
                paper_row.get(field),
                f"paper {field}",
                allow_zero=field == "ask_size",
            )
            == _decimal(
                source_row.get(field),
                f"source {field}",
                allow_zero=field == "ask_size",
            )
            for field in numeric_fields
        )
    except RuntimeError:
        exact_numbers = False

    common_identity = all((
        bool(str(source_row.get("event_slug") or "")),
        bool(str(source_row.get("snapshot_id") or "")),
        _is_policy_hash(source_row.get("policy_hash")),
    ))
    if source_profile == "model":
        fair = _decimal(
            source_row.get("fair_probability"),
            "model source fair probability",
        )
        profile_checks = {
            "source_model_mode": source_row.get("run_mode") == "live-pilot",
            "source_model_quote_permission": bool_value(
                source_row.get("quote_permission"),
                False,
            ),
            "source_model_live_permission": bool_value(
                source_row.get("live_trade_permission"),
                False,
            ),
            "source_model_not_shadow": not bool_value(
                source_row.get("shadow_mode"),
                False,
            ),
            "source_model_identity": all((
                common_identity,
                bool(str(source_row.get("served_model_version") or "")),
                fair < 1,
            )),
        }
    else:
        try:
            source_zero_reward = all(
                _decimal(
                    source_row.get(field),
                    f"market_harvest {field}",
                    allow_zero=True,
                ) == 0
                for field in ("expected_reward_score", "expected_rebate_value")
            )
            paper_zero_reward = all(
                _decimal(
                    paper_row.get(field),
                    f"paper market_harvest {field}",
                    allow_zero=True,
                ) == 0
                for field in ("expected_reward_score", "expected_rebate_value")
            )
        except RuntimeError:
            source_zero_reward = paper_zero_reward = False
        profile_checks = {
            "source_harvest_mode": (
                source_row.get("run_mode") == "paper-live-forward"
            ),
            "source_harvest_marker": (
                str(source_row.get("known_edge_permission") or "").lower()
                == "market_harvest"
                and str(
                    source_row.get("model_variant_probability_source") or ""
                ).lower() == "market_mid_no_model"
            ),
            "source_harvest_quote_permission": bool_value(
                source_row.get("quote_permission"),
                False,
            ),
            "source_harvest_live_permission_disabled": not bool_value(
                source_row.get("live_trade_permission"),
                False,
            ),
            "source_harvest_shadow": bool_value(
                source_row.get("shadow_mode"),
                False,
            ),
            "source_harvest_two_sided": (
                str(source_row.get("side") or "").upper() == "TWO_SIDED"
            ),
            "source_harvest_zero_reward_assumption": source_zero_reward,
            "source_harvest_identity": common_identity,
            "paper_harvest_marker": (
                str(paper_row.get("known_edge_permission") or "").lower()
                == "market_harvest"
                and str(
                    paper_row.get("model_variant_probability_source") or ""
                ).lower() == "market_mid_no_model"
            ),
            "paper_harvest_two_sided": (
                str(paper_row.get("side") or "").upper() == "TWO_SIDED"
            ),
            "paper_harvest_zero_reward_assumption": paper_zero_reward,
            "exact_harvest_source_row": (
                _canonical_hash(paper_row) == _canonical_hash(source_row)
            ),
        }

    checks = {
        "artifact_schema": (
            payload.get("schema_version")
            == PAPER_COUNTERFACTUAL_SCHEMA_VERSION
        ),
        "paper_mode": paper_row.get("run_mode") == "paper-live-forward",
        "paper_quote_permission": bool_value(
            paper_row.get("quote_permission"),
            False,
        ),
        "paper_live_mutation_disabled": not bool_value(
            paper_row.get("live_trade_permission"),
            False,
        ),
        "paper_shadow": bool_value(paper_row.get("shadow_mode"), False),
        "paper_action": paper_row.get("action") == "QUOTE",
        "paper_budget_reserved": paper_row.get("budget_action") == "reserved",
        "exact_treatment_text": exact_text,
        "exact_treatment_numbers": exact_numbers,
        "recorded_after_generation": recorded >= paper_generated,
        "recorded_before_freeze": recorded <= current,
        "source_generated_before_freeze": source_generated <= current,
        "paper_generated_before_freeze": paper_generated <= current,
        "paper_current": current <= paper_expires,
        "paper_ttl": paper_ttl <= MAX_QUOTE_TTL_SECONDS,
        **profile_checks,
    }
    missing = [name for name, valid in checks.items() if not valid]
    if missing:
        raise RuntimeError(
            "Stage 2 paper counterfactual binding failed: " + ", ".join(missing)
        )
    return {
        "artifact_sha256": hashlib.sha256(raw_artifact).hexdigest(),
        "quote_row_sha256": _canonical_hash(paper_row),
        "source_quote_row_sha256": _canonical_hash(source_row),
        "source_permission_profile": source_profile,
        "generated_at_utc": paper_generated.isoformat(),
        "recorded_at_utc": recorded.isoformat(),
        "expires_at_utc": paper_expires.isoformat(),
    }


def _public_capture_binding(live_row, evidence, *, current):
    payload = dict(evidence or {})
    receipt_raw, receipt = _json_object_bytes(
        payload.get("probe_receipt_bytes"),
        "Stage 2 execution capture probe receipt",
    )
    status_raw, status = _json_object_bytes(
        payload.get("live_status_bytes"),
        "Stage 2 global execution capture status",
    )
    market_day_status_raw, market_day_status = _json_object_bytes(
        payload.get("market_day_status_bytes"),
        "Stage 2 market-day execution capture status",
    )
    baseline = receipt.get("baseline_integrity_counters")
    final = receipt.get("final_integrity_counters")
    active_rows = status.get("active_market_days")
    observed = _parse_utc(status.get("updated_at_utc"), "execution capture update")
    market_day_observed = _parse_utc(
        market_day_status.get("updated_at_utc"),
        "market-day execution capture update",
    )
    finished = _parse_utc(receipt.get("finished_at"), "execution capture probe finish")
    heartbeat_before = _parse_utc(
        receipt.get("snapshot_heartbeat_before"),
        "execution capture probe starting heartbeat",
    )
    heartbeat_after = _parse_utc(
        receipt.get("snapshot_heartbeat_after"),
        "execution capture probe ending heartbeat",
    )
    probe_age = Decimal(str((current - finished).total_seconds()))
    status_age = Decimal(str((current - observed).total_seconds()))
    market_day_status_age = Decimal(
        str((current - market_day_observed).total_seconds())
    )
    integrity_names = ("parse_rejections", "unrouted_trades", "ambiguous_routes")
    clean_integrity = isinstance(baseline, dict) and isinstance(final, dict)
    if clean_integrity:
        try:
            clean_integrity = all(
                int(final.get(name)) == int(baseline.get(name))
                for name in integrity_names
            )
        except (TypeError, ValueError):
            clean_integrity = False
    matching_rows = [
        row
        for row in active_rows or []
        if isinstance(row, dict)
        and str(row.get("market_id") or "") == str(live_row.get("market_id") or "")
        and str(row.get("target_date") or "") == str(live_row.get("target_date") or "")
        and str(row.get("event_slug") or "") == str(live_row.get("event_slug") or "")
        and str(row.get("connection_state") or "") == "CONNECTED"
        and str(row.get("evidence_interpretation") or "")
        in {"TRADES_CONTINUOUSLY_CONNECTED", "NO_TRADES_CONNECTED_QUIET"}
    ]
    checks = {
        "probe_schema": receipt.get("schema_version")
        == "execution_tape_bounded_probe_v0.2",
        "probe_pass": receipt.get("ok") is True and receipt.get("stage") == "proved",
        "probe_commit": _is_git_sha(receipt.get("repo_head"))
        and _is_git_sha(receipt.get("required_ancestor")),
        "probe_connected_seed_set": receipt.get("connected_seed_set_proved") is True,
        "probe_observation": int(receipt.get("new_trade_observations") or 0) >= 1,
        "probe_integrity": clean_integrity,
        "probe_capture_survival": int(receipt.get("capture_workers_before") or 0) == 3
        and int(receipt.get("capture_workers_after") or 0) == 3
        and heartbeat_after > heartbeat_before,
        "probe_current": Decimal("0") <= probe_age <= MAX_PUBLIC_CAPTURE_PROBE_AGE_SECONDS,
        "status_schema": status.get("schema_version") == "execution_tape_status_v0.1",
        "status_connected": status.get("state") == "CONNECTED"
        and not status.get("last_seed_error"),
        "status_session": bool(str(status.get("coordinator_session_id") or "")),
        "status_count": isinstance(active_rows, list)
        and len(active_rows) == int(status.get("active_market_day_count") or 0)
        and bool(active_rows),
        "status_scope": len(matching_rows) == 1,
        "status_current": Decimal("0") <= status_age <= MAX_PUBLIC_CAPTURE_AGE_SECONDS,
        "market_day_status_schema": market_day_status.get("schema_version")
        == "execution_tape_status_v0.1",
        "market_day_status_scope": all((
            str(market_day_status.get("market_id") or "")
            == str(live_row.get("market_id") or ""),
            str(market_day_status.get("target_date") or "")
            == str(live_row.get("target_date") or ""),
            str(market_day_status.get("event_slug") or "")
            == str(live_row.get("event_slug") or ""),
            str(market_day_status.get("connection_state") or "") == "CONNECTED",
            str(market_day_status.get("evidence_interpretation") or "")
            in {"TRADES_CONTINUOUSLY_CONNECTED", "NO_TRADES_CONNECTED_QUIET"},
            bool(str(market_day_status.get("session_id") or "")),
            _is_sha256(market_day_status.get("seed_sha256")),
        )),
        "market_day_status_current": Decimal("0")
        <= market_day_status_age
        <= MAX_PUBLIC_CAPTURE_AGE_SECONDS,
    }
    missing = [name for name, valid in checks.items() if not valid]
    if missing:
        raise RuntimeError(
            "Stage 2 public execution capture binding failed: " + ", ".join(missing)
        )
    return {
        "probe_receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "probe_repo_head": str(receipt.get("repo_head")).lower(),
        "live_status_sha256": hashlib.sha256(status_raw).hexdigest(),
        "market_day_status_sha256": hashlib.sha256(
            market_day_status_raw
        ).hexdigest(),
        "coordinator_session_id": str(status.get("coordinator_session_id")),
        "capture_session_id": str(market_day_status.get("session_id")),
        "seed_sha256": str(market_day_status.get("seed_sha256")).lower(),
        "observed_at_utc": min(observed, market_day_observed).isoformat(),
        "expires_at_utc": (
            min(observed, market_day_observed)
            + timedelta(seconds=float(MAX_PUBLIC_CAPTURE_AGE_SECONDS))
        ).isoformat(),
    }


def build_stage2_session_envelope(
    adapter,
    platform_gate,
    quote_decision,
    market_preflight,
    paper_counterfactual,
    public_capture_evidence,
    *,
    session_budget_pusd,
    now=None,
):
    """Validate one profile-bound quote and freeze the non-raisable envelope."""

    gate, budget = _gate_binding(adapter, platform_gate, session_budget_pusd)
    row = dict(quote_decision or {})
    source_profile = _source_permission_profile(row)
    preflight = dict(market_preflight or {})
    preflight_gates = preflight.get("gates")
    preflight_gate_names = {
        str(gate_row.get("name") or "")
        for gate_row in preflight_gates or []
        if isinstance(gate_row, dict) and gate_row.get("ok") is True
    }
    live_gate = preflight.get("live_gate") or {}
    generated = _parse_utc(row.get("generated_at_utc"), "quote generated_at_utc")
    current = now or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    paper_binding = _paper_counterfactual_binding(
        row,
        paper_counterfactual,
        current=current,
        source_profile=source_profile,
    )
    capture_binding = _public_capture_binding(
        row,
        public_capture_evidence,
        current=current,
    )
    ttl = _decimal(row.get("quote_ttl_seconds"), "quote TTL")
    price = _decimal(row.get("bid_price"), "Stage 2 BUY price")
    quoted_size = _decimal(row.get("bid_size"), "Stage 2 quoted BUY size")
    event_before = _decimal(
        row.get("event_notional"),
        "event notional",
        allow_zero=True,
    )
    band_before = _decimal(
        row.get("band_notional"),
        "band notional",
        allow_zero=True,
    )
    daily_loss_value = row.get("daily_loss_pusd")
    if daily_loss_value in (None, ""):
        daily_loss_value = row.get("daily_loss")
    if daily_loss_value in (None, ""):
        try:
            verified_open_order_count = _decimal(
                gate.get("open_order_count"),
                "verified open-order count",
                allow_zero=True,
            )
        except RuntimeError:
            verified_open_order_count = None
        stage1_no_fill = all((
            source_profile == "market_harvest",
            (gate.get("checks") or {}).get(
                "stage1_derived_evidence_matches_platform_fields"
            ) is True,
            verified_open_order_count == 0,
        ))
        if not stage1_no_fill:
            raise RuntimeError(
                "Stage 2 requires explicit daily loss or verified Stage 1 "
                "no-fill zero-state evidence"
            )
        daily_loss_before = Decimal("0")
        daily_loss_basis = "verified_stage1_no_fill_isolated_wallet"
    else:
        daily_loss_before = _decimal(
            daily_loss_value,
            "daily loss",
            allow_zero=True,
        )
        daily_loss_basis = "source_quote"
    quote_risk = _decimal(row.get("quote_risk_usdc"), "quote risk")
    run_budget = _decimal(row.get("run_budget_usdc"), "quote run budget")
    adapter_order_cap = _decimal(
        getattr(adapter, "max_order_notional", MAX_ORDER_NOTIONAL_PUSD),
        "adapter order cap",
    )
    order_cap = min(MAX_ORDER_NOTIONAL_PUSD, adapter_order_cap, budget)
    required_gates = (
        MODEL_STAGE2_PREFLIGHT_GATES
        if source_profile == "model"
        else MARKET_HARVEST_STAGE2_PREFLIGHT_GATES
    )
    if source_profile == "model":
        profile_checks = {
            "preflight_profile": (
                preflight.get("permission_profile") in {None, "", "model"}
            ),
            "run_mode": row.get("run_mode") == "live-pilot",
            "live_trade_permission": bool_value(
                row.get("live_trade_permission"),
                False,
            ),
            "source_not_shadow": not bool_value(
                row.get("shadow_mode"),
                False,
            ),
            "live_gate": all((
                live_gate.get("required") is True,
                live_gate.get("pilot_flag") is True,
                live_gate.get("confirm_live_orders") is True,
                live_gate.get("live_ready") is True,
                live_gate.get("platform_verified") is True,
                live_gate.get("release_production_capable") is True,
                live_gate.get("ok") is True,
            )),
        }
    else:
        profile_checks = {
            "preflight_profile": (
                preflight.get("permission_profile") == "market_harvest"
            ),
            "run_mode": row.get("run_mode") == "paper-live-forward",
            "live_trade_permission_disabled": not bool_value(
                row.get("live_trade_permission"),
                False,
            ),
            "source_shadow": bool_value(row.get("shadow_mode"), False),
            "source_market_mid_no_model": (
                str(
                    row.get("model_variant_probability_source") or ""
                ).lower() == "market_mid_no_model"
            ),
            "source_two_sided": (
                str(row.get("side") or "").upper() == "TWO_SIDED"
            ),
            "paper_live_gate": (
                live_gate.get("required") is False
                and live_gate.get("ok") is True
            ),
        }
    checks = {
        "preflight_status": preflight.get("status") == "PASS",
        "preflight_gates": (
            isinstance(preflight_gates, list)
            and bool(preflight_gates)
            and all(
                isinstance(gate_row, dict) and gate_row.get("ok") is True
                for gate_row in preflight_gates
            )
        ),
        "required_preflight_gates": required_gates.issubset(
            preflight_gate_names
        ),
        "market": (
            str(preflight.get("market_id") or "")
            == str(row.get("market_id") or "")
            and bool(str(row.get("market_id") or ""))
        ),
        "target": (
            str(preflight.get("target_date") or "")
            == str(row.get("target_date") or "")
            == str(gate.get("target_date") or "")
        ),
        "quote_permission": bool_value(row.get("quote_permission"), False),
        "action": row.get("action") == "QUOTE",
        "budget_reserved": row.get("budget_action") == "reserved",
        "condition": (
            str(row.get("condition_id") or "").lower()
            == str(gate.get("condition_id") or "").lower()
        ),
        "token": (
            str(row.get("clob_token_id") or "")
            == str(gate.get("token_id") or "")
        ),
        "source_fresh": bool_value(row.get("source_fresh"), False),
        "heartbeat": bool_value(row.get("heartbeat_ok"), False),
        "current_high": bool_value(row.get("current_high_trusted"), False),
        "latency": row.get("latency_budget_status") == "ok",
        "fresh": (
            generated <= current
            and Decimal(str((current - generated).total_seconds())) <= ttl
        ),
        "ttl": ttl <= MAX_QUOTE_TTL_SECONDS,
        "price": price < 1,
        "quoted_size": quoted_size > 0,
        "quote_risk": price * quoted_size <= quote_risk <= order_cap,
        "run_budget": (
            run_budget == budget and budget <= MAX_OPERATOR_BUDGET_PUSD
        ),
        "event_ceiling": event_before < MAX_EVENT_NOTIONAL_PUSD,
        "band_ceiling": band_before < MAX_BAND_NOTIONAL_PUSD,
        "daily_loss_ceiling": daily_loss_before < MAX_DAILY_LOSS_PUSD,
        **profile_checks,
    }
    missing = [name for name, valid in checks.items() if not valid]
    if missing:
        raise RuntimeError(
            "Stage 2 quote/preflight binding failed: " + ", ".join(missing)
        )
    envelope = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "target_date": gate.get("target_date"),
        "condition_id": str(gate.get("condition_id") or "").lower(),
        "token_id": str(gate.get("token_id") or ""),
        "funder_address": str(gate.get("funder_address") or "").lower(),
        "source_permission_profile": source_profile,
        "source_run_mode": row.get("run_mode"),
        "source_live_trade_permission": bool_value(
            row.get("live_trade_permission"),
            False,
        ),
        "source_shadow_mode": bool_value(row.get("shadow_mode"), False),
        "model_promotion_bypass_scope": (
            "none"
            if source_profile == "model"
            else "stage2_single_submit_from_market_harvest_paper_proof"
        ),
        "ordinary_model_lane_unchanged": True,
        "session_budget_pusd": str(budget),
        "max_daily_loss_pusd": str(MAX_DAILY_LOSS_PUSD),
        "max_event_notional_pusd": str(MAX_EVENT_NOTIONAL_PUSD),
        "max_band_notional_pusd": str(MAX_BAND_NOTIONAL_PUSD),
        "max_order_notional_pusd": str(order_cap),
        "quote_ttl_seconds": str(ttl),
        "max_network_submits": 1,
        "post_only_required": True,
        "backed_buy_only": True,
        "naked_sell_forbidden": True,
        "risk_ceilings_non_raisable": True,
        "quote_price": str(price),
        "quoted_size": str(quoted_size),
        "quote_generated_at_utc": generated.isoformat(),
        "quote_expires_at_utc": (
            generated + timedelta(seconds=float(ttl))
        ).isoformat(),
        "event_notional_before_pusd": str(event_before),
        "band_notional_before_pusd": str(band_before),
        "daily_loss_before_pusd": str(daily_loss_before),
        "daily_loss_before_basis": daily_loss_basis,
        "platform_verification_sha256": gate.get("artifact_sha256"),
        "stage1_lifecycle_bundle_sha256": gate.get(
            "stage1_lifecycle_bundle_sha256"
        ),
        "quote_decision_sha256": _canonical_hash(row),
        "market_preflight_sha256": _canonical_hash(preflight),
        "paper_counterfactual": paper_binding,
        "public_execution_capture": capture_binding,
        "secret_values_redacted": True,
    }
    envelope["envelope_sha256"] = _canonical_hash(envelope)
    return envelope


def _accepted_paid_rebate(rewards, *, maker_address, condition_id):
    evidence = dict((rewards or {}).get("maker_rebate_evidence") or {})
    rows = evidence.get("rows")
    try:
        parsed = urlsplit(str(evidence.get("request_url") or ""))
        query = parse_qs(parsed.query, keep_blank_values=True)
    except (TypeError, ValueError):
        parsed = None
        query = {}
    query_maker = (query.get("maker_address") or [""])[0]
    query_date = (query.get("date") or [""])[0]
    scope_ok = all((
        evidence.get("status") == "OBSERVED",
        evidence.get("query_scope") == "exact_maker_date",
        evidence.get("payout_cycle_complete") is True,
        evidence.get("http_status") == 200,
        _is_sha256(evidence.get("response_sha256")),
        isinstance(rows, list) and all(isinstance(row, dict) for row in rows),
        parsed is not None,
        parsed.scheme.lower() == "https",
        parsed.netloc.lower() == "clob.polymarket.com",
        parsed.path == "/rebates/current",
        not parsed.fragment,
        set(query) == {"date", "maker_address"},
        query_maker.lower() == str(maker_address or "").lower(),
        query_date == str(evidence.get("query_date") or ""),
    ))
    total = Decimal("0")
    if scope_ok:
        for row in rows:
            try:
                amount = _decimal(
                    row.get("rebated_fees_usdc"),
                    "paid maker rebate",
                    allow_zero=True,
                )
            except RuntimeError:
                scope_ok = False
                break
            if (
                str(row.get("maker_address") or "").lower()
                != str(maker_address or "").lower()
                or str(row.get("date") or "") != query_date
            ):
                scope_ok = False
                break
            if str(row.get("condition_id") or "").lower() == str(
                condition_id or ""
            ).lower():
                total += amount
    return {
        "paid_rebate_evidence_verified": scope_ok,
        "accepted_paid_rebate_pusd": str(total if scope_ok else Decimal("0")),
        "query_date": evidence.get("query_date") if scope_ok else None,
        "response_sha256": evidence.get("response_sha256") if scope_ok else None,
        "payout_cycle_complete": evidence.get("payout_cycle_complete") is True,
        "unverified_rebate_credited": False,
    }


def _raise_final_reconciliation(journal, cleanup, order_id, message):
    error = RuntimeError(message)
    try:
        journal.record(
            "session_failed",
            phase="final_reconciliation",
            exception_type=type(error).__name__,
            order_id=order_id,
            cleanup=cleanup,
        )
    except Exception:
        pass
    raise error


def execute_stage2_maker_session(
    adapter,
    platform_gate,
    quote_decision,
    market_preflight,
    paper_counterfactual,
    public_capture_evidence,
    *,
    confirmation,
    session_budget_pusd,
    journal_path,
    monotonic_clock=None,
    wall_clock=None,
    sleeper=None,
    observation_timeout_seconds=10.0,
    poll_interval_seconds=0.25,
    heartbeat_interval_seconds=5.0,
):
    """Submit at most one smallest-valid backed BUY and reconcile it fully."""

    if confirmation != CONFIRMATION:
        raise RuntimeError("Stage 2 requires the exact one-band maker confirmation token")
    if not getattr(adapter, "supports_trading", False):
        raise RuntimeError("Stage 2 requires a mutation-capable official adapter")
    if not journal_path:
        raise RuntimeError("Stage 2 requires a durable new journal path")
    heartbeat_interval = _decimal(
        heartbeat_interval_seconds,
        "Stage 2 heartbeat interval",
    )
    if heartbeat_interval > MAX_HEARTBEAT_INTERVAL_SECONDS:
        raise RuntimeError("Stage 2 heartbeat interval cannot exceed five seconds")
    observation_timeout = float(observation_timeout_seconds)
    poll_interval = max(0.01, float(poll_interval_seconds))
    if not 0 < observation_timeout <= 30:
        raise RuntimeError("Stage 2 observation timeout must be in (0, 30] seconds")

    clock = monotonic_clock or time.monotonic
    current_time = wall_clock or _utc_now
    sleep = sleeper or time.sleep
    envelope = build_stage2_session_envelope(
        adapter,
        platform_gate,
        quote_decision,
        market_preflight,
        paper_counterfactual,
        public_capture_evidence,
        session_budget_pusd=session_budget_pusd,
        now=current_time(),
    )
    journal = Stage2Journal(journal_path)
    journal.record(
        "session_authorized",
        envelope_sha256=envelope["envelope_sha256"],
        condition_id=envelope["condition_id"],
        token_id=envelope["token_id"],
        session_budget_pusd=envelope["session_budget_pusd"],
        source_permission_profile=envelope["source_permission_profile"],
        max_network_submits=1,
        post_only_required=True,
        backed_buy_only=True,
        confirmation_matched=True,
        paper_counterfactual_sha256=envelope["paper_counterfactual"][
            "quote_row_sha256"
        ],
        public_capture_status_sha256=envelope["public_execution_capture"][
            "live_status_sha256"
        ],
        secret_values_redacted=True,
    )

    starting_orders = adapter.open_orders()
    if starting_orders:
        journal.record(
            "session_blocked",
            phase="starting_order_check",
            open_order_count=len(starting_orders),
        )
        raise RuntimeError("Stage 2 requires zero open orders at start")
    starting_positions, starting_position_evidence = _verified_exact_positions(adapter)
    if _positive_positions(starting_positions):
        journal.record(
            "session_blocked",
            phase="starting_position_check",
            positive_position_count=len(_positive_positions(starting_positions)),
        )
        raise RuntimeError("Stage 2 requires zero positive positions at start")
    try:
        starting_collateral = _verified_collateral(adapter)
    except Exception as collateral_exc:
        journal.record(
            "session_blocked",
            phase="starting_collateral_check",
            exception_type=type(collateral_exc).__name__,
        )
        raise
    frozen_budget = _decimal(
        envelope["session_budget_pusd"],
        "Stage 2 frozen session budget",
    )
    if any((
        starting_collateral["balance_pusd"] < frozen_budget,
        starting_collateral["balance_pusd"] > MAX_OPERATOR_BUDGET_PUSD,
        starting_collateral["minimum_allowance_pusd"] < frozen_budget,
    )):
        journal.record(
            "session_blocked",
            phase="starting_collateral_check",
            collateral_response_sha256=starting_collateral["response_sha256"],
        )
        raise RuntimeError(
            "Stage 2 current collateral does not satisfy the frozen wallet envelope"
        )
    journal.record(
        "starting_state_verified",
        zero_open_orders=True,
        zero_positive_positions=True,
        position_response_sha256=starting_position_evidence["response_sha256"],
        collateral_response_sha256=starting_collateral["response_sha256"],
        collateral_balance_pusd=str(starting_collateral["balance_pusd"]),
        minimum_allowance_pusd=str(
            starting_collateral["minimum_allowance_pusd"]
        ),
    )

    cleanup_armed = True
    order_id = None
    order_size = None
    order_price = None
    placed_at = None
    phase = "stage2_capability"
    operation_error = None
    final_events = []
    final_positions = []
    final_position_evidence = {}
    final_collateral = {}
    cleanup = {
        "cancel_order_attempted": False,
        "cancel_all_attempted": False,
        "zero_open_orders_verified": False,
        "exception_type": None,
        "exception_types": [],
    }
    try:
        capability = adapter.authorize_stage2_maker_session(platform_gate, envelope)
        journal.record(
            "stage2_capability_issued",
            single_submit=True,
            envelope_sha256=envelope["envelope_sha256"],
        )
        phase = "heartbeat"
        heartbeat = adapter.heartbeat()
        last_heartbeat_at = clock()
        journal.record(
            "heartbeat_acknowledged",
            heartbeat_id_present=bool(_value(heartbeat, "heartbeat_id")),
        )
        phase = "market_rules"
        rules = adapter.refresh_market_rules()
        if (
            str(rules.get("token_id") or "") != envelope["token_id"]
            or str(rules.get("condition_id") or "").lower()
            != envelope["condition_id"]
        ):
            raise RuntimeError("Stage 2 fresh market rules changed exact scope")
        min_size = _decimal(rules.get("min_order_size"), "fresh minimum order size")
        quoted_size = _decimal(envelope["quoted_size"], "quoted size")
        if quoted_size < min_size:
            raise RuntimeError("Stage 2 quote size is below the fresh exchange minimum")
        order_size = min_size
        order_price = _decimal(envelope["quote_price"], "Stage 2 order price")
        notional = order_price * order_size
        event_after = _decimal(
            envelope["event_notional_before_pusd"],
            "event notional",
            allow_zero=True,
        ) + notional
        band_after = _decimal(
            envelope["band_notional_before_pusd"],
            "band notional",
            allow_zero=True,
        ) + notional
        session_budget = _decimal(envelope["session_budget_pusd"], "session budget")
        daily_loss_after = _decimal(
            envelope["daily_loss_before_pusd"],
            "daily loss",
            allow_zero=True,
        ) + notional
        if any((
            notional > _decimal(
                envelope["max_order_notional_pusd"],
                "frozen order notional cap",
            ),
            daily_loss_after > _decimal(
                envelope["max_daily_loss_pusd"],
                "frozen daily-loss cap",
            ),
            notional > session_budget,
            event_after > MAX_EVENT_NOTIONAL_PUSD,
            band_after > MAX_BAND_NOTIONAL_PUSD,
        )):
            raise RuntimeError("Stage 2 smallest valid order exceeds a frozen risk ceiling")
        intent = {
            "token_id": envelope["token_id"],
            "price": str(order_price),
            "size": str(order_size),
            "side": "BUY",
        }
        journal.record(
            "intent_prepared",
            side="BUY",
            price=str(order_price),
            size=str(order_size),
            order_notional_pusd=str(notional),
            event_notional_after_pusd=str(event_after),
            band_notional_after_pusd=str(band_after),
            daily_loss_after_pusd=str(daily_loss_after),
            post_only_required=True,
        )
        phase = "placement"
        quote_expires_at = _parse_utc(
            envelope["quote_expires_at_utc"],
            "Stage 2 quote expiry",
        )
        paper_expires_at = _parse_utc(
            envelope["paper_counterfactual"]["expires_at_utc"],
            "Stage 2 paper counterfactual expiry",
        )
        capture_expires_at = _parse_utc(
            envelope["public_execution_capture"]["expires_at_utc"],
            "Stage 2 public capture expiry",
        )
        submit_wall_time = current_time()
        if submit_wall_time.tzinfo is None:
            submit_wall_time = submit_wall_time.replace(tzinfo=timezone.utc)
        submit_time_utc = submit_wall_time.astimezone(timezone.utc)
        remaining_ttl_seconds = min(
            (quote_expires_at - submit_time_utc).total_seconds(),
            (paper_expires_at - submit_time_utc).total_seconds(),
            (capture_expires_at - submit_time_utc).total_seconds(),
        )
        if remaining_ttl_seconds <= 0:
            raise RuntimeError(
                "Stage 2 quote, paper counterfactual, or public capture expired "
                "before order submission"
            )
        response = adapter.place_order(intent, stage2_capability=capability)
        placed_at = clock()
        order_id = _order_id(response)
        if not order_id:
            raise RuntimeError("Stage 2 placement response omitted the order id")
        journal.record(
            "order_accepted",
            order_id=order_id,
            placement_status=str(_value(response, "status") or "").lower(),
        )

        phase = "authoritative_observation"
        observation_deadline = clock() + observation_timeout
        observed = False
        while clock() <= observation_deadline:
            if Decimal(str(clock() - last_heartbeat_at)) >= heartbeat_interval:
                adapter.heartbeat()
                last_heartbeat_at = clock()
                journal.record("heartbeat_continued", phase=phase)
            open_orders = adapter.open_orders()
            final_events = _scoped_events(adapter.user_events(), order_id)
            summary = _event_summary(final_events)
            if summary["invalid_event_evidence"]:
                raise RuntimeError("Stage 2 user-event evidence is malformed or unbound")
            if summary["taker_observed"]:
                raise RuntimeError("Stage 2 observed a taker lifecycle on a post-only order")
            if summary["failed_trade_ids"]:
                raise RuntimeError("Stage 2 observed a failed trade lifecycle")
            if summary["order_observed"] and (
                _contains_order(open_orders, order_id) or summary["confirmed"]
            ):
                observed = True
                break
            sleep(poll_interval)
        if not observed:
            raise RuntimeError(
                "Stage 2 order was not observed on the authoritative user stream"
            )
        journal.record(
            "order_observed",
            order_id=order_id,
            authoritative_user_event_observed=True,
        )

        phase = "resting_ttl"
        ttl_deadline = placed_at + remaining_ttl_seconds
        while clock() < ttl_deadline:
            if Decimal(str(clock() - last_heartbeat_at)) >= heartbeat_interval:
                adapter.heartbeat()
                last_heartbeat_at = clock()
                journal.record("heartbeat_continued", phase=phase)
            open_orders = adapter.open_orders()
            final_events = _scoped_events(adapter.user_events(), order_id)
            summary = _event_summary(final_events)
            if summary["invalid_event_evidence"]:
                raise RuntimeError("Stage 2 user-event evidence is malformed or unbound")
            if summary["taker_observed"]:
                raise RuntimeError("Stage 2 observed a taker lifecycle on a post-only order")
            if summary["failed_trade_ids"]:
                raise RuntimeError("Stage 2 observed a failed trade lifecycle")
            if summary["unresolved_trade_ids"]:
                journal.record(
                    "trade_pending_stop",
                    order_id=order_id,
                    trade_id_count=len(summary["unresolved_trade_ids"]),
                )
                break
            if not _contains_order(open_orders, order_id):
                if summary["confirmed"]:
                    break
                raise RuntimeError(
                    "Stage 2 order disappeared without authoritative terminal lifecycle"
                )
            sleep(min(poll_interval, max(0.0, ttl_deadline - clock())))
    except Exception as exc:
        operation_error = exc
    finally:
        if cleanup_armed:
            cleanup_errors = []
            needs_order_cancel = bool(order_id)
            if order_id:
                try:
                    needs_order_cancel = _contains_order(
                        adapter.open_orders(),
                        order_id,
                    )
                except Exception as open_reader_exc:
                    cleanup["pre_cancel_open_order_reader_exception_type"] = type(
                        open_reader_exc
                    ).__name__
                    cleanup_errors.append(open_reader_exc)
            if order_id and needs_order_cancel:
                cleanup["cancel_order_attempted"] = True
                try:
                    adapter.cancel_order(order_id)
                except Exception as cancel_exc:
                    cleanup["cancel_order_exception_type"] = type(cancel_exc).__name__
                    cleanup_errors.append(cancel_exc)

            cleanup["cancel_all_attempted"] = True
            try:
                adapter.cancel_all()
            except Exception as cancel_all_exc:
                cleanup["cancel_all_exception_type"] = type(cancel_all_exc).__name__
                cleanup_errors.append(cancel_all_exc)

            try:
                remaining = adapter.open_orders()
                cleanup["zero_open_orders_verified"] = not bool(remaining)
                if remaining:
                    raise RuntimeError("Stage 2 final cancel-all left open orders")
            except Exception as final_open_reader_exc:
                cleanup["final_open_order_reader_exception_type"] = type(
                    final_open_reader_exc
                ).__name__
                cleanup_errors.append(final_open_reader_exc)

            try:
                terminal_deadline = clock() + observation_timeout
                while order_id and clock() <= terminal_deadline:
                    final_events = _scoped_events(adapter.user_events(), order_id)
                    summary = _event_summary(final_events)
                    filled = sum(
                        _decimal(row.get("fill_size"), "confirmed fill size")
                        for row in summary["confirmed"]
                    )
                    if (
                        not summary["unresolved_trade_ids"]
                        and (
                            order_size is not None
                            and filled >= order_size
                            or summary["cancellation_observed"]
                        )
                    ):
                        break
                    sleep(poll_interval)
            except Exception as terminal_reader_exc:
                cleanup["terminal_event_reader_exception_type"] = type(
                    terminal_reader_exc
                ).__name__
                cleanup_errors.append(terminal_reader_exc)

            try:
                final_positions, final_position_evidence = _verified_exact_positions(adapter)
            except Exception as position_reader_exc:
                cleanup["final_position_reader_exception_type"] = type(
                    position_reader_exc
                ).__name__
                cleanup_errors.append(position_reader_exc)

            try:
                final_collateral = _verified_collateral(adapter)
            except Exception as collateral_reader_exc:
                cleanup["final_collateral_reader_exception_type"] = type(
                    collateral_reader_exc
                ).__name__
                cleanup_errors.append(collateral_reader_exc)

            if cleanup_errors:
                cleanup["exception_type"] = type(cleanup_errors[0]).__name__
                cleanup["exception_types"] = [
                    type(error).__name__ for error in cleanup_errors
                ]
                if operation_error is None:
                    operation_error = RuntimeError(
                        "Stage 2 cleanup or final evidence reconciliation failed"
                    )

    if operation_error is not None:
        try:
            journal.record(
                "session_failed",
                phase=phase,
                exception_type=type(operation_error).__name__,
                order_id=order_id,
                cleanup=cleanup,
            )
        except Exception:
            pass
        raise operation_error

    summary = _event_summary(final_events)
    if summary["invalid_event_evidence"]:
        _raise_final_reconciliation(
            journal,
            cleanup,
            order_id,
            "Stage 2 final user-event evidence is malformed or unbound",
        )
    if summary["taker_observed"]:
        _raise_final_reconciliation(
            journal,
            cleanup,
            order_id,
            "Stage 2 final reconciliation observed taker liquidity",
        )
    if summary["failed_trade_ids"] or summary["unresolved_trade_ids"]:
        _raise_final_reconciliation(
            journal,
            cleanup,
            order_id,
            "Stage 2 final trade lifecycle is unresolved or failed",
        )
    confirmed_fills = []
    filled_size = Decimal("0")
    for row in summary["confirmed"]:
        if str(row.get("liquidity_role") or "").upper() != "MAKER":
            _raise_final_reconciliation(
                journal,
                cleanup,
                order_id,
                "Stage 2 confirmed fill is not maker liquidity",
            )
        try:
            size = _decimal(row.get("fill_size"), "confirmed fill size")
            price = _decimal(row.get("fill_price"), "confirmed fill price")
        except RuntimeError:
            _raise_final_reconciliation(
                journal,
                cleanup,
                order_id,
                "Stage 2 confirmed fill contains invalid numeric evidence",
            )
        filled_size += size
        confirmed_fills.append({
            "trade_id": row.get("trade_id"),
            "order_id": row.get("order_id"),
            "transaction_hash": row.get("transaction_hash"),
            "fill_size": str(size),
            "fill_price": str(price),
            "liquidity_role": "MAKER",
            "fee_rate_bps": row.get("fee_rate_bps"),
            "raw_event_sha256": row.get("raw_event_sha256"),
        })

    try:
        positive = _positive_positions(final_positions)
    except RuntimeError:
        _raise_final_reconciliation(
            journal,
            cleanup,
            order_id,
            "Stage 2 final position contains invalid numeric evidence",
        )
    token_owned = sum(
        size for asset, size, _ in positive if asset == envelope["token_id"]
    )
    other_positive = [row for asset, _, row in positive if asset != envelope["token_id"]]
    if other_positive:
        _raise_final_reconciliation(
            journal,
            cleanup,
            order_id,
            "Stage 2 final positions contain an out-of-scope asset",
        )
    if filled_size == 0 and token_owned != 0:
        _raise_final_reconciliation(
            journal,
            cleanup,
            order_id,
            "Stage 2 position exists without a confirmed authoritative fill",
        )
    if filled_size > 0 and token_owned != filled_size:
        _raise_final_reconciliation(
            journal,
            cleanup,
            order_id,
            "Stage 2 confirmed fills do not equal the exact current position",
        )
    if filled_size < (order_size or Decimal("0")) and not summary["cancellation_observed"]:
        _raise_final_reconciliation(
            journal,
            cleanup,
            order_id,
            "Stage 2 unfilled remainder lacks a terminal cancellation event",
        )
    expected_collateral_spend = sum(
        _decimal(row["fill_size"], "confirmed fill size")
        * _decimal(row["fill_price"], "confirmed fill price")
        for row in confirmed_fills
    )
    observed_collateral_spend = (
        starting_collateral["balance_pusd"] - final_collateral["balance_pusd"]
    )
    if observed_collateral_spend != expected_collateral_spend:
        _raise_final_reconciliation(
            journal,
            cleanup,
            order_id,
            "Stage 2 collateral change does not equal confirmed maker-fill notional",
        )

    evidence_reader_errors = {}
    try:
        fees = adapter.fees()
    except Exception as exc:
        fees = {}
        evidence_reader_errors["fee_reader_exception_type"] = type(exc).__name__
    try:
        rewards = adapter.rewards()
    except Exception as exc:
        rewards = {}
        evidence_reader_errors["rebate_reader_exception_type"] = type(exc).__name__
    rebate = _accepted_paid_rebate(
        rewards,
        maker_address=getattr(adapter, "maker_address", ""),
        condition_id=getattr(adapter, "condition_id", ""),
    )
    journal.record(
        "session_passed",
        order_id=order_id,
        confirmed_fill_count=len(confirmed_fills),
        confirmed_fill_size=str(filled_size),
        zero_open_orders_verified=True,
        exact_position_reconciled=True,
        exact_collateral_reconciled=True,
        accepted_paid_rebate_pusd=rebate["accepted_paid_rebate_pusd"],
        economics_complete=False,
        evidence_reader_errors=evidence_reader_errors,
    )
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": "PASS",
        "completed_at_utc": _utc_iso(current_time()),
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "claim_boundary": "bounded_one_order_lifecycle_not_profitability",
        "source_permission_profile": envelope["source_permission_profile"],
        "ordinary_model_lane_unchanged": True,
        "condition_id": envelope["condition_id"],
        "token_id": envelope["token_id"],
        "session_budget_pusd": envelope["session_budget_pusd"],
        "envelope": envelope,
        "order": {
            "order_id": order_id,
            "side": "BUY",
            "price": str(order_price),
            "size": str(order_size),
            "post_only_forced": True,
            "network_submit_count": 1,
        },
        "authoritative_lifecycle": {
            "event_count": len(final_events),
            "event_hashes": sorted({
                str(row.get("raw_event_sha256"))
                for row in final_events
                if row.get("raw_event_sha256")
            }),
            "cancellation_observed": summary["cancellation_observed"],
            "unresolved_trade_ids": [],
            "taker_liquidity_observed": False,
        },
        "confirmed_maker_fills": confirmed_fills,
        "final_reconciliation": {
            "zero_open_orders_verified": True,
            "positions": final_positions,
            "position_response_sha256": final_position_evidence.get("response_sha256"),
            "position_request_url": final_position_evidence.get("request_url"),
            "confirmed_fill_size": str(filled_size),
            "exact_position_size": str(token_owned),
            "starting_collateral_balance_pusd": str(
                starting_collateral["balance_pusd"]
            ),
            "final_collateral_balance_pusd": str(
                final_collateral["balance_pusd"]
            ),
            "expected_collateral_spend_pusd": str(expected_collateral_spend),
            "observed_collateral_spend_pusd": str(observed_collateral_spend),
            "starting_collateral_response_sha256": starting_collateral[
                "response_sha256"
            ],
            "final_collateral_response_sha256": final_collateral[
                "response_sha256"
            ],
        },
        "fees": {
            "current_market_fee_rate": fees.get("fee_rate_bps") if isinstance(fees, dict) else None,
            "authoritative_fill_fee_rates_bps": sorted({
                str(row.get("fee_rate_bps"))
                for row in confirmed_fills
                if row.get("fee_rate_bps") is not None
            }),
            "actual_maker_fee_observed": True,
            "accepted_actual_fee_pusd": "0",
            "evidence": (
                "confirmed maker role plus exact collateral-spend reconciliation"
            ),
        },
        "rebate": rebate,
        "economic_acceptance": {
            "complete": False,
            "realized_pnl_after_fees_and_paid_rebates_pusd": None,
            "reason": (
                "position exit/settlement and completed rebate payout cycle are not yet "
                "reconciled"
            ),
            "unpaid_or_unverified_rebate_credited": False,
        },
        "evidence_reader_errors": evidence_reader_errors,
        "cleanup": cleanup,
        "journal_path": str(journal.path),
        "journal_sha256": journal.sha256(),
        "secret_values_redacted": True,
    }
    return result
