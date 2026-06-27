"""Exchange economics snapshot validation and drift reporting.

This module owns the paper/shadow evidence gate for platform economics.  The
live account/platform submission gate remains in ``market_making_preflight``.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
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
from weather.paths import data_path, docs_path
from weather.schema_registry import schema_version


SNAPSHOT_SCHEMA_VERSION = schema_version("exchange_economics_snapshot")
DRIFT_SCHEMA_VERSION = schema_version("exchange_economics_drift")
DEFAULT_PLATFORM = "polymarket_us"
DEFAULT_MAX_AGE_HOURS = 24.0
DEFAULT_TEMPLATE = docs_path("research", "exchange_economics_snapshot_template.json")
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
RUNTIME_SNAPSHOT_FIELDS = {
    "accepted_at_utc",
    "accepted_from_snapshot_path",
    "accepted_gate",
    "exchange_economics_hash",
    "published_at_utc",
    "published_from_template",
    "snapshot_hash",
    "snapshot_id",
    "source_hash",
    "source_hash_sha256",
    "target_date",
    "verified_at_utc",
    "verified_for_target_date",
}
SOURCE_HASH_METADATA_FIELDS = {"source_hash", "source_hash_sha256"}


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


def source_proof_hash(payload):
    payload = payload or {}
    source_metadata = {
        key: value
        for key, value in (payload.get("source_metadata") or {}).items()
        if key not in SOURCE_HASH_METADATA_FIELDS
    }
    source_payload = {
        "source_urls": sorted(set(_source_urls(payload))),
        "sources": payload.get("sources") or [],
        "source_metadata": source_metadata,
        "source_evidence": payload.get("source_evidence") or {},
        "source_verification": payload.get("source_verification") or {},
    }
    return _json_hash(source_payload, length=32)


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


def load_snapshot_template(path=DEFAULT_TEMPLATE):
    path = Path(path)
    payload = _load_json(path)
    if payload is None:
        raise ValueError(f"invalid or missing exchange-economics template: {path}")
    return payload


def prepare_snapshot_from_template(
    template_payload,
    *,
    target_date=None,
    verified_at_utc=None,
    platform=DEFAULT_PLATFORM,
    now=None,
):
    now_dt = utc_now(now)
    target_text = _target_text(target_date or _evidence_target(template_payload or {}) or now_dt.date())
    verified_at = verified_at_utc or now_dt.isoformat()
    payload = deepcopy(template_payload or {})
    for field in RUNTIME_SNAPSHOT_FIELDS:
        payload.pop(field, None)
    payload["schema_version"] = payload.get("schema_version") or SNAPSHOT_SCHEMA_VERSION
    payload["platform"] = platform or payload.get("platform") or DEFAULT_PLATFORM
    payload["verified_for_target_date"] = target_text
    payload["target_date"] = target_text
    payload["verified_at_utc"] = verified_at
    payload["source_hash"] = source_proof_hash(payload)
    payload["source_hash_sha256"] = payload["source_hash"]
    payload["snapshot_id"] = snapshot_id(payload)
    payload["exchange_economics_hash"] = snapshot_hash(payload)
    return payload


def publish_snapshot_from_template(
    *,
    template_path=DEFAULT_TEMPLATE,
    snapshot_path=DEFAULT_SNAPSHOT,
    target_date=None,
    platform=DEFAULT_PLATFORM,
    now=None,
    max_age_hours=None,
):
    template = load_snapshot_template(template_path)
    payload = prepare_snapshot_from_template(
        template,
        target_date=target_date,
        platform=platform,
        now=now,
    )
    payload["published_at_utc"] = payload["verified_at_utc"]
    payload["published_from_template"] = str(template_path)
    gate = _check_snapshot_payload(
        payload,
        path=snapshot_path,
        target_date=target_date or payload.get("verified_for_target_date"),
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )
    if not gate.get("ok"):
        raise ValueError(gate.get("reason") or "exchange-economics snapshot template did not validate")
    out = write_json(snapshot_path, payload)
    return {
        "status": "PASS",
        "snapshot_path": str(out),
        "template_path": str(template_path),
        "target_date": payload.get("verified_for_target_date"),
        "snapshot_id": gate.get("snapshot_id"),
        "snapshot_hash": gate.get("snapshot_hash"),
        "source_hash": gate.get("source_hash"),
        "gate": gate,
        "payload": payload,
    }


def accept_snapshot_baseline(
    *,
    snapshot_path=DEFAULT_SNAPSHOT,
    accepted_snapshot_path=DEFAULT_ACCEPTED_SNAPSHOT,
    drift_report_path=DEFAULT_DRIFT_REPORT,
    target_date=None,
    platform=DEFAULT_PLATFORM,
    now=None,
    max_age_hours=None,
):
    gate = load_exchange_economics_gate(
        snapshot_path,
        target_date,
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )
    if not gate.get("ok"):
        raise ValueError(gate.get("reason") or "exchange-economics snapshot is not current")
    payload = _load_json(snapshot_path)
    if payload is None:
        raise ValueError(f"invalid exchange-economics snapshot JSON: {snapshot_path}")
    accepted_payload = deepcopy(payload)
    accepted_payload["accepted_at_utc"] = utc_now(now).isoformat()
    accepted_payload["accepted_from_snapshot_path"] = str(snapshot_path)
    accepted_payload["accepted_gate"] = {
        "status": gate.get("status"),
        "evidence_basis": gate.get("evidence_basis"),
        "snapshot_id": gate.get("snapshot_id"),
        "snapshot_hash": gate.get("snapshot_hash"),
        "source_hash": gate.get("source_hash"),
        "verified_at_utc": gate.get("verified_at_utc"),
        "verified_for_target_date": gate.get("verified_for_target_date"),
    }
    accepted_out = write_json(accepted_snapshot_path, accepted_payload)
    drift = build_drift_report(
        snapshot_path=snapshot_path,
        accepted_snapshot_path=accepted_out,
        target_date=target_date,
        platform=platform,
        now=now,
        max_age_hours=max_age_hours,
    )
    drift_out = write_drift_report(drift, drift_report_path) if drift_report_path else None
    return {
        "status": "PASS" if drift.get("status") == "PASS" else drift.get("status"),
        "accepted_snapshot_path": str(accepted_out),
        "drift_report_path": str(drift_out) if drift_out else None,
        "gate": gate,
        "drift": drift,
    }


def build_snapshot_payload(
    *,
    target_date,
    verified_at_utc,
    platform=DEFAULT_PLATFORM,
    effective_date=None,
    source_hash="source-docs-sha256-test",
    source_urls=None,
    tick_size=0.005,
    min_order_size=0.01,
    taker_fee_rate=0.05,
    maker_fee_rate=0.0,
    maker_rebate_pool_share=0.25,
    flattening_fee_rate=0.05,
    reward_formula="score = discount_factor ** ticks_from_best_price * order_size",
):
    source_urls = source_urls or ["https://docs.polymarket.us/fees", "https://docs.polymarket.us/incentives/liquidity"]
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "platform": platform,
        "platform_surface": "retail_api_and_exchange_clob",
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
            "formula": "maker_rebate_usdc = maker_rebate_pool_share * taker_fee_usdc",
            "pool_share": maker_rebate_pool_share,
            "maker_rebate_rate": maker_rebate_pool_share,
            "theta_equivalent": taker_fee_rate * maker_rebate_pool_share,
        },
        "liquidity_rewards": {
            "formula": reward_formula,
            "distance_unit": "ticks_from_best_price",
            "discount_factor_default": 0.3,
            "target_size_default_contracts": 10000,
            "min_payout_usd": 1.0,
            "parameters_market_specific": True,
            "parameters_can_change": True,
        },
        "market_rules": {
            "tick_size": tick_size,
            "min_order_size": min_order_size,
            "tick_size_field": "orderPriceMinTickSize",
            "min_order_size_field": "minimumTradeQty",
            "market_specific_fields_required": True,
            "order_semantics": {
                "limit_order": "Priced order can trade only at the specified price or better.",
                "market_order": "Market behavior is represented by market-to-limit/IOC or a marketable order; no-liquidity market orders can reject.",
                "cancel": "Open orders can be canceled before fill; canceled, expired, or rejected orders do not incur fees.",
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


def _add_drift_args(parser):
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--accepted-snapshot", default=str(DEFAULT_ACCEPTED_SNAPSHOT))
    parser.add_argument("--target-date", default="")
    parser.add_argument("--platform", default=DEFAULT_PLATFORM)
    parser.add_argument("--now", default=None)
    parser.add_argument("--json-out", default=str(DEFAULT_DRIFT_REPORT))
    return parser


def main(argv=None):
    parser = argparse.ArgumentParser(description="Publish, accept, or validate exchange economics snapshots.")
    sub = parser.add_subparsers(dest="command")

    publish = sub.add_parser("publish", help="Stamp and validate a runtime snapshot from the tracked template.")
    publish.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    publish.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    publish.add_argument("--target-date", default="")
    publish.add_argument("--platform", default=DEFAULT_PLATFORM)
    publish.add_argument("--now", default=None)
    publish.add_argument("--max-age-hours", type=float, default=None)
    publish.add_argument("--accept", action="store_true", help="Also promote the published snapshot to the accepted baseline.")
    publish.add_argument("--accepted-snapshot", default=str(DEFAULT_ACCEPTED_SNAPSHOT))
    publish.add_argument("--json-out", default=str(DEFAULT_DRIFT_REPORT))

    accept = sub.add_parser("accept", help="Promote a current validated snapshot to the accepted baseline.")
    accept.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    accept.add_argument("--accepted-snapshot", default=str(DEFAULT_ACCEPTED_SNAPSHOT))
    accept.add_argument("--target-date", default="")
    accept.add_argument("--platform", default=DEFAULT_PLATFORM)
    accept.add_argument("--now", default=None)
    accept.add_argument("--max-age-hours", type=float, default=None)
    accept.add_argument("--json-out", default=str(DEFAULT_DRIFT_REPORT))

    drift = sub.add_parser("drift", help="Validate current snapshot and compare it to the accepted baseline.")
    _add_drift_args(drift)

    _add_drift_args(parser)
    args = parser.parse_args(argv)
    if args.command == "publish":
        payload = publish_snapshot_from_template(
            template_path=args.template,
            snapshot_path=args.snapshot,
            target_date=args.target_date or None,
            platform=args.platform,
            now=args.now,
            max_age_hours=args.max_age_hours,
        )
        print(f"Exchange economics snapshot: {payload['status']} -> {payload['snapshot_path']}")
        if args.accept:
            payload["acceptance"] = accept_snapshot_baseline(
                snapshot_path=args.snapshot,
                accepted_snapshot_path=args.accepted_snapshot,
                drift_report_path=args.json_out,
                target_date=args.target_date or None,
                platform=args.platform,
                now=args.now,
                max_age_hours=args.max_age_hours,
            )
            print(f"Accepted baseline: {payload['acceptance']['status']} -> {payload['acceptance']['accepted_snapshot_path']}")
        return payload
    if args.command == "accept":
        payload = accept_snapshot_baseline(
            snapshot_path=args.snapshot,
            accepted_snapshot_path=args.accepted_snapshot,
            drift_report_path=args.json_out,
            target_date=args.target_date or None,
            platform=args.platform,
            now=args.now,
            max_age_hours=args.max_age_hours,
        )
        print(f"Accepted baseline: {payload['status']} -> {payload['accepted_snapshot_path']}")
        return payload
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
