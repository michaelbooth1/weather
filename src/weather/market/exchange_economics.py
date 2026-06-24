"""Exchange economics snapshot validation and drift reporting.

This module owns the paper/shadow evidence gate for platform economics.  The
live account/platform submission gate remains in ``market_making_preflight``.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from weather.market.market_config import ensure_date
from weather.market.market_making_preflight import (
    SUPPORTED_PLATFORM_IDS,
    non_empty_text,
    recent_utc_timestamp,
)
from weather.market.mm_policy import maybe_float, parse_time, utc_now
from weather.paths import data_path
from weather.schema_registry import schema_version


SNAPSHOT_SCHEMA_VERSION = schema_version("exchange_economics_snapshot")
DRIFT_SCHEMA_VERSION = schema_version("exchange_economics_drift")
DEFAULT_PLATFORM = "polymarket_us"
DEFAULT_MAX_AGE_HOURS = 24.0
DEFAULT_SNAPSHOT = data_path() / "backtest" / "exchange_economics_snapshot.json"
DEFAULT_ACCEPTED_SNAPSHOT = data_path() / "backtest" / "exchange_economics_accepted_snapshot.json"
DEFAULT_DRIFT_REPORT = data_path() / "backtest" / "exchange_economics_drift.json"

SNAPSHOT_ID_PREFIX = "xecon"
CURRENT_EVIDENCE_BASIS = "current_exchange_economics"
STALE_EVIDENCE_BASIS = "paper_stale_exchange_economics"

MATERIAL_FIELD_PATHS = (
    ("fee_model",),
    ("maker_rebate",),
    ("liquidity_rewards",),
    ("reward_formula",),
    ("market_rules", "tick_size"),
    ("market_rules", "min_order_size"),
    ("market_rules", "order_semantics"),
    ("api_order_semantics",),
    ("order_semantics",),
)


def _json_hash(payload, length=24):
    import hashlib

    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:length]


def _load_json(path):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _dig(payload, path):
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _source_urls(payload):
    urls = _as_list(payload.get("source_urls"))
    metadata = payload.get("source_metadata") or {}
    urls.extend(_as_list(metadata.get("source_urls")))
    sources = payload.get("sources") or []
    if isinstance(sources, list):
        for row in sources:
            if isinstance(row, dict):
                urls.extend(_as_list(row.get("url")))
                urls.extend(_as_list(row.get("source_url")))
    return [str(url).strip() for url in urls if non_empty_text(str(url))]


def _source_hash(payload):
    metadata = payload.get("source_metadata") or {}
    return (
        payload.get("source_hash")
        or payload.get("source_hash_sha256")
        or metadata.get("source_hash")
        or metadata.get("source_hash_sha256")
    )


def _target_text(value):
    if not value:
        return None
    if isinstance(value, date):
        return value.isoformat()
    try:
        return ensure_date(value).isoformat()
    except (TypeError, ValueError):
        return str(value)


def normalized_economics_payload(payload):
    """Return only material economics fields for stable hashing/drift checks."""
    payload = payload or {}
    market_rules = payload.get("market_rules") or {}
    if "tick_size" not in market_rules and payload.get("tick_size") is not None:
        market_rules = {**market_rules, "tick_size": payload.get("tick_size")}
    if "min_order_size" not in market_rules and payload.get("min_order_size") is not None:
        market_rules = {**market_rules, "min_order_size": payload.get("min_order_size")}
    return {
        "platform": payload.get("platform"),
        "platform_surface": payload.get("platform_surface"),
        "fee_model": payload.get("fee_model") or {},
        "maker_rebate": payload.get("maker_rebate") or {},
        "liquidity_rewards": payload.get("liquidity_rewards") or {},
        "reward_formula": payload.get("reward_formula"),
        "market_rules": market_rules,
        "api_order_semantics": payload.get("api_order_semantics") or {},
        "order_semantics": payload.get("order_semantics") or {},
    }


def snapshot_hash(payload):
    return _json_hash(normalized_economics_payload(payload), length=32)


def snapshot_id(payload):
    existing = str((payload or {}).get("snapshot_id") or "").strip()
    if existing:
        return existing
    return f"{SNAPSHOT_ID_PREFIX}-{snapshot_hash(payload)[:16]}"


def _fee_rate(payload, *names):
    fee_model = (payload or {}).get("fee_model") or {}
    for name in names:
        value = fee_model.get(name)
        if value is None:
            value = payload.get(name)
        parsed = maybe_float(value)
        if parsed is not None:
            return parsed
    return None


def _positive_field(value):
    parsed = maybe_float(value)
    return parsed is not None and parsed > 0


def _valid_nonnegative_field(value):
    parsed = maybe_float(value)
    return parsed is not None and parsed >= 0


def _validated_market_rules(payload):
    rules = dict((payload or {}).get("market_rules") or {})
    if payload.get("tick_size") is not None:
        rules.setdefault("tick_size", payload.get("tick_size"))
    if payload.get("min_order_size") is not None:
        rules.setdefault("min_order_size", payload.get("min_order_size"))
    return rules


def _evidence_target(payload):
    return (
        payload.get("verified_for_target_date")
        or payload.get("target_date")
        or payload.get("run_date")
    )


def _check_snapshot_payload(payload, *, path=None, target_date=None, platform=DEFAULT_PLATFORM, now=None, max_age_hours=None):
    now = utc_now(now)
    target_text = _target_text(target_date)
    max_age = maybe_float(max_age_hours) or maybe_float((payload or {}).get("max_age_hours")) or DEFAULT_MAX_AGE_HOURS
    effective_date = _target_text((payload or {}).get("effective_date"))
    evidence_target = _target_text(_evidence_target(payload or {}))
    market_rules = _validated_market_rules(payload or {})
    source_urls = _source_urls(payload or {})
    fee_model = (payload or {}).get("fee_model") or {}
    rebate = (payload or {}).get("maker_rebate") or {}
    rewards = (payload or {}).get("liquidity_rewards") or {}
    order_semantics = (payload or {}).get("order_semantics") or {}
    api_order_semantics = (payload or {}).get("api_order_semantics") or {}

    taker_fee_rate = _fee_rate(payload, "taker_fee_rate", "theta")
    maker_fee_rate = _fee_rate(payload, "maker_fee_rate")
    flattening_fee_rate = _fee_rate(payload, "flattening_fee_rate")
    maker_rebate_rate = maybe_float(
        rebate.get("maker_rebate_rate")
        or rebate.get("pool_share")
        or payload.get("maker_rebate_rate")
        or payload.get("maker_rebate_pool_share")
    )

    checks = {
        "schema_version_supported": (payload or {}).get("schema_version") == SNAPSHOT_SCHEMA_VERSION,
        "platform_supported": (payload or {}).get("platform") in SUPPORTED_PLATFORM_IDS,
        "platform_matches": platform in (None, "", (payload or {}).get("platform")),
        "effective_date_recorded": effective_date is not None,
        "effective_date_not_after_target": (
            target_text is None or effective_date is None or effective_date <= target_text
        ),
        "target_date_matches": (
            target_text is None or evidence_target is None or evidence_target == target_text
        ),
        "verified_at_recent": recent_utc_timestamp((payload or {}).get("verified_at_utc"), now, max_age),
        "source_urls_recorded": bool(source_urls),
        "source_hash_recorded": non_empty_text(str(_source_hash(payload or {}) or "")),
        "fee_model_recorded": non_empty_text(str(fee_model.get("taker_fee_model") or fee_model.get("name") or "")),
        "taker_fee_rate_recorded": _valid_nonnegative_field(taker_fee_rate),
        "maker_fee_rate_recorded": _valid_nonnegative_field(maker_fee_rate),
        "flattening_fee_rate_recorded": _valid_nonnegative_field(flattening_fee_rate),
        "maker_rebate_formula_recorded": non_empty_text(
            str(rebate.get("formula") or (payload or {}).get("maker_rebate_formula") or "")
        ),
        "maker_rebate_rate_recorded": _valid_nonnegative_field(maker_rebate_rate),
        "reward_formula_recorded": non_empty_text(
            str(rewards.get("formula") or (payload or {}).get("reward_formula") or "")
        ),
        "tick_size_recorded": _positive_field(market_rules.get("tick_size")),
        "min_order_size_recorded": _positive_field(market_rules.get("min_order_size")),
        "order_semantics_recorded": bool(order_semantics or market_rules.get("order_semantics")),
        "api_order_semantics_recorded": bool(api_order_semantics),
    }
    missing = [name for name, ok in checks.items() if not ok]
    economics_hash = snapshot_hash(payload or {})
    return {
        "required": True,
        "ok": not missing,
        "status": "PASS" if not missing else "BLOCK",
        "evidence_basis": CURRENT_EVIDENCE_BASIS if not missing else STALE_EVIDENCE_BASIS,
        "path": str(path) if path else None,
        "schema_version": (payload or {}).get("schema_version"),
        "snapshot_id": snapshot_id(payload or {}),
        "snapshot_hash": economics_hash,
        "exchange_economics_hash": economics_hash,
        "source_hash": _source_hash(payload or {}),
        "platform": (payload or {}).get("platform"),
        "platform_surface": (payload or {}).get("platform_surface"),
        "target_date": target_text,
        "verified_for_target_date": evidence_target,
        "effective_date": effective_date,
        "verified_at_utc": (payload or {}).get("verified_at_utc"),
        "max_age_hours": max_age,
        "source_urls": source_urls,
        "checks": checks,
        "missing": missing,
        "reason": "ok" if not missing else "exchange-economics snapshot missing current proof: " + ", ".join(missing),
    }


def load_exchange_economics_gate(
    path=DEFAULT_SNAPSHOT,
    target_date=None,
    *,
    platform=DEFAULT_PLATFORM,
    now=None,
    max_age_hours=None,
    required=True,
):
    if not required:
        return {"required": False, "ok": True, "status": "PASS", "reason": "not required"}
    path = Path(path) if path else None
    if path is None:
        return {
            "required": True,
            "ok": False,
            "status": "BLOCK",
            "path": None,
            "target_date": _target_text(target_date),
            "evidence_basis": STALE_EVIDENCE_BASIS,
            "reason": "no exchange-economics snapshot path provided",
            "missing": ["snapshot_path"],
        }
    if not path.exists():
        return {
            "required": True,
            "ok": False,
            "status": "BLOCK",
            "path": str(path),
            "target_date": _target_text(target_date),
            "platform": platform,
            "evidence_basis": STALE_EVIDENCE_BASIS,
            "reason": "exchange-economics snapshot artifact missing",
            "missing": ["snapshot_missing"],
        }
    payload = _load_json(path)
    if payload is None:
        return {
            "required": True,
            "ok": False,
            "status": "BLOCK",
            "path": str(path),
            "target_date": _target_text(target_date),
            "platform": platform,
            "evidence_basis": STALE_EVIDENCE_BASIS,
            "reason": "invalid exchange-economics snapshot JSON",
            "missing": ["snapshot_invalid_json"],
        }
    return _check_snapshot_payload(
        payload,
        path=path,
        target_date=target_date,
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )


def exchange_economics_artifact_fields(gate):
    gate = gate or {}
    return {
        "exchange_economics_status": gate.get("status"),
        "exchange_economics_evidence_basis": gate.get("evidence_basis"),
        "exchange_economics_snapshot_id": gate.get("snapshot_id"),
        "exchange_economics_hash": gate.get("snapshot_hash") or gate.get("exchange_economics_hash"),
        "exchange_economics_source_hash": gate.get("source_hash"),
        "exchange_economics_verified_at_utc": gate.get("verified_at_utc"),
        "exchange_economics_effective_date": gate.get("effective_date"),
        "exchange_economics_platform": gate.get("platform"),
    }


def compare_snapshots(current, accepted):
    changes = []
    current_econ = normalized_economics_payload(current or {})
    accepted_econ = normalized_economics_payload(accepted or {})
    for path in MATERIAL_FIELD_PATHS:
        old = _dig(accepted_econ, path)
        new = _dig(current_econ, path)
        if old != new:
            changes.append({
                "field": ".".join(path),
                "accepted": old,
                "current": new,
            })
    return changes


def build_drift_report(
    snapshot_path=DEFAULT_SNAPSHOT,
    accepted_snapshot_path=DEFAULT_ACCEPTED_SNAPSHOT,
    *,
    target_date=None,
    platform=DEFAULT_PLATFORM,
    now=None,
    max_age_hours=None,
):
    current_gate = load_exchange_economics_gate(
        snapshot_path,
        target_date,
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )
    current_payload = _load_json(snapshot_path) if snapshot_path and Path(snapshot_path).exists() else {}
    accepted_payload = _load_json(accepted_snapshot_path) if accepted_snapshot_path and Path(accepted_snapshot_path).exists() else None
    changes = compare_snapshots(current_payload, accepted_payload) if accepted_payload else []
    rescore_required = bool(changes)
    status = "BLOCK" if (not current_gate.get("ok") or rescore_required) else "PASS"
    return {
        "schema_version": DRIFT_SCHEMA_VERSION,
        "generated_at_utc": utc_now(now).isoformat(),
        "status": status,
        "target_date": _target_text(target_date),
        "platform": platform,
        "snapshot_path": str(snapshot_path) if snapshot_path else None,
        "accepted_snapshot_path": str(accepted_snapshot_path) if accepted_snapshot_path else None,
        "current_gate": current_gate,
        "current_snapshot_id": current_gate.get("snapshot_id"),
        "current_snapshot_hash": current_gate.get("snapshot_hash"),
        "accepted_snapshot_id": snapshot_id(accepted_payload) if accepted_payload else None,
        "accepted_snapshot_hash": snapshot_hash(accepted_payload) if accepted_payload else None,
        "accepted_snapshot_present": accepted_payload is not None,
        "material_change_count": len(changes),
        "material_changes": changes,
        "rescore_required": rescore_required,
        "blockers": (
            [
                {
                    "code": "exchange_economics_snapshot_not_current",
                    "detail": current_gate.get("reason"),
                }
            ]
            if not current_gate.get("ok")
            else []
        )
        + (
            [
                {
                    "code": "exchange_economics_material_drift_rescore_required",
                    "detail": f"{len(changes)} material exchange-economics field(s) changed; rescore paper evidence",
                }
            ]
            if rescore_required
            else []
        ),
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def write_drift_report(payload, path=DEFAULT_DRIFT_REPORT):
    return write_json(path, payload)


def build_snapshot_payload(
    *,
    target_date,
    verified_at_utc,
    platform=DEFAULT_PLATFORM,
    effective_date=None,
    source_hash="source-docs-sha256-test",
    source_urls=None,
    tick_size=0.001,
    min_order_size=1.0,
    taker_fee_rate=0.05,
    maker_fee_rate=0.05,
    maker_rebate_pool_share=0.25,
    flattening_fee_rate=0.05,
    reward_formula="polymarket_liquidity_rewards_distance_threshold",
):
    source_urls = source_urls or ["https://docs.polymarket.com/"]
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "platform": platform,
        "platform_surface": "clob",
        "verified_for_target_date": _target_text(target_date),
        "effective_date": _target_text(effective_date or target_date),
        "verified_at_utc": verified_at_utc,
        "max_age_hours": DEFAULT_MAX_AGE_HOURS,
        "source_urls": list(source_urls),
        "source_hash": source_hash,
        "fee_model": {
            "taker_fee_model": "polymarket_symmetric_price_v1",
            "taker_fee_rate": taker_fee_rate,
            "maker_fee_rate": maker_fee_rate,
            "flattening_fee_rate": flattening_fee_rate,
        },
        "maker_rebate": {
            "formula": "maker_fee_equivalent_usdc * maker_rebate_pool_share",
            "pool_share": maker_rebate_pool_share,
        },
        "liquidity_rewards": {
            "formula": reward_formula,
            "distance_threshold": 0.045,
            "c": 3.0,
        },
        "market_rules": {
            "tick_size": tick_size,
            "min_order_size": min_order_size,
            "order_semantics": {
                "limit_order": "postable/cancellable CLOB limit order",
                "market_order": "crosses executable resting depth",
                "cancel": "cancel by order id before fill",
            },
        },
        "api_order_semantics": {
            "order_type": "GTC limit order by default",
            "partial_fill": "allowed",
            "self_trade": "platform-defined",
        },
    }
    payload["snapshot_id"] = snapshot_id(payload)
    payload["exchange_economics_hash"] = snapshot_hash(payload)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate exchange economics snapshot and drift.")
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--accepted-snapshot", default=str(DEFAULT_ACCEPTED_SNAPSHOT))
    parser.add_argument("--target-date", default="")
    parser.add_argument("--platform", default=DEFAULT_PLATFORM)
    parser.add_argument("--now", default=None)
    parser.add_argument("--json-out", default=str(DEFAULT_DRIFT_REPORT))
    args = parser.parse_args(argv)
    payload = build_drift_report(
        snapshot_path=args.snapshot,
        accepted_snapshot_path=args.accepted_snapshot,
        target_date=args.target_date or None,
        platform=args.platform,
        now=args.now,
    )
    out = write_drift_report(payload, args.json_out)
    print(f"Exchange economics drift: {payload['status']} -> {out}")
    return payload


if __name__ == "__main__":
    main()
